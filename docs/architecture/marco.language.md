# `marco.language`

Text and structure: language packs, parsing, realization. Written 2026-09-23
against commit `78bd062`; updated 2026-09-24 against `5f321a3` (goal D2), after
the realizer rounds made `realize` more than a stub.

## Purpose

Be the one place where MARCO turns between language and meaning. Today the
output direction lives here: Hermeneia, the language realization pipeline, and
its check, in [`marco.language.realizer`](marco.language.realizer.md). The input
direction, Noesis for text (packs, parsing, particles), still lives in root
modules; goal S4 moves the whole-file ones under `marco/language/`
(`python tools/doc_facts.py layout` lists them), and the split of the large
ones waits for MARCO 1.

Working-tree update, 2026-10-06: MARCO 1 release is cancelled. The L1
[selected constituent reader](marco.language.frames.md) now lives in
`marco/language/frames.py` and is called by the legacy root RelationalParser.
It adds an opt-in selected declaration path, with full source coverage and
role/operator boundaries, through the existing meaning and reasoning pipeline.
It does not add general declarations to the ordinary language packs yet.

## Owns

- The exported name `realize`, re-exported from
  [`marco.language.realizer`](marco.language.realizer.md)
  ([marco/language/__init__.py](../../marco/language/__init__.py)).
- `__all__ == ["realize"]`.
- The subpackage `marco.language.realizer`.
- The opt-in selected constituent reader in `marco.language.frames`.
- Selected native graph compilation in `graph_projection.py`, including explicit
  relation-policy to same-root query associations. Predicate/role coordinates and
  origins come from selected graph declarations; no association preserves the
  prior output. This metadata does not interpret an unknown question or admit learning.
- Pure installed-expression origin validation and positional remapping in
  [`entry_origins.py`](../../marco/language/entry_origins.py). The legacy parser
  carries detached origin rows through retained, derived and learned examples;
  these rows do not change meanings, matching rank or grammar fingerprints.
- The realizer's round report `marco/language/W1-report.md` and the measurements
  folder `marco/language/measurements/` (fluency samples, composition counts).

## Does not own

- The legacy root parser entry point `relational_semantics.py` remains at the
  repository root. This package's constituent reader does not replace it or
  own L5 inference decisions.
- Language packs. `styles/한국어.json` and `styles/english.json` are read by
  `pack_model.py`, `language_components.py` and `marco/reasoning/context.py`.
- Korean particles and inflection (`marco/language/hangul.py`), which the realizer's grammar
  layer calls.
- The graph engine's authored answer lines (`engine.py`). They pass through
  `realize` unchanged, because no plan composes them.

## Depends on

- `marco.language.realizer`. No other import in `__init__.py`.
- `entry_origins.py` uses only the Python standard library. It performs no
  learning-store lookup; `LearningMemory` supplies accepted origins after approval.

## Public interface

| Name | Signature | Proof |
| --- | --- | --- |
| `realize` | `realize(meaning, intent, language) -> str` | `tests/test_language_seam.py::test_realize_is_exported_with_the_declared_signature` asserts `__all__`, the three parameter names and the `str` return annotation |
| `entry_origins.validated_entry_origin`, `.remap_entry_origins` | Detached origin validation and exact retained/derived index remapping | `tests/test_marco2_entry_origins.py`, `tests/test_marco2_constructor_lineage.py` |
| `graph_projection.project_language_dialogue` | `project_language_dialogue(view, graph_id, root, *, source=None)`; optional detached `relation_hypothesis_queries` table for explicit selected links | [Six frozen native compiler development groups](../../tools/marco2_unknown_query_association_dev/README.md) |

Pure helper validation retains `ValueError`. Parser provenance faults use
`EntryOriginError(RuntimeError)` so a source-metadata defect is not a semantic
learning rejection. `None` means unknown. An installed origin is not evidence
that an input matched it or an answer used it; those collectors remain incomplete.

The callers of `realize` are `ReasoningContext.turn` (`marco/reasoning/context.py`), `engine.answer`
(`engine.py`) and `AppState` (`views/kgpack_ui.py`). What the function does:
[marco.language.realizer.md](marco.language.realizer.md).


### 부분 수집: 실제 선택된 입력 예시

`RelationalParser.parse(..., _entry_selection=True)`는 성공한 일반 진술·물음의
실제 최종 선택 예시 위치, 해당 설치 출처와 적용된 facts/query 위치를 반환한다.
동일 의미 경쟁에서 실제 첫 선택을 보존하며 `_used` 제외 키의 의미는 바꾸지 않는다.
기본값은 꺼져 있다. 출처 목록의 길이·행이 잘못되거나 출처를 모르면 해당 출처와
누락 이유만 남기고 가능한 의미 처리는 계속한다. graph binding을 모르는 유효한
출처는 교사·규칙 식별자를 보존하며 현재 binding으로 채우지 않는다.

`entry_selection`의 scope는 `known_selected_input_clauses`, status는 항상 `partial`,
좌표는 `parser_view`다. 상대절 재작성 원문 연결이 입증되지 않으면 별도 gap을 남긴다.
조건·사건·정의·특수 경로의 사용 출처, L5 역사 기록과 L9 최종 답변 근거의 연결은
아직 남아 있다. 이 기록을 답변에 쓴 학습 전체나 완전한 추적으로 선언하지 않는다.


