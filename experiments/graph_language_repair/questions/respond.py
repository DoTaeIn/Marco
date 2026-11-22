"""Evaluation result + plan -> human-readable Korean text.

Which template renders which evidence state is a lookup into
``graphs/questions/scope_policy.json``; this module performs the lookup and
fills placeholders, it does not itself decide that e.g. ``scope_kind:
attribution`` means "tentative, with attribution" -- that mapping is data.
Particle attachment (가/이, 를/을, 는/은) is the one piece of generic
mechanics done in Python: it is deterministic Hangul-syllable arithmetic
(whether the last character of a span has a trailing consonant), not a
per-sentence or per-word choice, so it is not duplicated across every
template variant.
"""
import json
import os

from experiments.graph_language_repair.questions.compile import slot_value

_GRAPHS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "graphs", "questions")

_SUBJECT_PARTICLES = ("이", "가")   # (has_batchim, no_batchim)
_OBJECT_PARTICLES = ("을", "를")
_TOPIC_PARTICLES = ("은", "는")
_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3


def _load(name):
    with open(os.path.join(_GRAPHS_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def has_batchim(text):
    """True if ``text`` ends in a Hangul syllable with a trailing consonant.

    A non-Hangul-ending span (digits, Latin letters, punctuation) has no
    representable batchim here; it is treated as not having one, which
    picks the 가/를/는 forms -- a stated, deterministic default, not a
    guess about the word's pronunciation.
    """
    if not text:
        return False
    code = ord(text[-1])
    if not (_HANGUL_BASE <= code <= _HANGUL_LAST):
        return False
    return (code - _HANGUL_BASE) % 28 != 0


def particle(text, kind):
    table = {"subject": _SUBJECT_PARTICLES, "object": _OBJECT_PARTICLES,
             "topic": _TOPIC_PARTICLES}[kind]
    return table[0] if has_batchim(text) else table[1]


def phrase(text, kind):
    return text + particle(text, kind)


def _format_unresolved(item):
    reason = item["reason"]
    if reason == "missing_argument":
        return "missing_argument(cue=%s, missing=%s)" % (item["cue_id"], ",".join(item["missing"]))
    if reason == "ambiguous_argument":
        return "ambiguous_argument(cue=%s, function=%s, candidates=%s)" % (
            item["cue_id"], item["function"], ",".join(item["candidates"]))
    if reason == "ambiguous_intent":
        return "ambiguous_intent(candidates=%s)" % ",".join(item["candidates"])
    if reason == "ambiguous_role_question":
        return "ambiguous_role_question(candidates=%s)" % ",".join(item["candidates"])
    if reason in ("unrecognized_action", "ambiguous_action"):
        return "%s(candidates=%s)" % (reason, ",".join(item.get("candidates") or []))
    return reason


def _disclosure(plan, templates):
    items = plan.get("unresolved") or [{"reason": "unrepresentable"}]
    reason = ", ".join(_format_unresolved(item) for item in items)
    return templates["disclosure"].format(reason=reason)


def _build_context(result, plan):
    context = {"reason": result.get("reason") or ""}
    slots = plan.get("slots", {})
    subject_text, subject_status = slot_value(slots, "subject")
    if subject_status == "ok":
        context["actor_phrase"] = phrase(subject_text, "subject")
    object_text, object_status = slot_value(slots, "object")
    if object_status == "ok":
        context["object_phrase"] = phrase(object_text, "object")
    reporter_candidates = result.get("state", {}).get("reporter", [])
    if reporter_candidates:
        context["reporter_phrase"] = phrase(reporter_candidates[0]["value"], "subject")
    if result.get("case") == "reporter" and result.get("value"):
        context["reporter_phrase"] = phrase(result["value"], "subject")
    if result.get("case") == "answer":
        # raw_value, not value: value may have been overridden by a polarity
        # lookup (e.g. to the synthetic "event_negated") -- the display text
        # is always the literal fact value.
        answer_text = result.get("raw_value") or result.get("value")
        if answer_text:
            context["answer_phrase"] = answer_text
    return context


def render(result, plan):
    """Render ``result`` (from ``questions.select.execute_plan``) for ``plan``."""
    templates = _load("responses.json")["templates"]
    if result.get("gate") == "unresolved":
        return _disclosure(plan, templates)

    policy = _load("scope_policy.json")
    intent = result["intent"]

    gate = result.get("gate")
    if gate is not None:
        template_key = policy["gates"].get(intent, {}).get(gate)
        if template_key is None:
            return templates["disclosure"].format(reason=result.get("reason") or gate)
        context = _build_context(result, plan)
        context["reason"] = result.get("reason") or gate
        if gate == "multiple_answers":
            context["candidates"] = ", ".join(sorted({c["value"] for c in result["candidates"]}))
        return templates[template_key].format(**context)

    case, value = result["case"], result["value"]
    case_table = policy["by_case"].get(intent, {}).get(case, {})
    template_key = case_table.get(value) or case_table.get("any_value")
    if template_key is None:
        return templates["disclosure"].format(
            reason="unrecognized_value(case=%s, value=%s)" % (case, value))

    template_key = (policy.get("requested_polarity_templates", {})
                    .get(plan.get("required_polarity"), {}).get(template_key, template_key))
    context = _build_context(result, plan)
    scopes = {c["value"] for c in result.get("state", {}).get("scope", [])}
    if scopes & {"attribution", "reported_claim"}:
        template_key = policy.get("attributed_templates", {}).get(template_key, template_key)
        if template_key in policy.get("attributed_templates", {}).values() and not context.get("reporter_phrase"):
            context["reporter_phrase"] = "출처"
    fallback_key = policy.get("no_reporter_fallback", {}).get(template_key)
    if fallback_key and not context.get("reporter_phrase"):
        template_key = fallback_key
    return templates[template_key].format(**context)
