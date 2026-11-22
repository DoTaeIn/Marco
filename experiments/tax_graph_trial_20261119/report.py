"""Render the frozen first capture; no model calls or answer generation."""
import collections
import hashlib
import json
from pathlib import Path
p=Path(__file__).resolve().parent
read=lambda name: json.loads((p/name).read_text(encoding='utf8'))
questions=read('questions.json'); facts=read('facts.json')
results=[json.loads(line) for line in (p/'first_results.jsonl').read_text(encoding='utf8').splitlines()]
assert len(results)==len(questions)*2
by={(r['question_id'],r['arm']):r for r in results}
assert len(by)==len(results)
def raw(r):
 x=r['result']; answer=json.dumps(x.get('answers',[]),ensure_ascii=False,separators=(',',':'))
 reason=x.get('reason',''); verify=x.get('executor','기록 없음')
 return f"{x['status']}; answers={answer}; reason={reason}; executor={verify}"
def esc(s): return str(s).replace('|','\\|').replace('\n',' ')
lines=['# 세금 지식 그래프: 첫 실행 결과','', '2026-11-19 기준. 24개 질문 모두 동일한 14개 사실 그래프를 받았다. 그래프 방식은 질문을 모델이 읽은 뒤 그래프를 검색한다. 자연어 방식은 전체 사실 문장과 질문을 모두 모델이 읽는다. 답변 칸은 모델의 상태, 원시 answers 배열, 이유 및 검증 상태를 그대로 표시한다.', '', '적용 범위는 사실 메타데이터에 기록되었으나 그래프의 조건으로 자동 검증되지 않는다. 입력 문장은 공식 페이지를 근거로 만든 정규화 문장이지 공식 페이지의 직인용이 아니다. 질문별 정답 메타데이터는 추론에 사용하지 않았다.', '', '| 번호 | 질문 | 그래프 방식: 실제 원시 결과 | 자연어 방식: 실제 원시 결과 |','|---|---|---|---|']
for q in questions:
 lines.append('| '+ ' | '.join(map(esc,[q['id'],q['text'],raw(by[q['id'],'graph']),raw(by[q['id'],'end_to_end'])]))+' |')
lines+=['','## 구분별 결과','']
for tier in ('direct','paraphrase','boundary'):
 qs=[q for q in questions if q['tier']==tier]
 counts=collections.Counter(by[q['id'],'graph']['result']['status'] for q in qs)
 exact=0; incorrect=0
 for q in qs:
  out=by[q['id'],'graph']['result']
  if out['status']=='answered':
   expected=sorted([[x['value']] for x in q['expected_bindings']])
   if q['expected_behavior']['gold_status']=='answer' and sorted(out['answers'])==expected: exact+=1
   else: incorrect+=1
 lines.append(f"- {tier}: {len(qs)}문항, 그래프 상태 {dict(counts)}, 직접 사실값과 정확히 일치한 답 {exact}개, 그 밖의 답변 {incorrect}개. 보류는 정답으로 계산하지 않았다.")
lines+=['','## 사실 및 출처','', '| 사실 | 대상 | 속성 | 값 | 범위 | 출처 |','|---|---|---|---|---|---|']
for f in facts:
 lines.append('| '+' | '.join(map(esc,[f['id'],f['subject'],f['property'],f['value'],f['scope']]))+f" | [국세청]({f['url']}) |")
lines+=['','## 재현과 검증','', '전체 결과와 모델의 후보 읽기·카운트·근거·독립 검증 상태는 `first_results.jsonl`에 있다. 각 줄은 고정된 manifest와 모델의 SHA-256을 포함하며, 한 번의 실행에서 처음 기록된 결과다. 응답이 보류되었다는 것은 해당 사실이 없다는 판단과 다르다. 그래프 데이터는 사람이 구성했으며 14개 사실에 대한 작은 시험이므로 세법 전반의 성능을 나타내지 않는다.','',f"- manifest SHA-256: {hashlib.sha256((p/'manifest.json').read_bytes()).hexdigest()}",f"- model SHA-256: {hashlib.sha256((p/'model.json').read_bytes()).hexdigest()}",f"- first_results SHA-256: {hashlib.sha256((p/'first_results.jsonl').read_bytes()).hexdigest()}",'']
(p/'REPORT.md').write_text('\n'.join(lines),encoding='utf8')
