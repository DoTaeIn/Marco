"""Semantic Check: parse the realized clause back with the same pack; meaning unchanged?

Independent readers, all from the language pack, none from the expression
that produced the clause:

* numbers — digits and the pack's numerals, outside quotations and citations,
  must be exactly the proposition's overt numbers; cited numbers exactly the
  cited ones;
* polarity — the pack's negation marker must occur in the clause's own words
  exactly when the proposition is negative;
* quotations — every quoted span must be a value the proposition quotes;
* reading — for frames with a declared reading, the same clause said in full
  (every role, the parser's own register) is parsed by the pack parser, and
  its facts or event roles must give back the proposition's roles, numbers
  and polarity;
* ellipsis — the clause as said must be the full clause with pieces removed
  and nothing added.

A clause that fails any reader is never emitted.
"""
import re

from numeral_semantics import parse_numeral

_DIGITS = re.compile(r"\d+")


def meaning_declarations():
    from marco.language.realizer.packs import meaning_declarations as declared
    return declared()


def _quoted_fields():
    return set(meaning_declarations()["quoted_fields"]["fields"])


QUOTED_FIELDS = _quoted_fields()


def _quoted_strings(value, out):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in QUOTED_FIELDS:
                if isinstance(item, str):
                    out.add(item)
            _quoted_strings(item, out)
    elif isinstance(value, list):
        for item in value:
            _quoted_strings(item, out)
    return out


