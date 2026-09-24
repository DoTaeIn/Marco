# -*- coding: utf-8 -*-
"""교체 가능한 대화 언어 팩과 가장 작은 기본 해석 부품.

코어는 특정 언어의 낱말, 조사, 정규식을 알지 않는다. 언어 팩의 선언형
템플릿을 읽어 구조화된 후보를 만들 뿐이며, 더 좋은 모델은 같은 ``parse``
인터페이스를 구현해 주입할 수 있다.
"""
from __future__ import annotations

import json
import os
import importlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent


class DialogueBackend(Protocol):
    def parse(self, text: str, pack: dict[str, Any]) -> dict[str, Any] | None: ...


def default_language() -> str:
    """The one pack under styles/ that declares ``default_model_language: true``.

    This is the single declaration every language-choosing path reads —
    development tools, the dialect reader and pack construction — so the
    defaults cannot drift apart. Two declarations, or none, is an error.
    """
    files = sorted((ROOT / "styles").glob("*.json"))
    stamp = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    return _default_language(stamp)


@lru_cache(maxsize=4)
def _default_language(stamp):
    declared = []
    for path, _mtime, _size in stamp:
        try:
            with open(path, encoding="utf-8") as handle:
                if json.load(handle).get("default_model_language") is True:
                    declared.append(Path(path).stem)
        except (OSError, ValueError):
            continue
    if len(declared) != 1:
        raise ValueError("exactly one styles/*.json must declare default_model_language: %s" % declared)
    return declared[0]


def _language_path(language: str | None = None) -> Path:
    name = (language or os.environ.get("NAI_LANGUAGE") or os.environ.get("KG_LANG")
            or default_language())
    path = Path(name)
    if path.suffix.lower() != ".json":
        path = ROOT / "styles" / (name + ".json")
    elif not path.is_absolute():
        path = ROOT / path
    return path


def _validate_clauses(clauses):
    if not isinstance(clauses, dict):
        raise ValueError("문장분리 must be an object")
    for key in ("candidate_suffixes", "continuation_prefixes", "after_clause_markers",
                "comma_after_suffixes", "hypothetical_prefixes", "question_marks", "abbreviations"):
        values = clauses.get(key, [])
        if not isinstance(values, list) or not all(isinstance(x, str) and x for x in values):
            raise ValueError("문장분리.%s must contain nonempty strings" % key)
    rules = clauses.get("canonical_endings", [])
    if not isinstance(rules, list):
        raise ValueError("문장분리.canonical_endings must be a list")
    ids = set()
    for rule in rules:
        if (not isinstance(rule, dict)
                or not isinstance(rule.get("id"), str) or not rule["id"] or rule["id"] in ids
                or not isinstance(rule.get("suffix"), str) or not rule["suffix"]
                or not isinstance(rule.get("replacements"), list) or not rule["replacements"]
                or not all(isinstance(x, str) for x in rule["replacements"])
                or not isinstance(rule.get("example_features", {}), dict)):
            raise ValueError("invalid 문장분리.canonical_endings rule")
        ids.add(rule["id"])
    return clauses


def _validate_slot_particles(groups):
    """같은 성분 자리를 채울 수 있는 조사 무리. 이 칸이 없는 언어는 빈 목록이다."""
    if not isinstance(groups, list):
        raise ValueError("language pack '자리조사' must be a list")
    seen = set()
    for group in groups:
        if not isinstance(group, list) or len(group) < 2 or not all(
                isinstance(particle, str) and particle for particle in group):
            raise ValueError("each '자리조사' group must list two or more particles")
        for particle in group:
            if particle in seen:
                # 한 조사가 두 무리에 있으면 어느 자리를 뜻하는지 정해지지 않는다.
                raise ValueError("particle '%s' is in two '자리조사' groups" % particle)
            seen.add(particle)
    # 긴 조사를 먼저 본다. '으로' 를 '로' 보다 나중에 보면 앞 글자가 남는다.
    return [sorted(group, key=len, reverse=True) for group in groups]


def _validate_particles(particles):
    """조사는 닫힌 낱말갈래다. 낱말마다 늘지 않으므로 한 번 적어 둔다."""
    if not isinstance(particles, list) or not all(
            isinstance(particle, str) and particle for particle in particles):
        raise ValueError("language pack '조사' must be a list of nonempty strings")
    if len(set(particles)) != len(particles):
        raise ValueError("'조사' lists the same particle twice")
    # 긴 조사를 먼저 본다. `에게` 를 `에게서` 보다 먼저 보면 `서` 가 남는다.
    return sorted(particles, key=len, reverse=True)


