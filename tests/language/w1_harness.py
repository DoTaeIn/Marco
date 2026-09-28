"""Test harness for the realizer (goal W1).

``w1_1_fields()`` attaches to each turn result the ``meaning`` block that
``docs/requests/W1-1.md`` asks ``reasoning_context.py`` to attach. It wraps the
engine's own methods inside a test only; the engine file is not edited. The
values are computed the way each engine method computes the sentence it
builds, so a test run under it shows what the live dialogue does once W1-1 is
applied.

``play()`` runs one dialogue and returns every turn's result with the
realizer's report.
"""
import contextlib
import copy

import marco.reasoning.context as reasoning_context
from marco.reasoning.context import ReasoningContext


def _premise(parser, queries, facts):
    """(subject, relation) of the first missing premise, found as ``_missing_premise`` finds it."""
    names = parser.data.get("relation_names", {})
    known = set()
    for item in facts:
        subject = item.get("triple", [None])[0]
        if isinstance(subject, str):
            known.add(subject)
            known.add(subject.split()[0])
    for query in queries:
        triple = query.get("triple") if isinstance(query, dict) else None
        if not (isinstance(triple, list) and len(triple) == 3 and isinstance(triple[0], str)):
            continue
        subject, predicate = triple[0], triple[1]
        if subject.startswith(("?", "$")) or subject not in known or predicate not in names:
            continue
        if any(item.get("triple", [None, None])[1] == predicate
               and str(item["triple"][0]).split()[:len(subject.split())] == subject.split() for item in facts):
            continue
        return {"subject": subject, "relation": predicate}
    return None


# The pack's template slots, named as W1-1 asks the engine to name them.
SLOT_FIELDS = {"말": "said", "목록": "items", "자리": "role", "정한값": "declared", "온값": "given", "남은": "rest",
               "물음": "question", "몸통": "body", "범위": "scope", "값": "value", "원문": "source", "규칙": "rule",
               "수선": "operations", "비용": "cost", "한도": "bound", "읽음": "reading"}


def _template_hold(replies, answer):
    """(key, fields) of the pack reply that produced ``answer``, as W1-1 item 7 would carry them."""
    import re
    for key, template in replies.items():
        if not isinstance(template, str):
            continue
        names = []

        def slot(match):
            name = match.group(1)
            if name in names:
                return "(?P=s%d)" % names.index(name)
            names.append(name)
            return "(?P<s%d>.*?)" % (len(names) - 1)
        pattern = re.sub(r"\\\{([^}]+)\\\}", slot, re.escape(template))
        found = re.fullmatch(pattern, answer, re.S)
        if found:
            return key, {SLOT_FIELDS.get(name, name): found.group("s%d" % index) for index, name in enumerate(names)}
    return None, None


def _other_than(context, parser, request, facts):
    excluded = request["excluded"]
    pointers = set(parser.pointers or [])
    people = sorted({str(item["triple"][0]).split()[0] for item in facts
                     if isinstance(item.get("triple", [None])[0], str) and len(str(item["triple"][0]).split()) > 1})
    fields = {"word": request["excluded"]}
    if excluded in pointers:
        if isinstance(context.last_subject, str) and context.last_subject in people and len(context.last_mentioned) <= 1:
            excluded = context.last_subject
        else:
            fields["candidates"] = [name for name in (context.last_mentioned or people) if name in people]
            return fields
    others = [name for name in people if name != excluded]
    fields.update({"excluded": excluded, "candidates": others})
    if len(others) == 1:
        fields["other"] = others[0]
    return fields


