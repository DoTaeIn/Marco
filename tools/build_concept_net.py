# -*- coding: utf-8 -*-
"""국어사전의 유(類) 관계를 개념망으로 굳힌다.

    python tools/build_concept_net.py --최대 5        # data/개념망.json 을 짓는다
    python tools/build_concept_net.py --최대 5 --보기  # 짓지 않고 무엇이 들어가나 본다

왜 이걸 두나. 별칭을 하나 더 적으면 노드 하나가 덮인다. 상위어 관계를
하나 적으면 그 말이 나오는 모든 그래프의 모든 문장이 덮인다. 6,998개 노드에
각각 적는 것과, 관계 하나로 전부 덮는 것의 차이다.

무엇을 거르나. 사전의 유는 그대로 쓰면 해가 된다.

  서술어      '있다·한다·된다' 가 유로 잡힌 것이 별칭 1,798곳에 걸린다.
              이걸 갈아 끼우면 문장이 부서진다.
  가벼운 말    '것·수·때·자리·가지' 는 무엇의 상위어도 아니다.
  너무 큰 것   '사람' 은 하위어가 1,496개다. 한 문장이 1,496개로 불어난다.

남는 것이 '결과 -> 성과·업적', '차이 -> 격차·개인차', '상대 -> 경쟁자·맞수'
같은 것들이다.

**잰 결과: 안 는다.** 2,741종 4,870개를 붙여 별칭이 2.0배(884 -> 1750)로
불었는데 눈금이 안 움직였다.

    얼린 잣대(라우팅)   대조 368/368 · 셋 안 379->378 · 안 물음 86/86 · 셋 안 150->151
    그래프 안 매칭       45/250 -> 46/250     (물어볼 별칭을 빼고 잰 것)

그래서 data/개념망.json 은 저장소에 안 넣는다. 이 파일을 만들면 engine 이
읽어서 켜진다. 다시 해 보려면 여기서 시작하면 된다.

왜 안 늘었나 — 못 알아듣는 물음이 '빛으로 안 보이는 물질' · '유전정보를 담은
분자' 처럼 **설명문**이라, 낱말 하나를 동의어로 갈아 끼워서는 안 닿는다.
바꿔 말하기의 병목은 어휘가 아니다.
"""
import collections
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = "data/개념망.json"
# 유로 잡히지만 상위어가 아닌 말. 무엇이든 이것의 하위어가 될 수 있어서
# 갈아 끼우면 뜻이 아니라 문장 꼴만 바뀐다.
LIGHT = {"것", "수", "때", "곳", "바", "등", "이", "그", "저", "말", "데", "위", "안", "속",
         "중", "일", "자리", "가지", "내용", "부분", "경우", "상태", "모양", "방법", "정도",
         "사실", "종류", "이름", "사이", "이상", "이하", "따위", "무엇", "여럿", "하나"}


def is_noun(word):
    """서술어와 가벼운 말을 뺀다. 두 글자 이상의 순수 한글만 본다."""
    return (len(word) >= 2 and not word.endswith("다") and word not in LIGHT
            and bool(re.fullmatch(r"[가-힣]+", word or "")))


def build(max_n=5):
    """-> {상위어: [하위어, ...]}. 하위어가 max_n 개를 넘는 상위어는 뺀다."""
    import dict_extract
    genus, _target, _action = dict_extract.build_chain(dict_extract.read_dict())
    below = collections.defaultdict(list)
    for word, upper in genus.items():
        if word != upper and is_noun(upper) and is_noun(word):
            below[upper].append(word)
    return {u: sorted(v) for u, v in below.items() if 1 <= len(v) <= max_n}


def main():
    max_n = int(sys.argv[sys.argv.index("--최대") + 1]) if "--최대" in sys.argv else 5
    net = build(max_n)
    print("상위어 %d종 · 엣지 %d개 (하위어 %d개 이하만)"
          % (len(net), sum(len(v) for v in net.values()), max_n))
    for u, v in list(sorted(net.items()))[:8]:
        print("   %s -> %s" % (u, ", ".join(v)))
    if "--보기" in sys.argv:
        return
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(net, ensure_ascii=False, indent=0, sort_keys=True))
    print("-> %s" % OUT)


if __name__ == "__main__":
    main()