def _validate_negation(declared):
    """`…지 않았다` 같은 부정. 낱말마다가 아니라 언어마다 한 번 적는다."""
    if not declared:
        return {}
    if isinstance(declared, dict) and "do_support" in declared:
        # English: an auxiliary do and a negative particle before the bare verb.
        support, particles = declared.get("do_support"), declared.get("particles")
        contractions = declared.get("contractions", {})
        if (not isinstance(support, dict) or not support
                or not all(isinstance(k, str) and v in ("past", "third_person", "base") for k, v in support.items())
                or not isinstance(particles, list) or not all(isinstance(p, str) and p for p in particles)
                or not isinstance(contractions, dict)
                or not all(isinstance(k, str) and v in support for k, v in contractions.items())):
            raise ValueError("language pack '부정' do_support needs forms, particles and contractions")
        return {k: v for k, v in declared.items() if not k.startswith("_")}
    if (not isinstance(declared, dict)
            or not all(isinstance(declared.get(key), str) and declared[key]
                       for key in ("연결", "어간", "갈래"))):
        raise ValueError("language pack '부정' needs 연결, 어간 and 갈래")
    return dict(declared)


def _validate_negation_marker(declared):
    """부정표지: 이름 바로 뒤가 부정인지 보는 정규식 하나. 없으면 ``None``.

    말투 파일의 선언을 부품이 그대로 나른다 — 묶인 팩(``PackModel.language``)도
    느슨한 파일 없이 극성을 읽는다.
    """
    if declared in (None, ""):
        return None
    if not isinstance(declared, str):
        raise ValueError("language pack '부정표지' must be a regular expression string")
    import re
    try:
        re.compile(declared)
    except re.error as exc:
        raise ValueError("language pack '부정표지' is not a regular expression: %s" % exc)
    return declared


def _validate_placeholders(words):
    """뜻풀이에서 아무거나 하나를 가리키는 낱말. 낱말의 성질이라 낱말로 적는다.

    한 가리킴을 두 꼴로 말하기도 한다(`나`·`내`). 그런 것은 **묶어서** 적는다 —
    묶인 낱말끼리는 한 자리다. 낱말 → 그 묶음의 이름 으로 돌려준다.
    """
    if not isinstance(words, list):
        raise ValueError("language pack '자리말' must be a list")
    table = {}
    for item in words:
        group = [item] if isinstance(item, str) else item
        if (not isinstance(group, list) or not group
                or not all(isinstance(word, str) and word for word in group)):
            raise ValueError("language pack '자리말' must list words or word groups")
        for word in group:
            if word in table:
                raise ValueError("'자리말' lists '%s' twice" % word)
            table[word] = min(group)
    return table


def _validate_quantities(rows):
    """기준이 되는 양에서 계산해 나오는 양. 낱말 → (연산, 값)."""
    table = {}
    for row in rows or []:
        if (not isinstance(row, dict) or not isinstance(row.get("말"), list)
                or not all(isinstance(word, str) and word for word in row["말"])
                or not isinstance(row.get("연산"), str) or not row["연산"]
                or not isinstance(row.get("값"), str) or not row["값"].isdecimal()):
            raise ValueError("language pack '수량표현' must list entries with 말, 연산 and 값")
        for word in row["말"]:
            if word in table:
                raise ValueError("'수량표현' lists '%s' twice" % word)
            table[word] = {"연산": row["연산"], "값": row["값"]}
    return table


def _validate_actor_targets(declared):
    """행위자 표지가 붙은 대상명을 어느 상태 변화에 잇는지 선언한다.

    ``민수가 구슬을 꺼냈다``의 ``민수``는 동작의 행위자이고 ``구슬``은
    움직이는 대상이다. 수량 상태는 둘을 함께 이름으로 쓰므로, 이 선언이 있는
    관계에서만 ``민수 구슬``이라는 상태 대상을 만든다. 모든 주격 명사를
    소유로 바꾸는 규칙이 아니다.
    """
    if not declared:
        return {"relations": [], "joiner": " "}
    if (not isinstance(declared, dict)
            or not isinstance(declared.get("관계", []), list)
            or not all(isinstance(value, str) and value for value in declared["관계"])
            or not isinstance(declared.get("잇기", " "), str)
            or not declared.get("잇기", " ")):
        raise ValueError("language pack '행위대상결합' needs a 관계 list and 잇기")
    return {"relations": list(declared["관계"]), "joiner": declared.get("잇기", " ")}


