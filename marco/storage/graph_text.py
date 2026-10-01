"""MARCO ``.kg`` graph text: read into ``read_kg``'s dictionary, and written back.

The merged base-plus-overlay view (``marco/storage/graph_view.py``) is a graph
dictionary; the engine reads ``.kg`` text files. This module turns one into the
other, so a graph the overlay touches can be written out as text the engine reads.

* :func:`parse` is the parsing part of ``engine.read_kg`` for text held in memory
  (a pack member): the same sections, header keys, node annotations, defaults,
  dictionary insertion order and value types. It leaves out the merge of shared
  hypernym edges from ``data/개념망.json`` that ``read_kg`` does at the end, as
  ``mco.native.kgtext.parse_kg`` does; the engine adds them again when it reads the
  written text. ``tests/test_overlay_graph_text.py`` compares it with
  ``mco.native.kgtext.parse_kg`` for every graph in ``graphs/``.
* :func:`write` is the inverse: graph dictionary -> ``.kg`` text. It checks its own
  output by parsing it again and raises :class:`GraphTextError` when the text would
  not read back equal (a name holding ``:`` or ``#``, an example holding ``|``, ...).
  :func:`unwritable` gives that reason without raising.

Standard library only; nothing here imports ``mco`` or the engine.
"""
from __future__ import annotations

import re

__all__ = ["GraphTextError", "parse", "write", "unwritable", "POS", "NEG", "LAYER_KEYS", "SLOT_KEYS"]

# engine.POS, engine.NEG and the initial dictionary of engine.read_kg.
POS = ("증명", "충족")
NEG = ("부정",)
LAYER_KEYS = ("공통층", "사례층", "무관층")
SLOT_KEYS = ("수치조건", "값받이", "값옮김", "값셈", "물음", "되물음", "출처")

_ARROW = re.compile(r"\s*(?:-+|→)\s*(\S+?)\s*(?:-+>|→)\s*")
_numeric = re.compile(r"^(.*?)\s*\{\s*(\S*?)\s*(>=|<=)\s*([\d.]+)\s*\}$")
_move_value = re.compile(r"^(.*?)\s*\{\s*(\S+?)\s*<-\s*(\S+?)\s*\}$")
_value_sink = re.compile(r"^(.*?)\s*\{\s*(\S+?)\s*\}$")
_eval_value = re.compile(r"^(.*?)\s*\{\s*(\S+?)\s*(?<![<>])=\s*(.+?)\s*\}$")
_SECTIONS = ("개념", "사례", "무관", "논증", "대사", "개념망", "공리", "물음", "되물음")
_LAYER_OF = {"개념": "공통층", "사례": "사례층", "무관": "무관층", "공리": "공통층"}
_HEADER_LISTS = ("전진관계", "부정관계", "근거관계", "맡음")


class GraphTextError(ValueError):
    """The text is not a graph ``read_kg`` accepts, or a graph has no exact ``.kg`` text."""


def _defaults():
    return {"역할": "", "목표": "", "임계값": {"A_MIN": 0.50, "OK_MIN": 0.60},
            "이름말": "용어", "색인": "예", "언어": "한국어",
            "전진관계": list(POS), "부정관계": list(NEG),
            "대사": {}, "공통층": {}, "사례층": {}, "무관층": {},
            "수치조건": {}, "값받이": {}, "값옮김": {}, "값셈": {}, "물음": {}, "되물음": {},
            "엣지": [], "개념엣지": [], "포함": [], "공리": []}


def _lines(data):
    # read_kg iterates a text-mode file: strict UTF-8 and universal newlines.
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def parse(data, name="<graph>"):
    """The graph dictionary of ``.kg`` text ``data`` (bytes or str), as ``read_kg``
    returns it without the shared hypernym merge. Raises :class:`GraphTextError`."""
    try:
        return _parse(data, name)
    except GraphTextError:
        raise
    except ValueError as exc:                    # UnicodeDecodeError, float() failures
        raise GraphTextError("%s: %s" % (name, exc)) from exc


def _parse(data, name):
    g = _defaults()
    section = None

    def error(i, line, why):
        return GraphTextError("%s:%d  %s\n    %s" % (name, i, why, line))

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
        if section is None:
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
                    raise error(i, head, "%s needs at least one relation" % key)
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
                raise error(i, head, "%s is 'key: text'" % section)
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
        else:
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


