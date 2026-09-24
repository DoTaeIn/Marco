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

def asserted(meaning):
    """이 뜻이 내놓는 사실들. 한 문장이 사실 하나라는 법은 없다.

    주고받기는 한 문장이 **둘**을 말한다 — 주는 쪽이 줄고 받는 쪽이 는다.
    사실 하나만 담을 수 있으면 그런 움직임은 보통 문장으로 못 적고, 뜻풀이
    틀을 손으로 하나 더 적는 수밖에 없다.
    """
    if "triple" in meaning:
        return [joined(meaning["triple"])]
    return [joined(row) for row in meaning.get("triples", [])]


def joined(triple):
    """여러 조각으로 적힌 이름을 한 이름으로 잇는다.

    `[민수, 구슬]` 은 `민수 구슬` 이다 — 누구의 무엇인지를 함께 세는 자리.
    """
    return [" ".join(part) if isinstance(part, list) else part for part in triple]


def declared_plural(word, declared):
    """The plural the pack declares for one word (``명사수``), or None.

    The irregular table is looked up first, whole word; otherwise the first
    spelling row whose ending the word has. The word's own capitalization is kept
    for the part that does not change."""
    if not word or not declared:
        return None
    irregular = declared.get("irregular") or {}
    many = irregular.get(word.lower())
    if many is not None:
        return (many[:1].upper() + many[1:]) if word[:1].isupper() else many
    for row in declared.get("plural", []):
        if any(word.lower().endswith(tail) for tail in row.get("after", [])):
            stem = word[:len(word) - int(row.get("drop", 0))] if row.get("drop") else word
            return stem + row.get("append", "")
    return None


def substitute(value, slots):
    if isinstance(value, str):
        return slots.get(value[1:], value) if value.startswith("$") else value
    if isinstance(value, list):
        return [substitute(x, slots) for x in value]
    if isinstance(value, dict):
        return {k: substitute(v, slots) for k, v in value.items()}
    return value