@contextlib.contextmanager
def w1_1_fields():
    """Turn results carry ``meaning`` as W1-1 requests, for the duration of the block."""
    originals = {name: ReasoningContext.__dict__[name] for name in
                 ("_missing_premise", "_turn", "_turn_reply", "_companion_turn", "_explain_last",
                  "_answer_other_than", "_correct_by_reference")}
    premises = {}
    missing_premise = originals["_missing_premise"].__func__

    def _missing(parser, queries, facts):
        text = missing_premise(parser, queries, facts)
        if text:
            found = _premise(parser, queries, facts)
            if found:
                premises[text] = found
        return text

    def _turn(self, text, knowledge_path=None):
        result = originals["_turn"](self, text, knowledge_path)
        if result is None or "meaning" in result:
            return result
        answer = result.get("answer")
        if result.get("status") == "unresolved" and answer in premises:
            return {**result, "meaning": {"act": "refuse", "reason": "premise_missing", **premises[answer]}}
        if result.get("status") == "answered":
            return {**result, "meaning": {"act": "inform"}}
        if result.get("status") == "unresolved":
            key, values = _template_hold(self._parser().data.get("context_replies", {}), answer or "")
            if key is not None:
                return {**result, "meaning": {"act": "hold", "reason": key, **values}}
        if result.get("status") == "observed" and not any(
                row.get("operation") == "correction" for row in result.get("transitions", [])):
            parser = self._parser()
            replies = parser.data.get("context_replies", {})
            this_turn = [row for row in result.get("transitions", [])
                         if (row.get("evidence") or {}).get("turn") == len(self.observations) - 1]
            spoken = parser.render_changes(this_turn)
            if spoken and "observed_state" in replies and answer == replies["observed_state"].format(**{"목록": spoken}):
                return {**result, "meaning": {"act": "record", "reason": "observed_state",
                                              "turn": len(self.observations) - 1, "changes": this_turn}}
        return result

    def _companion(self, parser, text, knowledge_path):
        result = originals["_companion_turn"](self, parser, text, knowledge_path)
        if result is None or "meaning" in result:
            return result
        language = next((c.get("language") for c in result.get("verification", {}).get("checks", [])
                         if c.get("language")), None)
        if result.get("status") == "unresolved" and result.get("answer") in premises:
            return {**result, "meaning": {"act": "refuse", "reason": "premise_missing",
                                          "answer_language": language, **premises[result["answer"]]}}
        return result

    def _explain(self, parser, knowledge_path):
        last = copy.deepcopy(self.last_explanation)
        result = originals["_explain_last"](self, parser, knowledge_path)
        if result.get("status") != "answered" or not last:
            return result
        rule_names = parser.data.get("rule_names", {})
        updates = parser.data.get("numeric_updates", {})
        transitions = last["transitions"]
        evidence, rules = [], []
        for row in transitions:
            source = ((row.get("evidence") or {}).get("source") or (row.get("evidence") or {}).get("text") or "").strip()
            if source and source not in evidence:
                evidence.append(source)
        for source in evidence:
            parsed = self._read_source(parser, source, events=True,
                                       verbs=self._verbs_for(parser, self.observations)) or {}
            for fact in parsed.get("facts", []):
                name = fact["triple"][1]
                if name in updates and name in rule_names and name not in rules:
                    rules.append(name)
        fields = {"act": "explain", "kind": last["kind"], "question": last.get("question"),
                  "evidence": evidence, "rules": rules,
                  "changes": [row for row in transitions if row.get("operation") == "quantity_update"],
                  "repairs": [{"source": r["source"], "reading": r["reading"]}
                              for r in ReasoningContext._repairs_under(transitions)]}
        if last["kind"] == "correction":
            record = last["correction"]
            fields["correction"] = {"utterance": record.get("utterance", ""), "before": record["before"].strip(),
                                    "after": record["after"].strip(), "old": record["reference"]["old"],
                                    "new": record["reference"]["new"]}
        return {**result, "meaning": fields}

    def _other(self, parser, request, facts, knowledge_path):
        fields = _other_than(self, parser, request, facts)
        result = originals["_answer_other_than"](self, parser, request, facts, knowledge_path)
        reason = result["verification"]["checks"][-1]["reason"]
        return {**result, "meaning": {"act": "ask", "reason": reason, **fields}}

    def _correct(self, parser, request, text, knowledge_path):
        before = len(self.corrections)
        result = originals["_correct_by_reference"](self, parser, request, text, knowledge_path)
        if result.get("status") == "observed" and len(self.corrections) > before:
            record = self.corrections[-1]
            index = record["index"]
            changes = [row for row in result.get("transitions", []) if row.get("operation") == "quantity_update"
                       and (row.get("evidence") or {}).get("turn", index) == index]
            return {**result, "meaning": {"act": "correct", "event": record["before"].strip(),
                                          "old": record["reference"]["old"], "new": record["reference"]["new"],
                                          "new_event": False, "changes": changes}}
        return result

    def _turn_reply(self, text, knowledge_path=None):
        result = originals["_turn_reply"](self, text, knowledge_path)
        if (result is not None and "meaning" not in result and result.get("status") == "unresolved"
                and any(r.get("status") == "over_bound" for r in result.get("repair") or [])):
            return {**result, "meaning": {"act": "hold", "reason": "repair_over_bound"}}
        return result

    ReasoningContext._turn_reply = _turn_reply
    ReasoningContext._missing_premise = staticmethod(_missing)
    ReasoningContext._turn = _turn
    ReasoningContext._companion_turn = _companion
    ReasoningContext._explain_last = _explain
    ReasoningContext._answer_other_than = _other
    ReasoningContext._correct_by_reference = _correct
    try:
        yield premises
    finally:
        for name, original in originals.items():
            setattr(ReasoningContext, name, original)


@contextlib.contextmanager
def realizer_in_dialogue(realizer):
    """The dialogue's one ``realize`` call goes to ``realizer``."""
    saved = reasoning_context.realize
    reasoning_context.realize = realizer.realize
    try:
        yield realizer
    finally:
        reasoning_context.realize = saved


def play(language, turns, *, companion=None, realizer=None, fields=True):
    """Run one dialogue. Returns [(input, result, realizer report)]."""
    from pack_model import development_model
    from marco.language.realizer import Realizer
    realizer = realizer or Realizer()
    companions = [development_model(companion)] if companion else []
    context = ReasoningContext(model=development_model(language), companions=companions)
    rows = []
    stack = contextlib.ExitStack()
    with stack:
        if fields:
            stack.enter_context(w1_1_fields())
        stack.enter_context(realizer_in_dialogue(realizer))
        for text in turns:
            before = len(realizer.reports)
            result = context.turn(text)
            report = realizer.reports[-1] if len(realizer.reports) > before else None
            rows.append((text, result, report))
    return rows, context
