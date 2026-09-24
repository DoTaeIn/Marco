"""MARCO 1 usability gate: the frozen dialogue set and its scorer.

The dialogues in ``data/benchmarks/dialogues_v1/`` are the exam.  They were
written before the language realizer and are never used to tune it.  Each turn
carries its expected answer as a semantic structure (act, entity, quantity,
relation, evidence turns), never as a surface string, and one label from
``LABELS``.

Every dialogue is played through ``views.kgpack_ui.AppState.turn`` -- the call
behind the UI's ``POST /api/turn`` -- in its own conversation, with web research
stubbed and counted.  ``restart_before`` builds a new ``AppState`` over the same
saved conversation store.  The scorer reads the payload the UI receives:

* status from the trace verdict and ``known`` flag (see ``status``);
* the stated value from the answer text, with quoted, bracketed and
  parenthesised spans removed (they cite, they do not assert);
* evidence from the answered ``fact`` rows and the verification checks.

Gate number: turns labelled ``answerable``.  Correct means the stated value
matches, evidence is present, and no retracted evidence is used.  A hold, an
execution error and an unverifiable answer all count against it; they are
reported apart, never as correct.  Holds, ambiguous referents, unsupported
requests, corrections, "why" answers and statement turns are reported
separately.

Commands (``python bench/dialogue_gate.py <command>``):

  validate    F1.1  schema, counts, and an independent replay of every expectation
  categories  F1.2  category and variation tables
  overlap     F1.3  full-sentence overlap with tests/ bench/ cases/ data/ styles/
  run         F1.4  play all dialogues through the UI turn handler and score them
  score       F1.4  score a saved answers file
  hash        F1.7  print (or --write) the frozen directory hash
  baseline    F1.6  record the before number at the first main containing f985857

Every command takes ``--dataset <dir>`` to read another dialogue directory with
the same schema instead of the frozen set (default ``data/benchmarks/dialogues_v1``).
With it, ``overlap`` checks that directory against every corpus file outside it,
the frozen set included, and ``run`` hashes that directory, not the frozen one.

``--split <name>`` keeps only the dialogues a dataset's ``split.txt`` lists under
that name (a line ``<name> <id> <id> ...``). ``overlap`` takes ``--dataset`` more
than once and ``--files <path> ...`` to check those files instead of the corpus
directories. For the frozen set it prints counts per file only: its sentences
are never written to the terminal by a development run.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmarks/dialogues_v1"
FROZEN = DATASET / "FROZEN.sha256"
REPORT_DIR = ROOT / "docs/ko/dialogue-gate-2026-09-22"
BASELINE_COMMIT = "f985857"

SCHEMA = "marco1-dialogue-gate-v1"
LABELS = ("answerable", "hold", "unsupported", "ambiguous", "correction", "why")
CATEGORIES = ("ownership", "transfer", "follow_up", "missing_premise", "correction",
              "why", "ambiguous_referent", "restart")
LANGUAGES = {"ko": "한국어", "en": "english"}
VARIATION_KEYS = ("word_order", "register", "split", "correction_position", "roles")
OWNED = ("data/benchmarks/dialogues_v1/", "bench/dialogue_gate.py", "tests/test_dialogue_gate.py",
         "docs/ko/dialogue-gate-2026-09-22/")
CORPUS_DIRS = ("tests", "bench", "cases", "data", "styles")
BUCKETS = ("correct", "hold", "wrong", "execution_error", "unverifiable")

# Engine verdict vocabulary.  An unknown verdict falls back to the ``known`` flag.
OBSERVED = {"상태기억"}
HELD = {"조건부족", "입력이해실패", "근거불충분", "미지", "B2", "지식부족", "근거없음", "전제불성립"}
CHAT = {"대화"}


# ---------------------------------------------------------------------------
# dataset
# ---------------------------------------------------------------------------
def load(directory=DATASET, split=None):
    directory = Path(directory)
    dialogues = [json.loads(path.read_text(encoding="utf-8"))
                 for path in sorted(directory.glob("*.json"))]
    if split is None:
        return dialogues
    keep = set(split_ids(directory)[split])
    return [d for d in dialogues if d["id"] in keep]


def split_ids(directory):
    """``{name: [dialogue id, ...]}`` from the dataset's ``split.txt``."""
    path = Path(directory) / "split.txt"
    table = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, rest = line.partition(" ")
        if name and name != "seed":
            table[name] = rest.split()
    return table


def tree_hash(directory=DATASET):
    """SHA-256 over every non-hidden file except FROZEN.sha256: path, NUL, file hash."""
    directory = Path(directory)
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        if path.name == FROZEN.name or any(part.startswith(".") for part in Path(rel).parts):
            continue
        digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return digest.hexdigest()


def frozen_hash(path=FROZEN):
    return Path(path).read_text(encoding="utf-8").split()[0]


def _apply(state, event):
    kind = event["type"]
    if kind == "has":
        state[(event["holder"], event["item"])] = event["quantity"]
        return
    q = event["quantity"]
    if kind == "use":
        key = (event["holder"], event["item"])
        state[key] = None if state.get(key) is None else state[key] - q
    elif kind == "transfer":
        giver, taker = (event["from"], event["item"]), (event["to"], event["item"])
        state[giver] = None if state.get(giver) is None else state[giver] - q
        state[taker] = None if state.get(taker) is None else state[taker] + q
    else:
        raise ValueError("unknown event type %r" % kind)


def _replay(dialogue, upto, corrected=True):
    """State after turn ``upto``; corrections replace their target's events from their turn on."""
    turns, state = dialogue["turns"], {}
    replaced = {}
    if corrected:
        for turn in turns[:upto]:
            if turn["expect"]["act"] == "revise":
                replaced[turn["expect"]["target_turn"]] = turn["expect"]["with"]
    for turn in turns[:upto]:
        if turn["expect"]["act"] == "record":
            for event in replaced.get(turn["n"], turn["expect"]["events"]):
                _apply(state, event)
    return state


