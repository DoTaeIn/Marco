# -*- coding: utf-8 -*-
"""호환성 이름. 새 구현은 ``semantic_parser``와 ``state_engine``에 있다.

문장별 정규식 추론은 의도적으로 제거됐다. 호출자는 검증된 상태 JSON을
``state_engine.evaluate``에 넘겨야 하며, 원시 자연어만으로는 답을 만들지 않는다.
"""
from state_engine import evaluate


def reason(_text, _knowledge_path=None):
    return {"status": "unknown", "answer": None, "operator": None,
            "transitions": [], "verification": {"accepted": False,
            "reason": "raw_text_requires_semantic_parse"}}