class Checker:
    def __init__(self, language, grammar, clause_realizer_factory):
        self.lang = language
        self.g = grammar
        self.make = clause_realizer_factory

    # readers ------------------------------------------------------------
    def numbers(self, text):
        """Digits, and numeral words; where the language counts with counters, a
        numeral word is a number only when a declared counter follows it."""
        found = [int(m) for m in _DIGITS.findall(text)]
        tokens = [token.strip("".join(self._marks())) for token in text.split()]
        counters = [spec["form"] for spec in self.g.decl.get("counters", {}).values()]
        unit = self.g.question_counter(self._prop) if getattr(self, "_prop", None) else None
        if unit:
            counters.append(unit)
        needs_counter = bool((self.g.decl.get("numbers") or {}).get("words_need_counter"))
        for index, core in enumerate(tokens):
            if core and not _DIGITS.search(core):
                value = parse_numeral(core, self.lang.numerals)
                if value is None:
                    continue
                following = tokens[index + 1] if index + 1 < len(tokens) else ""
                if needs_counter and not any(following.startswith(form) for form in counters):
                    continue
                found.append(int(value))
        return sorted(found)

    def _marks(self):
        marks = set()
        for pair in self.g.ortho.get("quotes", {}).values():
            marks.update(pair)
        marks.update(self.g.ortho.get("punctuation", {}).values())
        marks.update(self.g.ortho.get("symbols", {}).get(name, "") for name in ("comma",))
        return marks

    def negated(self, words):
        """Whether the words carry the pack's negation: its marker pattern, or a
        form of its declared negation verb. ``None`` when the pack declares neither."""
        # The model's own component first (request W1-3 part 2); the loose pack
        # file only when the model carries no marker.
        declared = (getattr(self.lang.parser, "language_pack", None) or {}).get("negation_marker")
        marker = re.compile(declared) if isinstance(declared, str) and declared else self.lang.negation_marker
        forms = set((self.lang.parser.negation or {}).get("forms", ()))
        if marker is None and not forms:
            return None
        return any((marker is not None and marker.match(word)) or word in forms for word in words)

    # the check ------------------------------------------------------------
    def answer_polarity(self, words):
        """The polarity of a yes or no word, read from the pack alone: False for the pack's
        negation, or for the first word of the pack's own answer that two counts differ
        (``comparison_answers.different``); True for the first word of its answer that they are
        the same; None for anything else."""
        marks = "".join(self._marks())
        said = self.g.ortho["word_separator"].join(str(word).strip().strip(marks).lower() for word in words).strip()
        answers = (getattr(self.lang.parser, "data", None) or {}).get("comparison_answers") or {}

        def first(render):
            if not isinstance(render, list) or not render or not isinstance(render[0], str) \
                    or render[0].startswith(tuple(meaning_declarations().get("variable_marks", ()))):
                return None
            return render[0].strip().strip(marks).lower() or None
        if said and said == first(answers.get("different")):
            return False
        if said and said == first(answers.get("same")):
            return True
        if self.negated(list(words)):
            return False
        return None

    def check(self, prop, candidate, clause, *, elided, sentence, register, allow_repair=False,
              frame_decl=None, tense=None):
        failures = []
        self._prop = prop
        separator = self.g.ortho["word_separator"]
        frame_decl = frame_decl or {}
        plain = [w for w in clause.words if not w["quoted"] and not w["cited"]]
        overt_text = separator.join("".join(w["pieces"]) for w in plain)
        expected = sorted(int(prop["roles"][role]["number"]) for role in frame_decl.get("numbers", [])
                          if role in prop["roles"] and role not in elided)
        said = self.numbers(overt_text)
        if said != expected:
            failures.append({"reader": "quantities", "said": said, "meant": expected})
        cited_expected = sorted(int(prop["roles"][role]["number"]) for role in frame_decl.get("cited", [])
                                if role in prop["roles"])
        cited_said = sorted(int(n) for w in clause.words for n in w.get("cited_numbers", []))
        if cited_said != cited_expected:
            failures.append({"reader": "cited_numbers", "said": cited_said, "meant": cited_expected})
        own_words = ["".join(w["pieces"]) for w in plain if w["kind"] not in ("np", "num", "counter")]
        negated = self.negated(own_words)
        if negated is None and prop.get("polarity", True) is False:
            failures.append({"reader": "polarity", "said": "unreadable", "meant": "negative"})
        if negated is not None and negated != (prop.get("polarity", True) is False):
            failures.append({"reader": "polarity", "said": "negative" if negated else "positive",
                             "meant": "negative" if prop.get("polarity", True) is False else "positive"})
        allowed = _quoted_strings(prop.get("roles", {}), set())
        for value in prop.get("roles", {}).values():
            for item in (value.get("list", []) if isinstance(value, dict) else []):
                if isinstance(item, dict) and "text" in item:
                    allowed.add(self.g.ortho["word_separator"].join(self.g.entity_words(item)))
        opening_closing = list(self.g.ortho.get("quotes", {}).values())
        for word in clause.words:
            if word["kind"] not in ("quote", "list", "cite", "operation"):
                continue
            text = "".join(word["pieces"])
            # Spans that quote an allowed value are taken out first, so a mark inside a
            # quotation (an apostrophe in "Milo's") never pairs with a mark outside it.
            changed = True
            while changed:
                changed = False
                for opening, closing in opening_closing:
                    for inner in re.findall(re.escape(opening) + "(.*?)" + re.escape(closing), text):
                        if inner in allowed:
                            text = text.replace(opening + inner + closing, separator, 1)
                            changed = True
            for opening, closing in opening_closing:
                for inner in re.findall(re.escape(opening) + "(.*?)" + re.escape(closing), text):
                    if inner not in allowed:
                        failures.append({"reader": "quotes", "said": inner})
        full = self.make().realize(prop, candidate, elided=(), sentence=sentence, register=register, tense=tense)
        canon = self.g.canonical_piece
        if not _subsequence(clause.pieces(canon), full.pieces(canon)):
            failures.append({"reader": "ellipsis", "said": clause.pieces(), "full": full.pieces()})
        reading = self.g.decl.get("readings", {}).get(prop["frame"])
        parse = "not_declared"
        repaired = False
        if reading:
            reading_prop = prop
            if reading.get("default_counter"):
                # A counter classifies what is counted and carries no amount; the pack
                # reads counts in its declared counter, so the reading uses that one.
                reading_prop = {key: value for key, value in prop.items() if key != "question_render"}
            restated = self.make().realize(reading_prop, candidate, elided=(), sentence="declarative",
                                           register="reading")
            from marco.language.realizer.grammar import finish_sentence
            text = finish_sentence(self.g, restated.text(separator), "declarative")
            parsed = self.lang.parser.parse(text, partial=True, events=True, repair=allow_repair)
            problem = self._reading(reading, parsed, prop)
            parse = "parsed" if problem is None else "mismatch"
            repaired = bool(parsed and any((f.get("evidence") or {}).get("normalization", {}).get("repair")
                                           for f in parsed.get("facts", [])))
            if problem is not None:
                failures.append({"reader": "parse", "text": text, "problem": problem})
        return {"ok": not failures, "failures": failures, "parse": parse, "repaired": repaired}

    # reading rules --------------------------------------------------------
    def _expected_words(self, prop, roles):
        words = []
        for role in roles:
            value = prop["roles"].get(role)
            if value is None:
                continue
            words.extend(self.g.entity_words(value))
        return words

    def _keyed_subjects(self, prop, spec):
        """The subject words the pack's reading may give back for this fact.

        The recorded words; and, when the fact counts one, the same words with the
        counted thing's head in the plural the pack declares — the pack keys "one X"
        on X's plural (``명사수``), so a word it can only inflect by rule (a name of
        a thing in another script) comes back in that plural. Nothing else is
        accepted."""
        words = self._expected_words(prop, spec["subject"])
        keyed = [words]
        value = prop["roles"].get(spec.get("object")) or {}
        declared = self.g.declared_number()
        if not declared or "number" not in value or not self.g.is_one(value["number"]):
            return keyed
        item = self._expected_words(prop, spec["subject"][-1:])
        if not item or len(item) > len(words):
            return keyed
        head = next((item.index(marker) - 1 for marker in declared.get("partitive", [])
                     if marker in item[1:]), len(item) - 1)
        many = self.g.plural_of(item[head])
        if many and many != item[head]:
            start = len(words) - len(item)
            keyed.append(words[:start + head] + [many] + words[start + head + 1:])
        return keyed

    def same_words(self, said, meant):
        said, meant = str(said).split(), list(meant)
        if len(said) != len(meant):
            return False
        for a, b in zip(said, meant):
            if a == b:
                continue
            ca, cb = self.lang.concept(a), self.lang.concept(b)
            if ca and ca == cb:
                continue
            if a.lower() == b.lower():
                continue
            return False
        return True

    def _object_matches(self, value, said):
        if value is None:
            return False
        if "number" in value:
            return str(said) == str(value["number"])
        return self.same_words(said, self.g.entity_words(value))

    def _reading(self, reading, parsed, prop):
        if not parsed:
            return "unread"
        polarity = prop.get("polarity", True)
        problems = []
        for spec in reading.get("facts", []):
            facts = [f for f in parsed.get("facts", []) if (f.get("triple") or [None, None])[1] == spec["predicate"]]
            if not facts:
                problems.append("no_fact:%s" % spec["predicate"])
                continue
            keyed = self._keyed_subjects(prop, spec)
            match = [f for f in facts if any(self.same_words(f["triple"][0], words) for words in keyed)
                     and self._object_matches(prop["roles"].get(spec["object"]), f["triple"][2])
                     and f.get("polarity", True) == polarity]
            if not match:
                problems.append("fact_mismatch:%s:%s" % (spec["predicate"], [f["triple"] for f in facts]))
        if problems and reading.get("events"):
            event_problems = []
            for spec in reading["events"]:
                events = parsed.get(spec["key"], [])
                ok = False
                for event in events:
                    # The pack may read the roles in more than one way; the meaning
                    # must be one of the readings it offers.
                    readings = [event.get(spec["roles_key"], {})] + list(event.get(spec.get("candidates_key") or "", []))
                    for slots in readings:
                        if all(self._slot(slots, particle, prop, role) for role, particle in spec["roles"].items()):
                            ok = True
                if not ok:
                    event_problems.append("event_mismatch")
            if not event_problems:
                return None
            problems += event_problems
        return problems or None

    def _slot(self, slots, particle, prop, role):
        mates = self.lang.mates
        for key, text in slots.items():
            if key == particle or (mates.get(key) and mates.get(key) == mates.get(particle)):
                if self.same_words(text, self.g.entity_words(prop["roles"].get(role) or {})):
                    return True
        return False


def _subsequence(small, big):
    position = 0
    for piece in small:
        while position < len(big) and big[position] != piece:
            position += 1
        if position == len(big):
            return False
        position += 1
    return True
