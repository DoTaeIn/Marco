"""A selected model's immutable source assets, independent of its host directory.

Pack construction selects the language and axiom files once. Runtime consumers
receive this object explicitly; an absent component is empty, never a request
to load a different model beside the engine. Compiled parsers are derived state.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from language_components import decode_language_pack


class ModelError(ValueError):
    pass


def descriptor(assets, language=None):
    languages = sorted(p for p in assets if p.startswith("styles/") and p.endswith(".json"))
    if language is None:
        preferred = [p for p in languages if json.loads(assets[p]).get("default_model_language") is True]
        if len(preferred) > 1:
            raise ModelError("multiple_default_model_languages")
        language = preferred[0] if preferred else (languages[0] if len(languages) == 1 else None)
        if languages and language is None:
            raise ModelError("select_model_language_explicitly")
    if language is not None and language not in languages:
        raise ModelError("model_language_not_in_pack")
    return {"format": "nai-model", "version": 1, "language": language,
            "axioms": sorted(p for p in assets if p.startswith("axioms/") and p.endswith(".json"))}


class PackModel:
    def __init__(self, manifest, assets):
        declaration = manifest.get("model")
        # Old packs have no new reasoning declaration. Do not borrow one from
        # the current working directory, environment, or another running pack.
        if declaration is None and manifest.get("version") == 2:
            declaration = {"format": "nai-model", "version": 1, "language": None, "axioms": []}
        if (not isinstance(declaration, dict) or declaration.get("format") != "nai-model"
                or declaration.get("version") != 1):
            raise ModelError("unsupported_model_declaration")
        language = declaration.get("language")
        axiom_paths = declaration.get("axioms")
        if (not isinstance(axiom_paths, list) or not all(isinstance(p, str) for p in axiom_paths)
                or len(set(axiom_paths)) != len(axiom_paths)):
            raise ModelError("invalid_model_axiom_paths")
        if language is not None and not isinstance(language, str):
            raise ModelError("invalid_model_language_path")
        paths = ([language] if language is not None else []) + axiom_paths
        if len(set(paths)) != len(paths) or any(p not in assets for p in paths):
            raise ModelError("model_asset_not_in_pack")
        if language is not None and not (language.startswith("styles/") and language.endswith(".json")):
            raise ModelError("model_language_outside_styles")
        if any(not (p.startswith("axioms/") and p.endswith(".json")) for p in axiom_paths):
            raise ModelError("model_axioms_outside_axioms")
        self.sources = [{"path": p, "sha256": hashlib.sha256(assets[p]).hexdigest()} for p in paths]
        self.fingerprint = hashlib.sha256(json.dumps(self.sources, sort_keys=True).encode()).hexdigest()
        self._language = decode_language_pack(json.loads(assets[language]) if language else {}, language or "")
        self._axioms = {"rules": [], "mutable_predicates": [], "numeric_updates": {}, "operators": []}
        rule_ids = set()
        for path in axiom_paths:
            doc = json.loads(assets[path])
            if not isinstance(doc, dict) or doc.get("schema") != "nai-axioms-v1":
                raise ModelError("unsupported_axiom_schema: " + path)
            for key in ("rules", "mutable_predicates", "operators"):
                if not isinstance(doc.get(key, []), list):
                    raise ModelError("invalid_axiom_list: " + key)
            for rule in doc.get("rules", []):
                if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or rule["id"] in rule_ids:
                    raise ModelError("invalid_or_duplicate_rule_id")
                rule_ids.add(rule["id"])
                self._axioms["rules"].append(deepcopy(rule))
            for key in ("mutable_predicates", "operators"):
                for value in doc.get(key, []):
                    if not isinstance(value, str) or not value:
                        raise ModelError("invalid_axiom_name: " + key)
                    if value not in self._axioms[key]:
                        self._axioms[key].append(value)
            updates = doc.get("numeric_updates", {})
            if not isinstance(updates, dict):
                raise ModelError("invalid_numeric_updates")
            for name, update in updates.items():
                if name in self._axioms["numeric_updates"]:
                    raise ModelError("duplicate_numeric_update: " + name)
                self._axioms["numeric_updates"][name] = deepcopy(update)
        relational = self._language["relations"]
        if not isinstance(relational, dict) or any(k in relational for k in self._axioms):
            raise ModelError("axioms_must_not_be_in_language_component")
        self._relational = {"schema": "annotated-relations-v1", "examples": [], "answer_suffix": "",
                            "context_replies": {}, **deepcopy(relational), **deepcopy(self._axioms)}

    @property
    def language(self):
        return deepcopy(self._language)

    @property
    def relational_data(self):
        return deepcopy(self._relational)

    def permits(self, operation):
        return operation in self._axioms["operators"]

    def parser(self):
        from relational_semantics import RelationalParser
        return RelationalParser(data=self._relational, language_pack=self._language)

    def parse_expression(self, text):
        from expression_graph import parse
        return parse(text, grammar=self._language["verbal_expressions"],
                     numerals=self._relational.get("numerals", {}))

    def format_output(self, question, answer):
        from output_contracts import apply
        return apply(question, answer, config=self._language["output_contracts"])

    def number_answer(self, value, unit=""):
        template = self._language["state_answers"].get("value", "{value}{unit}")
        return template.format(value=value, unit=unit)


@lru_cache(maxsize=8)
def _development_snapshot(paths_and_revisions, language):
    assets = {name: Path(path).read_bytes() for name, path, _stamp, _size in paths_and_revisions}
    return PackModel({"version": 3, "model": descriptor(assets, language)}, assets)


def development_model(language=None):
    """Explicit source-tree tooling, not a fallback used by a selected kgpack.

    The loose files here are exactly the authoring sources that pack creation
    includes. The cache follows their revisions; callers cannot mutate it.
    """
    from language_components import _language_path
    root = Path(__file__).resolve().parent
    selected = _language_path(language)
    files = [("styles/" + selected.name, selected)]
    files += [("axioms/" + path.name, path) for path in sorted((root / "axioms").glob("*.json"))]
    revisions = tuple((name, str(path), path.stat().st_mtime_ns, path.stat().st_size) for name, path in files)
    return _development_snapshot(revisions, files[0][0])
