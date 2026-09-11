"""로컬 위키 정의문(JSONL)을 정확한 정의 질문에만 연결하는 읽기 전용 색인.

모델 추측이나 웹 요청 없이 ``수학이 뭐야`` 같은 질문의 표제어를 찾아,
원문 정의를 근거로 반환한다. 색인은 /private/tmp에만 생성한다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


# 긴 꼴부터 확인한다. 조사(이/가/은/는)를 선택적으로 정규식에 섞으면
# ``음계의 정의가 뭐야``에서 표제어가 ``음계의 정의``로 잘릴 수 있어서,
# 접미어를 제거하는 결정론 방식으로 둔다.
_QUESTION_SUFFIXES = (
    "에 대해 설명해 줘", "에 대해 설명해줘", "에 대해 알려 줘", "에 대해 알려줘",
    "에 관한 설명을 해 줘", "에 관한 설명 해줘", "에 관해 설명해 줘", "에 관해 설명해줘",
    "의 정의가 뭐야", "의 정의 뭐야", "의 뜻이 뭐야", "의 뜻 뭐야",
    "이란 무엇인가요", "란 무엇인가요", "이란 무엇이야", "란 무엇이야",
    "은 무엇인가요", "는 무엇인가요", "이 무엇인가요", "가 무엇인가요", " 무엇인가요",
    "은 무엇인가", "는 무엇인가", "이 무엇인가", "가 무엇인가", " 무엇인가",
    "뜻을 알려 줘", "뜻을 알려줘", "뜻 알려 줘", "뜻 알려줘",
    "정의를 알려 줘", "정의를 알려줘", "정의 알려 줘", "정의 알려줘",
    " 설명해 줘", " 설명해줘", " 알려 줘", " 알려줘",
    "이 뭐야", "가 뭐야", "은 뭐야", "는 뭐야", " 뭐야", " 뭔데",
    "이란", "란",
)

# 비교는 정의 질문과 다르게 두 표제어를 동시에 얻어야 한다. 문장 가운데의
# "와/과"를 무작정 나누면 고유명사나 나열문을 잘못 해석하므로, 비교 표지와
# 질문 종결이 모두 있을 때만 보수적으로 허용한다.
_COMPARISON = re.compile(
    r"^\s*(?P<left>.+?)\s*(?:와|과|랑|하고)\s*(?P<right>.+?)\s*"
    r"(?:의\s*)?(?:차이|차이가|차이를|비교)\s*(?:가\s*)?(?:뭐야|무엇인가요?|알려\s*줘)?\s*[?？!！.\s]*$"
)


def _term(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


class DefinitionLookup:
    def __init__(self, source: Path, cache: Path = Path("/private/tmp/nai-definition-index.sqlite")):
        self.source, self.cache = Path(source), Path(cache)

    def _ensure(self) -> None:
        if self.cache.exists() and self.cache.stat().st_mtime >= self.source.stat().st_mtime:
            # 초기 색인은 정확 표제어만 저장했다. 공백을 달리 쓴 자연어도
            # 찾을 수 있도록 compact 열이 있는 현재 스키마인지 확인한다.
            db = sqlite3.connect(self.cache)
            try:
                columns = {row[1] for row in db.execute("PRAGMA table_info(definitions)")}
                if {"term", "compact", "definition"}.issubset(columns):
                    return
            finally:
                db.close()
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache.with_suffix(".building")
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        db = sqlite3.connect(temporary)
        try:
            db.execute("CREATE TABLE definitions (term TEXT PRIMARY KEY, compact TEXT NOT NULL, definition TEXT NOT NULL)")
            db.execute("CREATE INDEX definitions_compact ON definitions(compact)")
            batch = []
            with self.source.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key, definition = _term(item.get("말")), str(item.get("정의") or "").strip()
                    if len(key) >= 1 and definition:
                        batch.append((key, key.replace(" ", ""), definition))
                    if len(batch) >= 2000:
                        db.executemany("INSERT OR REPLACE INTO definitions VALUES (?, ?, ?)", batch); batch.clear()
                if batch:
                    db.executemany("INSERT OR REPLACE INTO definitions VALUES (?, ?, ?)", batch)
            db.commit()
        finally:
            db.close()
        temporary.replace(self.cache)

    @staticmethod
    def question_term(text: str) -> str | None:
        raw = str(text or "").strip().rstrip("?？!！. ")
        raw = raw.strip("'\"“” ")
        candidate = None
        for suffix in _QUESTION_SUFFIXES:
            if raw.endswith(suffix):
                candidate = raw[:-len(suffix)].strip()
                break
        if not candidate:
            return None
        candidate = _term(candidate).removeprefix("혹시 ").removeprefix("그럼 ")
        # 인사·대화예절 등의 짧은 말은 정의 데이터가 아니라 대화 그래프가 맡는다.
        if len(candidate.replace(" ", "")) < 2:
            return None
        return candidate

    def lookup(self, text: str) -> dict | None:
        term = self.question_term(text)
        if not term or not self.source.exists():
            return None
        self._ensure()
        return self._lookup_term(term)

    def _lookup_term(self, term: str) -> dict | None:
        """색인을 이미 준비한 뒤 정규화된 표제어 하나를 정확히 찾는다."""
        db = sqlite3.connect(self.cache)
        try:
            row = db.execute("SELECT term, definition FROM definitions WHERE term = ?", (term,)).fetchone()
            if not row:
                row = db.execute("SELECT term, definition FROM definitions WHERE compact = ? LIMIT 1",
                                 (term.replace(" ", ""),)).fetchone()
        finally:
            db.close()
        if not row:
            return None
        # 한 정의가 UI를 밀어내지 않도록 두 문장/480자까지만 보인다.
        matched_term, raw_definition = row
        definition = re.split(r"(?<=[.!?])\s+", raw_definition.strip(), maxsplit=2)[0][:480]
        # 동음이의어 표제의 안내문은 정의가 아니다. 이런 문장을 우선 반환하면
        # 실제 기초 KG가 가진 설명 경로까지 가로막으므로, 정직하게 미일치로
        # 돌려 해당 KG/조사 흐름에 맡긴다.
        if definition.endswith("다음 뜻으로 쓰인다") or definition.endswith("다음과 같은 뜻이 있다"):
            return None
        return {"term": matched_term, "definition": definition,
                "source": "data/위키/정의문.jsonl", "verified": True}

    @staticmethod
    def comparison_terms(text: str) -> tuple[str, str] | None:
        matched = _COMPARISON.match(str(text or ""))
        if not matched:
            return None
        left = _term(matched.group("left").rstrip("의 "))
        right = _term(matched.group("right").rstrip("의 "))
        if not left or not right or left == right:
            return None
        return left, right

    def compare(self, text: str) -> dict | None:
        """두 표제어가 모두 정확히 있을 때만 원문 정의를 나란히 반환한다.

        이 메서드는 어느 쪽이 더 낫다거나 원인 관계라고 추정하지 않는다.
        따라서 비교가 성립하지 않는 질문은 기존 KG·조사 흐름으로 그대로 넘긴다.
        """
        terms = self.comparison_terms(text)
        if not terms or not self.source.exists():
            return None
        self._ensure()
        left, right = (self._lookup_term(term) for term in terms)
        if not left or not right:
            return None
        return {
            "kind": "comparison", "terms": [left["term"], right["term"]],
            "definitions": [left, right], "source": "data/위키/정의문.jsonl",
            "verified": True,
        }

    def lookup_any(self, text: str) -> dict | None:
        """정확한 단일 정의 또는 두 표제어 비교를 읽기 전용으로 조회한다."""
        return self.compare(text) or self.lookup(text)