def _validate_possessor(declared):
    """A stated count whose counted name starts with a marked owner (`하루는 구슬`)."""
    if not declared:
        return {}
    if (not isinstance(declared, dict)
            or not isinstance(declared.get("관계"), list) or not declared["관계"]
            or not all(isinstance(value, str) and value for value in declared["관계"])
            or not isinstance(declared.get("조사"), list) or not declared["조사"]
            or not all(isinstance(value, str) and value for value in declared["조사"])):
        raise ValueError("language pack '소유자리' needs a 관계 list and a 조사 list")
    return {"relations": list(declared["관계"]),
            "particles": sorted(declared["조사"], key=len, reverse=True),
            "min_length": int(declared.get("최소글자", 1))}


def _validate_quantity_chain(declared):
    """수량의 시작값·연쇄 변화·남은 양 물음을 한 구조로 선언한다."""
    empty = {"units": [], "from_markers": [], "initial_forms": [], "object_particles": [], "joiners": [],
             "operations": [], "query_prefixes": [], "query_forms": [], "query_particles": [],
             "query_render": []}
    if not declared:
        return empty
    if not isinstance(declared, dict):
        raise ValueError("language pack '수량연쇄' must be an object")
    names = {"units": "단위", "from_markers": "시작연결", "object_particles": "수량조사",
             "joiners": "이어말", "query_prefixes": "물음앞말", "query_forms": "물음꼴",
             "query_particles": "물음조사", "query_render": "답"}
    result = {}
    for target, source in names.items():
        values = declared.get(source, [])
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            raise ValueError("language pack 수량연쇄.%s is malformed" % source)
        result[target] = list(values)
    initial_forms = declared.get("시작꼴", [])
    if (not isinstance(initial_forms, list)
            or any(not isinstance(row, dict)
                   or not isinstance(row.get("물건조사", []), list) or not row["물건조사"]
                   or not isinstance(row.get("꼬리", []), list) or not row["꼬리"]
                   or not all(isinstance(value, str) and value
                              for value in row["물건조사"] + row["꼬리"])
                   for row in initial_forms)):
        raise ValueError("language pack 수량연쇄.시작꼴 is malformed")
    result["initial_forms"] = [{"item_particles": list(row["물건조사"]),
                                "tails": list(row["꼬리"])} for row in initial_forms]
    operations = declared.get("동작", [])
    if (not isinstance(operations, list) or not operations
            or any(not isinstance(row, dict) or not isinstance(row.get("관계"), str) or not row["관계"]
                   or not isinstance(row.get("꼴", []), list) or not row["꼴"]
                   or not all(isinstance(value, str) and value for value in row["꼴"])
                   for row in operations)):
        raise ValueError("language pack 수량연쇄.동작 is malformed")
    result["operations"] = [{"predicate": row["관계"], "forms": list(row["꼴"])}
                            for row in operations]
    return result


def _validate_event_domains(declared):
    if not declared:
        return []
    if not isinstance(declared, list):
        raise ValueError("language pack event_domains must be a list")
    names = set()
    rows = []
    for row in declared:
        predicates = row.get("effect_predicates", []) if isinstance(row, dict) else []
        operations = row.get("operations", []) if isinstance(row, dict) else []
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]
                or row["name"] in names or not isinstance(predicates, list) or not isinstance(operations, list)
                or not (predicates or operations)
                or not all(isinstance(value, str) and value for value in predicates + operations)):
            raise ValueError("invalid event_domains declaration")
        names.add(row["name"])
        rows.append({"name": row["name"], "effect_predicates": list(predicates),
                     "operations": list(operations)})
    return rows


