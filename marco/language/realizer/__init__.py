"""The only path from meaning to sentence.

    MARCO reasoning
      -> Meaning Graph        meaning.py       no language in it
      -> Utterance Intent     intent.py        why this is said
      -> Discourse Planner    discourse.py     what to say, what to omit
      -> Expression Selector  expression.py    which way of saying it fits here
      -> Grammar Realizer     grammar.py       particles, endings, inflection, order
      -> Surface Sentence
      -> Semantic Check       check.py         parse the sentence back; meaning unchanged?

``realize(meaning, intent, language)`` is called once per dialogue turn
(``reasoning_context.ReasoningContext.turn``). ``meaning`` is the turn result.
A turn the realizer can build a Meaning Graph for is realized, in the language
of the pack or of the companion that answered. Any other turn keeps the
sentence the engine built: the realizer never composes from a sentence.
Every realized clause passes the semantic check or is not emitted; when no
declared expression passes, the turn is held with the declared hold.
"""
import collections
import copy

from marco.language.realizer import discourse, expression, intent as intents, meaning as mg
from marco.language.realizer.check import Checker
from marco.language.realizer.grammar import ClauseRealizer, Grammar, RealizationError, finish_sentence
from marco.language.realizer.packs import Language, available, language as load_language, register, stem_of