def validate(dialogues):
    """Return a list of problems; empty means F1.1 holds and every expectation replays."""
    problems = []
    ids = [d.get("id") for d in dialogues]
    if len(set(ids)) != len(ids):
        problems.append("duplicate ids")
    by_language = {code: sum(d.get("language") == code for d in dialogues) for code in LANGUAGES}
    if len(dialogues) < 50:
        problems.append("fewer than 50 dialogues: %d" % len(dialogues))
    for code in LANGUAGES:
        if by_language[code] < 20:
            problems.append("fewer than 20 %s dialogues: %d" % (code, by_language[code]))
    for d in dialogues:
        where = d.get("id")
        if d.get("schema") != SCHEMA:
            problems.append("%s: schema" % where)
        if d.get("language") not in LANGUAGES or not d.get("domain"):
            problems.append("%s: language/domain" % where)
        turns = d.get("turns") or []
        if not 4 <= len(turns) <= 10:
            problems.append("%s: %d turns" % (where, len(turns)))
        if [t.get("n") for t in turns] != list(range(1, len(turns) + 1)):
            problems.append("%s: turn numbering" % where)
        if sorted(d.get("categories", [])) != sorted({x for t in turns for x in t.get("tags", [])}):
            problems.append("%s: categories != union of turn tags" % where)
        corrections = 0
        for t in turns:
            at = "%s#%s" % (where, t.get("n"))
            e = t.get("expect") or {}
            if t.get("label") not in LABELS:
                problems.append("%s: label %r" % (at, t.get("label")))
            if not isinstance(t.get("say"), str) or not t["say"].strip():
                problems.append("%s: say" % at)
            for key in ("act", "entity", "quantity", "relation", "evidence"):
                if key not in e:
                    problems.append("%s: expect.%s missing" % (at, key))
            if any(key in e for key in ("answer", "text", "reply")):
                problems.append("%s: surface string in expectation" % at)
            ev = (e.get("evidence") or {}).get("turns")
            if not isinstance(ev, list) or any(not isinstance(n, int) or not 1 <= n <= t["n"] for n in ev):
                problems.append("%s: evidence turns" % at)
            act, label = e.get("act"), t.get("label")
            expected_label = {"record": "hold", "hold": "hold", "answer": "answerable", "clarify": "ambiguous",
                              "decline": "unsupported", "revise": "correction", "explain": "why"}.get(act)
            if expected_label != label:
                problems.append("%s: act %r with label %r" % (at, act, label))
            state = _replay(d, t["n"])
            if act in ("record", "revise"):
                for row in e.get("state", []):
                    if state.get((row["entity"], row["item"])) != row["quantity"]:
                        problems.append("%s: state %s/%s" % (at, row["entity"], row["item"]))
            if act == "revise":
                corrections += 1
                target = turns[e["target_turn"] - 1]
                if target["expect"]["act"] != "record" or len(target["expect"]["events"]) != 1:
                    problems.append("%s: correction target must be a one-event statement" % at)
                if target["expect"]["events"] != e["replaces"]:
                    problems.append("%s: replaces != target events" % at)
            if act == "answer":
                if e["relation"] in ("count", "total"):
                    names = e["entity"] if isinstance(e["entity"], list) else [e["entity"]]
                    values = [state.get((name, e["item"])) for name in names]
                    if None in values or sum(values) != e["quantity"]:
                        problems.append("%s: quantity does not replay" % at)
                    original = _replay(d, t["n"], corrected=False)
                    old = [original.get((name, e["item"])) for name in names]
                    if "retracted_quantity" in e and (None in old or sum(old) != e["retracted_quantity"]):
                        problems.append("%s: retracted quantity does not replay" % at)
                    for key in ("retracted_quantity", "reexecuted_quantity"):
                        if e.get(key) == e["quantity"]:
                            problems.append("%s: %s equals the answer" % (at, key))
                    if e["relation"] == "count":
                        others = [v for (h, i), v in state.items()
                                  if i == e["item"] and h != e["entity"] and v is not None]
                        if e["quantity"] in others:
                            problems.append("%s: another holder has the same value" % at)
                elif e["relation"] == "more":
                    a, b = e["candidates"]
                    va, vb = state.get((a, e["item"])), state.get((b, e["item"]))
                    if None in (va, vb) or e["entity"] != (a if va > vb else b):
                        problems.append("%s: 'more' does not replay" % at)
                else:
                    problems.append("%s: relation %r" % (at, e["relation"]))
            if act == "explain" and e.get("entity") is not None:
                if state.get((e["entity"], e["item"])) != e["quantity"]:
                    problems.append("%s: why quantity does not replay" % at)
            if act == "clarify" and len(e.get("candidates") or []) < 2:
                problems.append("%s: fewer than two candidates" % at)
            if t.get("lang") and t["lang"] not in LANGUAGES:
                problems.append("%s: lang" % at)
        if corrections > 1:
            problems.append("%s: more than one correction" % where)
    return problems


def category_table(dialogues):
    table = {}
    for name in CATEGORIES + ("cross_language",):
        rows = [d for d in dialogues if name in d["categories"]]
        table[name] = {"dialogues": len(rows), "ko": sum(d["language"] == "ko" for d in rows),
                       "en": sum(d["language"] == "en" for d in rows),
                       "turns": sum(name in t["tags"] for d in dialogues for t in d["turns"])}
    variation = {}
    for key in VARIATION_KEYS:
        counts = {}
        for d in dialogues:
            value = str(d["variation"].get(key))
            counts[value] = counts.get(value, 0) + 1
        variation[key] = dict(sorted(counts.items()))
    initial = sorted({v for d in dialogues for v in d["variation"]["initial_values"].values() if v is not None})
    labels = {label: sum(t["label"] == label for d in dialogues for t in d["turns"]) for label in LABELS}
    return {"categories": table, "variation": variation, "initial_values_used": initial, "labels": labels,
            "dialogues": len(dialogues), "turns": sum(len(d["turns"]) for d in dialogues),
            "by_language": {code: sum(d["language"] == code for d in dialogues) for code in LANGUAGES}}