@lru_cache(maxsize=8)
def _cached_reasoning_language(path, stamp, size):
    with Path(path).open(encoding="utf-8") as handle:
        pack = json.load(handle)
    return {"clauses": _validate_clauses(pack.get("문장분리", {})),
            "inflection": pack.get("활용", {}),
            "fillers": pack.get("군말", {}),
            "slot_particles": _validate_slot_particles(pack.get("자리조사", [])),
            "case_particles": _validate_particles(pack.get("조사", [])),
            "negation": _validate_negation(pack.get("부정", {})),
            "negation_marker": _validate_negation_marker(pack.get("부정표지")),
            "placeholders": _validate_placeholders(pack.get("자리말", [])),
            "doer_particle": pack.get("임자조사", ""),
            "speaker_placeholder": pack.get("임자자리말", ""),
            "actor_targets": _validate_actor_targets(pack.get("행위대상결합", {})),
            "possessor": _validate_possessor(pack.get("소유자리", {})),
            "count_question": dict(pack.get("수량물음", {})) if isinstance(pack.get("수량물음"), dict) else {},
            "name_reply": dict(pack.get("이름답", {})) if isinstance(pack.get("이름답"), dict) else {},
            "contrast_correction": dict(pack.get("대조정정", {})) if isinstance(pack.get("대조정정"), dict) else {},
            "quantities": _validate_quantities(pack.get("수량표현", [])),
            "quantity_chain": _validate_quantity_chain(pack.get("수량연쇄", {})),
            "event_domains": _validate_event_domains(pack.get("event_domains", [])),
            "pointers": list(pack.get("지시어", [])),
            "person_pointers": list(pack.get("사람지시어", [])),
            "plan": dict(pack.get("계획", {})),
            "slot_questions": dict(pack.get("자리물음", {})),
            "short_tails": list(pack.get("짧은답꼬리", [])),
            "scope_words": dict(pack.get("범위답", {})),
            "target_words": dict(pack.get("정정대상답", {})),
            "relation_choice_words": dict(pack.get("관계선택답", {})),
            "repair": _validate_repair(pack.get("수선", {})),
            "particle_mates": dict(pack.get("조사짝", {})),
            "romanization": {k: v for k, v in pack.get("로마자", {}).items() if not k.startswith("_")},
            "senses": dict(pack.get("뜻고리", {}).get("words", {})),
            "ellipsis": _validate_ellipsis(pack.get("생략", {})),
            "particle_exceptions": dict(pack.get("조사예외", {})),
            "name_suffix": str(pack.get("이름꼬리", {}).get("꼬리", "")) if isinstance(pack.get("이름꼬리"), dict) else "",
            "noun_number": dict(pack.get("명사수", {})) if isinstance(pack.get("명사수"), dict) else {},
            "counters": ({"units": list(pack["수량단위"].get("단위", [])),
                          "askers": list(pack["수량단위"].get("물음말", [])),
                          "attach": list(pack["수량단위"].get("붙는조사", []))}
                         if isinstance(pack.get("수량단위"), dict) else {}),
            "same_frame": [dict(row) for row in pack.get("같은틀", []) if isinstance(row, dict)],
            "phrase_variants": [dict(row) for row in pack.get("말바꿈", []) if isinstance(row, dict)],
            "particle_variants": [dict(row) for row in pack.get("조사바꿈", []) if isinstance(row, dict)],
            "role_swaps": [dict(row) for row in pack.get("역할바꿈", []) if isinstance(row, dict)],
            "object_fronting": dict(pack.get("어순바꿈", {})) if isinstance(pack.get("어순바꿈"), dict) else {},
            "comparison": dict(pack.get("비교물음", {})) if isinstance(pack.get("비교물음"), dict) else {},
            "passive": dict(pack.get("수동태", {})) if isinstance(pack.get("수동태"), dict) else {},
            "request": dict(pack.get("요청", {})) if isinstance(pack.get("요청"), dict) else {},
            "outside_names": list(pack.get("이름밖", [])) if isinstance(pack.get("이름밖"), list) else [],
            "why_count": dict(pack.get("수량이유물음", {})) if isinstance(pack.get("수량이유물음"), dict) else {},
            "holder_forms": dict(pack.get("가진쪽꼴", {})) if isinstance(pack.get("가진쪽꼴"), dict) else {},
            "word_order_forms": dict(pack.get("말자리", {})) if isinstance(pack.get("말자리"), dict) else {}}


def load_clause_grammar(language: str | None = None) -> dict[str, Any]:
    """Read the selected style's optional clause rules, including legacy styles.

    The cache follows file revisions, not just the selected name. An absent
    clause section is empty; it never inherits Korean rules from another file.
    """
    return load_reasoning_language(language)["clauses"]


def load_reasoning_language(language: str | None = None) -> dict[str, Any]:
    """Only the optional components needed for symbolic language analysis."""
    path = _language_path(language)
    stat = path.stat()
    return _cached_reasoning_language(str(path), stat.st_mtime_ns, stat.st_size)


def load_language_pack(language: str | None = None) -> dict[str, Any]:
    """언어 이름 또는 JSON 경로 하나로 대화 설정을 읽는다."""
    path = _language_path(language)
    with path.open(encoding="utf-8") as handle:
        pack = json.load(handle)
    return decode_language_pack(pack, str(path))


