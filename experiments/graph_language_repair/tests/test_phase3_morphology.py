"""Public controls for compositional colloquial predicate morphology."""

from experiments.graph_language_repair.core import analyze_predicates, read_text


def find(text, lemma, mode="question"):
    matches = [item for item in analyze_predicates(text, mode=mode)
               if item["lemma"] == lemma]
    return next((item for item in matches if item["mood"] == "interrogative"), matches[0])


def test_regular_past_colloquial_endings_compose_across_body_and_question():
    body = find("라미가 끈을 묶었어.", "묶", "document")
    polite = find("라미가 끈을 묶었어요.", "묶", "document")
    plain_question = find("라미가 끈을 묶었어?", "묶")
    assert body["action"] == polite["action"] == plain_question["action"]
    assert body["mood"] == polite["mood"] == "declarative"
    assert plain_question["mood"] == "interrogative"
    assert body["semantic_status"] == "opaque"


def test_colloquial_negation_keeps_negative_polarity_and_identity():
    body = find("라미가 끈을 묶지 않았어.", "묶", "document")
    query = find("라미가 끈을 묶지 않았어요?", "묶")
    assert body["action"] == query["action"]
    assert body["polarity"] is query["polarity"] is False


def test_hada_colloquial_questions_retain_the_declared_stem():
    query = find("다온이 문서를 색인했어?", "색인")
    assert query["action"] == "action:observed:" + "색인".encode().hex()
    assert query["semantic_status"] == "opaque"
    assert query["mood"] == "interrogative"


def test_future_and_embedded_quote_remain_nonassertive_or_unsupported():
    assert not read_text("라미가 끈을 묶겠다.")["events"]
    doc = read_text("라미가 ‘끈을 묶었어?’라고 물었다.")
    quoted = next(event for event in doc["events"]
                  if event.get("predicate_analysis", {}).get("lemma") == "묶")
    assert next(claim for claim in doc["claims"] if claim["id"] == quoted["claim"])["kind"] != "direct_text"
