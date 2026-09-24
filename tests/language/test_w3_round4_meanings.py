"""W3.5: reply plans for the meanings goal G4 adds in round 4.

The user as a holder, said in the person forms the language file declares over the
pack's own first person; places as holders; titled and relational holders said as
the user named them; a count of zero said as having none; a vague count said as
some, number unknown. Both languages.

No G4 request had landed when these plans were written, so each result here carries
the meaning block asked for in ``docs/requests/W3-1.md``. Every reply is still parsed
back with the pack before it is said. Where the pack does not yet read a form W3-1
asks for, two things are tested: with the pack as it is, the plainer form or a hold
(never an unchecked sentence); and with ``ReadsAs``, a stand-in parser that reads
that form as W3-1 asks (a phrase read as another before the pack's own parser runs),
the composed reply.

Every name and thing here is written for this file.
"""
import pytest

from marco.language.realizer import Realizer
from marco.language.realizer.grammar import Grammar
from marco.language.realizer.intent import holder_of
from marco.language.realizer.packs import Language, meaning_declarations
from pack_model import development_model

HOLD = {"english": "This answer is on hold.", "한국어": "답을 보류합니다."}


@pytest.fixture(autouse=True)
def own_models(monkeypatch):
    """A model a reply is realized with is registered for its language; a stand-in stays in its test."""
    from marco.language.realizer import packs
    monkeypatch.setattr(packs, "_registered", dict(packs._registered))


class ReadsAs:
    """The development pack model of ``language``, its parser reading each phrase in
    ``rewrites`` as another first: a stand-in for a pack reading W3-1 asks G4 for."""

    def __init__(self, language, rewrites):
        self._model = development_model(language)
        self.sources = self._model.sources
        self._rewrites = list(rewrites)

    def parser(self):
        return _Parser(self._model.parser(), self._rewrites)

    def __getattr__(self, name):
        return getattr(self._model, name)


class _Parser:
    def __init__(self, parser, rewrites):
        self._parser, self._rewrites = parser, rewrites

    def parse(self, text, *args, **kwargs):
        for said, read in self._rewrites:
            text = text.replace(said, read)
        return self._parser.parse(text, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._parser, name)


# The readings W3-1 asks for, as phrases the present pack already reads.
EN_READS = [("I have", "I has"), ("The warehouse", "Warehouse"), ("has no", "has 0"),
            ("My roommate Ivo", "Ivo"), (" put ", " gave "), (" in the warehouse", " to warehouse")]
KO_READS = [(" 씨", ""), ("하나도 없다", "0개이다"), ("에는", "는"), ("내 룸메이트 ", "")]


def answered(fact, asked=None, holders=None, said=""):
    meaning = {"act": "inform", "query": [fact[0], fact[1], "?n"], "asked": asked or [fact[0], fact[1], "?n"]}
    if holders:
        meaning["holders"] = holders
    evidence = {"start": 0, "end": len(said), "text": said, "turn": 0, "source": said}
    return {"status": "answered", "answer": "ENGINE", "meaning": meaning,
            "transitions": [{"fact": list(fact), "evidence": evidence}]}


def change(subject, before, after, said, turn=1):
    return {"operation": "quantity_update", "subject": subject, "predicate": "count", "before": before,
            "after": after, "delta": after - before,
            "evidence": {"start": 0, "end": len(said), "text": said, "turn": turn, "source": said}}


def recorded(changes, holders=None):
    meaning = {"act": "record", "reason": "observed_state", "changes": list(changes)}
    if holders:
        meaning["holders"] = holders
    return {"status": "observed", "answer": "ENGINE", "meaning": meaning, "transitions": list(changes)}


def compared(kind, subjects, **fields):
    meaning = dict({"act": "inform", "kind": kind, "subjects": list(subjects)}, **fields)
    return {"status": "answered", "answer": "ENGINE", "meaning": meaning, "transitions": []}


def vague(act, subject):
    return {"status": "observed" if act == "record" else "unresolved", "answer": "ENGINE",
            "meaning": {"act": act, "reason": "vague_count", "subject": subject}}


def say(result, language, model=None):
    """The reply and the realizer's report; a composed reply is exactly its sentence."""
    text, report = Realizer().realize_with_report(result, result["status"], model or "styles/%s.json" % language)
    assert report["realized"], report.get("reason")
    assert "ENGINE" not in (text or "")
    return text, report