def _validate_ellipsis(declared):
    """Which omissions the language allows the reader to fill, and from where."""
    if not isinstance(declared, dict):
        raise ValueError("ellipsis must be an object")
    allowed = {"coordination": {"trailing_words"}, "part_reference": {"leading_words"}, "scope": {"turn"},
               "thing_reference": {"trailing_word"},
               "gapping": {"first_conjunct_verb"}, "counted_noun": {"after_numeral"}}
    for key, value in declared.items():
        if key.startswith("_"):
            continue
        if key == "topic_continuity":
            if (not isinstance(value, dict) or set(value) - {"item_particles"}
                    or not all(isinstance(p, str) and p for p in value.get("item_particles", []))):
                raise ValueError("invalid ellipsis declaration: topic_continuity")
            continue
        if key not in allowed or value not in allowed[key]:
            raise ValueError("unknown ellipsis declaration: %s" % key)
    return {k: v for k, v in declared.items() if not k.startswith("_")}


REPAIR_OPERATIONS = ("particle_drop", "particle_insert", "particle_move", "token_skip",
                     "adjacent_swap", "ending_restore")


def _validate_repair(declared):
    """Edits that bring an unmatched clause to the nearest declared rule.

    The edit kinds are a closed, language-neutral set; the pack enables them,
    prices them and bounds the total. A clause over the bound is held. The
    report bound only lets a hold say what the nearest reading would need.
    """
    if not declared:
        return {}
    if not isinstance(declared, dict):
        raise ValueError("repair must be an object")
    costs = declared.get("costs", {})
    if (not isinstance(costs, dict) or not costs or set(costs) - set(REPAIR_OPERATIONS)
            or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in costs.values())):
        raise ValueError("repair.costs must price known edit kinds with positive integers")
    bound, reach, budget = declared.get("bound"), declared.get("report_bound"), declared.get("budget")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (bound, reach, budget)) \
            or not 0 < bound <= reach or budget <= 0:
        raise ValueError("repair needs integer bound <= report_bound and a positive budget")
    names = declared.get("names", {})
    if not isinstance(names, dict) or set(names) - set(costs) or not all(isinstance(v, str) for v in names.values()):
        raise ValueError("repair.names must name enabled edit kinds")
    inserts = declared.get("insert_particles", [])
    if not isinstance(inserts, list) or not all(isinstance(v, str) and v for v in inserts):
        raise ValueError("repair.insert_particles must be nonempty strings")
    outside = declared.get("not_in_names", [])
    if not isinstance(outside, list) or not all(isinstance(v, str) and v for v in outside):
        raise ValueError("repair.not_in_names must be nonempty strings")
    protected = declared.get("protected", {})
    if (not isinstance(protected, dict) or set(protected) - {"scope", "negation", "negation_in_names"}
            or not all(isinstance(v, list) and all(isinstance(x, str) and x for x in v)
                       for v in protected.values())):
        raise ValueError("repair.protected lists scope words and negation patterns")
    import re
    for pattern in protected.get("negation", []) + protected.get("negation_in_names", []):
        re.compile(pattern)
    return {"costs": dict(costs), "bound": bound, "report_bound": reach, "budget": budget,
            "names": dict(names), "insert_particles": list(inserts),
            "not_in_names": list(outside), "join": declared.get("join", ", "),
            "hold_max_edits": int(declared.get("hold_max_edits", 1)),
            "protected": {key: list(value) for key, value in protected.items()}}


def _validate_components(declared, source=""):
    """어느 부품을 쓸지는 **팩이 한 곳에서** 말한다.

    환경변수로 고르면 같은 실행 안에서 팩마다 다르게 고를 수가 없고, 팩을 둘
    띄우면 나중에 켠 쪽이 앞엣것의 선택을 덮는다. 값은 `module:Class` 또는
    `module:factory` 이며, 여기서 불러오지는 않는다 — **고른 것만** 쓰는 자리에서
    불러온다.
    """
    if not isinstance(declared, dict):
        raise ValueError("language pack '부품' must be an object: %s" % source)
    for kind, spec in declared.items():
        if not isinstance(kind, str) or not kind:
            raise ValueError("language pack '부품' names must be strings: %s" % source)
        if not isinstance(spec, str) or spec.count(":") != 1 or not all(spec.split(":")):
            raise ValueError("'부품' '%s' must have the form 'module:Class': %s" % (kind, source))
    return dict(declared)


