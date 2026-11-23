"""Do answers come out right when people ask the way people ask?

The whole path is run: three packs are loaded, a question is read, matched and answered. The
questions in FRESH were written by the implementer before the first run and are not changed
afterwards; they are a development probe, not an independent evaluation. The tax trial's 24
questions are the public ones of 2026-11-19, already exposed: regression only.

Each question has the value a person would expect, or None when the packs do not hold the
answer and the right behaviour is to give none.

  right      the expected answer and nothing else (for a claim: the right yes/no)
  flagged    the expected answer, but reached by ignoring words or matching a name loosely
  wrong      a different answer, or an answer where none should be given
  held       no answer although the packs hold one
  held ok    no answer, and none should be given

Run from the repository root:
  PYTHONPATH=. python experiments/graph_weighted_acquisition/probes/real_sentences.py
"""
import importlib.util
import json
from pathlib import Path

from experiments.graph_weighted_acquisition import pack as PK
from experiments.graph_weighted_acquisition import reader as R

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ML = _module('make_language', HERE / 'packs' / 'make_language.py')
PROBE = _module('reading_limits', HERE / 'probes' / 'reading_limits.py')


def load(name):
    return json.loads((HERE / 'packs' / name).read_text(encoding='utf8'))


YES, NO = ('claim', True), ('claim', False)
FRESH = {
    'library': [   # (question, expected, kind)
        ('일반회원의 대출기간은 얼마인가요?', '14일', 'textbook'),
        ('별관의 운영시간은 언제인가요?', '10시~18시', 'textbook'),
        ('중앙도서관의 휴관일은 언제인가요?', '매주월요일', 'textbook'),
        ('별관의 반납장소는 어디인가요?', '무인반납함', 'textbook'),
        ('꼬마회원의 대출권수는 무엇인가요?', '10권', 'textbook'),
        ('어린이회원의 대출권수는 10권이 맞나요?', YES, 'textbook'),
        ('일반회원의 대출기간은 21일이 맞나요?', NO, 'textbook'),
        ('일반회원은 책을 며칠 동안 빌릴 수 있나요?', '14일', 'natural'),
        ('어린이회원은 책을 몇 권까지 빌릴 수 있어요?', '10권', 'natural'),
        ('어린이는 몇 권 빌릴 수 있나요?', '10권', 'natural'),
        ('책을 늦게 반납하면 연체료가 얼마인가요?', '하루100원', 'natural'),
        ('일반회원의 연체료는 하루에 얼마예요?', '하루100원', 'natural'),
        ('중앙도서관은 몇 시부터 몇 시까지 여나요?', '9시~22시', 'natural'),
        ('중앙도서관 운영시간 알려주세요.', '9시~22시', 'natural'),
        ('별관은 몇 시에 닫아요?', '10시~18시', 'natural'),
        ('중앙도서관은 무슨 요일에 쉬나요?', '매주월요일', 'natural'),
        ('중앙도서관 전화번호가 뭐예요?', '555', 'natural'),
        ('별관에서는 책을 어디에 반납하나요?', '무인반납함', 'natural'),
        ('본관은 언제 문을 여나요?', '9시~22시', 'natural'),
        ('꼬마회원의 대출권수는 몇 권인가요?', '10권', 'natural'),
        ('일반회원과 어린이회원의 대출기간은 얼마인가요?', ['14일', '21일'], 'natural'),
        ('어린이회원의 연체료는 얼마인가요?', None, 'no answer'),
        ('별관의 휴관일은 언제인가요?', None, 'no answer'),
        ('중앙도서관의 주말 운영시간은 언제인가요?', None, 'no answer'),
        ('도서관 회원 가입은 어떻게 하나요?', None, 'no answer'),
    ],
    'tax': [
        ('일반과세자의 세율은 얼마인가요?', '10%', 'textbook'),
        ('개인일반사업자의 신고횟수는 무엇인가요?', '연2회', 'textbook'),
        ('성실신고확인서제출자의 신고기한은 언제인가요?', '다음해6월30일', 'textbook'),
        ('국세청상담센터의 상담전화는 무엇인가요?', '126', 'textbook'),
        ('법인사업자의 신고횟수는 연4회가 맞나요?', YES, 'textbook'),
        ('일반과세자의 과세기간은 1년이 맞나요?', NO, 'textbook'),
        ('일반과세자는 부가가치세를 몇 퍼센트 내나요?', '10%', 'natural'),
        ('부가가치세 세율이 어떻게 되나요?', '10%', 'natural'),
        ('법인사업자는 부가가치세를 일 년에 몇 번 신고하나요?', '연4회', 'natural'),
        ('간이과세자는 언제 신고하나요?', '다음해1월1일~1월25일', 'natural'),
        ('사업자등록은 어디서 신청하나요?', '홈택스', 'natural'),
        ('사업자등록의 신청기한은 언제까지인가요?', '사업개시일부터20일이내', 'natural'),
        ('국세상담센터 전화번호는 몇 번인가요?', '126', 'natural'),
        ('종합소득세는 언제 신고하나요?', '다음해5월1일~5월31일', 'natural'),
        ('2026년 제1기 부가가치세 확정신고는 언제까지 하나요?', '2026년7월27일', 'natural'),
        ('일반과세자 제1기 확정신고 기간이 언제예요?', '7월1일~7월25일', 'natural'),
        ('간이과세자의 세율은 얼마인가요?', None, 'no answer'),
        ('법인세의 신고기한은 언제인가요?', None, 'no answer'),
        ('면세사업자의 세율은 얼마인가요?', None, 'no answer'),
        ('일반과세자의 세율은 왜 10%인가요?', None, 'no answer'),
    ],
}