# ---------------------------------------------------------------------------
# F1.3 unseen: full-sentence overlap
# ---------------------------------------------------------------------------
_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_BEFORE = set("\n.!?。…\"“”'‘’`([{<,;:|\\=>*#-")
_AFTER = set("\n.!?。…\"“”'‘’`)]}>,;:|\\")


def _normalize_corpus(text):
    text = _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text).replace("\\n", "\n")
    return re.sub(r"[ \t\r\f\v]+", " ", text.lower())


def _normalize_sentence(text):
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text.strip(" .!?。…,;:\"“”‘’'")


def dialogue_sentences(dialogues):
    out = []
    for d in dialogues:
        for t in d["turns"]:
            for sentence in re.split(r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<=[.!?])\s+", t["say"].strip()):
                norm = _normalize_sentence(sentence)
                if norm:
                    out.append((d["id"], t["n"], sentence, norm))
    return out


def _owned(path, owned=OWNED):
    return any(path == p or path.startswith(p) for p in owned)


def corpus(rev="HEAD", disk_root=None, dirs=CORPUS_DIRS, owned=OWNED, files=None):
    """Yield (path, normalized text) for every file under ``dirs`` at ``rev`` (or on disk),
    or for exactly ``files`` (on disk) when given."""
    if files is not None:
        for name in files:
            path = Path(name)
            path = path if path.is_absolute() else ROOT / path
            data = path.read_bytes()
            if b"\0" not in data[:8192]:
                yield str(name), _normalize_corpus(data.decode("utf-8", "ignore"))
        return
    if disk_root:
        base = Path(disk_root)
        for top in dirs:
            for path in sorted((base / top).rglob("*")):
                rel = path.relative_to(base).as_posix()
                if path.is_file() and not _owned(rel, owned) and "/.git/" not in rel:
                    data = path.read_bytes()
                    if b"\0" not in data[:8192]:
                        yield rel, _normalize_corpus(data.decode("utf-8", "ignore"))
        return
    names = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", "-z", "--name-only", rev, "--", *dirs],
                           check=True, capture_output=True).stdout.decode("utf-8").split("\0")
    names = [n for n in names if n and not _owned(n, owned)]
    batch = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch"], check=True, capture_output=True,
                           input="".join("%s:%s\n" % (rev, n) for n in names).encode("utf-8")).stdout
    offset = 0
    for name in names:
        header_end = batch.index(b"\n", offset)
        size = int(batch[offset:header_end].split()[2])
        data = batch[header_end + 1: header_end + 1 + size]
        offset = header_end + 1 + size + 1
        if b"\0" not in data[:8192]:
            yield name, _normalize_corpus(data.decode("utf-8", "ignore"))


def _full_sentence_at(text, sentence):
    start = text.find(sentence)
    while start != -1:
        i = start - 1
        while i >= 0 and text[i] == " ":
            i -= 1
        j = start + len(sentence)
        while j < len(text) and text[j] == " ":
            j += 1
        if (i < 0 or text[i] in _BEFORE) and (j >= len(text) or text[j] in _AFTER):
            return True
        start = text.find(sentence, start + 1)
    return False


def overlaps(dialogues, rev="HEAD", disk_root=None, dirs=CORPUS_DIRS, owned=OWNED, files=None):
    sentences = dialogue_sentences(dialogues)
    found, count = [], 0
    for path, text in corpus(rev, disk_root, dirs, owned, files):
        count += 1
        for did, n, raw, norm in sentences:
            if norm in text and _full_sentence_at(text, norm):
                found.append({"dialogue": did, "turn": n, "sentence": raw, "file": path})
    source = "%d named files" % len(files) if files is not None else (disk_root or rev)
    return {"source": source, "files": count, "sentences": len(sentences), "overlaps": found}


# ---------------------------------------------------------------------------
# F1.4 run: the UI turn handler
# ---------------------------------------------------------------------------
def observe(result, research_calls, elapsed_ms):
    """Reduce the UI payload to what the scorer reads.  No expectation is consulted here."""
    answer = result.get("answer") if isinstance(result.get("answer"), dict) else {}
    trace = answer.get("trace") or {}
    reasoning = answer.get("reasoning") or trace.get("reasoning") or {}
    facts, state, corrections, evidence = [], [], [], []
    for row in reasoning.get("transitions") or []:
        if not isinstance(row, dict):
            continue
        ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        texts = [x for x in (ev.get("text"), ev.get("source")) if isinstance(x, str) and x]
        if isinstance(row.get("fact"), (list, tuple)) and len(row["fact"]) >= 3:
            facts.append({"subject": str(row["fact"][0]), "predicate": str(row["fact"][1]),
                          "value": str(row["fact"][2]), "evidence": texts})
        elif row.get("operation") in ("state_update", "quantity_update"):
            state.append({"subject": str(row.get("subject")), "predicate": str(row.get("predicate")),
                          "value": str(row.get("after")), "evidence": texts})
        elif row.get("operation") == "correction":
            corrections.append({"index": row.get("index"), "before": row.get("before"), "after": row.get("after")})
    verification = answer.get("verification") or trace.get("verification") or {}
    observation_turns = None
    for check in verification.get("checks") or [] if isinstance(verification, dict) else []:
        if isinstance(check, dict):
            evidence += [x for x in check.get("evidence") or [] if isinstance(x, str)]
            if isinstance(check.get("observation_turns"), int):
                observation_turns = check["observation_turns"]
    for source in trace.get("sources") or []:
        if isinstance(source, dict):
            evidence += [str(source[k]) for k in ("text", "source") if source.get(k)]
    text = answer.get("answer")
    if not isinstance(text, str):
        text = result.get("web_answer") if isinstance(result.get("web_answer"), str) else ""
    return {"phase": result.get("phase"), "verdict": trace.get("verdict"), "known": answer.get("known"),
            "answer": text, "facts": facts, "state": state, "corrections": corrections, "evidence": evidence,
            "observation_turns": observation_turns, "research_calls": research_calls,
            "elapsed_ms": round(elapsed_ms, 1)}