def _validate_encoder(declared, source=""):
    """팩 하나가 고르는 경량 인코더의 재현 가능한 설정.

    환경변수는 개발 기본값으로만 남긴다. 팩 선언은 인코더 이름 대신
    실행에 영향을 주는 모든 숫자를 함께 기록해, 같은 프로세스의 다른 팩과
    섞이지 않게 한다. 신경망 모델명·원격 URL은 허용하지 않는다.
    """
    if not declared:
        return {}
    if not isinstance(declared, dict):
        raise ValueError("language pack '인코더' must be an object: %s" % source)
    allowed = {"mode", "dimensions", "jamo_weight", "smoothing", "route_threshold",
               "cluster_threshold", "goal_similarity_threshold", "device"}
    if set(declared) - allowed:
        raise ValueError("language pack '인코더' has unknown settings: %s" % source)
    mode = declared.get("mode", "문자")
    if mode not in {"문자", "신경망"}:
        raise ValueError("인코더.mode must be 문자 or 신경망: %s" % source)
    dimensions = declared.get("dimensions", 4096)
    if not isinstance(dimensions, int) or not 256 <= dimensions <= 65536:
        raise ValueError("인코더.dimensions must be an integer in 256..65536: %s" % source)
    for key in ("jamo_weight", "smoothing", "route_threshold", "cluster_threshold",
                "goal_similarity_threshold"):
        value = declared.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                  or not 0 <= float(value) <= 1):
            raise ValueError("인코더.%s must be a number in 0..1: %s" % (key, source))
    if "device" in declared and declared["device"] != "cpu":
        raise ValueError("인코더.device allows only cpu: %s" % source)
    return dict(declared)