# --- writing ---------------------------------------------------------------------------

def _number(value):
    return repr(float(value))


def _annotation(g, name):
    if name in g.get("수치조건", {}):
        cond = g["수치조건"][name]
        sign, value = (">=", cond["최소"]) if "최소" in cond else ("<=", cond["최대"])
        return " {%s %s %s}" % (cond.get("단위", ""), sign, _number(value))
    if name in g.get("값옮김", {}):
        a, b = g["값옮김"][name]
        return " {%s <- %s}" % (a, b)
    if name in g.get("값셈", {}):
        var, expr = g["값셈"][name]
        return " {%s = %s}" % (var, expr)
    if name in g.get("값받이", {}):
        return " {%s}" % g["값받이"][name]
    return ""


def _node_line(g, name, examples):
    src = (g.get("출처") or {}).get(name)
    head = name + ("@" + src if src else "") + _annotation(g, name)
    return "%s: %s" % (head, " | ".join('"%s"' % x for x in examples))


def _text(g):
    """``.kg`` text for graph dictionary ``g`` (no check; see :func:`write`)."""
    base = _defaults()
    out = []
    for key in g:
        value = g[key]
        if key in ("역할", "목표", "이름말", "색인", "언어"):
            if value != base[key]:
                out.append("%s: %s" % (key, value))
        elif key == "임계값":
            if value != base[key]:
                out.append("임계값: %s / %s" % (_number(value["A_MIN"]), _number(value["OK_MIN"])))
        elif key in _HEADER_LISTS:
            if key in base and value == base[key]:
                continue
            out.append("%s: %s" % (key, ", ".join(value)))
        elif key == "포함":
            if value:
                out.append("포함: %s" % ", ".join(value))
    axioms = list(g.get("공리") or [])
    section = None
    for name, examples in (g.get("공통층") or {}).items():
        wanted = "공리" if name in axioms else "개념"
        for _ in range(max(1, axioms.count(name)) if wanted == "공리" else 1):
            if section != wanted:
                out += ["", "[%s]" % wanted]
                section = wanted
            out.append(_node_line(g, name, examples))
    for layer, title in (("사례층", "사례"), ("무관층", "무관")):
        if g.get(layer):
            out += ["", "[%s]" % title]
            out += [_node_line(g, name, examples) for name, examples in g[layer].items()]
    for key, title in (("엣지", "논증"), ("개념엣지", "개념망")):
        if g.get(key):
            out += ["", "[%s]" % title]
            out += ["%s -%s-> %s" % tuple(edge) for edge in g[key]]
    for key in ("되물음", "물음", "대사"):
        if g.get(key):
            out += ["", "[%s]" % key]
            out += ["%s: %s" % item for item in g[key].items()]
    return "\n".join(out) + "\n"


def _comparable(g):
    """The part of ``g`` that ``read_kg`` gives back: its keys, without the engine's own
    additions (``adj``, ``vec``, ...) that ``engine.load`` makes after reading."""
    keys = set(_defaults()) | {"근거관계", "맡음", "출처"}
    return {k: v for k, v in g.items() if k in keys}


def unwritable(g):
    """Why graph ``g`` has no ``.kg`` text that reads back equal to it, or ``None``."""
    try:
        write(g)
    except GraphTextError as exc:
        return str(exc)
    return None


def write(g, name="<graph>"):
    """``.kg`` text for graph dictionary ``g`` (the shape :func:`parse` and ``read_kg``
    return). The text is parsed again; if it does not read back equal to ``g``, this
    raises :class:`GraphTextError` naming what differs."""
    want = _comparable(g)
    try:
        text = _text(want)
    except (KeyError, TypeError, ValueError) as exc:
        raise GraphTextError("%s: not a graph dictionary (%s: %s)" % (name, type(exc).__name__, exc)) from None
    try:
        got = parse(text, name)
    except GraphTextError as exc:
        raise GraphTextError("%s: its .kg text does not parse (%s)" % (name, str(exc).splitlines()[0])) from None
    if got != want:
        differ = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
        raise GraphTextError("%s: its .kg text does not read back equal (%s)" % (name, ", ".join(differ)))
    return text