def exposed_tax():
    """The 24 public tax questions with what their own file expects."""
    out = []
    for q in json.loads((ROOT / 'experiments' / 'tax_graph_trial_20261119' / 'questions.json').read_text(encoding='utf8')):
        gold = q['expected_behavior']['gold_status']
        expected = {'answer': lambda: q['expected_bindings'][0]['value'],
                    'derived_answer': lambda: q['expected_behavior']['expected_answer'],   # a calculation
                    'reject_claim': lambda: NO,                                             # "…0%가 맞나요?"
                    'hold': lambda: None}[gold]()
        out.append((q['text'], expected, q['tier']))
    return out


def verdict(result, expected):
    flagged = bool(result.get('partial'))
    if result['status'] != 'answered':
        return 'held ok' if expected is None else 'held'
    if expected is None:
        return 'wrong'
    if isinstance(expected, tuple):
        right = result.get('claim') is not None and result['claim']['holds'] == expected[1]
    else:
        want = expected if isinstance(expected, list) else [expected]
        right = result.get('claim') is None and sorted(a[0] for a in result['answers']) == sorted(want)
    return ('flagged' if flagged else 'right') if right else 'wrong'


def shown(result):
    if result['status'] != 'answered':
        return '-- ' + result['reason'][:60]
    said = [s['text'] for s in result.get('sentences', []) if s['status'] == 'said']
    text = said[0] if said else ', '.join(a[0] for a in result['answers'])
    if result.get('claim'):
        text = ('맞다: ' if result['claim']['holds'] else '아니다: ') + text
    return text + (' [' + '; '.join(result['partial'])[:50] + ']' if result.get('partial') else '')


def run(title, system, rows, tally):
    print('\n### ' + title)
    for text, expected, kind in rows:
        result = PK.ask(system, text)
        v = verdict(result, expected)
        tally.setdefault(kind, {}).setdefault(v, 0)
        tally[kind][v] += 1
        print('%-8s %-9s %s  =>  %s' % (v, kind[:9], text, shown(result)))


def main():
    variants = load('../data/connector_variants_ko.json')
    packs = [('A. shipped language pack (built before today, 112 lessons)', load('language.json')),
             ('B. same lessons rebuilt with today\'s two reader rules', R.build(ML.lessons(), variants=variants)),
             ('C. B plus 128 lessons for more wordings of the plain shape (written by the implementer today)',
              R.build(ML.lessons() + PROBE.wordings(), variants=variants))]
    order = ['right', 'flagged', 'wrong', 'held', 'held ok']
    summary = []
    for name, language in packs:
        print('\n\n# ' + name)
        fresh, old = {}, {}
        for field in ('library', 'tax'):
            system = PK.load(language, load(field + '_words.json'), load(field + '_facts.json'))
            run('%s: fresh questions' % field, system, FRESH[field], fresh)
            if field == 'tax':
                run('tax: the 24 public questions (exposed, regression only)', system, exposed_tax(), old)
        summary.append((name, fresh, old))
    print('\n\n# Summary')
    for name, fresh, old in summary:
        print('\n' + name)
        for label, tally in (('fresh', fresh), ('exposed tax', old)):
            for kind in sorted(tally):
                n = sum(tally[kind].values())
                print('  %-12s %-10s %2d: ' % (label, kind, n) + ', '.join('%s %d' % (k, tally[kind].get(k, 0)) for k in order))


if __name__ == '__main__':
    main()
