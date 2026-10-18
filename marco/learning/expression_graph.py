"""Pure bounded graph induction/compilation; implementation supplied as literal patches."""
import copy
import hashlib
import itertools

SCHEMA = "learned-expression-choice-graph-v1"
POLICY = "selected-reference-choice-graph-v1"
_ROOT = "expression-choice-root-v1"
_ORDERS = ("subject-object", "object-subject")
_HEAD = ("subject", "object", "predicate", "order", "word_subject", "word_object",
         "choice0", "choice1", "choice2")
_HEAD_EDGES = (("subject", "root-subject"), ("object", "root-object"),
               ("predicate", "root-predicate"), ("order", "root-order"),
               ("word_subject", "root-word-subject"), ("word_object", "root-word-object"),
               ("choice0", "root-segment0"), ("choice1", "root-segment1"),
               ("choice2", "root-segment2"))
_MAX_KG = 65536
_MAX_INTERVAL = 512
_MAX_VARIANTS = 16


def _hex(text):
    return text.encode("utf-8", "strict").hex()


def _unhex(value):
    if (type(value) is not str or len(value) % 2 or value != value.lower()
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("pattern_graph_hex_invalid")
    try:
        text = bytes.fromhex(value).decode("utf-8", "strict")
    except (ValueError, UnicodeDecodeError):
        raise ValueError("pattern_graph_hex_invalid") from None
    if _hex(text) != value:
        raise ValueError("pattern_graph_hex_invalid")
    return text


def _demo_text(value):
    if type(value) is not str or not value.strip():
        raise ValueError("pattern_graph_demonstration_invalid")
    try:
        raw = value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise ValueError("pattern_graph_demonstration_invalid") from None
    if len(raw) > 4096:
        raise ValueError("pattern_graph_demonstration_invalid")
    return value


def _relation_ok(relation):
    return type(relation) is str and bool(relation) and not relation.startswith(("$", "?"))


def induce_pattern_graph(base, demonstrations):
    """Induce a bounded three-interval literal choice graph; no validation is used."""
    from marco.learning.expressions import from_paraphrase
    from marco.storage import graph_text
    if type(demonstrations) is not list or not 2 <= len(demonstrations) <= 8:
        raise ValueError("pattern_graph_requires_2_to_8_demonstrations")
    pairs = set()
    entities = set()
    rows = []
    relation = order = word = None
    for demo in demonstrations:
        if type(demo) is not dict or set(demo) != {"text", "equivalent"}:
            raise ValueError("pattern_graph_demonstration_invalid")
        key = (_demo_text(demo["text"]), _demo_text(demo["equivalent"]))
        if key in pairs:
            raise ValueError("pattern_graph_duplicate_demonstration")
        pairs.add(key)
        # A known consequent alone is not an unconditional reference meaning.
        reference = base.parse(demo["equivalent"], partial=True, _entry_selection=True)
        if not isinstance(reference, dict):
            raise ValueError("pattern_graph_requires_flat_fact")
        for field in ("definition", "definitions", "events", "condition", "assumption", "reason",
                      "cause", "hypothesis",
                      "correction", "repair", "정의", "사건", "가정사건", "조건", "가정",
                      "원인", "이유물음", "수선", "사건정정"):
            if field in reference and reference[field] not in (None, [], {}, ""):
                raise ValueError("pattern_graph_requires_flat_fact")
        if (type(reference.get("facts")) is not list or len(reference["facts"]) != 1
                or reference.get("query") not in (None, [])):
            raise ValueError("pattern_graph_requires_flat_fact")
        ann = from_paraphrase(base, demo["text"], demo["equivalent"])
        meaning = ann["meaning"]
        if not isinstance(meaning, dict) or set(meaning) - {"triple", "polarity", "modality"}:
            raise ValueError("pattern_graph_requires_flat_fact")
        if meaning.get("polarity", True) is not True:
            raise ValueError("pattern_graph_requires_positive_fact")
        if meaning.get("modality", "asserted") != "asserted":
            raise ValueError("pattern_graph_requires_asserted_fact")
        triple = meaning.get("triple")
        if (type(triple) is not list or len(triple) != 3 or triple[0] != "$subject"
                or triple[2] != "$object" or not _relation_ok(triple[1])):
            raise ValueError("pattern_graph_requires_flat_fact")
        subj, obj = ann["slots"]["subject"], ann["slots"]["object"]
        if (type(subj) is not str or type(obj) is not str or not subj or not obj
                or subj == obj or subj in obj or obj in subj):
            raise ValueError("pattern_graph_requires_distinct_entities")
        if subj in entities or obj in entities:
            raise ValueError("pattern_graph_entities_not_disjoint")
        entities.update((subj, obj))
        ws = tuple(ann.get("word_slots") or ())
        if any(x not in ("subject", "object") for x in ws) or list(ws) != sorted(
                set(ws), key=("subject", "object").index):
            raise ValueError("pattern_graph_word_slots_invalid")
        if relation is None:
            relation, word = triple[1], ws
        elif triple[1] != relation:
            raise ValueError("pattern_graph_relation_mismatch")
        elif ws != word:
            raise ValueError("pattern_graph_word_slots_mismatch")
        surface = ann["text"]
        if surface.count(subj) != 1 or surface.count(obj) != 1:
            raise ValueError("paraphrase_requires_unambiguous_shared_entities")
        s, o = surface.find(subj), surface.find(obj)
        if s < o:
            cur, first, second, a, b = "subject-object", subj, obj, s, o
        else:
            cur, first, second, a, b = "object-subject", obj, subj, o, s
        if a + len(first) > b:
            raise ValueError("pattern_graph_entity_spans_overlap")
        if order is None:
            order = cur
        elif cur != order:
            raise ValueError("pattern_graph_order_mismatch")
        segs = (surface[:a], surface[a + len(first):b], surface[b + len(second):])
        rows.append((subj, obj, segs))
    for _subj, _obj, segs in rows:
        for seg in segs:
            if len(seg) > _MAX_INTERVAL:
                raise ValueError("pattern_graph_interval_too_long")
            if any(entity in seg for entity in entities):
                raise ValueError("pattern_graph_entity_outside_role_span")
    choices = []
    total = 1
    for index in range(3):
        alts = sorted({row[2][index] for row in rows})
        total *= len(alts)
        if total > _MAX_VARIANTS:
            raise ValueError("pattern_graph_too_many_variants")
        choices.append(alts)
    subj0, obj0 = rows[0][0], rows[0][1]
    nodes = {"root": [_ROOT], "subject": [_hex(subj0)], "object": [_hex(obj0)],
             "predicate": [_hex(relation)], "order": [order],
             "word_subject": ["word" if "subject" in word else "phrase"],
             "word_object": ["word" if "object" in word else "phrase"],
             "choice0": ["choice"], "choice1": ["choice"], "choice2": ["choice"]}
    edges = [["root", rel, name] for name, rel in _HEAD_EDGES]
    for seg, alts in enumerate(choices):
        for idx, alt in enumerate(alts):
            name = "literal%d_%d" % (seg, idx)
            nodes[name] = [_hex(alt)]
            edges.append(["choice%d" % seg, "alternative%d" % idx, name])
    g = graph_text.parse("")
    g["공통층"] = nodes
    g["엣지"] = edges
    try:
        kg = graph_text.write(g)
    except graph_text.GraphTextError:
        raise ValueError("pattern_graph_unwritable") from None
    raw = kg.encode("utf-8", "strict")
    if len(raw) > _MAX_KG:
        raise ValueError("pattern_graph_too_large")
    graph = {"schema": SCHEMA, "kg": kg, "sha256": hashlib.sha256(raw).hexdigest()}
    graph_annotations(graph)
    return graph


def _decode(graph):
    from marco.storage import graph_text
    if type(graph) is not dict or set(graph) != {"schema", "kg", "sha256"}:
        raise ValueError("pattern_graph_invalid")
    if graph["schema"] != SCHEMA or type(graph["kg"]) is not str or type(graph["sha256"]) is not str:
        raise ValueError("pattern_graph_invalid")
    kg = graph["kg"]
    try:
        raw = kg.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise ValueError("pattern_graph_invalid") from None
    if len(raw) > _MAX_KG:
        raise ValueError("pattern_graph_too_large")
    if graph["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("pattern_graph_digest_mismatch")
    try:
        g = graph_text.parse(kg)
        again = graph_text.write(g)
    except graph_text.GraphTextError:
        raise ValueError("pattern_graph_invalid") from None
    if again != kg:
        raise ValueError("pattern_graph_not_canonical")
    base = graph_text.parse("")
    if set(g) != set(base) or any(g[k] != base[k] for k in base if k not in ("공통층", "엣지")):
        raise ValueError("pattern_graph_extra_content")
    nodes, edges = g["공통층"], g["엣지"]
    if type(nodes) is not dict or type(edges) is not list:
        raise ValueError("pattern_graph_invalid")
    if len(nodes) > 128 or len(edges) > 256:
        raise ValueError("pattern_graph_too_large")
    for name, examples in nodes.items():
        if type(examples) is not list or len(examples) != 1 or type(examples[0]) is not str:
            raise ValueError("pattern_graph_node_invalid")
    for name in ("root",) + _HEAD:
        if name not in nodes:
            raise ValueError("pattern_graph_node_missing")
    one = {name: nodes[name][0] for name in nodes}
    if one["root"] != _ROOT or one["order"] not in _ORDERS:
        raise ValueError("pattern_graph_node_invalid")
    if one["word_subject"] not in ("word", "phrase") or one["word_object"] not in ("word", "phrase"):
        raise ValueError("pattern_graph_node_invalid")
    if any(one["choice%d" % i] != "choice" for i in range(3)):
        raise ValueError("pattern_graph_node_invalid")
    subj, obj, relation = _unhex(one["subject"]), _unhex(one["object"]), _unhex(one["predicate"])
    if not subj or not obj or subj == obj or subj in obj or obj in subj or not _relation_ok(relation):
        raise ValueError("pattern_graph_node_invalid")
    names = ["root", *_HEAD]
    want_edges = [["root", rel, name] for name, rel in _HEAD_EDGES]
    alts = []
    total = 1
    for seg in range(3):
        found = []
        idx = 0
        while "literal%d_%d" % (seg, idx) in nodes:
            name = "literal%d_%d" % (seg, idx)
            text = _unhex(one[name])
            if len(text) > _MAX_INTERVAL:
                raise ValueError("pattern_graph_interval_too_long")
            found.append(text)
            names.append(name)
            want_edges.append(["choice%d" % seg, "alternative%d" % idx, name])
            idx += 1
        if not found or found != sorted(set(found)):
            raise ValueError("pattern_graph_choice_invalid")
        total *= len(found)
        if total > _MAX_VARIANTS:
            raise ValueError("pattern_graph_too_many_variants")
        alts.append(found)
    if list(nodes) != names or edges != want_edges:
        raise ValueError("pattern_graph_topology_invalid")
    word = [role for role, name in (("subject", "word_subject"), ("object", "word_object"))
            if one[name] == "word"]
    return subj, obj, relation, one["order"], word, alts


def graph_annotations(graph):
    """Compile a strictly validated choice graph into canonical bare-triple annotations."""
    subj, obj, relation, order, word, alts = _decode(graph)
    first, second = (subj, obj) if order == "subject-object" else (obj, subj)
    out = []
    texts = set()
    for a, b, c in itertools.product(*alts):
        surface = a + first + b + second + c
        if surface.count(subj) != 1 or surface.count(obj) != 1:
            raise ValueError("pattern_graph_seed_not_unique")
        s, o = surface.find(subj), surface.find(obj)
        if not (s + len(subj) <= o or o + len(obj) <= s):
            raise ValueError("pattern_graph_seed_overlap")
        if surface in texts:
            raise ValueError("pattern_graph_duplicate_annotation")
        texts.add(surface)
        ann = {"text": surface, "slots": {"subject": subj, "object": obj},
               "meaning": {"triple": ["$subject", relation, "$object"]}}
        if word:
            ann["word_slots"] = list(word)
        out.append(ann)
    return out


def propose_pattern_graph(parser, graph, validation, *, entry_origin=None):
    """Atomically gate every graph-derived annotation through native learn and validation."""
    from relational_semantics import RelationalParser
    from marco.language.entry_origins import EntryOriginError, validated_entry_origin
    from marco.learning.expressions import semantics
    annotations = graph_annotations(graph)
    origin = validated_entry_origin(entry_origin)
    if not isinstance(validation, list) or not validation:
        raise ValueError("expression_requires_transfer_validation")
    if any(not isinstance(case, dict) for case in validation):
        raise ValueError("invalid_expression_validation")
    if not any(x.get("expected") is None for x in validation) or not any(
            isinstance(x.get("expected"), dict) for x in validation):
        raise ValueError("need_positive_and_negative_expression_validation")
    seeds = list(annotations[0]["slots"].values())
    for case in validation:
        if not isinstance(case.get("text"), str) or not case["text"].strip() or "expected" not in case:
            raise ValueError("invalid_expression_validation")
        expected = case["expected"]
        if expected is not None and (not isinstance(expected, dict)
                or set(expected) != {"facts", "query"} or not isinstance(expected["facts"], list)):
            raise ValueError("invalid_expected_semantics")
        if any(seed in case["text"] for seed in seeds):
            raise ValueError("training_validation_entity_overlap")
    if len(parser.data["examples"]) != len(parser.templates):
        raise EntryOriginError("entry_origins_misaligned")
    current_origins = None
    if "_entry_origins" in parser.__dict__:
        current_origins = parser.__dict__["_entry_origins"]
        if (not isinstance(current_origins, list)
                or len(current_origins) != len(parser.data["examples"])
                or len(current_origins) != len(parser.templates)):
            raise EntryOriginError("entry_origins_misaligned")
    trial = RelationalParser(data=parser.data, language_pack=parser.language_pack,
                             entry_origins=current_origins)
    changed = True
    for ann in annotations:
        if not trial.learn(copy.deepcopy(ann), entry_origin=copy.deepcopy(origin)):
            changed = False
    rows = []
    for case in validation:
        expected = case["expected"]
        before, after = semantics(parser, case["text"]), semantics(trial, case["text"])
        rows.append({"id": case.get("id"), "before_ok": before == expected,
                     "after_ok": after == expected, "before": before, "after": after,
                     "expected": expected})
    accepted = (changed and all(row["after_ok"] for row in rows)
                and any(not row["before_ok"] for row in rows))
    if accepted:
        parser.data = copy.deepcopy(trial.data)
        parser.templates = list(trial.templates)
        parser._entry_origins = copy.deepcopy(trial._entry_origins)
        parser._rebuild_inflections()
    return {"kind": "validated_supervised_expression", "accepted": accepted,
            "reason": "validated_transfer" if accepted else "no_improvement_or_validation_failure",
            "validation": rows, "inferred_annotations": copy.deepcopy(annotations),
            "induction_policy": POLICY}