def composed(result, language, model=None):
    text, report = say(result, language, model)
    assert not report["held"], [c.get("attempts") for c in report.get("clauses", []) if c.get("blocked")]
    return text


def held(result, language, model=None):
    text, report = say(result, language, model)
    assert report["held"] and text == HOLD[language]
    return report


# the declarations ------------------------------------------------------------------------

@pytest.mark.parametrize("language", ["english", "한국어"])
def test_the_users_own_forms_are_the_packs_first_person(language):
    person = Language(language).person()
    assert person["first"]["holder"] == development_model(language).parser().speaker_placeholder
    # The words the reading says the user with are forms the pack groups with its first person.
    for case in ("subject", "default"):
        assert person["user"][case] in person["first"]["forms"], case
    assert person["addressee"] and not set(person["addressee"].values()) & set(person["first"]["forms"])


def test_the_holder_kinds_are_declared_once_and_every_candidate_names_only_them():
    spec = meaning_declarations()["holders"]
    kinds = set(spec["kinds"]) | {spec["name"]}
    for language in ("english", "한국어"):
        for frame, candidates in Language(language).decl["expressions"].items():
            for candidate in candidates:
                for role, allowed in ((candidate.get("when") or {}).get("holder") or {}).items():
                    allowed = allowed if isinstance(allowed, list) else [allowed]
                    assert set(allowed) <= kinds, (language, frame, candidate["id"])


def test_the_user_is_the_conversation_languages_first_person_or_a_declared_holder():
    graph = {"fields": {}, "source": "한국어"}
    assert holder_of("나", graph) == {"kind": "speaker"}
    assert holder_of("I", graph) is None                    # the first person of another language
    assert holder_of("I", {"fields": {}, "source": "english"}) == {"kind": "speaker"}
    graph = {"fields": {"holders": {"Ivo": {"kind": "named", "said": "my roommate Ivo"},
                                    "Oda": {"kind": "friend"}}}, "source": "english"}
    assert holder_of("Ivo", graph) == {"kind": "named", "said": "my roommate Ivo"}
    assert holder_of("Oda", graph) is None                   # not a declared kind: a bare name


# the user as a holder -------------------------------------------------------------------

EN_USER = ReadsAs("english", EN_READS)


@pytest.mark.parametrize("result,said", [
    (answered(["I apricots", "count", "3"], asked=["she", "count", "?n"], said="I have 3 apricots"),
     "You have 3 apricots."),
    (answered(["I apricots", "count", "3"], said="I have 3 apricots"), "3 apricots."),
    (answered(["I apricots", "count", "1"], asked=["she", "count", "?n"], said="I have 1 apricot"),
     "You have 1 apricot."),
    (recorded([change("I apricots", 5, 3, "I gave Oda 2 apricots"), change("Oda apricots", 1, 3, "I gave Oda 2 apricots")]),
     "Recorded. Now you have 3 apricots and Oda has 3."),
    (recorded([change("Oda apricots", 5, 3, "Oda gave me 2 apricots"), change("I apricots", 1, 3, "Oda gave me 2 apricots")]),
     "Recorded. Now Oda has 3 apricots and you have 3 apricots."),
])
def test_english_says_the_user_as_you(result, said):
    assert composed(result, "english", EN_USER) == said


def test_english_holds_the_user_until_the_pack_reads_the_first_person():
    # The present pack does not read "I have 3 apricots.": the reply is held, not said unchecked.
    report = held(answered(["I apricots", "count", "3"], asked=["she", "count", "?n"], said="I have 3 apricots"),
                  "english")
    texts = [failure.get("text") for clause in report["clauses"] for attempt in clause["attempts"]
             for failure in (attempt.get("check") or {}).get("failures", [])]
    assert "I have 3 apricots." in texts


@pytest.mark.parametrize("result,said", [
    (compared("more", ["I plums", "Oda plums"], winner="I plums", values=[5, 3]), "You have more plums."),
    (compared("fewer", ["I plums", "Oda plums"], winner="I plums", values=[1, 3]), "You have fewer plums."),
    (compared("tie", ["I plums", "Oda plums"], value=4), "You and Oda both have 4 plums."),
    (compared("total", ["I plums", "Oda plums"], value=8), "You and Oda have 8 plums together."),
])
def test_english_compares_the_user_as_you(result, said):
    assert composed(result, "english") == said


