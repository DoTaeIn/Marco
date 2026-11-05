"""Run an explicit offline evidence fixture or a bounded, actual public search.

    python3 -m examples.marco2_retrieval_demo
    python3 -m examples.marco2_retrieval_demo --live 'Python programming language' --limit 2

The live mode never substitutes fixture data after a failure.
"""
import argparse
import json

from marco.knowledge.ingest.retrieval import PublicWebBackend, SearchEvidenceService


class DialogueFixture:
    provider = "local_dialogue_fixture"
    urls = ["https://a.example/minji", "https://b.example/minji", "https://c.example/unavailable"]

    def search(self, terms, count):
        return [{"url": url} for url in self.urls[:count]]

    def fetch(self, url, terms, sentence_limit):
        if url == self.urls[2]:
            raise TimeoutError("fixture source timed out")
        sentence = "민지는 지금 서울에 있다." if url == self.urls[0] else "민지는 서울에 있지 않다."
        return {"title": "명시한 오프라인 대화 자료", "final_url": url, "sentences": [sentence]}


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--live", metavar="QUERY", help="Perform actual public web search and fetch")
    args.add_argument("--limit", type=int, default=3, choices=range(1, 6))
    options = args.parse_args()
    if options.live:
        report = SearchEvidenceService(PublicWebBackend(timeout=4)).research(
            options.live, search_terms=options.live, limit=options.limit, sentence_limit=6)
    else:
        # The existing declarative parser reads the retrieved Korean statements.
        # There is no sentence-specific answer, neural generator or new grammar.
        from relational_semantics import RelationalParser
        parser = RelationalParser(language="한국어")
        report = SearchEvidenceService(DialogueFixture()).research(
            "민지는 어디에 있나?", search_terms="민지", limit=options.limit,
            meaning_reader=lambda text: parser.parse(text, partial=True),
            single_value_predicates=parser.data.get("mutable_predicates", []))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