def _import_code(code_root):
    code_root = str(Path(code_root).resolve())
    if code_root in sys.path:
        sys.path.remove(code_root)
    sys.path.insert(0, code_root)
    os.environ.setdefault("KG_ENCODER", "문자")
    import kgpack  # noqa: E402
    from conversation_store import ConversationStore  # noqa: E402
    from views.kgpack_ui import AppState  # noqa: E402
    return kgpack, ConversationStore, AppState


def run(dialogues, code_root=ROOT, progress=None):
    """Play every dialogue through AppState.turn; return {dialogue id: [observation per turn]}."""
    from unittest.mock import patch
    kgpack, ConversationStore, AppState = _import_code(code_root)
    code_root = Path(code_root).resolve()
    answers = {}
    with tempfile.TemporaryDirectory(prefix="nai-dialogue-gate-") as temporary:
        folder = Path(temporary)
        packs = {}
        for code, style in LANGUAGES.items():
            pack = folder / ("gate-%s.kgpack" % code)
            files = [code_root / "graphs/graph_일상추론.kg"] + kgpack.model_files(code_root)
            try:
                kgpack.write_pack(pack, files, root=code_root, language="styles/%s.json" % style)
            except TypeError:  # an older pack writer without a declared language
                kgpack.write_pack(pack, files, root=code_root)
            packs[code] = pack
        for d in dialogues:
            home = folder / d["id"]

            def app():
                state = AppState(packs[d["language"]], overlay_root=home / "overlay")
                state.conversations = ConversationStore(home / "conversations.json")
                return state
            rows = []
            try:
                current = app()
                chat = current.conversations.create_chat()["id"]
            except Exception as exc:
                answers[d["id"]] = [{"error": "startup %s: %s" % (type(exc).__name__, exc)} for _ in d["turns"]]
                continue
            session = "dialoguegate_" + re.sub(r"[^A-Za-z0-9_-]", "_", d["id"])
            for t in d["turns"]:
                start = time.perf_counter()
                try:
                    if t.get("restart_before"):
                        current = app()
                    offline = {"query": t["say"], "sources": [], "verified": False}
                    with patch.object(current.goals, "research", return_value=offline) as research:
                        result = current.turn(t["say"], session, conversation_id=chat)
                    rows.append(observe(result, research.call_count, (time.perf_counter() - start) * 1000))
                except Exception as exc:  # an execution error is its own bucket, never a hold
                    rows.append({"error": "%s: %s" % (type(exc).__name__, exc),
                                 "where": traceback.format_exc(limit=-3).strip().splitlines()[-3:],
                                 "elapsed_ms": round((time.perf_counter() - start) * 1000, 1)})
            answers[d["id"]] = rows
            if progress:
                progress(d["id"], rows)
    return answers


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
_EN_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90}
_EN_WORD = re.compile(r"(?<![a-z'])(?:(%s)(?:[- ](%s))?|(%s))(?![a-z])" % (
    "|".join(_EN_TENS), "|".join(list(_EN_UNITS)[1:10]), "|".join(sorted(_EN_UNITS, key=len, reverse=True))))
_EN_NOT_NUMBER = re.compile(r"(?:that|this|the|which|other|another|each|any|every|no|a)\s+$")
_KO_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70,
            "여든": 80, "아흔": 90}
_KO_UNITS = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "석": 3, "넷": 4, "네": 4, "넉": 4,
             "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_KO_COUNTER = "개|명|권|장|병|자루|묶음|마리|대|잔|알|송이|켤레|상자|통|봉지|조각|개비"
_KO_WORD = re.compile(r"(?<![가-힣])(%s)?(%s)?\s?(?=(?:%s))" % (
    "|".join(sorted(_KO_TENS, key=len, reverse=True)), "|".join(sorted(_KO_UNITS, key=len, reverse=True)),
    _KO_COUNTER))
_CITED = [re.compile(p) for p in (r"\"[^\"]*\"", r"“[^”]*”", r"‘[^’]*’", r"「[^」]*」", r"«[^»]*»",
                                  r"(?<![A-Za-z])'[^']*'(?![A-Za-z])", r"\([^)]*\)", r"\[[^\]]*\]")]


def asserted(text):
    """The answer text without spans that quote or annotate rather than assert."""
    for pattern in _CITED:
        text = pattern.sub(" ", text or "")
    return text


def quantities(text):
    """Every quantity stated in ``text``: digits, English and Korean native numeral words."""
    values = [int(m) for m in re.findall(r"(?<![\d.])\d+(?![\d]|\.\d)", text)]
    lower = text.lower()
    for m in _EN_WORD.finditer(lower):
        if m.group(3) == "one" and _EN_NOT_NUMBER.search(lower[:m.start()]):
            continue
        values.append(_EN_TENS[m.group(1)] + _EN_UNITS.get(m.group(2) or "zero", 0) if m.group(1)
                      else _EN_UNITS[m.group(3)])
    for m in _KO_WORD.finditer(text):
        if m.group(1) or m.group(2):
            values.append(_KO_TENS.get(m.group(1), 0) + _KO_UNITS.get(m.group(2), 0))
    return set(values)


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip().strip(" .!?。…")


def _mentions(text, name):
    text, name = (text or "").lower(), name.lower()
    if re.fullmatch(r"[a-z .'-]+", name):
        return re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(name), text) is not None
    return name in text


def status(obs):
    if obs.get("error"):
        return "error"
    if obs.get("phase") != "answer":
        return "held"          # research or plan: no local answer was given
    verdict = obs.get("verdict")
    if verdict in OBSERVED:
        return "observed"
    if verdict in HELD:
        return "held"
    if verdict in CHAT:
        return "chat"
    if obs.get("known") is True:
        return "answered"
    if obs.get("known") is False:
        return "held"
    return "unknown"


def _turn_map(dialogue, text):
    """Dialogue turns whose wording contains ``text``."""
    needle = _norm(text)
    if not needle:
        return set()
    return {t["n"] for t in dialogue["turns"] if needle in _norm(t["say"])}


