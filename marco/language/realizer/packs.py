"""Load the realizer's declarations and the language pack pieces it reuses.

Two sources per language, both data:

* ``marco/language/realizer/<stem>.json`` — the realizer's own declarations
  (expressions, lexicon, cases, endings, reading rules);
* the language pack ``styles/<stem>.json`` through its parser — particle
  mates, the inflection grammar, negation, numerals, senses, romanization.

``meaning.json`` holds what is shared by every language.
"""
import contextvars
import copy
import hashlib
import json
import re
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


# Selected-package scope: transient actual models of one call, never stored in graphs or reports.
_BINDING = contextvars.ContextVar('realizer_selected_binding', default=None)
_INHERIT = object()
_SHA256 = re.compile(r'\A[0-9a-f]{64}\Z')


class _SelectedUnavailable(Exception):
    """A selected lookup has no admitted declaration (unbound, ambiguous, drifted or missing)."""


def _digest(value):
    return value if isinstance(value, str) and _SHA256.match(value) else None


def _entry(model):
    fp, ek = _digest(getattr(model, 'content_fingerprint', None)), _digest(getattr(model, 'effective_key', None))
    decl = (model.language or {}).get('realizer') if fp and ek else None
    if type(decl) is not dict:
        decl = None
    sha = None if decl is None else hashlib.sha256(json.dumps(
        decl, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
        allow_nan=False).encode('utf-8')).hexdigest()
    return {'model': model, 'stem': stem_of(model), 'fp': fp, 'ek': ek, 'decl': decl, 'sha': sha}


@contextmanager
def selected_scope(source=None, target=None, conversation=_INHERIT):
    outer = _BINDING.get()
    src = _entry(source) if hasattr(source, 'parser') else None
    tgt = _entry(target) if hasattr(target, 'parser') else None
    if src is None and tgt is None:
        if outer is None:
            yield None
            return
        binding = dict(outer)
    else:
        def same(entry, other):
            return entry is None or (other is not None and (entry['fp'], entry['ek']) == (other['fp'], other['ek']))
        if outer is not None and all(same(e, outer['source']) or same(e, outer['target']) for e in (src, tgt)):
            binding = dict(outer)
        else:
            src = src or tgt
            tgt = tgt or src
            binding = {'source': src, 'target': tgt, 'conversation': None}
    if conversation is not _INHERIT:
        binding['conversation'] = conversation
    token = _BINDING.set(binding)
    try:
        yield binding
    finally:
        _BINDING.reset(token)


def selected_binding():
    return _BINDING.get()


def bind_conversation(value):
    binding = _BINDING.get()
    if binding is not None:
        binding['conversation'] = value


def _resolve(stem):
    binding = _BINDING.get()
    if binding is None:
        return None
    found = {}
    for entry in (binding['source'], binding['target']):
        if entry['stem'] != stem:
            continue
        model = entry['model']
        if entry['decl'] is None or entry['sha'] is None or (
                _digest(getattr(model, 'content_fingerprint', None)),
                _digest(getattr(model, 'effective_key', None))) != (entry['fp'], entry['ek']):
            return None
        found[(entry['fp'], entry['ek'], entry['sha'])] = entry
    return next(iter(found.values())) if len(found) == 1 else None


def _identity(entry):
    if entry is None or entry['decl'] is None:
        return None
    return {'content_fingerprint': entry['fp'], 'effective_key': entry['ek'], 'realizer_sha256': entry['sha']}


def selected_identity(stem):
    return _identity(_resolve(stem))


def selected_identities():
    binding = _BINDING.get()
    if binding is None:
        return None
    return {'source': _identity(_resolve(binding['source']['stem'])),
            'target': _identity(_resolve(binding['target']['stem']))}


def _resolve_language(stem):
    entry = _resolve(stem)
    if entry is None:
        raise _SelectedUnavailable(stem)
    key = (stem, entry['fp'], entry['ek'], entry['sha'])
    if key not in _languages:
        _languages[key] = Language(stem, entry['decl'], entry['model'])
    return _languages[key]


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
    if _BINDING.get() is not None:
        return _resolve(stem) is not None
    if model is not None and hasattr(model, "parser"):
        with selected_scope(model, model):
            return _resolve(stem) is not None
    declared = _declared_pack(stem) if stem else None
    if declared is None:
        return False
    return model is not None or (ROOT / declared).is_file()


class Language:
    """One language: the realizer's declarations and the pack parser's pieces."""

    def __init__(self, stem, declarations=None, model=None):
        self.stem = stem
        if _BINDING.get() is not None:
            # Inside a selected scope only the bound admitted declaration and its actual model
            # are used; an explicit override is ignored before anything is copied.
            entry = _resolve(stem)
            if entry is None:
                raise _SelectedUnavailable(stem)
            declarations, model = entry["decl"], entry["model"]
        elif declarations is None and model is not None and hasattr(model, "parser"):
            # A model's own inline declaration; a selected model never reads the HOST file for it.
            declarations = (model.language or {}).get("realizer")
            if type(declarations) is not dict:
                raise _SelectedUnavailable(stem)
        self.decl = copy.deepcopy(declarations) if declarations is not None else json.loads(
            (HERE / (stem + ".json")).read_text(encoding="utf-8"))
        if model is None:
            from pack_model import development_model
            model = development_model(stem)
        self.parser = model.parser()
        component = self.parser.language_pack
        self.mates = dict(component.get("particle_mates", {}))
        self.mate_exceptions = dict(component.get("particle_exceptions", {}))
        self.pack_negation = dict(component.get("negation", {}))
        self.senses = dict(component.get("senses", {}))
        self.romanization = copy.deepcopy(component.get("romanization", {}))
        self.numerals = copy.deepcopy(self.parser.data.get("numerals", {}))
        # The selected pack's own negation marker pattern, from its loaded
        # component. The semantic check reads polarity with it.
        marker = component.get("negation_marker")
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
    if _BINDING.get() is not None:
        return _resolve_language(stem)
    if model is not None and hasattr(model, "parser"):
        with selected_scope(model, model):
            return _resolve_language(stem)
    model = model if model is not None else _registered.get(stem)
    if model is not None:
        key = (stem, id(model))
        if key not in _languages:
            # Legacy registered parser: the HOST declaration is handed over explicitly.
            _languages[key] = Language(
                stem, json.loads((HERE / (stem + ".json")).read_text(encoding="utf-8")), model)
        return _languages[key]
    if stem not in _languages:
        _languages[stem] = Language(stem)
    return _languages[stem]


def with_declarations(stem, declarations):
    """A Language whose realizer declarations are replaced (used to inject faults)."""
    return Language(stem, declarations)
