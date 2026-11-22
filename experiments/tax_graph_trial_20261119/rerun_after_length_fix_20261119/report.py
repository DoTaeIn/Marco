import collections,hashlib,json
from pathlib import Path
p=Path(__file__).resolve().parent; base=p.parent
read=lambda f:json.loads(f.read_text(encoding='utf8'))
def rows(f):return [json.loads(x) for x in f.read_text(encoding='utf8').splitlines()]
qs=read(base/'questions.json')+read(base/'supplemental_questions.json')
new=rows(p/'first_results.jsonl'); old=rows(base/'first_results.jsonl')+rows(base/'diagnostic_first_results.jsonl')
assert len(new)==52 and len({(x['question_id'],x['arm']) for x in new})==52
n={(x['question_id'],x['arm']):x for x in new}; o={(x['question_id'],x['arm']):x for x in old}
def classification(q,r):
 x=r['result']; status=x['status']
 if status!='answered':return status
 gold=q['expected_behavior']['gold_status']; actual=sorted(x['answers'])
 if gold=='answer':return 'correct' if actual==sorted([[b['value']] for b in q['expected_bindings']]) else 'wrong'
 if gold=='derived_answer': return 'correct' if actual==[[q['expected_behavior']['expected_answer']]] else 'wrong'
 return 'unscored answer' if gold=='reject_claim' else 'wrong'
def raw(r):
 x=r['result']; return json.dumps({'status':x['status'],'answers':x.get('answers',[]),'reason':x.get('reason'),'executor':x.get('executor'),'verified':x.get('verified'),'withheld':x.get('withheld'),'proofs':x.get('match',{}).get('proofs',[])},ensure_ascii=False,separators=(',',':'))
def e(x):return str(x).replace('|','\\|').replace('\n',' ')
lines=['# 기존 세금 질문 재실행','', '동일한 24개 질문과 사후 진단 4개, 같은 14개 사실 그래프 및 기존 저장 모델을 사용했다. 현재 소스에는 원본 당시와 비교해 reader.py와 answer.py 변경이 포함된다. 새로운 독립 시험이 아니며, 기존 사례를 수정 후 다시 실행한 결과다. 2개 작업을 동시에 실행했으므로 시간은 부하가 있는 상태에서 측정됐다. 그래프 arm 20초, 자연어 arm 10초 제한.','', '각 결과는 원시 배열·이유·독립 실행기 상태와 근거를 표시한다. 원래 24개 그래프 결과와 사후 4개는 모두 hold였다. 사실의 범위는 원본 자료의 출처 메타데이터로 주어지며 그래프에서 자동으로 검증되지 않는다.','', '| 번호 | 질문 | 이전 → 현재 그래프 판정 | 현재 그래프 실제 결과 | 이전 → 현재 자연어 판정 | 현재 자연어 실제 결과 |','|---|---|---|---|---|---|']
for q in qs:
 i=q['id']; g=n[i,'graph']; oldg=o[i,'graph']; t=n.get((i,'end_to_end')); oldt=o.get((i,'end_to_end'))
 vals=[i,q['text'],classification(q,oldg)+' → '+classification(q,g),raw(g),classification(q,oldt)+' → '+classification(q,t) if t else '미실행',raw(t) if t else '미실행']
 lines.append('| '+' | '.join(map(e,vals))+' |')
lines+=['','## 유형별 그래프 결과','']
for tier in ('direct','paraphrase','boundary','posthoc_supported_form'):
 sub=[q for q in qs if q['tier']==tier]; c=collections.Counter(classification(q,n[q['id'],'graph']) for q in sub)
 lines.append(f'- {tier}: {len(sub)}개, {dict(c)}')
lines+=['','정확 일치는 사전에 기록한 예상 사실값과 원시 답 배열의 일치로 집계했다. 보류는 사실 정확도로 세지 않았다. 반박형 질문에 답이 나왔다면 별도 판단이 필요하므로 자동 정오 채점하지 않는다. 그래프 arm의 독립 검증은 executor와 verified 값으로 구별한다. 전체 판독 후보, 학습 횟수, 근거와 14개 출처는 JSONL 원본에 기록됐다.','', '## 확인값','',f"- 실행 전 고정 manifest SHA-256: {hashlib.sha256((p/'manifest.json').read_bytes()).hexdigest()}",f"- 결과 SHA-256: {hashlib.sha256((p/'first_results.jsonl').read_bytes()).hexdigest()}",f"- 실행 후 코드·입력 불변: {read(p/'postcheck.json')['inputs_and_sources_unchanged']}",f"- 저장 모델 SHA-256: {read(p/'manifest.json')['model_sha256']}",'']
(p/'REPORT.md').write_text('\n'.join(lines),encoding='utf8')
