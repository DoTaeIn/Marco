"""Load the realizer's declarations and the language pack pieces it reuses.

Two sources per language, both data:

* ``marco/language/realizer/<stem>.json`` — the realizer's own declarations
  (expressions, lexicon, cases, endings, reading rules);
* the language pack ``styles/<stem>.json`` through its parser — particle
  mates, the inflection grammar, negation, numerals, senses, romanization.

``meaning.json`` holds what is shared by every language.
"""
import copy
import json
import re
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


@lru_cache(maxsize=1)
def meaning_declarations():
    return json.loads((HERE / "meaning.json").read_text(encoding="utf-8"))


def stem_of(language):
    """``styles/english.json`` -> ``english``; a model -> its language; ``None`` -> the declared default."""
    if hasattr(language, "parser") and hasattr(language, "sources"):
        paths = [source["path"] for source in language.sources if source["path"].startswith("styles/")]
        return Path(paths[0]).stem if paths else None
    if not language:
        # The same selection every other language-choosing path makes:
        # NAI_LANGUAGE, then KG_LANG, then the one declared default.
        from language_components import _language_path
        return _language_path(None).stem
    return Path(str(language)).stem


@lru_cache(maxsize=16)
def _declared_pack(stem):
    path = HERE / (stem + ".json")
    if stem == "meaning" or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("pack", "")


def available(stem, model=None):
    """Realizer declarations exist for ``stem`` and its language pack can be read."""
    declared = _declared_pack(stem) if stem else None
    if declared is None:
        return False
    return model is not None or (ROOT / declared).is_file()


class Language:
    """One language: the realizer's declarations and the pack parser's pieces."""

    def __init__(self, stem, declarations=None, model=None):
        self.stem = stem
        self.decl = copy.deepcopy(declarations) if declarations is not None else json.loads(
            (HERE / (stem + ".json")).read_text(encoding="utf-8"))
        if model is None:
            from pack_model import development_model
            model = development_model(stem)
        self.parser = model.parser()
        pack_path = ROOT / self.decl["pack"]
        # The pack's raw declarations, for the one field its loaded component
        # does not carry (the negation marker). A packed model without the file
        # on disk has no marker; the check then reads polarity with the parser.
        self.style = json.loads(pack_path.read_text(encoding="utf-8")) if pack_path.is_file() else {}
        component = self.parser.language_pack
        self.mates = dict(component.get("particle_mates", {}))
        self.mate_exceptions = dict(component.get("particle_exceptions", {}))
        self.pack_negation = dict(component.get("negation", {}))
        self.senses = dict(component.get("senses", {}))
        self.romanization = copy.deepcopy(component.get("romanization", {}))
        self.numerals = copy.deepcopy(self.parser.data.get("numerals", {}))
        # The pack's own negation marker pattern, named by the key the realizer
        # file declares. The semantic check reads polarity with it.
        marker = self.style.get(self.decl.get("negation_marker_key") or "")
        self.negation_marker = re.compile(marker) if isinstance(marker, str) and marker else None
        self.inflection = self._grammar()
        self._pack_words()

    def _pack_words(self):
        """Lexemes the language file takes from the pack's own reply strings.

        ``{"from_pack": {"reply": key, "enclosed": [open, close]}}`` is the text
        the pack's reply ``key`` encloses in those marks (the pack's label for a
        repair, say). The realizer then says the pack's word, whatever it is;
        a pack that renames it renames it here too. A reply without the marks
        leaves the lexeme without a word, and a clause that needs it is not said.
        """
        data = getattr(self.parser, "data", None) or {}
        replies = data.get("context_replies") or {}
        answers = data.get("comparison_answers") or {}
        ortho = self.decl.get("orthography") or {}
        marks = "".join(list(ortho.get("punctuation", {}).values()) + list(ortho.get("symbols", {}).values()))
        variables = tuple(meaning_declarations().get("variable_marks", ()))
        for entry in self.decl.get("lexicon", {}).values():
            spec = entry.get("from_pack") if isinstance(entry, dict) else None
            if not spec:
                continue
            if spec.get("answer"):
                # ``{"answer": key}``: the word the pack's comparison answer ``key`` begins with
                # (its yes or its no). A render that begins with a value has no such word.
                render = answers.get(spec["answer"])
                first = render[0] if isinstance(render, list) and render and isinstance(render[0], str) else ""
                word = first.strip().strip(marks).strip()
                if word and not first.startswith(variables) and len(word.split()) == 1:
                    entry["word"] = word
                continue
            template = replies.get(spec.get("reply"))
            opening, closing = spec.get("enclosed") or (None, None)
            if not isinstance(template, str) or not opening or opening not in template:
                continue
            rest = template.split(opening, 1)[1]
            if closing in rest and rest.split(closing, 1)[0].strip():
                entry["word"] = rest.split(closing, 1)[0].strip()

    def _grammar(self):
        grammar = copy.deepcopy(self.parser.inflection_grammar)
        declared = self.decl.get("grammar", {})
        grammar.setdefault("endings", {}).update(copy.deepcopy(declared.get("endings", {})))
        grammar["kinds"] = list(dict.fromkeys(list(grammar.get("kinds", [])) + list(declared.get("kinds", []))))
        lexicon = copy.deepcopy(grammar.get("lexicon", {}))
        for lemma, forms in self.decl.get("lexicon_forms", {}).items():
            lexicon.setdefault(lemma, {}).update(forms)
        if lexicon:
            grammar["lexicon"] = lexicon
        grammar.setdefault("max_forms", 32)
        return grammar

    def person(self):
        """The persons of a conversation, from two declarations.

        ``first``: the pack's own first person — the word its definitions use for the one who
        acts (``임자자리말``, the holder key of the user) and every form the pack groups with it
        (``자리말``: I, me, myself; 나, 내). ``user``: the forms the user says of themself, by the
        case the reply's part gives the holder, and ``addressee``: the words a reply names the
        user with, by the same cases (an empty word: the user is not said), both from this
        language's realizer file; ``honorific``: the stem ending a predicate takes when it
        agrees with the user, or None. A user form the pack does not group with its first
        person is not read as the user (``forms``)."""
        if getattr(self, "_person", None) is not None:
            return self._person
        holder = str(getattr(self.parser, "speaker_placeholder", "") or "")
        groups = getattr(self.parser, "placeholders", None) or {}
        forms = sorted({word for word, target in groups.items() if holder and target == holder} | (
            {holder} if holder else set()))
        declared = self.decl.get("person") or {}
        self._person = {"first": {"holder": holder, "forms": forms},
                        "user": {key: word for key, word in (declared.get("user") or {}).items()
                                 if not key.startswith("_")},
                        "addressee": {key: word for key, word in (declared.get("addressee") or {}).items()
                                      if not key.startswith("_")},
                        "honorific": declared.get("honorific")}
        return self._person

    def concept(self, word):
        return self.senses.get(word) or self.senses.get(str(word).lower())

    def words_for(self, concept):
        return [word for word, value in self.senses.items() if value == concept]


_languages = {}


_registered = {}


def register(stem, model):
    """The model a dialogue speaks for this language; pack pieces come from it."""
    _registered[stem] = model


def language(stem, model=None):
    model = model if model is not None else _registered.get(stem)
    if model is not None:
        key = (stem, id(model))
        if key not in _languages:
            _languages[key] = Language(stem, model=model)
        return _languages[key]
    if stem not in _languages:
        _languages[stem] = Language(stem)
    return _languages[stem]


def with_declarations(stem, declarations):
    """A Language whose realizer declarations are replaced (used to inject faults)."""
    return Language(stem, declarations)
