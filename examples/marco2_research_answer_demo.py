"""Explicit offline source-answer fixtures using the existing Korean parser.

    python3 -m examples.marco2_research_answer_demo

The shared fixture scope is a caller-declared interpretation condition, not
source evidence of a time. These fictional sources perform no HTTP request.
Two fixture-only output declarations explicitly permit neutral composition.
The old location declaration has no such contract and its answer is held.
"""
import copy
import json

from relational_semantics import RelationalParser
from marco.knowledge.ingest.retrieval import SearchEvidenceService
from marco.runtime.research import ResearchAnswerer


SCOPE = {"fixture": "research-answer-demo-v1", "interpretation": "simultaneous"}


class SourceFixture:
    provider = "explicit_offline_source_answer_fixture"

    def __init__(self, sentences):
        self.pages = {"https://source-%d.example/document" % index: sentence
                      for index, sentence in enumerate(sentences, 1)}

    def search(self, terms, count):
        return [{"url": url} for url in list(self.pages)[:count]]

    def fetch(self, url, terms, sentence_limit):
        return {"title": "명시한 오프라인 자료", "final_url": url, "sentences": [self.pages[url]]}


def main():
    ordinary = RelationalParser(language="한국어")
    data = copy.deepcopy(ordinary.data)
    data["examples"] += [
        {"text": "소루는 누루보다 키가 크다", "slots": {"a": "소루", "b": "누루"},
         "meaning": {"triple": ["$a", "taller", "$b"]},
         "source_answer": {"temporal": "timeless"}},
        {"text": "소루는 누루이다", "slots": {"a": "소루", "c": "누루"},
         "meaning": {"triple": ["$a", "isa", "$c"]},
         "source_answer": {"temporal": "neutral"}},
    ]
    parser = RelationalParser(data=data, language_pack=copy.deepcopy(ordinary.language_pack))
    before = copy.deepcopy(parser.data)
    def run(question, sentences, scoped=True):
        def reading(text):
            parsed = parser.parse(text, partial=True)
            if scoped:
                for fact in (parsed or {}).get("facts", []):
                    fact["scope"] = copy.deepcopy(SCOPE)
            return parsed
        report = SearchEvidenceService(SourceFixture(sentences)).research(
            question, search_terms="자료", meaning_reader=reading,
            single_value_predicates=parser.data.get("mutable_predicates", []))
        return ResearchAnswerer(parser).answer(report, source_scope=SCOPE)
    output = {
        "mode": "offline_fixture",
        "output_declarations": "explicit_fixture_neutral_and_timeless; built_in_pack_unchanged",
        "location": run("나루아는 어디에 있나?", ["나루아는 지금 도서관에 있다."]),
        "classification": run("이것만으로 가람빛이 조용한 청솔형이라고 할 수 있는가?",
                              ["가람빛은 조용한 청솔형이다."]),
        "height_chain": run("아라봄과 해루솔 중 누가 더 커?", ["아라봄은 도란별보다 키가 크다.",
                            "도란별은 해루솔보다 키가 크다.", "마루샘은 지금 과학관에 있다."]),
        "contradiction_hold": run("나루아는 어디에 있어?", ["나루아는 지금 도서관에 있다.",
                                     "나루아는 지금 운동장에 있다."]),
        "unknown_scope_hold": run("나루아는 어디에 있어?", ["나루아는 지금 도서관에 있다."], scoped=False),
    }
    output["parser_model_unchanged"] = parser.data == before
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