class Realizer:
    """One realizer: its reports, its learned expressions, its context.

    ``overrides`` maps a language stem to replaced declarations (tests inject
    faults this way). ``learning`` turns on expression learning from observed
    user sentences (``learning.py``).
    """

    def __init__(self, *, context=None, overrides=None, learning=False):
        self.context = dict(context or {})
        self.overrides = dict(overrides or {})
        self._languages = {}
        self._models = {}
        self._conversation = None
        self.reports = collections.deque(maxlen=500)
        self.learning = None
        if learning:
            from marco.language.realizer.learning import LearnedExpressions
            self.learning = LearnedExpressions(self)

    # languages ------------------------------------------------------------
    def language(self, stem):
        if stem in self.overrides:
            if stem not in self._languages:
                self._languages[stem] = Language(stem, self.overrides[stem])
            return self._languages[stem]
        return load_language(stem, self._models.get(stem))

    def learned(self, stem):
        return self.learning.candidates(stem, self._conversation) if self.learning else []

    def _learning_declared(self, stem):
        """Live learning runs only where the language's realizer file declares it."""
        return bool(((self.language(stem).decl.get("learning") or {}).get("live")))

    # entry points -----------------------------------------------------------
    def realize(self, meaning, intent, language) -> str:
        text, _report = self.realize_with_report(meaning, intent, language)
        return text

    def realize_with_report(self, result, intent, language):
        model = language if hasattr(language, "parser") else None
        speaker = stem_of(language)
        if model is not None and speaker:
            register(speaker, model)
        # The conversation's own language (its words); a companion model speaks the reply.
        said_in = (result.get("meaning") or {}).get("conversation_language") if isinstance(
            result.get("meaning"), dict) else None
        source = stem_of(said_in) if said_in else speaker
        block = result.get("meaning") if isinstance(result.get("meaning"), dict) else {}
        # What the turn meant, whatever is said of it (request L1-2 item 3): the trace can say
        # what was held and why even when its caller has no engine meaning.
        report = {"realized": False, "intent": intent, "source": source,
                  "meaning": {"act": block.get("act"), "reason": block.get("reason")}}
        if not available(source, model if source == speaker else None):
            report["reason"] = "no_declarations"
            return self._passthrough(result, report)
        meaning = result.get("meaning") if isinstance(result.get("meaning"), dict) else {}
        self._conversation = meaning.get("conversation")
        text, report = self._realize(result, report, source, model)
        if self.learning is None and self._learning_declared(source):
            from marco.language.realizer.learning import LearnedExpressions
            self.learning = LearnedExpressions(self)
        if self.learning is not None:
            # Learned after the turn is said: a sentence never confirms itself.
            report["learned"] = [c["id"] for c in self.learning.observe(result, source)]
        return text, report

    def _realize(self, result, report, source, model):
        graph = mg.build(result, source)
        report["language"] = graph["answer_language"]
        if graph["answer_language"] != source and not available(
                graph["answer_language"], model if stem_of(model) == graph["answer_language"] else None):
            report["reason"] = "no_declarations"
            return self._passthrough(result, report)
        if model is not None:
            self._models[stem_of(model)] = model
        if not intents.plan(graph):
            report["reason"] = "no_plan"
            return self._passthrough(result, report)
        report["plan"] = graph.get("plan_match")
        text, detail = self.realize_graph(graph, graph["answer_language"])
        report.update(detail)
        report["realized"] = True
        self.reports.append(report)
        return text, report

    def _passthrough(self, result, report):
        self.reports.append(report)
        return result.get("answer"), report

    def build_graph(self, result, language):
        """The Meaning Graph of a turn result with its acts planned, or None."""
        graph = mg.build(result, stem_of(language))
        return graph if intents.plan(graph) else None

    # realization ----------------------------------------------------------
    def realize_graph(self, graph, target):
        lang = self.language(target)
        grammar = Grammar(lang)
        factory = lambda: ClauseRealizer(grammar)
        checker = Checker(lang, grammar, factory)
        register = self.context.get("register") or lang.decl.get("register", {}).get("default")
        sentences, counts = discourse.plan(graph)
        separator = grammar.ortho["word_separator"]
        texts, clauses_report = [], []
        frames = mg.meaning_declarations()["frames"]
        for sentence in sentences:
            if sentence.get("options"):
                said = self._options(lang, grammar, checker, sentence, register, frames, clauses_report)
                if said is None:
                    return self._hold(lang, grammar, checker, register, counts, clauses_report)
                texts.append(said)
                continue
            parts = []
            coordination = lang.decl.get("coordination", {}).get(sentence["clauses"][0]["prop"]["frame"], {})
            prefer = None
            for index, planned in enumerate(sentence["clauses"]):
                last = index == len(sentence["clauses"]) - 1
                # A clause before the last of a coordination says no predicate (gapped), or says
                # its verb with the declared joining ending.
                gap = (coordination.get("verb_joint") or True) if coordination.get("gap_predicate") and not last \
                    else False
                subordinate = planned["prop"].get("subordinate")
                if subordinate and (lang.decl.get("ellipsis") or {}).get("subordinate") == "full":
                    # A language whose answers are fragments says a clause with a time clause in full.
                    planned = dict(planned, elided=set())
                chosen = self._clause(lang, grammar, checker, planned, sentence["sentence"], register,
                                      gap=gap, frames=frames, prefer=prefer)
                if chosen["clause"] is None and planned["prop"].get("alternative"):
                    # The same meaning in its plainer frame (a count of zero said in digits).
                    clauses_report.append(dict(chosen["report"], replaced=True))
                    planned = dict(planned, prop=planned["prop"]["alternative"])
                    chosen = self._clause(lang, grammar, checker, planned, sentence["sentence"], register,
                                          gap=gap, frames=frames, prefer=prefer)
                prefer = chosen["report"].get("candidate")
                clauses_report.append(chosen["report"])
                if chosen["clause"] is None:
                    if planned["prop"].get("optional"):
                        # A clause the plan marks optional is left out when the language cannot say it.
                        chosen["report"]["omitted"] = True
                        continue
                    return self._hold(lang, grammar, checker, register, counts, clauses_report)
                said = chosen["clause"].text(separator)
                if subordinate:
                    said = self._with_subordinate(lang, grammar, checker, subordinate, said, register, frames,
                                                  planned["act"], clauses_report)
                    if said is None:
                        return self._hold(lang, grammar, checker, register, counts, clauses_report)
                parts.append(said)
            if not parts:
                continue
            if len(parts) > 1:
                if coordination.get("separator") == "list" and grammar.ortho.get("list_last"):
                    body = grammar.ortho["list_separator"].join(parts[:-1]) + grammar.ortho["list_last"] + parts[-1]
                else:
                    joint = grammar.symbol(coordination.get("separator", "comma")) + separator
                    body = joint.join(parts)
            else:
                body = parts[0]
            if sentence.get("lead"):
                lead = self._lead(lang, grammar, checker, sentence["lead"], register,
                                  polarity=sentence.get("polarity", True))
                if lead is None and not sentence.get("lead_optional"):
                    return self._hold(lang, grammar, checker, register, counts, clauses_report)
                if lead is not None:
                    body = lead + separator + body
            texts.append(finish_sentence(grammar, body, sentence["sentence"]))
        text = grammar.ortho["sentence_separator"].join(texts)
        trace = {"meaning": [{"id": p["id"], "frame": p["frame"], "polarity": p.get("polarity", True)}
                             for p in graph["props"]],
                 "intent": [act["intent"] for act in graph["acts"]],
                 "discourse": [{"act": s["act"], "props": [c["prop"]["id"] for c in s["clauses"]],
                                "elided": [sorted(c["elided"]) for c in s["clauses"]]} for s in sentences],
                 "expression": [c["candidate"] for c in clauses_report if not c.get("omitted") and not c.get("replaced")],
                 "grammar": [c["pieces"] for c in clauses_report if not c.get("omitted") and not c.get("replaced")],
                 "check": [c["parse"] for c in clauses_report if not c.get("omitted") and not c.get("replaced")],
                 # Said in words in the reply; named by id here.
                 "rules": [(p["roles"].get(frames.get(p["frame"], {}).get("select_by", {}).get("role")) or {}).get("id")
                           for p in graph["props"] if frames.get(p["frame"], {}).get("select_by")],
                 # Every repair the turn rests on, in full (rule, operations, cost), whether said or not.
                 "repairs": [{key: report.get(key) for key in mg.meaning_declarations()["frames"][
                     mg.meaning_declarations()["repair_notes"]["full_frame"]]["roles"] if key in report}
                     for report in graph.get("repairs") or []]}
        return text, {"held": False, "clauses": clauses_report, "discourse": counts,
                      "acts": [act["intent"] for act in graph["acts"]], "text": text, "trace": trace}

    def _clause(self, lang, grammar, checker, planned, sentence, register, *, gap, frames, prefer=None,
                tense=None):
        prop = planned["prop"]
        elided_answer = {r for r in planned["elided"] if prop.get("answer")}
        attempts = []
        pool = expression.candidates(lang.decl, prop, register=register, intent=planned["act"],
                                     learned=self.learned(lang.stem), prefer=prefer)
        for candidate in pool:
            keep = set(candidate.get("keep", []))
            elided = {r for r in planned["elided"] if not (r in keep and r in elided_answer)}
            try:
                clause = ClauseRealizer(grammar).realize(prop, candidate, elided=elided, sentence=sentence,
                                                         register=register, gap=gap, tense=tense)
                verdict = checker.check(prop, candidate, clause, elided=elided, sentence=sentence,
                                        register=register, frame_decl=frames.get(prop["frame"]),
                                        allow_repair=bool(candidate.get("learned")), tense=tense, gap=gap)
            except RealizationError as exc:
                attempts.append({"candidate": candidate.get("id"), "error": str(exc)})
                continue
            attempts.append({"candidate": candidate.get("id"), "check": verdict})
            if verdict["ok"]:
                return {"clause": clause, "report": {"frame": prop["frame"], "prop": prop.get("id"),
                                                     "candidate": candidate.get("id"),
                                                     "pieces": clause.pieces(),
                                                     "text": clause.text(grammar.ortho["word_separator"]),
                                                     "learned": bool(candidate.get("learned")),
                                                     "elided": sorted(elided), "parse": verdict["parse"],
                                                     "attempts": attempts}}
        return {"clause": None, "report": {"frame": prop["frame"], "prop": prop.get("id"), "candidate": None,
                                           "attempts": attempts, "blocked": True}}

    def _lead(self, lang, grammar, checker, lead, register, polarity=True):
        """A word before the sentence (``now``; a yes or no). A lead declared with a polarity
        answers yes or no: it is said only before a sentence of that polarity, and the check reads
        its polarity back (the pack's negation, or the pack's own answer words). Any other lead
        carries no number and no negation."""
        spec = lang.decl.get("leads", {}).get(lead)
        parts = spec.get("parts") if isinstance(spec, dict) else spec
        if not parts:
            return None
        answers = spec.get("polarity") if isinstance(spec, dict) else None
        if answers is not None and answers != polarity:
            return None
        clause = ClauseRealizer(grammar).realize({"roles": {}, "polarity": True}, {"parts": parts}, register=register)
        words = ["".join(w["pieces"]) for w in clause.words]
        if checker.numbers(grammar.ortho["word_separator"].join(words)):
            return None
        if answers is None:
            if checker.negated(words):
                return None
        elif checker.answer_polarity(words) != answers:
            return None
        text = clause.text(grammar.ortho["word_separator"])
        if isinstance(spec, dict) and spec.get("join"):
            text += grammar.symbol(spec["join"])
        return text

    def _with_subordinate(self, lang, grammar, checker, subordinate, main, register, frames, act, clauses_report):
        """``main`` with the clause of the event it is relative to (before or after it), as the
        language declares that order: the event clause's sentence form and tense, the words
        before and after it, and the joint to the main clause. Each event clause passes the
        semantic check like any other; a language that does not declare the order says nothing."""
        spec = (lang.decl.get("subordinate") or {}).get(subordinate.get("order"))
        if not spec:
            return None
        separator = grammar.ortho["word_separator"]
        elide = set(mg.meaning_declarations()["time_event"].get("elide", []))
        texts = []
        for prop in subordinate.get("props") or []:
            planned = {"prop": prop, "elided": {role for role in elide if role in prop.get("roles", {})}, "act": act}
            chosen = self._clause(lang, grammar, checker, planned, spec.get("sentence", "declarative"), register,
                                  gap=False, frames=frames, tense=spec.get("tense"),
                                  prefer=(spec.get("prefer") or {}).get(prop["frame"]))
            chosen["report"]["subordinate"] = subordinate.get("order")
            clauses_report.append(chosen["report"])
            if chosen["clause"] is None:
                return None
            texts.append(chosen["clause"].text(separator))
        if not texts:
            return None
        words = []
        for key in ("open", "close"):
            clause = ClauseRealizer(grammar).realize({"roles": {}, "polarity": True}, {"parts": spec.get(key) or []},
                                                     register=register)
            said = [("".join(w["pieces"])) for w in clause.words]
            if checker.numbers(separator.join(said)) or checker.negated(said):
                return None
            words.append(clause.text(separator))
        opening, closing = words
        event = separator.join(part for part in (opening, separator.join(texts), closing) if part)
        joint = grammar.symbol(spec["join"]) if spec.get("join") else ""
        return event + joint + separator + main

    def _options(self, lang, grammar, checker, sentence, register, frames, clauses_report):
        """One question offering each clause as a choice (did you mean A, or B?), as the language
        declares it (``options``): each option clause in the declared sentence form, then the words
        after each option, the words between two, and the words before the first. Every option
        passes the semantic check like any clause; the declared words carry no number and no
        negation. A language that declares no options says none (the turn is held)."""
        spec = lang.decl.get("options")
        if not spec:
            return None
        separator = grammar.ortho["word_separator"]

        def words(parts):
            try:
                clause = ClauseRealizer(grammar).realize({"roles": {}, "polarity": True}, {"parts": parts or []},
                                                         sentence=sentence["sentence"], register=register)
            except RealizationError:
                return None
            said = ["".join(w["pieces"]) for w in clause.words]
            if checker.numbers(separator.join(said)) or checker.negated(said):
                return None
            return clause

        def joined(left, clause):
            if clause is None or not clause.words:
                return left
            text = clause.text(separator)
            return left + text if (clause.words[0]["bind"] or not left) else left + separator + text
        first, after, between = words(spec.get("first")), words(spec.get("after_each")), words(spec.get("between"))
        if None in (first, after, between):
            return None
        body = joined("", first)
        for index, planned in enumerate(sentence["clauses"]):
            chosen = self._clause(lang, grammar, checker, dict(planned, elided=set()), spec["sentence"], register,
                                  gap=False, frames=frames,
                                  prefer=(spec.get("prefer") or {}).get(planned["prop"]["frame"]))
            chosen["report"]["option"] = index
            clauses_report.append(chosen["report"])
            if chosen["clause"] is None:
                return None
            if index:
                body = joined(body, between)
            body = body + (separator if body else "") + chosen["clause"].text(separator)
            body = joined(body, after)
        return finish_sentence(grammar, body, sentence["sentence"])

    def _hold(self, lang, grammar, checker, register, counts, clauses_report):
        """No declared expression kept the meaning: say that the answer is held, nothing else.
        The report names the declared hold frame as its reason; the seam makes the turn a hold."""
        frame = mg.meaning_declarations()["hold"]["frames"][0]
        prop = {"frame": frame, "roles": {}, "polarity": True}
        text = None
        for candidate in lang.decl.get("expressions", {}).get(frame, []):
            try:
                clause = ClauseRealizer(grammar).realize(prop, candidate, register=register)
            except RealizationError:
                continue
            verdict = checker.check(prop, candidate, clause, elided=(), sentence="declarative",
                                    register=register, frame_decl={})
            text = finish_sentence(grammar, clause.text(grammar.ortho["word_separator"]), "declarative")
            if verdict["ok"]:
                break
        return text or "", {"held": True, "reason": frame, "clauses": clauses_report, "discourse": counts,
                            "text": text}