@pytest.mark.parametrize("result,said", [
    (answered(["나 살구", "count", "3"], said="나는 살구가 3개 있어"), "3개 있으십니다."),
    (answered(["나 살구", "count", "3"], asked=["그", "count", "?n"], said="나는 살구가 3개 있어"), "3개 있으십니다."),
    (recorded([change("나 살구", 5, 3, "내가 오다에게 살구 2개 줬어"), change("오다 살구", 1, 3, "내가 오다에게 살구 2개 줬어")]),
     "반영했습니다. 이제 살구는 3개 있으시고, 오다는 3개입니다."),
    (recorded([change("오다 살구", 5, 3, "오다가 나에게 살구 2개 줬어"), change("나 살구", 1, 3, "오다가 나에게 살구 2개 줬어")]),
     "반영했습니다. 이제 오다 살구는 3개, 살구는 3개 있으십니다."),
    (compared("more", ["나 자두", "오다 자두"], winner="나 자두", values=[5, 3]), "자두는 더 많으십니다."),
    (compared("fewer", ["나 자두", "오다 자두"], winner="나 자두", values=[1, 3]), "자두는 더 적으십니다."),
])
def test_korean_leaves_the_user_unsaid_and_honours_them_in_the_predicate(result, said):
    # The present pack reads the user's own form ("나 살구는 3개 있다."), so no stand-in is needed.
    assert composed(result, "한국어") == said


def test_korean_holds_the_user_where_its_person_forms_declare_no_word():
    # A list of holders, or the user as a recipient, needs a word for the user the file does not declare.
    report = held(compared("tie", ["나 자두", "오다 자두"], value=4), "한국어")
    assert any("undeclared_person_form" in str(attempt.get("error"))
               for clause in report["clauses"] for attempt in clause["attempts"])


# titled and relational holders ----------------------------------------------------------

@pytest.mark.parametrize("language,model,result,said", [
    ("english", None, answered(["Lind pens", "count", "4"], asked=["he", "count", "?n"],
                               holders={"Lind": {"kind": "named", "said": "Mr. Lind"}}, said="Mr. Lind has 4 pens"),
     "Mr. Lind has 4 pens."),
    ("english", EN_USER, answered(["Ivo pens", "count", "2"], asked=["he", "count", "?n"],
                                  holders={"Ivo": {"kind": "named", "said": "my roommate Ivo"}},
                                  said="my roommate Ivo has 2 pens"),
     "Your roommate Ivo has 2 pens."),
    ("한국어", ReadsAs("한국어", KO_READS), answered(["린드 펜", "count", "4"], asked=["그", "count", "?n"],
                                                  holders={"린드": {"kind": "named", "said": "린드 씨"}},
                                                  said="린드 씨는 펜이 4개 있어"),
     "린드 씨는 4개입니다."),
    ("한국어", ReadsAs("한국어", KO_READS), answered(["이보 펜", "count", "2"], asked=["그", "count", "?n"],
                                                  holders={"이보": {"kind": "named", "said": "내 룸메이트 이보"}},
                                                  said="내 룸메이트 이보는 펜이 2개 있어"),
     "룸메이트 이보는 2개입니다."),
])
def test_a_named_holder_is_said_as_the_user_named_them(language, model, result, said):
    # The user's own first-person words turn to the one addressed (my -> your; 내 -> not said).
    assert composed(result, language, model) == said


def test_a_named_holder_the_pack_reads_back_otherwise_is_held():
    # The present Korean pack reads "린드 씨 펜" as the holder "린드 씨", not the key "린드".
    held(answered(["린드 펜", "count", "4"], asked=["그", "count", "?n"],
                  holders={"린드": {"kind": "named", "said": "린드 씨"}}, said="린드 씨는 펜이 4개 있어"), "한국어")


def test_a_named_holder_in_another_language_is_said_by_its_key():
    grammar = Grammar(Language("english"))
    value = {"text": "린드", "lang": "한국어", "kind": "agent", "holder": {"kind": "named", "said": "린드 씨"}}
    assert grammar.entity_words(value, register="formal", case="subject") == grammar.entity_words(value)