def _retracted_targets(dialogue, upto):
    return {t["expect"]["target_turn"]: t["n"] for t in dialogue["turns"][:upto - 1]
            if t["expect"]["act"] == "revise"}


def _subject_value(obs, entity, item):
    """Latest recorded value for (entity, item) in the payload's state rows, or None."""
    rows = [r for r in obs.get("state") or [] if _mentions(r["subject"], entity)]
    if not rows:
        return None
    words = [w for w in re.split(r"\s+", item.lower()) if w]
    stem = words[-1][:4] if re.fullmatch(r"[a-z]+", words[-1]) else words[-1]
    with_item = [r for r in rows if stem in r["subject"].lower()]
    chosen = with_item or (rows if len({r["subject"] for r in rows}) == 1 else [])
    return chosen[-1]["value"] if chosen else None


def score_turn(dialogue, turn, obs, previous_observation_turns=None):
    """Outcome for one turn.  Returns (bucket, reason, violation or None)."""
    e, label = turn["expect"], turn["label"]
    st = status(obs)
    if st == "error":
        return "execution_error", obs.get("error"), None
    text = obs.get("answer") or ""
    if label == "answerable":
        if st != "answered":
            return "hold", st, None
        claimed = asserted(text)
        fact_values = {int(f["value"]) for f in obs.get("facts") or [] if re.fullmatch(r"-?\d+", f["value"])}
        fact_evidence = [x for f in obs.get("facts") or [] for x in f["evidence"]]
        evidence = fact_evidence + list(obs.get("evidence") or [])
        if e["relation"] == "more":
            named = {c for c in e["candidates"] if _mentions(claimed, c)}
            if named == {e["entity"]}:
                return ("correct", "entity", None) if evidence else \
                    ("unverifiable", "no_evidence", "confident_without_evidence")
            if not named:
                return "unverifiable", "no_candidate_named", None
            if e["entity"] not in named:
                return "wrong", "other_entity", None
            return "unverifiable", "several_candidates_named", None
        values = quantities(claimed)
        if len(values) == 1:
            value = next(iter(values))
        elif len(values) > 1 and len(fact_values) == 1 and fact_values <= values:
            value = next(iter(fact_values))
        elif not values:
            return "unverifiable", "no_quantity_in_answer", None
        else:
            return "unverifiable", "several_quantities:%s" % sorted(values), None
        if value != e["quantity"]:
            if value == e.get("retracted_quantity"):
                return "wrong", "retracted_value:%d" % value, "retracted_evidence_used"
            if value == e.get("reexecuted_quantity"):
                return "wrong", "correction_reexecuted:%d" % value, None
            return "wrong", "value:%d" % value, None
        if not evidence:
            return "unverifiable", "no_evidence", "confident_without_evidence"
        targets = _retracted_targets(dialogue, turn["n"])
        expected_turns = set(e["evidence"]["turns"])
        for item in fact_evidence:
            mapped = _turn_map(dialogue, item)
            if mapped & set(targets):
                return "wrong", "retracted_evidence:%s" % item, "retracted_evidence_used"
            if mapped and not mapped & expected_turns:
                return "wrong", "evidence_from_unrelated_turn:%s" % item, None
        return "correct", "value", None
    if label == "why":
        if st != "answered":
            return "hold", st, None
        corpus_text = _norm(" ".join([text] + list(obs.get("evidence") or [])
                                     + [x for f in obs.get("facts") or [] for x in f["evidence"]]
                                     + [str(c.get(k)) for c in obs.get("corrections") or []
                                        for k in ("before", "after")]))
        if not corpus_text:
            return "unverifiable", "empty_answer", None
        targets = _retracted_targets(dialogue, turn["n"])
        missing = []
        for n in e["evidence"]["turns"]:
            if _norm(dialogue["turns"][n - 1]["say"]) in corpus_text:
                continue
            if n in targets and _norm(dialogue["turns"][targets[n] - 1]["say"]) in corpus_text:
                continue
            missing.append(n)
        return ("correct", "cites_all", None) if not missing else ("wrong", "missing_citation:%s" % missing, None)
    if label == "hold" and e["act"] == "record":
        if st == "answered":
            return "wrong", "answered_statement", None
        if st != "observed":
            return "hold", "not_recorded:%s" % st, None
        checked = 0
        for row in e["state"]:
            if row["quantity"] is None:
                continue
            got = _subject_value(obs, row["entity"], row["item"])
            if got is None:
                continue
            checked += 1
            if got != str(row["quantity"]):
                return "wrong", "misrecorded:%s=%s" % (row["entity"], got), None
        if not checked and any(row["quantity"] is not None for row in e["state"]):
            return "unverifiable", "state_not_in_payload", None
        return "correct", "recorded", None
    if label == "correction":
        if st != "observed":
            return ("wrong", "answered_correction", None) if st == "answered" else ("hold", st, None)
        if (previous_observation_turns is not None and obs.get("observation_turns") is not None
                and obs["observation_turns"] > previous_observation_turns):
            return "wrong", "new_event_added", None
        checked = 0
        for row in e["state"]:
            got = _subject_value(obs, row["entity"], row["item"])
            if got is None or row["quantity"] is None:
                continue
            checked += 1
            if got != str(row["quantity"]):
                return "wrong", "state:%s=%s" % (row["entity"], got), None
        if not checked:
            return "unverifiable", "state_not_in_payload", None
        return "correct", "revised", None
    if label in ("hold", "ambiguous", "unsupported"):
        if st == "answered":
            return "wrong", "confident_answer", "confident_without_evidence"
        if st == "observed":
            return "wrong", "recorded_as_statement", None
        if label == "unsupported":
            return "correct", "declined", None
        names = [e["entity"]] if label == "hold" else e["candidates"]
        if all(_mentions(text, name) for name in names):
            return "correct", "held_and_named" if label == "hold" else "asked_which", None
        return "hold", "vague_hold", None
    return "unverifiable", "unknown_label", None


def _bucket_counts(rows):
    out = {k: 0 for k in BUCKETS}
    for row in rows:
        out[row["bucket"]] += 1
    out["n"] = len(rows)
    out["accuracy"] = round(out["correct"] / out["n"], 4) if out["n"] else None
    return out


