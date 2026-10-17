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

# Every pattern this module matches, compiled once per process. Parsing builds a few thousand distinct
# patterns (pack words escaped into them), more than the 512 `re` keeps, so its own cache thrashed and
# recompiled. A compiled pattern depends only on its text and flags, never on a parser, so parsers share
# it and nothing a parser learns makes it stale.
# ponytail: unbounded; the patterns come from the loaded packs, a few thousand per language.
_patterns = {}


def _compiled(pattern, flags=0):
    found = _patterns.get((pattern, flags))
    if found is None:
        found = _patterns[pattern, flags] = re.compile(pattern, flags)
    return found


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
    def __init__(self, data=None, model_path=None, *, language_pack=None, language=None,
                 entry_origins=None, selected_action_surface=None):
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
        if selected_action_surface is not None:
            self.language_pack["selected_action_surface"] = copy.deepcopy(selected_action_surface)
        # 몸통에서 꺼낸 틀은 예문이 그대로인 동안만 같다. `learn` 이 예문을
        # 늘리면 버린다 — 옛 사례로 읽은 몸통을 그대로 쓰면 안 된다.
        self.induced_frames = {}
        incoming = self.data["examples"]
        kept = [i for i, e in enumerate(incoming) if not e.get("derived")]
        parents = []
        generated = self._elided_counted_nouns(incoming, _parents=parents)
        self.data["examples"] = [incoming[i] for i in kept] + generated
        # Passive provenance only: one entry per final example, never written
        # into data/examples/meaning/templates.
        if entry_origins is None:
            self._entry_origins = [None] * len(self.data["examples"])
        else:
            from marco.language.entry_origins import EntryOriginError, remap_entry_origins
            try:
                self._entry_origins = remap_entry_origins(entry_origins, input_count=len(incoming),
                                                          kept_indices=kept, derived_from=parents)
            except ValueError as exc:
                raise EntryOriginError('entry_origin_remap_invalid') from exc
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

    def _elided_counted_nouns(self, examples, *, _parents=None):
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
        for source_index, example in enumerate(examples):
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
            if _parents is not None:
                _parents.append(source_index)
            have.add(text)
        return out

    def _negation(self, declared):
        """부정을 나타내는 말들. 잇는 말과 보조 어간만 선언하고 꼴은 계산한다.

        `않았다`·`않아요`·`않습니다` 를 손으로 적지 않는다. 언어팩이 이미
        활용을 계산하고 있으므로, 부정도 낱말이 아니라 한 줄이면 된다.
        """
        from marco.language.hangul import inflect
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
        from marco.language.hangul import inflect
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
        if annotation.get("endings"):
            # The example names the endings it is said with: a statement that ends the sentence
            # is not also read as the opening clause of a longer one (있었는데 ...).
            endings = [ending for ending in endings if ending in annotation["endings"]]
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
        # A literal's variant readings and clause candidates, memoized per literal. They follow the
        # examples and this trie, and every change to those comes through here (__init__, learn,
        # expression_learning.propose), so the memos start over with the trie.
        # ponytail: unbounded per parser; a parser lives for one conversation.
        self._variant_memo, self._candidate_memo = {}, {}
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
        from marco.language.hangul import inflect
        from marco.language.numerals import parse_numeral
        grammar = self.inflection_grammar or {}
        numerals = self.data.get("numerals", {})
        table = {}
        for row in self.same_frame:
            kinds = [row["kind"]] if row.get("kind") else list(grammar.get("kinds", []))
            for stem in row.get("stems", []):
                for kind in kinds:
                    for tense in grammar.get("tenses", {}):
                        for ending in grammar.get("endings", {}):
                            # An optional ``endings`` list keeps a row to the endings it names.
                            if "endings" in row and ending not in (row["endings"] or []):
                                continue
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
        # The subject honorific (쓰셨습니다, 파셨어요, 주셨다) of a verb the examples use or a same-frame verb reads as
        # the plain form of the same tense and ending (활용.honorific).
        honorific = grammar.get("honorific") or {}
        if honorific.get("infix"):
            pairs = [(stem, row.get("as") or stem, row.get("read_as"), row.get("endings")) for row in self.same_frame
                     for stem in row.get("stems", [])]
            pairs += [(e["event_verb"], e["event_verb"], None, None) for e in self.data["examples"] if e.get("event_verb")]
            for stem, target_stem, read_as, only_endings in pairs:
                raised = self._honorific_stem(stem)
                if raised is None:
                    continue
                for tense in grammar.get("tenses", {}):
                    for ending in honorific.get("endings", []):
                        if only_endings is not None and ending not in only_endings:
                            continue
                        try:
                            forms = [f["text"] for f in inflect(raised, tense, ending, grammar, kind="regular")]
                            targets = [read_as] if read_as else [
                                f["text"] for f in inflect(target_stem, tense, ending, grammar, kind="regular")]
                        except (ValueError, KeyError):
                            continue
                        for form in forms:
                            if targets and form != targets[0] and parse_numeral(form, numerals) is None:
                                table.setdefault(form, (targets[0], {"id": "declared-same-frame-v1", "stem": raised,
                                                                     "as": read_as or target_stem, "tense": tense,
                                                                     "ending": ending, "honorific": True}))
        for row in self.phrase_variants:
            source, target = row.get("from"), row.get("to", "")
            if isinstance(source, str) and source and isinstance(target, str):
                table.setdefault(source, (target, {"id": "declared-phrase-variant-v1", "from": source, "to": target,
                                                   **({"final": True} if row.get("final") else {})}))
        self._variant_table = table
        return table

    def _honorific_stem(self, stem):
        """The stem with the declared subject honorific (활용.honorific): 쓰 -> 쓰시, 받 -> 받으시, 팔 -> 파시."""
        from marco.language.hangul import compose, decompose
        honorific = (self.inflection_grammar or {}).get("honorific") or {}
        if not honorific.get("infix") or not stem:
            return None
        last = decompose(stem[-1])
        if last is None:
            return None
        coda = last[2] if len(last) > 2 else ""
        if coda in honorific.get("dropped_coda", []):
            return stem[:-1] + compose(last[0], last[1]) + honorific["infix"]
        return stem + (honorific.get("after_coda", honorific["infix"]) if coda else honorific["infix"])

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
                                 _compiled(left + re.escape(source) + right, flags)))
            # The honorific forms are looked for only in a text with one of the declared honorific marks
            # (활용.honorific.marks): hundreds of forms that most clauses cannot contain.
            self._variant_compiled_all = compiled
            self._variant_compiled = [row for row in compiled if not row[2].get("honorific")]
        return self._variant_compiled

    def _variant_patterns_for(self, literal):
        plain = self._variant_patterns()
        marks = ((self.inflection_grammar or {}).get("honorific") or {}).get("marks", [])
        return self._variant_compiled_all if any(mark in literal for mark in marks) else plain

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
        """``literal`` with every declared variant replaced, one reading per step (memoized, see
        ``_rebuild_inflections``)."""
        found = self._variant_memo.get(literal)
        if found is None:
            found = self._variant_memo[literal] = self._variant_literals_of(literal)
        return list(found)

    def _variant_literals_of(self, literal):
        patterns = self._variant_patterns_for(literal)
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
                    current = _compiled(r"\s+([,;:])").sub(r"\1", _compiled(r"\s+").sub(" ", replaced)).strip()
                    folded = current.lower() if self.data.get("ignore_case") else current
                    notes.append({**note, "written": target})
            for index, target in enumerate(kept):
                current = current.replace("QQKEPT%dQQ" % index, target)
            folded = current.lower() if self.data.get("ignore_case") else current
            # A phrase dropped at a clause edge leaves its comma behind ("..., apparently").
            current = _compiled(r"^[,;:\s]+|[,;:\s]+$").sub("", _compiled(r",\s*,").sub(",", current))
            current, note = self._holder_forms(current)
            if note is not None:
                notes.append(note)
            if floated:
                current, note = self._float_quantifier(current)
                if note is None:
                    continue
                notes.append(note)
            unmoved, unmoved_notes = current, list(notes)
            for structural in (self._front_object, self._scramble, self._swap_roles):
                changed, note = structural(current)
                if note is not None:
                    current = changed
                    notes.append(note)
            if notes and current and current != literal_in and all(current != seen for seen, _n in out):
                out.append((current, notes))
            # A word order put back is one more candidate after the words as said, never in place of them: a
            # declared particle variant (한테는 -> 에게는) may read in the order it was said (G7-S experiment 3)
            if unmoved_notes and unmoved != current and unmoved != literal_in \
                    and all(unmoved != seen for seen, _n in out):
                out.append((unmoved, unmoved_notes))
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
            m = _compiled(r"(?i:%s) ([^,]+), (.+)$" % re.escape(preposition)).match(text)
            if m and len(m.group(1).split()) <= 4:
                text, applied = "%s %s %s" % (m.group(2), preposition, m.group(1)), applied + ["fronted_recipient"]
                break
        for preposition in spec.get("fronted_purpose", []):
            m = _compiled(r"(?i:%s) [^,]+, (.+)$" % re.escape(preposition)).match(text)
            if m:
                text, applied = m.group(1), applied + ["fronted_purpose"]
                break
        objects = spec.get("fronted_purpose_objects") or {}
        for suffix in spec.get("fronted_purpose_suffixes", []):
            # 행사 때문에 (,) ... / 이사 준비로, ...: a purpose phrase at the clause's start fills no role
            m = _compiled(r"((?:\S+ ){0,2}?)(\S*)%s,? (.+)$" % re.escape(suffix)).match(text)
            # 바자회를 위해: a suffix that takes an object keeps its object particle on the word before it
            taken = tuple(objects.get("particles", [])) if suffix in objects.get("suffixes", []) else ()
            words = (m.group(1) + m.group(2)).split() if m else []
            if m and (m.group(1) or m.group(2)) and not any(
                    self._ends_in_particle(w) and not (taken and index == len(words) - 1 and w.endswith(taken))
                    for index, w in enumerate(words)):
                text, applied = m.group(3), applied + ["fronted_purpose"]
                break
        determiners = spec.get("possessive_before_numeral") or []
        if determiners:
            # lost his one radio: a possessive determiner right before a count says whose the things are, which
            # the subject already says; the count is read without it (never before a noun: gave his sister)
            from marco.language.numerals import parse_numeral
            numerals = self.data.get("numerals", {})
            words = text.split(" ")
            kept = [w for i, w in enumerate(words)
                    if not (w.lower() in determiners and i + 1 < len(words) and (
                        words[i + 1].isdigit() or parse_numeral(words[i + 1].lower(), numerals) is not None))]
            if len(kept) != len(words):
                text, applied = " ".join(kept), applied + ["possessive_before_numeral"]
        completive = spec.get("completive") or {}
        if completive:
            # 다 썼어요 (used up): the completive adverb before a verb of using up fills no role
            new = _compiled(r"(?<!\S)(?:%s) (?=(?:%s))" % ("|".join(re.escape(w) for w in completive.get("words", [])),
                                                        "|".join(re.escape(v) for v in completive.get("before", [])))).sub("", text)
            if new != text:
                text, applied = new, applied + ["completive"]
        auxiliaries = spec.get("spaced_auxiliary") or []
        if auxiliaries:
            # 나눠 줬어 -> 나눠줬어: a same-frame compound (V-어 주다) written with a space before its auxiliary
            def build():
                prefixes = sorted({stem[:-len(a)] for row in self.same_frame for stem in row.get("stems", [])
                                   for a in auxiliaries if stem.endswith(a) and len(stem) > len(a)},
                                  key=len, reverse=True)
                if not prefixes:
                    return None
                return re.compile(r"(?<!\S)(%s) (\S+?)(?=[.,!?]*(?:\s|$))" % "|".join(map(re.escape, prefixes)))
            pattern, known = self._form_pattern("spaced_auxiliary", build), self._declared_verb_words()
            if pattern is not None and " " in text:
                new = pattern.sub(lambda m: m.group(1) + m.group(2) if (m.group(1) + m.group(2)) in known
                                  else m.group(0), text)
                if new != text:
                    text, applied = new, applied + ["spaced_auxiliary"]
        nouns = spec.get("numeral_nouns") or {}
        if nouns:
            # 하나를 줬어요: a native numeral said as a noun, as an object, is that many of the first counter.
            # Only the native numerals (atoms and tens): the Sino-Korean digits are also common words (일을).
            from marco.language.numerals import parse_numeral
            native = {k: v for k, v in self.data.get("numerals", {}).items() if k in ("atoms", "tens")}
            counter = nouns["counter"]

            def counted(m):
                value = parse_numeral(m.group(1), native)
                # the determiner forms (두, 열두) stand before a counter, never as a noun
                if value is None or m.group(1).endswith(tuple(nouns.get("determiners", []))):
                    return m.group(0)
                return "%s%s%s" % (value, counter, self._particle_form(counter, m.group(2)))
            new = self._form_pattern("numeral_nouns", lambda: re.compile(
                r"(?<!\S)(\S+?)(%s)(?=[\s.,!?]|$)" % "|".join(map(re.escape, nouns["particles"])))).sub(counted, text)
            if new != text:
                text, applied = new, applied + ["numeral_noun"]
        made = spec.get("made_from") or {}
        if made:
            # 세 개로 잼을 만들었어: things an amount of which something was made from are used up
            # (세 개를 썼어), the verb in the same tense and ending; the product fills no role.
            forms = self._same_form_table(made["verb"], made["reads_as"])
            units = "|".join(re.escape(u) for u in sorted(self.counters.get("units", []), key=len, reverse=True))
            if forms and units and made["verb"] in text:
                def used(m):
                    amount = m.group(1).strip()
                    from marco.language.numerals import parse_numeral
                    if not amount.isdigit() and parse_numeral(amount, self.data.get("numerals", {})) is None:
                        return m.group(0)
                    unit = m.group(2)
                    return "%s%s%s %s" % (m.group(1), unit, self._particle_form(unit, made["object"][-1]),
                                         forms[m.group(3)])
                new = self._form_pattern("made_from", lambda: re.compile(
                    r"(?<!\S)(\S+ ?)(%s)(?:%s) \S+?(?:%s) (%s)(?=[\s.,!?]|$)" % (
                        units, "|".join(map(re.escape, made["source"])), "|".join(map(re.escape, made["object"])),
                        "|".join(map(re.escape, sorted(forms, key=len, reverse=True)))))).sub(used, text)
                if new != text:
                    text, applied = new, applied + ["made_from"]
        adverbs = spec.get("dropped_adverbs") or []
        if adverbs:
            # time adverbs that fill no role are left out in every reading, not only with the phrase variants
            new = _compiled(r"(?<!\S)(?:%s)(?!\S)\s*" % "|".join(re.escape(w) for w in adverbs)).sub("", text).strip()
            if new != text and new:
                text, applied = new, applied + ["adverb"]
        zero = spec.get("zero_idiom") or {}
        if zero:
            # 하나도 없어요 / 한 켤레도 없습니다: the amount none, said as the count 0 with the verb of
            # presence in the same form (없어요 -> 0개 있어요)
            units = "|".join(re.escape(u) for u in sorted(self.counters.get("units", []), key=len, reverse=True))
            amounts = "|".join([re.escape(w) for w in zero.get("words", [])]
                               + (["%s ?(?:%s)도" % (re.escape(zero["one"]), units)] if zero.get("one") and units else []))
            new = _compiled(r"(?<!\S)(?:%s) %s(?=\S*)" % (amounts, re.escape(zero["absent"]))).sub("%s %s" % (zero["reads_as"], zero["present"]), text)
            if new != text:
                text, applied = new, applied + ["zero_idiom"]
        marker = spec.get("genitive_quantifier")
        if marker:
            # 열한 개의 메달을 -> 메달을 열한 개: an amount said before its thing with the genitive
            from marco.language.numerals import parse_numeral
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
                new = _compiled(r"(\S+) ?(%s)(%s) (\S+?)(을|를|이|가|은|는|도)?(?=\s|$)" % (units, re.escape(marker))).sub(float_back, text)
                if new != text:
                    text, applied = new, applied + ["genitive_quantifier"]
        particles = spec.get("shifted_particles", [])
        if particles:
            new = _compiled(r"(\S+) (\S+) (%s)(?= )" % "|".join(re.escape(p) for p in particles)).sub(lambda m: "%s %s %s" % (m.group(1), m.group(3), m.group(2))
                         if m.group(1).lower() in self._declared_verb_words() else m.group(0), text)
            if new != text:
                text, applied = new, applied + ["shifted_particle"]
        if not applied:
            return literal, None
        return text, {"id": "declared-word-order-v1", "forms": applied, "from": literal}

    def _holds_counted_amount(self, value):
        """True when ``value`` has a numeral word right before a declared counter (여섯 권, 여섯권을)."""
        from marco.language.numerals import parse_numeral
        units = self.counters.get("units", [])
        if not units:
            return False
        # the native numerals only: the Sino-Korean digits are also syllables of common words (사장)
        numerals = {k: v for k, v in self.data.get("numerals", {}).items() if k in ("atoms", "tens")}
        words = value.split()
        for index, word in enumerate(words):
            for unit in units:
                if word.startswith(unit) and index and parse_numeral(words[index - 1], numerals) is not None:
                    return True
                at = word.find(unit)
                if at > 0 and parse_numeral(word[:at], numerals) is not None:
                    return True
        return False

    def _form_pattern(self, key, build):
        """A word-order form's pattern, compiled once per parser (the module cache of re is too small)."""
        cache = self.__dict__.setdefault("_form_pattern_cache", {})
        if key not in cache:
            cache[key] = build()
        return cache[key]

    def _same_form_table(self, stem, target):
        """{form of ``stem``: the form of ``target`` in the same tense and ending}, by the pack's inflection."""
        cache = self.__dict__.setdefault("_same_form_cache", {})
        if (stem, target) not in cache:
            from marco.language.hangul import inflect
            grammar, table = self.inflection_grammar or {}, {}
            for tense in grammar.get("tenses", {}):
                for ending in grammar.get("endings", {}):
                    try:
                        forms = [f["text"] for f in inflect(stem, tense, ending, grammar, kind="regular")]
                        targets = [f["text"] for f in inflect(target, tense, ending, grammar, kind="regular")]
                    except (ValueError, KeyError):
                        continue
                    for form in forms:
                        if targets and " " not in form:
                            table.setdefault(form, targets[0])
            cache[(stem, target)] = table
        return cache[(stem, target)]

    def _only_dropped_words(self, literal):
        """True when every word of ``literal`` is inside a phrase the pack's phrase variants read
        as nothing (말바꿈 with an empty ``to``)."""
        flags = re.IGNORECASE if self.data.get("ignore_case") else 0
        rest = literal
        for row in sorted(self.phrase_variants, key=lambda r: len(r.get("from") or ""), reverse=True):
            source = row.get("from")
            if source and row.get("to", "") == "":
                rest = _compiled(r"(?<![\w'])%s(?![\w'])" % re.escape(source), flags).sub(" ", rest)
        return bool(literal.strip()) and not _compiled(r"[\s,.!?;:]+").sub("", rest)

    def _declared_verb_words(self):
        """Every form the inflection grammar computes for the verbs the pack reads (its examples'
        event verbs and its same-frame stems), lower-cased."""
        if getattr(self, "_verb_word_cache", None) is None:
            from marco.language.hangul import inflect
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

    def _holder_slot_forms(self, slots, meaning):
        """A holder slot's value said with a declared possessive and a declared relation noun (가진쪽꼴, where
        the pack declares its relation nouns): with a name after them, the name (제 형 창민 -> 창민, as the holder
        form relation_name reads a sentence); alone, the relation noun (제 형 -> 형, own_relation). Only the slots
        that stand first in a holder-thing pair of the meaning (G5 batch 6)."""
        spec = self.holder_forms or {}
        relations, owners = spec.get("relation_nouns"), spec.get("possessives")
        if not relations or not owners:
            return slots
        holders = set()

        def walk(node):
            if isinstance(node, list):
                if (len(node) == 3 and isinstance(node[0], list) and len(node[0]) == 2
                        and isinstance(node[0][0], str) and node[0][0].startswith("$")):
                    holders.add(node[0][0][1:])
                for child in node:
                    walk(child)
            elif isinstance(node, dict):
                for child in node.values():
                    walk(child)
        walk(meaning)
        out = dict(slots)
        for name in holders:
            words = str(out.get(name) or "").split()
            if len(words) >= 2 and words[0] in owners and words[1] in relations:
                out[name] = " ".join(words[2:]) if len(words) >= 3 else words[1]
        return out

    def _slotless_words(self):
        """The single words the pack's phrase variants read as nothing (말바꿈 with an empty ``to``), letters
        only (a title with its period is the holder forms' to read)."""
        if getattr(self, "_slotless_word_set", None) is None:
            fold = (lambda w: w.lower()) if self.data.get("ignore_case") else (lambda w: w)
            self._slotless_word_set = {fold(row["from"].strip()) for row in self.phrase_variants
                                       if isinstance(row.get("from"), str) and row.get("to", "") == ""
                                       and row["from"].strip().isalpha()}
        return self._slotless_word_set

    def _frame_words(self):
        """The words the pack's frames are made of: every word of its examples outside their slots, and every
        single word a declared variant reads as another (sent, lent, passed). A verb or a function word;
        never a relation noun (G5 batch 4)."""
        if getattr(self, "_frame_word_set", None) is None:
            words = set()
            for example in self.data.get("examples", []):
                text = example.get("text", "")
                for value in (example.get("slots") or {}).values():
                    text = _compiled(r"(?<!\w)%s(?!\w)" % re.escape(str(value))).sub(" ", text)
                words |= {w.lower() for w in _compiled(r"[^\W\d_]+").findall(text)}
            words |= {source.lower() for source in self._variants() if " " not in source.strip()}
            self._frame_word_set = words
        return self._frame_word_set

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
                new = _compiled(r"(?<![\w'])%s(?![\w'])" % re.escape(source), flags).sub(target, text)
                if new != text:
                    text, applied = new, applied + ["contraction"]
            for source, target in sorted((speaker.get("particle_forms") or {}).items(), key=lambda kv: -len(kv[0])):
                new = _compiled(r"(?<![\w])%s(?![\w])" % re.escape(source)).sub(target, text)
                if new != text:
                    text, applied = new, applied + ["speaker"]
            forms = speaker.get("forms") or []
            if forms:
                new = _compiled(r"(?<![\w'])(?:%s)(?![\w'])" % words_re(forms), flags).sub(key, text)
                if new != text:
                    text, applied = new, applied + ["speaker"]
            inverted = speaker.get("inverted") or {}
            for verb, agreed in inverted.items():
                # (not before a coordinated subject: do I and Vera have is plural and stays as it is)
                new = _compiled(r"(?<![\w'])%s %s(?![\w'])(?! (?:and|or|nor)(?![\w]))" % (re.escape(verb), re.escape(key)), flags).sub("%s %s" % (agreed, key), text)
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
                new = _compiled(r"(?<![\w'])%s %s(?![\w'])" % (re.escape(key), re.escape(verb))).sub(agree, text)
                if new != text:
                    text, applied = new, applied + ["agreement"]
        prefix_titles = spec.get("prefix_titles") or []
        if prefix_titles:
            # a title before a name (Mr. Lind, Dr. Moore) names the holder by the name
            new = _compiled(r"(?<![\w'])(?:%s) (?=%s(?![\w]))" % (words_re(prefix_titles), name)).sub("", text)
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
                from marco.language.numerals import parse_numeral
                bare = next((word[:-len(x)] for x in suffixes if x and word.endswith(x) and len(word) > len(x)), word)
                return (word.lower() in {w.lower() for w in possessives} or
                        (not self._ends_in_particle(bare) and bare.lower() not in self.outside_names
                         and bare.lower() not in self.pointers and not bare.isdigit()
                         and parse_numeral(bare.lower(), self.data.get("numerals", {})) is None))

            def is_relation(words):
                # a relation noun is a bare content word: never a word outside names (a preposition),
                # a numeral, a pointer, or a word that already carries a case particle; where the pack
                # declares its relation nouns (a language whose names stand bare beside nouns), one of them
                from marco.language.numerals import parse_numeral
                if spec.get("relation_nouns") is not None:
                    return words in spec["relation_nouns"]
                # nor a word the pack's own frames are made of (my niece gave Ann: 'gave' is no relation)
                return all(w.lower() not in self.outside_names and w.lower() not in self.pointers
                           and w.lower() not in self._frame_words()
                           and not w.isdigit() and parse_numeral(w.lower(), self.data.get("numerals", {})) is None
                           and not self._ends_in_particle(w)
                           for w in words.split())
            # A match whose owner word carries a particle moves on by one word, not past the whole match: in 민혁이
            # 가윤 사위 태오에게, 민혁이 is no owner, and 가윤 사위 태오 must still be read as 태오 (one holder, G7-S).
            compiled, new, at = _compiled(pattern), text, 0
            while at <= len(new):
                m = compiled.search(new, at)
                if m is None:
                    break
                if is_owner(m.group(1)) and is_relation(m.group(2)) and not any(
                        (m.group(3).casefold() if self.data.get("ignore_case") else m.group(3))
                        == (a.casefold() if self.data.get("ignore_case") else a)
                        for a in (self.comparison.get("between") or {}).get("among", [])
                        if isinstance(a, str) and a):
                    new = new[:m.start()] + m.group(3) + new[m.end():]
                    at = m.start() + len(m.group(3))
                elif self._ends_in_particle(m.group(1)):
                    # the owner word carries a particle (민혁이): it ends a clause role, the next word may begin one
                    space = new.find(" ", m.start())
                    if space < 0:
                        break
                    at = space + 1
                else:
                    # a bare word that is no owner (곽 of 곽 기사님 짝꿍 우진) begins a longer name: past the match
                    at = m.end()
            if new != text:
                text, applied = new, applied + ["relation_name"]
        determiners = spec.get("determiners") or []
        if determiners:
            pattern = r"(?<![\w'])(?i:%s) (?:[a-z]+ ){0,2}[a-z]+, (%s)(?:,|(?=$))" % (words_re(determiners), name)
            new = _compiled(pattern).sub(r"\1", text)
            if new != text:
                text, applied = new, applied + ["apposition"]
        own = spec.get("self_possessives") or []
        if own:
            pattern = r"(?<![\w'])(?i:%s) (%s)(?![\w'])" % (words_re(own), relation)
            from marco.language.numerals import parse_numeral

            def own_relation(m):
                word = m.group(1)
                if word.lower() in self.outside_names or word.isdigit() or \
                        parse_numeral(word.lower(), self.data.get("numerals", {})) is not None:
                    return m.group(0)
                carries = self._ends_in_particle(word)
                if spec.get("relation_nouns") is not None:
                    particles = sorted({x for g in self.slot_particles for x in g} | set(self.case_particles)
                                       | set(spec.get("delimiters") or []), key=len, reverse=True)
                    stem = next((word[:-len(x)] for x in particles if word.endswith(x) and len(word) > len(x)
                                 and word[:-len(x)] in spec["relation_nouns"]), word)
                    if stem not in spec["relation_nouns"]:
                        return m.group(0)
                    # (a one-syllable relation noun with its particle, 형이, carries a particle too)
                    carries = carries or stem != word
                # a bare relation word before a name belongs to the close apposition (my cousin Ana)
                if not carries and _compiled(r" (?:%s)(?![\w'])" % name).match(text[m.end():]):
                    return m.group(0)
                return word
            new = _compiled(pattern).sub(own_relation, text)
            if new != text:
                text, applied = new, applied + ["own_relation"]
        particle_alt = "|".join(re.escape(p) for p in sorted(
            {p for g in self.slot_particles for p in g} | set(self.case_particles)
            | {row["from"] for row in self.particle_variants if row.get("from")}
            | set(spec.get("delimiters") or []), key=len, reverse=True)) or "(?!)"
        role_titles = spec.get("role_titles") or []
        if role_titles:
            # one or two bare role words before a titled name (인턴 예린 씨, 택배 기사 은우 씨): the name
            from marco.language.numerals import parse_numeral
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
            new = _compiled(pattern).sub(unrole, text)
            if new != text:
                text, applied = new, applied + ["role"]
        titles = spec.get("name_titles") or []
        if titles:
            def untitle(m):
                stem, particle = m.group(1), m.group(3) or ""
                return stem + (self._particle_form(stem, particle) if particle else "")
            pattern = r"(?<!\S)(%s) ?(%s)(%s)?(?![\w])" % (name, words_re(titles), particle_alt)
            new = _compiled(pattern).sub(untitle, text)
            if new != text:
                text, applied = new, applied + ["title"]
        articles = spec.get("numeral_articles") or []
        if articles:
            from marco.language.numerals import parse_numeral
            numerals = self.data.get("numerals", {})

            def drop(m):
                # (one after an article is the pronoun: the one given)
                value = m.group(2) if m.group(2).isdigit() else parse_numeral(
                    m.group(2).lower() if flags else m.group(2), numerals)
                return m.group(2) if value is not None and str(value) != "1" else m.group(0)
            # (not before a partitive: the two of them names holders, not an amount)
            new = _compiled(r"(?<![\w'])(%s) (\S+)(?! of\b)" % words_re(articles), flags).sub(drop, text)
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
        from marco.language.numerals import parse_numeral
        cases = sorted((self.object_fronting or {}).get("floating_cases") or [], key=len, reverse=True)
        units = sorted((self.counters or {}).get("units", []), key=len, reverse=True)
        words = literal.split()
        if not cases or not units or len(words) < 3:
            return literal, None
        numerals = self.data.get("numerals", {})
        for at in range(1, len(words) - 1):
            number, counted = words[at], words[at + 1]
            fused = _compiled(r"(\d+)(.+)").fullmatch(number)
            if fused:                       # ``1마리를``: digits and counter in one word
                number, counted, span = fused.group(1), fused.group(2), 1
            else:
                span = 2
            if not (_compiled(r"\d+").fullmatch(number) or parse_numeral(number, numerals) is not None):
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
        match = _compiled(r"(?P<theme>.+?) (?P<aux>%s) (?P<part>\S+) %s (?P<to>.+?) %s (?P<by>.+)" % (
            "|".join(re.escape(a) for a in auxiliaries), re.escape(to), re.escape(by)), flags).fullmatch(literal)
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
            from marco.language.hangul import inflect
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
            from marco.language.hangul import inflect
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
                        # the subject honorific of the taker's verb (받으셨어요 -> 줬어요)
                        raised = self._honorific_stem(row["stem"])
                        if raised and target and ending in (grammar.get("honorific") or {}).get("endings", []):
                            try:
                                for f in inflect(raised, tense, ending, grammar, kind="regular"):
                                    table.setdefault(f["text"], (row, target[0]))
                            except (ValueError, KeyError):
                                pass
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
        # a surname before a declared job title is one holder with it (탁 차장한테서, 탁 차장이): 가진쪽꼴.job_titles
        titles = set((self.holder_forms or {}).get("job_titles") or [])
        lead = 1 if len(words) > 4 and words[0] and not self._ends_in_particle(words[0]) and any(
            words[1].startswith(t) and words[1][len(t):] in row.get("subject_particles", ["이", "가"])
            for t in titles) else 0
        subject = next((p for p in row.get("subject_particles", ["이", "가"])
                        if words[lead].endswith(p) and len(words[lead]) > len(p)), None)
        if subject is None:
            return literal, None
        taker = " ".join(words[:lead] + [words[lead][:-len(subject)]])
        middle = words[lead + 1:-1]
        if row.get("shape") == "source":
            at = next((i for i, w in enumerate(middle)
                       for p in row.get("source_particles", []) if w.endswith(p) and len(w) > len(p)), None)
            if at is None:
                return literal, None
            particle = next(p for p in row["source_particles"] if middle[at].endswith(p))
            giver = middle[at][:-len(particle)]
            rest = middle[:at] + middle[at + 1:]
            if at > 0 and giver in titles and not self._ends_in_particle(middle[at - 1]):
                giver = middle[at - 1] + " " + giver
                rest = middle[:at - 1] + middle[at + 1:]
        else:
            from marco.language.numerals import parse_numeral
            if len(middle) < 3 or parse_numeral(middle[1], self.data.get("numerals", {})) is not None:
                return literal, None
            # the owner shape is owner, thing, amount (모루의 구슬 두 개를): the amount comes right after the thing
            if parse_numeral(middle[2], self.data.get("numerals", {})) is None and not middle[2][:1].isdigit():
                return literal, None
            giver = middle[0]
            for particle in row.get("owner_particles", []):
                if giver.endswith(particle) and len(giver) > len(particle):
                    giver = giver[:-len(particle)]
                    break
            else:
                # an owner is bare or takes the declared owner particle; a word with another case (상자에서:
                # the place taken from) is no owner (G5 batch 6)
                if self._ends_in_particle(giver):
                    return literal, None
            rest = middle[1:]
        swapped = [giver + self._particle_form(giver, "이"), taker + "에게"] + rest + [verb]
        return " ".join(swapped), {"id": "declared-role-swap-v1", "verb": words[-1], "as": verb}

    def _authority_scope_sha256(self):
        """Hash of the installed language scope; recomputed on every call (no cache)."""
        import hashlib

        def pure(v):
            if type(v) is str or type(v) is int:
                return True
            if type(v) is list:
                return all(pure(x) for x in v)
            return type(v) is dict and all(type(k) is str and pure(x) for k, x in v.items())

        infl, clauses = self.inflection_grammar, self.clause_grammar
        neg = self.language_pack.get('negation', {})
        if (type(infl) is not dict or not infl or type(clauses) is not dict or type(neg) is not dict
                or self.language_pack.get('inflection') != infl
                or self.language_pack.get('clauses') != clauses
                or set(clauses) - {'candidate_suffixes', 'question_marks'}
                or (neg and (set(neg) != {'연결', '어간', '갈래'}
                             or not all(type(x) is str for x in neg.values())))
                or type(clauses.get('question_marks')) is not list or not clauses['question_marks']
                or not all(type(x) is str for x in clauses['question_marks'])
                or type(clauses.get('candidate_suffixes', [])) is not list
                or len(clauses.get('candidate_suffixes', [])) > 16
                or not all(type(x) is str for x in clauses.get('candidate_suffixes', []))
                or not pure(infl)):
            return None
        scope = {'inflection': infl, 'negation': neg,
                 'clauses': {'candidate_suffixes': clauses.get('candidate_suffixes', []),
                             'question_marks': clauses['question_marks']}}
        try:
            text = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                              allow_nan=False)
        except (TypeError, ValueError):
            return None
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    @staticmethod
    def _sb_canon(value):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                              allow_nan=False)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sb_bytes(value):
        text = RelationalParser._sb_canon(value)
        try:
            return None if text is None else text.encode('utf-8')
        except UnicodeEncodeError:
            return None

    @staticmethod
    def _sb_sha(value):
        import hashlib
        data = RelationalParser._sb_bytes(value)
        return None if data is None else hashlib.sha256(data).hexdigest()

    @staticmethod
    def _sb_isindex(v):
        return type(v) is int and v >= 0

    @staticmethod
    def _sb_ishash(v):
        return type(v) is str and len(v) == 64 and set(v) <= set('0123456789abcdef')

    @staticmethod
    def _sb_iscompact(r):
        return (type(r) is dict and set(r) == {'index', 'annotation_sha256', 'source_ref_sha256'}
                and RelationalParser._sb_isindex(r['index'])
                and RelationalParser._sb_ishash(r['annotation_sha256'])
                and RelationalParser._sb_ishash(r['source_ref_sha256']))

    @staticmethod
    def _sb_safe_path(path):
        import unicodedata
        if (type(path) is not str or not path or path != path.strip()
                or unicodedata.normalize('NFC', path) != path or path.startswith('/')
                or chr(92) in path or any(ord(c) < 32 or ord(c) == 127 for c in path)):
            return False
        parts = path.split('/')
        return all(p and p not in ('.', '..') for p in parts) and ':' not in parts[0]

    @staticmethod
    def _sb_triple(triple):
        if type(triple) is not list or len(triple) != 3:
            return None
        for part in triple:
            if type(part) is str and part:
                continue
            if type(part) is list and part and all(type(x) is str and x for x in part):
                continue
            return None
        return joined(triple)

    def _sb_wire_detach(self, value, cap=262144):
        # Pure bounded faithful wire detach: (True, detached, canonical_size) or None (fail closed).
        try:
            if type(cap) is not int or not 1 <= cap <= 262144:
                return None
            budget = [0, 0]

            def walk(v, depth):
                if depth > 32:
                    raise ValueError('depth')
                budget[0] += 1
                if budget[0] > 8192:
                    raise ValueError('items')
                if v is None or type(v) is bool or type(v) is int:
                    return v
                if type(v) is float:
                    if v - v != 0:
                        raise ValueError('float')
                    return v
                if isinstance(v, str):
                    text = str.encode(v, 'utf-8').decode('utf-8')
                    budget[1] += len(text)
                    if budget[1] > cap:
                        raise ValueError('size')
                    return text
                if type(v) is list:
                    return [walk(x, depth + 1) for x in v]
                if type(v) is dict:
                    out = {}
                    for k, x in v.items():
                        if not isinstance(k, str):
                            raise ValueError('key')
                        k2 = str.encode(k, 'utf-8').decode('utf-8')
                        budget[1] += len(k2)
                        if budget[1] > cap:
                            raise ValueError('size')
                        if k2 in out:
                            raise ValueError('key')
                        out[k2] = walk(x, depth + 1)
                    return out
                raise ValueError('type')
            detached = walk(value, 0)
            size = len(json.dumps(detached, sort_keys=True, ensure_ascii=False,
                                  separators=(',', ':'), allow_nan=False).encode('utf-8'))
            if size > cap:
                return None
            return True, detached, size
        except (TypeError, ValueError, RecursionError, OverflowError):
            return None

    def _sb_native_flat_core(self, source):
        # Pure: (lead, body) with at most one declared non-question terminal stripped, else None.
        if type(source) is not str or not source:
            return None
        qmarks = {m for m in self.clause_grammar.get('question_marks', [])
                  if type(m) is str and len(m) == 1 and not m.isspace()}
        if any(q in source for q in qmarks):
            return None
        declared = self.data.get('predicate_frames')
        terms = declared.get('terminators', []) if type(declared) is dict else []
        marks = {m for m in (terms if type(terms) is list else [])
                 if type(m) is str and len(m) == 1 and not m.isspace()} - qmarks
        lead = len(source) - len(source.lstrip())
        body = source.strip()
        if body and body[-1] in marks:
            body = body[:-1].rstrip()
        if not body:
            return None
        return lead, body

    def _sb_native_flat_caps(self, source, roles, slotnames):
        # Pure: (capture_spans, fixed_spans) rebuilt from binder roles, else None.
        if type(roles) is not dict or not slotnames or set(roles) != slotnames:
            return None
        caps = {}
        for name, role in roles.items():
            if type(role) is not dict or set(role) != {'value', 'span'}:
                return None
            sp, val = role['span'], role['value']
            if (type(val) is not str or type(sp) is not list or len(sp) != 2
                    or not all(type(x) is int for x in sp)
                    or not 0 <= sp[0] < sp[1] <= len(source) or source[sp[0]:sp[1]] != val):
                return None
            caps[name] = {'value': val, 'span': [sp[0], sp[1]]}
        ordered = sorted(c['span'] for c in caps.values())
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            return None
        fixed, at = [], 0
        for lo, hi in ordered:
            if lo > at:
                fixed.append([at, lo])
            at = max(at, hi)
        if at < len(source):
            fixed.append([at, len(source)])
        return caps, fixed

    def _sb_native_flat_bind(self, source, idx, resolved):
        # Pure: independently rebind the unique own frame with the native binder; (meaning, trace) or None.
        try:
            from marco.language.frames import _bind_seed_roles
        except ImportError:
            return None
        def canon(v):
            return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                              allow_nan=False)
        if type(source) is not str or type(resolved) is not dict:
            return None
        try:
            decl = self.data.get('predicate_frames')
            frames = decl.get('frames') if type(decl) is dict else None
            if type(frames) is not list or type(idx) is not int or not 0 <= idx < len(frames):
                return None
            full = resolved['source_ref']
            own = [f for f in frames if type(f) is dict and type(f.get('source_ref')) is dict
                   and canon(f['source_ref']) == canon(full)
                   and type(f['source_ref'].get('index')) is int and f['source_ref']['index'] == idx]
            if len(own) != 1 or own[0] is not frames[idx]:
                return None
            frame = own[0]
        except (TypeError, ValueError, KeyError, AttributeError, IndexError, RecursionError, re.error):
            return None
        try:
            out = _bind_seed_roles(self, source, decl, frame)
        except ValueError:
            return None
        try:
            if type(out) is not tuple or len(out) != 3 or out[0] != 'ok':
                return None
            wired = self._sb_wire_detach([out[1], out[2]], 262144)
            if wired is None:
                return None
            nmeaning, ntrace = wired[1]
            keys = {'rule', 'source', 'seed_count', 'seed_sha256', 'source_ref', 'frame_id',
                    'declaration_sha256', 'predicate_span', 'roles', 'markers', 'punctuation',
                    'coverage', 'inflection', 'operators', 'scope'}
            if type(nmeaning) is not dict or type(ntrace) is not dict:
                return None
            if set(ntrace) != keys or len(ntrace) != 15 or ntrace['rule'] != 'seed-constituents-v2':
                return None
            if ntrace['source'] != source or ntrace['inflection'] is not None:
                return None
            sc = ntrace['scope']
            if (type(sc) is not list or len(sc) != 2 or not all(type(x) is int for x in sc)
                    or sc != [0, len(source)]):
                return None
            if (canon(ntrace['source_ref']) != canon(full) or ntrace['frame_id'] != frame.get('id')
                    or canon(ntrace['seed_count']) != canon(decl.get('seed_count'))
                    or canon(ntrace['seed_sha256']) != canon(decl.get('seed_sha256'))):
                return None
            return nmeaning, ntrace
        except (TypeError, ValueError, KeyError, AttributeError, IndexError, RecursionError, re.error):
            return None

    def _sb_verify_native_flat(self, whole, rec, kind, ei, resolved):
        # Pure closed native_flat branch of the witness verifier (positive_fact only).
        bad = (TypeError, ValueError, KeyError, AttributeError, IndexError, RecursionError, re.error)
        try:
            if (kind != 'positive_fact' or rec['normalization'] is not None
                    or rec['grammar_scope'] is not None):
                return None
            if type(rec['meaning_key']) is not str or type(rec['meaning']) is not dict:
                return None
            if type(ei) is not int or ei < 0:
                return None
            examples = self.data.get('examples')
            ex = examples[ei] if type(examples) is list and ei < len(examples) else None
            if type(ex) is not dict or type(ex.get('slots')) is not dict or not ex['slots']:
                return None
        except bad:
            return None
        bound = self._sb_native_flat_bind(whole, ei, resolved)
        if bound is None:
            return None
        split = self._sb_native_flat_core(whole)
        if split is None:
            return None
        try:
            meaning, ntrace = bound
            lead, body = split
            if rec['canonical'] != body:
                return None
            roles = ntrace['roles']
            slotset = set(ex['slots'])
        except bad:
            return None
        built = self._sb_native_flat_caps(whole, roles, slotset)
        if built is None:
            return None
        try:
            caps, fixed = built
            for item in caps.values():
                if not lead <= item['span'][0] or item['span'][1] > lead + len(body):
                    return None

            def dump(v):
                return json.dumps(v, sort_keys=True, ensure_ascii=False, allow_nan=False)
            if dump(rec['capture_spans']) != dump(caps) or dump(rec['fixed_spans']) != dump(fixed):
                return None
            key = json.dumps(meaning, sort_keys=True, ensure_ascii=False)
            detached = json.loads(json.dumps(meaning, ensure_ascii=False))
            if (type(detached) is not dict or rec['meaning_key'] != key
                    or json.dumps(rec['meaning'], sort_keys=True, ensure_ascii=False) != key):
                return None
            if not set(detached) <= {'triple', 'polarity', 'places'}:
                return None
            triple = detached.get('triple')
        except bad:
            return None
        if self._sb_triple(triple) is None:
            return None
        try:
            if 'polarity' in detached and detached['polarity'] is not True:
                return None
            return {'source_ref': copy.deepcopy(resolved['source_ref']), 'compiler_index': ei,
                    'meaning': detached, 'capability_sha256': resolved['capability_sha256']}
        except bad:
            return None

    def _sb_native_flat_record(self, bundle, evidence, meaning):
        # Pure native_flat record: authority comes from the resolver plus an independent binder rebind.
        bad = (TypeError, ValueError, KeyError, AttributeError, IndexError, RecursionError, re.error)

        def canon(v):
            return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                              allow_nan=False)
        try:
            if type(bundle) is not dict or type(meaning) is not dict or type(evidence) is not dict:
                return None
            wired_parts, total = [], 0
            for part in (bundle, evidence, meaning):
                got = self._sb_wire_detach(part, 262144)
                if got is None:
                    return None
                total += got[2]
                if total > 262144:
                    return None
                wired_parts.append(got[1])
            bundle, evidence, meaning = wired_parts
            route = bundle.get('route')
            if type(route) is not dict or route.get('kind') != 'flat':
                return None
            cands = route.get('flat_candidates')
            if type(cands) is not list or len(cands) != 1 or type(cands[0]) is not dict:
                return None
            cand = cands[0]
            trace = cand.get('trace')
            if type(trace) is not dict or canon(cand.get('meaning')) != canon(meaning):
                return None
            if len(trace) != 15 or trace.get('rule') != 'seed-constituents-v2':
                return None
            mkey = json.dumps(meaning, sort_keys=True, ensure_ascii=False)
            got = bundle.get('meanings')
            if type(got) is not dict or set(got) != {mkey} or got[mkey] != meaning:
                return None
            ders = bundle.get('derivations')
            if type(ders) is not dict or set(ders) != {mkey} or canon(ders[mkey]) != canon(trace):
                return None
            tref = trace.get('source_ref')
            if type(tref) is not dict or type(tref.get('index')) is not int or tref['index'] < 0:
                return None
            idx = tref['index']
            matched = bundle.get('matched')
            if (type(matched) is not dict or set(matched) != {mkey}
                    or type(matched[mkey]) is not int or matched[mkey] != idx):
                return None
        except bad:
            return None
        compact = self._sb_compact('positive_fact', idx)
        if compact is None:
            return None
        resolved = self.resolve_selected_binary_authority('positive_fact', idx, compact)
        if type(resolved) is not dict:
            return None
        try:
            if (canon(resolved['source_ref']) != canon(tref)
                    or type(resolved['compiler_index']) is not int
                    or resolved['compiler_index'] != idx
                    or canon(resolved['annotation']) != canon(self.data['examples'][idx])):
                return None
            src, core = trace.get('source'), evidence.get('text')
            if (type(src) is not str or src != bundle.get('source')
                    or type(core) is not str or not core):
                return None
        except bad:
            return None
        bound = self._sb_native_flat_bind(src, idx, resolved)
        if bound is None:
            return None
        try:
            nmeaning, ntrace = bound
            if canon(ntrace) != canon(trace) or canon(nmeaning) != canon(meaning):
                return None
        except bad:
            return None
        split = self._sb_native_flat_core(src)
        try:
            if split is None or split[1] != core:
                return None
            ex = self.data['examples'][idx]
            if type(ex) is not dict or type(ex.get('slots')) is not dict or not ex['slots']:
                return None
            roles = ntrace['roles']
            slotset = set(ex['slots'])
        except bad:
            return None
        built = self._sb_native_flat_caps(src, roles, slotset)
        if built is None:
            return None
        try:
            caps, fixed = built
            rec = {'meaning_key': mkey, 'meaning': copy.deepcopy(meaning), 'example_index': idx,
                   'annotation_sha256': compact['annotation_sha256'], 'canonical': core,
                   'normalization': None, 'source': src, 'capture_spans': caps,
                   'fixed_spans': fixed, 'reader_kind': 'native_flat', 'grammar_scope': None}
        except bad:
            return None
        if self.verify_selected_binary_witness(src, rec, 'positive_fact') is None:
            return None
        return rec

    def _sb_flat_consequent_record(self, bundle, evidence, meaning):
        rec = self._sb_flat_consequent_template_record(bundle, evidence, meaning)
        if rec is not None:
            return rec
        return self._sb_native_flat_record(bundle, evidence, meaning)

    def _sb_flat_consequent_template_record(self, bundle, evidence, meaning):
        """Pure re-derivation of a direct canonical flat positive consequent record, or None.

        Only the actual cached flat selection whose derivation is the exact selected
        seed-constituents-v2 trace, with no normalization, is accepted; every mismatch fails
        closed (proof absent)."""
        try:
            def detach(v, depth, budget):
                if depth > 32:
                    raise ValueError('depth')
                budget[0] += 1
                if budget[0] > 8192:
                    raise ValueError('items')
                if v is None or type(v) is bool or type(v) is int:
                    return v
                if type(v) is float:
                    if v - v != 0:
                        raise ValueError('float')
                    return v
                if isinstance(v, str):
                    return str.encode(v, 'utf-8').decode('utf-8')
                if type(v) is list:
                    return [detach(x, depth + 1, budget) for x in v]
                if type(v) is dict:
                    out = {}
                    for k, x in v.items():
                        if not isinstance(k, str):
                            raise ValueError('key')
                        k2 = str.encode(k, 'utf-8').decode('utf-8')
                        if k2 in out:
                            raise ValueError('key')
                        out[k2] = detach(x, depth + 1, budget)
                    return out
                raise ValueError('type')

            def canon(v):
                return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                                  allow_nan=False)

            bundle = detach(bundle, 0, [0])
            evidence = detach(evidence, 0, [0])
            meaning = detach(meaning, 0, [0])
            if len(canon(bundle).encode('utf-8')) > 262144:
                return None
            if type(bundle) is not dict or type(meaning) is not dict or type(evidence) is not dict:
                return None
            route = bundle.get('route')
            if type(route) is not dict or route.get('kind') != 'flat':
                return None
            cands = route.get('flat_candidates')
            if type(cands) is not list or len(cands) != 1 or type(cands[0]) is not dict:
                return None
            cand = cands[0]
            trace = cand.get('trace')
            if type(trace) is not dict or canon(cand.get('meaning')) != canon(meaning):
                return None
            trace_keys = {'rule', 'source', 'seed_count', 'seed_sha256', 'source_ref', 'frame_id',
                          'declaration_sha256', 'predicate_span', 'roles', 'markers', 'punctuation',
                          'coverage', 'inflection', 'operators', 'scope'}
            if (set(trace) != trace_keys or len(trace) != 15
                    or trace.get('rule') != 'seed-constituents-v2'):
                return None
            mkey = json.dumps(meaning, sort_keys=True, ensure_ascii=False)
            got = bundle.get('meanings')
            if type(got) is not dict or set(got) != {mkey} or got[mkey] != meaning:
                return None
            ders = bundle.get('derivations')
            if type(ders) is not dict or set(ders) != {mkey} or canon(ders[mkey]) != canon(trace):
                return None
            tref = trace.get('source_ref')
            if type(tref) is not dict or type(tref.get('index')) is not int or tref['index'] < 0:
                return None
            idx = tref['index']
            matched = bundle.get('matched')
            if (type(matched) is not dict or set(matched) != {mkey}
                    or type(matched[mkey]) is not int or matched[mkey] != idx):
                return None
            frames = self.data.get('predicate_frames')
            frames = frames.get('frames') if type(frames) is dict else None
            if (type(frames) is not list or idx >= len(frames) or type(frames[idx]) is not dict
                    or canon(frames[idx].get('source_ref')) != canon(tref)):
                return None
            import hashlib
            decl = self.data.get('predicate_frames')
            frame_row = frames[idx]
            dsha = hashlib.sha256(json.dumps(decl, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=False).encode()).hexdigest()
            if (type(frame_row.get('id')) is not str or trace.get('frame_id') != frame_row['id']
                    or trace.get('declaration_sha256') != dsha
                    or canon(trace.get('seed_count')) != canon(decl.get('seed_count'))
                    or canon(trace.get('seed_sha256')) != canon(decl.get('seed_sha256'))):
                return None
            compact = self._sb_compact('positive_fact', idx)
            if compact is None:
                return None
            resolved = self.resolve_selected_binary_authority('positive_fact', idx, compact)
            if (resolved is None or canon(resolved['source_ref']) != canon(tref)
                    or type(resolved['compiler_index']) is not int
                    or resolved['compiler_index'] != idx
                    or canon(resolved['annotation']) != canon(self.data['examples'][idx])):
                return None
            src = trace.get('source')
            core = evidence.get('text')
            if type(src) is not str or type(core) is not str or not core:
                return None
            marks = set()
            declared = self.data.get('predicate_frames')
            for mk in (list(declared.get('terminators') or []) if type(declared) is dict else []):
                if type(mk) is str and len(mk) == 1 and not mk.isspace():
                    marks.add(mk)
            for mk in self.clause_grammar.get('question_marks', []):
                if type(mk) is str and len(mk) == 1 and not mk.isspace():
                    marks.add(mk)
            lead = len(src) - len(src.lstrip())
            body = src.strip()
            if body and body[-1] in marks:
                body = body[:-1]
            if body != core:
                return None
            examples = self.data.get('examples')
            if type(examples) is not list or idx >= len(examples):
                return None
            ex = examples[idx]
            if type(ex) is not dict or type(ex.get('slots')) is not dict or not ex['slots']:
                return None
            slotnames = set(ex['slots'])
            patterns, tmeaning = self.compile(copy.deepcopy(ex), self.data.get('numerals', {}),
                                              self.slot_particles,
                                              ignore_case=bool(self.data.get('ignore_case')),
                                              counters=self.counters, pointers=self.pointers)
            if type(tmeaning) is not dict or tmeaning != ex.get('meaning'):
                return None
            bindings = set()
            for pattern in patterns:
                match = pattern.fullmatch(core)
                if match is None:
                    continue
                gd = match.groupdict()
                if slotnames - set(gd) or any(gd.get(n) is None for n in slotnames):
                    continue
                bindings.add(tuple(sorted((n, match.span(n)) for n in slotnames)))
            if len(bindings) != 1:
                return None
            binding = dict(next(iter(bindings)))
            caps = {}
            for name, (a, b) in binding.items():
                if not 0 <= a < b <= len(core):
                    return None
                caps[name] = {'value': core[a:b], 'span': [a + lead, b + lead]}
            if src != bundle.get('source'):
                return None
            tscope = trace.get('scope')
            if (type(tscope) is not list or len(tscope) != 2
                    or not all(type(x) is int for x in tscope) or tscope != [0, len(src)]):
                return None
            tinfl = trace.get('inflection')
            if tinfl is not None and type(tinfl) is not dict:
                return None
            roles = trace.get('roles')
            if type(roles) is not dict or set(roles) != slotnames:
                return None
            for name, item in caps.items():
                role = roles[name]
                if (type(role) is not dict or set(role) != {'value', 'span'}
                        or type(role['value']) is not str or role['value'] != item['value']
                        or type(role['span']) is not list or len(role['span']) != 2
                        or not all(type(x) is int for x in role['span'])
                        or role['span'] != item['span']):
                    return None
            fixed, at = [], 0
            for lo, hi in sorted(item['span'] for item in caps.values()):
                if lo > at:
                    fixed.append([at, lo])
                at = max(at, hi)
            if at < len(src):
                fixed.append([at, len(src)])
            rec = {'meaning_key': mkey, 'meaning': copy.deepcopy(meaning), 'example_index': idx,
                   'annotation_sha256': compact['annotation_sha256'], 'canonical': core,
                   'normalization': None, 'source': src, 'capture_spans': caps,
                   'fixed_spans': fixed, 'reader_kind': 'template', 'grammar_scope': None}
            if self.verify_selected_binary_witness(src, rec, 'positive_fact') is None:
                return None
            return rec
        except (TypeError, ValueError, KeyError, AttributeError, IndexError, RecursionError, re.error):
            return None

    def _sb_compact(self, kind, index):
        caps = self.data.get('semantic_capabilities')
        if type(caps) is not dict:
            return None
        cap = caps.get('negative_binary' if kind in ('negative_fact', 'negative_query') else 'conditional_binary')
        if type(cap) is not dict:
            return None
        basis = cap.get('basis')
        if kind == 'negative_query':
            refs = cap.get('query_refs')
        else:
            refs = basis.get('frame_refs') if type(basis) is dict else None
        if type(refs) is not list:
            return None
        found = [r for r in refs if type(r) is dict and type(r.get('index')) is int and r['index'] == index]
        return found[0] if len(found) == 1 else None

    def resolve_selected_binary_authority(self, kind, compiler_index, compact_ref):
        """Foundation authority lookup (not semantic proof): detached full source ref or None.

        A matching hash alone does not prove where a source came from; the full-source projection
        is authenticated outside this pure helper."""
        canon, sha = self._sb_canon, self._sb_sha
        isindex, ishash, isref = self._sb_isindex, self._sb_ishash, self._sb_iscompact
        table = {'negative_fact': ('negative_binary', False), 'negative_query': ('negative_binary', True),
                 'positive_guard': ('conditional_binary', False),
                 'positive_fact': ('conditional_binary', False)}
        if (type(kind) is not str or kind not in table or not isindex(compiler_index)
                or not isref(compact_ref) or compact_ref['index'] != compiler_index):
            return None
        name, is_query = table[kind]
        schemas = {'negative_binary': ('selected-negative-binary-v1', 'selected-negative-binary-basis-v1'),
                   'conditional_binary': ('selected-conditional-binary-v1',
                                          'selected-conditional-binary-basis-v1')}[name]
        caps = self.data.get('semantic_capabilities')
        allowed = {'negative_binary', 'conditional_binary'}
        if (type(caps) is not dict or caps.get('schema') != 'selected-binary-semantic-capabilities-v1'
                or set(caps) - allowed - {'schema'} or not set(caps) & allowed):
            return None
        cap = caps.get(name)
        if (type(cap) is not dict or set(cap) != {'schema', 'basis', 'capability_sha256', 'query_refs'}
                or cap['schema'] != schemas[0]):
            return None
        basis = cap['basis']
        if (type(basis) is not dict
                or set(basis) != {'schema', 'grammar_reference', 'frame_refs', 'original_query_refs',
                                  'normalized_language_scope_sha256'}
                or basis['schema'] != schemas[1]):
            return None
        grammar = basis['grammar_reference']
        frame_refs, originals, derived = basis['frame_refs'], basis['original_query_refs'], cap['query_refs']
        if (type(grammar) is not dict or set(grammar) != {'member_path', 'schema', 'sha256'}
                or grammar['schema'] != 'selected-scoped-grammar-v2'
                or not self._sb_safe_path(grammar['member_path']) or not ishash(grammar['sha256'])
                or not ishash(cap['capability_sha256']) or sha(basis) != cap['capability_sha256']
                or not ishash(basis['normalized_language_scope_sha256'])
                or basis['normalized_language_scope_sha256'] != self._authority_scope_sha256()):
            return None
        for refs, low, high in ((frame_refs, 1, 16), (originals, 0, 2), (derived, 0, 2)):
            if (type(refs) is not list or not low <= len(refs) <= high
                    or not all(isref(r) for r in refs) or len({r['index'] for r in refs}) != len(refs)):
                return None
        if name == 'conditional_binary' and (originals or derived):
            return None
        if name == 'negative_binary' and len(originals) != len(derived):
            return None
        if compact_ref not in (derived if is_query else frame_refs):
            return None
        examples = self.data.get('examples')
        if type(examples) is not list or compiler_index >= len(examples):
            return None
        annotation_sha = sha(examples[compiler_index])
        if annotation_sha is None or annotation_sha != compact_ref['annotation_sha256']:
            return None
        plain = {'index', 'annotation_sha256', 'graph_source'}
        if not is_query:
            frames = self.data.get('predicate_frames')
            frames = frames.get('frames') if type(frames) is dict else None
            if (type(frames) is not list or compiler_index >= len(frames)
                    or type(frames[compiler_index]) is not dict):
                return None
            full = frames[compiler_index].get('source_ref')
            size = self._sb_bytes(full)
            if (type(full) is not dict or set(full) != plain or size is None or len(size) > 65536
                    or type(full['index']) is not int or full['index'] != compiler_index
                    or not ishash(full['annotation_sha256']) or full['annotation_sha256'] != annotation_sha
                    or type(full['graph_source']) is not dict):
                return None
        else:
            registry = self.data.get('semantic_query_sources')
            if (type(registry) is not list or not registry or len(registry) > 4
                    or len(registry) != len(originals) + len(derived)):
                return None
            full, total, seen, matched = None, 0, set(), []
            for entry in registry:
                if type(entry) is not dict or set(entry) not in (plain, plain | {'negative_derivation'}):
                    return None
                size = self._sb_bytes(entry)
                if size is None or len(size) > 65536:
                    return None
                total += len(size)
                idx = entry['index']
                if (not isindex(idx) or idx in seen or idx >= len(examples)
                        or not ishash(entry['annotation_sha256']) or type(entry['graph_source']) is not dict
                        or sha(examples[idx]) != entry['annotation_sha256']):
                    return None
                seen.add(idx)
                ref = {'index': idx, 'annotation_sha256': entry['annotation_sha256'],
                       'source_ref_sha256': sha(entry)}
                if 'negative_derivation' in entry:
                    d = entry['negative_derivation']
                    if (type(d) is not dict
                            or set(d) != {'original_query_ref', 'grammar_reference', 'capability_sha256'}
                            or d['capability_sha256'] != cap['capability_sha256']
                            or d['grammar_reference'] != grammar or d['original_query_ref'] not in originals
                            or ref not in derived):
                        return None
                elif ref not in originals:
                    return None
                matched.append(canon(ref))
                if ref == compact_ref:
                    full = entry
            if (total > 262144 or full is None or 'negative_derivation' not in full
                    or sorted(matched) != sorted(canon(r) for r in originals + derived)):
                return None
        if sha(full) != compact_ref['source_ref_sha256']:
            return None
        return {'source_ref': copy.deepcopy(full), 'compiler_index': compiler_index,
                'annotation': copy.deepcopy(examples[compiler_index]),
                'capability_sha256': cap['capability_sha256']}

    def verify_selected_binary_witness(self, clause_source, rec, kind):
        """Pure re-derivation of one selected-example record from its clause source.

        Returns a detached {source_ref, compiler_index, meaning, capability_sha256} or None."""
        from marco.language.hangul import inflect
        from marco.language.numerals import parse_numeral
        keys = {'meaning_key', 'meaning', 'example_index', 'annotation_sha256', 'canonical', 'normalization',
                'source', 'capture_spans', 'fixed_spans', 'reader_kind', 'grammar_scope'}
        if (type(kind) is not str or kind not in ('negative_fact', 'negative_query', 'positive_guard', 'positive_fact')
                or type(clause_source) is not str or not clause_source or len(clause_source) > 65536
                or type(rec) is not dict or set(rec) != keys):
            return None
        native = False
        try:
            kind_back = rec['reader_kind']
            if isinstance(kind_back, str):
                native = str.encode(kind_back, 'utf-8').decode('utf-8') == 'native_flat'
        except (UnicodeError, KeyError, TypeError):
            native = False
        if native:
            wired_rec = self._sb_wire_detach(rec, 65536)
            if wired_rec is None or type(wired_rec[1]) is not dict or set(wired_rec[1]) != keys:
                return None
            rec = wired_rec[1]
        size = self._sb_bytes(rec)
        if size is None or len(size) > 65536:
            return None
        ei, canonical, norm = rec['example_index'], rec['canonical'], rec['normalization']
        examples = self.data.get('examples')
        if (not self._sb_isindex(ei) or type(examples) is not list or ei >= len(examples)
                or rec['source'] != clause_source
                or type(canonical) is not str or not canonical):
            return None
        compact = self._sb_compact(kind, ei)
        if compact is None:
            return None
        resolved = self.resolve_selected_binary_authority(kind, ei, compact)
        if resolved is None or rec['annotation_sha256'] != compact['annotation_sha256']:
            return None
        if native:
            return self._sb_verify_native_flat(clause_source, rec, kind, ei, resolved)
        ex = examples[ei]
        if type(ex) is not dict or type(ex.get('slots')) is not dict or type(ex.get('meaning')) is not dict:
            return None
        slotnames = set(ex['slots'])
        if type(self.data) is not dict:
            return None
        numerals_cfg = self.data.get('numerals', {})
        if (type(numerals_cfg) is not dict or numerals_cfg
                or type(self.counters) is not dict or self.counters
                or type(self.pointers) is not list or self.pointers
                or type(self.holder_forms) is not dict or self.holder_forms
                or type(self.noun_number) is not dict or self.noun_number
                or type(self.actor_targets) is not dict or self.actor_targets
                or type(self.slot_particles) is not list or self.slot_particles
                or type(self.case_particles) is not list or self.case_particles):
            return None
        retained = self.language_pack
        if type(retained) is not dict:
            return None
        for copy_key, empty_type in (('slot_particles', list), ('case_particles', list),
                                     ('pointers', list), ('counters', dict),
                                     ('noun_number', dict), ('actor_targets', dict),
                                     ('holder_forms', dict)):
            held = retained.get(copy_key, empty_type())
            if type(held) is not empty_type or held:
                return None
        fold_case = self.data.get('ignore_case', False)
        if type(fold_case) is not bool:
            return None
        if not {'text', 'slots', 'meaning'} <= set(ex) <= {'text', 'slots', 'meaning', 'inflection'}:
            return None
        ex_bytes = self._sb_bytes(ex)
        if ex_bytes is None or len(ex_bytes) > 65536:
            return None
        ex_text = ex['text']
        if (type(ex_text) is not str or not ex_text.strip() or len(ex_text) > 512
                or len(ex_text.split()) > 40):
            return None
        if len(ex['slots']) != (1 if kind == 'negative_query' else 2):
            return None
        for slot_name, seed in ex['slots'].items():
            if (type(slot_name) is not str or not 1 <= len(slot_name) <= 64
                    or re.fullmatch(r'[a-z][a-z0-9_]*', slot_name) is None
                    or type(seed) is not str or not seed or seed != seed.strip()
                    or len(seed) > 128 or seed.isdecimal() or ex_text.count(seed) != 1):
                return None
        if len(set(ex['slots'].values())) != len(ex['slots']):
            return None
        try:
            patterns, tmeaning = self.compile(copy.deepcopy(ex), self.data.get('numerals', {}),
                                              self.slot_particles,
                                              ignore_case=bool(self.data.get('ignore_case')),
                                              counters=self.counters, pointers=self.pointers)
        except (ValueError, re.error):
            return None
        if type(tmeaning) is not dict or tmeaning != ex['meaning']:
            return None
        infl = self.inflection_grammar
        if type(infl) is not dict or not infl:
            return None
        lists = []
        for key in ('parsing_endings', 'condition_endings', 'boundary_endings', 'question_endings'):
            value = infl.get(key, [])
            if type(value) is not list or not all(type(x) is str for x in value):
                return None
            lists.append(value)
        parsing, cond, bound, qend = lists
        asking = set(self._asking(infl))
        assertive = [e for e in parsing if e not in cond and e not in bound and e not in asking]
        qmarks = {m for m in self.clause_grammar.get('question_marks', [])
                  if type(m) is str and len(m) == 1 and not m.isspace()}
        declared = self.data.get('predicate_frames')
        terminals = declared.get('terminators', []) if type(declared) is dict else []
        marks = qmarks | {m for m in (terminals if type(terminals) is list else [])
                          if type(m) is str and len(m) == 1 and not m.isspace()}
        whole = clause_source
        start = len(whole) - len(whole.lstrip())
        body = whole.strip()
        stripped = asked = False
        if body and body[-1] in marks:
            stripped, asked = True, body[-1] in qmarks
            body = body[:-1]
        if kind == 'negative_query':
            if stripped and not asked:
                return None
        elif asked:
            return None

        def frame_allows(ending):
            frames = declared.get('frames') if type(declared) is dict else None
            frame = frames[ei] if type(frames) is list and ei < len(frames) else None
            allowed = frame.get('allowed_endings') if type(frame) is dict else None
            return type(allowed) is list and ending in allowed

        tmean = ex['meaning']
        limit, ending, trace = None, None, None
        if kind == 'negative_fact':
            neg = self.language_pack.get('negation')
            ann = ex.get('inflection')
            if (type(neg) is not dict or set(neg) != {'연결', '어간', '갈래'}
                    or not all(type(x) is str for x in neg.values()) or not neg['어간']
                    or type(ann) is not dict
                    or not all(type(ann.get(k)) is str for k in ('stem', 'tense', 'ending', 'kind'))):
                return None
            if (type(norm) is not dict or set(norm) != {'id', 'canonical', 'example_index', 'polarity'}
                    or norm['id'] != 'declared-negation-v1' or norm['canonical'] != canonical
                    or type(norm['example_index']) is not int or norm['example_index'] != ei
                    or norm['polarity'] is not False):
                return None
            if (type(tmean.get('triple')) is not list
                    or any(k in tmean for k in ('query', 'define', 'invoke', 'triples', 'condition', 'plan'))
                    or tmean.get('polarity') is False or tmean.get('modality', 'asserted') != 'asserted'):
                return None
            if ann['tense'] != 'present' or ann['ending'] not in assertive:
                return None
            try:
                forms = inflect(ann['stem'], 'present', ann['ending'], infl, kind=ann['kind'])
            except ValueError:
                return None
            text = ex.get('text')
            if type(text) is not str:
                return None
            slot_end = max((text.index(v) + len(v) for v in ex['slots'].values()), default=0)
            tails = {f['text'] for f in forms
                     if text.endswith(f['text']) and len(text) - len(f['text']) >= slot_end}
            if len(tails) != 1:
                return None
            tail = next(iter(tails))
            if not canonical.endswith(tail):
                return None
            prefix = canonical[:len(canonical) - len(tail)]
            auxes = set()
            for tense in infl.get('tenses', {}):
                for aux_ending in assertive:
                    try:
                        made = inflect(neg['어간'], tense, aux_ending, infl, kind=neg['갈래'])
                    except ValueError:
                        continue
                    auxes |= {f['text'] for f in made}
            if body not in {prefix + ann['stem'] + neg['연결'] + ' ' + a for a in auxes}:
                return None
            limit = len(prefix)
        elif norm is None:
            if kind not in ('negative_query', 'positive_fact') or body != canonical:
                return None
            if kind == 'positive_fact':
                ann = ex.get('inflection')
                if type(ann) is not dict or ann.get('ending') not in assertive:
                    return None
            limit = len(canonical)
        else:
            if (type(norm) is not dict
                    or set(norm) != {'id', 'stem', 'tense', 'ending', 'operations', 'example_index'}
                    or type(norm['example_index']) is not int or norm['example_index'] != ei):
                return None
            core = {k: v for k, v in norm.items() if k != 'example_index'}
            try:
                found = [t for t in self._inflected_examples(ex) if t[2] == core]
            except ValueError:
                return None
            if len(found) != 1:
                return None
            typed, tail, trace = found[0]
            if not canonical.endswith(tail):
                return None
            prefix = canonical[:len(canonical) - len(tail)]
            if body != prefix + typed:
                return None
            limit, ending = len(prefix), trace['ending']
            if kind == 'negative_query':
                good = ending in qend
            elif kind == 'positive_guard':
                good = ending in cond and frame_allows(ending)
            else:
                good = ending in assertive and frame_allows(ending)
            if not good:
                return None
        if kind == 'positive_guard' and trace is None:
            return None
        want_reader = {'negative_query': 'query', 'positive_guard': 'guard'}.get(kind, 'template')
        scope = rec['grammar_scope']
        if kind == 'positive_guard':
            if (type(scope) is not dict or set(scope) != {'kind', 'ending', 'scope', 'rule_id'}
                    or scope['kind'] != 'guard' or scope['ending'] != ending
                    or scope['rule_id'] != trace['id'] or type(scope['scope']) is not list
                    or len(scope['scope']) != 2 or not all(type(x) is int for x in scope['scope'])
                    or scope['scope'] != [0, len(whole)]):
                return None
        elif scope is not None:
            return None
        if rec['reader_kind'] != want_reader:
            return None
        given = rec['capture_spans']
        if type(given) is not dict or set(given) != slotnames or not slotnames:
            return None
        spans = {}
        for name, item in given.items():
            if type(item) is not dict or set(item) != {'value', 'span'}:
                return None
            sp = item['span']
            if (type(sp) is not list or len(sp) != 2 or not all(type(x) is int for x in sp)
                    or not start <= sp[0] < sp[1] <= start + limit or type(item['value']) is not str
                    or whole[sp[0]:sp[1]] != item['value']):
                return None
            spans[name] = (sp[0] - start, sp[1] - start)
        ordered = sorted(spans.values())
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            return None
        chosen = None
        for pattern in patterns:
            match = pattern.fullmatch(canonical)
            if match is None or slotnames - set(match.groupdict()):
                continue
            if all(match.span(n) == spans[n] for n in slotnames):
                chosen = match
                break
        if chosen is None:
            return None
        fixed, at = [], 0
        for lo, hi in sorted(item['span'] for item in given.values()):
            if lo > at:
                fixed.append([at, lo])
            at = max(at, hi)
        if at < len(whole):
            fixed.append([at, len(whole)])
        shown = rec['fixed_spans']
        if (type(shown) is not list or len(shown) != len(fixed)
                or not all(type(s) is list and len(s) == 2 and all(type(x) is int for x in s) for s in shown)
                or shown != fixed):
            return None
        raw = chosen.groupdict()
        if any(raw.get(n) is None for n in slotnames):
            return None
        live = copy.deepcopy(ex)
        slots = self._holder_slot_forms(dict(raw), copy.deepcopy(tmeaning))
        for name, annotated in live['slots'].items():
            if type(annotated) is str and annotated.isdecimal():
                typed = slots[name].lower() if self.data.get('ignore_case') else slots[name]
                slots[name] = parse_numeral(typed, self.data.get('numerals', {}))
        if any(value is None for value in slots.values()):
            return None
        slots = self._number_agreement(slots, live)
        grounded = self._grounded(copy.deepcopy(tmeaning), slots, copy.deepcopy(norm), live)
        try:
            key = json.dumps(grounded, sort_keys=True, ensure_ascii=False)
            detached = json.loads(json.dumps(grounded, ensure_ascii=False))
            shown_key = json.dumps(rec['meaning'], sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            return None
        if type(detached) is not dict or rec['meaning_key'] != key or shown_key != key:
            return None
        if kind == 'negative_query':
            rows = detached.get('query') if set(detached) == {'query'} else None
            if (type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict
                    or not set(rows[0]) <= {'triple', 'render', 'polarity'}
                    or rows[0].get('polarity') is not False
                    or self._sb_triple(rows[0].get('triple')) is None):
                return None
        else:
            if not set(detached) <= {'triple', 'polarity', 'places'} or self._sb_triple(detached.get('triple')) is None:
                return None
            if kind == 'negative_fact':
                if detached.get('polarity') is not False:
                    return None
            elif 'polarity' in detached and detached['polarity'] is not True:
                return None
        return {'source_ref': copy.deepcopy(resolved['source_ref']), 'compiler_index': ei,
                'meaning': detached, 'capability_sha256': resolved['capability_sha256']}

    def verify_selected_binary_certificate(self, source, cert):
        """Pure check of one source certificate against the installed selected authority.

        Returns a detached {kind, triple, polarity, compiler_index, source_ref} or None."""
        import hashlib
        keys = {'schema', 'kind', 'capability_sha256', 'source_sha256', 'source_span', 'compiler_index',
                'source_ref', 'witness', 'meaning'}
        if (type(source) is not str or not source or len(source) > 262144 or type(cert) is not dict
                or set(cert) != keys or cert['schema'] != 'selected-binary-source-certificate-v1'
                or type(cert['kind']) is not str
                or cert['kind'] not in ('negative_fact', 'negative_query', 'positive_guard')):
            return None
        size = self._sb_bytes(cert)
        if size is None or len(size) > 65536:
            return None
        try:
            digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        except UnicodeEncodeError:
            return None
        kind, span, index, ref = cert['kind'], cert['source_span'], cert['compiler_index'], cert['source_ref']
        if (not self._sb_ishash(cert['capability_sha256']) or cert['source_sha256'] != digest
                or type(span) is not list or len(span) != 2 or not all(type(x) is int for x in span)
                or not 0 <= span[0] < span[1] <= len(source) or not self._sb_isindex(index)
                or not self._sb_iscompact(ref) or ref['index'] != index
                or type(cert['witness']) is not dict or type(cert['meaning']) is not dict):
            return None
        resolved = self.resolve_selected_binary_authority(kind, index, ref)
        if resolved is None or resolved['capability_sha256'] != cert['capability_sha256']:
            return None
        witness = self.verify_selected_binary_witness(source[span[0]:span[1]], cert['witness'], kind)
        if (witness is None or witness['compiler_index'] != index
                or witness['capability_sha256'] != cert['capability_sha256']
                or self._sb_canon(witness['source_ref']) != self._sb_canon(resolved['source_ref'])
                or self._sb_sha(witness['source_ref']) != ref['source_ref_sha256']
                or self._sb_canon(cert['meaning']) != self._sb_canon(witness['meaning'])):
            return None
        meaning = witness['meaning']
        row = meaning['query'][0] if kind == 'negative_query' else meaning
        triple = self._sb_triple(row['triple'])
        if triple is None:
            return None
        return {'kind': kind, 'triple': triple, 'polarity': kind == 'positive_guard',
                'compiler_index': index, 'source_ref': copy.deepcopy(resolved['source_ref'])}

    def _clause_candidates(self, literal):
        """Every (candidate, normalization) of ``literal`` (memoized, see ``_rebuild_inflections``)."""
        found = self._candidate_memo.get(literal)
        if found is None:
            found = self._candidate_memo[literal] = list(self._all_clause_candidates(literal))
        return iter(found)

    def _all_clause_candidates(self, literal):
        yield from self._clause_candidates_of(literal)
        for replaced, notes in self._variant_literals(literal):
            for candidate, normalization in self._clause_candidates_of(replaced):
                base = normalization or {"id": notes[0]["id"], "canonical": candidate, "words_only": True}
                yield candidate, {**base, "variants": notes}

    @staticmethod
    def _sb_plain(text):
        if not isinstance(text, str):
            return None
        try:
            return text.encode('utf-8').decode('utf-8')
        except UnicodeError:
            return None

    def _scoped_negative_state(self):
        """(entries, auxes, connector) for the installed negative capability, or None (fail closed)."""
        from marco.language.hangul import inflect
        caps = self.data.get('semantic_capabilities')
        cap = caps.get('negative_binary') if type(caps) is dict else None
        basis = cap.get('basis') if type(cap) is dict else None
        refs = basis.get('frame_refs') if type(basis) is dict else None
        infl, neg = self.inflection_grammar, self.language_pack.get('negation')
        if (type(refs) is not list or type(infl) is not dict or not infl or type(neg) is not dict
                or set(neg) != {'연결', '어간', '갈래'} or not all(type(x) is str for x in neg.values())
                or not neg['어간']):
            return None
        lists = []
        for key in ('parsing_endings', 'condition_endings', 'boundary_endings', 'question_endings'):
            value = infl.get(key, [])
            if type(value) is not list or not all(type(x) is str for x in value):
                return None
            lists.append(value)
        parsing, cond, bound, _qend = lists
        asking = set(self._asking(infl))
        assertive = [e for e in parsing if e not in cond and e not in bound and e not in asking]
        auxes = set()
        for tense in infl.get('tenses', {}):
            for aux_ending in assertive:
                try:
                    made = inflect(neg['어간'], tense, aux_ending, infl, kind=neg['갈래'])
                except ValueError:
                    continue
                auxes |= {f['text'] for f in made}
        entries = []
        for ref in refs:
            if not self._sb_iscompact(ref):
                return None
            idx = ref['index']
            if self.resolve_selected_binary_authority('negative_fact', idx, ref) is None:
                return None
            ex = self.data['examples'][idx]
            ann, mean, slots, text = (ex.get('inflection'), ex.get('meaning'), ex.get('slots'),
                                      ex.get('text'))
            if (type(ann) is not dict or type(mean) is not dict or type(slots) is not dict
                    or type(text) is not str
                    or not all(type(ann.get(k)) is str for k in ('stem', 'tense', 'ending', 'kind'))
                    or not ann['stem'] or type(mean.get('triple')) is not list
                    or any(k in mean for k in ('query', 'define', 'invoke', 'triples', 'condition', 'plan'))
                    or mean.get('polarity') is False or mean.get('modality', 'asserted') != 'asserted'
                    or ann['tense'] != 'present' or ann['ending'] not in assertive):
                continue
            try:
                forms = inflect(ann['stem'], 'present', ann['ending'], infl, kind=ann['kind'])
                slot_end = max((text.index(v) + len(v) for v in slots.values()), default=0)
            except (ValueError, TypeError):
                continue
            tails = {f['text'] for f in forms
                     if text.endswith(f['text']) and len(text) - len(f['text']) >= slot_end}
            if len(tails) != 1:
                continue
            entries.append((idx, ann['stem'], next(iter(tails))))
        return entries, auxes, neg['연결']

    def _scoped_negative_candidates(self, literal):
        state = self._scoped_negative_state()
        if state is None or not isinstance(literal, str):
            return
        plain = self._sb_plain(literal)
        if plain is None or type(plain) is not str:
            return
        literal = plain
        entries, auxes, connector = state
        qmarks = [m for m in self.clause_grammar.get('question_marks', []) if type(m) is str and m]
        body = literal.strip()
        if not body or any(m in body for m in qmarks):
            return
        for idx, stem, tail in entries:
            for aux in sorted(auxes):
                suffix = stem + connector + ' ' + aux
                if not literal.endswith(suffix):
                    continue
                candidate = literal[:len(literal) - len(suffix)] + tail
                yield candidate, {'id': 'declared-negation-v1', 'canonical': candidate,
                                  'example_index': idx, 'polarity': False}

    def _scoped_negative_record(self, example, index, match, candidate, normalization, grounded, source):
        """Produce and verify the 11-key original-source witness of a scoped negative fact, or None."""
        whole = self._sb_plain(source)
        state = self._scoped_negative_state()
        if whole is None or not whole or state is None or not isinstance(normalization, dict):
            return None
        found = [e for e in state[0] if e[0] == index]
        if len(found) != 1:
            return None
        _, stem, tail = found[0]
        if not candidate.endswith(tail):
            return None
        prefix = candidate[:len(candidate) - len(tail)]
        marks = set()
        for mark in (list((self.data.get('predicate_frames') or {}).get('terminators') or [])
                     + list((self.clause_grammar or {}).get('question_marks') or [])):
            if isinstance(mark, str) and len(mark) == 1 and not mark.isspace():
                marks.add(mark)
        start = len(whole) - len(whole.lstrip())
        body = whole.strip()
        if body and body[-1] in marks:
            body = body[:-1]
        limit = len(prefix)
        if not body.startswith(prefix) or body[limit:] not in {stem + state[2] + ' ' + a for a in state[1]}:
            return None
        spans = {name: match.span(name) for name in example['slots']}
        ordered = sorted(spans.values())
        if not (all(0 <= lo <= hi <= limit for lo, hi in ordered)
                and all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:]))):
            return None
        captures = {name: {'value': whole[start + lo:start + hi], 'span': [start + lo, start + hi]}
                    for name, (lo, hi) in spans.items()}
        fixed, at = [], 0
        for lo, hi in sorted(item['span'] for item in captures.values()):
            if lo > at:
                fixed.append([at, lo])
            at = max(at, hi)
        if at < len(whole):
            fixed.append([at, len(whole)])
        try:
            key = json.dumps(grounded, sort_keys=True, ensure_ascii=False)
            detached = json.loads(json.dumps(grounded, ensure_ascii=False))
            norm = json.loads(json.dumps(normalization, ensure_ascii=False))
        except (TypeError, ValueError):
            return None
        digest = self._sb_sha(example)
        if digest is None:
            return None
        rec = {'meaning_key': key, 'meaning': detached, 'example_index': index,
               'annotation_sha256': digest, 'canonical': candidate, 'normalization': norm,
               'source': whole, 'capture_spans': captures, 'fixed_spans': fixed,
               'reader_kind': 'template', 'grammar_scope': None}
        got = self.verify_selected_binary_witness(whole, rec, 'negative_fact')
        if got is None or got['compiler_index'] != index:
            return None
        try:
            if json.dumps(got['meaning'], sort_keys=True, ensure_ascii=False) != key:
                return None
        except (TypeError, ValueError):
            return None
        return rec

    def make_selected_binary_certificate(self, source, source_span, witness, kind):
        """Detached 9-key source certificate, or None unless the pure verifier accepts it."""
        if type(kind) is not str or kind not in ('negative_fact', 'negative_query', 'positive_guard'):
            return None
        text = self._sb_plain(source)
        if text is None or not text or len(text) > 262144:
            return None
        if (type(source_span) not in (list, tuple) or len(source_span) != 2
                or not all(type(x) is int for x in source_span)):
            return None
        lo, hi = source_span
        if not 0 <= lo < hi <= len(text) or type(witness) is not dict:
            return None
        if type(witness.get('source')) is not str or witness['source'] != text[lo:hi]:
            return None
        verified = self.verify_selected_binary_witness(text[lo:hi], witness, kind)
        if verified is None:
            return None
        index = verified['compiler_index']
        compact = self._sb_compact(kind, index)
        if compact is None:
            return None
        resolved = self.resolve_selected_binary_authority(kind, index, compact)
        if (resolved is None or resolved['capability_sha256'] != verified['capability_sha256']
                or self._sb_sha(resolved['source_ref']) != compact['source_ref_sha256']):
            return None
        import hashlib
        try:
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        except UnicodeEncodeError:
            return None
        cert = {'schema': 'selected-binary-source-certificate-v1', 'kind': kind,
                'capability_sha256': resolved['capability_sha256'], 'source_sha256': digest,
                'source_span': [lo, hi], 'compiler_index': index,
                'source_ref': copy.deepcopy(compact), 'witness': copy.deepcopy(witness),
                'meaning': copy.deepcopy(witness['meaning'])}
        size = self._sb_bytes(cert)
        if size is None or len(size) > 65536:
            return None
        if self.verify_selected_binary_certificate(text, cert) is None:
            return None
        return cert

    def _clause_candidates_of(self, literal):
        from marco.language.hangul import canonical_clauses
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
        if "semantic_capabilities" in self.data:
            # Opt-in scoped negative: only authenticated selected facts; never the legacy inference.
            yield from self._scoped_negative_candidates(literal)
            return
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
        from marco.language.hangul import inflect
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
        from marco.language.numerals import parse_numeral
        declared = (self.repair or {}).get("protected", {})
        core = str(word).strip(".,!?\"'")
        folded = core.lower()
        if any(_compiled(pattern).search(folded) for pattern in declared.get("negation", [])):
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
        if _compiled(r"\d").search(core) or parse_numeral(folded, numerals) is not None \
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
                if any(_compiled(r"\d+(%s)\S*" % "|".join(map(re.escape, units))).fullmatch(word) for word in words
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
                    if kind in ("numeral", "counter") and not _compiled(r"\d").search(word):
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
        from marco.reasoning.inference import leading_word_referent
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
        from marco.reasoning.inference import leading_word_referent
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
        from marco.language.hangul import batchim
        if not isinstance(subject, str) or not subject.strip():
            return subject
        words = subject.split(" ")
        # ``내 사탕``: the speaker's own thing (가진쪽꼴.self_singular_possessives before a word that is no relation noun)
        forms = self.holder_forms or {}
        if (len(words) >= 2 and words[0] in (forms.get("self_singular_possessives") or [])
                and words[1] not in (forms.get("relation_nouns") or []) and self.speaker_placeholder):
            words[0] = self.speaker_placeholder
            subject = " ".join(words)
        suffix = self.name_suffix
        if not suffix:
            return subject
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
        from marco.language.hangul import batchim
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
        from marco.language.hangul import batchim
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
                parts = {"holder": " ".join(carried), "thing": subject}
            else:
                carried = before[len(words):]
                rewritten.append([" ".join(words + carried)] + list(row[1:]))
                parts = {"holder": subject, "thing": " ".join(carried)}
            inherited.append({"subject": subject, "inherited": " ".join(carried),
                              "from": match[0], "index": len(rewritten) - 1, "parts": parts})
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
        from marco.language.numerals import parse_numeral
        spec = (self.clause_grammar or {}).get("relative_clauses") or {}
        if not spec or not isinstance(text, str):
            return text
        numerals = self.data.get("numerals", {})
        ignore = bool(self.data.get("ignore_case"))
        fold = (lambda word: word.lower()) if ignore else (lambda word: word)

        def amount(words):
            return any(_compiled(r"\d").search(word) or parse_numeral(fold(word.strip(",.")), numerals) is not None
                       for word in words)
        for pronoun in spec.get("pronouns", []):
            pattern = _compiled(r"(?P<head>[^\s,]+), %s (?P<body>[^,.;!?]+), (?P<rest>[^.;!?]+)"
                                 % re.escape(pronoun), re.IGNORECASE if ignore else 0)
            found = pattern.search(text)
            if found and amount(found.group("body").split()):
                head = found.group("head")
                text = (text[:found.start()] + "%s %s. %s %s" % (head, found.group("body"), head, found.group("rest"))
                        + text[found.end():])
        particles = sorted({p for p in self.case_particles} | {p for group in self.slot_particles for p in group},
                           key=len, reverse=True)
        for row in spec.get("adnominal", []):
            from marco.language.hangul import inflect
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
        from marco.language.numerals import parse_numeral
        if (self.ellipsis or {}).get("gapping") != "first_conjunct_verb":
            return None
        numerals = self.data.get("numerals", {})
        fold = (lambda word: word.lower()) if self.data.get("ignore_case") else (lambda word: word)

        def number_at(words):
            return next((i for i, word in enumerate(words)
                         if _compiled(r"\d+").fullmatch(word) or parse_numeral(fold(word), numerals) is not None), None)
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

    def _inherited_subject(self, literal, previous_text, previous_rows, slot_pair=None):
        """A clause with no actor of its own after a stated count of one named holder
        (``윤재는 단추 여덟 개를 소유하고 있고, 하린에게 단추 세 개를 건네줬어``): the
        clause said again with that holder as its actor (문장분리.subject_continuity).

        Every word of the clause stays; only the holder and its actor particle
        are put before it. Returns the rebuilt clause, or None.
        """
        spec = self.clause_grammar.get("subject_continuity") or {}
        actor = spec.get("actor_particle")
        if not actor or len(previous_rows) != 1 or previous_rows[0][1] not in (spec.get("from_predicates") or []):
            return None
        from marco.language.frames import particle_key, split_particle
        subject_group = particle_key(actor, self.slot_particles)
        # a clause that marks its own actor or topic keeps it
        particles = sorted({p for p in self.case_particles if isinstance(p, str) and p}
                           | {p for group in self.slot_particles for p in group}, key=len, reverse=True)
        for word in literal.split():
            found = split_particle(word, particles, self.slot_particles)
            if found and found[1] == subject_group:
                return None
        if (isinstance(slot_pair, list) and len(slot_pair) == 2
                and all(isinstance(w, str) and w.strip() for w in slot_pair)):
            holder = slot_pair[0].strip()
        else:
            key = previous_rows[0][0]
            parts = self._typed_parts(key, previous_text) if isinstance(key, str) and key.strip() else None
            holder = parts.get("holder") if parts else None
        if not isinstance(holder, str) or not holder.strip():
            return None
        return "%s%s %s" % (holder, self._particle_form(holder, actor), literal)

    def _cased_parts(self, key):
        """The holder of a key in which the holder kept a case particle of the pack (조사) that agrees with the word
        before it (G7-S): as the key's last word, the holder's case with the thing unsaid (기 대표님에게는 열 개 있어
        -> 기 대표에게: holder 기 대표, no thing); inside the key, a place between the holder and the thing (경아는
        승합차에 형광펜을 싣고 있어 -> 경아 승합차에 형광펜: holder 경아, place 승합차, thing 형광펜). ``key`` names the
        key the parts are of. None otherwise, and in a pack without case particles."""
        # only a case particle outside the slot groups (은/는/이/가, 을/를 ...: the reader takes those off, and a
        # noun may end in one: 목걸이, 오이): 에게, 한테, 에 ...
        slots = {p for group in (self.slot_particles or ()) for p in group}
        particles = sorted((p for p in (getattr(self, "case_particles", ()) or ())
                            if isinstance(p, str) and p and p not in slots), key=len, reverse=True)
        words = key.split()
        if not particles or len(words) < 2:
            return None

        def cased(word):
            return next((word[:-len(p)] for p in particles if word.endswith(p) and len(word) > len(p)
                         and self._particle_form(word[:-len(p)], p) == p), None)
        last = cased(words[-1])
        if last is not None:
            return {"holder": " ".join(words[:-1] + [last]), "thing": None, "key": key}
        for at in range(1, len(words) - 1):
            place = cased(words[at])
            if place is not None:
                return {"holder": " ".join(words[:at]), "place": place, "thing": " ".join(words[at + 1:]), "key": key}
        return None

    @staticmethod
    def _typed_parts(key, text):
        """The holder and the thing of a key one slot gave (보늬 연필 from 보늬는 연필이 세 개; 미경 줄무늬 면 수건 from
        미경은 줄무늬 면 수건이), as the words were typed: the key's words are found in the typed words in order; the
        holder ends at the first word typed with something after it (a particle or a title: 보늬는, 과장님은) or
        followed by a typed word that is not the key's next word (우진 씨는; Nora has); what stands between it and
        the end is the thing, every word of it (줄무늬 면 수건: G7-5). None when the typed words do not show it."""
        words = key.split()
        if len(words) < 2:
            return None
        typed = [w.strip(".,!?") for w in str(text).split()]
        at, found = 0, []
        for word in words:
            j = next((j for j in range(at, len(typed)) if typed[j].startswith(word)), None)
            if j is None:
                return None
            found.append(j)
            at = j + 1
        for i in range(len(words) - 1):
            j = found[i]
            if len(typed[j]) > len(words[i]) or found[i + 1] != j + 1:
                return {"holder": " ".join(words[:i + 1]), "thing": " ".join(words[i + 1:])}
        return None

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
            elif subject in typed and self._object_marked_after(typed, typed.index(subject)):
                # a bare word before a count the clause marks as its object (컵 두 개를 가지고 있어): the thing
                # held, not a holder, which the clause would mark as its subject or topic (G7-S)
                out.add(subject)
        return out

    def _object_marked_after(self, typed, at):
        """Whether a word after ``typed[at]`` carries the object particle (the slot group with 을)."""
        group = next((g for g in self.slot_particles if "을" in g or "를" in g), ())
        return any(any(w.endswith(p) and len(w) > len(p) for p in group) for w in typed[at + 1:])

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
        from marco.language.hangul import batchim
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

    def _splits_titled_holder(self, meaning, literal):
        """A reading that names the surname of a surname-and-title holder without the title, or the title
        without the surname (the declared job titles: 변 과장한테 -> 변 and 과장)."""
        titles = sorted((self.holder_forms or {}).get("job_titles") or [], key=len, reverse=True)
        if not titles:
            return False
        words = literal.split()
        particles = {p for group in self.slot_particles for p in group} | set(self.case_particles) | {""}
        honorifics = [h for h in (self.holder_forms or {}).get("name_titles") or [] if isinstance(h, str)]
        def is_title(word, title):
            if not word.startswith(title):
                return False
            rest = word[len(title):]
            rest = next((rest[len(h):] for h in honorifics if h and rest.startswith(h)), rest)
            return rest in particles or any(rest.startswith(p) and rest[len(p):] in particles for p in particles if p)
        pairs = []
        for before, word in zip(words, words[1:]):
            title = next((t for t in titles if is_title(word, t)), None)
            if title is not None and not self._ends_in_particle(before):
                pairs.append((before, title))
        if not pairs:
            return False
        rows = asserted(meaning) or [joined(q["triple"]) for q in meaning.get("query", [])
                                     if isinstance(q, dict) and isinstance(q.get("triple"), list)]
        for row in rows:
            for value in (row[0], row[2]):
                tokens = value.split() if isinstance(value, str) else []
                for surname, title in pairs:
                    for i, token in enumerate(tokens):
                        if token == surname and not (i + 1 < len(tokens) and is_title(tokens[i + 1], title)):
                            return True
                        if is_title(token, title) and (i == 0 or tokens[i - 1] != surname):
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
        from marco.language.hangul import batchim
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
            if not isinstance(shape, str) or change.get("after") is None:
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
        from marco.language.hangul import inflect
        return [form["text"] for form in inflect(stem, tense, ending,
                                                  self.inflection_grammar, kind=kind)]

    @staticmethod
    def compile(example, numerals=None, slot_particles=(), *, ignore_case=False, counters=None, pointers=(), capture_terminals=()):
        text, slots = example["text"], example["slots"]
        if not isinstance(capture_terminals, (tuple, list)):
            raise ValueError("invalid_capture_terminals")
        if capture_terminals:
            if (any(not isinstance(c, str) or len(c) != 1 or c.isspace() or c.isalnum()
                    for c in capture_terminals)
                    or len(capture_terminals) > 16 or len(set(capture_terminals)) != len(capture_terminals)):
                raise ValueError("invalid_capture_terminals")
            wide = example.get("wide_slots", [])
            if (not isinstance(wide, list) or any(name not in wide for name in slots)
                    or example.get("word_slots") or example.get("slot_forms")
                    or any(isinstance(seed, str) and seed.isdecimal() for seed in slots.values())):
                raise ValueError("invalid_capture_terminals")
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
                        unescaped = _compiled(r"\\(.)").sub(r"\1", tail)
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
            if not _compiled(r"[a-z][a-z0-9_]*").fullmatch(name) or text.count(literal) != 1:
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
                if capture_terminals:
                    kept = [c for c in ".!?" if c not in capture_terminals] + ["\r", "\n"]
                    slot_pattern = "[^%s]+" % "".join(re.escape(c) for c in kept)
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
        return [_compiled(variant, flags) for variant in variants], example["meaning"]

    def learn(self, correction, *, entry_origin=None, expression_kind="fact"):
        """Return a new reusable template; do not change inference rules."""
        if type(expression_kind) is not str or expression_kind not in ("fact", "query"):
            raise ValueError("invalid_expression_kind")
        from marco.language.entry_origins import EntryOriginError, validated_entry_origin
        try:
            new_origin = validated_entry_origin(entry_origin)
        except ValueError as exc:
            raise EntryOriginError(str(exc)) from exc
        if len(self.data["examples"]) != len(self.templates):
            raise EntryOriginError("entry origin data/templates are misaligned")
        existing = self.__dict__.get("_entry_origins")
        if "_entry_origins" not in self.__dict__:
            prospective = [None] * len(self.templates)
        else:
            if not isinstance(existing, list) or len(existing) != len(self.templates):
                raise EntryOriginError("entry origin vector is misaligned")
            try:
                prospective = [validated_entry_origin(row) for row in existing]
            except ValueError as exc:
                raise EntryOriginError(str(exc)) from exc
        meaning = correction.get("meaning", {})
        triple = meaning.get("triple")
        slots = correction.get("slots", {})
        if expression_kind == "query":
            query = meaning.get("query") if isinstance(meaning, dict) else None
            record = query[0] if isinstance(query, list) and len(query) == 1 else None
            q_triple = record.get("triple") if isinstance(record, dict) else None
            q_render = record.get("render") if isinstance(record, dict) else None
            known = next(iter(slots)) if isinstance(slots, dict) and len(slots) == 1 else None
            seed = slots.get(known) if known is not None else None
            ok = (isinstance(correction, dict) and set(correction) <= {"text", "slots", "meaning", "word_slots"}
                  and set(meaning) == {"query"} and isinstance(record, dict)
                  and set(record) == {"triple", "render"}
                  and isinstance(q_triple, list) and len(q_triple) == 3
                  and all(isinstance(x, str) and x for x in q_triple)
                  and isinstance(q_render, list) and bool(q_render)
                  and all(isinstance(x, str) for x in q_render)
                  and isinstance(known, str) and bool(known)
                  and isinstance(seed, str) and bool(seed)
                  and isinstance(correction.get("text"), str)
                  and correction["text"].count(seed) == 1
                  and not q_triple[1].startswith(("$", "?")))
            if ok:
                positions = [i for i in (0, 2) if q_triple[i] == "$" + known]
                ok = len(positions) == 1
            if ok:
                asked = q_triple[2 - positions[0]]
                ok = asked.startswith("?") and len(asked) > 1 and asked[1:] != known
            if ok and "word_slots" in correction:
                ok = correction["word_slots"] in ([], [known])
            if not ok:
                raise ValueError("correction_requires_grounded_query_slots")
        elif (not set(meaning).issubset({"triple", "polarity", "modality"})
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
        from marco.language.hangul import canonical_clauses
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
        append_index = len(self.templates)
        prospective.insert(append_index, new_origin)
        self.data["examples"].append(copy.deepcopy(correction))
        self.templates.append(compiled)
        self._entry_origins = prospective
        self.induced_frames.clear()
        self.__dict__.pop("_조각틀", None)
        self._rebuild_inflections()
        self._repair_cache.clear()
        self._ending_table = None
        return True

    def bind_entry_origin(self, entry_index, origin):
        """Bind passive origin metadata to one installed entry; return a copy."""
        from marco.language.entry_origins import EntryOriginError, validated_entry_origin
        if type(entry_index) is not int:
            raise EntryOriginError("entry_index must be a strict int")
        count = len(self.templates)
        if len(self.data["examples"]) != count:
            raise EntryOriginError("entry origin data/templates are misaligned")
        if not 0 <= entry_index < count:
            raise EntryOriginError("entry_index out of range")
        existing = self.__dict__.get("_entry_origins")
        try:
            row = validated_entry_origin(origin)
            if "_entry_origins" not in self.__dict__:
                prospective = [None] * count
            elif not isinstance(existing, list) or len(existing) != count:
                raise EntryOriginError("entry origin vector is misaligned")
            else:
                prospective = [validated_entry_origin(r) for r in existing]
        except ValueError as exc:
            raise EntryOriginError(str(exc)) from exc
        current = prospective[entry_index]
        if current is not None and current != row:
            raise EntryOriginError("entry origin conflicts with the bound origin")
        prospective[entry_index] = row
        self._entry_origins = prospective
        return copy.deepcopy(row)

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
        from marco.learning.rules import propose
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
        from marco.reasoning.inference import closure
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
            from marco.reasoning.inference import bind, current_facts, proof
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

    def _clause_selection(self, literal, *, source=None, phase="clause", guard_names=True, exclude=()):
        """Private selection transport: the selected meanings with their derivations, matched
        indexes and witness records, under the declared version (0 absent, 1, or 2)."""
        from copy import deepcopy
        if phase not in ("whole", "clause"):
            raise ValueError("clause selection: phase")
        eff_source = literal if source is None else source
        decl = self.data.get("predicate_frames")
        if decl is None:
            version = 0
        elif not isinstance(decl, dict):
            raise ValueError("clause selection: declaration")
        elif decl.get("schema") == "predicate-frames-v1":
            version = 1
        elif decl.get("schema") == "predicate-frames-v2":
            version = 2
        else:
            raise ValueError("clause selection: schema")
        route = None

        def legacy():
            d, m, r = {}, {}, {}
            got = self._legacy_clause_meanings(literal, derivations=d, matched=m, guard_names=guard_names,
                                               exclude=exclude, source=source, records=r)
            return got, d, m, r

        def pack(meanings, d, m, r):
            return {"version": version, "literal": literal, "source": eff_source,
                    "route": deepcopy(route), "meanings": deepcopy(meanings),
                    "derivations": deepcopy(d), "matched": deepcopy(m), "records": deepcopy(r)}

        if version == 0:
            return pack(*legacy())
        if version == 1:
            from marco.language.frames import declared_clause
            owned = declared_clause(self, source or literal)
            if owned is not None:
                if owned[0] != "ok":
                    return pack({}, {}, {}, {})
                key = json.dumps(owned[1], sort_keys=True, ensure_ascii=False)
                if key in exclude:
                    return pack({}, {}, {}, {})
                return pack({key: owned[1]}, {key: owned[2]}, {}, {})
            return pack(*legacy())
        from marco.language.frames import _declared_route
        sink = {}
        route = _declared_route(self, eff_source, phase=phase, literal=literal, guard_names=guard_names,
                                exclude=exclude, legacy_selection=sink)
        kind = route["kind"]
        if kind == "none":
            if not sink:
                return pack(*legacy())
            return pack({}, {}, {}, {})
        if kind == "legacy":
            keys = route["legacy_keys"]
            got = sink["meanings"]
            return pack({k: got[k] for k in keys},
                        {k: sink["derivations"][k] for k in keys if k in sink["derivations"]},
                        {k: sink["matched"][k] for k in keys if k in sink["matched"]},
                        {k: sink["records"][k] for k in keys if k in sink["records"]})
        if kind == "flat":
            cand = route["flat_candidates"][0]
            key = json.dumps(cand["meaning"], sort_keys=True, ensure_ascii=False)
            if key in exclude:
                return pack({}, {}, {}, {})
            return pack({key: cand["meaning"]}, {key: cand["trace"]},
                        {key: cand["trace"]["source_ref"]["index"]}, {})
        return pack({}, {}, {}, {})

    def _clause_meanings(self, literal, *, derivations=None, matched=None, guard_names=True, exclude=(),
                         source=None):
        """The clause's readings of the best rank. ``exclude``: meaning keys already returned (by
        ``readings``): they are left out, so the readings of the next rank are found (goal G5.4 B)."""
        sel = self._clause_selection(literal, source=source, phase="clause", guard_names=guard_names,
                                     exclude=exclude)
        route = sel["route"]
        if sel["matched"] and (route is None or route["kind"] in ("legacy", "none")):
            if derivations is not None:
                derivations.clear()
            if matched is not None:
                matched.clear()
        if derivations is not None:
            derivations.update(sel["derivations"])
        if matched is not None:
            matched.update(sel["matched"])
        return sel["meanings"]

    def _legacy_clause_meanings(self, literal, *, derivations=None, matched=None, guard_names=True, exclude=(),
                                source=None, records=None):
        """The template/query/definition algorithm of ``_clause_meanings``. ``records``: an optional dict
        that receives, for each accepted best-rank key, the selected example's witness record."""
        from marco.language.numerals import parse_numeral
        if records is not None:
            records.clear()
        # Where a declared holder form rewrites the clause (제 동기 서준 -> 서준, 예린 씨 -> 예린), the
        # typed words are that form: a reading that keeps them inside a name is not taken.
        held, holder_note = self._holder_forms(literal)
        if holder_note is not None and set(holder_note["forms"]) <= {"numeral_article"}:
            holder_note = None          # an article dropped before a numeral names no holder
        for said in ([held] if holder_note is not None else []) + [literal]:
            chained = self._quantity_chain_meaning(said)
            if chained is not None and getattr(self, "effort", 3) >= 1 and self._chain_swallowed(chained, said):
                chained = None
            if chained is not None and json.dumps(chained, sort_keys=True, ensure_ascii=False) not in exclude:
                return {json.dumps(chained, sort_keys=True, ensure_ascii=False): chained}
            counted = (self._count_question_meaning(said) or self._why_count_meaning(said)
                       or self._why_fact_meaning(said))
            if counted is not None and json.dumps(counted, sort_keys=True, ensure_ascii=False) not in exclude:
                return {json.dumps(counted, sort_keys=True, ensure_ascii=False): counted}
            compared = self._comparison_meaning(said) or self._same_meaning(said)
            if compared is not None and json.dumps(compared, sort_keys=True, ensure_ascii=False) not in exclude:
                return {json.dumps(compared, sort_keys=True, ensure_ascii=False): compared}
            # A question read as the pack's question frame, before any example reads it with a modifier inside a
            # name (G7-Q, effort 1).
            framed = self._question_frame_meaning(said) if getattr(self, "effort", 3) >= 1 else None
            if framed is not None and json.dumps(framed, sort_keys=True, ensure_ascii=False) not in exclude:
                return {json.dumps(framed, sort_keys=True, ensure_ascii=False): framed}
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
                    slots = self._holder_slot_forms(match.groupdict(), meaning)
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
                    # The thing counted never holds a count in digits (``Claire 7 pans``): the amount leaked
                    # into the thing's name, so the reading is not taken (G5).
                    if isinstance(slots.get("item"), str) and _compiled(r"(?<![\w])\d+(?![\w])").search(slots["item"]) \
                            and not str(example["slots"].get("item", "")).isdecimal():
                        continue
                    # nor a numeral word with its counter (공 여섯 권을: an amount said, not a thing's name, G6)
                    if isinstance(slots.get("item"), str) and self._holds_counted_amount(slots["item"]):
                        continue
                    # A word the pack declares as filling no slot (a phrase variant read as nothing: 지금은,
                    # 오늘은, now, still) is never part of a holder or a thing: the reading without it is taken
                    # (G5 batch 5)
                    if any(word in self._slotless_words() for name, value in slots.items()
                           if isinstance(value, str) and not str(example["slots"].get(name, "")).isdecimal()
                           for word in (value.lower() if self.data.get("ignore_case") else value).split()):
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
                            _compiled(pattern).search(row["word"].lower()) for pattern in in_names))
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
                    # Nor a surname without its job title, or the title without its surname (변 과장한테 ...: 변
                    # the giver and 과장 the receiver): the two are one holder (가진쪽꼴.job_titles).
                    if self._splits_titled_holder(grounded_names, literal):
                        continue
                    if exclude and json.dumps(self._grounded(meaning, slots, normalization, example), sort_keys=True,
                                              ensure_ascii=False) in exclude:
                        continue
                    scoped_record = None
                    if ("semantic_capabilities" in self.data and isinstance(normalization, dict)
                            and normalization.get("id") == "declared-negation-v1"
                            and normalization.get("polarity") is False
                            and "example_index" in normalization):
                        # The original-source proof gates the meaning itself, before any mutation.
                        scoped_record = self._scoped_negative_record(
                            example, index, match, candidate, normalization,
                            self._grounded(meaning, slots, normalization, example),
                            source if source is not None else literal)
                        if scoped_record is None:
                            continue
                    if best_rank is None or rank > best_rank:
                        meanings, best_rank = {}, rank
                        if derivations is not None:
                            derivations.clear()
                        if matched is not None:
                            matched.clear()
                        if records is not None:
                            records.clear()
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
                        if records is not None and key not in meanings and scoped_record is not None:
                            records[key] = scoped_record
                        elif records is not None and key not in meanings:
                            import hashlib
                            whole = source if source is not None else literal
                            captures, fixed = None, None
                            start = len(whole) - len(whole.lstrip())
                            marks = set()
                            for mark in (list((self.data.get("predicate_frames") or {}).get("terminators") or [])
                                         + list((self.clause_grammar or {}).get("question_marks") or [])
                                         + [(self.clause_grammar or {}).get("question_mark")]):
                                if isinstance(mark, str) and len(mark) == 1 and not mark.isspace():
                                    marks.add(mark)
                            body = whole.strip()
                            if body and body[-1] in marks:
                                body = body[:-1]
                            limit, selected = None, None
                            if normalization is None:
                                if body == candidate:
                                    limit = len(candidate)
                            elif isinstance(normalization, dict) and normalization.get("example_index") == index:
                                core = {k: v for k, v in normalization.items() if k != "example_index"}
                                found = [t for t in self._inflected_examples(example) if t[2] == core]
                                if len(found) == 1:
                                    selected = found[0]
                                    typed, canon = selected[0], selected[1]
                                    if candidate.endswith(canon):
                                        prefix = candidate[:len(candidate) - len(canon)]
                                        if body == prefix + typed:
                                            limit = len(prefix)
                            if limit is not None:
                                spans = {name: match.span(name) for name in example["slots"]}
                                ordered = sorted(spans.values())
                                if (all(0 <= lo <= hi <= limit for lo, hi in ordered)
                                        and all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:]))):
                                    captures = {name: {"value": whole[start + lo:start + hi],
                                                       "span": [start + lo, start + hi]}
                                                for name, (lo, hi) in spans.items()}
                                    fixed, at = [], 0
                                    for lo, hi in sorted(item["span"] for item in captures.values()):
                                        if lo > at:
                                            fixed.append([at, lo])
                                        at = max(at, hi)
                                    if at < len(whole):
                                        fixed.append([at, len(whole)])
                            guard = (selected is not None and "query" not in meaning and "define" not in meaning
                                     and "invoke" not in meaning
                                     and selected[2]["ending"] in self.condition_endings)
                            kind = ("query" if "query" in meaning else "definition" if "define" in meaning
                                    else "invoke" if "invoke" in meaning else "guard" if guard else "template")
                            records[key] = {
                                "meaning_key": key,
                                "meaning": json.loads(json.dumps(grounded, ensure_ascii=False)),
                                "example_index": index,
                                "annotation_sha256": hashlib.sha256(json.dumps(
                                    example, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest(),
                                "canonical": candidate,
                                "normalization": json.loads(json.dumps(normalization, ensure_ascii=False)),
                                "source": whole,
                                "capture_spans": captures,
                                "fixed_spans": fixed,
                                "reader_kind": kind,
                                "grammar_scope": ({"kind": "guard", "ending": selected[2]["ending"],
                                                   "scope": [0, len(whole)], "rule_id": selected[2]["id"]}
                                                  if guard else None),
                            }
                        meanings[key] = grounded
        return meanings


    def _chain_swallowed(self, chained, said):
        """Whether a count question the chain reader read (``지금 X는 몇 개야``) holds in its name words the count
        reader leaves out (a joiner of two holders, a declared modifier such as 남은): the count question's own
        reading is then the one (G7-Q, effort 1)."""
        counted = self._count_question_meaning(said)
        rows = [q for q in (chained or {}).get("query") or [] if isinstance(q, dict)]
        if counted is None or len(rows) != 1 or not isinstance(rows[0].get("triple"), list):
            return False
        subject = rows[0]["triple"][0]
        if not isinstance(subject, str):
            return False
        row = counted["query"][0]
        if isinstance(row.get("triple"), list):
            words = str(row["triple"][0]).split()
        elif isinstance(row.get("total"), dict) and isinstance(row["total"].get("members"), list):
            words = [w for m in row["total"]["members"] for w in str(m).split()] + str(row["total"].get("item") or "").split()
        else:
            return False
        typed = subject.split()
        if len(typed) > len(words):
            return all(any(t.startswith(w) for t in typed) for w in words)
        return typed != words and len(typed) == len(words) and all(t.startswith(w) for t, w in zip(typed, words))

    def _frame_phrase(self, low, at, phrases):
        """The length in words of the longest declared phrase that starts at ``low[at]`` (0 for none)."""
        best = 0
        for phrase in phrases:
            words = phrase.lower().split()
            if words and low[at:at + len(words)] == words and len(words) > best:
                best = len(words)
        return best

    def _frame_modifiers(self, low, start, end, modifiers):
        """Whether ``low[start:end]`` is modifier phrases only (the declared classes), and which classes."""
        kinds, at = set(), start
        while at < end:
            if low[at] == ",":
                at += 1
                continue
            step = 0
            for kind, phrases in modifiers.items():
                n = self._frame_phrase(low[:end], at, phrases)
                if n > step:
                    step, found = n, kind
            if not step:
                return False, kinds
            kinds.add(found)
            at += step
        return True, kinds

    def _frame_holder(self, spec, words):
        """One holder as the frame reads it: an article left out, the speaker as the pack's self form."""
        words = [w for w in words if w != ","]
        if words and words[0].lower() in [a.lower() for a in spec.get("articles", [])]:
            words = words[1:]
        if not words or len(words) > 4:
            return None
        if len(words) == 1 and words[0] in spec.get("self", []):
            return (self.holder_forms.get("self") or {}).get("reads_as") or words[0]
        return " ".join(words)

    def _frame_holders(self, spec, words):
        """The holders of a frame: joined by the declared joiners (and commas), or a group word."""
        low = " ".join(w.lower() for w in words if w != ",")
        group = {k.lower(): v for k, v in (spec.get("group") or {}).items()}
        if low in group:
            return group[low]
        joiners = {j.lower() for j in spec.get("joiners", [])}
        members, current = [], []
        for word in words:
            if word.lower() in joiners or word == ",":
                if current:
                    members.append(current)
                current = []
            else:
                current.append(word)
        if current:
            members.append(current)
        out = [self._frame_holder(spec, m) for m in members]
        # a protected word (a scope word such as each, a numeral, a negation) is never part of a holder
        if any(self._protected_kind(w) for m in members for w in m):
            return None
        return out if out and all(out) else None

    def _question_frame_meaning(self, literal):
        """``How many pens do Nora and Bo have combined?`` -> total(Nora, Bo, pens): a question read as a frame
        plus slots (G7-Q), from the pack's declaration (수량물음.frame): the asker, the thing, an auxiliary, the
        holders, a predicate of having, and after it only words of the declared modifier classes; or the thing,
        a copula, and a place or a holder after its marker; or a comparison of two holders. A modifier never
        changes the operator: one holder is a count, two or more a total. Any other word: not read."""
        spec = (self.count_question or {}).get("frame") or {}
        if not spec:
            return None
        text = literal.strip().rstrip("?.!？ ").replace(",", " , ")
        tokens = text.split()
        low = [t.lower() for t in tokens]
        modifiers = spec.get("modifiers") or {}
        compared = self._frame_comparison(spec, tokens, low, modifiers)
        if compared is not None:
            return compared
        n = next((self._frame_phrase(low, 0, [a]) for a in spec.get("askers", []) if self._frame_phrase(low, 0, [a])), 0)
        if not n:
            return None
        auxiliaries = {w.lower() for w in spec.get("auxiliaries", [])}
        copulas = {w.lower() for w in spec.get("copulas", [])}
        lefts = [w.lower() for w in spec.get("left_verbs", [])]
        cut = next((i for i in range(n, len(low)) if low[i] in auxiliaries | copulas
                    or self._frame_phrase(low, i, lefts)), None)
        if cut is None or (cut == n and low[cut] not in auxiliaries):
            return None
        # no thing said (How many do the two of them have?): read only for a group or several holders, the thing
        # left to the conversation
        item = self._frame_holder(spec, tokens[n:cut]) if cut > n else None
        if (cut > n and item is None) or item == (self.holder_forms.get("self") or {}).get("reads_as") \
                or any(self._protected_kind(w) for w in tokens[n:cut]):
            return None
        render = ["$n", " ", item, "."] if item else ["$n", "."]
        if low[cut] in auxiliaries:
            predicates = {w.lower() for w in spec.get("predicates", [])}
            k = next((i for i in range(len(low) - 1, cut, -1) if low[i] in predicates), None)
            if k is None:
                return None
            ok, _kinds = self._frame_modifiers(low, k + 1, len(low), modifiers)
            if not ok:
                return None
            # a modifier may stand before the predicate too (does Nora still have)
            end = k
            while end > cut + 1:
                back = next((j for j in range(cut + 1, end) if self._frame_modifiers(low, j, end, modifiers)[0]), None)
                if back is None:
                    break
                end = back
            holders = self._frame_holders(spec, tokens[cut + 1:end])
            if holders is None:
                return None
            if isinstance(holders, str):
                return {"query": [{"total": {"members": holders, "item": item}, "render": render}]}
            if len(holders) >= 2:
                return {"query": [{"total": {"members": holders, "item": item}, "render": render}]}
            if item is None:
                return None
            return {"query": [{"triple": ["%s %s" % (holders[0], item), "count", "?n"], "render": render}]}
        # how many THING are (there) (modifiers) in PLACE / are left with HOLDER / remain with HOLDER
        at = cut + (1 if low[cut] in copulas else 0)
        at += 1 if at < len(low) and low[at] in [w.lower() for w in spec.get("there", [])] else 0
        markers = [w.lower() for w in spec.get("place_markers", [])] + [w.lower() for w in spec.get("holder_markers", [])]
        mark = next((i for i in range(at, len(low)) if low[i] in markers), None)
        if mark is None:
            return None
        ok, _kinds = self._frame_modifiers(low, at, mark, dict(modifiers, verbs=spec.get("left_verbs", [])))
        if not ok:
            return None
        tail = mark + 1
        while tail < len(low) and not self._frame_modifiers(low, tail, len(low), modifiers)[0]:
            tail += 1
        holder = self._frame_holder(spec, tokens[mark + 1:tail])
        if holder is None:
            return None
        return {"query": [{"triple": ["%s %s" % (holder, item), "count", "?n"], "render": render}]}

    def _frame_comparison(self, spec, tokens, low, modifiers):
        """``Who has more pens left, Nora or Bo?``, ``Which of us has fewer pens, me or Bo?``, ``Do Nora and Bo
        have the same number of pens now?``: two holders compared, the declared comparison frame."""
        comp = spec.get("comparison") or {}
        if not comp:
            return None
        more_words = [w.lower() for w in comp.get("more", [])]
        fewer_words = [w.lower() for w in comp.get("fewer", [])]
        # Between A and B, who has more X? / A or B, who has more X?: the two holders said first
        for w in range(1, len(low)):
            n = max([self._frame_phrase(low, w, [x]) for x in comp.get("who", [])] + [0])
            if not n or low[w - 1] != "," or w + n + 1 >= len(low) or low[w + n] not in comp.get("verbs", []):
                continue
            head = tokens[:w - 1]
            if head and head[0].lower() in [x.lower() for x in comp.get("prefixes", [])]:
                head = head[1:]
            alternative = comp.get("alternative", "or")
            head = ["and" if t.lower() == alternative else t for t in head]
            holders = self._frame_holders(spec, head)
            kind = "more" if low[w + n + 1] in more_words else "fewer" if low[w + n + 1] in fewer_words else None
            if not isinstance(holders, list) or len(holders) != 2 or kind is None:
                return None
            body = w + n + 2
            stop = next((j for j in range(body, len(low) + 1) if self._frame_modifiers(low, j, len(low), modifiers)[0]),
                        len(low))
            item = self._frame_holder(spec, tokens[body:stop]) if stop > body else None
            if stop > body and item is None:
                return None
            return {"query": [{kind: {"a": holders[0], "b": holders[1], **({"item": item} if item else {})}}]}
        # Does A have more X than B?
        than = [x.lower() for x in comp.get("than", [])]
        asks = [x.lower() for x in (comp.get("same") or {}).get("asks", [])]
        if low and low[0] in asks and any(t in than for t in low):
            predicates = {w.lower() for w in spec.get("predicates", [])}
            k = next((i for i in range(1, len(low)) if low[i] in predicates), None)
            t = next(i for i, x in enumerate(low) if x in than)
            if k is None or k + 1 >= t or t + 1 >= len(low):
                return None
            kind = "more" if low[k + 1] in more_words else "fewer" if low[k + 1] in fewer_words else None
            a = self._frame_holder(spec, tokens[1:k])
            item = self._frame_holder(spec, tokens[k + 2:t]) if t > k + 2 else None
            stop = next((j for j in range(t + 1, len(low) + 1) if self._frame_modifiers(low, j, len(low), modifiers)[0]),
                        len(low))
            b = self._frame_holder(spec, tokens[t + 1:stop])
            if kind is None or a is None or b is None or (t > k + 2 and item is None) \
                    or any(self._protected_kind(x) for x in tokens[1:]):
                return None
            return {"query": [{kind: {"a": a, "b": b, **({"item": item} if item else {})}}]}
        n = max([self._frame_phrase(low, 0, [w]) for w in comp.get("who", [])] + [0])
        if n and n < len(low) and low[n] in [v.lower() for v in comp.get("verbs", [])]:
            kind_at = n + 1
            if kind_at >= len(low):
                return None
            kind = "more" if low[kind_at] in comp.get("more", []) else "fewer" if low[kind_at] in comp.get("fewer", [])                 else None
            if kind is not None and "," not in low[kind_at:] and any(
                    self._frame_phrase(low, 0, [w]) == n for w in comp.get("pair_who", [])):
                # which of the two has more (X)?: the two holders are the conversation's
                body = kind_at + 1
                stop = next((j for j in range(body, len(low) + 1) if self._frame_modifiers(low, j, len(low), modifiers)[0]),
                            len(low))
                item = self._frame_holder(spec, tokens[body:stop]) if stop > body else None
                if stop > body and item is None:
                    return None
                return {"query": [{kind: {"pair": True, **({"item": item} if item else {})}}]}
            if kind is None or "," not in low[kind_at:]:
                return None
            comma = kind_at + low[kind_at:].index(",")
            body = kind_at + 1
            stop = next((j for j in range(body, comma) if self._frame_modifiers(low, j, comma, modifiers)[0]), comma)
            item = self._frame_holder(spec, tokens[body:stop]) if stop > body else None
            rest = low[comma + 1:]
            alternative = comp.get("alternative", "or")
            if rest.count(alternative) != 1:
                return None
            split = comma + 1 + rest.index(alternative)
            a = self._frame_holder(spec, tokens[comma + 1:split])
            b = self._frame_holder(spec, tokens[split + 1:])
            if a is None or b is None:
                return None
            return {"query": [{kind: {"a": a, "b": b, **({"item": item} if item else {})}}]}
        same = comp.get("same") or {}
        if low and low[0] in [w.lower() for w in same.get("asks", [])]:
            predicates = {w.lower() for w in spec.get("predicates", [])}
            k = next((i for i in range(1, len(low)) if low[i] in predicates), None)
            if k is None:
                return None
            m = max([self._frame_phrase(low, k + 1, [p]) for p in same.get("phrases", [])] + [0])
            if not m:
                return None
            start = k + 1 + m
            stop = next((j for j in range(start, len(low) + 1) if self._frame_modifiers(low, j, len(low), modifiers)[0]),
                        len(low))
            item = self._frame_holder(spec, tokens[start:stop]) if stop > start else None
            holders = self._frame_holders(spec, tokens[1:k])
            if not isinstance(holders, list) or len(holders) != 2:
                return None
            return {"query": [{"same": {"a": holders[0], "b": holders[1], **({"item": item} if item else {})}}]}
        return None

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
            if len(words) == 1:
                # a one-word holder keeps a case the example's own particle stood on (도서관에는 일곱 개예요 ->
                # 도서관에): the case is no part of the name (소유자리.홀로떼는조사)
                case = next((p for p in (self.possessor or {}).get("lone_cases", [])
                             if name.endswith(p) and len(name) - len(p) >= shortest), None)
                return name[:-len(case)] if case else name
            for index, word in enumerate(words[:-1]):
                # (a particle the owner's last sound does not take is no particle: 나은 is a name, not 나 + 은)
                particle = next((p for p in particles if word.endswith(p) and len(word) > len(p)
                                 and self._particle_form(word[:-len(p)], p) == p), None)
                owner = words[:index] + [word[:-len(particle)]] if particle is not None else []
                # The speaker's key (나) is an owner however short it is; so is a declared relation noun
                # (형은: 형 + 은, G5 batch 6).
                if particle is not None and (len("".join(owner)) >= shortest
                                             or owner == [self.speaker_placeholder]
                                             or owner[-1:] and owner[-1] in (
                                                 (self.holder_forms or {}).get("relation_nouns") or [])):
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
            touched, owners = False, set()
            for row, new in zip(rows, new_rows):
                if isinstance(row, list) and len(row) == 3 and row[1] in relations and isinstance(row[0], str):
                    joined_name = split(row[0])
                    if joined_name != row[0]:
                        new[0] = joined_name
                        touched = True
                        owners.add(joined_name[:len(joined_name) - len(row[0].split()[-1])].strip())
            if len(owners) == 1:
                # The topic holds across the clauses of one sentence (하루는 구슬이 18개 있고 단추도 좀 있다): a
                # thing said bare in another clause is the same owner's (G5 batch 6).
                owner = next(iter(owners))
                for row, new in zip(rows, new_rows):
                    if (isinstance(row, list) and len(row) == 3 and row[1] in relations and isinstance(row[0], str)
                            and len(row[0].split()) == 1 and new[0] == row[0] and owner):
                        new[0] = owner + " " + row[0]
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

    def _why_fact_meaning(self, literal):
        """``왜 보라가 4개야`` / ``Why does Nora have 4?`` -> ``{"why_count": {"subject": [보라], "value": 4}}``.

        A why that restates a count (G6 class 13). The pack declares its forms (수량이유물음.facts): a
        pattern with ``{수}`` for the number (and ``{단위}`` for a counter), and ``ask``, the count
        question the same holder would be asked with (``{h}``, ``{i}`` from the pattern's groups). The
        holder is read by reading that question, so a why names a holder exactly as a count question
        does. A form without ``ask`` names no holder (``왜 4개예요``); a form with no number names none.
        """
        from marco.language.numerals import parse_numeral
        forms = (self.why_count or {}).get("facts") or []
        said = " ".join(literal.strip().rstrip("".join(self.clause_grammar.get("question_marks", [])) + ".! ").split())
        units = "|".join(re.escape(u) for u in sorted(self.counters.get("units", []), key=len, reverse=True))
        for form in forms:
            pattern = form["pattern"].replace("{수}", r"(?P<n>\S+?)").replace("{단위}", "(?P<c>%s)" % (units or "(?!)"))
            found = re.fullmatch(pattern, said, re.IGNORECASE)
            if found is None:
                continue
            groups = {key: (value or "").strip() for key, value in found.groupdict().items()}
            value = parse_numeral(groups["n"], self.data.get("numerals", {})) if "n" in groups else None
            if "n" in groups and value is None:
                continue
            subject = []
            if form.get("ask"):
                question = " ".join(form["ask"].format(**groups).split())
                asked = [q["triple"] for meaning in self._clause_meanings(question).values()
                         for q in meaning.get("query") or []
                         if isinstance(q, dict) and isinstance(q.get("triple"), list) and len(q["triple"]) == 3
                         and q["triple"][1] == "count"]
                if len(asked) != 1:
                    continue
                holder = asked[0][0]
                holder = " ".join(holder) if isinstance(holder, list) else str(holder)
                subject = [self.canonical_name(holder)]
            return {"query": [{"why_count": {"subject": subject,
                                             **({"value": int(value)} if value is not None else {})}}]}
        return None

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
        more_totals = set()
        if getattr(self, "effort", 3) >= 1:
            # the modifier words declared for the question frame (G7-Q, effort 1)
            more = spec.get("frame_modifiers") or {}
            drop |= set(more.get("time", []))
            more_totals = set(more.get("total", []))
        name, total, marked, raw = [], False, [], []
        shortest = int((self.possessor or {}).get("min_length", 1))
        for index, word in enumerate(words[:at]):
            if (index == 0 and word in heads) or word in drop:
                continue
            if word in spec.get("total_words", []) or word in more_totals:
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
            marked.append(particle is not None)
            raw.append(word)
        # A declared group word ("두 사람", "둘") in a total names every holder.
        joined_name, group, pair = " ".join(name), False, False
        for phrase in sorted(spec.get("group_words", []), key=len, reverse=True):
            if joined_name == phrase or joined_name.startswith(phrase + " "):
                joined_name, group = joined_name[len(phrase):].strip(), True
                # a group word that names two (두 사람, 둘이) sums exactly two holders
                pair = phrase in spec.get("pair_words", [])
                break
        if not group:
            # ``A와 B는 구슬이 모두 몇 개야``: two holders joined by a declared
            # conjunctive particle (비교물음.between.joiners) are the members. The count of two
            # holders joined so is their total with or without a total word (``A와 B는 구슬이
            # 몇 개 있어``, G5): one holder's count is never asked with two names.
            joiners = sorted((self.comparison or {}).get("between", {}).get("joiners", []), key=len, reverse=True)
            # the first member runs to the first word that carries a joiner (``선 이사님과``: a holder of two words,
            # G5 batch 6), at most the first three words
            k = next((i for i, w in enumerate(raw[:3]) if any(w.endswith(j) and len(w) > len(j) for j in joiners)), None)
            joiner = next((j for j in joiners if k is not None and raw[k].endswith(j) and len(raw[k]) > len(j)), None)
            first = (" ".join(name[:k] + [raw[k]])) if joiner else ""
            start = (k or 0) + 1
            # the second member runs to the first word after it that carries its case (``A와 황 팀장님이``: a
            # holder of two words); with none, it is one word (G5 batch 5)
            end = next((i for i in range(start, len(name) - 1) if marked[i]), start)
            groups = sorted(spec.get("group_words", []), key=len, reverse=True)
            end = next((j - 1 for j in range(start + 1, end + 1)
                        if any(" ".join(name[j:]) == g or " ".join(name[j:]).startswith(g + " ") for g in groups)), end)
            rest = " ".join(name[end + 1:])
            # A group word after the two names repeats them (``A와 B 둘이``).
            for phrase in sorted(spec.get("group_words", []), key=len, reverse=True):
                if rest == phrase or rest.startswith(phrase + " "):
                    rest = rest[len(phrase):].strip()
                    break
            if joiner is not None and len(name) >= start + 2 and rest:
                # the second member may carry the joiner too (A랑 B랑 합쳐서)
                second = " ".join(name[start:end + 1])
                tail = next((j for j in joiners if second.endswith(j) and len(second) > len(j)), None)
                second = second[:-len(tail)] if tail else second
                return {"query": [{"total": {"members": [first[:-len(joiner)], second], "item": rest},
                                   "render": list(spec["render"])}]}
        if (total and not group and getattr(self, "effort", 3) >= 1 and len(name) >= 2
                and (words[at - 1] in spec.get("total_words", []) or words[at - 1] in more_totals)
                and not any(self._protected_kind(w) in ("scope", "negation") for w in raw)):
            # (a counter inside the thing's name, 과자 봉지, is no scope word: the count of 과자 봉지)
            # a total word right before the question word, over one holder and its thing, asks that holder's
            # count (G7-Q); anywhere else it is a scope word out of place and the repair guard holds it
            total = False
        if total or group:
            if not (total and group):
                return None
            return {"query": [{"total": {"members": "two" if pair else "all", "item": joined_name or None},
                               "render": list(spec["render"])}]}
        if not name:
            return None
        # The one name word said in a holder's case (수량물음.owner_cases, with or without a delimiter on it) is the
        # holder, wherever it stands: 사과는 라온한테 몇 개 있어 asks 라온's apples, as 라온한테 사과가 몇 개 있어 does.
        cases = spec.get("owner_cases", [])
        endings = [c + d for c in cases for d in [""] + list(spec.get("delimiters", []))]
        owners = [i for i, word in enumerate(raw) if any(word.endswith(e) and len(word) > len(e) for e in endings)]
        if len(owners) == 1 and owners[0] > 0:
            # the unmarked words right before the owner word are its own (기 대표에게: a surname and a title,
            # G7-Q, effort 1); a marked word before it is another phrase (사과는 라온한테)
            first = owners[0]
            if getattr(self, "effort", 3) >= 1:
                while first > 0 and not marked[first - 1]:
                    first -= 1
            name = name[first:owners[0] + 1] + name[:first] + name[owners[0] + 1:]
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
        than = next((w for w in words for t in spec.get("than", []) if w.endswith(t) and len(w) > len(t)), None)
        if (than is not None and getattr(self, "effort", 3) >= 1 and words[-1] in self._comparison_forms()
                and any(w in spec.get("more", []) for w in words)):
            # A가 B보다 X이 더 많아?: two holders compared by the word of comparison (보다), G7-Q, effort 1
            at = words.index(than)
            marker = next(t for t in spec.get("than", []) if than.endswith(t))
            more_at = next(i for i, w in enumerate(words) if w in spec.get("more", []))
            if at != 1 or more_at < at or len(words) - 1 != more_at + 1:
                return None
            item = [bare(w) for w in words[at + 1:more_at] if w not in spec.get("time_words", [])]
            if len(item) > 1 or any(self._protected_kind(w) for w in words):
                return None
            kind = "fewer" if self._comparison_forms()[words[-1]] == "less" else "more"
            return {"query": [{kind: {"a": bare(words[0]), "b": than[:-len(marker)],
                                      **({"item": item[0]} if item else {})}}]}
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
        if (before and getattr(self, "effort", 3) >= 1 and before[-1] in spec.get("between", {}).get("among", [])
                and " ".join(before[:-1]) in (self.count_question or {}).get("pair_words", [])):
            # 둘 중 누가 더 많아?: the two holders are the conversation's
            return {"query": [{kind: {"pair": True, **({"item": request["item"]} if request.get("item") else {})}}]}
        if before:
            among = spec.get("between", {}).get("among", [])
            joiners = sorted(spec.get("between", {}).get("joiners", []), key=len, reverse=True)
            if len(before) != 3 and getattr(self, "effort", 3) >= 1 and len(before) >= 3 and before[-1] in among:
                # holders of several words (기 대표님과 민석 중에: G7-Q, effort 1): the first runs to the word
                # that carries the joiner, the second from there to the word of choice
                k = next((i for i, w in enumerate(before[:-1]) if any(w.endswith(j) and len(w) > len(j)
                                                                      for j in joiners)), None)
                if k is None or k + 1 >= len(before) - 1:
                    return None
                joiner = next(j for j in joiners if before[k].endswith(j) and len(before[k]) > len(j))
                request.update(a=" ".join(before[:k] + [before[k][:-len(joiner)]]), b=" ".join(before[k + 1:-1]))
                return {"query": [{kind: request}]}
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
        from marco.language.hangul import inflect
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
        if joiner is None and getattr(self, "effort", 3) >= 1 and len(body) >= 3:
            # a first holder of several words (기 대표님과 민석은: G7-Q, effort 1)
            k = next((i for i, w in enumerate(body[:2]) if any(w.endswith(j) and len(w) > len(j) for j in joiners)),
                     None)
            if k is not None:
                joiner = next(j for j in joiners if body[k].endswith(j) and len(body[k]) > len(j))
                body = [" ".join(body[:k + 1])] + body[k + 1:]
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
            from marco.language.hangul import inflect
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
        from marco.language.numerals import parse_numeral
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
                        for match in [_compiled(pattern).fullmatch(literal)] if match is not None), None)
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
            step = _compiled(r"\s*(?P<n>[^.!?,]+?)\s*" + unit + r"\s*" + particle
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
        asked = _compiled(r"\s*" + prefix + r"\s+(?P<item>.+?)" + particle + r"\s*" + question + r"\s*").fullmatch(literal)
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

    def open_reading(self, text):
        """What a sentence no reading covers whole still says, part by part, with the slots left open (G7-Q,
        partial readings): each word with its span and its kind as the pack declares it -- a number (a numeral,
        digits, a numeral with a counter), the question word, a correction or contrast word (대조정정 and its
        frame's cues), a negation, a verb form of a declared verb, a name by the pack's name form -- and the
        word with its particle taken off. Nothing is guessed: which holder, thing or event a word is, is left
        to the conversation, which grounds the open slots against its state."""
        from marco.language.numerals import parse_numeral
        fold = (lambda v: v.lower()) if self.data.get("ignore_case") else (lambda v: v)
        numerals = self.data.get("numerals", {})
        units = sorted((self.counters or {}).get("units", []), key=len, reverse=True)
        askers = [fold(a) for a in (self.counters or {}).get("askers", [])]
        askers += [fold(a) for a in ((self.count_question or {}).get("frame") or {}).get("askers", [])]
        contrast = dict(self.language_pack.get("contrast_correction") or {})
        cues = [fold(c) for c in (contrast.get("frame") or {}).get("cues", [])]
        particles = sorted(set(self.case_particles) | {p for group in self.slot_particles for p in group}
                           | set((self.count_question or {}).get("delimiters", []))
                           | {row["from"] for row in self.particle_variants if row.get("from")}, key=len, reverse=True)
        name_form = (self.holder_forms or {}).get("name")
        verbs = self._declared_verb_words()
        marks = "".join(self.clause_grammar.get("question_marks", []))
        spans = [(m.group(), m.start(), m.end()) for m in re.finditer(r"[^\s,.!?？。…]+", text)]
        low = [fold(w) for w, _s, _e in spans]
        tokens, at = [], 0
        while at < len(spans):
            word, start, end = spans[at]
            asker = next((a for a in sorted(askers, key=len, reverse=True)
                          if low[at:at + len(a.split())] == a.split()), None)
            if asker:
                width = len(asker.split())
                tokens.append({"text": " ".join(w for w, _s, _e in spans[at:at + width]), "stem": asker,
                               "span": [start, spans[at + width - 1][2]], "kind": "asker"})
                at += width
                continue
            stem = next((word[:-len(p)] for p in particles if word.endswith(p) and len(word) > len(p)), word)
            row = {"text": word, "stem": stem, "span": [start, end], "kind": "word"}
            value = parse_numeral(fold(word), numerals) if not word.isdigit() else int(word)
            for unit in units if value is None else []:
                head = word[:word.find(unit)] if word.find(unit) > 0 else ""
                if head and (head.isdigit() or parse_numeral(head, numerals) is not None):
                    value = int(head) if head.isdigit() else parse_numeral(head, numerals)
                    break
            counter = any(word == u or (word.startswith(u) and word[len(u):] in
                                        (self.count_question or {}).get("copula", []) + particles) for u in units)
            if value is not None:
                row.update(kind="number", value=str(value))
            elif counter:
                row["kind"] = "counter"
            elif self._protected_kind(word) == "negation" or fold(word) in cues:
                row["kind"] = "marker"
            elif fold(word) in verbs or fold(stem) in verbs:
                row["kind"] = "verb"
            elif name_form and re.fullmatch(name_form, word) and not re.fullmatch(name_form, word.lower()):
                row["kind"] = "name"        # (a name form that tells names apart by their letters' case)
            tokens.append(row)
            at += 1
        question = text.rstrip().endswith(tuple(marks)) or any(t["kind"] == "asker" for t in tokens)
        markers = [t for t in tokens if t["kind"] == "marker"]
        opened = (["holder", "thing"] if question else []) + (["event"] if markers else [])
        return {"text": text.strip(), "tokens": tokens, "question": question,
                "numbers": [t for t in tokens if t["kind"] == "number"], "markers": markers,
                "verb": next((t for t in tokens if t["kind"] == "verb"), None), "open": opened}

    def parse(self, text, *, partial=False, events=False, verbs=None, repair=False, _diagnostics=None,
              _exclude=(), _used=None, open_slots=False, _entry_selection=False):
        """``events`` 를 켜면 아무 사례도 못 읽은 구절을 **사건 꼴**로도 본다.

        조사가 자리를 짚고 남은 한 낱말이 움직임인 꼴이다. 뜻은 여기서 안
        정한다 — 쓰인 낱말을 그대로 담고, 설명받은 어간과 잇는 일은 대화
        쪽에서 한다. 이 문을 열지 않으면 뜻을 모르는 말을 만났을 때 **무엇을**
        모르는지 짚어 줄 수 없다.

        ``verbs`` 는 설명받은 말들의 꼴 → ``{어간, 물음}`` 이다. **무슨 동사인가
        만으로는 모자란다** — 물어본 것인지 실제로 일어난 일인지가 같이 와야
        `민수가 지연에게 베풉니까` 가 구슬을 옮기지 않는다.
        """
        from marco.language.hangul import clause_spans
        # A relative clause that states a holder's amount is its own clause
        # (문장분리.relative_clauses): said first, then the clause it modified.
        forced = []
        _frames = self.data.get("predicate_frames")
        v2 = isinstance(_frames, dict) and _frames.get("schema") == "predicate-frames-v2"
        whole_sel, whole_literal, original_text = None, text, text
        if v2:
            # v2 never calls the v1 declaration; the actual whole-phase selection validates it.
            # The matching literal drops outer whitespace and at most ONE selected terminal /
            # question mark; the exact typed text stays the source of that view.
            whole_literal = text.strip()
            _terms = [m for m in [*(_frames.get("terminators") or []),
                                  *self.clause_grammar.get("question_marks", [])] if isinstance(m, str) and m]
            for _mark in sorted(_terms, key=len, reverse=True):
                if whole_literal.endswith(_mark) and len(whole_literal) > len(_mark):
                    whole_literal = whole_literal[:-len(_mark)].rstrip()
                    break
            whole_sel = self._clause_selection(whole_literal, source=text, phase="whole", exclude=_exclude)
            whole_route = whole_sel["route"]
            if (whole_route["kind"] == "flat" and len(whole_route["flat_candidates"]) == 1
                    and whole_sel["meanings"]):
                _lead = len(text) - len(text.lstrip())
                forced = [{"start": _lead, "end": _lead + len(whole_literal), "text": whole_literal}]
        elif "predicate_frames" in self.data:
            # The original source is read by the declaration before any rewrite or segmentation.
            from marco.language.frames import declared_clause
            owned_source = declared_clause(self, text)
            if owned_source is not None:
                whole_span = {"start": 0, "end": len(text), "text": text}
                if owned_source[0] != "ok":
                    (_diagnostics if _diagnostics is not None else []).append(
                        {"reason": "declared_clause_hold", "evidence": whole_span, "detail": owned_source[1]})
                    return None
                forced = [whole_span]
        source_text = str(text) if _entry_selection else None
        if not forced and (not v2 or whole_sel["route"]["kind"] in ("none", "legacy")):
            # v2: a genuinely unowned whole keeps the native relative grammar (the entry gap
            # relative_source_offset_unproven already marks the synthetic rewrite).
            text = self._relative_clauses(text)
        rewritten = v2 and text != original_text
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
        diag_start = len(diagnostics)
        unrecognized = False
        # Only a fully recognized prefix authorizes a soft clause boundary.
        # A failed suffix guess (e.g. a noun ending in 고) never drops source text.
        cache, derivations = {}, {}
        # a clause reading after _owner_items -> the reading _clause_meanings gave (what ``readings`` leaves out)
        self._owner_origin = {}

        sources = {}

        selections = {}
        if whole_sel is not None and not rewritten:
            # The actual whole bundle is the same view (canonical literal + original source + exclude).
            sources[whole_literal] = original_text
            selections[(whole_literal, original_text, tuple(_exclude))] = whole_sel

        def selection(literal, source=None, use_source=False):
            # one actual selection per literal + typed source view + exclude (None source = literal)
            src = source if use_source else sources.get(literal)
            key = (literal, src if src is not None else literal, tuple(_exclude))
            if key not in selections:
                selections[key] = self._clause_selection(literal, source=src, phase="clause",
                                                         exclude=_exclude)
            return selections[key]

        def declared_owned(literal):
            if "predicate_frames" not in self.data:
                return None
            if v2:
                if rewritten:
                    return None         # synthetic relative slices are unowned legacy text
                route = selection(literal)["route"]
                if route["kind"] in ("blocked", "segment"):
                    # a selected hypothetical prefix over an exact typed core that itself
                    # reads as a guard / query is not an unowned segment: the fresh core
                    # proof (same original boundary) is consulted before holding
                    _candidate, marker = without_hypothetical_prefix(literal)
                    if marker:
                        return None
                    return ("hold", route.get("reason"))
                return None
            from marco.language.frames import declared_clause
            return declared_clause(self, sources.get(literal, literal))

        def guard_scoped(sel):
            # only a selected guard / query reading may stand under a hypothetical prefix
            records = sel.get("records")
            items = records.values() if isinstance(records, dict) else (records or [])
            for record in items:
                if not isinstance(record, dict):
                    continue
                scope = record.get("grammar_scope")
                if (record.get("reader_kind") in ("guard", "query")
                        or (isinstance(scope, dict) and scope.get("kind") in ("guard", "query"))):
                    return True
            return False

        def without_hypothetical_prefix(literal):
            if not v2 and declared_owned(literal) is not None:
                return literal, None        # the declaration owns its operator prefixes
            leading = literal[:len(literal) - len(literal.lstrip())]
            body = literal[len(leading):]
            for prefix in self.hypothetical_prefixes:
                if (body.startswith(prefix) and len(body) > len(prefix)
                        and body[len(prefix)].isspace()):
                    core = leading + body[len(prefix):].lstrip()
                    if not v2 or rewritten:
                        return core, prefix
                    # v2: the exact typed core (same original boundary) must itself read as a guard
                    # or query; an ordinary asserted/flat core is never admitted under the prefix.
                    src = sources.get(literal)
                    core_source = None
                    if src is not None:
                        s_body = src.lstrip()
                        if (s_body.startswith(prefix) and len(s_body) > len(prefix)
                                and s_body[len(prefix)].isspace()):
                            core_source = s_body[len(prefix):].lstrip()
                    sel = selection(core, source=core_source, use_source=True)
                    if sel["meanings"] and sel["route"]["kind"] not in ("blocked", "segment") \
                            and guard_scoped(sel):
                        return core, prefix
                    return literal, None
            return literal, None

        matched_examples = {}

        def meanings(literal):
            if literal not in cache and v2 and not rewritten:
                sel = selection(literal)
                if not sel["meanings"]:
                    # a segment / unsupported-scope route over a selected prefix is still
                    # consulted: the marker is only returned when the exact typed core
                    # proves as a guard / query under the original boundary
                    candidate, marker = without_hypothetical_prefix(literal)
                    if marker:
                        # the proven core bundle is transferred to the prefixed literal; its
                        # source record stays the core view
                        sel = selection(candidate, source=(sources.get(literal) or "").lstrip()
                                        [len(marker):].lstrip() if sources.get(literal) else None,
                                        use_source=True)
                derivations[literal] = sel["derivations"]
                matched_examples[literal] = sel["matched"]
                cache[literal] = sel["meanings"]
            if literal not in cache:
                derivations[literal] = {}
                matched_examples[literal] = {}
                candidate, _marker = without_hypothetical_prefix(literal)
                cache[literal] = self._clause_meanings(candidate, derivations=derivations[literal],
                                                       matched=matched_examples[literal], exclude=_exclude,
                                                       source=sources.get(literal))
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
            from marco.language.frames import read_event
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
        if v2 and not rewritten:
            whole = whole_literal       # the canonical selected literal; its source is the original text
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
            return bool(repair and self.repair and not (v2 and declared_owned(literal) is not None)
                        and (literal + ",") in text and self._repair(literal)[0])

        last_read = None        # (text, asserted rows) of the clause read just before
        anchor = None           # ((clauses, diagnostics) seen then, (typed text, rows)) of a plain count clause
        spans = (forced or clause_spans(text, self.clause_grammar, commas=True,
                                     accept_prefix=complete_prefix,
                                     inflected_boundary=lambda word: (
                                         self._inflected_boundary(word)
                                         or bool((verbs or {}).get(word, {}).get("조건")))))
        held = set()
        if v2 and not rewritten:
            # Original-source gaps: only selected terminal / separators / after-clause markers are consumed.
            # (never applied to synthetic relative slices: their offsets are not original)
            spans = list(spans)
            terminals = [m for m in [*(_frames.get("terminators") or []),
                                     *self.clause_grammar.get("question_marks", [])] if isinstance(m, str) and m]
            joiners = sorted([m for m in [*(_frames.get("separators") or []),
                                          *self.clause_grammar.get("after_clause_markers", [])]
                              if isinstance(m, str) and m], key=len, reverse=True)

            def gap_unread(gap, terminal):
                rest = gap.strip()
                if terminal:
                    for mark in sorted(terminals, key=len, reverse=True):
                        if rest.startswith(mark):
                            rest = rest[len(mark):]
                            break
                while True:
                    rest = rest.strip()
                    for mark in joiners:
                        if rest.startswith(mark):
                            rest = rest[len(mark):]
                            break
                    else:
                        return bool(rest)

            previous_end = 0
            for position, span in enumerate(spans):
                if gap_unread(text[previous_end:span["start"]], position > 0):
                    held.update({position, position - 1} - {-1})
                previous_end = span["end"]
            if spans and gap_unread(text[previous_end:], True):
                held.add(len(spans) - 1)
        for span_no, evidence in enumerate(spans):
            if span_no in held:
                diagnostics.append({"reason": "declared_clause_hold", "evidence": evidence,
                                    "detail": "unread_source_gap"})
                unrecognized = True
                continue
            if "predicate_frames" in self.data:
                from marco.language.frames import declared_source
                typed = declared_source(self, text, evidence)
                if (v2 and not rewritten and evidence["text"] == whole_literal
                        and typed.strip() == original_text.strip()):
                    typed = original_text   # same actual whole view: original source, cached bundle
                if typed != sources.get(evidence["text"], evidence["text"]):
                    sources[evidence["text"]] = typed
                    cache.pop(evidence["text"], None)
                owned = declared_owned(evidence["text"])
                if owned is not None and not meanings(evidence["text"]):
                    # No normalization, repair, gapping or event reading may rescue it.
                    diagnostics.append({"reason": "declared_clause_hold", "evidence": evidence,
                                        "detail": owned[1] if owned[0] == "hold" else "rejected"})
                    unrecognized = True
                    continue
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
            if (not unique and anchor is not None and anchor[0] == (len(clauses), len(diagnostics))
                    and not any(text[evidence["end"]:].lstrip().startswith(mark)
                                for mark in self.clause_grammar.get("question_marks", []))):
                # A clause with no actor of its own after a stated count of one holder is that holder's
                # (문장분리.subject_continuity); it is read by the same rules as if said with the holder.
                inherited = self._inherited_subject(evidence["text"], *anchor[1])
                read = (self._owner_items(meanings(inherited), inherited, derivations, matched_examples)
                        if inherited is not None else {})
                if len(read) == 1:
                    unique = read
                    # the normal reader trace (ending, polarity, rule) survives; the continuity is a note
                    derivations[evidence["text"]] = {
                        key: {**((derivations.get(inherited) or {}).get(key) or {}),
                              "subject_continuity": "declared-subject-continuity-v1", "inherited_from": inherited}
                        for key in read}
                    matched_examples[evidence["text"]] = dict(matched_examples.get(inherited, {}))
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
                from marco.language.frames import _marked
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
                from marco.language.frames import asks, read_event
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
            # Only a plain positive reading (one triple, no modality or polarity) can lend its holder to the next clause.
            trace = (derivations.get(evidence["text"]) or {}).get(only[0][0]) or {}
            pair = only[0][1].get("triple", [None])[0] if isinstance(only[0][1].get("triple"), list) else None
            anchor = (((len(clauses), len(diagnostics)), (evidence["text"], last_read[1], pair))
                      if last_read is not None and set(only[0][1]) == {"triple"}
                      and not trace.get("subject_continuity")
                      and trace.get("ending") not in self.condition_endings
                      and trace.get("rule") != "declared-subject-continuity-v1" else None)
        if unrecognized:
            def structural_fallback():
                # N1a1: one fully unmatched original span, read once by the selected declaration.
                if not (v2 and events and partial and not rewritten and not open_slots and not _exclude):
                    return None
                if held or len(spans) != 1 or clauses or 수선 or defined or invoked or 조건:
                    return None
                route = whole_sel["route"]
                if (not isinstance(route, dict) or route.get("kind") != "none"
                        or route.get("predicate_hits") or whole_sel["meanings"]):
                    return None
                evidence = spans[0]
                lead = len(text) - len(text.lstrip())
                if (evidence["start"] != lead or evidence["end"] != lead + len(whole_literal)
                        or evidence["text"] != whole_literal):
                    return None
                fresh = diagnostics[diag_start:]
                if (len(fresh) != 1 or fresh[0].get("reason") != "unrecognized_clause"
                        or fresh[0].get("evidence") != evidence):
                    return None
                declaration = self.language_pack.get("selected_action_surface")
                if not (isinstance(declaration, dict) and set(declaration) == {"surface", "binding"}
                        and isinstance(declaration["surface"], dict)
                        and isinstance(declaration["binding"], dict)):
                    return None
                from marco.language.frames import asks, read_unknown_action
                if asks(whole_literal, self.negation, verbs):
                    return None
                body = whole_literal.lstrip()
                for prefix in self.hypothetical_prefixes:
                    if (body.startswith(prefix) and len(body) > len(prefix)
                            and body[len(prefix)].isspace()):
                        return None
                neg = self.negation or {}
                neg_forms = set(neg.get("forms", ()) or ())
                neg_particles = set(neg.get("particles", ()) or ())
                neg_contractions = set((neg.get("contractions") or {}).keys())
                # the exact selected negation 연결 forms (only when declared non-empty; no invented words)
                _links = neg.get("연결")
                neg_links = ({_links} if isinstance(_links, str) and _links
                             else {l for l in _links if isinstance(l, str) and l}
                             if isinstance(_links, (list, tuple, set)) else set())
                for token in whole_literal.split():
                    core = token.strip(".,!?\"'")
                    # a protected negation OR scope token never becomes an unknown action reading
                    if (self._protected_kind(token) in ("negation", "scope") or core in neg_forms
                            or core in neg_links or core.lower() in neg_particles
                            or core.lower() in neg_contractions):
                        return None
                    if any(core.endswith(e) and len(core) > len(e) for e in self.condition_endings):
                        return None
                source = str(original_text)
                # Selected _frames.operators phrases are declared operators, never unknown role values.
                # Same matching semantics as frames._declared_route: whole phrase over the original Unicode
                # source, nonword boundaries, re.escape, optional ignore_case. A malformed operator
                # declaration refuses here instead of inventing per-word meaning.
                _operators = _frames.get("operators")
                if _operators is not None:
                    if not isinstance(_operators, list):
                        return None
                    _flags = re.IGNORECASE if self.data.get("ignore_case") else 0
                    for _operator in _operators:
                        _phrase = _operator.get("text") if isinstance(_operator, dict) else _operator
                        if not (isinstance(_phrase, str) and _phrase.strip()):
                            return None
                        if re.search(r"(?<!\w)" + re.escape(_phrase) + r"(?!\w)", source, _flags):
                            return None
                reading = read_unknown_action(source, declaration["surface"])
                if not (isinstance(reading, dict) and reading.get("schema") == "unknown-action-reading-v1"
                        and reading.get("status") == "read" and reading.get("search_complete") is True
                        and reading.get("truncated") is False and reading.get("gaps") == []):
                    return None
                unknown = reading.get("unknown_text")
                candidates = reading.get("role_candidates")
                if not (isinstance(unknown, str) and unknown and isinstance(candidates, list) and candidates):
                    return None
                if unknown in (verbs or {}):
                    return None
                for found in (verbs or {}).values():
                    if (found.get("stem") if isinstance(found, dict) else found) == unknown:
                        return None
                maps = []
                for candidate in candidates:
                    bindings = candidate.get("bindings") if isinstance(candidate, dict) else None
                    if not isinstance(bindings, list) or not bindings:
                        return None
                    row = {}
                    for binding in bindings:
                        if not isinstance(binding, dict):
                            return None
                        slot, value, span = binding.get("slot"), binding.get("value"), binding.get("span")
                        if not (isinstance(slot, str) and slot and isinstance(value, str) and value
                                and isinstance(span, list) and len(span) == 2
                                and all(type(x) is int for x in span)
                                and 0 <= span[0] < span[1] <= len(source)
                                and source[span[0]:span[1]] == value):
                            return None
                        if slot in row:
                            return None
                        row[slot] = value
                    maps.append(row)
                shared = {slot: value for slot, value in maps[0].items()
                          if all(slot in other and other[slot] == value for other in maps[1:])}
                event = {"verb": unknown, "꼬리": "", "자리": shared, "자리후보": maps,
                         "잘림": False, "structural_reading": copy.deepcopy(reading),
                         "selected_action_binding": copy.deepcopy(declaration["binding"])}
                built = {"facts": [], "query": None, "정의": [], "사건": [event], "가정사건": [],
                         "조건": [], "가정": [], "원인": [], "이유물음": [], "수선": [], "사건정정": []}
                if _entry_selection:
                    built["entry_selection"] = {
                        "schema": "marco-entry-selection-v1", "scope": "known_selected_input_clauses",
                        "status": "partial", "coordinate_space": "parser_view", "items": [],
                        "gaps": [{"clause_ordinal": 0, "code": "structural_origin_unproven",
                                  "span": [evidence["start"], evidence["end"]],
                                  "selected_action_binding": copy.deepcopy(declaration["binding"])}]}
                return built

            # shape / gap checks inside structural_fallback refuse by returning None;
            # an unexpected error (MemoryError, NameError, ...) propagates instead of being masked
            fallback = structural_fallback()
            if fallback is not None:
                return fallback
            # asked for, what was recognised comes back as a partial reading with open slots (G7-Q)
            return {"partial": self.open_reading(text)} if open_slots else None

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
        previous_rows, previous_end, previous_parts = [], None, {}
        choices = []
        entry_items, entry_gaps, entry_ordinal = [], [], -1
        read_info, guard_at = [], []

        def carrier_for(sb_kind, evidence, key, meaning, certify):
            # Data-only proof lookup from the actual selected record; any mismatch -> None (proof absent).
            if not _entry_selection or text != original_text:
                return None
            plain = self._sb_plain(original_text)
            if plain is None:
                return None
            bundle = selection(evidence["text"])
            if not isinstance(bundle, dict):
                return None
            records = bundle.get("records")
            if not isinstance(records, dict):
                return None
            origin_map = getattr(self, "_owner_origin", {})
            rec = None
            for k in dict.fromkeys((key, origin_map.get(key, key))):
                cand = records.get(k)
                if (isinstance(cand, dict) and cand.get("meaning") == meaning
                        and cand.get("meaning_key") in (k, key)):
                    rec = cand
                    break
            if rec is None and sb_kind == "positive_fact":
                rec = self._sb_flat_consequent_record(bundle, evidence, meaning)
            if rec is None or not all(isinstance(rk, str) for rk in rec):
                return None
            import json as _json
            try:
                dumped = _json.dumps(rec, ensure_ascii=False, allow_nan=False)
                if len(dumped.encode('utf-8')) > 65536:
                    return None
                rec = _json.loads(dumped)
            except (TypeError, ValueError, RecursionError):
                return None
            if type(rec) is not dict or len(rec) != 11:
                return None
            src = rec.get('source')
            if type(src) is not str:
                return None
            start, end = evidence['start'], evidence['end']
            if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(plain)):
                return None
            core = plain[start:end]
            if core != evidence['text']:
                return None
            lead = len(src) - len(src.lstrip())
            body = src.strip()
            if not body.startswith(core):
                return None
            rest = body[len(core):]
            if rest:
                marks = set()
                frames = self.data.get('predicate_frames')
                declared_marks = list(frames.get('terminators') or []) if isinstance(frames, dict) else []
                declared_marks += list(self.clause_grammar.get('question_marks', []))
                for mk in declared_marks:
                    if isinstance(mk, str) and mk:
                        marks.add(mk)
                if rest.strip() not in marks:
                    return None
            lo = start - lead
            if lo < 0 or lo + len(src) > len(plain) or plain[lo:lo + len(src)] != src:
                return None
            n = len(core)
            caps = rec.get('capture_spans')
            if type(caps) is not dict or not caps:
                return None
            newcaps = {}
            for cname, citem in caps.items():
                if type(citem) is not dict:
                    return None
                sp, val = citem.get('span'), citem.get('value')
                if (type(sp) is not list or len(sp) != 2 or not all(type(x) is int for x in sp)
                        or type(val) is not str):
                    return None
                ca, cb = sp[0] - lead, sp[1] - lead
                if not 0 <= ca < cb <= n or core[ca:cb] != val:
                    return None
                newcaps[cname] = {'value': val, 'span': [ca, cb]}
            fixed, at = [], 0
            for fa, fb in sorted(ci['span'] for ci in newcaps.values()):
                if fa > at:
                    fixed.append([at, fa])
                at = max(at, fb)
            if at < n:
                fixed.append([at, n])
            scope = rec.get('grammar_scope')
            if scope is not None:
                if type(scope) is not dict or scope.get('scope') != [0, len(src)]:
                    return None
                scope = {**scope, 'scope': [0, n]}
            shortened = dict(rec)
            shortened['source'] = core
            shortened['capture_spans'] = newcaps
            shortened['fixed_spans'] = fixed
            shortened['grammar_scope'] = scope
            if self.verify_selected_binary_witness(core, shortened, sb_kind) is None:
                return None
            cert = None
            if certify:
                cert = self.make_selected_binary_certificate(plain, [start, end], shortened, sb_kind)
                if cert is None:
                    return None
            return shortened, cert
        if _entry_selection and source_text != text:
            entry_gaps.append({"clause_ordinal": None, "code": "relative_source_offset_unproven"})

        def entry_origin(index):
            # Detached validated row of the already-selected entry; metadata trouble only becomes a gap.
            vector = getattr(self, "_entry_origins", None)
            if not isinstance(index, int) or isinstance(index, bool):
                return None, "origin_index_unavailable"
            if vector is None:
                return None, "origin_unavailable"
            if not isinstance(vector, list):
                return None, "origin_invalid"
            if len(vector) != len(self.data["examples"]):
                return None, "origin_alignment_invalid"
            if not 0 <= index < len(vector):
                return None, "origin_index_unavailable"
            try:
                from marco.language.entry_origins import validated_entry_origin
                origin = validated_entry_origin(vector[index])
            except ValueError:
                return None, "origin_invalid"
            if origin is None:
                return None, "origin_unknown"
            if origin["graph_binding"] is None:
                return origin, "binding_unknown"
            return origin, None

        for options, evidence in clauses:
            entry_ordinal += 1
            facts_before, ordinary_query = len(facts), False
            meaning = options[0]
            key = json.dumps(meaning, sort_keys=True, ensure_ascii=False)
            if _used is not None:
                _used.append(getattr(self, "_owner_origin", {}).get(key, key))
            normalization = derivations.get(evidence["text"], {}).get(key)
            if normalization:
                evidence = {**evidence, "normalization": normalization}
            stated = asserted(meaning)
            if _entry_selection:
                read_info.append((evidence, key, meaning, normalization))
            # The holder and the thing of each row, as the example's slots named them ([holder, thing]): the
            # conversation's graph takes its nodes from these, never from splitting the joined key (G7-S)
            raw = [meaning["triple"]] if "triple" in meaning else list(meaning.get("triples") or [])
            parts_of = [{"holder": row[0][0], "thing": row[0][1]}
                        if isinstance(row, list) and row and isinstance(row[0], list) and len(row[0]) == 2
                        and all(isinstance(w, str) and w.strip() for w in row[0]) else None for row in raw]
            # 조건 맺음으로 읽힌 절은 **일어난 일이 아니다.** 사실로 적으면
            # `5개보다 많으면` 이 "많다" 는 단정이 되고, 뒤의 일도 그냥 일어난
            # 일이 된다. 어느 맺음이 조건인지는 문법이 선언한다 — 낱말이 아니다.
            if stated and (normalization or {}).get("ending") in self.condition_endings:
                _candidate, marker = without_hypothetical_prefix(evidence["text"])
                조건 += [{"triple": triple, "evidence": evidence, "kind": "guard",
                          "marker": marker}
                         for triple in stated]
                if _entry_selection:
                    entry_gaps.append({"clause_ordinal": entry_ordinal, "code": "condition_scope_uncollected"})
                    guard_at.append(len(read_info) - 1)
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
                # A subject marked with an undecided particle (도) may be another holder (모루도: Moru too) or
                # another thing of the topic (고구마도: sweet potatoes too), and the particle stays in the name:
                # the clause is not read (생략.topic_continuity.undecided_particles).
                undecided = ((self.ellipsis or {}).get("topic_continuity") or {}).get("undecided_particles") or []
                if any(isinstance(row["subject"], str) and any(row["subject"].endswith(p) and len(row["subject"]) > len(p)
                                                               for p in undecided) for row in inherited):
                    diagnostics.append({"reason": "undecided_subject", "evidence": evidence})
                    return None
                if inherited:
                    evidence = {**evidence, "ellipsis": inherited}
                    for row in inherited:
                        if row["index"] < len(parts_of):
                            parts_of[row["index"]] = row["parts"]
            if stated and in_turn and self.ellipsis.get("omitted_subject") == "same_relation":
                # 그리고 은호에게 네 장을 주었다: a clause whose example leaves its subject out takes the subject of
                # the clause before it in the turn with the same relation (the giver who gave just before)
                carried = []
                for index, row in enumerate(stated):
                    prior = next((p for p in previous_rows if row[0] is None and p[1] == row[1]
                                  and isinstance(p[0], str)), None)
                    carried.append([prior[0]] + list(row[1:]) if prior else row)
                    if prior and index < len(parts_of):
                        parts_of[index] = previous_parts.get(prior[0])
                stated = carried
            previous_rows, previous_end = (stated or []), evidence["end"]
            previous_parts = {row[0]: part for row, part in zip(stated or [], parts_of) if part and isinstance(row[0], str)}
            if stated:
                role_bindings = meaning.get("role_bindings", [])
                example_index = matched_examples.get(evidence["text"], {}).get(key)
                if example_index is None and (normalization or {}).get("repair"):
                    example_index = normalization["repair"].get("rule_index")
                event_verb = (self.data["examples"][example_index].get("event_verb")
                              if example_index is not None else None)
                for position, triple in enumerate(stated):
                    said_key = triple[0]
                    triple = [self.canonical_name(triple[0])] + list(triple[1:])
                    fact = {"triple": triple, "evidence": evidence}
                    part = parts_of[position] if position < len(parts_of) else None
                    if part is None and isinstance(said_key, str) and not meaning.get("places"):
                        part = self._cased_parts(said_key) or self._typed_parts(said_key, evidence["text"])
                    if part and isinstance(said_key, str) and triple[0] == said_key \
                            and part.get("key", " ".join(w for w in (part["holder"], part["thing"]) if w)) == said_key:
                        fact["parts"] = dict(part)
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
                ordinary_query = True
                if isinstance(query, list):
                    for request in query:
                        if isinstance(request, dict) and isinstance(request.get("triple"), list):
                            request["triple"] = joined(request["triple"])
                            request["triple"][0] = self.canonical_name(request["triple"][0])
            else:
                diagnostics.append({"reason": "multiple_queries_or_invalid_meaning", "evidence": evidence})
                return None
            if _entry_selection:
                new_facts = list(range(facts_before, len(facts)))
                new_query = list(range(len(query))) if ordinary_query and isinstance(query, list) else []
                if not new_facts and not new_query:
                    entry_gaps.append({"clause_ordinal": entry_ordinal, "code": "uncollected_scope"})
                else:
                    index = matched_examples.get(evidence["text"], {}).get(key)
                    if index is None and (normalization or {}).get("repair"):
                        index = normalization["repair"].get("rule_index")
                    origin = None
                    if index is None:
                        entry_gaps.append({"clause_ordinal": entry_ordinal, "code": "uncollected_index"})
                    else:
                        origin, code = entry_origin(index)
                        if code:
                            entry_gaps.append({"clause_ordinal": entry_ordinal, "code": code})
                    derivation = None
                    if normalization:
                        try:
                            derivation = json.loads(json.dumps(normalization, allow_nan=False))
                        except (TypeError, ValueError):
                            entry_gaps.append({"clause_ordinal": entry_ordinal, "code": "derivation_unavailable"})
                    entry_items.append({"clause_ordinal": entry_ordinal,
                                        "span": [evidence["start"], evidence["end"]],
                                        "compiler_index": index, "origin": origin,
                                        "targets": {"facts": new_facts, "query": new_query},
                                        "derivation": derivation})
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
        result = ({"facts": facts, "query": query, "정의": defined,
                   "사건": [event for event in invoked if not event.get("hypothetical")],
                   "가정사건": 가정사건,
                   "조건": 조건, "가정": 가정, "원인": 원인, "이유물음": 이유물음,
                   "수선": 수선, "사건정정": 사건정정}
                  if usable else None)
        if result is not None and _entry_selection:
            result["entry_selection"] = {
                "schema": "marco-entry-selection-v1", "scope": "known_selected_input_clauses",
                "status": "partial", "coordinate_space": "parser_view",
                "items": entry_items, "gaps": entry_gaps}
            plain_only = not (defined or invoked or 원인 or 이유물음 or 수선 or 사건정정 or 가정 or 가정사건)
            if (plain_only and len(clauses) == 1 and len(entry_items) == 1 and len(read_info) == 1
                    and not guard_at and not 조건):
                ev, k, m, norm = read_info[0]
                item = entry_items[0]
                sb_kind = None
                if len(facts) == 1 and query is None and facts[0].get("polarity") is False:
                    sb_kind = "negative_fact"
                elif (not facts and isinstance(query, list) and len(query) == 1
                        and isinstance(m.get("query"), list) and len(m["query"]) == 1
                        and isinstance(m["query"][0], dict)
                        and m["query"][0].get("polarity") is False):
                    sb_kind = "negative_query"
                got = carrier_for(sb_kind, ev, k, m, True) if sb_kind else None
                if got is not None and got[1] is not None:
                    cert = got[1]
                    cm = cert["meaning"]
                    if sb_kind == "negative_fact":
                        rows = asserted(cm)
                        ok = (len(rows) == 1 and cm.get("polarity") is False
                              and [self.canonical_name(rows[0][0])] + list(rows[0][1:]) == facts[0]["triple"])
                    else:
                        rows = cm.get("query")
                        ok = (isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
                              and rows[0].get("polarity") is False
                              and isinstance(rows[0].get("triple"), list))
                        if ok:
                            tri = joined(rows[0]["triple"])
                            tri[0] = self.canonical_name(tri[0])
                            ok = (tri == query[0].get("triple")
                                  and rows[0].get("render") == query[0].get("render"))
                    if (ok and item["compiler_index"] is not None
                            and cert["compiler_index"] == item["compiler_index"]):
                        item["source_certificate"] = cert
            elif (plain_only and len(clauses) == 2 and len(entry_items) == 1 and len(read_info) == 2
                    and guard_at == [0] and len(조건) == 1 and 조건[0].get("kind") == "guard"
                    and 조건[0].get("marker") is None and query is None and len(facts) == 1
                    and facts[0].get("polarity", True) is True):
                gev, gk, gm, _gn = read_info[0]
                cev, ck, cm2, _cn = read_info[1]
                item = entry_items[0]
                grows, crows = asserted(gm), asserted(cm2)
                if (gev["end"] <= cev["start"] and gm.get("polarity", True) is True
                        and cm2.get("polarity", True) is True
                        and len(grows) == 1 and grows[0] == 조건[0]["triple"]
                        and len(crows) == 1
                        and [self.canonical_name(crows[0][0])] + list(crows[0][1:]) == facts[0]["triple"]):
                    gg = carrier_for("positive_guard", gev, gk, gm, True)
                    gc = carrier_for("positive_fact", cev, ck, cm2, False)
                    if gg is not None and gg[1] is not None and gc is not None:
                        gplain = self._sb_plain(original_text)
                        if gplain is not None:
                            조건[0]["source_original"] = gplain
                            조건[0]["source_certificate"] = gg[1]
                            item["source_witness"] = copy.deepcopy(gc[0])
        return result

    def _answer_negative(self, parsed, negatives):
        """Answer one authenticated signed negative query from directly asserted negative facts only."""
        from marco.reasoning.inference import bind, current_facts
        queries = parsed.get("query")
        if (type(queries) is not list or len(queries) != 1 or len(negatives) != 1
                or queries[0] is not negatives[0] or type(negatives[0]) is not dict):
            return None
        query = negatives[0]
        auth = parsed.get("selected_query_source")
        if (type(auth) is not dict or set(auth) != {"source_original", "source_certificate"}
                or type(auth["source_original"]) is not str
                or type(auth["source_certificate"]) is not dict):
            return None
        cert = auth["source_certificate"]
        verified = self.verify_selected_binary_certificate(auth["source_original"], cert)
        if (verified is None or verified.get("kind") != "negative_query"
                or cert.get("kind") != "negative_query"):
            return None
        meaning = cert.get("meaning")
        mrows = meaning.get("query") if type(meaning) is dict else None
        if type(mrows) is not list or not mrows or type(mrows[0]) is not dict:
            return None
        try:
            same = (json.dumps(query, sort_keys=True, ensure_ascii=False)
                    == json.dumps(mrows[0], sort_keys=True, ensure_ascii=False))
        except (TypeError, ValueError):
            return None
        if not same or query.get("polarity") is not False or mrows[0].get("polarity") is not False:
            return None
        triple, render = query.get("triple"), query.get("render")
        if (type(triple) is not list or len(triple) != 3
                or not all(type(term) is str for term in triple)
                or sum(1 for term in triple if term.startswith("?")) != 1
                or type(render) is not list or not all(type(part) is str for part in render)):
            return None
        try:
            facts, changes = current_facts(parsed["facts"], self.data.get("mutable_predicates", []),
                                           self.data.get("numeric_updates", {}))
        except (ValueError, KeyError, TypeError):
            return None
        found, positive = {}, set()
        for row in facts:
            if type(row) is not dict:
                continue
            fact = row.get("triple")
            if type(fact) is not list or len(fact) != 3:
                continue
            bindings = bind(triple, fact, {})
            if bindings is None:
                continue
            polarity = row.get("polarity", True)
            if type(polarity) is not bool:
                return None
            try:
                key = json.dumps(bindings, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                return None
            if polarity is False:
                if (row.get("modality", "asserted") != "asserted"
                        or not all(type(term) is str and not term.startswith("?") for term in fact)
                        or type(row.get("evidence")) is not dict):
                    return None
                found.setdefault(key, []).append((bindings, row))
            else:
                positive.add(key)
        if len(found) != 1 or set(found) & positive:
            return None
        unique = {}
        for item in next(iter(found.values())):
            try:
                ekey = json.dumps(item[1]["evidence"], sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                return None
            unique.setdefault(ekey, item)
        bindings, row = unique[sorted(unique)[0]]
        result = substitute(query, {k[1:]: v for k, v in bindings.items()})
        out = result.get("render")
        if type(out) is not list or not all(type(part) is str for part in out):
            return None
        return {"answer": "".join(out),
                "transitions": changes + [{"operation": "negative_evidence",
                                           "fact": list(row["triple"]), "polarity": False,
                                           "evidence": copy.deepcopy(row["evidence"])}]}

    def answer(self, parsed):
        from marco.reasoning.inference import bind, current_facts, proof
        signed = parsed.get("query")
        if type(signed) is list:
            negatives = [query for query in signed
                         if isinstance(query, dict) and query.get("polarity") is False]
            if negatives:
                return self._answer_negative(parsed, negatives)
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
                _compiled(r"\$([a-z][a-z0-9_]*)").sub(lambda matched: str(record.get(matched.group(1), matched.group(0))), part)
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
            from marco.reasoning.inference import leading_word_referent
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
                    if referent == triple[0] and self.ellipsis.get("thing_reference") == "trailing_word" \
                            and " " not in triple[0].strip():
                        # `지금 돌은 몇 개야`: the thing alone names the one subject that holds it (상자 돌)
                        holders = sorted({s for s, p in present if p == triple[1] and s.endswith(" " + triple[0])})
                        if len(holders) == 1:
                            referent = holders[0]
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
