"""A selected model's immutable source assets, independent of its host directory.

Pack construction selects the language and axiom files once. Runtime consumers
receive this object explicitly; an absent component is empty, never a request
to load a different model beside the engine. Compiled parsers are derived state.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import unicodedata

from language_components import decode_language_pack
from encoder import EncoderRuntime


class ModelError(ValueError):
    pass


# fingerprint -> the parser built from that model's assets, kept only to be copied (PackModel.parser).
# The fingerprint hashes every asset the parser is built from, so an entry never goes stale.
_built_parsers = {}


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
    relational = sorted(p for p in assets if p.startswith("models/") and p.endswith(".json"))
    if len(relational) > 1:
        raise ModelError("multiple_relational_models")
    return {"format": "nai-model", "version": 1, "language": language,
            "axioms": sorted(p for p in assets if p.startswith("axioms/") and p.endswith(".json")),
            # 관계 표현/규칙 학습은 이 선택적 자산에만 든다. 코드 옆 환경 변수나
            # 작성 트리의 모델을 팩 런타임이 찾아 쓰지 않는다.
            "relational_model": relational[0] if relational else None}


class PackModel:
    def __init__(self, manifest, assets, *, language_overlay=None, language_at=None):
        declaration = manifest.get("model")
        if isinstance(declaration, dict) and "language_graph" in declaration:
            self._init_language_graph(manifest, assets, declaration, language_overlay, language_at)
            return
        if language_overlay is not None or language_at is not None:
            raise ModelError("language_graph_keyword_on_legacy_model")
        # Old packs have no new reasoning declaration. Do not borrow one from
        # the current working directory, environment, or another running pack.
        if declaration is None and manifest.get("version") == 2:
            declaration = {"format": "nai-model", "version": 1, "language": None, "axioms": []}
        if (not isinstance(declaration, dict) or declaration.get("format") != "nai-model"
                or declaration.get("version") != 1):
            raise ModelError("unsupported_model_declaration")
        language = declaration.get("language")
        axiom_paths = declaration.get("axioms")
        relational_path = declaration.get("relational_model")
        if (not isinstance(axiom_paths, list) or not all(isinstance(p, str) for p in axiom_paths)
                or len(set(axiom_paths)) != len(axiom_paths)):
            raise ModelError("invalid_model_axiom_paths")
        if language is not None and not isinstance(language, str):
            raise ModelError("invalid_model_language_path")
        if relational_path is not None and not isinstance(relational_path, str):
            raise ModelError("invalid_relational_model_path")
        if relational_path is not None and not (relational_path.startswith("models/")
                                                and relational_path.endswith(".json")):
            raise ModelError("relational_model_outside_models")
        paths = ([language] if language is not None else []) + axiom_paths + (
            [relational_path] if relational_path is not None else [])
        if len(set(paths)) != len(paths) or any(p not in assets for p in paths):
            raise ModelError("model_asset_not_in_pack")
        if language is not None and not (language.startswith("styles/") and language.endswith(".json")):
            raise ModelError("model_language_outside_styles")
        if any(not (p.startswith("axioms/") and p.endswith(".json")) for p in axiom_paths):
            raise ModelError("model_axioms_outside_axioms")
        self.sources = [{"path": p, "sha256": hashlib.sha256(assets[p]).hexdigest()} for p in paths]
        self.fingerprint = hashlib.sha256(json.dumps(self.sources, sort_keys=True).encode()).hexdigest()
        # immutable identity of everything supplied (graph members included) plus the model declaration;
        # `fingerprint` only covers parser sources, so identical parsers over different graphs collide there
        self._declaration = deepcopy(declaration)
        self._content_fingerprint = hashlib.sha256(json.dumps(
            {"assets": [{"path": p, "sha256": hashlib.sha256(assets[p]).hexdigest()} for p in sorted(assets)],
             "model": declaration}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        self._language = decode_language_pack(json.loads(assets[language]) if language else {}, language or "")
        # 인코더는 팩의 언어 자산에서만 고른다. 개발 환경변수는 선언이 없는
        # 옛 팩의 기본값일 뿐, 선택된 팩 둘이 서로의 값을 덮는 통로가 아니다.
        self.encoder = EncoderRuntime(self._language.get("encoder"))
        self._load_axioms(assets, axiom_paths)
        relational = self._language["relations"]
        if not isinstance(relational, dict) or any(k in relational for k in self._axioms):
            raise ModelError("axioms_must_not_be_in_language_component")
        base_relational = {"schema": "annotated-relations-v1", "examples": [], "answer_suffix": "",
                           "context_replies": {}, **deepcopy(relational), **deepcopy(self._axioms)}
        # 불러온 부품은 이 팩의 것이다. 모듈 전역에 두면 팩 둘이 섞인다.
        self._components = {}
        self._relational = self._load_relational_model(
            base_relational, json.loads(assets[relational_path]) if relational_path else None)

    def _load_axioms(self, assets, axiom_paths):
        self._axioms = {"rules": [], "mutable_predicates": [], "numeric_updates": {},
                        "comparisons": {}, "operators": []}
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
            # 견주기. 어느 성질을 어떤 연산으로 재는지는 여기서 선언하고, 재는
            # 쪽은 성질 이름을 모른 채 돈다 — 자리나 관계를 견주려면 줄이 늘지
            # 코드가 늘지 않는다. 연산은 글자가 아니라 이름이라 언어에 안 매인다.
            comparisons = doc.get("comparisons", {})
            if not isinstance(comparisons, dict):
                raise ModelError("invalid_comparisons")
            for name, spec in comparisons.items():
                if name in self._axioms["comparisons"]:
                    raise ModelError("duplicate_comparison: " + name)
                if (not isinstance(spec, dict) or not isinstance(spec.get("target"), str)
                        or not spec["target"] or spec.get("op") not in (">", "<", "==")):
                    raise ModelError("invalid_comparison: " + name)
                self._axioms["comparisons"][name] = deepcopy(spec)

    @staticmethod
    def _authenticate_graph_pack(manifest, assets):
        """Check manifest.files against the supplied members; return a detached snapshot."""
        files = manifest.get("files")
        if not isinstance(assets, dict) or not isinstance(files, list):
            raise ModelError("language_graph_pack_not_authenticated")
        snapshot = {}
        for path, data in assets.items():
            if not isinstance(path, str) or type(data) is not bytes:
                raise ModelError("language_graph_invalid_member")
            snapshot[path] = data
        seen = set()
        for entry in files:
            if not isinstance(entry, dict):
                raise ModelError("language_graph_invalid_file_entry")
            path, size, digest = entry.get("path"), entry.get("bytes"), entry.get("sha256")
            parts = path.split("/") if isinstance(path, str) else []
            if (not isinstance(path, str) or not path or path in seen or "\\" in path
                    or path.startswith("/") or unicodedata.normalize("NFC", path) != path
                    or any(p in ("", ".", "..") for p in parts) or any(ord(c) < 32 for c in path)):
                raise ModelError("language_graph_unsafe_file_path")
            seen.add(path)
            if path not in snapshot:
                raise ModelError("language_graph_file_not_in_assets: " + path)
            data = snapshot[path]
            if (type(size) is not int or size != len(data) or not isinstance(digest, str)
                    or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                    or digest != hashlib.sha256(data).hexdigest()):
                raise ModelError("language_graph_file_mismatch: " + path)
        if seen != set(snapshot):
            raise ModelError("language_graph_files_assets_membership_mismatch")
        return snapshot

    @staticmethod
    def _graph_encoder_spec(spec):
        keys = ("mode", "dimensions", "jamo_weight", "smoothing", "route_threshold",
                "cluster_threshold", "goal_similarity_threshold", "device")
        if not isinstance(spec, dict) or set(spec) != set(keys):
            raise ModelError("invalid_language_graph_encoder")
        if spec["mode"] != "문자" or spec["device"] != "cpu":
            raise ModelError("invalid_language_graph_encoder_mode_or_device")
        if type(spec["dimensions"]) is not int or not 256 <= spec["dimensions"] <= 65536:
            raise ModelError("invalid_language_graph_encoder_dimensions")
        for key in keys[2:7]:
            value = spec[key]
            # Bounds first: math.isfinite(10**400) raises OverflowError, so a huge integer must be
            # rejected by the 0..1 comparison (exact for int) before any float conversion. NaN fails
            # the comparison; infinity fails it too, and isfinite remains as the explicit guard.
            if (type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value)):
                raise ModelError("invalid_language_graph_encoder_" + key)
        return dict(spec)

    def _init_language_graph(self, manifest, assets, declaration, language_overlay, language_at):
        from marco.language.graph_projection import project_language_dialogue
        from marco.storage import ids
        from marco.storage.graph_view import GraphView, OverlayAttachment, PackBase, pack_content_sha256
        if (set(declaration) - {"format", "version", "language", "relational_model", "axioms",
                                "language_graph", "encoder"}
                or declaration.get("format") != "nai-model" or declaration.get("version") != 1):
            raise ModelError("unsupported_model_declaration")
        if declaration.get("language") is not None or declaration.get("relational_model") is not None:
            raise ModelError("language_graph_mixed_with_legacy_language")
        graph = declaration["language_graph"]
        if (not isinstance(graph, dict) or set(graph) != {"member_path", "root"}
                or not all(isinstance(graph[k], str) and graph[k] for k in graph)):
            raise ModelError("invalid_language_graph_declaration")
        axiom_paths = declaration.get("axioms")
        if (not isinstance(axiom_paths, list) or not all(isinstance(p, str) for p in axiom_paths)
                or len(set(axiom_paths)) != len(axiom_paths)):
            raise ModelError("invalid_model_axiom_paths")
        encoder_spec = self._graph_encoder_spec(declaration.get("encoder"))
        if language_overlay is None and language_at is not None:
            raise ModelError("language_at_requires_language_overlay")
        if language_at is not None and (type(language_at) is not int or language_at < 0):
            raise ModelError("invalid_language_at")
        if language_overlay is not None and not isinstance(language_overlay, OverlayAttachment):
            raise ModelError("invalid_language_overlay")
        assets = self._authenticate_graph_pack(manifest, assets)
        member = graph["member_path"]
        if not member.endswith(".kg") or member not in assets:
            raise ModelError("language_graph_member_not_in_pack")
        graph_ids = [ids.graph_id(p) for p in assets if p.endswith(".kg")]
        if len(set(graph_ids)) != len(graph_ids):
            raise ModelError("language_graph_id_collision")
        graph_id = ids.graph_id(member)
        paths = [member] + axiom_paths
        if len(set(paths)) != len(paths):
            raise ModelError("model_asset_not_in_pack")
        if any(not (p.startswith("axioms/") and p.endswith(".json")) for p in axiom_paths):
            raise ModelError("model_axioms_outside_axioms")
        manifest = deepcopy(manifest)
        base_sha256 = pack_content_sha256(manifest)
        # The authenticated raw member path travels with the provenance; it is distinct from the
        # canonical graph_id and from the base/overlay identities, and shared by both view paths.
        source = {"member_path": member,
                  "member_sha256": hashlib.sha256(assets[member]).hexdigest(),
                  "base_content_sha256": base_sha256}
        try:
            base = PackBase(manifest, assets)
            if language_overlay is None:
                view = GraphView(base)
                view.check()
                projection = project_language_dialogue(view, graph_id, graph["root"], source=source)
                action_candidate = self._action_grounding_read(view, graph_id, graph["root"], source, projection)
                learning_candidate = self._action_learning_read(view, graph_id, graph["root"], source, projection, action_candidate)
            else:
                if language_overlay.base_sha256 != base_sha256:
                    raise ModelError("language_overlay_base_mismatch")
                with language_overlay._open() as store:
                    meta = store.meta()
                    if meta["base_sha256"] != base_sha256:
                        raise ModelError("language_overlay_base_mismatch")
                    if meta.get("base_build_id") is not None:
                        source["base_build_id"] = meta["base_build_id"]
                    view = GraphView(base, store, language_at, base_build_id=meta.get("base_build_id"))
                    view.check()
                    projection = project_language_dialogue(view, graph_id, graph["root"], source=source)
                    action_candidate = self._action_grounding_read(view, graph_id, graph["root"], source, projection)
                    learning_candidate = self._action_learning_read(view, graph_id, graph["root"], source, projection, action_candidate)
        except ModelError:
            raise
        except Exception as error:
            raise ModelError("language_graph_projection_failed: %s: %s" % (type(error).__name__, error))
        self._load_axioms(assets, axiom_paths)
        self._action_grounding_projection = self._action_grounding_publish(action_candidate)
        self._action_learning_projection = self._action_learning_publish(learning_candidate)
        data = deepcopy(projection["data"])
        if any(k in data for k in self._axioms):
            raise ModelError("axioms_must_not_be_in_language_component")
        self.sources = [{"path": p, "sha256": hashlib.sha256(assets[p]).hexdigest()} for p in paths]
        self.fingerprint = hashlib.sha256(json.dumps(
            {"projection": projection["fingerprint"], "axioms": self.sources[1:]},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self._declaration = deepcopy(declaration)
        self._content_fingerprint = hashlib.sha256(json.dumps(
            {"assets": [{"path": p, "sha256": hashlib.sha256(assets[p]).hexdigest()} for p in sorted(assets)],
             "model": declaration}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        self._language = deepcopy(projection["language_pack"])
        self._language_projection = deepcopy(projection)
        self.encoder = EncoderRuntime(encoder_spec)
        self._components = {}
        self._relational = {"schema": "annotated-relations-v1", "answer_suffix": "", "context_replies": {},
                            **data, **deepcopy(self._axioms)}

    @property
    def language_projection(self):
        projection = getattr(self, "_language_projection", None)
        return None if projection is None else deepcopy(projection)

    @property
    def action_grounding_projection(self):
        envelope = getattr(self, '_action_grounding_projection', None)
        return None if envelope is None else deepcopy(envelope)

    @property
    def action_learning_projection(self):
        envelope = getattr(self, '_action_learning_projection', None)
        return None if envelope is None else deepcopy(envelope)

    @staticmethod
    def _action_learning_gap(code, cause=None):
        return {'schema': 'pack-action-learning-projection-v1', 'status': 'gap',
                'projection': None, 'binding': None,
                'gaps': [{'code': code, 'cause': cause}]}

    @staticmethod
    def _action_learning_read(view, graph_id, root, source, language_projection, action_candidate):
        def gap(code, cause=None):
            return PackModel._action_learning_gap(code, cause)
        try:
            if (not isinstance(action_candidate, dict)
                    or set(action_candidate) != {'projection', 'binding'}):
                return None
            action = action_candidate['projection']
            action_binding = action_candidate['binding']
            if not isinstance(action, dict) or not isinstance(action_binding, dict):
                return None
            import re
            from marco.language.graph_projection import LanguageProjectionGap, project_action_learning
            from marco.storage import ids
            try:
                learning = project_action_learning(
                    view, graph_id, root, source=source,
                    action_projection=deepcopy(action),
                    language_projection=deepcopy(language_projection))
            except LanguageProjectionGap as error:
                cause = getattr(error, 'gap', None)
                if not isinstance(cause, str) and len(error.args) > 1:
                    cause = error.args[1]
                if not (isinstance(cause, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', cause)):
                    cause = None
                return gap('learning_projection_gap', cause)
            if learning is None:
                return None

            def digest(value):
                return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                                 ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()

            def is_hex(value):
                return (isinstance(value, str) and len(value) == 64
                        and all(c in '0123456789abcdef' for c in value))
            keys = {'schema', 'policy', 'forms', 'render', 'role_labels', 'source_maps',
                    'provenance', 'parent_action_fingerprint',
                    'language_projection_fingerprint', 'fingerprint'}
            if (not isinstance(learning, dict) or set(learning) != keys
                    or learning['schema'] != 'graph-action-learning-projection-v1'
                    or not isinstance(language_projection, dict)):
                return gap('learning_projection_shape')
            learning_fp = learning['fingerprint']
            parent_fp = learning['parent_action_fingerprint']
            language_fp = learning['language_projection_fingerprint']
            action_fp = action.get('fingerprint')
            if not all(is_hex(v) for v in (learning_fp, parent_fp, language_fp, action_fp)):
                return gap('learning_fingerprint_mismatch')
            graph_data, _origins = view.graph_with_origins(graph_id)
            expected = {'graph_id': graph_id,
                        'root_id': ids.node_id(graph_id, root),
                        'effective_graph_sha256': digest(graph_data),
                        'view_key': list(deepcopy(view.key)),
                        'base_origin': deepcopy(dict(view.base_origin)),
                        'source': dict({'status': 'caller_supplied'}, **deepcopy(source))}
            for prov in (language_projection.get('provenance'), action.get('provenance'),
                         learning['provenance']):
                if not isinstance(prov, dict) or any(k not in prov or prov[k] != v
                                                     for k, v in expected.items()):
                    return gap('learning_identity_mismatch')
            if (parent_fp != action_fp
                    or language_fp != language_projection.get('fingerprint')
                    or action_binding.get('action_projection_fingerprint') != action_fp
                    or action_binding.get('language_projection_fingerprint') != language_fp):
                return gap('learning_fingerprint_mismatch')
            if digest({k: v for k, v in learning.items() if k != 'fingerprint'}) != learning_fp:
                return gap('learning_fingerprint_mismatch')
            binding = {'schema': 'selected-action-learning-projection-binding-v1',
                       'graph_id': expected['graph_id'], 'root_id': expected['root_id'],
                       'effective_graph_sha256': expected['effective_graph_sha256'],
                       'view_key': deepcopy(expected['view_key']),
                       'base_origin': deepcopy(expected['base_origin']),
                       'source': deepcopy(expected['source']),
                       'language_projection_fingerprint': language_fp,
                       'action_projection_fingerprint': action_fp,
                       'action_learning_projection_fingerprint': learning_fp}
            return {'projection': deepcopy(learning), 'binding': binding}
        except Exception:
            return PackModel._action_learning_gap('learning_projection_failed')

    def _action_learning_publish(self, learning_candidate):
        if learning_candidate is None:
            return None
        try:
            if not isinstance(learning_candidate, dict):
                return self._action_learning_gap('learning_projection_shape')
            if learning_candidate.get('schema') == 'pack-action-learning-projection-v1':
                if (set(learning_candidate) == {'schema', 'status', 'projection', 'binding', 'gaps'}
                        and learning_candidate['status'] == 'gap'):
                    return deepcopy(learning_candidate)
                return self._action_learning_gap('learning_projection_shape')
            projection = learning_candidate.get('projection')
            binding = learning_candidate.get('binding')
            if (set(learning_candidate) != {'projection', 'binding'}
                    or not isinstance(projection, dict) or not isinstance(binding, dict)):
                return self._action_learning_gap('learning_projection_shape')
            action = getattr(self, '_action_grounding_projection', None)
            if (not isinstance(action, dict) or action.get('status') != 'paired'
                    or not isinstance(action.get('binding'), dict)
                    or action['binding'].get('action_projection_fingerprint')
                    != binding.get('action_projection_fingerprint')):
                return self._action_learning_gap('learning_action_not_paired')
            return {'schema': 'pack-action-learning-projection-v1', 'status': 'paired',
                    'projection': deepcopy(projection), 'binding': deepcopy(binding), 'gaps': []}
        except Exception:
            return self._action_learning_gap('learning_projection_failed')

    @staticmethod
    def _action_grounding_gap(code, cause=None):
        return {'schema': 'pack-action-grounding-projection-v1', 'status': 'gap',
                'projection': None, 'binding': None,
                'gaps': [{'code': code, 'cause': cause}]}

    @staticmethod
    def _action_grounding_read(view, graph_id, root, source, language_projection):
        def gap(code, cause=None):
            return PackModel._action_grounding_gap(code, cause)
        try:
            import re
            from marco.language.graph_projection import LanguageProjectionGap, project_action_grounding
            from marco.storage import ids
            try:
                action = project_action_grounding(view, graph_id, root, source=source)
            except LanguageProjectionGap as error:
                cause = getattr(error, 'gap', None)
                if not isinstance(cause, str) and len(error.args) > 1:
                    cause = error.args[1]
                if not (isinstance(cause, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', cause)):
                    cause = None
                return gap('action_projection_gap', cause)
            if action is None:
                return None

            def digest(value):
                return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                                 ensure_ascii=False).encode('utf-8')).hexdigest()

            def is_hex(value):
                return (isinstance(value, str) and len(value) == 64
                        and all(c in '0123456789abcdef' for c in value))
            keys = {'schema', 'catalog', 'surface', 'policy', 'replies', 'required_operators',
                    'hypothesis_scope', 'entry_labels', 'source_maps', 'provenance', 'fingerprint',
                    'catalog_description'}
            if (not isinstance(action, dict) or set(action) != keys
                    or action['schema'] != 'graph-action-grounding-projection-v1'
                    or not isinstance(language_projection, dict)
                    or language_projection.get('schema') != 'graph-dialogue-projection-v1'):
                return gap('action_projection_shape')
            operators = action['required_operators']
            if (not isinstance(operators, list) or len(operators) != 2
                    or any(type(o) is not str for o in operators)
                    or set(operators) != {'relational_graph', 'contextual_action_hypothesis'}
                    or action['hypothesis_scope'] != 'provisional_nonexecuting_v1'):
                return gap('action_projection_shape')
            graph_data, _origins = view.graph_with_origins(graph_id)
            expected = {'graph_id': graph_id,
                        'root_id': ids.node_id(graph_id, root),
                        'effective_graph_sha256': digest(graph_data),
                        'view_key': list(deepcopy(view.key)),
                        'base_origin': deepcopy(dict(view.base_origin)),
                        'source': dict({'status': 'caller_supplied'}, **deepcopy(source))}
            for prov in (language_projection.get('provenance'), action['provenance']):
                if not isinstance(prov, dict) or any(k not in prov or prov[k] != v
                                                     for k, v in expected.items()):
                    return gap('action_identity_mismatch')
            language_fp = language_projection.get('fingerprint')
            action_fp = action['fingerprint']
            if not is_hex(language_fp) or not is_hex(action_fp):
                return gap('action_fingerprint_mismatch')
            catalog = action['catalog']
            if (not isinstance(catalog, dict)
                    or set(catalog) != {'schema', 'catalog_id', 'graph', 'limits', 'programs'}
                    or catalog['schema'] != 'nai-action-catalog-v1'):
                return gap('action_projection_shape')
            graph_identity = dict(deepcopy(expected), projection_fingerprint=action_fp)
            if catalog['graph'] != graph_identity:
                return gap('action_identity_mismatch')
            preimage = {'schema': action['schema'], 'required_operators': action['required_operators'],
                        'hypothesis_scope': action['hypothesis_scope'],
                        'catalog': {'catalog_id': catalog['catalog_id'], 'limits': catalog['limits'],
                                    'programs': catalog['programs']},
                        'surface': action['surface'], 'policy': action['policy'],
                        'replies': action['replies'], 'entry_labels': action['entry_labels'],
                        'source_maps': action['source_maps'], 'provenance': action['provenance']}
            if digest(preimage) != action_fp:
                return gap('action_fingerprint_mismatch')
            desc = action['catalog_description']
            flags = desc.get('flags') if isinstance(desc, dict) else None
            if (not isinstance(desc, dict) or desc.get('schema') != 'nai-action-catalog-footprint-v1'
                    or desc.get('status') != 'described' or desc.get('gaps') != []
                    or desc.get('claimed_identity') != {'catalog_id': catalog['catalog_id'],
                                                        'graph': catalog['graph']}
                    or desc.get('identity_verified') is not False
                    or desc.get('projection_adapter_pending') is not True
                    or not isinstance(flags, dict)
                    or flags.get('identity_verified') is not False
                    or flags.get('projection_adapter_pending') is not True
                    or flags.get('candidate_enumeration_ready') is not False):
                return gap('action_helper_gap')
            binding = {'schema': 'selected-action-projection-binding-v1',
                       'graph_id': expected['graph_id'], 'root_id': expected['root_id'],
                       'effective_graph_sha256': expected['effective_graph_sha256'],
                       'view_key': deepcopy(expected['view_key']),
                       'base_origin': deepcopy(expected['base_origin']),
                       'source': deepcopy(expected['source']),
                       'language_projection_fingerprint': language_fp,
                       'action_projection_fingerprint': action_fp,
                       'required_operators': list(operators),
                       'hypothesis_scope': 'provisional_nonexecuting_v1'}
            return {'projection': deepcopy(action), 'binding': binding}
        except Exception:
            return gap('action_projection_failed')

    def _action_grounding_publish(self, action_candidate):
        if action_candidate is None:
            return None
        try:
            if not isinstance(action_candidate, dict):
                return self._action_grounding_gap('action_projection_shape')
            if action_candidate.get('schema') == 'pack-action-grounding-projection-v1':
                if (set(action_candidate) == {'schema', 'status', 'projection', 'binding', 'gaps'}
                        and action_candidate['status'] == 'gap'):
                    return deepcopy(action_candidate)
                return self._action_grounding_gap('action_projection_shape')
            projection = action_candidate.get('projection')
            binding = action_candidate.get('binding')
            if (set(action_candidate) != {'projection', 'binding'}
                    or not isinstance(projection, dict) or not isinstance(binding, dict)):
                return self._action_grounding_gap('action_projection_shape')
            for operator in projection['required_operators']:
                try:
                    allowed = self.permits(operator)
                except Exception:
                    return self._action_grounding_gap('action_permission_failed')
                if not allowed:
                    return self._action_grounding_gap('action_permission_missing')
            return {'schema': 'pack-action-grounding-projection-v1', 'status': 'paired',
                    'projection': deepcopy(projection), 'binding': deepcopy(binding), 'gaps': []}
        except Exception:
            return self._action_grounding_gap('action_projection_failed')

    @staticmethod
    def _load_relational_model(base, learned):
        """검증한 표현·규칙 확장만 팩 안에서 다시 쓴다.

        ``RelationalParser.save``는 전체 모델을 내보낸다. 팩의 언어·공리를
        그 파일이 몰래 바꾸지 못하도록, 바탕과 다른 것은 추가 ``examples``와
        추가 규칙뿐인지 확인한다. 따라서 패키지 이동 뒤에도 학습 근거는
        유지하면서 팩 선언과 충돌하지 않는다.
        """
        if learned is None:
            return base
        if not isinstance(learned, dict) or learned.get("schema") != "annotated-relations-v1":
            raise ModelError("unsupported_relational_model")
        mutable = {"examples", "rules"}
        if set(learned) != set(base):
            raise ModelError("relational_model_schema_mismatch")
        for key in set(base) - mutable:
            if learned[key] != base[key]:
                raise ModelError("relational_model_changes_pack_declaration: " + key)
        if (not isinstance(learned["examples"], list) or not isinstance(learned["rules"], list)
                or learned["examples"][:len(base["examples"])] != base["examples"]
                or learned["rules"][:len(base["rules"])] != base["rules"]):
            raise ModelError("relational_model_not_an_extension")
        return deepcopy(learned)

    @property
    def language(self):
        return deepcopy(self._language)

    @property
    def relational_data(self):
        return deepcopy(self._relational)

    def component(self, kind, override=None):
        """선언된 부품 하나를 준다. **고른 것만 불러온다.**

        주입한 것이 가장 세고, 그다음이 이 팩의 선언이다. 선언이 없으면 ``None``
        이라 부르는 쪽이 제 기본값을 쓴다 — 여기서 기본 부품을 고르지 않는다.
        불러온 것은 팩마다 따로 담아, 팩 둘을 동시에 띄워도 서로 안 덮는다.
        """
        if override is not None:
            return override
        spec = self._language.get("components", {}).get(kind)
        if not spec:
            return None
        if kind not in self._components:
            import importlib
            module_name, _, member_name = spec.partition(":")
            member = getattr(importlib.import_module(module_name), member_name)
            self._components[kind] = member() if callable(member) else member
        return self._components[kind]

    def permits(self, operation):
        return operation in self._axioms["operators"]

    @property
    def content_fingerprint(self):
        return self._content_fingerprint

    @property
    def declaration(self):
        return deepcopy(self._declaration)

    @property
    def effective_key(self):
        """The parser cache key: the fingerprint, or with an overlay's rule changes applied, a digest
        of the fingerprint and the overlay head (seq and change id) they were read at."""
        return getattr(self, "_overlay_key", None) or self.fingerprint

    def apply_rule_overlay(self, changes, key):
        """Use the rules of an attached overlay (docs/architecture/overlay.md) from the next parser on.

        ``changes`` is ``GraphView.rule_changes()`` (DISABLE / REPLACE / ADD), applied after the model
        is loaded, to the loaded rules; ``key`` names the overlay head they were read at. ``None`` (or
        no changes) puts the loaded rules back. ``fingerprint`` stays the base fingerprint."""
        if getattr(self, "_language_projection", None) is not None:
            raise ModelError("rule_overlay_not_supported_on_language_graph_model")
        from marco.storage.graph_view import apply_rule_changes
        base = self.__dict__.setdefault("_base_relational", self._relational)
        if not changes:
            self._relational, self._overlay_key = base, None
            return
        self._relational = {**base, "rules": apply_rule_changes(base.get("rules") or [], changes)}
        self._overlay_key = hashlib.sha256(("%s\n%s" % (self.fingerprint, key)).encode()).hexdigest()

    def parser(self):
        """A parser of this model for one caller.

        Built once per model fingerprint (a restart and the realizer ask again for the same model) and
        handed out as a deep copy of that build, which no caller ever holds: what one conversation
        learns (examples, templates, rules, memos) stays in its copy. The copies share the compiled
        patterns and the first suffix trie; learning replaces a trie, it never changes one in place.
        """
        from relational_semantics import RelationalParser
        declaration = None
        envelope = self.action_grounding_projection
        if (isinstance(envelope, dict)
                and envelope.get('schema') == 'pack-action-grounding-projection-v1'
                and envelope.get('status') == 'paired'
                and envelope.get('gaps') == []
                and isinstance(envelope.get('projection'), dict)
                and isinstance(envelope['projection'].get('surface'), dict)
                and isinstance(envelope.get('binding'), dict)):
            declaration = {'surface': deepcopy(envelope['projection']['surface']),
                           'binding': deepcopy(envelope['binding'])}
        if declaration is None:
            key = self.effective_key
        else:
            try:
                canonical = json.dumps(declaration, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=False, allow_nan=False).encode('utf-8')
            except (TypeError, ValueError) as exc:
                raise ModelError('selected_action_surface_not_canonical_json') from exc
            key = (self.effective_key, hashlib.sha256(canonical).hexdigest())
        built = _built_parsers.get(key)
        if built is None:
            if declaration is None:
                built = RelationalParser(data=self._relational, language_pack=self._language)
            else:
                built = RelationalParser(data=self._relational, language_pack=self._language,
                                         selected_action_surface=deepcopy(declaration))
            _built_parsers[key] = built
        return deepcopy(built, {id(built._inflection_trie): built._inflection_trie})

    def parse_expression(self, text):
        from marco.language.arithmetic import parse
        return parse(text, grammar=self._language["verbal_expressions"],
                     numerals=self._relational.get("numerals", {}))

    def format_output(self, question, answer):
        from marco.language.realizer.contracts import apply
        return apply(question, answer, config=self._language["output_contracts"])

    def number_answer(self, value, unit=""):
        template = self._language["state_answers"].get("value", "{value}{unit}")
        return template.format(value=value, unit=unit)


def companion_models(manifest, assets):
    """The other languages of the same pack, for questions asked in them.

    Each shares the pack's axioms. A learned relational model belongs to the
    language it was learned in, so a companion never loads it.
    """
    selected = (manifest.get("model") or {}).get("language")
    models = []
    for path in sorted(p for p in assets if p.startswith("styles/") and p.endswith(".json")):
        if path == selected:
            continue
        declaration = {**descriptor(assets, path), "relational_model": None}
        models.append(PackModel({**manifest, "model": declaration}, assets))
    return models


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