# places as holders ----------------------------------------------------------------------

@pytest.mark.parametrize("language,model,result,said", [
    ("english", EN_USER, answered(["warehouse crates", "count", "5"], asked=["it", "count", "?n"],
                                  holders={"warehouse": {"kind": "place"}}, said="The warehouse has 5 crates"),
     "The warehouse has 5 crates."),
    ("english", EN_USER, recorded([change("Tove crates", 5, 2, "Tove put 3 crates in the warehouse"),
                                   change("warehouse crates", 1, 4, "Tove put 3 crates in the warehouse")],
                                  holders={"warehouse": {"kind": "place"}}),
     "Recorded. Now Tove has 2 crates and the warehouse has 4."),
    ("한국어", ReadsAs("한국어", KO_READS), answered(["북쪽 창고 상자", "count", "5"], asked=["거기", "count", "?n"],
                                                  holders={"북쪽 창고": {"kind": "place"}},
                                                  said="북쪽 창고에는 상자가 5개 있어"),
     "북쪽 창고에는 5개 있습니다."),
    # The present Korean pack reads "북쪽 창고에는" with its particle: the place is said juxtaposed.
    ("한국어", None, answered(["북쪽 창고 상자", "count", "5"], asked=["거기", "count", "?n"],
                            holders={"북쪽 창고": {"kind": "place"}}, said="북쪽 창고에는 상자가 5개 있어"),
     "북쪽 창고는 5개입니다."),
    ("한국어", None, answered(["북쪽 창고 상자", "count", "5"], holders={"북쪽 창고": {"kind": "place"}},
                            said="북쪽 창고에는 상자가 5개 있어"),
     "5개입니다."),
])
def test_a_place_holds_things(language, model, result, said):
    assert composed(result, language, model) == said


def test_a_place_of_several_words_owns_the_compound_subject():
    from marco.language.realizer import meaning as mg
    fields = {"holders": {"north warehouse": {"kind": "place"}, "Tove": {"kind": "named", "said": "Ms. Tove"}}}
    prop = mg.fact_prop(["north warehouse crates", "count", "5"], "english", holders=mg.holder_keys(fields))
    assert prop["roles"]["owner"]["text"] == "north warehouse" and prop["roles"]["item"]["text"] == "crates"
    plain = mg.fact_prop(["north warehouse crates", "count", "5"], "english")
    assert plain["roles"]["owner"]["text"] == "north"          # without the declaration: the first word
    rows = [change("north warehouse crates", 5, 2, "x"), change("Tove crates", 1, 4, "x")]
    transfer = mg.transfer_props(rows, "english", mg.holder_keys(fields))[0]
    assert (transfer["roles"]["giver"]["text"], transfer["roles"]["receiver"]["text"],
            transfer["roles"]["item"]["text"]) == ("north warehouse", "Tove", "crates")


@pytest.mark.parametrize("language,giver,receiver,words", [
    ("english", {"kind": "place"}, None, ["took", "from", "the"]),
    ("english", None, {"kind": "place"}, ["put", "in", "the"]),
    ("english", {"kind": "place"}, {"kind": "place"}, ["were", "moved", "from", "the", "to"]),
    ("한국어", {"kind": "place"}, None, ["가져갔습니다"]),
    ("한국어", None, {"kind": "place"}, ["뒀습니다"]),
    ("한국어", {"kind": "place"}, {"kind": "place"}, ["옮겨졌습니다"]),
])
def test_a_transfer_with_a_place_takes_the_place_expression(language, giver, receiver, words):
    from marco.language.realizer.expression import candidates
    from marco.language.realizer.grammar import ClauseRealizer
    lang = Language(language)

    def holder(text, kind):
        return dict({"text": text, "lang": language, "kind": "agent"}, **({"holder": kind} if kind else {}))
    prop = {"frame": "transfer", "tense": "past", "polarity": True,
            "roles": {"giver": holder("Aki", giver), "receiver": holder("Bo", receiver),
                      "item": {"text": "crates", "lang": language, "kind": "thing"}, "amount": {"number": "3"}}}
    first = candidates(lang.decl, prop, register="formal", intent="INFORM")[0]
    said = ClauseRealizer(Grammar(lang)).realize(prop, first, register="formal").text(" ")
    assert all(word in said.split() for word in words), said
    assert first["id"] != "transfer_give"