def score(dialogues, answers, meta=None):
    rows = []
    for d in dialogues:
        got = answers.get(d["id"]) or []
        previous = None
        for index, t in enumerate(d["turns"]):
            obs = got[index] if index < len(got) else {"error": "no observation recorded"}
            bucket, reason, violation = score_turn(d, t, obs, previous)
            if obs.get("observation_turns") is not None:
                previous = obs["observation_turns"]
            rows.append({"dialogue": d["id"], "language": d["language"], "n": t["n"], "label": t["label"],
                         "act": t["expect"]["act"], "tags": t["tags"], "say": t["say"], "bucket": bucket,
                         "reason": reason, "violation": violation, "status": status(obs),
                         "answer": (obs.get("answer") or "")[:300], "research_calls": obs.get("research_calls")})
    answerable = [r for r in rows if r["label"] == "answerable"]
    gate = _bucket_counts(answerable)
    needed = math.ceil(0.9 * gate["n"])
    gate.update(threshold=0.9, needed=needed, passed=gate["correct"] >= needed and gate["n"] > 0,
                denominator="every turn labelled answerable across %d dialogues (%d turns); hold, wrong, "
                            "execution_error and unverifiable all count against" % (len(dialogues), gate["n"]))
    other = {}
    for name, keep in (("record", lambda r: r["act"] == "record"), ("hold", lambda r: r["act"] == "hold"),
                       ("ambiguous", lambda r: r["label"] == "ambiguous"),
                       ("unsupported", lambda r: r["label"] == "unsupported"),
                       ("correction", lambda r: r["label"] == "correction"), ("why", lambda r: r["label"] == "why")):
        other[name] = _bucket_counts([r for r in rows if keep(r)])
    violations = {"confident_without_evidence": [], "retracted_evidence_used": []}
    for r in rows:
        if r["violation"]:
            violations[r["violation"]].append("%s#%d" % (r["dialogue"], r["n"]))
    per_dialogue = {}
    for r in rows:
        per_dialogue.setdefault(r["dialogue"], []).append(r["bucket"] == "correct")
    return {
        "schema": SCHEMA + "-report", "meta": meta or {},
        "dataset": {"dialogues": len(dialogues), "turns": len(rows),
                    "by_language": {c: sum(d["language"] == c for d in dialogues) for c in LANGUAGES},
                    "labels": {label: sum(r["label"] == label for r in rows) for label in LABELS}},
        "gate": gate,
        "by_language": {c: _bucket_counts([r for r in answerable if r["language"] == c]) for c in LANGUAGES},
        "by_category": {c: _bucket_counts([r for r in answerable if c in r["tags"]])
                        for c in CATEGORIES + ("cross_language",)},
        "other_labels": other,
        "violations": {k: {"count": len(v), "turns": v} for k, v in violations.items()},
        "dialogues_fully_passed": sum(all(v) for v in per_dialogue.values()),
        "failures": [r for r in rows if r["bucket"] != "correct"],
        "rows": rows,
    }


def format_report(report):
    g = report["gate"]
    lines = ["dialogues %d  turns %d  (ko %d, en %d)" % (
        report["dataset"]["dialogues"], report["dataset"]["turns"],
        report["dataset"]["by_language"]["ko"], report["dataset"]["by_language"]["en"]),
        "GATE answerable N=%d  correct %d  hold %d  wrong %d  execution_error %d  unverifiable %d  "
        "-> %s  (needs %d/%d = 90%%; %s)" % (
            g["n"], g["correct"], g["hold"], g["wrong"], g["execution_error"], g["unverifiable"],
            "%.1f%%" % (100 * g["accuracy"]) if g["accuracy"] is not None else "n/a", g["needed"], g["n"],
            "PASS" if g["passed"] else "FAIL"),
        "denominator: " + g["denominator"], "",
        "%-22s %4s %7s %4s %5s %5s %6s" % ("answerable by", "N", "correct", "hold", "wrong", "error", "unver.")]
    for group in ("by_language", "by_category"):
        for name, c in report[group].items():
            lines.append("%-22s %4d %7d %4d %5d %5d %6d" % (
                name, c["n"], c["correct"], c["hold"], c["wrong"], c["execution_error"], c["unverifiable"]))
    lines += ["", "%-22s %4s %7s %4s %5s %5s %6s" % ("reported apart", "N", "correct", "hold", "wrong", "error",
                                                    "unver.")]
    for name, c in report["other_labels"].items():
        lines.append("%-22s %4d %7d %4d %5d %5d %6d" % (
            name, c["n"], c["correct"], c["hold"], c["wrong"], c["execution_error"], c["unverifiable"]))
    v = report["violations"]
    lines += ["", "confident answers without evidence: %d  %s" % (v["confident_without_evidence"]["count"],
                                                                  v["confident_without_evidence"]["turns"][:12]),
              "retracted evidence used: %d  %s" % (v["retracted_evidence_used"]["count"],
                                                   v["retracted_evidence_used"]["turns"][:12]),
              "dialogues with every turn correct: %d/%d" % (report["dialogues_fully_passed"],
                                                            report["dataset"]["dialogues"]),
              "failures listed: %d (full list in the JSON report)" % len(report["failures"])]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# synthetic answers (for the error-injection tests)