def decode_language_pack(pack: dict, source: str = "") -> dict[str, Any]:
    """Decode in-memory pack content. Never consult paths or environment here."""
    path = Path(source)
    conversation = pack.get("대화이해", pack.get("conversation", {}))
    if not isinstance(conversation, dict):
        raise ValueError("language pack needs a '대화이해' or 'conversation' object: %s" % path)
    shell_risks = conversation.get("shell_risks", {})
    if not isinstance(shell_risks, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                                    for key, value in shell_risks.items()):
        raise ValueError("language pack shell_risks must map strings to strings: %s" % path)
    templates = conversation.get("templates", [])
    if not isinstance(templates, list):
        raise ValueError("language pack templates must be a list: %s" % path)
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError("language pack template entries must be objects: %s" % path)
        types = item.get("slot_types", {})
        if not isinstance(types, dict) or not all(isinstance(key, str) and value in {"text", "integer"}
                                                   for key, value in types.items()):
            raise ValueError("language pack slot_types must map slot names to text/integer: %s" % path)
    external_retrieval = pack.get("외부조사", {})
    if not isinstance(external_retrieval, dict):
        raise ValueError("language pack '외부조사' must be an object: %s" % path)
    intents = external_retrieval.get("의도", [])
    def valid_intent(item):
        if (not isinstance(item, dict) or not isinstance(item.get("kind"), str) or not item["kind"]
                or not isinstance(item.get("질문표지", []), list)
                or not isinstance(item.get("근거표지", []), list)
                or not all(isinstance(value, str) and value
                           for value in item.get("질문표지", []) + item.get("근거표지", []))):
            return False
        relation = item.get("관계", {})
        if not isinstance(relation, dict):
            return False
        for key in ("질문동작", "근거동작", "값조사", "주어조사", "절잇기"):
            values = relation.get(key, [])
            if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
                return False
        return True
    if not isinstance(intents, list) or not all(valid_intent(item) for item in intents):
        raise ValueError("language pack 외부조사.의도 is malformed: %s" % path)
    response_composition = pack.get("응답구성", {})
    if (not isinstance(response_composition, dict)
            or not isinstance(response_composition.get("계획표지", []), list)
            or not all(isinstance(value, str) and value
                       for value in response_composition.get("계획표지", []))):
        raise ValueError("language pack 응답구성.계획표지 is malformed: %s" % path)
    return {"name": pack.get("이름") or pack.get("name") or path.stem,
            "path": str(path), "conversation": conversation,
            "clauses": _validate_clauses(pack.get("문장분리", {})),
            "inflection": pack.get("활용", {}),
            "fillers": pack.get("군말", {}),
            "particles": pack.get("붙일조사", []),
            # 붙일조사는 답을 쓸 때 이름에 붙이는 조사고, 자리조사는 읽을 때
            # 한 자리를 채울 수 있는 조사 무리다. 두 길이 같은 선언을 보게 한다.
            "slot_particles": _validate_slot_particles(pack.get("자리조사", [])),
            "case_particles": _validate_particles(pack.get("조사", [])),
            "negation": _validate_negation(pack.get("부정", {})),
            "negation_marker": _validate_negation_marker(pack.get("부정표지")),
            "placeholders": _validate_placeholders(pack.get("자리말", [])),
            "doer_particle": pack.get("임자조사", ""),
            "speaker_placeholder": pack.get("임자자리말", ""),
            "actor_targets": _validate_actor_targets(pack.get("행위대상결합", {})),
            "possessor": _validate_possessor(pack.get("소유자리", {})),
            "count_question": dict(pack.get("수량물음", {})) if isinstance(pack.get("수량물음"), dict) else {},
            "name_reply": dict(pack.get("이름답", {})) if isinstance(pack.get("이름답"), dict) else {},
            "contrast_correction": dict(pack.get("대조정정", {})) if isinstance(pack.get("대조정정"), dict) else {},
            "quantities": _validate_quantities(pack.get("수량표현", [])),
            "quantity_chain": _validate_quantity_chain(pack.get("수량연쇄", {})),
            "event_domains": _validate_event_domains(pack.get("event_domains", [])),
            "pointers": list(pack.get("지시어", [])),
            "person_pointers": list(pack.get("사람지시어", [])),
            "plan": dict(pack.get("계획", {})),
            "slot_questions": dict(pack.get("자리물음", {})),
            "short_tails": list(pack.get("짧은답꼬리", [])),
            "scope_words": dict(pack.get("범위답", {})),
            "target_words": dict(pack.get("정정대상답", {})),
            "relation_choice_words": dict(pack.get("관계선택답", {})),
            "repair": _validate_repair(pack.get("수선", {})),
            "particle_mates": dict(pack.get("조사짝", {})),
            "romanization": {k: v for k, v in pack.get("로마자", {}).items() if not k.startswith("_")},
            "senses": dict(pack.get("뜻고리", {}).get("words", {})),
            "ellipsis": _validate_ellipsis(pack.get("생략", {})),
            "particle_exceptions": dict(pack.get("조사예외", {})),
            "name_suffix": str(pack.get("이름꼬리", {}).get("꼬리", "")) if isinstance(pack.get("이름꼬리"), dict) else "",
            "noun_number": dict(pack.get("명사수", {})) if isinstance(pack.get("명사수"), dict) else {},
            "counters": ({"units": list(pack["수량단위"].get("단위", [])),
                          "askers": list(pack["수량단위"].get("물음말", [])),
                          "attach": list(pack["수량단위"].get("붙는조사", []))}
                         if isinstance(pack.get("수량단위"), dict) else {}),
            "same_frame": [dict(row) for row in pack.get("같은틀", []) if isinstance(row, dict)],
            "phrase_variants": [dict(row) for row in pack.get("말바꿈", []) if isinstance(row, dict)],
            "particle_variants": [dict(row) for row in pack.get("조사바꿈", []) if isinstance(row, dict)],
            "role_swaps": [dict(row) for row in pack.get("역할바꿈", []) if isinstance(row, dict)],
            "object_fronting": dict(pack.get("어순바꿈", {})) if isinstance(pack.get("어순바꿈"), dict) else {},
            "comparison": dict(pack.get("비교물음", {})) if isinstance(pack.get("비교물음"), dict) else {},
            "passive": dict(pack.get("수동태", {})) if isinstance(pack.get("수동태"), dict) else {},
            "request": dict(pack.get("요청", {})) if isinstance(pack.get("요청"), dict) else {},
            "outside_names": list(pack.get("이름밖", [])) if isinstance(pack.get("이름밖"), list) else [],
            "why_count": dict(pack.get("수량이유물음", {})) if isinstance(pack.get("수량이유물음"), dict) else {},
            "holder_forms": dict(pack.get("가진쪽꼴", {})) if isinstance(pack.get("가진쪽꼴"), dict) else {},
            "word_order_forms": dict(pack.get("말자리", {})) if isinstance(pack.get("말자리"), dict) else {},
            "relations": pack.get("관계해석", {}),
            "external_retrieval": {"intents": [dict(item) for item in intents]},
            "response_composition": {"plan_markers": list(response_composition.get("계획표지", []))},
            "question_templates": list(pack.get("질문틀", [])),
            "strip_particles": list(pack.get("떼는조사", [])),
            "learning_question_endings": list(pack.get("학습질문종결", [])),
            "learning_topic_exclusions": list(pack.get("학습주제제외", [])),
            "search_stopwords": list(pack.get("검색불용어", [])),
            "components": _validate_components(pack.get("부품", {}), path),
            "encoder": _validate_encoder(pack.get("인코더", pack.get("encoder", {})), path),
            "document_kinds": pack.get("문서분류", {}),
            "verbal_expressions": pack.get("말수식", {}),
            "output_contracts": pack.get("출력계약", {}),
            "state_answers": pack.get("상태표현", {}),
            # 답하지 못할 때의 말. 모르는 것·못 하는 것·딴 이야기를 갈라 말한다.
            "refusals": {k: v for k, v in pack.get("답못함", {}).items() if not k.startswith("_")}}