# zero -----------------------------------------------------------------------------------

@pytest.mark.parametrize("language,model,result,said", [
    ("english", EN_USER, answered(["Tove quinces", "count", "0"], said="Tove has no quinces"), "No quinces."),
    ("english", EN_USER, answered(["Tove quinces", "count", "0"], asked=["she", "count", "?n"],
                                  said="Tove has no quinces"), "Tove has no quinces."),
    ("english", EN_USER, answered(["I quinces", "count", "0"], asked=["she", "count", "?n"],
                                  said="I have no quinces"), "You have no quinces."),
    ("english", EN_USER, recorded([change("Tove quinces", 2, 0, "Tove ate 2 quinces")]), "Recorded. Now Tove has no quinces."),
    ("한국어", ReadsAs("한국어", KO_READS), answered(["토베 모과", "count", "0"], said="토베는 모과가 하나도 없어"),
     "하나도 없습니다."),
    ("한국어", ReadsAs("한국어", KO_READS), answered(["토베 모과", "count", "0"], asked=["그", "count", "?n"],
                                                  said="토베는 모과가 하나도 없어"), "토베는 하나도 없습니다."),
    ("한국어", None, answered(["나 모과", "count", "0"], said="나는 모과가 하나도 없어"), "하나도 없으십니다."),
    ("한국어", ReadsAs("한국어", KO_READS), recorded([change("토베 모과", 2, 0, "토베가 모과 2개를 먹었어")]),
     "반영했습니다. 이제 토베 모과는 하나도 없습니다."),
])
def test_a_count_of_zero_is_said_as_none(language, model, result, said):
    if model is None:
        model = ReadsAs(language, KO_READS)
    assert composed(result, language, model) == said


@pytest.mark.parametrize("language,result,said", [
    ("english", answered(["Tove quinces", "count", "0"], said="Tove has 0 quinces"), "0 quinces."),
    ("english", answered(["Tove quinces", "count", "0"], asked=["she", "count", "?n"], said="Tove has 0 quinces"),
     "Tove has 0 quinces."),
    ("한국어", answered(["토베 모과", "count", "0"], said="토베는 모과가 0개 있어"), "0개입니다."),
])
def test_a_zero_the_pack_does_not_read_as_none_is_said_in_digits(language, result, said):
    text, report = say(result, language)
    assert text == said and not report["held"]
    tried = [clause for clause in report["clauses"] if clause.get("replaced")]
    assert tried and tried[0]["frame"] == "count_none"


WRONG_ZERO = ReadsAs("english", [("has no", "has 5")])


def test_none_is_said_only_when_the_pack_reads_it_as_zero():
    # A pack that read "has no" as a count of 5 would not confirm none: the digits are said.
    assert composed(answered(["Tove quinces", "count", "0"], said="Tove has no quinces"), "english", WRONG_ZERO) \
        == "0 quinces."


# vague counts ---------------------------------------------------------------------------

@pytest.mark.parametrize("language,result,said", [
    ("english", vague("record", "Una pears"), "Recorded. Una has some pears, but I do not know how many."),
    ("english", vague("hold", "Una pears"), "Una has some pears, but I do not know how many."),
    ("english", vague("hold", "I pears"), "You have some pears, but I do not know how many."),
    ("한국어", vague("record", "우나 배"), "반영했습니다. 우나는 배가 있지만 몇 개인지 알 수 없습니다."),
    ("한국어", vague("hold", "우나 배"), "우나는 배가 있지만 몇 개인지 알 수 없습니다."),
    ("한국어", vague("hold", "나 배"), "배가 있으시지만 몇 개인지 알 수 없습니다."),
])
def test_a_vague_count_is_said_as_some_number_unknown(language, result, said):
    text = composed(result, language)
    assert text == said
    # No number is said, and the number is said to be unknown (the pack's negation).
    assert not any(char.isdigit() for char in text)


def test_a_vague_count_without_a_holder_and_a_thing_is_not_planned():
    text, report = Realizer().realize_with_report(vague("hold", "pears"), "unresolved", "styles/english.json")
    assert report["realized"] is False and text == "ENGINE"