# ---------------------------------------------------------------------------
def synthesize(dialogues, mode):
    """An answers file built from the expectations: ``perfect`` or deliberately ``wrong``."""
    assert mode in ("perfect", "wrong")
    answers = {}
    for d in dialogues:
        rows, observations = [], 0
        for t in d["turns"]:
            e = t["expect"]
            act = e["act"]
            targets = _retracted_targets(d, t["n"])
            clean = [d["turns"][n - 1]["say"] for n in e["evidence"]["turns"]
                     if n not in targets and n not in targets.values()] or ["(corrected event)"]
            base = {"phase": "answer", "facts": [], "state": [], "corrections": [], "evidence": [],
                    "observation_turns": None, "research_calls": 0}
            if act == "record":
                observations += 1
                if mode == "perfect":
                    row = dict(base, verdict="상태기억", known=False, answer="recorded",
                               observation_turns=observations,
                               state=[{"subject": "%s %s" % (s["entity"], s["item"]), "predicate": "count",
                                       "value": str(s["quantity"]), "evidence": [t["say"]]} for s in e["state"]])
                else:
                    row = dict(base, verdict="입력이해실패", known=False, answer="?")
            elif act == "revise":
                row = dict(base, verdict="상태기억", known=False, answer="revised",
                           observation_turns=observations + (0 if mode == "perfect" else 1),
                           state=[{"subject": "%s %s" % (s["entity"], s["item"]), "predicate": "count",
                                   "value": str(s["quantity"] if mode == "perfect" else
                                                (s["quantity"] or 0) + 1), "evidence": []}
                                  for s in e["state"]])
            elif act == "answer" and e["relation"] == "more":
                name = e["entity"] if mode == "perfect" else next(c for c in e["candidates"] if c != e["entity"])
                row = dict(base, verdict="계산완료", known=True, answer=name + ".", evidence=clean)
            elif act == "answer":
                q = e["quantity"] if mode == "perfect" else e["quantity"] + 1
                subject = e["entity"] if isinstance(e["entity"], str) else " ".join(e["entity"])
                row = dict(base, verdict="계산완료", known=True, answer="%d." % q,
                           facts=[{"subject": "%s %s" % (subject, e["item"]), "predicate": "count",
                                   "value": str(q), "evidence": clean}])
            elif act == "explain":
                cited = " ".join('"%s"' % d["turns"][n - 1]["say"] for n in e["evidence"]["turns"])
                row = dict(base, verdict="계산완료", known=True,
                           answer=("Because of " + cited) if mode == "perfect" else "Because.")
            elif act == "hold":
                row = (dict(base, verdict="조건부족", known=False, answer="%s: not stated." % e["entity"])
                       if mode == "perfect" else dict(base, verdict="계산완료", known=True, answer="7."))
            elif act == "clarify":
                row = (dict(base, verdict="조건부족", known=False, answer="Which: %s?" % ", ".join(e["candidates"]))
                       if mode == "perfect" else
                       dict(base, verdict="계산완료", known=True, answer="%s: 3." % e["candidates"][0]))
            elif act == "decline":
                row = (dict(base, verdict="입력이해실패", known=False, answer="Not supported.")
                       if mode == "perfect" else dict(base, verdict="계산완료", known=True, answer="Done."))
            else:
                raise ValueError(act)
            rows.append(row)
        answers[d["id"]] = rows
    return answers


# ---------------------------------------------------------------------------
# F1.6 baseline
# ---------------------------------------------------------------------------
def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _contains(commit, sha):
    return subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, sha]).returncode == 0


def first_main_with(commit=BASELINE_COMMIT, branch="main"):
    """The first commit the branch actually stood at that contains ``commit``.

    Walking first-parent history alone lands on a commit the branch may never
    have pointed at: a fast-forward skips over everything between the old tip
    and the new one.  The reflog says where the branch really was, so only those
    commits can count.  Without a reflog the head is the earliest we can attest.
    """
    head = _git("rev-parse", branch)
    if not _contains(commit, head):
        return None
    try:
        stood_at = set(_git("reflog", "show", branch, "--format=%H").split())
    except subprocess.CalledProcessError:
        stood_at = set()
    for sha in _git("rev-list", "--first-parent", "--reverse", branch).split():
        if sha in stood_at and _contains(commit, sha):
            return sha
    return head


def run_at_revision(rev, answers_out, dataset=DATASET, split=None):
    """Export ``rev`` without git metadata and run the dialogues against that code in a subprocess."""
    with tempfile.TemporaryDirectory(prefix="nai-gate-code-") as temporary:
        export = Path(temporary) / "code"
        export.mkdir()
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", rev], check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(export)], input=archive, check=True)
        env = dict(os.environ)
        env.setdefault("KG_ENCODER", "문자")
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "run", "--code-root", str(export),
                        "--answers-out", str(answers_out), "--quiet", "--dataset", str(Path(dataset).resolve())]
                       + (["--split", split] if split else []),
                       check=True, env=env, cwd=str(export))
    return json.loads(Path(answers_out).read_text(encoding="utf-8"))


