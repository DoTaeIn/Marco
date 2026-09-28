"""R8: zero language-specific literals in the realization-path files.

Files, fixed at R0: every ``.py`` under ``marco/language/``.

Two counts over string constants outside docstrings:

1. the pattern count of docs/ko/언어-기능차이-측정.md: Hangul words in string
   constants (patterns, comparisons, anything);
2. surface forms: a constant equal to a form a realizer file declares as
   surface (a word, stem, particle, ending piece, counter, number word,
   determiner, preposition, separator, quote, symbol, punctuation), or any
   constant containing whitespace. A constant used only as a key
   (``d["key"]``, ``d.get("key")``, ``{"key": ...}``) is a key, not a surface.
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "marco" / "language"
HANGUL_WORD = re.compile("[가-힣ㄱ-ㆎ]+")
def files():
    """The realization path fixed at R0. The file moves put the reader's own modules (hangul, frames,
    numerals ...) beside it under marco/language; the target map names them, and they are not on the path."""
    moved = json.loads((ROOT / "docs" / "architecture" / "target-map.json").read_text(encoding="utf-8"))
    beside = {ROOT.joinpath(*target.split(".")).with_suffix(".py") for target in moved["modules"].values()}
    return sorted(path for path in PACKAGE.rglob("*.py") if path not in beside)


def surface_forms():
    """Every form a realizer file declares as something to say, read from its declared place."""
    forms = set()

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    for path in (PACKAGE / "realizer").glob("*.json"):
        if path.name == "meaning.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        ortho = {k: v for k, v in data["orthography"].items() if not k.startswith("_") and k not in (
            "initial_capital", "name_case", "latin_codas", "digit_codas")}
        compound = ortho.pop("compound", {})
        forms.update(strings(ortho))
        forms.update(v for k, v in compound.items() if not k.startswith("_") and k != "join")
        for entry in data["lexicon"].values():
            forms.update(entry[key] for key in ("word", "verb") if key in entry)
        forms.update(strings(data.get("lexicon_forms", {})))
        for spec in data["cases"].values():
            forms.update(spec[key] for key in ("form", "before") if key in spec)
        forms.update(spec["form"] for spec in data.get("counters", {}).values())
        forms.update(strings(data.get("determiners", {})))
        forms.update(strings(data.get("relation_words", {})))
        forms.update(strings((data.get("numbers") or {}).get("words", {})))
        grammar = data.get("grammar", {})
        for rules in grammar.get("endings", {}).values():
            for rule in rules:
                for step in rule.get("steps", []):
                    forms.update(step[key] for key in ("text", "open", "closed") if key in step)
        for spec in grammar.get("negation", {}).values():
            forms.update(spec[key] for key in ("connective", "aux", "word") if key in spec)
        copula = grammar.get("copula") or {}
        forms.update(copula[key] for key in ("stem",) if key in copula)
        forms.update(strings(copula.get("after_open", {})))
        forms.update(strings(copula.get("after_closed", {})))
    return forms


def constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)}
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            keys.add(id(node.slice))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                node.func.attr in ("get", "setdefault", "pop") and node.args and isinstance(node.args[0], ast.Constant):
            keys.add(id(node.args[0]))
        elif isinstance(node, ast.Dict):
            keys.update(id(k) for k in node.keys if isinstance(k, ast.Constant))
        elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant) and \
                all(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            keys.add(id(node.left))          # "key" in mapping
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            out.append((node.lineno, node.value, id(node) in keys))
    return out


def count(path, forms):
    hangul, surface = [], []
    for line, value, is_key in constants(path):
        hangul += [(line, word) for word in HANGUL_WORD.findall(value)]
        if re.search(r"\s", value) or (value in forms and not is_key):
            surface.append((line, value))
    return hangul, surface


def test_the_realization_path_files_are_the_ones_fixed_at_r0():
    names = [str(p.relative_to(ROOT)) for p in files()]
    assert "marco/language/__init__.py" in names and "marco/language/realizer/__init__.py" in names
    assert all(name.startswith("marco/language/") for name in names)


def test_zero_language_literals_in_the_realization_path():
    forms = surface_forms()
    assert {"개", "입니다", "the", "에게", "."} & forms == {"개", "the", "에게", "."}
    report = {str(p.relative_to(ROOT)): count(p, forms) for p in files()}
    offenders = {name: found for name, found in report.items() if found[0] or found[1]}
    assert offenders == {}


def test_the_measure_sees_a_literal_when_there_is_one(tmp_path):
    forms = surface_forms()
    planted = tmp_path / "planted.py"
    planted.write_text('def f(x):\n    return x + "개" + " " + "the" + x["the"]\n', encoding="utf-8")
    hangul, surface = count(planted, forms)
    assert [word for _line, word in hangul] == ["개"]
    assert sorted(value for _line, value in surface) == [" ", "the", "개"]
