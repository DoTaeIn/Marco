# -*- coding: utf-8 -*-
"""오래 걸리는 일에 진행 막대를 붙인다. 기다리는 사람이 뭘 기다리는지 알게.

    from 진행 import 막대
    for x in 막대(물음들, "라우팅"):
        ...

    with 막대(총=len(파일들), 이름="색인") as 밀기:
        for f in 파일들:
            ...
            밀기()

왜 만드나. 벤치마크 한 번이 몇 분인데 그동안 아무것도 안 나온다. 멈춘
것인지 도는 것인지 알 수 없으면 사람은 껐다 켠다 — 실제로 이 저장소에서
백그라운드 기다림 여덟 개가 5~21시간 돌고 있던 적이 있다.

셈이 아니라 **남은 시간**을 낸다. 몇 개 했는지는 그 자체로 쓸모가 없고,
얼마나 더 기다려야 하는지가 궁금한 것이다.

tqdm 을 안 쓴다. 이 프로젝트는 KG_ENCODER=문자 로 돌면 numpy 말고는
아무것도 안 올라오는 것이 값어치라(engine 들이는 데 14ms), 막대 하나
때문에 꾸러미를 늘리지 않는다. 필요한 것은 표준 라이브러리로 충분하다.

터미널이 아니면(파이프·로그 파일) 조용히 끈다. 진행 막대가 로그에 캐리지
리턴으로 도배되면 읽을 수 없게 된다.
"""
import os
import shutil
import sys
import time

_켬 = os.environ.get("KG_PROGRESS", "").lower() not in ("0", "off", "no")


def _시간(초):
    초 = int(max(초, 0))
    if 초 < 60:
        return "%d초" % 초
    if 초 < 3600:
        return "%d분 %02d초" % (초 // 60, 초 % 60)
    return "%d시간 %02d분" % (초 // 3600, (초 % 3600) // 60)


class 막대:
    """진행 막대. 이터러블을 감싸거나 with 로 쓴다.

    총 개수를 모르면(제너레이터) 막대 없이 센 것과 걸린 시간만 낸다 —
    남은 시간을 모르면서 아는 척하지 않는다."""

    def __init__(self, 것들=None, 이름="", 총=None, 최소간격=0.2):
        self.것들 = 것들
        self.이름 = 이름
        self.총 = 총 if 총 is not None else _길이(것들)
        self.한것 = 0
        self.시작 = time.time()
        self.마지막 = 0.0
        self.최소간격 = 최소간격
        self.켬 = _켬 and sys.stderr.isatty()

    def __iter__(self):
        for x in self.것들:
            yield x
            self.밀기()
        self.닫기()

    def __enter__(self):
        return self.밀기

    def __exit__(self, *_):
        self.닫기()
        return False

    def 밀기(self, 몇=1):
        self.한것 += 몇
        지금 = time.time()
        if not self.켬 or 지금 - self.마지막 < self.최소간격:
            return
        self.마지막 = 지금
        self._그리기(지금)

    def _그리기(self, 지금):
        걸린 = 지금 - self.시작
        폭 = min(shutil.get_terminal_size((80, 20)).columns, 100)
        if self.총:
            몫 = min(self.한것 / self.총, 1.0)
            남은 = (걸린 / 몫 - 걸린) if 몫 > 0 else 0
            꼬리 = " %d/%d  %s 남음" % (self.한것, self.총, _시간(남은))
            칸 = max(폭 - len(self.이름) - len(꼬리) - 6, 8)
            찬 = int(칸 * 몫)
            글 = "%s [%s%s]%s" % (self.이름, "━" * 찬, " " * (칸 - 찬), 꼬리)
        else:
            글 = "%s %d개 · %s 걸림" % (self.이름, self.한것, _시간(걸린))
        sys.stderr.write("\r\x1b[K" + 글[:폭])
        sys.stderr.flush()

    def 닫기(self):
        if not self.켬:
            return
        걸린 = time.time() - self.시작
        sys.stderr.write("\r\x1b[K%s %d개 · %s\n"
                         % (self.이름, self.한것, _시간(걸린)))
        sys.stderr.flush()


def _길이(것들):
    try:
        return len(것들)
    except TypeError:
        return None                     # 제너레이터는 총을 모른다


def _자가검사():
    # 터미널이 아니면 조용해야 한다. 로그가 캐리지 리턴으로 도배되면 못 읽는다.
    b = 막대(range(5), "시험")
    assert not b.켬 or sys.stderr.isatty()
    assert list(막대(range(5), "시험")) == [0, 1, 2, 3, 4]
    assert 막대(range(5)).총 == 5
    assert 막대(iter(range(5))).총 is None      # 모르면 모른다고 둔다
    # with 꼴은 밀기 함수를 준다
    with 막대(총=3, 이름="시험") as 밀기:
        밀기(); 밀기(); 밀기()
    assert _시간(5) == "5초" and _시간(65) == "1분 05초"
    assert _시간(3700) == "1시간 01분"
    assert _시간(-3) == "0초"
    # 총이 0 이어도 0 으로 안 나눈다
    with 막대(총=0, 이름="빈것") as 밀기:
        밀기()
    # 끄는 스위치가 듣는가. 모듈을 다시 들이는 대신 규칙만 확인한다 —
    # __main__ 으로 돌 때는 reload 가 안 된다.
    for 값, 켜져야 in (("0", False), ("off", False), ("no", False),
                     ("1", True), ("", True)):
        assert (값.lower() not in ("0", "off", "no")) is 켜져야, 값
    print("자가검사 ok")


if __name__ == "__main__":
    if "--자가검사" in sys.argv:
        _자가검사()
    elif "--보기" in sys.argv:          # 눈으로 확인용
        import random
        for _ in 막대(range(60), "보기"):
            time.sleep(random.random() * 0.05)
    else:
        print(__doc__)
