"""Induce slot templates from annotated examples; keep facts and answers separate.

This is supervised template induction, not a pretrained language model. A new
correction supplies a sentence, entity spans and its relation, never a QA answer.
"""
import copy
import json
import os
from pathlib import Path
import re
import tempfile

def substitute(value, slots):
    if isinstance(value, str):
        return slots.get(value[1:], value) if value.startswith("$") else value
    if isinstance(value, list):
        return [substitute(x, slots) for x in value]
    if isinstance(value, dict):
        return {k: substitute(v, slots) for k, v in value.items()}
    return value


class RelationalParser:
    def __init__(self, data=None, model_path=None, *, language_pack=None):
        selected = model_path or (os.environ.get("NAI_RELATIONAL_MODEL") if data is None else None)
        self.model_path = Path(selected) if selected is not None else None
        if data is None:
            if self.model_path is not None:
                data = json.loads(self.model_path.read_text(encoding="utf-8"))
            else:
                from pack_model import development_model
                data = development_model().relational_data
        self.data = copy.deepcopy(data)
        if language_pack is None:
            from language_components import load_reasoning_language
            language_pack = load_reasoning_language()
        # Do not copy unrelated conversation/output configuration for each
        # parser. Keep only the language component this interpreter consumes.
        self.clause_grammar = copy.deepcopy(language_pack.get("clauses", {}))
        self.inflection_grammar = copy.deepcopy(language_pack.get("inflection", {}))
        self.language_pack = {"clauses": self.clause_grammar, "inflection": self.inflection_grammar}
        self.templates = []
        for example in self.data["examples"]:
            self.templates.append(self.compile(example, self.data.get("numerals", {})))
        self._rebuild_inflections()

    def _inflected_examples(self, example):
        """Generate suffix realizations, never a separate regex per sentence form."""
        from hangul import inflect
        annotation = example.get("inflection")
        if not annotation or not self.inflection_grammar:
            return []
        # A question keeps its speech act. Swapping in a declarative ending
        # would turn asking into asserting, so questions are realized only
        # through the endings the grammar declares as questions.
        asking = "query" in example["meaning"]
        endings = (self.inflection_grammar.get("question_endings") if asking
                   else self.inflection_grammar.get("parsing_endings"))
        if not endings:
            raise ValueError("question_inflection_requires_declared_question_endings"
                             if asking else "inflection_requires_declared_parsing_endings")
        args = {key: annotation[key] for key in ("stem", "tense", "ending", "kind")}
        canonical_forms = inflect(**args, grammar=self.inflection_grammar)
        slot_end = max((example["text"].index(value) + len(value) for value in example["slots"].values()), default=0)
        canonicals = [form["text"] for form in canonical_forms
                      if example["text"].endswith(form["text"])
                      and len(example["text"]) - len(form["text"]) >= slot_end]
        if len(canonicals) != 1:
            raise ValueError("inflection_annotation_does_not_match_literal_tail")
        canonical = canonicals[0]
        result = []
        for tense in annotation.get("tenses", [annotation["tense"]]):
            for ending in endings:
                for form in inflect(annotation["stem"], tense, ending, self.inflection_grammar,
                                    kind=annotation["kind"]):
                    if form["text"] != canonical:
                        result.append((form["text"], canonical, {
                            "id": self.inflection_grammar["id"], "stem": annotation["stem"],
                            "tense": tense, "ending": ending, "operations": form["operations"]}))
        return result

    def _rebuild_inflections(self):
        # A reverse suffix trie shares stems/endings across templates. The
        # existing compiled sentence templates remain one per annotation.
        self._inflection_trie = {}
        for index, example in enumerate(self.data["examples"]):
            forms = self._inflected_examples(example)
            for surface, canonical, trace in forms:
                node = self._inflection_trie
                for char in reversed(surface):
                    node = node.setdefault(char, {})
                node.setdefault(None, []).append((index, canonical, trace))

    def _inflected_boundary(self, word):
        node = self._inflection_trie
        for char in reversed(word):
            node = node.get(char)
            if node is None:
                return False
            if any(trace["ending"] in self.inflection_grammar.get("boundary_endings", [])
                   for _, _, trace in node.get(None, [])):
                return True
        return False

    def _clause_candidates(self, literal):
        from hangul import canonical_clauses
        yield from canonical_clauses(literal, self.clause_grammar)
        node = self._inflection_trie
        for length, char in enumerate(reversed(literal), 1):
            node = node.get(char)
            if node is None:
                break
            for index, canonical, trace in node.get(None, []):
                yield literal[:-length] + canonical, {**trace, "example_index": index}

    @staticmethod
    def compile(example, numerals=None):
        text, slots = example["text"], example["slots"]
        spans = []
        for name, literal in slots.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or text.count(literal) != 1:
                raise ValueError("ambiguous_slot_annotation")
            start = text.index(literal)
            spans.append((start, start + len(literal), name))
        pieces, offset = [], 0
        for start, end, name in sorted(spans):
            if start < offset:
                raise ValueError("overlapping_slots")
            # Slot boundaries come from the annotated surrounding language,
            # not from a one-word restriction. Preserve multiword entity names.
            # Numeric examples still constrain their slot to decimal digits.
            slot_pattern = r"[^.!?,\n]+?"
            if slots[name].isdecimal():
                chars = "".join(sorted({c for words in (numerals or {}).values() for word in words for c in word}))
                slot_pattern = (r"(?:\d+|[" + re.escape(chars) + r"]+(?:\s+[" + re.escape(chars) + r"]+)*)") if chars else r"\d+"
            pieces.extend([re.escape(text[offset:start]), f"(?P<{name}>{slot_pattern})"])
            if slots[name].isdecimal():
                pieces.append(r"\s*")
            offset = end
        pieces.append(re.escape(text[offset:]))
        return re.compile("".join(pieces)), example["meaning"]

    def learn(self, correction):
        """Return a new reusable template; do not change inference rules."""
        meaning = correction.get("meaning", {})
        triple = meaning.get("triple")
        slots = correction.get("slots", {})
        if (not set(meaning).issubset({"triple", "polarity", "modality"})
                or type(meaning.get("polarity", True)) is not bool
                or meaning.get("modality", "asserted") not in {"asserted", "planned", "conditional"}
                or not isinstance(triple, list) or len(triple) != 3
                or any(not isinstance(x, str) for x in triple)
                or len(slots) < 2 or any("$" + name not in triple for name in slots)
                or any(x.startswith("$") and x[1:] not in slots for x in triple)):
            raise ValueError("correction_requires_grounded_relation_slots")
        compiled = self.compile(correction, self.data.get("numerals", {}))
        inflections = self._inflected_examples(correction)
        if correction in self.data["examples"]:
            return False
        expected = substitute(meaning, slots)
        if any(prior != expected for prior in self._clause_meanings(correction["text"]).values()):
            raise ValueError("correction_conflicts_with_previous_template")
        for surface, canonical, _ in inflections:
            realized = correction["text"][:-len(canonical)] + surface
            if any(prior != expected for prior in self._clause_meanings(realized).values()):
                raise ValueError("correction_conflicts_with_previous_inflection")
        # Reject an interpretation that changes any previous supervised example.
        from hangul import canonical_clauses
        for prior in self.data["examples"]:
            for literal, normalization in canonical_clauses(prior["text"], self.clause_grammar):
                if normalization and any(correction.get(k) != v for k, v in
                                         normalization.get("example_features", {}).items()):
                    continue
                match = compiled[0].fullmatch(literal)
                if match and substitute(compiled[1], match.groupdict()) != substitute(prior["meaning"], prior["slots"]):
                    raise ValueError("correction_conflicts_with_previous_example")
        for pattern, meaning in self.templates:
            match = pattern.fullmatch(correction["text"])
            if match and substitute(meaning, match.groupdict()) != substitute(correction["meaning"], correction["slots"]):
                raise ValueError("correction_conflicts_with_previous_template")
        self.data["examples"].append(copy.deepcopy(correction))
        self.templates.append(compiled)
        self._rebuild_inflections()
        return True

    def save(self, path):
        """Publish explicitly to a model file, without touching the seed corpus."""
        path = Path(path)
        root = Path(__file__).resolve().parent
        if any(folder in path.resolve().parents for folder in (root / "styles", root / "axioms")):
            raise ValueError("seed_corpus_is_read_only")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name + ".", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def learn_rule(self, corrections, validation):
        from rule_learning import propose
        report = propose(self.data, corrections, validation)
        if report["accepted"]:
            self.data["rules"].append(report["candidate"])
            self.data.setdefault("rule_learning_history", []).append(copy.deepcopy(report))
        return report

    def diagnose(self, text):
        diagnostics = []
        parsed = self.parse(text, _diagnostics=diagnostics)
        if parsed is None:
            return {"stage": "semantic_parse", "reason": "unrecognized_or_ambiguous_clauses",
                    "input": text, "answer": None, "diagnostics": diagnostics}
        try:
            result = self.answer(parsed)
        except ValueError as exc:
            return {"stage": "state_or_inference_precondition", "reason": str(exc),
                    "input": text, "answer": None, "facts": parsed["facts"], "query": parsed["query"]}
        if result is None:
            from graph_inference import bind, closure, current_facts, proof
            facts, _ = current_facts(parsed["facts"], self.data.get("mutable_predicates", []),
                                     self.data.get("numeric_updates", {}))
            known = closure(facts, self.data["rules"])
            candidates = [{"fact": list(fact), "query_index": index, "proof": proof(known, fact)}
                          for index, query in enumerate(parsed["query"]) for fact in known
                          if bind(query["triple"], fact, {}) is not None]
            return {"stage": "graph_inference", "reason": "nonunique_proof" if candidates else "missing_proof",
                    "input": text, "answer": None, "facts": parsed["facts"], "query": parsed["query"],
                    "candidates": candidates}
        return {"stage": "answered", "input": text, **result}

    def _clause_meanings(self, literal, *, derivations=None):
        from numeral_semantics import parse_numeral
        meanings, best_specificity = {}, -1
        for candidate, normalization in self._clause_candidates(literal):
            for index, ((pattern, meaning), example) in enumerate(zip(self.templates, self.data["examples"])):
                if normalization and "example_index" in normalization and index != normalization["example_index"]:
                    continue
                if (normalization and "example_index" not in normalization
                        and example.get("inflection") and self.inflection_grammar):
                    # A declared stem/class has a computed paradigm. A legacy
                    # suffix shortcut must not reintroduce invalid forms such
                    # as 한다 -> 한고 behind the morphology component's back.
                    continue
                if normalization and any(example.get(k) != v for k, v in
                                         normalization.get("example_features", {}).items()):
                    continue
                # A normalization made by this example's own declared paradigm
                # keeps the speech act — a question is realized only through
                # endings the grammar declares as questions. The legacy suffix
                # shortcut carries no such guarantee, so it still may not
                # rewrite the ending of a question.
                declared = normalization and "example_index" in normalization
                if normalization and not declared and "query" in meaning:
                    continue
                # Rewriting a tail that is itself a slot would edit the entity,
                # whatever produced the normalization.
                if normalization and any(example["text"].endswith(value)
                                         for value in example["slots"].values()):
                    continue
                match = pattern.fullmatch(candidate)
                if not match:
                    continue
                slots = match.groupdict()
                # Do not absorb an unrecognized preceding clause into an entity
                # slot just because the trailing predicate is understood.
                if any(self._inflected_boundary(word) for value in slots.values()
                       for word in value.split()):
                    continue
                for name, annotated in example["slots"].items():
                    if annotated.isdecimal():
                        slots[name] = parse_numeral(slots[name], self.data.get("numerals", {}))
                if any(value is None for value in slots.values()):
                    continue
                # Count the observed fixed surface, not letters manufactured by
                # expansion to the canonical spelling. Different canonical
                # forms of the same spoken ending must not win by their length.
                specificity = len(re.sub(r"\(\?P<[^>]+>[^)]*\)", "", pattern.pattern))
                if normalization and "example_index" in normalization:
                    specificity += len(literal) - len(candidate)
                if specificity > best_specificity:
                    meanings, best_specificity = {}, specificity
                    if derivations is not None:
                        derivations.clear()
                if specificity == best_specificity:
                    grounded = substitute(meaning, slots)
                    key = json.dumps(grounded, sort_keys=True, ensure_ascii=False)
                    # Exact evidence is tried first; do not replace its proof
                    # with a later equivalent normalization.
                    if key not in meanings and derivations is not None:
                        derivations[key] = ({"rule": normalization["id"], "canonical": candidate}
                                            if normalization else None)
                        if normalization and "operations" in normalization:
                            derivations[key].update({k: normalization[k] for k in
                                                     ("stem", "tense", "ending", "operations")})
                    meanings[key] = grounded
        return meanings

    def parse(self, text, *, partial=False, _diagnostics=None):
        from hangul import clause_spans
        facts, query = [], None
        clauses = []
        diagnostics = _diagnostics if _diagnostics is not None else []
        unrecognized = False
        # Only a fully recognized prefix authorizes a soft clause boundary.
        # A failed suffix guess (e.g. a noun ending in 고) never drops source text.
        cache, derivations = {}, {}
        def meanings(literal):
            if literal not in cache:
                derivations[literal] = {}
                cache[literal] = self._clause_meanings(literal, derivations=derivations[literal])
            return cache[literal]

        for evidence in clause_spans(text, self.clause_grammar, commas=True,
                                     accept_prefix=meanings, inflected_boundary=self._inflected_boundary):
            unique = meanings(evidence["text"])
            if (any(text[evidence["end"]:].lstrip().startswith(mark) for mark in self.clause_grammar.get("question_marks", []))
                    and any("triple" in meaning for meaning in unique.values())):
                diagnostics.append({"reason": "question_is_not_an_observation", "evidence": evidence})
                unrecognized = True
                continue
            if not unique:
                diagnostics.append({"reason": "unrecognized_clause", "evidence": evidence,
                                    "candidates": []})
                unrecognized = True
                continue
            clauses.append((list(unique.values()), evidence))
        if unrecognized:
            return None

        def entities(meaning):
            triples = ([meaning["triple"]] if "triple" in meaning else
                       [q["triple"] for q in meaning.get("query", [])])
            return {triple[i] for triple in triples for i in (0, 2)
                    if isinstance(triple[i], str) and not triple[i].startswith(("?", "$"))
                    and not triple[i].isdecimal()}

        # Use only unambiguous clauses as anchors. An uncertain candidate must
        # not manufacture its own support or silently discard another clause.
        while any(len(options) > 1 for options, _ in clauses):
            anchors = set().union(*(entities(options[0]) for options, _ in clauses if len(options) == 1))
            changed = False
            for index, (options, evidence) in enumerate(clauses):
                if len(options) == 1:
                    continue
                scores = [len(entities(option) & anchors) for option in options]
                best = max(scores)
                winners = [option for option, score in zip(options, scores) if score == best]
                if best > 0 and len(winners) == 1:
                    clauses[index] = (winners, evidence)
                    changed = True
            if not changed:
                diagnostics.extend({"reason": "ambiguous_clause", "evidence": evidence,
                                    "candidates": options} for options, evidence in clauses if len(options) > 1)
                return None
        for options, evidence in clauses:
            meaning = options[0]
            key = json.dumps(meaning, sort_keys=True, ensure_ascii=False)
            normalization = derivations[evidence["text"]].get(key)
            if normalization:
                evidence = {**evidence, "normalization": normalization}
            if "triple" in meaning:
                fact = {"triple": meaning["triple"], "evidence": evidence}
                if "scope" in meaning:
                    fact["scope"] = meaning["scope"]
                for field in ("polarity", "modality"):
                    if field in meaning:
                        fact[field] = meaning[field]
                facts.append(fact)
            elif "query" in meaning and query is None:
                query = meaning["query"]
            else:
                diagnostics.append({"reason": "multiple_queries_or_invalid_meaning", "evidence": evidence})
                return None
        usable = bool(facts or query) if partial else bool(facts and query)
        if not usable:
            diagnostics.append({"reason": "missing_facts" if not facts else "missing_query"})
        return {"facts": facts, "query": query} if usable else None

    def answer(self, parsed):
        from graph_inference import bind, closure, current_facts, proof
        facts, changes = current_facts(parsed["facts"], self.data.get("mutable_predicates", []),
                                       self.data.get("numeric_updates", {}))
        known = closure(facts, self.data["rules"])
        found = []
        for query in parsed["query"]:
            for fact in known:
                bindings = bind(query["triple"], fact, {})
                if bindings is not None:
                    result = substitute(query, {k[1:]: v for k, v in bindings.items()})
                    result["triple"] = list(fact)
                    found.append(result)
        if len(found) != 1:
            return None
        result = found[0]
        answer = ("".join(result["render"]) if "render" in result else
                  result["answer"] + self.data["answer_suffix"])
        return {"answer": answer,
                "transitions": changes + proof(known, result["triple"])}