def _meta(code_root, rev=None, dataset=DATASET):
    frozen = Path(dataset) / FROZEN.name
    meta = {"dataset_sha256": tree_hash(dataset), "frozen_sha256": frozen_hash(frozen) if frozen.exists() else None,
            "encoder": os.environ.get("KG_ENCODER", "문자"), "entry": "views.kgpack_ui.AppState.turn",
            "research": "stubbed; calls counted", "python": sys.version.split()[0]}
    if rev:
        meta["code_commit"] = _git("rev-parse", rev)
    else:
        try:
            meta["code_commit"] = subprocess.run(["git", "-C", str(code_root), "rev-parse", "HEAD"], check=True,
                                                 capture_output=True, text=True).stdout.strip()
            meta["code_dirty"] = bool(subprocess.run(["git", "-C", str(code_root), "status", "--porcelain",
                                                      "--untracked-files=no"], capture_output=True,
                                                     text=True).stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            meta["code_commit"] = None
    return meta


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dataset", type=Path, action="append",
                        help="dialogue directory to read (default: the frozen set); "
                             "overlap takes it more than once")
    common.add_argument("--split", help="only the dialogues listed under this name in the dataset's split.txt")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", parents=[common])
    sub.add_parser("categories", parents=[common])
    p = sub.add_parser("overlap", parents=[common])
    p.add_argument("--rev", default="HEAD")
    p.add_argument("--disk-root")
    p.add_argument("--files", nargs="+", help="check these files (on disk) instead of the corpus directories")
    p = sub.add_parser("run", parents=[common])
    p.add_argument("--code-root", default=str(ROOT))
    p.add_argument("--code-rev", help="export this revision and run the dialogues against it")
    p.add_argument("--answers-out", type=Path)
    p.add_argument("--report-out", type=Path)
    p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("score", parents=[common])
    p.add_argument("answers", type=Path)
    p.add_argument("--report-out", type=Path)
    p = sub.add_parser("hash", parents=[common])
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("baseline", parents=[common])
    p.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    datasets = [path.resolve() for path in (args.dataset or [DATASET])]
    if args.command != "overlap" and len(datasets) != 1:
        print("%s reads one dataset" % args.command)
        return 2
    if args.command == "overlap" and len(datasets) > 1:
        combined = 0
        for one in datasets:
            combined |= main([arg for arg in _without_datasets(argv if argv is not None else sys.argv[1:])]
                           + ["--dataset", str(one)])
        return combined
    dataset = datasets[0]
    frozen_set = dataset == DATASET.resolve()
    if args.command == "baseline" and not frozen_set:
        print("baseline records the frozen set only")
        return 2
    dialogues = load(dataset, args.split)

    if args.command == "validate":
        problems = validate(dialogues)
        print(json.dumps(category_table(dialogues)["by_language"]), "dialogues", len(dialogues),
              "turns", sum(len(d["turns"]) for d in dialogues))
        print("problems: %d" % len(problems))
        for item in problems:
            print("  " + item)
        return 1 if problems else 0
    if args.command == "categories":
        table = category_table(dialogues)
        print("%-20s %9s %4s %4s %6s" % ("category", "dialogues", "ko", "en", "turns"))
        for name, row in table["categories"].items():
            print("%-20s %9d %4d %4d %6d%s" % (name, row["dialogues"], row["ko"], row["en"], row["turns"],
                                               "" if name == "cross_language" or row["dialogues"] >= 5
                                               else "  < 5"))
        for key, counts in table["variation"].items():
            print("%s: %s" % (key, json.dumps(counts, ensure_ascii=False)))
        print("initial values used:", table["initial_values_used"])
        print("labels:", json.dumps(table["labels"]))
        short = [n for n, r in table["categories"].items() if n in CATEGORIES and r["dialogues"] < 5]
        return 1 if short else 0
    if args.command == "overlap":
        owned = OWNED
        if not frozen_set:  # the other set against everything outside itself, the frozen set included
            try:
                owned = (dataset.relative_to(ROOT).as_posix() + "/",)
            except ValueError:
                owned = ()
        result = overlaps(dialogues, rev=args.rev, disk_root=args.disk_root, owned=owned, files=args.files)
        label = dataset.relative_to(ROOT).as_posix() if dataset.is_relative_to(ROOT) else str(dataset)
        print("%s%s: source %s  files %d  dialogue sentences %d  overlaps %d" % (
            label, " (%s)" % args.split if args.split else "", result["source"], result["files"],
            result["sentences"], len(result["overlaps"])))
        if frozen_set:
            # The exam's sentences stay unseen: only how many, and where.
            per_file = {}
            for item in result["overlaps"]:
                per_file[item["file"]] = per_file.get(item["file"], 0) + 1
            for name, count in sorted(per_file.items()):
                print("  %d in %s" % (count, name))
        else:
            for item in result["overlaps"]:
                print("  %(dialogue)s#%(turn)d %(sentence)r in %(file)s" % item)
        return 1 if result["overlaps"] else 0
    if args.command == "hash":
        digest, frozen = tree_hash(dataset), dataset / FROZEN.name
        if args.write:
            label = dataset.relative_to(ROOT).as_posix() if dataset.is_relative_to(ROOT) else str(dataset)
            frozen.write_text("%s  %s\n" % (digest, label), encoding="utf-8")
        print(digest, "frozen" if frozen.exists() and frozen_hash(frozen) == digest else "NOT FROZEN")
        return 0
    if args.command in ("run", "score", "baseline"):
        if args.command == "score":
            saved = json.loads(args.answers.read_text(encoding="utf-8"))
            answers, meta = saved["answers"], saved.get("meta", {})
            out = args.report_out
        elif args.command == "baseline":
            target = first_main_with()
            main_head = _git("rev-parse", "main")
            if not target:
                print("F1.6 not reachable: main %s does not contain %s" % (main_head[:7], BASELINE_COMMIT))
                return 2
            out = REPORT_DIR / "baseline.json"
            if out.exists() and not args.force:
                print("baseline already recorded: %s" % out)
                return 2
            with tempfile.TemporaryDirectory() as temporary:
                saved = run_at_revision(target, Path(temporary) / "answers.json")
            answers, meta = saved["answers"], saved["meta"]
            meta.update(code_commit=_git("rev-parse", target), main_head_at_run=main_head,
                        rule="first commit main actually stood at (reflog, else head) that contains %s" % BASELINE_COMMIT)
        elif args.code_rev:
            with tempfile.TemporaryDirectory() as temporary:
                saved = run_at_revision(args.code_rev, Path(temporary) / "answers.json", dataset, args.split)
            answers, meta = saved["answers"], saved["meta"]
            meta["code_commit"] = _git("rev-parse", args.code_rev)
            out = args.report_out
        else:
            start = time.perf_counter()
            progress = None if args.quiet else (lambda did, rows: print(
                did, " ".join("E" if r.get("error") else status(r)[0] for r in rows), flush=True))
            answers = run(dialogues, args.code_root, progress)
            meta = _meta(args.code_root, dataset=dataset)
            meta["seconds"] = round(time.perf_counter() - start, 1)
            if args.split:
                meta["split"] = args.split
            out = args.report_out
            if args.answers_out:
                args.answers_out.write_text(json.dumps({"meta": meta, "answers": answers}, ensure_ascii=False,
                                                       indent=1) + "\n", encoding="utf-8")
                if args.quiet:
                    return 0
        report = score(dialogues, answers, meta)
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(format_report(report))
        return 0
    return 1


def _without_datasets(argv):
    out, skip = [], False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg == "--dataset":
            skip = True
            continue
        if arg.startswith("--dataset="):
            continue
        out.append(arg)
    return out


if __name__ == "__main__":
    sys.exit(main())