class RelationalParser:
    def __init__(self, data=None, model_path=None, *, language_pack=None, language=None):
        selected = model_path or (os.environ.get("NAI_RELATIONAL_MODEL") if data is None else None)
        self.model_path = Path(selected) if selected is not None else None
        if data is None:
            if self.model_path is not None:
                data = json.loads(self.model_path.read_text(encoding="utf-8"))
            else:
                from pack_model import development_model
                data = development_model(language).relational_data
        self.data = copy.deepcopy(data)
        if language_pack is None:
            from language_components import load_reasoning_language
            language_pack = load_reasoning_language(language)
        # Do not copy unrelated conversation/output configuration for each
        # parser. Keep only the language component this interpreter consumes.
        self.clause_grammar = copy.deepcopy(language_pack.get("clauses", {}))
        self.inflection_grammar = copy.deepcopy(language_pack.get("inflection", {}))
        self.slot_particles = copy.deepcopy(language_pack.get("slot_particles", []))
        # 자리를 짚는 격조사. 틀을 사례에서 꺼낼 때 몸통과 사건이 같은 자리를
        # 가리키는지 보는 데만 쓴다. 닫힌 갈래라 낱말마다 늘지 않는다.
        self.case_particles = copy.deepcopy(language_pack.get("case_particles", []))
        self.negation = self._negation(language_pack.get("negation", {}))
        # 뜻풀이에서 아무거나 하나를 가리키는 낱말. 그 자리는 사건이 채운다.
        # 자리말: 낱말 -> 그 묶음의 이름. `나` 와 `내` 는 한 자리다.
        self.placeholders = dict(language_pack.get("placeholders", {}))
        # 누가 했는지를 짚는 자리. 뜻풀이가 그 자리를 안 써도 넘어간다.
        # 조건으로 읽어야 하는 맺음. 조건을 낱말로 알아보면 말마다 분기가 는다.
        self.condition_endings = list(self.inflection_grammar.get("condition_endings", []))
        # `만약`은 조건의 내용이 아니라 절 전체의 해석 방식을 여는 담화 표지다.
        # 언어팩이 선언한 표지만, 낱말 경계를 지킬 때만 후보 읽기에서 뺀다.
        self.hypothetical_prefixes = sorted(
            self.clause_grammar.get("hypothetical_prefixes", []), key=len, reverse=True)
        self.doer_particle = language_pack.get("doer_particle", "")
        # 자리말 가운데 **그 일을 한 쪽**. 절 순서가 아니라 이것이 임자 자리를 정한다.
        self.speaker_placeholder = language_pack.get("speaker_placeholder", "")
        # 주격으로 드러난 행위자와 대상이 수량 상태 하나를 가리키는 문법.
        # 어느 관계에 적용할지는 언어 팩이 선언한다.
        self.actor_targets = copy.deepcopy(language_pack.get("actor_targets", {}))
        # A stated count whose counted name begins with an owner the pack's
        # particles mark (`하루는 구슬이 18개 있다`): the owner is split off.
        self.possessor = copy.deepcopy(language_pack.get("possessor", {}))
        # "[who/what] [time word] <question word> <counter> [predicate]": a
        # count question whose parts the pack declares (수량물음).
        self.count_question = copy.deepcopy(language_pack.get("count_question", {}))
        self._count_predicates = None
        # 기준이 되는 양에서 계산해 나오는 양. `절반` 은 글자 그대로의 수가 아니다.
        self.quantities = dict(language_pack.get("quantities", {}))
        # 초기 수량에서 여러 변화를 잇고 남은 값을 묻는 표현. 대상·수·동작은
        # 고정하지 않고, 언어 팩이 선언한 구조와 관계만 읽는다.
        self.quantity_chain = copy.deepcopy(language_pack.get("quantity_chain", {}))
        self.event_domains = copy.deepcopy(language_pack.get("event_domains", []))
        # 말머리 군말. 지우는 규칙이 아니라 **읽기 후보**를 하나 더 두는 데 쓴다.
        self.fillers = copy.deepcopy(language_pack.get("fillers", {}))
        # 앞서 말한 것을 도로 가리키는 말. 자리말과 다르다 — 이쪽은 이 대화에서
        # 이미 나온 것을 가리킨다.
        self.pointers = list(language_pack.get("pointers", []))
        # 아직 안 일어난 일의 꼴. 사실이 아니라 **기록**으로만 남는다.
        self.plan = self._plan(language_pack.get("plan", {}))
        # 빈 자리를 사람 말로 되묻는 법. 짧은 답을 부르는 물음이다.
        self.slot_questions = dict(language_pack.get("slot_questions", {}))
        # 이름 하나로 답할 때 이름 뒤에 붙을 수 있는 말. **받아들일 꼴**의 목록이다.
        self.short_tails = list(language_pack.get("short_tails", []))
        # 뜻풀이와 어긋난 값이 **어디까지** 미치는지 묻고 받는 말. 셋뿐이다.
        self.scope_words = dict(language_pack.get("scope_words", {}))
        self.target_words = dict(language_pack.get("target_words", {}))
        # Ordinal surface forms for choosing one already enumerated
        # relationship occurrence.  The algorithm only maps an ordinal to a
        # bounded candidate list; each language supplies the words.
        self.relation_choice_words = copy.deepcopy(language_pack.get("relation_choice_words", {}))
        # 선언된 규칙 어디에도 안 맞는 절을 가장 가까운 규칙에 맞추는 편집들과
        # 그 비용·한도. 편집 종류는 닫힌 갈래이고, 무엇을 켜고 얼마로 치는지는
        # 언어 팩이 정한다. 선언이 없으면 고치지 않는다.
        self.repair = copy.deepcopy(language_pack.get("repair", {}))
        # 선언된 생략. 쉼표로 이은 마디의 뒷말 물려받기, 상태 대상의 앞말만으로
        # 그 대상을 가리키기. 선언이 없으면 아무것도 메우지 않는다.
        self.ellipsis = dict(language_pack.get("ellipsis", {}))
        # 다른 언어의 물음을 이 대화의 이름과 맞춰 볼 때 쓰는 선언: 글자 표기법과
        # 낱말 → 개념 ID. 번역기가 아니라 대조표다.
        self.romanization = copy.deepcopy(language_pack.get("romanization", {}))
        self.senses = dict(language_pack.get("senses", {}))
        # 받침에 따라 갈리는 조사 짝과 그 예외. 조사를 떼거나 옮길 때 그 꼴이
        # 앞말에 맞는지 본다 — `사과` 의 `과` 는 `사` 뒤에 올 조사 꼴이 아니다.
        self.particle_mates = dict(language_pack.get("particle_mates", {}))
        self.particle_exceptions = dict(language_pack.get("particle_exceptions", {}))
        # 받침 있는 이름 뒤에 붙는 부름 꼬리(`가람이는` 의 `이`). 뒤에 조사가 또
        # 붙으면 격조사가 아니다 — 조사는 겹쳐 쌓이지 않는다. 선언이 없으면 안 본다.
        self.name_suffix = str(language_pack.get("name_suffix", "") or "")
        # An item counted as one names the same things as its plural. The pack
        # declares the plural rule; a language without number declares none.
        self.noun_number = dict(language_pack.get("noun_number", {}) or {})
        # Counter nouns after a number (and after the declared question word).
        # Examples are written with the first one; every declared one reads alike.
        self.counters = dict(language_pack.get("counters", {}) or {})
        # Verbs the pack says take the frame of a verb it already has examples
        # for, and phrases it says read as another phrase. Both only add
        # candidate readings; the typed text still competes.
        self.same_frame = [dict(row) for row in language_pack.get("same_frame", []) or []]
        self.phrase_variants = [dict(row) for row in language_pack.get("phrase_variants", []) or []]
        # Word-final particles that read as another particle (honorific and
        # spoken forms). Kept out of the slot groups: a group's first form
        # names a learned action's role, and widening it would rename roles.
        self.particle_variants = [dict(row) for row in language_pack.get("particle_variants", []) or []]
        # Verbs said from the taker's side (받다, 가져가다), a fronted object,
        # and the comparison question: declared shapes read by rule, not by
        # more examples.
        self.role_swaps = [dict(row) for row in language_pack.get("role_swaps", []) or []]
        self.object_fronting = dict(language_pack.get("object_fronting", {}) or {})
        self.comparison = dict(language_pack.get("comparison", {}) or {})
        # 수동태: the auxiliary forms and the recipient/agent markers of the
        # pack's passive; a pack without it reads no passive.
        self.passive = dict(language_pack.get("passive", {}) or {})
        # 요청: the forms of an utterance that asks for an action.
        self.request = dict(language_pack.get("request", {}) or {})
        # 이름밖: words that are never part of a name in a reading.
        self.outside_names = {w.lower() for w in language_pack.get("outside_names", []) or []}
        self.outside_leading = {w.lower() for w in (language_pack.get("holder_forms") or {}).get("leading_modifiers", [])}
        # 수량이유물음: the words of a why-question about one holder's count.
        self.why_count = dict(language_pack.get("why_count", {}) or {})
        # 가진쪽꼴: how a holder is said when it is not a bare name -- the speaker, a relation
        # before a name, an apposition, the speaker's own relation -- each read as the one key
        # the facts use.
        self.holder_forms = dict(language_pack.get("holder_forms", {}) or {})
        self.word_order_forms = dict(language_pack.get("word_order_forms", {}) or {})
        self._role_swap_table = None
        self._variant_table = None
        self._repair_cache = {}
        self._ending_table = None
        self.language_pack = {"clauses": self.clause_grammar, "inflection": self.inflection_grammar,
                              "slot_particles": self.slot_particles,
                              "case_particles": self.case_particles,
                              "negation": copy.deepcopy(language_pack.get("negation", {})),
                              "negation_marker": language_pack.get("negation_marker"),
                              "placeholders": dict(self.placeholders),
                              "doer_particle": self.doer_particle,
                              "speaker_placeholder": self.speaker_placeholder,
                              "actor_targets": copy.deepcopy(self.actor_targets),
                              "possessor": copy.deepcopy(self.possessor),
                              "count_question": copy.deepcopy(self.count_question),
                              "name_reply": dict(language_pack.get("name_reply", {}) or {}),
                              "contrast_correction": dict(language_pack.get("contrast_correction", {}) or {}),
                              "quantities": dict(self.quantities),
                              "quantity_chain": copy.deepcopy(self.quantity_chain),
                              "event_domains": copy.deepcopy(self.event_domains),
                              "fillers": copy.deepcopy(self.fillers),
                              "pointers": list(self.pointers),
                              "person_pointers": list(language_pack.get("person_pointers", []) or []),
                              "plan": copy.deepcopy(language_pack.get("plan", {})),
                              "slot_questions": dict(self.slot_questions),
                              "short_tails": list(self.short_tails),
                              "scope_words": dict(self.scope_words),
                              "target_words": dict(self.target_words),
                              "repair": copy.deepcopy(self.repair),
                              "particle_mates": dict(self.particle_mates),
                              "ellipsis": dict(self.ellipsis),
                              "romanization": copy.deepcopy(self.romanization),
                              "senses": dict(self.senses),
                              "particle_exceptions": dict(self.particle_exceptions),
                              "name_suffix": self.name_suffix,
                              "noun_number": dict(self.noun_number),
                              "counters": dict(self.counters),
                              "same_frame": [dict(row) for row in self.same_frame],
                              "phrase_variants": [dict(row) for row in self.phrase_variants],
                              "particle_variants": [dict(row) for row in self.particle_variants],
                              "role_swaps": [dict(row) for row in self.role_swaps],
                              "object_fronting": dict(self.object_fronting),
                              "comparison": dict(self.comparison),
                              "passive": dict(self.passive),
                              "request": dict(self.request),
                              "outside_names": sorted(self.outside_names),
                              "why_count": dict(self.why_count),
                              "holder_forms": dict(self.holder_forms),
                              "word_order_forms": dict(self.word_order_forms)}
        # 몸통에서 꺼낸 틀은 예문이 그대로인 동안만 같다. `learn` 이 예문을
        # 늘리면 버린다 — 옛 사례로 읽은 몸통을 그대로 쓰면 안 된다.
        self.induced_frames = {}
        self.data["examples"] = [e for e in self.data["examples"] if not e.get("derived")] + \
            self._elided_counted_nouns(self.data["examples"])
        self.templates = []
        for example in self.data["examples"]:
            self.templates.append(self.compile(example, self.data.get("numerals", {}),
                                               self.slot_particles,
                                               ignore_case=bool(self.data.get("ignore_case")),
                                               counters=self.counters, pointers=self.pointers))
        # A learned event may form a clause boundary, except while that word
        # is still inside the body of a definition.  This delimiter comes from
        # the pack's definition examples; it is not a Korean string embedded
        # in the action parser.
        self.definition_body_delimiters = set()
        for example in self.data["examples"]:
            meaning, slots = example.get("meaning", {}), example.get("slots", {})
            definition = meaning.get("define") if isinstance(meaning, dict) else None
            verb, body = (definition or {}).get("verb"), (definition or {}).get("몸통")
            if not (isinstance(verb, str) and isinstance(body, str)
                    and verb.startswith("$") and body.startswith("$")
                    and verb[1:] in slots and body[1:] in slots):
                continue
            start = example["text"].find(str(slots[verb[1:]])) + len(str(slots[verb[1:]]))
            end = example["text"].find(str(slots[body[1:]]), start)
            delimiter = example["text"][start:end]
            if delimiter:
                self.definition_body_delimiters.add(delimiter)
        self._rebuild_inflections()

    def _elided_counted_nouns(self, examples):
        """Every statement example with its counted noun left out (생략.counted_noun).

        ``after_numeral``: the counted noun stands right after the numeral (``gave 2 marbles
        to Moru``); the same statement said with the numeral alone (``gave 2 to Moru``, what a
        partitive ``2 of them`` reads as) is one more example with the item unnamed. Its facts
        name each holder alone and are resolved by the leading words (생략.part_reference),
        as the pack's own elided examples are. Questions are not derived; an example the pack
        already writes elided is not written twice.
        """
        if self.ellipsis.get("counted_noun") != "after_numeral":
            return []
        have = {e["text"] for e in examples}
        out = []

        def collapse(term):
            if isinstance(term, list) and len(term) == 2 and term[1] == "$item":
                return term[0]
            return term
        for example in examples:
            meaning, slots = example.get("meaning") or {}, example.get("slots") or {}
            if not isinstance(meaning, dict) or not ("triple" in meaning or "triples" in meaning):
                continue
            if example.get("counted_noun") != "may_elide":
                continue
            if "n" not in slots or "item" not in slots or not str(slots["n"]).isdecimal():
                continue
            joined = "%s %s" % (slots["n"], slots["item"])
            if example["text"].count(joined) != 1:
                continue
            text = example["text"].replace(joined, str(slots["n"]))
            if text in have:
                continue
            new_meaning = dict(meaning)
            if "triple" in meaning:
                triple = list(meaning["triple"])
                new_meaning["triple"] = [collapse(triple[0])] + triple[1:]
            else:
                new_meaning["triples"] = [[collapse(t[0])] + list(t[1:]) for t in meaning["triples"]]
            if json.dumps(new_meaning).count("$item"):
                continue
            new_meaning["elided"] = True
            derived = {**example, "text": text, "slots": {k: v for k, v in slots.items() if k != "item"},
                       "meaning": new_meaning, "derived": "counted_noun_ellipsis"}
            out.append(derived)
            have.add(text)
        return out

    def _negation(self, declared):
        """부정을 나타내는 말들. 잇는 말과 보조 어간만 선언하고 꼴은 계산한다.

        `않았다`·`않아요`·`않습니다` 를 손으로 적지 않는다. 언어팩이 이미
        활용을 계산하고 있으므로, 부정도 낱말이 아니라 한 줄이면 된다.
        """
        from hangul import inflect
        grammar = self.inflection_grammar
        if declared and "do_support" in declared:
            return {"연결": "", "forms": set(), "물음": set(),
                    "do_support": dict(declared["do_support"]),
                    "particles": [p.lower() for p in declared.get("particles", [])],
                    "contractions": {k.lower(): v.lower() for k, v in (declared.get("contractions") or {}).items()}}
        if not declared or not grammar:
            return {}
        forms, asking = set(), set()
        for tense in grammar.get("tenses", {}):
            for ending in grammar.get("endings", {}):
                try:
                    made = {form["text"] for form in
                            inflect(declared["어간"], tense, ending, grammar,
                                    kind=declared["갈래"])}
                except ValueError:
                    continue
                forms |= made
                # 묻기만 하는 꼬리. `않았어요` 처럼 서술로도 쓰는 꼬리는 빼야
                # 한다 — 안 그러면 안 한 일을 말한 것까지 물음으로 읽는다.
                if ending in self._asking(grammar):
                    asking |= made
        return {"연결": declared["연결"], "forms": forms,
                "물음": asking - (forms - asking)}

    def _plan(self, declared):
        """계획을 나타내는 꼴. 동사 쪽 꼴은 활용이 계산한다.

        `베풀 예정이다` 의 `베풀` 은 매김꼴 미래다. 낱말을 적지 않고 꼴을 적으므로
        어떤 동사에도 선다.
        """
        if not declared or not self.inflection_grammar:
            return {}
        맺음 = [declared["이름"] + tail for tail in declared.get("맺음", [])]
        return {"맺음": set(맺음), "연결": declared["연결"]}

    @staticmethod
    def _asking(grammar):
        """묻기에만 쓰는 꼬리. 서술에도 쓰는 꼬리는 물음의 표가 못 된다."""
        return set(grammar.get("question_endings", [])) - set(grammar.get("parsing_endings", []))

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
                # 언어가 모든 시제에 모든 맺음을 허용하는 것은 아니다. 예를 들어
                # 과거 관형 연결만 선언했다면 현재형을 억지로 만들지 않고, 선언된
                # 조합만 후보에 둔다.
                try:
                    realized = inflect(annotation["stem"], tense, ending,
                                       self.inflection_grammar, kind=annotation["kind"])
                except ValueError:
                    continue
                for form in realized:
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

    def _variants(self):
        """Surface form -> the form it reads as, from the pack's declarations.

        ``same_frame`` rows name stems whose every inflected form reads as the
        same tense/ending form of ``as`` (a declared stem), or as the single
        word ``read_as``. ``phrase_variants`` rows map a typed phrase to
        another (possibly empty) phrase. Forms are computed by the pack's own
        inflection grammar; nothing is guessed from the input.
        """
        if self._variant_table is not None:
            return self._variant_table
        from hangul import inflect
        from numeral_semantics import parse_numeral
        grammar = self.inflection_grammar or {}
        numerals = self.data.get("numerals", {})
        table = {}
        for row in self.same_frame:
            kinds = [row["kind"]] if row.get("kind") else list(grammar.get("kinds", []))
            for stem in row.get("stems", []):
                for kind in kinds:
                    for tense in grammar.get("tenses", {}):
                        for ending in grammar.get("endings", {}):
                            try:
                                forms = [f["text"] for f in inflect(stem, tense, ending, grammar, kind=kind)]
                                targets = ([row["read_as"]] if row.get("read_as") else
                                           [f["text"] for f in inflect(row["as"], tense, ending, grammar, kind=kind)])
                            except (ValueError, KeyError):
                                continue
                            if not targets:
                                continue
                            for form in forms:
                                # A form that is also a numeral word (사다 -> 사, the
                                # numeral 4) is read as the number: a variant never
                                # changes a quantity.
                                if parse_numeral(form, numerals) is not None:
                                    continue
                                if form and form != targets[0]:
                                    table.setdefault(form, (targets[0], {"id": "declared-same-frame-v1",
                                                                         "stem": stem, "as": row.get("as") or row.get("read_as"),
                                                                         "tense": tense, "ending": ending}))
        for row in self.phrase_variants:
            source, target = row.get("from"), row.get("to", "")
            if isinstance(source, str) and source and isinstance(target, str):
                table.setdefault(source, (target, {"id": "declared-phrase-variant-v1", "from": source, "to": target,
                                                   **({"final": True} if row.get("final") else {})}))
        self._variant_table = table
        return table

    def _variant_patterns(self):
        """The declared variants, longest first, each compiled once per parser."""
        if getattr(self, "_variant_compiled", None) is None:
            table = self._variants()
            flags = re.IGNORECASE if self.data.get("ignore_case") else 0
            compiled = []
            for source in sorted(table, key=len, reverse=True):
                target, note = table[source]
                # A variant is a whole word or phrase: bounded by the text
                # edge, a space or punctuation on each side that is a word
                # character ("'s got" is bounded on its right only).
                left = "" if not source[:1].isalnum() else r"(?<![\w])"
                right = "" if not source[-1:].isalnum() else r"(?![\w])"
                compiled.append((source.lower() if flags else source, target, note,
                                 re.compile(left + re.escape(source) + right, flags)))
            self._variant_compiled = compiled
        return self._variant_compiled

    def _particle_variant_words(self, literal):
        """Each word ending in a declared particle variant, with the particle it reads as."""
        rows = sorted((row for row in self.particle_variants if row.get("from")),
                      key=lambda row: len(row["from"]), reverse=True)
        words, notes = literal.split(" "), []
        for index, word in enumerate(words):
            for row in rows:
                if word.endswith(row["from"]) and len(word) > len(row["from"]):
                    words[index] = word[:-len(row["from"])] + row.get("to", "")
                    notes.append({"id": "declared-particle-variant-v1", "from": row["from"],
                                  "to": row.get("to", "")})
                    break
        return " ".join(words), notes

    def _variant_literals(self, literal):
        """``literal`` with every declared variant replaced, one reading per step."""
        patterns = self._variant_patterns()
        literal_in = literal
        literal, particle_notes = self._particle_variant_words(literal)
        # The passive is recognised by its participle, before a same-frame
        # variant rewrites that participle into another form.
        literal, passive_note = self._passive(literal)
        particle_notes = particle_notes + ([passive_note] if passive_note else [])
        if not patterns and not particle_notes:
            return [(literal, particle_notes)] if particle_notes else []
        out = []
        # Every declared variant at once, and the phrase variants alone: a verb
        # read as another frame (``got`` -> ``received``) must not stop a phrase
        # variant (``now`` -> ``) from reading the clause with its own verb.
        # The verb variants without the phrase variants too: a phrase dropped for
        # one reading (``가지고``) must not stop a verb variant (``계시`` -> ``있``)
        # from reading the clause with the phrase kept. A floated quantifier is
        # one more candidate after those, never in place of them.
        for kinds, floated in ((None, False), (("declared-phrase-variant-v1",), False),
                               (("declared-same-frame-v1",), False), (None, True), ((), True)):
            current, notes = literal, list(particle_notes)
            # Holder forms are read before the phrase variants (I am carrying -> I is carrying ->
            # has) and again after them (the courier, Mr. Lind, -> the courier, Lind, -> Lind).
            for form in (self._word_order_forms, self._holder_forms):
                current, note = form(current)
                if note is not None:
                    notes.append(note)
            folded = current.lower() if self.data.get("ignore_case") else current
            kept = []
            defining = self._is_definition(literal_in)
            for source, target, note, pattern in patterns:
                if source not in folded or (kinds is not None and note["id"] not in kinds):
                    continue
                if defining and note.get("final"):
                    continue    # a verb of holding read as 가지고 reads a statement, not a definition's body
                # A variant the pack marks final is not read again by a later variant (보관하고 ->
                # 가지고 stays 가지고): its words wait behind a token until every variant is applied.
                written = target
                if note.get("final"):
                    kept.append(target)
                    written = "QQKEPT%dQQ" % (len(kept) - 1)
                replaced = pattern.sub(written, current)
                if replaced != current:
                    current = re.sub(r"\s+([,;:])", r"\1", re.sub(r"\s+", " ", replaced)).strip()
                    folded = current.lower() if self.data.get("ignore_case") else current
                    notes.append({**note, "written": target})
            for index, target in enumerate(kept):
                current = current.replace("QQKEPT%dQQ" % index, target)
            folded = current.lower() if self.data.get("ignore_case") else current
            # A phrase dropped at a clause edge leaves its comma behind ("..., apparently").
            current = re.sub(r"^[,;:\s]+|[,;:\s]+$", "", re.sub(r",\s*,", ",", current))
            current, note = self._holder_forms(current)
            if note is not None:
                notes.append(note)
            if floated:
                current, note = self._float_quantifier(current)
                if note is None:
                    continue
                notes.append(note)
            for structural in (self._front_object, self._scramble, self._swap_roles):
                changed, note = structural(current)
                if note is not None:
                    current = changed
                    notes.append(note)
            if notes and current and current != literal_in and all(current != seen for seen, _n in out):
                out.append((current, notes))
        return out

    def _is_definition(self, literal):
        """A clause that teaches a word (베풀다는 ... 것이다): its body is kept as said -- the holder and
        word-order forms read statements and questions, not a definition's placeholders."""
        return any(delimiter in literal for delimiter in getattr(self, "definition_body_delimiters", ()))

    def _word_order_forms(self, literal):
        """Phrases said away from where the examples have them (말자리), put back.

        * ``fronted_recipient``: a clause opened by a recipient preposition and a name closed by
          a comma (To Bo, Ada gave 2 figs) is said with that phrase at its end (Ada gave 2 figs
          to Bo).
        * ``fronted_purpose``: a clause opened by a purpose preposition and a phrase closed by a
          comma (For the trip, Ada lent Bo 2 figs) is read without it; a purpose changes no role.
        * ``shifted_particles``: a verb's particle said after a one-word object (gave Bo back 2)
          is said right after the verb (gave back Bo 2).

        The prepositions and particles are the pack's closed lists.
        """
        spec = getattr(self, "word_order_forms", None) or {}
        if not spec or self._is_definition(literal):
            return literal, None
        text, applied = literal, []
        for preposition in spec.get("fronted_recipient", []):
            m = re.match(r"(?i:%s) ([^,]+), (.+)$" % re.escape(preposition), text)
            if m and len(m.group(1).split()) <= 4:
                text, applied = "%s %s %s" % (m.group(2), preposition, m.group(1)), applied + ["fronted_recipient"]
                break
        for preposition in spec.get("fronted_purpose", []):
            m = re.match(r"(?i:%s) [^,]+, (.+)$" % re.escape(preposition), text)
            if m:
                text, applied = m.group(1), applied + ["fronted_purpose"]
                break
        for suffix in spec.get("fronted_purpose_suffixes", []):
            # 행사 때문에 (,) ... / 이사 준비로, ...: a purpose phrase at the clause's start fills no role
            m = re.match(r"((?:\S+ ){0,2}?)(\S*)%s,? (.+)$" % re.escape(suffix), text)
            if m and (m.group(1) or m.group(2)) and not any(
                    self._ends_in_particle(w) for w in (m.group(1) + m.group(2)).split()):
                text, applied = m.group(3), applied + ["fronted_purpose"]
                break
        completive = spec.get("completive") or {}
        if completive:
            # 다 썼어요 (used up): the completive adverb before a verb of using up fills no role
            new = re.sub(r"(?<!\S)(?:%s) (?=(?:%s))" % ("|".join(re.escape(w) for w in completive.get("words", [])),
                                                        "|".join(re.escape(v) for v in completive.get("before", []))),
                         "", text)
            if new != text:
                text, applied = new, applied + ["completive"]
        adverbs = spec.get("dropped_adverbs") or []
        if adverbs:
            # time adverbs that fill no role are left out in every reading, not only with the phrase variants
            new = re.sub(r"(?<!\S)(?:%s)(?!\S)\s*" % "|".join(re.escape(w) for w in adverbs), "", text).strip()
            if new != text and new:
                text, applied = new, applied + ["adverb"]
        zero = spec.get("zero_idiom") or {}
        if zero:
            # 하나도 없어요 / 한 켤레도 없습니다: the amount none, said as the count 0 with the verb of
            # presence in the same form (없어요 -> 0개 있어요)
            units = "|".join(re.escape(u) for u in sorted(self.counters.get("units", []), key=len, reverse=True))
            amounts = "|".join([re.escape(w) for w in zero.get("words", [])]
                               + (["%s ?(?:%s)도" % (re.escape(zero["one"]), units)] if zero.get("one") and units else []))
            new = re.sub(r"(?<!\S)(?:%s) %s(?=\S*)" % (amounts, re.escape(zero["absent"])),
                         "%s %s" % (zero["reads_as"], zero["present"]), text)
            if new != text:
                text, applied = new, applied + ["zero_idiom"]
        marker = spec.get("genitive_quantifier")
        if marker:
            # 열한 개의 메달을 -> 메달을 열한 개: an amount said before its thing with the genitive
            from numeral_semantics import parse_numeral
            units = "|".join(re.escape(u) for u in sorted(self.counters.get("units", []), key=len, reverse=True))
            if units:
                def float_back(m):
                    amount = m.group(1)
                    if parse_numeral(amount, self.data.get("numerals", {})) is None and not amount.isdigit():
                        return m.group(0)
                    # the thing first, the amount after it, the thing's particle on the amount (숟가락 세 개를)
                    particle = m.group(5) or ""
                    if particle:
                        particle = self._particle_form(m.group(2), particle) if particle in self.particle_mates else particle
                    return "%s %s %s%s" % (m.group(4), amount, m.group(2), particle)
                new = re.sub(r"(\S+) ?(%s)(%s) (\S+?)(을|를|이|가|은|는|도)?(?=\s|$)" % (units, re.escape(marker)),
                             float_back, text)
                if new != text:
                    text, applied = new, applied + ["genitive_quantifier"]
        particles = spec.get("shifted_particles", [])
        if particles:
            new = re.sub(r"(\S+) (\S+) (%s)(?= )" % "|".join(re.escape(p) for p in particles),
                         lambda m: "%s %s %s" % (m.group(1), m.group(3), m.group(2))
                         if m.group(1).lower() in self._declared_verb_words() else m.group(0), text)
            if new != text:
                text, applied = new, applied + ["shifted_particle"]
        if not applied:
            return literal, None
        return text, {"id": "declared-word-order-v1", "forms": applied, "from": literal}

    def _only_dropped_words(self, literal):
        """True when every word of ``literal`` is inside a phrase the pack's phrase variants read
        as nothing (말바꿈 with an empty ``to``)."""
        flags = re.IGNORECASE if self.data.get("ignore_case") else 0
        rest = literal
        for row in sorted(self.phrase_variants, key=lambda r: len(r.get("from") or ""), reverse=True):
            source = row.get("from")
            if source and row.get("to", "") == "":
                rest = re.sub(r"(?<![\w'])%s(?![\w'])" % re.escape(source), " ", rest, flags=flags)
        return bool(literal.strip()) and not re.sub(r"[\s,.!?;:]+", "", rest)

    def _declared_verb_words(self):
        """Every form the inflection grammar computes for the verbs the pack reads (its examples'
        event verbs and its same-frame stems), lower-cased."""
        if getattr(self, "_verb_word_cache", None) is None:
            from hangul import inflect
            grammar = self.inflection_grammar or {}
            stems = {e["event_verb"] for e in self.data["examples"] if e.get("event_verb")}
            stems |= {stem for row in self.same_frame for stem in row.get("stems", [])}
            words = set(stems)
            for stem in stems:
                for tense in grammar.get("tenses", {}):
                    for ending in grammar.get("endings", {}):
                        try:
                            words |= {f["text"].lower() for f in inflect(stem, tense, ending, grammar, kind="regular")}
                        except (ValueError, KeyError):
                            continue
            self._verb_word_cache = words
        return self._verb_word_cache

    def _ends_in_particle(self, word):
        """A word that ends in one of the pack's case or slot particles (a Korean noun phrase's
        last word carries its case; a bare noun does not)."""
        particles = {p for group in self.slot_particles for p in group} | set(self.case_particles)
        # the stem before it is at least the pack's shortest owner (가은 is a name, not 가 + 은)
        shortest = int((self.possessor or {}).get("min_length", 1))
        return any(word.endswith(p) and len(word) - len(p) >= shortest for p in particles if p)

    def _holder_forms(self, literal):
        """A holder said other than by its bare name, read as the key the facts use (가진쪽꼴).

        The pack declares every form, each a closed class:

        * ``speaker``: the speaker's pronouns (``forms``: me, myself; 저, 제, 내 ...) read as
          the one speaker key (``key``: I, 나); after the key a verb form agrees as with any
          other holder (``agreement``: I have -> I has), contractions first (``contractions``:
          I've -> I have), and in a question the auxiliary before the key too (``inverted``);
          whole words of the speaker with a particle (``particle_forms``: 제가 -> 나가, 저한테
          -> 나한테) read the same way.
        * ``relation_name``: a possessor (``possessives``: my, our ...; or a name with
          ``possessive_suffix``: Omar's) and a relation word before a name read as the name
          (my cousin Ana -> Ana).
        * ``apposition``: a determiner (``determiners``) and up to three role words, a comma,
          a name and a comma read as the name (the courier, Lind, -> Lind).
        * ``own_relation``: the speaker's possessive (``self_possessives``: my; 제, 내) and a
          relation word with no name after it read as the relation word (my sister -> sister).
        * ``name_titles``: a title word after a name (씨) left out, the particle after it said
          in the form the name's last syllable takes (예린 씨가 -> 예린이가).
        * ``numeral_articles``: an article before a numeral left out (the two ladders -> two
          ladders).

        Words are matched as the pack writes them; a name is a word the pack's ``name`` pattern
        matches (a capitalised word in English). Nothing else is rewritten.
        """
        spec = self.holder_forms or {}
        if not spec or self._is_definition(literal):
            return literal, None
        text, applied = literal, []
        name = spec.get("name") or r"\S+"
        flags = re.IGNORECASE if self.data.get("ignore_case") else 0

        def words_re(words):
            return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
        speaker = spec.get("self") or {}
        key = speaker.get("reads_as")
        if key:
            for source, target in sorted((speaker.get("contractions") or {}).items(), key=lambda kv: -len(kv[0])):
                new = re.sub(r"(?<![\w'])%s(?![\w'])" % re.escape(source), target, text, flags=flags)
                if new != text:
                    text, applied = new, applied + ["contraction"]
            for source, target in sorted((speaker.get("particle_forms") or {}).items(), key=lambda kv: -len(kv[0])):
                new = re.sub(r"(?<![\w])%s(?![\w])" % re.escape(source), target, text)
                if new != text:
                    text, applied = new, applied + ["speaker"]
            forms = speaker.get("forms") or []
            if forms:
                new = re.sub(r"(?<![\w'])(?:%s)(?![\w'])" % words_re(forms), key, text, flags=flags)
                if new != text:
                    text, applied = new, applied + ["speaker"]
            inverted = speaker.get("inverted") or {}
            for verb, agreed in inverted.items():
                new = re.sub(r"(?<![\w'])%s %s(?![\w'])" % (re.escape(verb), re.escape(key)),
                             "%s %s" % (agreed, key), text, flags=flags)
                if new != text:
                    text, applied = new, applied + ["agreement"]
            auxiliaries = {w.lower() for pair in inverted.items() for w in pair}
            for verb, agreed in (speaker.get("agreement") or {}).items():
                def agree(m):
                    before = text[:m.start()].split()
                    # after an auxiliary the verb is its infinitive (does I have): left as it is; a
                    # coordinated subject (Vera and I have) is plural and agrees as plural
                    if before and before[-1].lower() in auxiliaries | {"and", "or", "nor"}:
                        return m.group(0)
                    return "%s %s" % (key, agreed)
                new = re.sub(r"(?<![\w'])%s %s(?![\w'])" % (re.escape(key), re.escape(verb)), agree, text)
                if new != text:
                    text, applied = new, applied + ["agreement"]
        prefix_titles = spec.get("prefix_titles") or []
        if prefix_titles:
            # a title before a name (Mr. Lind, Dr. Moore) names the holder by the name
            new = re.sub(r"(?<![\w'])(?:%s) (?=%s(?![\w]))" % (words_re(prefix_titles), name), "", text)
            if new != text:
                text, applied = new, applied + ["title"]
        possessives = spec.get("possessives") or []
        suffixes = spec.get("possessive_suffix") or []
        relation = r"[^\s,.!?]+"
        if possessives or suffixes:
            owners = []
            if possessives:
                owners.append(r"(?i:%s)" % words_re(possessives))
            if suffixes:
                owners.append(r"%s(?:%s)" % (name, words_re(suffixes)))
            pattern = r"(?<![\w'])(%s) ((?:%s ){0,1}?%s) (%s)(?![\w'])" % ("|".join(owners), relation, relation, name)

            def is_owner(word):
                # an owner said by name is a bare name: no particle but a declared possessive, no numeral,
                # no word outside names, no pointer
                from numeral_semantics import parse_numeral
                bare = next((word[:-len(x)] for x in suffixes if x and word.endswith(x) and len(word) > len(x)), word)
                return (word.lower() in {w.lower() for w in possessives} or
                        (not self._ends_in_particle(bare) and bare.lower() not in self.outside_names
                         and bare.lower() not in self.pointers and not bare.isdigit()
                         and parse_numeral(bare.lower(), self.data.get("numerals", {})) is None))

            def is_relation(words):
                # a relation noun is a bare content word: never a word outside names (a preposition),
                # a numeral, a pointer, or a word that already carries a case particle; where the pack
                # declares its relation nouns (a language whose names stand bare beside nouns), one of them
                from numeral_semantics import parse_numeral
                if spec.get("relation_nouns") is not None:
                    return words in spec["relation_nouns"]
                return all(w.lower() not in self.outside_names and w.lower() not in self.pointers
                           and not w.isdigit() and parse_numeral(w.lower(), self.data.get("numerals", {})) is None
                           and not self._ends_in_particle(w)
                           for w in words.split())
            new = re.sub(pattern, lambda m: m.group(3) if is_owner(m.group(1)) and is_relation(m.group(2))
                         else m.group(0), text)
            if new != text:
                text, applied = new, applied + ["relation_name"]
        determiners = spec.get("determiners") or []
        if determiners:
            pattern = r"(?<![\w'])(?i:%s) (?:[a-z]+ ){0,2}[a-z]+, (%s)(?:,|(?=$))" % (words_re(determiners), name)
            new = re.sub(pattern, r"\1", text)
            if new != text:
                text, applied = new, applied + ["apposition"]
        own = spec.get("self_possessives") or []
        if own:
            pattern = r"(?<![\w'])(?i:%s) (%s)(?![\w'])" % (words_re(own), relation)
            from numeral_semantics import parse_numeral

            def own_relation(m):
                word = m.group(1)
                if word.lower() in self.outside_names or word.isdigit() or \
                        parse_numeral(word.lower(), self.data.get("numerals", {})) is not None:
                    return m.group(0)
                if spec.get("relation_nouns") is not None:
                    particles = sorted({x for g in self.slot_particles for x in g} | set(self.case_particles)
                                       | set(spec.get("delimiters") or []), key=len, reverse=True)
                    stem = next((word[:-len(x)] for x in particles if word.endswith(x) and len(word) > len(x)
                                 and word[:-len(x)] in spec["relation_nouns"]), word)
                    if stem not in spec["relation_nouns"]:
                        return m.group(0)
                # a bare relation word before a name belongs to the close apposition (my cousin Ana)
                if not self._ends_in_particle(word) and re.match(r" (?:%s)(?![\w'])" % name, text[m.end():]):
                    return m.group(0)
                return word
            new = re.sub(pattern, own_relation, text)
            if new != text:
                text, applied = new, applied + ["own_relation"]
        particle_alt = "|".join(re.escape(p) for p in sorted(
            {p for g in self.slot_particles for p in g} | set(self.case_particles)
            | {row["from"] for row in self.particle_variants if row.get("from")}
            | set(spec.get("delimiters") or []), key=len, reverse=True)) or "(?!)"
        role_titles = spec.get("role_titles") or []
        if role_titles:
            # one or two bare role words before a titled name (인턴 예린 씨, 택배 기사 은우 씨): the name
            from numeral_semantics import parse_numeral
            all_particles = {x for g in self.slot_particles for x in g} | set(self.case_particles)
            units = set(self.counters.get("units", []))

            def unrole(m):
                # a role word carries no particle at all, and is no numeral, counter or word outside names
                roles = m.group(1).split()
                if any(any(w.endswith(x) for x in all_particles) or w in role_titles or w in units
                       or w.lower() in self.outside_names
                       or parse_numeral(w, self.data.get("numerals", {})) is not None for w in roles):
                    return m.group(0)
                return m.group(2) + m.group(3)
            pattern = r"(?<!\S)((?:%s ){1,2})(%s)( ?(?:%s))(?=(?:%s)?(?![\w]))" % (
                name, name, words_re(role_titles), particle_alt)
            new = re.sub(pattern, unrole, text)
            if new != text:
                text, applied = new, applied + ["role"]
        titles = spec.get("name_titles") or []
        if titles:
            def untitle(m):
                stem, particle = m.group(1), m.group(3) or ""
                return stem + (self._particle_form(stem, particle) if particle else "")
            pattern = r"(?<!\S)(%s) ?(%s)(%s)?(?![\w])" % (name, words_re(titles), particle_alt)
            new = re.sub(pattern, untitle, text)
            if new != text:
                text, applied = new, applied + ["title"]
        articles = spec.get("numeral_articles") or []
        if articles:
            from numeral_semantics import parse_numeral
            numerals = self.data.get("numerals", {})

            def drop(m):
                # (one after an article is the pronoun: the one given)
                value = m.group(2) if m.group(2).isdigit() else parse_numeral(
                    m.group(2).lower() if flags else m.group(2), numerals)
                return m.group(2) if value is not None and str(value) != "1" else m.group(0)
            # (not before a partitive: the two of them names holders, not an amount)
            new = re.sub(r"(?<![\w'])(%s) (\S+)(?! of\b)" % words_re(articles), drop, text, flags=flags)
            if new != text:
                text, applied = new, applied + ["numeral_article"]
        if not applied:
            return literal, None
        return text, {"id": "declared-holder-forms-v1", "forms": sorted(set(applied)), "from": literal}

    def _float_quantifier(self, literal):
        """``하루는 꿀꿀이 한 마리를 가지고 있어`` -> ``하루는 꿀꿀이를 한 마리 가지고 있어``.

        A structural case particle (어순바꿈.floating_cases) on a numeral's counter
        is read on the counted noun right before the numeral instead; the noun
        is kept as typed and takes the particle's form its last syllable selects.
        """
        from numeral_semantics import parse_numeral
        cases = sorted((self.object_fronting or {}).get("floating_cases") or [], key=len, reverse=True)
        units = sorted((self.counters or {}).get("units", []), key=len, reverse=True)
        words = literal.split()
        if not cases or not units or len(words) < 3:
            return literal, None
        numerals = self.data.get("numerals", {})
        for at in range(1, len(words) - 1):
            number, counted = words[at], words[at + 1]
            fused = re.fullmatch(r"(\d+)(.+)", number)
            if fused:                       # ``1마리를``: digits and counter in one word
                number, counted, span = fused.group(1), fused.group(2), 1
            else:
                span = 2
            if not (re.fullmatch(r"\d+", number) or parse_numeral(number, numerals) is not None):
                continue
            unit = next((u for u in units if counted.startswith(u)), None)
            case = counted[len(unit):] if unit else None
            if not case or case not in cases:
                continue
            noun = words[at - 1]
            # The counted noun is bare: a word that already ends in a particle
            # (``지연은``, ``모래에게``) is another argument. A final 이 may be the
            # noun's own syllable (``고양이``, ``꿀꿀이``), so it does not stop it.
            particles = {p for p in self.case_particles} | {p for group in self.slot_particles for p in group}
            own = set((self.object_fronting or {}).get("floating_noun_endings") or [])
            if self._protected_kind(noun) is not None or any(
                    noun.endswith(p) and len(noun) > len(p) and p not in own
                    and self._particle_form(noun[:-len(p)], p) == p for p in particles):
                continue
            moved = (words[:at - 1] + [noun + self._particle_form(noun, case)]
                     + ([number + unit] if span == 1 else [number, unit]) + words[at + span:])
            return " ".join(moved), {"id": "declared-floating-quantifier-v1", "case": case, "noun": noun}
        return literal, None

    def _front_object(self, literal):
        """``구슬 세 개를 A가 B에게 줬다`` -> ``A가 B에게 구슬 세 개를 줬다``."""
        spec = self.object_fronting or {}
        objects, subjects = spec.get("object_particles", []), spec.get("subject_particles", [])
        words = literal.split()
        if not objects or len(words) < 4:
            return literal, None
        at = next((i for i, w in enumerate(words[:-2])
                   if any(w.endswith(p) and len(w) > len(p) for p in objects)), None)
        if at is None or not any(words[at + 1].endswith(p) and len(words[at + 1]) > len(p) for p in subjects):
            return literal, None
        moved = words[at + 1:-1] + words[:at + 1] + words[-1:]
        return " ".join(moved), {"id": "declared-object-fronting-v1", "moved": " ".join(words[:at + 1])}

    def _scramble(self, literal):
        """``B에게 A가 구슬 세 개를 줬다`` -> ``A가 B에게 구슬 세 개를 줬다``.

        Case-marked arguments may stand in any order before the verb. The pack
        declares the case particles and the order its examples are written in
        (어순바꿈.order: one list of particles per position). Every word before
        the verb must end a phrase marked by one of them; each phrase keeps its
        words, and two phrases of one position are not reordered.
        """
        order = (self.object_fronting or {}).get("order") or []
        words = literal.split()
        if len(order) < 2 or len(words) < 3:
            return literal, None
        ranked = sorted(((particle, rank) for rank, group in enumerate(order) for particle in group),
                        key=lambda row: len(row[0]), reverse=True)
        groups, current = [], []
        for word in words[:-1]:
            current.append(word)
            rank = next((r for p, r in ranked if word.endswith(p) and len(word) > len(p)), None)
            if rank is not None:
                groups.append((rank, current))
                current = []
        ranks = [rank for rank, _words in groups]
        if current or len(set(ranks)) != len(ranks) or ranks == sorted(ranks):
            return literal, None
        moved = [word for _rank, phrase in sorted(groups, key=lambda g: g[0]) for word in phrase]
        return " ".join(moved + words[-1:]), {"id": "declared-scrambling-v1", "from": literal}

    def _passive(self, literal):
        """``2 marbles were handed to Moru by Haru`` -> ``Haru gave Moru 2 marbles``.

        The pack declares its passive (수동태): the auxiliary forms, the
        recipient and agent markers. The participle must be the declared
        participle of a verb the pack reads; the clause is said again in the
        active voice with that verb's past form (or the form its same-frame
        row reads it as). Nothing is read without both markers.
        """
        spec = getattr(self, "passive", None) or {}
        auxiliaries, to, by = spec.get("auxiliaries", []), spec.get("recipient"), spec.get("agent")
        if not auxiliaries or not to or not by:
            return literal, None
        flags = re.IGNORECASE if self.data.get("ignore_case") else 0
        match = re.fullmatch(r"(?P<theme>.+?) (?P<aux>%s) (?P<part>\S+) %s (?P<to>.+?) %s (?P<by>.+)" % (
            "|".join(re.escape(a) for a in auxiliaries), re.escape(to), re.escape(by)), literal, flags)
        if not match:
            return literal, None
        past = self._participle_pasts().get(match.group("part").lower() if flags else match.group("part"))
        if past is None:
            return literal, None
        active = "%s %s %s %s" % (match.group("by"), past, match.group("to"), match.group("theme"))
        return active, {"id": "declared-passive-v1", "participle": match.group("part"), "as": past}

    def _participle_pasts(self):
        """Participle -> the past form the examples are written with, for every declared verb."""
        if getattr(self, "_participle_table", None) is None:
            from hangul import inflect
            grammar = self.inflection_grammar or {}
            table = {}
            reads = {}
            for row in self.same_frame:
                for stem in row.get("stems", []):
                    reads.setdefault(stem, row.get("read_as"))
            stems = set(reads) | {e["event_verb"] for e in self.data["examples"] if e.get("event_verb")}
            for stem in sorted(stems):
                try:
                    participles = [f["text"] for f in inflect(stem, "past", "participle", grammar, kind="regular")]
                    pasts = [f["text"] for f in inflect(stem, "past", "plain", grammar, kind="regular")]
                except (ValueError, KeyError):
                    continue
                target = reads.get(stem) or (pasts[0] if pasts else None)
                for participle in participles:
                    if target:
                        table.setdefault(participle, target)
            self._participle_table = table
        return self._participle_table

    def _role_swap_forms(self):
        """Inflected form of a taker-side verb -> (row, the same form of its giver-side verb)."""
        if self._role_swap_table is None:
            from hangul import inflect
            grammar = self.inflection_grammar or {}
            table = {}
            for row in self.role_swaps:
                for tense in grammar.get("tenses", {}):
                    for ending in grammar.get("endings", {}):
                        try:
                            forms = [f["text"] for f in inflect(row["stem"], tense, ending, grammar, kind=row.get("kind", "regular"))]
                            target = [f["text"] for f in inflect(row["as"], tense, ending, grammar, kind=row.get("kind", "regular"))]
                        except (ValueError, KeyError):
                            continue
                        for form in forms:
                            if target:
                                table.setdefault(form, (row, target[0]))
            self._role_swap_table = table
        return self._role_swap_table

    def _swap_roles(self, literal):
        """``A가 B에게서 … 받았다`` / ``A가 B(의) … 가져갔다`` -> ``B가 A에게 … 줬다``."""
        words = literal.split()
        if len(words) < 4:
            return literal, None
        found = self._role_swap_forms().get(words[-1])
        if found is None:
            return literal, None
        row, verb = found
        subject = next((p for p in row.get("subject_particles", ["이", "가"])
                        if words[0].endswith(p) and len(words[0]) > len(p)), None)
        if subject is None:
            return literal, None
        taker = words[0][:-len(subject)]
        middle = words[1:-1]
        if row.get("shape") == "source":
            at = next((i for i, w in enumerate(middle)
                       for p in row.get("source_particles", []) if w.endswith(p) and len(w) > len(p)), None)
            if at is None:
                return literal, None
            particle = next(p for p in row["source_particles"] if middle[at].endswith(p))
            giver = middle[at][:-len(particle)]
            rest = middle[:at] + middle[at + 1:]
        else:
            from numeral_semantics import parse_numeral
            if len(middle) < 3 or parse_numeral(middle[1], self.data.get("numerals", {})) is not None:
                return literal, None
            giver = middle[0]
            for particle in row.get("owner_particles", []):
                if giver.endswith(particle) and len(giver) > len(particle):
                    giver = giver[:-len(particle)]
                    break
            rest = middle[1:]
        swapped = [giver + self._particle_form(giver, "이"), taker + "에게"] + rest + [verb]
        return " ".join(swapped), {"id": "declared-role-swap-v1", "verb": words[-1], "as": verb}

    def _clause_candidates(self, literal):
        yield from self._clause_candidates_of(literal)
        for replaced, notes in self._variant_literals(literal):
            for candidate, normalization in self._clause_candidates_of(replaced):
                base = normalization or {"id": notes[0]["id"], "canonical": candidate, "words_only": True}
                yield candidate, {**base, "variants": notes}

    def _clause_candidates_of(self, literal):
        from hangul import canonical_clauses
        yield from canonical_clauses(literal, self.clause_grammar)
        node = self._inflection_trie
        for length, char in enumerate(reversed(literal), 1):
            node = node.get(char)
            if node is None:
                break
            for index, canonical, trace in node.get(None, []):
                yield literal[:-length] + canonical, {**trace, "example_index": index}
        yield from self._do_support_negation(literal)
        # 부정은 별도 동사 사례가 아니다. 언어팩이 계산한 `않다` 꼴을 걷어 내고,
        # 이미 선언된 어간의 마침꼴만 다시 만든다. 따라서 어떤 새 동사나 문장을
        # 긍정 사건으로 추측하지 않으며, 아래에서 polarity=False가 보존된다.
        forms = self.negation.get("forms", set())
        connector = self.negation.get("연결", "")
        for negative in forms:
            marker = " " + negative
            if not connector or not literal.endswith(marker):
                continue
            before = literal[:-len(marker)]
            if not before.endswith(connector):
                continue
            root = before[:-len(connector)]
            for index, example in enumerate(self.data["examples"]):
                annotation = example.get("inflection")
                if not annotation or not root.endswith(annotation["stem"]):
                    continue
                stem_prefix = root[:-len(annotation["stem"])]
                for tense in annotation.get("tenses", [annotation["tense"]]):
                    for ending in self.inflection_grammar.get("parsing_endings", []):
                        try:
                            realized = self._inflected_forms(annotation["stem"], tense, ending,
                                                             annotation["kind"])
                        except ValueError:
                            continue
                        for form in realized:
                            candidate = stem_prefix + form
                            yield candidate, {"id": "declared-negation-v1",
                                              "canonical": candidate, "example_index": index,
                                              "polarity": False}

    def _do_support_negation(self, literal):
        """``Haru did not give Moru 2 marbles`` -> ``Haru gave Moru 2 marbles``, not asserted.

        The pack declares its do-support (부정.do_support: which form of do
        carries which form of the verb), the negative particles and the
        contracted forms. The verb after them must be one the pack inflects
        (its lexicon, or a same-frame stem); its form is computed. The reading
        is the positive clause with polarity False: nothing it names changes.
        """
        from hangul import inflect
        spec = self.negation or {}
        support = spec.get("do_support") or {}
        if not support:
            return
        grammar = self.inflection_grammar or {}
        known = set((grammar.get("lexicon") or {})) | {stem for row in self.same_frame for stem in row.get("stems", [])}
        words = literal.split()
        for at, word in enumerate(words[:-1]):
            folded = word.lower()
            if folded in spec.get("contractions", {}):
                aux, verb_at = spec["contractions"][folded], at + 1
            elif folded in support and at + 2 < len(words) and words[at + 1].lower() in spec.get("particles", []):
                aux, verb_at = folded, at + 2
            else:
                continue
            verb = words[verb_at]
            # A same-frame variant may already have written the verb as the
            # form its frame reads as (``hand`` -> ``gave``): that form stays.
            read_as = {target.lower() for target, _note in self._variants().values() if target}
            if verb.lower() not in known and verb.lower() not in read_as:
                continue
            form = support[aux]
            if verb.lower() in read_as and verb.lower() not in known:
                said = verb
            elif form == "base":
                said = verb
            else:
                try:
                    made = inflect(verb.lower(), "past" if form == "past" else "present",
                                   "plain" if form == "past" else "third_person", grammar, kind="regular")
                except (ValueError, KeyError):
                    continue
                if not made:
                    continue
                said = made[0]["text"]
            candidate = " ".join(words[:at] + [said] + words[verb_at + 1:])
            yield candidate, {"id": "declared-negation-v1", "canonical": candidate, "polarity": False,
                              "words_only": True}
            return

    def _repair(self, literal):
        """No declared rule reads ``literal``: find the nearest one at a measured cost.

        Repair is matching at a distance, not guessing. Every edit either moves,
        drops or reorders what was typed, or adds a particle/ending the pack
        declares; nothing else can enter the reading. The edit kinds and their
        costs, the accepting bound and the reporting bound all come from the
        language pack. Returns ``(meanings, derivations, report)``: meanings are
        empty when nothing fits within the bound, and ``report`` then says what
        the nearest reading would have needed.
        """
        spec = self.repair
        costs = spec.get("costs", {})
        if not costs or not literal.strip():
            return {}, {}, None
        # A holder said by a declared holder form (제가, 예린 씨, 제 룸메이트) is repaired as the
        # holder it names: the typed words are that holder's form, not words to move.
        held, note = self._holder_forms(literal)
        if note is not None and held != literal and not set(note["forms"]) <= {"numeral_article"}:
            return self._repair(held)
        # A relative clause's past verb (잃어버렸던) is no place or name to repair a particle onto.
        if self._names_hold_adnominal({"triple": [literal, "", ""]}):
            return {}, {}, None
        cached = self._repair_cache.get(literal)
        if cached is not None:
            return copy.deepcopy(cached)
        import heapq
        from itertools import count
        bound, reach, budget = spec["bound"], spec["report_bound"], spec["budget"]
        particles = sorted({p for p in self.case_particles} |
                           {p for group in self.slot_particles for p in group}, key=len, reverse=True)
        insertable = spec.get("insert_particles", [])
        # 이름 자리에 들어갈 수 없는 닫힌 갈래의 말(정도·때 부사 등). 수선이 이런
        # 말을 이름에 붙여 `민수 사과 정말` 같은 대상을 만들지 못하게 한다.
        outside = {word.lower() for word in spec.get("not_in_names", [])}
        endings = self._declared_endings()

        def tail_particle(word):
            return [p for p in particles if len(word) > len(p) and word.endswith(p)
                    and self._particle_form(word[:-len(p)], p) == p]

        # 친 말에서 `이름+꼬리+조사` 로 나온 낱말의 `이름+꼬리` 는 조사 붙은 말이 아니다.
        named = self._suffixed_names(literal.split(), tail_particle)

        def marked_word(word):
            return [] if word in named else tail_particle(word)

        def neighbours(words):
            n = len(words)
            for i, word in enumerate(words):
                for p in tail_particle(word):
                    bare = word[:-len(p)]
                    if "particle_drop" in costs:
                        yield (words[:i] + (bare,) + words[i + 1:],
                               {"op": "particle_drop", "word": word, "particle": p})
                    if "particle_move" in costs:
                        for j, other in enumerate(words):
                            if j != i and not tail_particle(other) and not self._is_verb_form(other):
                                moved = list(words)
                                fitted = self._particle_form(other, p)
                                moved[i], moved[j] = bare, other + fitted
                                yield (tuple(moved), {"op": "particle_move", "word": word,
                                                      "particle": p, "to": other,
                                                      **({"as": fitted} if fitted != p else {})})
                if "particle_insert" in costs and not tail_particle(word) and not self._is_verb_form(word):
                    for p in insertable:
                        fitted = self._particle_form(word, p)
                        yield (words[:i] + (word + fitted,) + words[i + 1:],
                               {"op": "particle_insert", "word": word, "particle": fitted})
                if "token_skip" in costs and n > 1:
                    yield (words[:i] + words[i + 1:], {"op": "token_skip", "word": word})
                if "adjacent_swap" in costs and i + 1 < n:
                    yield (words[:i] + (words[i + 1], word) + words[i + 2:],
                           {"op": "adjacent_swap", "word": word, "to": words[i + 1]})
            if "ending_restore" in costs and words:
                for form in endings.get(words[-1], ()):
                    yield (words[:-1] + (form,), {"op": "ending_restore", "word": words[-1], "to": form})

        start = tuple(literal.split())
        ticket = count()
        frontier = [(0, next(ticket), start, ())]
        seen = {start: 0}
        found, found_cost, expanded = [], None, 0
        protected = None
        while frontier:
            cost, _t, words, path = heapq.heappop(frontier)
            if found_cost is not None and cost > found_cost:
                break
            if cost > reach:
                break
            if path:
                derivations, matched = {}, {}
                candidate = " ".join(words)
                readings = self._clause_meanings(candidate, derivations=derivations, matched=matched,
                                                 guard_names=False)
                # A repaired reading must place every marked word in its own
                # role. A name that swallows a word carrying an agreeing
                # particle (``민수는 사과``) is the misreading repair exists to
                # avoid, so it is not a reading at any cost.
                readings = {key: meaning for key, meaning in readings.items()
                            if not self._swallows_marked_word(meaning, marked_word)
                            and not self._names_hold(meaning, outside)
                            and not self._names_an_amount(meaning)}
                # A repair never changes a numeral, a counter, a scope word or a
                # negation (G2.5): a reading that needs such an edit, or that puts
                # such a word inside a name, is not taken. The nearest one is kept
                # so the hold can say what it would have changed.
                changed = self._protected_edits(path) if readings else []
                inside = {key: self._protected_in_names(meaning) for key, meaning in readings.items()}
                changed += [row for rows in inside.values() for row in rows
                            if not any(row["word"] == seen["word"] for seen in changed)]
                if changed:
                    if protected is None or cost < protected[0]:
                        protected = (cost, candidate, path, changed)
                    continue
                if readings:
                    found_cost = cost
                    found.append((candidate, path, readings, derivations, matched))
                    continue
            expanded += 1
            if expanded > budget:
                break
            for following, step in neighbours(words):
                total = cost + costs[step["op"]]
                if total <= reach and total < seen.get(following, total + 1):
                    seen[following] = total
                    heapq.heappush(frontier, (total, next(ticket), following, path + (step,)))
        if protected is not None and protected[0] <= reach and (not found or protected[0] <= found_cost):
            # The nearest reading would change a protected word: hold, and say which.
            cost, candidate, path, changed = protected
            report = {"status": "protected", "source": literal, "reading": candidate,
                      "operations": [dict(step) for step in path], "cost": cost, "bound": bound,
                      "rule": None, "changed": changed}
            self._repair_cache[literal] = ({}, {}, report)
            return {}, {}, copy.deepcopy(report)
        if not found:
            report = {"status": "unplaced", "source": literal, "bound": bound,
                      "cost": None, "searched_cost": reach, "rule": None, "operations": []}
            self._repair_cache[literal] = ({}, {}, report)
            return {}, {}, copy.deepcopy(report)
        distinct = {}
        for candidate, path, readings, derivations, matched in found:
            for key, meaning in readings.items():
                distinct.setdefault(key, (candidate, path, meaning, derivations.get(key), matched.get(key)))
        candidate, path, meaning, inner, index = next(iter(distinct.values()))
        rule = self.data["examples"][index]["text"] if index is not None else None
        report = {"source": literal, "reading": candidate, "operations": [dict(step) for step in path],
                  "cost": found_cost, "bound": bound, "rule": rule, "rule_index": index}
        if found_cost > bound:
            report["status"] = "over_bound"
            result = ({}, {}, report)
        elif len(distinct) > 1:
            report["status"] = "ambiguous"
            report["readings"] = [value[0] for value in distinct.values()]
            result = ({}, {}, report)
        else:
            report["status"] = "repaired"
            key = next(iter(distinct))
            derivation = {"rule": "declared-repair-v1", "canonical": candidate, "repair": report}
            for field in ("stem", "tense", "ending", "operations"):
                if inner and field in inner:
                    derivation[field] = inner[field]
            result = ({key: meaning}, {key: derivation}, report)
        self._repair_cache[literal] = result
        return copy.deepcopy(result)

    def _protected_kind(self, word):
        """What a repair may not change in ``word``: a numeral, a counter, a scope
        word or a negation (the pack's 수선.protected and its numerals and
        counters), or None."""
        from numeral_semantics import parse_numeral
        declared = (self.repair or {}).get("protected", {})
        core = str(word).strip(".,!?\"'")
        folded = core.lower()
        if any(re.search(pattern, folded) for pattern in declared.get("negation", [])):
            return "negation"
        particles = sorted(set(self.case_particles) | {p for group in self.slot_particles for p in group},
                           key=len, reverse=True)
        # A particle is taken off only where it agrees with the word before it
        # (``둘이``, not ``사과`` = 사 + 과).
        bare = next((core[:-len(p)] for p in particles if core.endswith(p) and len(core) > len(p)
                     and self._particle_form(core[:-len(p)], p) == p), core)
        if folded in declared.get("scope", []) or bare.lower() in declared.get("scope", []):
            return "scope"
        numerals = self.data.get("numerals", {})
        if re.search(r"\d", core) or parse_numeral(folded, numerals) is not None \
                or parse_numeral(bare.lower(), numerals) is not None:
            return "numeral"
        units = (self.counters or {}).get("units", [])
        copula = (self.count_question or {}).get("copula", [])
        for unit in sorted(units, key=len, reverse=True):
            rest = core[len(unit):]
            if core.startswith(unit) and (not rest or rest in particles or rest in copula):
                return "counter"
        return None

    def _protected_edits(self, path):
        """Protected words an edit path changes, as ``[{"word", "kind"}]``.

        A scope word or a negation may not be touched at all, not even its
        particle (``둘이`` -> ``둘`` turned a total into another reading). A
        numeral or a counter may not be skipped or swapped: that changes the
        amount or what it counts. Its case particle may be restored, dropped or
        moved (``두 개 줬어`` -> ``두 개를 줬어``): the amount and the unit stay.
        """
        out = []
        for step in path:
            op = step.get("op")
            for key in ("word", "to"):
                word = step.get(key)
                kind = self._protected_kind(word) if word else None
                if kind in ("numeral", "counter") and op not in ("token_skip", "adjacent_swap"):
                    continue
                if kind and not any(row["word"] == word for row in out):
                    out.append({"word": word, "kind": kind})
        return out

    def _names_an_amount(self, meaning):
        """A name that holds a numeral word with the pack's counter after it (``사과
        다섯 개``): an amount is never part of a holder's, a thing's or a place's
        name, so that is not a reading (a numeral word alone may be a noun: 공)."""
        rows = asserted(meaning) or [joined(q["triple"]) for q in meaning.get("query", [])
                                     if isinstance(q, dict) and isinstance(q.get("triple"), list)]
        units = sorted((self.counters or {}).get("units", []), key=len, reverse=True)
        for row in rows:
            for value in (row[0], row[2]):
                words = value.split() if isinstance(value, str) else []
                if any(self._protected_kind(word) == "numeral" and self._protected_kind(after) == "counter"
                       for word, after in zip(words, words[1:])):
                    return True
                # digits written together with their counter (``12개``)
                if any(re.fullmatch(r"\d+(%s)\S*" % "|".join(map(re.escape, units)), word) for word in words
                       if units):
                    return True
        return False

    def _protected_in_names(self, meaning):
        """Protected words a reading put inside an entity name."""
        rows = asserted(meaning) or [joined(q["triple"]) for q in meaning.get("query", [])
                                     if isinstance(q, dict) and isinstance(q.get("triple"), list)]
        out = []
        for row in rows:
            for value in (row[0], row[2]):
                if not isinstance(value, str) or len(value.split()) < 2:
                    continue
                words = value.split()
                titles = set((self.holder_forms or {}).get("job_titles") or [])
                for index, word in enumerate(words):
                    # a surname before a job title (안 기사, 안 팀장) is a name, however it reads alone
                    if index + 1 < len(words) and titles and any(
                            words[index + 1].startswith(t) for t in titles) and index == 0:
                        continue
                    kind = self._protected_kind(word)
                    # A numeral word can also be a noun (공 is a ball and zero, 사
                    # a word and four); inside a name only written digits count.
                    if kind in ("numeral", "counter") and not re.search(r"\d", word):
                        continue
                    if kind and not any(item["word"] == word for item in out):
                        out.append({"word": word, "kind": kind})
        return out

    def _number_agreement(self, slots, example):
        """Key a thing counted as one by its declared plural (``one apple`` -> ``apples``)."""
        declared = self.noun_number
        if not declared or "item" not in slots or not slots.get("item"):
            return slots
        one = str(declared.get("count_slot_value", 1))
        counts = [name for name, annotated in example["slots"].items() if annotated.isdecimal()]
        # An example may say its thing in the singular whatever the count (not a single marble).
        if not example.get("item_counted_as_one") and (
                not counts or any(str(slots.get(name)) != one for name in counts)):
            return slots
        words = slots["item"].split()
        # In a partitive (``jar of jam``) the number is marked on the measure
        # noun before the declared preposition, not on the last word.
        head = next((words.index(marker) - 1 for marker in declared.get("partitive", [])
                     if marker in words[1:]), len(words) - 1)
        many = declared_plural(words[head], declared)
        if many is None:
            return slots
        words[head] = many
        return {**slots, "item": " ".join(words)}

    def _answer_total(self, request, known, changes, proof):
        """Sum the current counts of the members a total question names.

        Members are named, or ``all`` (or a declared pointer such as "they")
        for every holder of the item. With no item, every holder must hold
        one kind of thing. Fewer than two members, or a member with no count,
        gives no answer.
        """
        from graph_inference import leading_word_referent
        spec = request["total"]
        item = spec.get("item")
        counts = {subject: value for subject, predicate, value in known
                  if predicate == "count" and isinstance(subject, str)}
        members = spec.get("members")
        pointers = {word.lower() for word in self.pointers}
        if members in ("all", "two") or (isinstance(members, list)
                                         and any(str(m).lower() in pointers for m in members)):
            subjects = [s for s in counts if item is None or s == item or s.endswith(" " + item)]
            if item is None and len({tuple(s.split()[1:]) for s in subjects}) > 1:
                return None
            # "the two of them" is a sum of two: with more holders it does not say which two
            if members == "two" and len(set(subjects)) != 2:
                return None
        elif isinstance(members, list):
            subjects = []
            for member in members:
                name = self.canonical_name(str(member))
                subject = ("%s %s" % (name, item)) if item else leading_word_referent(
                    name, "count", dict.fromkeys((s, "count") for s in counts))
                if subject not in counts:
                    return None
                subjects.append(subject)
        else:
            return None
        if len(set(subjects)) < 2 or not all(str(counts[s]).lstrip("-").isdigit() for s in subjects):
            return None
        value = sum(int(counts[s]) for s in subjects)
        render = request.get("render") or ["$n"]
        answer = "".join(str(part).replace("$n", str(value)).replace("$item", item or "") for part in render)
        transitions = list(changes)
        for subject in sorted(set(subjects)):
            transitions += proof(known, (subject, "count", counts[subject]))
        return {"answer": answer, "transitions": transitions}

    def _compared(self, request, known, changes, proof):
        """The two named holders' counts of the item: ``(a, count), (b, count), transitions``."""
        from graph_inference import leading_word_referent
        item = request.get("item")
        counts = {subject: value for subject, predicate, value in known
                  if predicate == "count" and isinstance(subject, str)}
        present = dict.fromkeys((subject, "count") for subject in counts)
        named = []
        for key in ("a", "b"):
            name = self.canonical_name(str(request.get(key) or ""))
            if not name:
                return None
            subject = ("%s %s" % (name, item)) if item else leading_word_referent(name, "count", present)
            if subject not in counts or not str(counts[subject]).lstrip("-").isdigit():
                return None
            named.append((name, subject, int(counts[subject])))
        (a, sa, va), (b, sb, vb) = named
        if sa == sb:
            return None
        transitions = list(changes)
        for subject in (sa, sb):
            transitions += proof(known, (subject, "count", counts[subject]))
        return (a, va), (b, vb), transitions

    def _comparison_answer(self, key, **values):
        """A declared answer frame of a comparison (관계해석.comparison_answers), or None."""
        render = (self.data.get("comparison_answers") or {}).get(key)
        if not isinstance(render, list):
            return None
        return "".join(str(values.get(part[1:], part)) if part.startswith("$") else part for part in render)

    def _answer_more(self, request, known, changes, proof, fewer=False):
        """Which of two named holders has more (``fewer``: fewer) of the item now.
        Equal counts answer with the pack's tie frame, or not at all."""
        compared = self._compared(request, known, changes, proof)
        if compared is None:
            return None
        (a, va), (b, vb), transitions = compared
        if va == vb:
            tie = self._comparison_answer("tie", a=a, b=b, n=va)
            return {"answer": tie, "transitions": transitions, "tie": True} if tie else None
        winner = (a if va < vb else b) if fewer else (a if va > vb else b)
        return {"answer": winner + self.data["answer_suffix"], "transitions": transitions}

    def _answer_same(self, request, known, changes, proof):
        """Whether two named holders have the same count of the item now."""
        compared = self._compared(request, known, changes, proof)
        if compared is None:
            return None
        (a, va), (b, vb), transitions = compared
        answer = self._comparison_answer("same" if va == vb else "different", a=a, b=b, n=va, m=vb)
        return {"answer": answer, "transitions": transitions} if answer else None

    def canonical_name(self, subject):
        """A subject's leading name written without the pack's name suffix.

        ``가람이 구슬`` and ``가람 구슬`` are one holder; one written form
        keeps facts and questions on the same key. Only a suffix after a
        consonant-final stem is removed; without a declared suffix nothing is.
        """
        from hangul import batchim
        suffix = self.name_suffix
        if not suffix or not isinstance(subject, str) or not subject.strip():
            return subject
        words = subject.split(" ")
        first = words[0]
        if first.endswith(suffix) and len(first) > len(suffix) and batchim(first[:-len(suffix)]):
            words[0] = first[:-len(suffix)]
        return " ".join(words)

    def _particle_marked_slots(self, index, example):
        """Slots the example follows directly with a declared case particle."""
        cache = self.__dict__.setdefault("_marked_slot_cache", {})
        if index not in cache:
            particles = {p for group in self.slot_particles for p in group} | set(self.case_particles)
            marked = []
            for name, value in example["slots"].items():
                at = example["text"].find(value)
                after = example["text"][at + len(value):] if at >= 0 else ""
                if any(after.startswith(p) and not after[len(p):][:1].isalnum() for p in particles):
                    marked.append(name)
            cache[index] = marked
        return cache[index]

    def _suffix_variants(self, subject):
        """``가람 구슬`` <-> ``가람이 구슬``: the leading name with and without the declared suffix."""
        from hangul import batchim
        suffix, words = self.name_suffix, subject.split()
        if not suffix or not words:
            return []
        first = words[0]
        if first.endswith(suffix) and len(first) > len(suffix) and batchim(first[:-len(suffix)]):
            return [" ".join([first[:-len(suffix)]] + words[1:])]
        if batchim(first):
            return [" ".join([first + suffix] + words[1:])]
        return []

    def _suffixed_names(self, words, tail_particle):
        """Words typed as ``base + suffix + particle`` whose ``base`` ends in a coda.

        The pack declares the suffix. Case particles do not stack, so the suffix
        in front of a particle is part of the name, not a second marker.
        """
        from hangul import batchim
        suffix, found = self.name_suffix, set()
        if not suffix:
            return found
        for word in words:
            for particle in tail_particle(word):
                base = word[:-len(particle)]
                if (base.endswith(suffix) and len(base) > len(suffix)
                        and batchim(base[:-len(suffix)])):
                    found.add(base)
        return found

    @staticmethod
    def _inherit_trailing(rows, previous, leading=()):
        """``[지연] count 2`` after ``[민수 사과] count 5`` -> ``[지연 사과] count 2``.

        A subject in ``leading`` is the thing counted, not its holder (topic
        continuity, 생략.topic_continuity): it takes the leading words instead,
        ``[배] count 3`` after ``[민수 사과] count 5`` -> ``[민수 배] count 3``."""
        rewritten, inherited = [], []
        for row in rows:
            subject = row[0]
            match = next((prior for prior in previous if prior[1] == row[1]
                          and isinstance(prior[0], str) and isinstance(subject, str)), None)
            if match is None:
                rewritten.append(row)
                continue
            words, before = subject.split(), match[0].split()
            # (a subject that already ends with the thing the clause before counted says it: 세영 메달
            # after 안 기사 메달 inherits nothing)
            if len(words) >= len(before) or words == before[:len(words)] or (len(words) > 1 and words[-1] == before[-1]):
                rewritten.append(row)
                continue
            if subject in leading:
                carried = before[:len(before) - len(words)]
                rewritten.append([" ".join(carried + words)] + list(row[1:]))
            else:
                carried = before[len(words):]
                rewritten.append([" ".join(words + carried)] + list(row[1:]))
            inherited.append({"subject": subject, "inherited": " ".join(carried),
                              "from": match[0]})
        return rewritten, inherited

    def _relative_clauses(self, text):
        """A relative clause that states its head's amount, said as its own clause.

        ``Moru, who has 2, gave Haru 1`` -> ``Moru has 2. Moru gave Haru 1``;
        ``구슬을 8개 가진 모루가 하루에게 1개를 줬어`` -> ``모루는 구슬을 8개 가지고
        있다. 모루가 하루에게 1개를 줬어``. The pack declares the relative
        pronouns that open a clause between commas after its head, and the
        adnominal forms (computed by its inflection grammar) that close a clause
        before its head, with what each reads as. Only a clause that holds an
        amount is split; anything else is left as typed.
        """
        from numeral_semantics import parse_numeral
        spec = (self.clause_grammar or {}).get("relative_clauses") or {}
        if not spec or not isinstance(text, str):
            return text
        numerals = self.data.get("numerals", {})
        ignore = bool(self.data.get("ignore_case"))
        fold = (lambda word: word.lower()) if ignore else (lambda word: word)

        def amount(words):
            return any(re.search(r"\d", word) or parse_numeral(fold(word.strip(",.")), numerals) is not None
                       for word in words)
        for pronoun in spec.get("pronouns", []):
            pattern = re.compile(r"(?P<head>[^\s,]+), %s (?P<body>[^,.;!?]+), (?P<rest>[^.;!?]+)"
                                 % re.escape(pronoun), re.IGNORECASE if ignore else 0)
            found = pattern.search(text)
            if found and amount(found.group("body").split()):
                head = found.group("head")
                text = (text[:found.start()] + "%s %s. %s %s" % (head, found.group("body"), head, found.group("rest"))
                        + text[found.end():])
        particles = sorted({p for p in self.case_particles} | {p for group in self.slot_particles for p in group},
                           key=len, reverse=True)
        for row in spec.get("adnominal", []):
            from hangul import inflect
            try:
                forms = {form["text"] for form in inflect(row["stem"], row["tense"], row["ending"],
                                                          self.inflection_grammar, kind=row["kind"])}
            except (KeyError, ValueError):
                continue
            words = text.split(" ")
            for at, word in enumerate(words[1:-1], 1):
                if word not in forms:
                    continue
                start = at
                while start > 0 and not words[start - 1].endswith(",") and not self._inflected_boundary(words[start - 1]):
                    start -= 1
                body, head = words[start:at], words[at + 1]
                particle = next((p for p in particles if head.endswith(p) and len(head) > len(p)
                                 and self._particle_form(head[:-len(p)], p) == p), None)
                if not body or particle is None or not amount(body):
                    continue
                name = head[:-len(particle)]
                said = [name + self._particle_form(name, row["topic"])] + body + [row["read_as"] + "."]
                text = " ".join(words[:start] + said + words[at + 1:])
                break
        return text

    def _gapped(self, literal, previous_text, previous_rows):
        """``Moru 2`` or ``2 pears`` after ``Haru has 5 marbles``: the conjunct said
        again with the words it shares with the clause before (생략.gapping).

        The clause before is [holder] [verb] [number] [thing]; its holder is the
        leading words of its subject as typed. The conjunct is [holder?] [number]
        [thing?] and nothing else; a part it leaves out is the clause before's.
        Returns the rebuilt clause, or None.
        """
        from numeral_semantics import parse_numeral
        if (self.ellipsis or {}).get("gapping") != "first_conjunct_verb":
            return None
        numerals = self.data.get("numerals", {})
        fold = (lambda word: word.lower()) if self.data.get("ignore_case") else (lambda word: word)

        def number_at(words):
            return next((i for i, word in enumerate(words)
                         if re.fullmatch(r"\d+", word) or parse_numeral(fold(word), numerals) is not None), None)
        words, before = literal.split(), previous_text.split()
        at, then = number_at(words), number_at(before)
        subject = next((row[0] for row in previous_rows if isinstance(row[0], str)), None)
        if at is None or then is None or subject is None or number_at(words[at + 1:]) is not None:
            return None
        holder = []
        for word in subject.split():
            if len(holder) < then and fold(before[len(holder)]) == fold(word):
                holder.append(word)
            else:
                break
        verb = before[len(holder):then]
        # The conjunct names a holder of at most as many words as the clause
        # before did, and no word of the shared verb: it is a remnant, not a clause.
        if not holder or not verb or len(words[:at]) > len(holder) or any(
                fold(word) in {fold(v) for v in verb} for word in words):
            return None
        return " ".join((words[:at] or before[:len(holder)]) + verb + [words[at]]
                        + (words[at + 1:] or before[then + 1:]))

    def _counted_subjects(self, evidence_text, rows):
        """The subjects this clause marks as the thing counted, not its holder: a
        one-word subject typed with a particle of 생략.topic_continuity.item_particles
        (``배가 세 개``), where the holder would take a topic particle."""
        spec = (self.ellipsis or {}).get("topic_continuity") or {}
        particles = sorted(spec.get("item_particles") or [], key=len, reverse=True)
        if not particles:
            return set()
        typed = evidence_text.split()
        out = set()
        for row in rows:
            subject = row[0] if isinstance(row[0], str) else ""
            if len(subject.split()) != 1:
                continue
            if any(word == subject + particle or word == subject + self._particle_form(subject, particle)
                   for word in typed for particle in particles):
                out.add(subject)
        return out

    @staticmethod
    def _names_hold(meaning, outside, leading=()):
        """A name holds a word declared outside names (``leading``: words outside names except as a
        name's first word -- the back hall, but not figs back)."""
        if not outside:
            return False
        rows = asserted(meaning) or [joined(q["triple"]) for q in meaning.get("query", [])
                                     if isinstance(q, dict) and isinstance(q.get("triple"), list)]
        return any(isinstance(value, str) and any(word.lower() in outside and not (i == 0 and word.lower() in leading)
                                                  for i, word in enumerate(value.split()))
                   for row in rows for value in (row[0], row[2]))

    def _names_hold_adnominal(self, meaning):
        spec = (self.holder_forms or {}).get("adnominal_past") or {}
        tails, coda = spec.get("tails") or [], spec.get("after_coda")
        if not tails or not coda:
            return False
        from hangul import batchim
        rows = asserted(meaning) or [joined(q["triple"]) for q in meaning.get("query", [])
                                     if isinstance(q, dict) and isinstance(q.get("triple"), list)]
        values = [value for row in rows for value in (row[0], row[2])]
        values += [meaning.get("scope")] + list(meaning.get("places") or [])
        for value in values:
            if True:
                for word in str(value).split() if isinstance(value, str) else []:
                    for tail in tails:
                        stem = word[:-len(tail)]
                        if word.endswith(tail) and stem and batchim(stem) == coda:
                            return True
        return False

    @staticmethod
    def _swallows_marked_word(meaning, tail_particle):
        values = []

        def walk(value):
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
        walk(meaning)
        # No word of a value may carry a case particle: not an inner word
        # (``민수는 사과``) and not the last one either (``표를`` read as the
        # item while the particle it carries was meant for the counter).
        return any(tail_particle(word) for value in values for word in value.split())

    def _is_verb_form(self, word):
        """A declared verb realized with an ending (`있었는데`). A particle never attaches to it."""
        node = self._inflection_trie
        for char in reversed(word):
            node = node.get(char)
            if node is None:
                return False
        return bool(node.get(None))

    def _particle_form(self, stem, particle):
        """The form of ``particle`` the pack's mate table selects after ``stem``."""
        from hangul import batchim
        mates = self.particle_mates.get(particle)
        if not mates or len(mates) != 2:
            return particle
        coda = batchim(stem)
        if coda is None:
            return particle
        closed, open_ = mates
        exception = self.particle_exceptions.get(closed, {})
        if coda and coda in exception.get("받침예외", []):
            return exception.get("쓸것", open_)
        return closed if coda else open_

    def render_changes(self, changes):
        """State changes in the pack's words: ``민수 사과 5개 → 3개``.

        Only changes with a declared shape are said; an undeclared operation
        or predicate is left out rather than printed as an internal name.
        """
        shapes = self.data.get("change_render", {})
        spoken = []
        for change in changes:
            shape = shapes.get(change.get("operation"))
            if isinstance(shape, dict):
                shape = shape.get(change.get("predicate"))
            if not isinstance(shape, str):
                continue
            spoken.append(shape.format(**{"대상": change.get("subject", ""),
                                          "전": change.get("before", ""),
                                          "후": change.get("after", "")}))
        return self.data.get("change_join", ", ").join(spoken)

    def repair_reports(self, text):
        """Reports already computed for clauses of ``text`` (no new search)."""
        return [copy.deepcopy(result[2]) for literal, result in self._repair_cache.items()
                if result[2] is not None and literal in text]

    def _declared_endings(self):
        """A bare declared stem -> the canonical forms its examples declare."""
        if self._ending_table is None:
            table = {}
            for example in self.data["examples"]:
                annotation = example.get("inflection")
                if not annotation or not self.inflection_grammar:
                    continue
                try:
                    forms = self._inflected_forms(annotation["stem"], annotation["tense"],
                                                  annotation["ending"], annotation["kind"])
                except ValueError:
                    continue
                for form in forms:
                    if form != annotation["stem"]:
                        table.setdefault(annotation["stem"], [])
                        if form not in table[annotation["stem"]]:
                            table[annotation["stem"]].append(form)
            self._ending_table = table
        return self._ending_table

    def render_repair(self, report, replies):
        """The pack's words for a repair report. Nothing here is language text."""
        names = self.repair.get("names", {})
        steps = []
        for step in report.get("operations", []):
            template = names.get(step["op"], step["op"])
            steps.append(template.format(**{"말": step.get("word", ""), "조사": step.get("particle", ""),
                                            "곳": step.get("to", "")}))
        joined = self.repair.get("join", ", ").join(steps)
        key = {"repaired": "repaired", "ambiguous": "repair_ambiguous",
               "over_bound": "repair_over_bound", "unplaced": "repair_unplaced",
               "protected": "repair_protected"}[report["status"]]
        return replies[key].format(**{"규칙": report.get("rule") or "", "수선": joined,
                                      "지킴": ", ".join('"%s"' % row["word"] for row in report.get("changed", [])),
                                      "읽음": report.get("reading", ""), "원문": report["source"],
                                      "비용": report.get("cost", ""), "한도": report["bound"],
                                      "목록": ", ".join('"%s"' % r for r in report.get("readings", []))})

    def _inflected_forms(self, stem, tense, ending, kind):
        from hangul import inflect
        return [form["text"] for form in inflect(stem, tense, ending,
                                                  self.inflection_grammar, kind=kind)]

    @staticmethod
    def compile(example, numerals=None, slot_particles=(), *, ignore_case=False, counters=None, pointers=()):
        text, slots = example["text"], example["slots"]
        units = [unit for unit in (counters or {}).get("units", []) if unit]
        askers = [word for word in (counters or {}).get("askers", []) if word]
        attach = sorted((p for p in (counters or {}).get("attach", []) if p), key=len, reverse=True)
        unit_class = "(?:%s)" % "|".join(re.escape(u) for u in sorted(units, key=len, reverse=True)) if units else ""

        def counted_rest(rest):
            """Regex for what follows the canonical counter.

            The example's own particle reads as any form of its declared group
            (``개를`` / ``권을``); where the example has none, none is read -- a
            particle there is left to repair. Where the example goes straight on
            to a copula ending, the copula ``이`` that a consonant-final counter
            takes is optional (``개야`` / ``권이야``).
            """
            for particle in attach:
                if rest.startswith(particle) and not rest[len(particle):][:1].isalnum():
                    group = next((g for g in slot_particles if particle in g), [particle])
                    return ("(?:%s)" % "|".join(re.escape(p) for p in sorted(group, key=len, reverse=True))
                            + re.escape(rest[len(particle):]))
            if not rest or rest[0].isspace():
                return re.escape(rest)
            copula = attach[0] if attach else ""
            return ("(?:%s)?" % re.escape(copula) if copula else "") + re.escape(rest)

        def after_number(literal):
            """The literal right after a number: any declared counter reads like the first."""
            if units and literal.startswith(units[0]):
                return [unit_class + counted_rest(literal[len(units[0]):])]
            return None

        def with_askers(pieces):
            """``몇 개`` inside a fixed literal reads any declared counter too."""
            if not (units and askers):
                return pieces
            out = []
            for piece in pieces:
                for asker in askers:
                    marker = re.escape(asker + " " + units[0])
                    if marker in piece:
                        head, _sep, tail = piece.partition(marker)
                        unescaped = re.sub(r"\\(.)", r"\1", tail)
                        piece = head + re.escape(asker) + r"\s*" + unit_class + counted_rest(unescaped)
                out.append(piece)
            return out
        slot_forms = example.get("slot_forms", {})
        if (not isinstance(slot_forms, dict)
                or any(name not in slots or not isinstance(forms, list) or not forms
                       or not all(isinstance(form, str) and form for form in forms)
                       for name, forms in slot_forms.items())):
            raise ValueError("invalid_slot_forms")

        def after_slot(literal):
            """자리를 잡은 조사는 글자가 아니라 그 자리에 올 수 있는 무리다.

            예문이 `구슬은` 이라고 적었다고 `구슬이` 를 못 읽으면, 조사 하나마다
            예문을 새로 써야 한다. 무리 안에서만 바꾼다 — 자리가 바뀌면 뜻이 바뀐다.

            무리를 정규식 하나의 `(?:은|는|이|가)` 로 적으면 안 된다. 그러면 한
            문장에서 **첫 일치 하나만** 남아 `작은 지도는 큰 서랍에 있었다` 가
            `작` + `지도는 큰 서랍` 으로 굳는다. 조사인지 꾸밈말의 끝인지는 뒤가
            띄어져 있다는 것만으로 못 가른다. 그러니 무리마다 **따로 된 틀**을
            내주고, 어느 자름이 옳은지는 개체 증거가 정하게 한다.
            """
            group = particle_group(literal)
            if group is None:
                return [re.escape(literal)]
            for particle in group:
                rest = literal[len(particle):]
                if literal.startswith(particle) and not rest[:1].isalnum():
                    return [re.escape(alternative) + re.escape(rest) for alternative in group]
            return [re.escape(literal)]

        def particle_group(literal):
            """이 자리가 조사로 시작하면 그 무리를 준다."""
            for group in slot_particles:
                for particle in group:
                    rest = literal[len(particle):]
                    # 조사는 앞말에 붙고 뒤는 띄운다. 뒤에 글자가 이어지면 조사가
                    # 아니다 — `이다` 의 `이` 는 잡음씨지 주격 조사가 아니며, 그것을
                    # 조사로 읽으면 `모래를 넘지 않` 이 이름으로 잡힌다.
                    if literal.startswith(particle) and not rest[:1].isalnum():
                        return group
            return None

        def branch(variants, chunks):
            return [head + tail for head in variants for tail in chunks]

        spans = []
        for name, literal in slots.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or text.count(literal) != 1:
                raise ValueError("ambiguous_slot_annotation")
            start = text.index(literal)
            spans.append((start, start + len(literal), name))
        ordered = sorted(spans)
        spans_by_start = {end: nxt for (_s, end, _n), (nxt, _e, _n2)
                          in zip(ordered, ordered[1:])}
        variants, offset = [""], 0
        numeric_before = False
        for start, end, name in ordered:
            if start < offset:
                raise ValueError("overlapping_slots")
            # Slot boundaries come from the annotated surrounding language,
            # not from a one-word restriction. Preserve multiword entity names.
            # Numeric examples still constrain their slot to decimal digits.
            slot_pattern = r"[^.!?,\n]+"
            if name in slot_forms:
                # 하나의 뜻 자리는 언어 팩이 선언한 여러 표면형으로 나타날 수
                # 있다. 이 갈래는 값 자체가 아니라 조사·연결어미처럼 **경계만**
                # 바꾸며, 정규식은 팩의 문자열을 이스케이프해서 만든다. 그러므로
                # 새 원인 연결 꼴을 읽으려고 문장별 분기를 코드에 늘리지 않는다.
                slot_pattern = "(?:%s)" % "|".join(
                    re.escape(form) for form in sorted(slot_forms[name], key=len, reverse=True))
            if name in example.get("wide_slots", []):
                # 절을 여럿 담는 자리. 쉼표로 이어진 뜻풀이 몸통이 여기 들어간다.
                slot_pattern = r"[^.!?\n]+"
            if name in example.get("word_slots", []):
                # 이 자리는 한 낱말이다. 꼬리가 슬롯인 틀이 아무 문장이나 삼키는 것을
                # 막는다 — `...에게 (?P<verb>...)다` 가 `사과를 준다` 를 먹지 않게.
                slot_pattern = r"[^\s.!?,\n]+"
                # A declared pointer phrase ("that person") stands for one name.
                phrases = sorted((p for p in pointers if " " in p), key=len, reverse=True)
                if phrases:
                    slot_pattern = "(?:%s|%s)" % ("|".join(re.escape(p) for p in phrases), slot_pattern)
            if slots[name].isdecimal():
                # A number slot holds digits or the pack's own numeral words, one
                # after another (``스물한``, ``twenty one``). Letters that merely
                # occur in numeral words (``one tin of``) are not a numeral.
                words = sorted({word for table in (numerals or {}).values() for word in table},
                               key=len, reverse=True)
                unit = "(?:%s)" % "|".join(re.escape(word) for word in words) if words else ""
                # Atomic: once a numeral is read it is not re-split on failure, so a
                # sentence that fails the template costs one pass, not every split.
                slot_pattern = (r"(?>\d+|%s+(?:[\s-]+%s+)*)" % (unit, unit)) if words else r"\d+"
            literal = text[offset:start]
            pieces = (after_number(literal) if numeric_before else None) or (
                after_slot(literal) if offset else [re.escape(literal)])
            variants = branch(variants, with_askers(pieces))
            # 뒤따르는 조사가 이름 안에도 있을 수 있다. `작은 공책은 큰 서랍에` 의
            # `은` 은 꾸밈말에도 조사에도 있다. 짧게 잡기와 길게 잡기를 **둘 다**
            # 내주고, 어느 자름이 옳은지는 개체 증거가 고른다. 한쪽만 내주면
            # `작` 이 이름이 된다. 세 번 나오면 가운데는 아직 못 본다.
            following = text[end:spans_by_start.get(end, len(text))]
            # 표면형 후보는 경계 자체다. 비어 있으면 다음 넓은 자리가 그 연결말을
            # 삼켜 원인·결과가 갈라지므로 선택형으로 만들지 않는다.
            reach = ([""] if name in slot_forms else
                     ["?", ""] if (not slots[name].isdecimal()
                                    and particle_group(following) is not None) else ["?"])
            variants = branch(variants, [f"(?P<{name}>{slot_pattern}{greedy})" for greedy in reach])
            if slots[name].isdecimal():
                variants = branch(variants, [r"\s*"])
            numeric_before = slots[name].isdecimal()
            offset = end
        tail = text[offset:]
        pieces = (after_number(tail) if numeric_before else None) or (
            after_slot(tail) if offset else [re.escape(tail)])
        variants = branch(variants, with_askers(pieces))
        # 대소문자를 가르지 않는 글자를 쓰는 언어는 팩이 그렇게 선언한다.
        flags = re.IGNORECASE if ignore_case else 0
        return [re.compile(variant, flags) for variant in variants], example["meaning"]

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
        compiled = self.compile(correction, self.data.get("numerals", {}), self.slot_particles,
                                ignore_case=bool(self.data.get("ignore_case")), counters=self.counters,
                                pointers=self.pointers)
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
                for pattern in compiled[0]:
                    match = pattern.fullmatch(literal)
                    if match and substitute(compiled[1], match.groupdict()) != substitute(prior["meaning"], prior["slots"]):
                        raise ValueError("correction_conflicts_with_previous_example")
        for patterns, meaning in self.templates:
            for pattern in patterns:
                match = pattern.fullmatch(correction["text"])
                if match and substitute(meaning, match.groupdict()) != substitute(correction["meaning"], correction["slots"]):
                    raise ValueError("correction_conflicts_with_previous_template")
        self.data["examples"].append(copy.deepcopy(correction))
        self.templates.append(compiled)
        self.induced_frames.clear()
        self.__dict__.pop("_조각틀", None)
        self._rebuild_inflections()
        self._repair_cache.clear()
        self._ending_table = None
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
                json.dump({**self.data, "examples": [e for e in self.data["examples"] if not e.get("derived")]},
                          handle, ensure_ascii=False, indent=2)
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

    def _inference_rules(self, facts):
        """Allow a host to select a validated rule view for this exact fact set.

        A selector is optional and receives the ordinary rule list.  It is
        deliberately consulted only at closure time; parsing, state replay,
        and proof-ledger reconstruction remain based on the original pack.
        """
        selector = getattr(self, "rule_selector", None)
        if selector is None:
            return self.data["rules"]
        selected = selector(facts, self.data["rules"])
        if not isinstance(selected, list):
            raise ValueError("invalid_rule_selector")
        return selected

    def _closure(self, facts):
        """Use an optional exact-input closure snapshot without caching answers."""
        from graph_inference import closure
        rules = self._inference_rules(facts)
        selector = getattr(self, "closure_selector", None)
        known = selector(facts, rules) if selector is not None else None
        if known is not None:
            return known
        recorder = getattr(self, "closure_recorder", None)
        metrics = {} if recorder is not None else None
        known = closure(facts, rules, metrics=metrics)
        if recorder is not None:
            recorder(facts, rules, known, metrics)
        return known

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
            from graph_inference import bind, current_facts, proof
            facts, _ = current_facts(parsed["facts"], self.data.get("mutable_predicates", []),
                                     self.data.get("numeric_updates", {}))
            known = self._closure(facts)
            candidates = [{"fact": list(fact), "query_index": index, "proof": proof(known, fact)}
                          for index, query in enumerate(parsed["query"]) for fact in known
                          if bind(query["triple"], fact, {}) is not None]
            return {"stage": "graph_inference", "reason": "nonunique_proof" if candidates else "missing_proof",
                    "input": text, "answer": None, "facts": parsed["facts"], "query": parsed["query"],
                    "candidates": candidates}
        return {"stage": "answered", "input": text, **result}

    def _clause_meanings(self, literal, *, derivations=None, matched=None, guard_names=True, exclude=()):
        """The clause's readings of the best rank. ``exclude``: meaning keys already returned (by
        ``readings``): they are left out, so the readings of the next rank are found (goal G5.4 B)."""
        from numeral_semantics import parse_numeral
        # Where a declared holder form rewrites the clause (제 동기 서준 -> 서준, 예린 씨 -> 예린), the
        # typed words are that form: a reading that keeps them inside a name is not taken.
        held, holder_note = self._holder_forms(literal)
        if holder_note is not None and set(holder_note["forms"]) <= {"numeral_article"}:
            holder_note = None          # an article dropped before a numeral names no holder
        for said in ([held] if holder_note is not None else []) + [literal]:
            chained = self._quantity_chain_meaning(said)
            if chained is not None and json.dumps(chained, sort_keys=True, ensure_ascii=False) not in exclude:
                return {json.dumps(chained, sort_keys=True, ensure_ascii=False): chained}
            counted = self._count_question_meaning(said) or self._why_count_meaning(said)
            if counted is not None and json.dumps(counted, sort_keys=True, ensure_ascii=False) not in exclude:
                return {json.dumps(counted, sort_keys=True, ensure_ascii=False): counted}
            compared = self._comparison_meaning(said) or self._same_meaning(said)
            if compared is not None and json.dumps(compared, sort_keys=True, ensure_ascii=False) not in exclude:
                return {json.dumps(compared, sort_keys=True, ensure_ascii=False): compared}
        meanings, best_rank = {}, None
        for candidate, normalization in self._clause_candidates(literal):
            if holder_note is not None and not any(
                    note.get("id") == "declared-holder-forms-v1" for note in (normalization or {}).get("variants", [])):
                continue
            # Words a same-frame or phrase variant wrote in place of the typed
            # ones. They stand for the example's own words; inside a slot they
            # would put a word nobody typed into an entity or a quoted effect
            # (``밥을 먹지 않은`` read back as another verb).
            written = {word for note in (normalization or {}).get("variants", [])
                       if note.get("id") in ("declared-same-frame-v1", "declared-phrase-variant-v1")
                       for word in str(note.get("written", "")).split()}
            for index, ((patterns, meaning), example) in enumerate(zip(self.templates, self.data["examples"])):
                if normalization and "example_index" in normalization and index != normalization["example_index"]:
                    continue
                if (normalization and "example_index" not in normalization
                        and not normalization.get("words_only")
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
                if (normalization and not declared and not normalization.get("words_only")
                        and "query" in meaning):
                    continue
                # Rewriting a tail that is itself a slot would edit the entity,
                # whatever produced the normalization.
                if (normalization and not normalization.get("words_only")
                        and any(example["text"].endswith(value) for value in example["slots"].values())):
                    continue
                for pattern in patterns:
                    match = pattern.fullmatch(candidate)
                    if not match:
                        continue
                    slots = match.groupdict()
                    # (A number slot may hold a numeral a variant wrote: an onion = 1 onion.)
                    if written and any(word in written for name, value in slots.items()
                                       if isinstance(value, str) and not str(example["slots"].get(name, "")).isdecimal()
                                       for word in value.split()):
                        continue
                    # A name never ends in an object particle the example does not put after it
                    # (나는 전구를 is not a holder's thing; 전구를 열네 개 reads 전구 with its particle).
                    # (Nor in a holder's particle: 지연은 alone is a holder whose thing was left out. A particle
                    # that may end a noun, the pack's floating_noun_endings, is not taken for one.)
                    objects = set((self.object_fronting or {}).get("object_particles") or [])
                    objects |= set((self.possessor or {}).get("particles") or [])
                    objects -= set((self.object_fronting or {}).get("floating_noun_endings") or [])
                    shortest = max(2, int((self.possessor or {}).get("min_length", 1)))
                    marked = self._particle_marked_slots(index, example)
                    if objects and any(isinstance(slots.get(name), str) and name not in marked
                                       and not str(example["slots"].get(name, "")).isdecimal()
                                       # (a name slot: one word in the example, not a slot for clauses)
                                       and len(str(example["slots"].get(name, "")).split()) == 1
                                       and name not in example.get("wide_slots", [])
                                       and name not in (example.get("slot_forms") or {})
                                       and slots[name].split()
                                       and any(slots[name].split()[-1].endswith(o)
                                               and len(slots[name].split()[-1]) - len(o) >= shortest
                                               for o in objects)
                                       for name in example["slots"]):
                        continue
                    # An object-marked word never stands inside a name (숫자를 in 숫자를 모르지): the name
                    # swallowed a clause.
                    object_only = set((self.object_fronting or {}).get("object_particles") or [])
                    if object_only and any(isinstance(slots.get(name), str) and name not in marked
                                           and len(str(example["slots"].get(name, "")).split()) == 1
                                           and any(w.endswith(o) and len(w) - len(o) >= shortest
                                                   for w in slots[name].split()[:-1] for o in object_only)
                                           for name in example["slots"]):
                        continue
                    # A particle attaches to the word before it, so a value the
                    # example follows with a case particle cannot end in a space:
                    # a cut before a name that starts with 이 reads that 이 as a particle.
                    if any(isinstance(slots.get(name), str) and slots[name] != slots[name].rstrip()
                           for name in self._particle_marked_slots(index, example)):
                        continue
                    # Do not absorb an unrecognized preceding clause into an entity
                    # slot just because the trailing predicate is understood.
                    # 고정된 인과 연결말 앞의 원인 자리는 서술어로 끝날 수 있다.
                    # 그 허용은 예문 일반화가 아니라 언어 팩의 명시 선언일 때만
                    # 열며, 나머지 넓은 자리가 못 읽은 절을 삼키는 일은 막는다.
                    if any(self._inflected_boundary(word) for name, value in slots.items()
                           if name not in example.get("allow_inflected_slots", [])
                           for word in value.split()):
                        continue
                    for name, annotated in example["slots"].items():
                        if annotated.isdecimal():
                            # A pack that reads its letters without case reads
                            # its numeral words that way too ("Two marbles ...").
                            typed = slots[name].lower() if self.data.get("ignore_case") else slots[name]
                            slots[name] = parse_numeral(typed, self.data.get("numerals", {}))
                    if any(value is None for value in slots.values()):
                        continue
                    slots = self._number_agreement(slots, example)
                    # Count the observed fixed surface, not letters manufactured by
                    # expansion to the canonical spelling. Different canonical
                    # forms of the same spoken ending must not win by their length.
                    # Measure the text this template actually pinned down, not the
                    # length of its regex source — a slot particle written as a
                    # class of particles is still one matched letter.
                    specificity = len(candidate) - sum(len(match.group(name) or "")
                                                       for name in example["slots"])
                    if normalization and "example_index" in normalization:
                        specificity += len(literal) - len(candidate)
                    if normalization and any(note.get("id") == "declared-floating-quantifier-v1"
                                             for note in normalization.get("variants", [])):
                        # A floated quantifier is read only where the words as
                        # typed are not: it ranks below every other reading.
                        specificity -= len(literal) + 1
                    elif normalization and normalization.get("variants"):
                        # A declared phrase read as declared is recognized text,
                        # not text a slot happened to swallow.
                        specificity += max(1, len(literal) - len(candidate))
                    # 조사가 있는 행위자 자리는 문장 전체를 삼키는 넓은 이름보다
                    # 첫 조사 경계의 이름을 우선할 수 있다. 어느 자리를 그렇게
                    # 고를지는 예문이 선언하며, 기본 틀·낱말·이름에는 적용하지
                    # 않는다. 따라서 공백이 든 이름도 살리고 `준호는 우산이`처럼
                    # 원인절까지 주어로 잡는 경쟁 읽기만 제거한다.
                    shortest = example.get("prefer_shortest_slots", [])
                    # At equal cost a sentence an example declares as written wins
                    # over a reading derived from another example (a negated
                    # sentence the pack declares whole, F2-2 B).
                    rank = (specificity, normalization is None,
                            -sum(len(match.group(name) or "") for name in shortest))
                    # A name never holds a negation or a scope word: ``Ada figs not``,
                    # ``누리 모두 단추`` read a polarity or a range as part of a thing.
                    grounded_names = self._join_actor_target(substitute(meaning, slots))
                    in_names = (self.repair or {}).get("protected", {}).get("negation_in_names", [])
                    # (The repair search asks without this guard and checks every
                    # protected word itself, so it can say what a repair would change.)
                    if guard_names and any(row["kind"] == "scope" or (row["kind"] == "negation" and any(
                            re.search(pattern, row["word"].lower()) for pattern in in_names))
                           for row in self._protected_in_names(grounded_names)):
                        continue
                    # A name never holds a word the pack declares outside names
                    # (English prepositions): it swallowed a phrase the example lacks.
                    if self.outside_names and self._names_hold(grounded_names, self.outside_names,
                                                               self.outside_leading):
                        continue
                    # Nor a verb in a relative clause's past form (잃어버렸던 볼펜: the pack's adnominal
                    # tails after a past stem, 이름밖꼴).
                    if self._names_hold_adnominal(grounded_names):
                        continue
                    if exclude and json.dumps(self._grounded(meaning, slots, normalization, example), sort_keys=True,
                                              ensure_ascii=False) in exclude:
                        continue
                    if best_rank is None or rank > best_rank:
                        meanings, best_rank = {}, rank
                        if derivations is not None:
                            derivations.clear()
                        if matched is not None:
                            matched.clear()
                    if rank == best_rank:
                        grounded = self._grounded(meaning, slots, normalization, example)
                        key = json.dumps(grounded, sort_keys=True, ensure_ascii=False)
                        # Exact evidence is tried first; do not replace its proof
                        # with a later equivalent normalization.
                        if key not in meanings and derivations is not None:
                            derivations[key] = ({"rule": normalization["id"], "canonical": candidate}
                                                if normalization else None)
                            if normalization and "operations" in normalization:
                                derivations[key].update({k: normalization[k] for k in
                                                         ("stem", "tense", "ending", "operations")})
                        if matched is not None:
                            matched.setdefault(key, index)
                        meanings[key] = grounded
        return meanings

    def _grounded(self, meaning, slots, normalization, example):
        """An example's meaning with its slots filled: the reading a clause gives."""
        grounded = self._join_actor_target(substitute(meaning, slots))
        if normalization and normalization.get("polarity") is False:
            grounded = {**grounded, "polarity": False}
        if isinstance(example.get("place"), list):
            # the slots the example declares places (a holder that is a place: W3-1)
            grounded = {**grounded, "places": [self.canonical_name(str(slots[name]).strip())
                                               for name in example["place"] if slots.get(name)]}
        return grounded

    def _join_actor_target(self, meaning):
        """주격 행위자와 수량 대상은 역할을 보존한 채 한 상태 대상을 가리킨다.

        사례 틀의 넓은 ``item`` 자리가 ``민수가 구슬``을 통째로 잡더라도,
        언어팩이 선언한 주격 조사와 수량 변화 관계가 함께 있을 때만
        ``민수 구슬``로 정규화한다. 다른 관계나 조사 없는 이름은 건드리지
        않는다. 따라서 문장별 이름·동사 예외가 아니다.
        """
        relations = set(self.actor_targets.get("relations", []))
        if not relations:
            return meaning
        joiner = self.actor_targets.get("joiner", " ")
        particles = next((group for group in self.slot_particles
                          if self.doer_particle in group), [self.doer_particle])

        def split_target(target):
            if not isinstance(target, str):
                # An [owner, item] pair already keeps its roles apart; reading
                # its printed form would split on quote marks and particles.
                return target, None
            words = target.split()
            for index, word in enumerate(words[:-1]):
                particle = next((value for value in particles
                                 if value and word.endswith(value) and len(word) > len(value)), None)
                if particle is None:
                    continue
                actor_words = words[:index] + [word[:-len(particle)]]
                item_words = words[index + 1:]
                actor, item = " ".join(actor_words), " ".join(item_words)
                if actor and item:
                    return joiner.join((actor, item)), {"actor": actor, "item": item}
            return target, None

        out = copy.deepcopy(meaning)
        rows = out.get("triples") or ([out["triple"]] if "triple" in out else [])
        roles = []
        changed = False
        for row in rows:
            if not isinstance(row, list) or len(row) != 3 or row[1] not in relations:
                roles.append(None)
                continue
            target, bound = split_target(row[0])
            if bound is None:
                roles.append(None)
                continue
            row[0] = target
            roles.append(bound)
            changed = True
        if changed:
            out["role_bindings"] = roles
        return out

    def _owner_items(self, readings, literal, derivations, matched):
        """``[하루는 구슬] count 18`` -> ``[하루 구슬] count 18`` in a direct reading.

        A wide name slot of a stated count swallowed the owner together with
        its particle. The pack declares which relation and which particles
        mark an owner. Repaired readings never get here: repair already moves
        such a particle itself and rejects a name that swallows one.
        """
        relations = set((self.possessor or {}).get("relations", []))
        particles = (self.possessor or {}).get("particles", [])
        shortest = int((self.possessor or {}).get("min_length", 1))
        if not readings or not relations or not particles:
            return readings

        def split(name):
            words = name.split()
            for index, word in enumerate(words[:-1]):
                particle = next((p for p in particles if word.endswith(p) and len(word) > len(p)), None)
                owner = words[:index] + [word[:-len(particle)]] if particle is not None else []
                # The speaker's key (나) is an owner however short it is.
                if particle is not None and (len("".join(owner)) >= shortest
                                             or owner == [self.speaker_placeholder]):
                    return " ".join(owner + words[index + 1:])
            return name

        out = {}
        for key, meaning in readings.items():
            # A question about an owned thing keys it by its owner too.
            rows = meaning.get("triples") or ([meaning["triple"]] if "triple" in meaning else []) or [
                q["triple"] for q in meaning.get("query") or [] if isinstance(q, dict) and isinstance(q.get("triple"), list)]
            changed = copy.deepcopy(meaning)
            new_rows = changed.get("triples") or ([changed["triple"]] if "triple" in changed else []) or [
                q["triple"] for q in changed.get("query") or [] if isinstance(q, dict) and isinstance(q.get("triple"), list)]
            touched = False
            for row, new in zip(rows, new_rows):
                if isinstance(row, list) and len(row) == 3 and row[1] in relations and isinstance(row[0], str):
                    joined_name = split(row[0])
                    if joined_name != row[0]:
                        new[0] = joined_name
                        touched = True
            if not touched:
                out[key] = meaning
                continue
            new_key = json.dumps(changed, sort_keys=True, ensure_ascii=False)
            out[new_key] = changed
            self.__dict__.setdefault("_owner_origin", {})[new_key] = key
            if key in derivations.get(literal, {}):
                derivations[literal][new_key] = derivations[literal][key]
            if key in matched.get(literal, {}):
                matched[literal][new_key] = matched[literal][key]
        return out

    def _why_count_meaning(self, literal):
        """``다올은 왜 단추가 그만큼 있는 거야`` -> ``{"why_count": {"subject": [다올, 단추]}}``.

        Read by its parts from the pack's declaration (수량이유물음): a why word
        and an amount word, a first predicate word after the amount word that
        starts with a declared count predicate stem; every other word before the
        amount word is part of the name, its declared particle taken off.
        """
        spec = self.why_count or {}
        if not spec:
            return None
        words = self._particle_variant_words(literal)[0].split()
        amount = next((i for i, w in enumerate(words) if w in spec.get("amount", [])), None)
        why = [i for i, w in enumerate(words) if w in spec.get("why", [])]
        if amount is None or not why or amount + 1 >= len(words) or any(i > amount for i in why):
            return None
        stems = [row.get("stem") for row in (self.count_question or {}).get("predicates", []) if row.get("stem")]
        if not any(words[amount + 1].startswith(stem) for stem in stems):
            return None
        particles = sorted(set(self.case_particles) | {p for group in self.slot_particles for p in group},
                           key=len, reverse=True)
        drop = set((self.count_question or {}).get("time_words", []))
        name = []
        for index, word in enumerate(words[:amount]):
            if index in why or word in drop:
                continue
            particle = next((p for p in particles if word.endswith(p) and len(word) > len(p)), None)
            name.append(word[:-len(particle)] if particle else word)
        if not name:
            return None
        return {"query": [{"why_count": {"subject": name}}]}

    def _count_question_meaning(self, literal):
        """``가람이는 이제 구슬 몇 개야`` -> ``[가람 구슬] count ?n``.

        The question word and the counters come from the pack's counter
        declaration; the words that may stand around them (time words, head
        words, possession modifiers, copula forms, predicate stems) from its
        count-question declaration. Every other word is part of the name;
        a name word loses the particle the pack declares. Nothing is read
        when a part is missing or a word after the counter is undeclared.
        """
        spec = self.count_question or {}
        units = sorted((self.counters or {}).get("units", []), key=len, reverse=True)
        askers = (self.counters or {}).get("askers", [])
        if not spec or not units or not askers or not spec.get("render"):
            return None
        words = self._particle_variant_words(literal)[0].split()
        at = next((i for i, word in enumerate(words) if word in askers), None)
        if at is None or at + 1 >= len(words):
            return None
        counter_word = words[at + 1]
        unit = next((u for u in units if counter_word.startswith(u)), None)
        if unit is None:
            return None
        rest = counter_word[len(unit):]
        particles = sorted(set(self.case_particles) | {p for group in self.slot_particles for p in group},
                           key=len, reverse=True)
        if rest and rest not in particles and rest not in spec.get("copula", []):
            return None
        tail = words[at + 2:]
        # Words between the counter and the end may take any declared form
        # (가지고 있나요); the last one must be a question form the grammar
        # declares, so a question ending that is not declared is not read.
        if any(word not in self._count_predicate_forms() for word in tail[:-1]):
            return None
        if tail and tail[-1] not in self._count_predicate_forms(questions_only=True):
            return None
        drop = set(spec.get("time_words", [])) | set(spec.get("modifiers", []))
        heads = set(spec.get("head_words", []))
        name, total = [], False
        shortest = int((self.possessor or {}).get("min_length", 1))
        for index, word in enumerate(words[:at]):
            if (index == 0 and word in heads) or word in drop:
                continue
            if word in spec.get("total_words", []):
                total = True
                continue
            particle = next((p for p in particles if word.endswith(p) and len(word) > len(p)), None)
            # A name shorter than the declared owner length, counted with the
            # words before it, is a modifier (`작은 구슬`), not a name with its
            # particle; a declared pointer (`걔는`) keeps its particle off.
            stem = word[:-len(particle)] if particle else word
            # A delimiter may stand on a case particle (``다올에게는``, ``다올에게도``):
            # both come off. A delimiter alone is left to the name.
            stacked = spec.get("delimited_cases") or particles
            for delimiter in sorted(spec.get("delimiters", []), key=len, reverse=True):
                bare = word[:-len(delimiter)] if word.endswith(delimiter) else ""
                inner = next((p for p in sorted(stacked, key=len, reverse=True)
                              if bare.endswith(p) and len(bare) > len(p)
                              and p not in spec.get("delimiters", [])), None)
                if inner is not None and len(bare) - len(inner) >= shortest:
                    particle, stem = delimiter, bare[:-len(inner)]
                    break
            if (particle is not None and index < at - 1 and stem not in self.pointers
                    and len("".join(name) + stem) < shortest):
                particle, stem = None, word
            name.append(stem)
        # A declared group word ("두 사람", "둘") in a total names every holder.
        joined_name, group, pair = " ".join(name), False, False
        for phrase in sorted(spec.get("group_words", []), key=len, reverse=True):
            if joined_name == phrase or joined_name.startswith(phrase + " "):
                joined_name, group = joined_name[len(phrase):].strip(), True
                # a group word that names two (두 사람, 둘이) sums exactly two holders
                pair = phrase in spec.get("pair_words", [])
                break
        if total and not group:
            # ``A와 B는 구슬이 모두 몇 개야``: two holders joined by a declared
            # conjunctive particle (비교물음.between.joiners) are the members.
            joiners = sorted((self.comparison or {}).get("between", {}).get("joiners", []), key=len, reverse=True)
            first = next((w for i, w in enumerate(words[:at]) if w not in drop and not (i == 0 and w in heads)), "")
            joiner = next((j for j in joiners if first.endswith(j) and len(first) > len(j)), None)
            rest = " ".join(name[2:])
            # A group word after the two names repeats them (``A와 B 둘이``).
            for phrase in sorted(spec.get("group_words", []), key=len, reverse=True):
                if rest == phrase or rest.startswith(phrase + " "):
                    rest = rest[len(phrase):].strip()
                    break
            if joiner is not None and len(name) >= 3 and rest:
                # the second member may carry the joiner too (A랑 B랑 합쳐서)
                second = name[1]
                tail = next((j for j in joiners if second.endswith(j) and len(second) > len(j)), None)
                second = second[:-len(tail)] if tail else second
                return {"query": [{"total": {"members": [first[:-len(joiner)], second], "item": rest},
                                   "render": list(spec["render"])}]}
        if total or group:
            if not (total and group):
                return None
            return {"query": [{"total": {"members": "two" if pair else "all", "item": joined_name or None},
                               "render": list(spec["render"])}]}
        if not name:
            return None
        return {"query": [{"triple": [" ".join(name), "count", "?n"], "render": list(spec["render"])}]}

    def _comparison_meaning(self, literal):
        """``누가 구슬이 더 많아`` -> more(item); ``A와 B 중 …`` names both; ``A야 B야`` -> choices."""
        spec = self.comparison or {}
        if not spec:
            return None
        particles = sorted(set(self.case_particles) | {p for group in self.slot_particles for p in group},
                           key=len, reverse=True)

        def bare(word):
            particle = next((p for p in particles if word.endswith(p) and len(word) > len(p)), None)
            return word[:-len(particle)] if particle else word
        words = self._particle_variant_words(literal)[0].replace(",", " ").split()
        tails = sorted(spec.get("choice_tails", []), key=len, reverse=True)
        if len(words) == 2 and not any(w in spec.get("who", []) for w in words):
            names = []
            for word in words:
                tail = next((t for t in tails if word.endswith(t) and len(word) > len(t)), None)
                if tail is None:
                    break
                names.append(word[:-len(tail)])
            if len(names) == 2:
                return {"choices": names}
        who = next((i for i, w in enumerate(words) if w in spec.get("who", [])), None)
        more = next((i for i, w in enumerate(words) if w in spec.get("more", [])), None)
        adverbial = spec.get("adverbial") or {}
        order = None
        if (who is not None and more is not None and who < more and more + 1 < len(words) - 1
                and words[more + 1] in (adverbial.get("adverbs") or {})
                and words[-1] in self._count_predicate_forms(questions_only=True)
                and all(w in self._count_predicate_forms() for w in words[more + 2:-1])):
            # 누가 접시를 더 많이 가지고 있어요: the adverb of amount before a count predicate
            order = adverbial["adverbs"][words[more + 1]]
            words = words[:more + 1] + [words[-1]]
        if who is None or more is None or not who < more or more + 1 != len(words) - 1:
            return None
        if order is None and words[-1] not in self._comparison_forms():
            return None
        item = [bare(w) for w in words[who + 1:more] if w not in spec.get("time_words", [])]
        before = [w for w in words[:who] if w not in spec.get("time_words", [])]
        request = {"item": " ".join(item) or None}
        kind = "fewer" if (order or self._comparison_forms()[words[-1]]) == "less" else "more"
        if before:
            among = spec.get("between", {}).get("among", [])
            joiners = sorted(spec.get("between", {}).get("joiners", []), key=len, reverse=True)
            if len(before) != 3 or before[-1] not in among:
                return None
            joiner = next((j for j in joiners if before[0].endswith(j) and len(before[0]) > len(j)), None)
            if joiner is None:
                return None
            request.update(a=before[0][:-len(joiner)], b=before[1])
        return {"query": [{kind: request}]}

    def _comparison_forms(self, rows=None):
        """The question forms of the declared comparison predicates: form -> its
        order (``more`` unless the row declares ``less``)."""
        cached = rows is None and getattr(self, "_comparison_cache", None) is not None
        if cached:
            return self._comparison_cache
        from hangul import inflect
        grammar = self.inflection_grammar or {}
        forms = {}
        for row in (self.comparison or {}).get("predicates", []) if rows is None else rows:
            for tense in grammar.get("tenses", {}):
                for ending in grammar.get("question_endings", []):
                    try:
                        for f in inflect(row["stem"], tense, ending, grammar, kind=row.get("kind", "regular")):
                            forms.setdefault(f["text"], row.get("order", "more"))
                    except (ValueError, KeyError):
                        continue
        if rows is None:
            self._comparison_cache = forms
        return forms

    def _same_meaning(self, literal):
        """``A와 B는 구슬이 같아`` -> same(a, b, item): whether two holders have as many.

        The pack declares the predicate (비교물음.same.predicates, its question
        forms computed), the words that may stand before it (intensifiers) and the
        nouns that name the number itself (number_nouns, left out of the item).
        """
        spec = (self.comparison or {}).get("same") or {}
        if not spec:
            return None
        words = self._particle_variant_words(literal)[0].replace(",", " ").split()
        if len(words) < 3 or words[-1] not in self._comparison_forms(spec.get("predicates", [])):
            return None
        particles = sorted(set(self.case_particles) | {p for group in self.slot_particles for p in group},
                           key=len, reverse=True)
        joiners = sorted((self.comparison or {}).get("between", {}).get("joiners", []), key=len, reverse=True)
        body = [w for w in words[:-1] if w not in spec.get("intensifiers", [])
                and w not in (self.comparison or {}).get("time_words", [])]
        joiner = next((j for j in joiners if body and body[0].endswith(j) and len(body[0]) > len(j)), None)
        if joiner is None or len(body) < 2:
            return None
        second = body[1]
        particle = next((p for p in particles if second.endswith(p) and len(second) > len(p)), None)
        if particle is None:
            return None
        item = []
        for word in body[2:]:
            stem = next((word[:-len(p)] for p in particles if word.endswith(p) and len(word) > len(p)), word)
            if stem not in spec.get("number_nouns", []):
                item.append(stem)
        return {"query": [{"same": {"a": body[0][:-len(joiner)], "b": second[:-len(particle)],
                                    "item": " ".join(item) or None}}]}

    def _count_predicate_forms(self, questions_only=False):
        """Forms of the declared count-question predicate stems (only question forms if asked)."""
        if self._count_predicates is None:
            from hangul import inflect
            grammar = self.inflection_grammar or {}
            asking = set(grammar.get("question_endings", []))
            forms, questions = set(), set()
            for row in (self.count_question or {}).get("predicates", []):
                for tense in grammar.get("tenses", {}):
                    for ending in grammar.get("endings", {}):
                        try:
                            made = {f["text"] for f in inflect(row["stem"], tense, ending, grammar,
                                                               kind=row.get("kind", "regular"))}
                        except (ValueError, KeyError):
                            continue
                        forms |= made
                        if ending in asking:
                            questions |= made
            self._count_predicates = (forms, questions)
        return self._count_predicates[1 if questions_only else 0]

    def _quantity_chain_meaning(self, literal):
        """팩이 선언한 `시작 양 → 변화들 → 남은 양` 구조를 한 번에 읽는다.

        이 경로는 물건 이름·수치·동사 하나를 코드에 갖지 않는다. 단위, 시작
        연결, 변화 관계와 표면형은 언어 팩이 주고, 이곳은 순서와 수량 슬롯을
        검증해 공통 상태 전이로 만든다.
        """
        from numeral_semantics import parse_numeral
        spec = self.quantity_chain
        units, starts = spec.get("units", []), spec.get("from_markers", [])
        operations = spec.get("operations", [])
        if not (units and starts and operations):
            return None
        unit = "(?:%s)" % "|".join(re.escape(value) for value in sorted(units, key=len, reverse=True))
        start = "(?:%s)" % "|".join(re.escape(value) for value in sorted(starts, key=len, reverse=True))
        initial_patterns = [
            r"\s*(?P<item>.+?)\s+(?P<n>[^.!?,]+?)\s*" + unit + r"\s*" + start
            + r"\s+(?P<tail>.+?)\s*"
        ]
        for declared in spec.get("initial_forms", []):
            particles = "(?:%s)" % "|".join(
                re.escape(value) for value in sorted(declared["item_particles"], key=len, reverse=True))
            tails = "(?:%s)" % "|".join(
                re.escape(value) for value in sorted(declared["tails"], key=len, reverse=True))
            initial_patterns.append(
                r"\s*(?P<item>.+?)" + particles + r"\s+(?P<n>[^.!?,]+?)\s*" + unit
                + r"\s+" + tails + r"\s+(?P<tail>.+?)\s*")
        initial = next((match for pattern in initial_patterns
                        for match in [re.fullmatch(pattern, literal)] if match is not None), None)
        if initial is not None:
            item = initial.group("item").strip()
            amount = parse_numeral(initial.group("n"), self.data.get("numerals", {}))
            if not item or amount is None:
                return None
            forms = [(form, operation["predicate"])
                     for operation in operations for form in operation.get("forms", [])]
            form = "(?:%s)" % "|".join(re.escape(value) for value, _predicate in
                                         sorted(forms, key=lambda row: len(row[0]), reverse=True))
            particle = spec.get("object_particles", [])
            particle = ("(?:%s)?" % "|".join(re.escape(value) for value in
                                                sorted(particle, key=len, reverse=True)) if particle else "")
            step = re.compile(r"\s*(?P<n>[^.!?,]+?)\s*" + unit + r"\s*" + particle
                              + r"\s*(?P<form>" + form + r")(?:\s*|$)")
            tail, triples = initial.group("tail"), [[item, "count", amount]]
            while tail:
                matched = step.match(tail)
                if matched is None:
                    return None
                delta = parse_numeral(matched.group("n"), self.data.get("numerals", {}))
                predicate = next((relation for surface, relation in forms
                                  if surface == matched.group("form")), None)
                if delta is None or predicate is None:
                    return None
                triples.append([item, predicate, delta])
                tail = tail[matched.end():].strip()
                if not tail:
                    break
                joiner = next((value for value in sorted(spec.get("joiners", []), key=len, reverse=True)
                               if tail.startswith(value)), None)
                if joiner is None:
                    return None
                tail = tail[len(joiner):].strip()
                if not tail:
                    return None
            return {"triples": triples}

        prefixes, particles = spec.get("query_prefixes", []), spec.get("query_particles", [])
        query_forms, render = spec.get("query_forms", []), spec.get("query_render", [])
        if not (prefixes and particles and query_forms and render):
            return None
        prefix = "(?:%s)" % "|".join(re.escape(value) for value in sorted(prefixes, key=len, reverse=True))
        particle = "(?:%s)" % "|".join(re.escape(value) for value in sorted(particles, key=len, reverse=True))
        question = "(?:%s)" % "|".join(re.escape(value) for value in sorted(query_forms, key=len, reverse=True))
        asked = re.fullmatch(r"\s*" + prefix + r"\s+(?P<item>.+?)" + particle + r"\s*" + question + r"\s*",
                              literal)
        if asked is None or not asked.group("item").strip():
            return None
        return {"query": [{"triple": [asked.group("item").strip(), "count", "?n"],
                            "render": list(render)}]}

    def readings(self, text, *, limit=6, **kw):
        """Every reading the declarations allow for ``text``, the reader's own first (goal G5.4 B, design note
        §10). Each is a whole parse (``parse``'s result) with ``used``: the clause readings it rests on. The
        next is found by parsing again with a clause reading already used left out, so a clause's readings
        of a lower rank, a repair, an event reading or a gapped reading come in their turn; a clause read two
        ways at one rank (which ``parse`` alone leaves unread) gives one reading per way. Readings that say
        the same are given once. Nothing is chosen here: the conversation checks them (reasoning_context)."""
        out, seen, tried = [], set(), set()
        # (excluded clause readings, tier): a tier is the reader's rank order -- a reading found by leaving a
        # used clause reading out is one tier below; the ways of an ambiguous clause share their tier
        queue = [(frozenset(), 0)]
        while queue and len(out) < limit and len(tried) < limit * 4:
            excluded, tier = queue.pop(0)
            if excluded in tried:
                continue
            tried.add(excluded)
            used, notes = [], []
            parsed = self.parse(text, _diagnostics=notes, _exclude=excluded, _used=used, **kw)
            if parsed is None:
                for note in notes:
                    keys = note.get("candidate_keys") or []
                    if note.get("reason") == "ambiguous_clause" and len(keys) > 1:
                        queue += [(excluded | frozenset(k for k in keys if k != keep), tier) for keep in keys]
                        break
                continue
            said = json.dumps([sorted(json.dumps(f["triple"], ensure_ascii=False) for f in parsed.get("facts", [])),
                               parsed.get("query"),
                               sorted(json.dumps([e.get("verb"), e.get("자리")], ensure_ascii=False, sort_keys=True)
                                      for e in parsed.get("사건", []))], ensure_ascii=False, sort_keys=True)
            if said not in seen:
                seen.add(said)
                out.append({"parsed": parsed, "used": list(used), "excluded": sorted(excluded), "said": said,
                            "tier": tier})
            queue += [(excluded | {key}, tier + 1) for key in used if key not in excluded]
        return out

    def parse(self, text, *, partial=False, events=False, verbs=None, repair=False, _diagnostics=None,
              _exclude=(), _used=None):
        """``events`` 를 켜면 아무 사례도 못 읽은 구절을 **사건 꼴**로도 본다.

        조사가 자리를 짚고 남은 한 낱말이 움직임인 꼴이다. 뜻은 여기서 안
        정한다 — 쓰인 낱말을 그대로 담고, 설명받은 어간과 잇는 일은 대화
        쪽에서 한다. 이 문을 열지 않으면 뜻을 모르는 말을 만났을 때 **무엇을**
        모르는지 짚어 줄 수 없다.

        ``verbs`` 는 설명받은 말들의 꼴 → ``{어간, 물음}`` 이다. **무슨 동사인가
        만으로는 모자란다** — 물어본 것인지 실제로 일어난 일인지가 같이 와야
        `민수가 지연에게 베풉니까` 가 구슬을 옮기지 않는다.
        """
        from hangul import clause_spans
        # A relative clause that states a holder's amount is its own clause
        # (문장분리.relative_clauses): said first, then the clause it modified.
        text = self._relative_clauses(text)
        facts, query, 조건 = [], None, []
        # 인과는 `누구의 원인` 하나가 아니다. 같은 사람이 여러 일을 할 수
        # 있으므로, 원인과 결과 사건 표지를 한 기록으로 묶어야 이유 물음이
        # 엉뚱한 사건의 원인을 가져가지 않는다. 표면형과 사건 표지는 언어 팩의
        # 뜻풀이가 주고, 여기서는 그 선언을 같은 방식으로 결합만 한다.
        원인, 이유물음 = [], []
        # 뜻풀이와 그 뜻을 쓰는 사건. 낱말마다 예문을 더하는 것이 아니라,
        # **뜻풀이가 어떻게 생겼는지**를 한 번 선언해 두고 내용은 사용자가 채운다.
        defined, invoked = [], []
        # 규칙에 맞춰 고쳐 읽은 절. 답과 상태가 이 수선 위에 선다는 것을 남긴다.
        수선 = []
        사건정정 = []
        clauses = []
        diagnostics = _diagnostics if _diagnostics is not None else []
        unrecognized = False
        # Only a fully recognized prefix authorizes a soft clause boundary.
        # A failed suffix guess (e.g. a noun ending in 고) never drops source text.
        cache, derivations = {}, {}
        # a clause reading after _owner_items -> the reading _clause_meanings gave (what ``readings`` leaves out)
        self._owner_origin = {}

        def without_hypothetical_prefix(literal):
            leading = literal[:len(literal) - len(literal.lstrip())]
            body = literal[len(leading):]
            for prefix in self.hypothetical_prefixes:
                if (body.startswith(prefix) and len(body) > len(prefix)
                        and body[len(prefix)].isspace()):
                    return leading + body[len(prefix):].lstrip(), prefix
            return literal, None

        matched_examples = {}

        def meanings(literal):
            if literal not in cache:
                derivations[literal] = {}
                matched_examples[literal] = {}
                candidate, _marker = without_hypothetical_prefix(literal)
                cache[literal] = self._clause_meanings(candidate, derivations=derivations[literal],
                                                       matched=matched_examples[literal], exclude=_exclude)
            return cache[literal]

        def learned_event(literal):
            """Read a learned action even when it is the premise of a question.

            The hypothetical marker is a discourse declaration, not an action
            name.  The event keeps its normal role reading and carries a scope
            bit into the common action executor instead of becoming an actual
            observation merely because it has a familiar verb.
            """
            if not events:
                return None
            candidate, marker = without_hypothetical_prefix(literal)
            from frame_induction import read_event
            event = read_event(candidate, self.case_particles, self.slot_particles,
                               self.negation, verbs, self.plan, self.inflection_grammar)
            # Clause boundaries for an unknown verb would split a definition
            # body such as "... 주고, ... 주는 것이다" before induction gets
            # to read the whole body.  Only an already learned surface form is
            # evidence that this prefix is an independently executable event.
            known = event is not None and (event["verb"] in (verbs or {})
                                            or any((found.get("stem") if isinstance(found, dict) else found)
                                                   == event["verb"]
                                                   for found in (verbs or {}).values()))
            if event is not None and not known:
                return None
            if event is not None and marker and (verbs or {}).get(event["verb"], {}).get("조건"):
                event = {**event, "hypothetical": True}
            return event

        # A sentence read whole by one declared example (all Haru has is marbles, 18 of them) or by
        # one with a phrase variant left out (..., apparently) is one clause: its commas split nothing.
        marks = "".join(self.clause_grammar.get("question_marks", [])) + ".!"
        whole = text.strip().rstrip(marks + " ")
        bare = whole
        for abbreviation in self.clause_grammar.get("abbreviations", []):
            bare = bare.replace(abbreviation, "")
        read_whole = bool(whole) and not any(ch in bare for ch in marks) and bool(meanings(whole))
        # A connective splits a sentence read whole only when no example read it with that
        # connective inside (Haru has 18 marbles and some pears is one example).
        joined_whole = read_whole and any(
            any((" %s " % marker) in " %s " % self.data["examples"][index]["text"]
                for marker in self.clause_grammar.get("after_clause_markers", []))
            for index in matched_examples.get(whole, {}).values())

        def complete_prefix(literal):
            if read_whole and "," in whole and (literal + ",") in text:
                return False
            if joined_whole and not (literal + ",") in text:
                return False
            if any(delimiter in literal for delimiter in self.definition_body_delimiters):
                # A definition body may itself contain a conditional or a
                # learned-action connective.  Do not let a broad ordinary
                # clause template split it before the definition template has
                # seen its complete body.
                return False
            if meanings(literal) or learned_event(literal) is not None:
                return True
            # A comma after words the phrase variants leave out (Actually, ...) ends a clause that says nothing.
            if (literal + ",") in text and self._only_dropped_words(literal):
                return True
            # A comma is a strong boundary: a conjunct that only a bounded
            # repair can place is still a complete clause. Weaker boundaries
            # (a connective ending) are never opened by repair.
            return bool(repair and self.repair and (literal + ",") in text and self._repair(literal)[0])

        last_read = None        # (text, asserted rows) of the clause read just before
        for evidence in clause_spans(text, self.clause_grammar, commas=True,
                                     accept_prefix=complete_prefix,
                                     inflected_boundary=lambda word: (
                                         self._inflected_boundary(word)
                                         or bool((verbs or {}).get(word, {}).get("조건")))):
            # Plans are pack-declared, role-bound event records.  Read them
            # before broad ordinary templates can reinterpret the same text
            # as (for example) an ``isa`` assertion; a plan must remain a
            # non-executed event through correction and replay.
            planned = learned_event(evidence["text"])
            if planned is not None and planned.get("modality") == "planned":
                clauses.append(([{"invoke": {"verb": planned["verb"], "자리": planned["자리"],
                                            "자리후보": planned["자리후보"], "잘림": planned["잘림"]},
                                 "modality": "planned"}], evidence))
                continue
            unique = self._owner_items(meanings(evidence["text"]), evidence["text"],
                                       derivations, matched_examples)
            if not unique and last_read is not None:
                # A conjunct that left out the verb it shares with the clause
                # before (생략.gapping) reads as that clause with its own words.
                gapped = self._gapped(evidence["text"], *last_read)
                read = (self._owner_items(meanings(gapped), gapped, derivations, matched_examples)
                        if gapped is not None else {})
                if len(read) == 1:
                    unique = read
                    derivations[evidence["text"]] = {key: {"rule": "declared-gapping-v1", "canonical": gapped}
                                                     for key in read}
                    matched_examples[evidence["text"]] = dict(matched_examples.get(gapped, {}))
            # 수선은 부르는 쪽이 청할 때만 한다. 파서 자체의 계약은 선언된 규칙에
            # 그대로 맞는 읽기뿐이다 — 대화가 수선을 청하고 그 사실을 보고한다.
            if not unique and repair and self.repair and learned_event(evidence["text"]) is None:
                repaired, repair_derivations, report = self._repair(evidence["text"])
                if repaired:
                    unique = repaired
                    derivations[evidence["text"]] = repair_derivations
                    수선.append(report)
            asking = any(text[evidence["end"]:].lstrip().startswith(mark)
                         for mark in self.clause_grammar.get("question_marks", []))
            if (not asking and (self.count_question or {}).get("declarative_vague")
                    and text[evidence["end"]:].lstrip().startswith(".") and len(unique) == 1):
                # 연서도 레몬이 몇 개 있어요. -- the question word of amount in a sentence closed by a full
                # stop says "a few": a count not known, not a question (수량물음.declarative_vague)
                only = next(iter(unique.values()))
                rows = only.get("query") or []
                if (len(rows) == 1 and isinstance(rows[0].get("triple"), list)
                        and rows[0]["triple"][1] == "count" and str(rows[0]["triple"][2]).startswith("?")):
                    stated = {"triple": [rows[0]["triple"][0], "count_unknown", "some"]}
                    unique = {json.dumps(stated, sort_keys=True, ensure_ascii=False): stated}
            if asking and any(asserted(meaning) or "invoke" in meaning
                              for meaning in unique.values()):
                diagnostics.append({"reason": "question_is_not_an_observation", "evidence": evidence})
                unrecognized = True
                continue
            # 물음표 검사가 사건 읽기보다 **먼저** 와야 한다. 나중에 오면
            # 새 경로로 들어온 물음을 놓쳐 물어본 일이 실제로 일어난다.
            # 사례 읽기가 **조사를 넘어 삼켰으면** 사건 읽기와 겨룬다. 넓은 틀은
            # 아무 말이나 한 이름으로 삼켜 맞기 때문에, 맞았다는 이유로 이기면
            # `민수가 지연에게 베풀 예정이다` 가 `민수 isa 지연에게 베풀 예정` 이 된다.
            if unique and events and not asking:
                from frame_induction import _marked
                # A generic relation can leave its subject unmarked while
                # swallowing only the object/recipient case marker.  Requiring
                # *every* generated field to be marked made a known planned
                # action such as ``하루가 공책을 옮길 예정이다`` become an
                # asserted ``isa`` fact.  One swallowed marker is enough to
                # compare the fully role-bound event; the event-side guard
                # below still rejects a reading that itself loses a marker.
                삼킴 = any(_marked(str(part), self.case_particles, self.slot_particles)
                           for meaning in unique.values()
                           for row in (asserted(meaning) or []) for part in row)
                # A pack-declared future plan is likewise unambiguous: its
                # action is recognized through the inflection grammar and it
                # carries typed roles, whereas the competing generic fact has
                # no modality.  Preserve it as a non-executed event even when
                # the broad template's captured value happens not to end in a
                # case marker.
                event = learned_event(evidence["text"])
                if 삼킴 or (event is not None and event.get("modality") == "planned"):
                    # 사건 읽기가 이기려면 **그쪽도 근거가 있어야** 한다 — 이 대화가
                    # 아는 말로 끝나고, 조사를 안 넘어야 한다. 그냥 이기게 두면
                    # `사과 상자는 책상에 있었다` 가 모르는 말 하나로 뒤집힌다.
                    아는말 = event is not None and (
                        event["verb"] in (verbs or {})
                        or any((found["stem"] if isinstance(found, dict) else found)
                               == event["verb"] for found in (verbs or {}).values()))
                    if 아는말 and not any(
                            _marked(value, self.case_particles, self.slot_particles)
                            for value in event["자리"].values()):
                        unique = {}
            if not unique and events and not asking:
                from frame_induction import asks, read_event
                if asks(evidence["text"], self.negation, verbs):
                    # 물음표가 없어도 묻는 말이다. 사건으로 읽으면 안 된다.
                    diagnostics.append({"reason": "question_is_not_an_observation",
                                        "evidence": evidence})
                    unrecognized = True
                    continue
                # At a finished sentence an unfamiliar action is still worth
                # recording as an unresolved event.  The known-only helper is
                # used for *boundaries* above, not for discarding this useful
                # diagnosis.
                candidate, marker = without_hypothetical_prefix(evidence["text"])
                event = read_event(candidate, self.case_particles, self.slot_particles,
                                   self.negation, verbs, self.plan, self.inflection_grammar)
                if event is not None and marker and (verbs or {}).get(event["verb"], {}).get("조건"):
                    event = {**event, "hypothetical": True}
                if event is not None:
                    meaning = {"invoke": {"verb": event["verb"], "자리": event["자리"],
                                          "자리후보": event["자리후보"],
                                          "잘림": event["잘림"]}}
                    if event.get("polarity") is False:
                        meaning["polarity"] = False
                    if event.get("modality"):
                        meaning["modality"] = event["modality"]
                    if event.get("hypothetical"):
                        meaning["hypothetical"] = True
                    clauses.append(([meaning], evidence))
                    continue
            if not unique and self._only_dropped_words(evidence["text"]):
                # A clause of words the pack's phrase variants leave out and nothing else (a
                # trailing "actually", "by the way") says nothing: it is not an unread clause.
                continue
            if not unique:
                diagnostics.append({"reason": "unrecognized_clause", "evidence": evidence,
                                    "candidates": []})
                unrecognized = True
                continue
            clauses.append((list(unique.values()), evidence))
            # The clause as it was read (a declared variant's wording: ``'s got``
            # read as ``has``) is what a gapped conjunct after it shares.
            only = list(unique.items())
            read_as = (((derivations.get(evidence["text"]) or {}).get(only[0][0]) or {}).get("canonical")
                       if len(only) == 1 else None)
            last_read = ((read_as or evidence["text"], asserted(only[0][1]))
                         if len(only) == 1 and asserted(only[0][1]) else None)
        if unrecognized:
            return None

        def entities(meaning):
            if "define" in meaning or "invoke" in meaning:
                return set()
            if "cause" in meaning:
                record = meaning["cause"]
                return {record["subject"]} if isinstance(record, dict) and isinstance(record.get("subject"), str) else set()
            if "reason_query" in meaning:
                request = meaning["reason_query"]
                return {request["subject"]} if isinstance(request, dict) and isinstance(request.get("subject"), str) else set()
            triples = asserted(meaning) or [joined(q["triple"]) for q in meaning.get("query", [])]
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
                origin = getattr(self, "_owner_origin", {})
                diagnostics.extend({"reason": "ambiguous_clause", "evidence": evidence, "candidates": options,
                                    "candidate_keys": [origin.get(k, k) for k in (
                                        json.dumps(o, sort_keys=True, ensure_ascii=False) for o in options)]}
                                   for options, evidence in clauses if len(options) > 1)
                return None
        previous_rows, previous_end = [], None
        choices = []
        for options, evidence in clauses:
            meaning = options[0]
            key = json.dumps(meaning, sort_keys=True, ensure_ascii=False)
            if _used is not None:
                _used.append(getattr(self, "_owner_origin", {}).get(key, key))
            normalization = derivations.get(evidence["text"], {}).get(key)
            if normalization:
                evidence = {**evidence, "normalization": normalization}
            stated = asserted(meaning)
            # 조건 맺음으로 읽힌 절은 **일어난 일이 아니다.** 사실로 적으면
            # `5개보다 많으면` 이 "많다" 는 단정이 되고, 뒤의 일도 그냥 일어난
            # 일이 된다. 어느 맺음이 조건인지는 문법이 선언한다 — 낱말이 아니다.
            if stated and (normalization or {}).get("ending") in self.condition_endings:
                _candidate, marker = without_hypothetical_prefix(evidence["text"])
                조건 += [{"triple": triple, "evidence": evidence, "kind": "guard",
                          "marker": marker}
                         for triple in stated]
                continue
            # 쉼표로 이은 둘째 마디가 앞 마디의 뒤쪽 말을 생략했으면 물려받는다.
            # 언어 팩이 이 생략을 선언했을 때만, 같은 관계끼리만 한다.
            between = text[previous_end:evidence["start"]].strip() if previous_end is not None else None
            # A declared connective joins two conjuncts just as a comma does:
            # "A has five marbles and B has two" leaves the item out the same
            # way "A has five marbles, and B has two" does.
            markers = self.clause_grammar.get("after_clause_markers", [])
            joined_by_comma = between is not None and (
                (between[:1] == "," and (between == "," or between[1:].strip() in markers))
                or between.lower() in {marker.lower() for marker in markers})
            # A pack may declare the ellipsis for every clause of one turn
            # (생략.scope = "turn"): "A has 4 figs. B has 2." and "A는 배가 네 개
            # 있고 B는 두 개 있어" leave the item to the clause before as a comma does.
            in_turn = between is not None and self.ellipsis.get("scope") == "turn"
            if stated and (joined_by_comma or in_turn) and self.ellipsis.get("coordination") == "trailing_words":
                stated, inherited = self._inherit_trailing(
                    stated, previous_rows, self._counted_subjects(evidence["text"], stated))
                if inherited:
                    evidence = {**evidence, "ellipsis": inherited}
            previous_rows, previous_end = (stated or []), evidence["end"]
            if stated:
                role_bindings = meaning.get("role_bindings", [])
                example_index = matched_examples.get(evidence["text"], {}).get(key)
                if example_index is None and (normalization or {}).get("repair"):
                    example_index = normalization["repair"].get("rule_index")
                event_verb = (self.data["examples"][example_index].get("event_verb")
                              if example_index is not None else None)
                for position, triple in enumerate(stated):
                    triple = [self.canonical_name(triple[0])] + list(triple[1:])
                    fact = {"triple": triple, "evidence": evidence}
                    if event_verb:
                        # 어순으로 역할을 짚는 언어는 동사 꼬리가 문장 끝에 없다.
                        # 예문이 그 사건의 동사 어간을 선언하면 사실에 남긴다.
                        fact["verb"] = event_verb
                    if meaning.get("elided") and self.ellipsis.get("part_reference"):
                        # 예문이 뒷말을 비워 둔 꼴이다. 앞말만으로 대상을 가리킨다.
                        fact["resolve"] = self.ellipsis["part_reference"]
                    if position < len(role_bindings) and role_bindings[position] is not None:
                        fact["roles"] = role_bindings[position]
                    if "scope" in meaning:
                        fact["scope"] = meaning["scope"]
                    if meaning.get("places"):
                        fact["places"] = list(meaning["places"])
                    if meaning.get("unnamed"):
                        fact["unnamed"] = True
                    for field in ("polarity", "modality"):
                        if field in meaning:
                            fact[field] = meaning[field]
                    facts.append(fact)
            elif "define" in meaning:
                defined.append({**meaning["define"], "evidence": evidence})
            elif "invoke" in meaning:
                invoked.append({**meaning["invoke"], "evidence": evidence,
                                **({"polarity": meaning["polarity"]} if "polarity" in meaning else {}),
                                **({"modality": meaning["modality"]} if "modality" in meaning else {}),
                                **({"hypothetical": True} if meaning.get("hypothetical") else {})})
            elif "cause" in meaning:
                record = meaning["cause"]
                if not (isinstance(record, dict)
                        and all(isinstance(record.get(key), str) and record[key]
                                for key in ("subject", "cause", "effect"))):
                    diagnostics.append({"reason": "invalid_cause_record", "evidence": evidence})
                    return None
                원인.append({**record, "evidence": evidence})
            elif "reason_query" in meaning:
                request = meaning["reason_query"]
                if not (isinstance(request, dict)
                        and all(isinstance(request.get(key), str) and request[key]
                                for key in ("subject", "effect"))):
                    diagnostics.append({"reason": "invalid_reason_query", "evidence": evidence})
                    return None
                이유물음.append({**request, "evidence": evidence})
            elif "relation_query" in meaning and query is None:
                # Relationship instances are event-created entities, not a
                # participant-pair subject.  Keep the query declarative in
                # the language pack; answer() performs the generic binary
                # joins over its participant indexes and status property.
                request = copy.deepcopy(meaning["relation_query"])
                if not (isinstance(request, dict)
                        and all(isinstance(request.get(key), str) and request[key]
                                for key in ("kind", "actor", "other", "predicate"))):
                    diagnostics.append({"reason": "invalid_relation_query", "evidence": evidence})
                    return None
                query = [{"relation_query": request}]
            elif "concept_query" in meaning and query is None:
                request = copy.deepcopy(meaning["concept_query"])
                if not (isinstance(request, dict)
                        and all(isinstance(request.get(key), str) and request[key]
                                for key in ("actor", "other", "action"))):
                    diagnostics.append({"reason": "invalid_concept_query", "evidence": evidence})
                    return None
                query = [{"concept_query": request}]
            elif "event_relation_query" in meaning and query is None:
                request = copy.deepcopy(meaning["event_relation_query"])
                if not (isinstance(request, dict)
                        and all(isinstance(request.get(key), str) and request[key]
                                for key in ("action", "predicate", "value"))
                        and isinstance(request.get("roles"), dict)
                        and all(isinstance(key, str) and isinstance(value, str) and value
                                for key, value in request["roles"].items())
                        and isinstance(request.get("render"), list)):
                    diagnostics.append({"reason": "invalid_event_relation_query", "evidence": evidence})
                    return None
                query = [{"event_relation_query": request}]
            elif "event_correction" in meaning:
                # 앞서 말한 사건 하나의 값을 고친다는 말. 새 사건이 아니다.
                request = copy.deepcopy(meaning["event_correction"])
                if not (isinstance(request, dict)
                        and all(isinstance(request.get(key), str) and request[key]
                                for key in ("verb", "old", "new"))):
                    diagnostics.append({"reason": "invalid_event_correction", "evidence": evidence})
                    return None
                사건정정.append({**request, "evidence": evidence})
            elif "why_last" in meaning and query is None:
                query = [{"why_last": True}]
            elif "why_count" in meaning and query is None:
                subject = meaning["why_count"].get("subject")
                if not (isinstance(subject, list) and subject and all(isinstance(w, str) and w for w in subject)):
                    diagnostics.append({"reason": "invalid_why_count", "evidence": evidence})
                    return None
                query = [{"why_count": {"subject": list(subject)}}]
            elif "other_than" in meaning and query is None:
                request = copy.deepcopy(meaning["other_than"])
                if not (isinstance(request, dict) and isinstance(request.get("excluded"), str)
                        and request["excluded"]):
                    diagnostics.append({"reason": "invalid_other_than", "evidence": evidence})
                    return None
                query = [{"other_than": request}]
            elif "choices" in meaning:
                # The names a comparison chooses between, said on their own
                # ("하루야 모래야"); they complete a comparison in the same turn.
                choices = [self.canonical_name(str(name)) for name in meaning["choices"]]
            elif "concept_reason_query" in meaning and query is None:
                query = [{"concept_reason_query": True}]
            elif "query" in meaning and query is None:
                # Query patterns use the same relation-identity representation
                # as asserted facts.  A pack may compose a subject from typed
                # roles (for example, actor + relation + participant); join
                # it before binding so current-state lookup and provenance see
                # one identical triple on both sides.
                query = copy.deepcopy(meaning["query"])
                if isinstance(query, list):
                    for request in query:
                        if isinstance(request, dict) and isinstance(request.get("triple"), list):
                            request["triple"] = joined(request["triple"])
                            request["triple"][0] = self.canonical_name(request["triple"][0])
            else:
                diagnostics.append({"reason": "multiple_queries_or_invalid_meaning", "evidence": evidence})
                return None
        for request in (query or []) if isinstance(query, list) else []:
            for kind in ("more", "fewer"):
                if (isinstance(request, dict) and isinstance(request.get(kind), dict)
                        and not request[kind].get("a") and len(choices) == 2):
                    request[kind]["a"], request[kind]["b"] = choices
        usable = bool(facts or query or defined or invoked or 조건 or 원인 or 이유물음 or 사건정정) if partial else bool(
            ((facts or defined or invoked) and query) or (원인 and 이유물음))
        if not usable:
            diagnostics.append({"reason": "missing_facts" if not facts else "missing_query"})
        # 조건절이 전부 상태 변화이고 그 뒤가 물음이면, 이는 실제 사건 기록이 아니라
        # 그 변화만 임시로 놓고 묻는 가정이다. 비교 조건+뒤 사건은 기존의 실제
        # 조건 실행으로 남긴다. 동사 이름이 아니라 공리의 상태 변화 선언으로 가른다.
        updates = self.data.get("numeric_updates", {})
        가정 = ([{**item, "kind": "hypothesis"} for item in 조건]
                if query is not None and 조건
                and all(item["triple"][1] in updates for item in 조건) else [])
        가정사건 = [event for event in invoked if event.get("hypothetical")]
        return ({"facts": facts, "query": query, "정의": defined,
                 "사건": [event for event in invoked if not event.get("hypothetical")],
                 "가정사건": 가정사건,
                 "조건": 조건, "가정": 가정, "원인": 원인, "이유물음": 이유물음,
                 "수선": 수선, "사건정정": 사건정정}
                if usable else None)

    def answer(self, parsed):
        from graph_inference import bind, current_facts, proof
        # 이유는 주어만 맞춰 답하지 않는다. 결과 사건 표지까지 같은 기록에서
        # 맞춰야 하며, 후보가 둘이면 하나를 고르지 않는다. 이 경로는 `cause`와
        # `reason_query`라는 팩 선언을 쓰므로 특정 원인·동사·문장에 의존하지 않는다.
        reason_queries = parsed.get("이유물음", [])
        if reason_queries:
            if len(reason_queries) != 1:
                return None
            request = reason_queries[0]
            candidates = [record for record in parsed.get("원인", [])
                          if (record["subject"], record["effect"])
                          == (request["subject"], request["effect"])]
            distinct = {(record["cause"], tuple(record.get("render", []))): record
                        for record in candidates}
            if len(distinct) != 1:
                return None
            record = next(iter(distinct.values()))
            render = record.get("render", ["$cause"])
            if not isinstance(render, list) or not all(isinstance(part, str) for part in render):
                return None
            answer = "".join(
                re.sub(r"\$([a-z][a-z0-9_]*)",
                       lambda matched: str(record.get(matched.group(1), matched.group(0))), part)
                for part in render)
            return {"answer": answer,
                    "transitions": [{"operation": "cause_for_effect",
                                     "fact": [record["subject"], "cause", record["cause"]],
                                     "effect": record["effect"],
                                     "evidence": record["evidence"]}]}
        facts, changes = current_facts(parsed["facts"], self.data.get("mutable_predicates", []),
                                       self.data.get("numeric_updates", {}))
        relation_queries = [query.get("relation_query") for query in parsed["query"]
                            if isinstance(query, dict) and isinstance(query.get("relation_query"), dict)]
        if relation_queries:
            # A relation occurrence is represented by four ordinary binary
            # facts: kind, actor, other and mutable status.  This join is
            # shared by every pack-declared relationship; no promise/person
            # special case is embedded here.
            if len(relation_queries) != 1 or len(parsed["query"]) != 1:
                return None
            request = relation_queries[0]
            fields, evidence = {}, {}
            for row in facts:
                triple = row.get("triple") or []
                if len(triple) != 3:
                    continue
                fields.setdefault(triple[0], {})[triple[1]] = triple[2]
                evidence[(triple[0], triple[1])] = row.get("evidence") or {}
            matches = [relation for relation, values in fields.items()
                       if values.get("relation_kind") == request["kind"]
                       and values.get("relation_actor") == request["actor"]
                       and values.get("relation_other") == request["other"]
                       and request["predicate"] in values]
            if len(matches) != 1:
                return None
            relation = matches[0]
            status = fields[relation][request["predicate"]]
            render = request.get("render")
            answer = ("".join(part.replace("$status", str(status)) for part in render)
                      if isinstance(render, list) and all(isinstance(part, str) for part in render)
                      else str(status) + self.data["answer_suffix"])
            return {"answer": answer,
                    "transitions": changes + [{"operation": "relation_lookup",
                                                 "relation": relation,
                                                 "kind": request["kind"],
                                                 "actor": request["actor"],
                                                 "other": request["other"],
                                                 "status": status,
                                                 "evidence": evidence.get((relation, request["predicate"]), {})}]}
        known = self._closure(facts)
        totals = [query for query in parsed["query"] or []
                  if isinstance(query, dict) and isinstance(query.get("total"), dict)]
        if totals:
            return self._answer_total(totals[0], known, changes, proof)
        mores = [query for query in parsed["query"] or []
                 if isinstance(query, dict) and isinstance(query.get("more"), dict)]
        if mores:
            return self._answer_more(mores[0]["more"], known, changes, proof)
        fewers = [query for query in parsed["query"] or []
                  if isinstance(query, dict) and isinstance(query.get("fewer"), dict)]
        if fewers:
            return self._answer_more(fewers[0]["fewer"], known, changes, proof, fewer=True)
        sames = [query for query in parsed["query"] or []
                 if isinstance(query, dict) and isinstance(query.get("same"), dict)]
        if sames:
            return self._answer_same(sames[0]["same"], known, changes, proof)
        queries = parsed["query"]
        if self.ellipsis.get("part_reference") == "leading_words":
            # `지연은 몇 개야` 의 `지연` 이 그대로는 상태 대상이 아니면, 그 앞말로
            # 시작하는 대상이 하나일 때만 그것을 묻는 것으로 읽는다.
            from graph_inference import leading_word_referent
            present = {(fact[0], fact[1]) for fact in known}
            queries = []
            for query in parsed["query"]:
                triple = query.get("triple") if isinstance(query, dict) else None
                if (isinstance(triple, list) and len(triple) == 3 and isinstance(triple[0], str)
                        and not triple[0].startswith(("?", "$")) and (triple[0], triple[1]) not in present):
                    referent = triple[0]
                    # The same name with or without the pack's name suffix
                    # (`가람` / `가람이`) is one person; try it before giving up.
                    for candidate in [triple[0]] + self._suffix_variants(triple[0]):
                        if (candidate, triple[1]) in present:
                            referent = candidate
                            break
                        found = leading_word_referent(candidate, triple[1], dict.fromkeys(present))
                        if found != candidate:
                            referent = found
                            break
                    if referent != triple[0]:
                        query = {**query, "triple": [referent] + triple[1:], "resolved_from": triple[0]}
                queries.append(query)
        found = []
        for query in queries:
            for fact in known:
                bindings = bind(query["triple"], fact, {})
                if bindings is not None:
                    result = substitute(query, {k[1:]: v for k, v in bindings.items()})
                    result["triple"] = list(fact)
                    found.append(result)
        if len(found) != 1:
            # `이 근거만으로 분류라고 할 수 있는가`처럼, 정방향 증명은 찾되
            # 그 역방향을 새 규칙으로 만들지 않는 질의가 있다. 이 경우에만
            # 팩이 선언한 보류 문구를 돌려 준다. 일반 사실 물음의 미증명은
            # 여전히 답을 만들지 않는다.
            unknown = [query.get("unknown") for query in queries
                       if isinstance(query.get("unknown"), str) and query["unknown"]]
            if not found and len(unknown) == 1:
                return {"answer": unknown[0], "transitions": []}
            return None
        result = found[0]
        answer = ("".join(result["render"]) if "render" in result else
                  result["answer"] + self.data["answer_suffix"])
        return {"answer": answer,
                "transitions": changes + proof(known, result["triple"])}