## Context 원문과 뜻 확인의 실험 연결 — 2026-10-23

`programs/contextual-meaning-candidates-ko-experimental.json`은 기존 문형의 관계·부호를 데이터로 읽어 여섯 해석을 제안하고, Context와 충돌한 해석을 뒤로 배치하며 뜻 확인 문장을 만든다. Python의 관계별 의미 분기는 추가하지 않았다. `marco/runtime/contextual_meaning_host.py`는 실제 Context의 `Obs`·ID·개정·전체 원장을 기존 `readings.validate_ledger`로 검사하고, 원문 전체를 기존 언어 그래프에 전달한다. native parsed 사실을 복사하지 않으며 읽기 불가 표시는 그대로 남긴다. 모든 원문이 새 그래프에서 접지되어야 하며 하나라도 지원하지 못하면 보류한다.

확인 전에 뜻을 확정하지 않는다. 답변은 실제 질문의 전체 확인 문장과 정확히 일치해야 하며 원문 해시·질문·대화·모델·프로그램·Context 원장·Overlay head에 묶인다. 질문과 확인은 기존 `OverlayStore.propose`의 pending 행 두 개로만 보존한다. 임시 문형 하나로 원문을 다시 해석하고 실제 목표의 전제·규칙·바인딩을 독립 검증한다. 활성 지식·학습 규칙은 바뀌지 않는다.

같은 그래프 자산 검사8/8·최종 연결 검사7묶음 PASS. 최종 별도 문맥 시험에서 풀이0/4→4/4, 같은 확인 정보를 준 이전 경로4/4, 새 기존문형 대조4/4, 질문의 여섯 후보·충돌순서8/8·기존 문맥 사실 대조8/8을 확인했다. 4건 모두 원문이 실제 목표 증명의 조상 근거다. 원래12 중 한 건은 no_reply 문항에 평가기가 답을 넣어 무효이며, 실행·원점수를 보존하고 유효11/11(풀이4·안전3·문형4)만 채택한다. 정확한 상호작용 허용 목록을 적용한 평가기는 순수 절차 검사32/32를 통과했고, 별도로 고정한 새 no_reply 대화2/2에서 답변·확인 행을 만들지 않고 질문 후보 한 건만 남겼다. 이 두 문항은 무효였던 옛 문항을 재실행하거나 대체한 점수가 아니다. 새 두 문맥의 기존 사실 대조도2/2였다.

초기 후보의 새20(풀이0/8→8/8·동일정보기존8/8·안전8/8·문형4/4)은 별도 버전 결과로 유지한다. 이후 문맥 준비 시 native snapshot이 읽기 불가를 반환한 실패와, Python3.9가 기존 정규식을 지원하지 않은 시작 실패·보호 실행기 시작 실패도 남겼다. native Context는 수선하지 않았다. 최종은 기존 원장 검증으로 실제 원문·개정을 읽는 별도 그래프 해석이다. 최대 Overlay evidence는10,184B로 기존65,536B 한도 안이며 head/활성/승인 건수는0이다. 원장 변경 없음은 실제 과정의 전후 비교 결과이고 전체 원장 본문을 저장해 독립 재구성한 주장은 하지 않는다.

반환 상태는 `baseline`(기존 그래프 인식), `clarify`, `scoped`(확인한 해석과 검증된 답변), `held`다. 입력은 `{source:{id,text,sha256},caller_attested:true}`, 응답은 `{question_id,source:{id,text,sha256},caller_attested:true}`다. 호출자 귀속은 실제 진실이나 발신자 인증이 아니다. v2 세션은 기존 v1 스냅샷 기반 세션을 재해석하지 않고 거절한다. 지원되지 않는 원문·잘못된 응답·바뀐 원장·기존 후보의 외부 거절도 보류한다.

VM4096·trace256·전이128·사실32·규칙16·기존 증명/탐색 한도를 유지한다. 기록은 새 저장소 대신 기존 Overlay와 반환 JSON을 사용한다. Context의 원문·원장만 읽는 이 경로를 전체 Context의 의미 스냅샷으로 부르지 않는다. 읽기 불가 native 문맥은 같은 실제 owner와 JSON 세션의 재개를 검증했고, 별도 과정의 실제 Context.snapshot/restore는 native 스냅샷이 가능한 문맥에서만 검증했다. 기본 Session·선택팩·기존 Context/Overlay/VM/추론 소스는 바꾸지 않았다. 검사에는 Python 3.11 이상을 사용한다.

공개 검사 실행(비공개 비교 문항은 포함하지 않음):

```bash
python3.11 tests/test_contextual_meaning_graph.py
python3.11 tests/test_contextual_meaning_host.py
```

그래프 검사 기록 파일은 `MARCO_CONTEXT_GRAPH_TEST_EVIDENCE`를 지정할 때만 내보낸다. 기본 검사 실행은 저장소에 기록 파일을 만들지 않는다.