_default = Realizer()


def default_realizer():
    return _default


def realize(meaning, intent, language) -> str:
    """Return the sentence for ``meaning``.

    ``meaning``: the turn result. ``intent``: the turn's status (``answered``,
    ``unresolved``, ...). ``language``: the language pack path, such as
    ``styles/english.json``, or ``None`` when the dialogue uses the declared default.
    """
    return _default.realize(meaning, intent, language)


def last_report():
    return copy.deepcopy(_default.reports[-1]) if _default.reports else None


def follow_up(text, language):
    """Which declared follow-up about the conversation's own replies ``text`` is, or None.

    A language file lists them under ``follow_ups`` by kind (``why_last``: why the last
    answer or correction came out so; ``repairs``: what a reading changed). Only the
    listed phrasings count, compared after the language's own punctuation and case.
    """
    stem = stem_of(language)
    if not available(stem, language if hasattr(language, "parser") else None):
        return None
    decl = load_language(stem, language if hasattr(language, "parser") else None).decl
    marks = "".join(decl["orthography"]["punctuation"].values())
    separator = decl["orthography"]["word_separator"]

    def plain(value):
        return separator.join(str(value).strip().strip(marks).lower().split())
    said = plain(text)
    for kind, phrasings in (decl.get("follow_ups") or {}).items():
        if not kind.startswith("_") and said in {plain(p) for p in phrasings}:
            return kind
    return None
