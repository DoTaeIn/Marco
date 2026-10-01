"""MARCO ``.kg`` graph text, read into the dictionary MARCO's ``read_kg`` returns.

The writer of MCO Format 1 builds the node and edge tables from this; it lives
in ``mco`` because ``mco`` does not import MARCO. It is a line-for-line port of
the parsing part of ``engine.read_kg``: the same sections, header keys, node
annotations, defaults, error cases, dictionary insertion order and value types
(``값옮김`` and ``값셈`` values are tuples, thresholds are floats).

What it leaves out on purpose: ``read_kg`` ends by merging hypernym edges from
``data/개념망.json`` of the engine checkout (``_merge_shared_net``). That file is
not part of the graph and not a pack member, so its edges are not graph content
and are not stored. ``tests/test_mco_native_tables.py`` compares this parser,
through the tables, with ``engine.read_kg`` for every graph in ``graphs/``.

Standard library only. Nothing in the text is executed.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = ["KgTextError", "parse_kg", "LAYER_KEYS", "SLOT_KEYS", "TOP_KEYS", "POS", "NEG"]

# MARCO's defaults (engine.POS, engine.NEG, and the initial dictionary of read_kg).
POS = ("증명", "충족")
NEG = ("부정",)
LAYER_KEYS = ("공통층", "사례층", "무관층")
#: Node-keyed dictionaries other than the layers, in the order read_kg creates them.
SLOT_KEYS = ("수치조건", "값받이", "값옮김", "값셈", "물음", "되물음", "출처")
#: The keys every read_kg result has, in insertion order.
TOP_KEYS = ("역할", "목표", "임계값", "이름말", "색인", "언어", "전진관계", "부정관계", "대사",
            "공통층", "사례층", "무관층", "수치조건", "값받이", "값옮김", "값셈", "물음", "되물음",
            "엣지", "개념엣지", "포함", "공리")

_ARROW = re.compile(r"\s*(?:-+|→)\s*(\S+?)\s*(?:-+>|→)\s*")
_numeric = re.compile(r"^(.*?)\s*\{\s*(\S*?)\s*(>=|<=)\s*([\d.]+)\s*\}$")
_move_value = re.compile(r"^(.*?)\s*\{\s*(\S+?)\s*<-\s*(\S+?)\s*\}$")
_value_sink = re.compile(r"^(.*?)\s*\{\s*(\S+?)\s*\}$")
_eval_value = re.compile(r"^(.*?)\s*\{\s*(\S+?)\s*(?<![<>])=\s*(.+?)\s*\}$")
_SECTIONS = ("개념", "사례", "무관", "논증", "대사", "개념망", "공리", "물음", "되물음")
_LAYER_OF = {"개념": "공통층", "사례": "사례층", "무관": "무관층", "공리": "공통층"}


class KgTextError(ValueError):
    """The text is not a graph ``read_kg`` accepts (``read_kg`` raises too)."""


def _lines(data: bytes) -> list[str]:
    # read_kg iterates a text-mode file: strict UTF-8, universal newlines
    # (CRLF and CR become LF). str.splitlines would split on more characters.
    text = data.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def parse_kg(data: bytes, name: str = "<graph>") -> dict[str, Any]:
    """The graph dictionary of ``.kg`` text ``data``, as ``read_kg`` returns it
    without the shared hypernym merge. Raises :class:`KgTextError`."""
    try:
        return _parse(data, name)
    except KgTextError:
        raise
    except ValueError as exc:                  # includes UnicodeDecodeError, float() failures
        raise KgTextError(f"{name}: {exc}") from exc


def _parse(data: bytes, name: str) -> dict[str, Any]:
    g: dict[str, Any] = {"역할": "", "목표": "", "임계값": {"A_MIN": 0.50, "OK_MIN": 0.60},
                         "이름말": "용어", "색인": "예", "언어": "한국어",
                         "전진관계": list(POS), "부정관계": list(NEG),
                         "대사": {}, "공통층": {}, "사례층": {}, "무관층": {},
                         "수치조건": {}, "값받이": {}, "값옮김": {}, "값셈": {}, "물음": {}, "되물음": {},
                         "엣지": [], "개념엣지": [], "포함": [], "공리": []}
    section = None

    def error(i: int, line: str, why: str) -> KgTextError:
        return KgTextError(f"{name}:{i}  {why}\n    {line}")

    for i, source_text in enumerate(_lines(data), 1):
        line = source_text.split("#")[0].rstrip() if not source_text.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        head = line.strip()
        if head.startswith("[") and head.endswith("]"):
            section = head[1:-1].strip()
            if section not in _SECTIONS:
                raise error(i, head, "unknown section")
            continue

        if section is None:                                   # header
            if ":" not in head:
                raise error(i, head, "a header line is 'key: value'")
            key, value = (x.strip() for x in head.split(":", 1))
            if key == "임계값":
                try:
                    a, b = (float(x) for x in value.replace("/", " ").split())
                except ValueError:
                    raise error(i, head, "임계값 is '0.50 / 0.60'") from None
                g["임계값"] = {"A_MIN": a, "OK_MIN": b}
            elif key == "포함":
                g["포함"] += [x.strip() for x in value.split(",") if x.strip()]
            elif key in ("전진관계", "부정관계", "근거관계"):
                kind = [x.strip() for x in value.split(",") if x.strip()]
                if not kind:
                    raise error(i, head, f"{key} needs at least one relation")
                g[key] = kind
            elif key == "언어":
                g["언어"] = value
            elif key == "색인":
                if value not in ("예", "아니오"):
                    raise error(i, head, "색인 is '예' or '아니오'")
                g["색인"] = value
            elif key == "이름말":
                if value not in ("용어", "문장"):
                    raise error(i, head, "이름말 is '용어' or '문장'")
                g["이름말"] = value
            elif key == "맡음":
                g["맡음"] = [x.strip() for x in value.split(",") if x.strip()]
            elif key in ("역할", "목표"):
                g[key] = value
            else:
                raise error(i, head, "unknown header key")

        elif section in ("되물음", "물음", "대사"):
            if ":" not in head:
                raise error(i, head, f"{section} is 'key: text'")
            key, value = head.split(":", 1)
            g[section][key.strip()] = value.strip()

        elif section in ("개념망", "논증"):
            m = _ARROW.search(head)
            if not m:
                raise error(i, head, "an edge line is 'A -relation-> B'")
            from_node = head[:m.start()].strip()
            relation = m.group(1)
            if section == "개념망" and relation != "상위":
                raise error(i, head, "개념망 knows only the relation '상위'")
            target = g["개념엣지"] if section == "개념망" else g["엣지"]
            for dest in (x.strip() for x in head[m.end():].split(",")):
                if from_node and dest:
                    target.append([from_node, relation, dest])

        else:                                                 # 개념 / 사례 / 무관 / 공리
            if ":" not in head:
                raise error(i, head, "a node line is 'name: \"example\" | \"example\"'")
            node, example = head.split(":", 1)
            node = node.strip().lstrip("*").strip()
            m = _numeric.match(node)
            if m:
                node, unit, sign, value = m.group(1).strip(), m.group(2), m.group(3), float(m.group(4))
                g["수치조건"][node] = {"단위": unit, "최소" if sign == ">=" else "최대": value}
            elif _move_value.match(node):
                m2 = _move_value.match(node)
                node = m2.group(1).strip()
                g["값옮김"][node] = (m2.group(2), m2.group(3))
            elif _eval_value.match(node):
                m4 = _eval_value.match(node)
                node = m4.group(1).strip()
                g["값셈"][node] = (m4.group(2), m4.group(3))
            elif _value_sink.match(node):
                m3 = _value_sink.match(node)
                node = m3.group(1).strip()
                g["값받이"][node] = m3.group(2)
            src = None
            if "@" in node:
                node, src = (x.strip() for x in node.split("@", 1))
            sentences = [x.strip().strip('"') for x in example.split("|") if x.strip()]
            if not sentences:
                raise error(i, head, "a node needs at least one example")
            g[_LAYER_OF[section]][node] = sentences
            if section == "공리":
                g["공리"].append(node)
            if src:
                g.setdefault("출처", {})[node] = src
    return g
