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

_on = os.environ.get("KG_PROGRESS", "").lower() not in ("0", "off", "no")


def _fmt_time(sec):
    sec = int(max(sec, 0))
    if sec < 60:
        return "%d초" % sec
    if sec < 3600:
        return "%d분 %02d초" % (sec // 60, sec % 60)
    return "%d시간 %02d분" % (sec // 3600, (sec % 3600) // 60)


class Bar:
    """진행 막대. 이터러블을 감싸거나 with 로 쓴다.

    총 개수를 모르면(제너레이터) 막대 없이 센 것과 걸린 시간만 낸다 —
    남은 시간을 모르면서 아는 척하지 않는다."""

    def __init__(self, items=None, name="", total=None, min_interval=0.2):
        self.items = items
        self.name = name
        self.total = total if total is not None else _length(items)
        self.done = 0
        self.start = time.time()
        self.last = 0.0
        self.min_interval = min_interval
        self.on = _on and sys.stderr.isatty()

    def __iter__(self):
        for x in self.items:
            yield x
            self.push()
        self.close()

    def __enter__(self):
        return self.push

    def __exit__(self, *_):
        self.close()
        return False

    def push(self, n_=1):
        self.done += n_
        now = time.time()
        if not self.on or now - self.last < self.min_interval:
            return
        self.last = now
        self._draw(now)

    def _draw(self, now):
        elapsed = now - self.start
        width = min(shutil.get_terminal_size((80, 20)).columns, 100)
        if self.total:
            share = min(self.done / self.total, 1.0)
            remaining = (elapsed / share - elapsed) if share > 0 else 0
            tail = " %d/%d  %s 남음" % (self.done, self.total, _fmt_time(remaining))
            slot = max(width - len(self.name) - len(tail) - 6, 8)
            filled = int(slot * share)
            txt = "%s [%s%s]%s" % (self.name, "━" * filled, " " * (slot - filled), tail)
        else:
            txt = "%s %d개 · %s 걸림" % (self.name, self.done, _fmt_time(elapsed))
        sys.stderr.write("\r\x1b[K" + txt[:width])
        sys.stderr.flush()

    def close(self):
        if not self.on:
            return
        elapsed = time.time() - self.start
        sys.stderr.write("\r\x1b[K%s %d개 · %s\n"
                         % (self.name, self.done, _fmt_time(elapsed)))
        sys.stderr.flush()


def _length(items):
    try:
        return len(items)
    except TypeError:
        return None                     # 제너레이터는 총을 모른다


def _selfcheck():
    # 터미널이 아니면 조용해야 한다. 로그가 캐리지 리턴으로 도배되면 못 읽는다.
    b = Bar(range(5), "시험")
    assert not b.on or sys.stderr.isatty()
    assert list(Bar(range(5), "시험")) == [0, 1, 2, 3, 4]
    assert Bar(range(5)).total == 5
    assert Bar(iter(range(5))).total is None      # 모르면 모른다고 둔다
    # with 꼴은 밀기 함수를 준다
    with Bar(total=3, name="시험") as push:
        push(); push(); push()
    assert _fmt_time(5) == "5초" and _fmt_time(65) == "1분 05초"
    assert _fmt_time(3700) == "1시간 01분"
    assert _fmt_time(-3) == "0초"
    # 총이 0 이어도 0 으로 안 나눈다
    with Bar(total=0, name="빈것") as push:
        push()
    # 끄는 스위치가 듣는가. 모듈을 다시 들이는 대신 규칙만 확인한다 —
    # __main__ 으로 돌 때는 reload 가 안 된다.
    for value, must_be_on in (("0", False), ("off", False), ("no", False),
                     ("1", True), ("", True)):
        assert (value.lower() not in ("0", "off", "no")) is must_be_on, value
    print("자가검사 ok")


if __name__ == "__main__":
    if "--자가검사" in sys.argv:
        _selfcheck()
    elif "--보기" in sys.argv:          # 눈으로 확인용
        import random
        for _ in Bar(range(60), "보기"):
            time.sleep(random.random() * 0.05)
    else:
        print(__doc__)