def _template_match(text: str, template: str, slot_types: dict[str, str] | None = None) -> dict[str, str] | None:
    """언어 팩의 슬롯 타입을 지키며 선언형 템플릿을 캡처한다."""
    pieces: list[tuple[str, str | None]] = []
    cursor = 0
    while cursor < len(template):
        opening = template.find("{", cursor)
        if opening < 0:
            pieces.append((template[cursor:], None)); break
        if opening > cursor:
            pieces.append((template[cursor:opening], None))
        closing = template.find("}", opening + 1)
        if closing < 0:
            return None
        slot = template[opening + 1:closing].strip()
        if not slot:
            return None
        pieces.append(("", slot)); cursor = closing + 1
    if not pieces:
        return None
    types = slot_types or {}

    def match(index: int, position: int, values: dict[str, str]) -> dict[str, str] | None:
        if index == len(pieces):
            return values if position == len(text) else None
        literal, slot = pieces[index]
        if slot is None:
            return match(index + 1, position + len(literal), values) if text.startswith(literal, position) else None
        # 다음 고정 조각의 모든 위치를 시도한다. `{a} {b}`처럼 공백이 여러 번
        # 나오는 언어에서도 뒤쪽 슬롯까지 맞는 해석만 선택한다.
        next_literal = next((value for value, next_slot in pieces[index + 1:] if next_slot is None and value), "")
        ends = [len(text)] if not next_literal else []
        if next_literal:
            cursor = position
            while True:
                cursor = text.find(next_literal, cursor)
                if cursor < 0:
                    break
                ends.append(cursor); cursor += 1
        for end in ends:
            value = text[position:end].strip()
            if not value:
                continue
            if types.get(slot) == "integer" and not value.isdecimal():
                continue
            result = match(index + 1, end, {**values, slot: value})
            if result is not None:
                return result
        return None
    return match(0, 0, {})


class TemplateBackend:
    """의존성 없는 기본 부품. 모든 언어 지식은 팩의 템플릿에 있다."""
    component_id = "template-language-pack-v1"

    def parse(self, text: str, pack: dict[str, Any]) -> dict[str, Any] | None:
        templates = pack.get("conversation", {}).get("templates") or []
        best: tuple[int, dict[str, Any]] | None = None
        for item in templates:
            if not isinstance(item, dict) or not isinstance(item.get("template"), str):
                continue
            slots = _template_match(text, item["template"], item.get("slot_types"))
            if slots is None:
                continue
            literal_size = len(item["template"]) - sum(len(key) + 2 for key in slots)
            candidate = dict(item.get("result") or {})
            candidate["slots"], candidate["evidence"] = slots, [item["template"]]
            if best is None or literal_size > best[0]:
                best = (literal_size, candidate)
        for item in pack.get("conversation", {}).get("phrases") or []:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or item["text"] != text:
                continue
            candidate = dict(item.get("result") or {})
            candidate["slots"], candidate["evidence"] = {}, [item["text"]]
            if best is None or len(item["text"]) > best[0]:
                best = (len(item["text"]), candidate)
        return best[1] if best else None


def resolve_backend(backend: DialogueBackend | None = None, pack: dict[str, Any] | None = None) -> DialogueBackend:
    """명시 주입이 우선이며, 그 밖에는 언어 팩이 고른 부품을 불러온다.

    ``backend`` 값은 ``module:Class`` 또는 ``module:factory`` 형식이다. factory는
    인자 없이 backend를 반환해야 한다. 팩에 지정하지 않으면 의존성 없는 기본
    템플릿 부품을 쓴다.
    """
    if backend is not None:
        return backend
    spec = ((pack or {}).get("conversation", {}).get("backend"))
    if not isinstance(spec, str) or not spec:
        return TemplateBackend()
    module_name, separator, member_name = spec.partition(":")
    if not separator or not module_name or not member_name:
        raise ValueError("dialogue backend must have the form 'module:Class' or 'module:factory'")
    component = getattr(importlib.import_module(module_name), member_name)
    instance = component() if callable(component) else component
    if not callable(getattr(instance, "parse", None)):
        raise TypeError("dialogue backend needs a parse(text, pack) method")
    return instance
