# -*- coding: utf-8 -*-
"""목적그래프가 지은 .kg 를 원문에서 다시 찍는다.

    python tools/regen_purpose_graphs.py            # 무엇이 달라지나 (안 쓴다)
    python tools/regen_purpose_graphs.py --쓰기      # 실제로 덮어쓴다

왜 다시 찍나. 틀에 조사가 박혀 있어서 '흙 가 없다' 처럼 아무도 쓰지 않는
한국어가 705개 그래프에 들어갔다. 틀은 고쳤지만 이미 찍힌 파일은 그대로다.

입력은 파일 안에 다 들어 있다 — 머리말에 원문 한 줄, `역할:` 에 말,
[개념] 에 대상, [사례] 의 말버릇에 도식, 공리 이름의 @ 뒤에 출처.
그래서 사전을 다시 뒤지지 않고 파일만으로 되찍을 수 있다.

뼈대(노드 이름과 논증)가 달라지면 조사 문제가 아니라는 뜻이므로 건너뛴다.
"""
import glob
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import purpose_graph                                   # noqa: E402

_MARK = "원문 한 줄에서 뽑았다"
_habits = {"가져감": "물건", "감": "장소", "부름": "사람"}


def inputs(text):
    """.kg 글자 -> build() 에 넣을 것들. 못 알아보면 None."""
    if _MARK not in text:
        return None
    role = re.search(r"^역할:\s*(.+?)\s*상담\s*$", text, re.M)
    definition = re.search(r"^#\s{4,}(\S.*)$", text, re.M)
    have = re.search(r"^(\S+?)있음:", text, re.M)
    axiom = re.search(r"^(\S+?)에는(\S+?)가필요(?:@(.*?))?:", text, re.M)
    case = re.search(r"^\*(\S+?)(가져감|감|부름):", text, re.M)
    if not (role and definition and have and case):
        return None
    return {"definition": definition.group(1).strip(),
            "phrase": role.group(1).strip(),
            "src": (axiom.group(3) or "") if axiom else "",
            "schema": _habits[case.group(2)],
            "index": "색인: 아니오" not in text}


def skeleton(text):
    """노드 이름과 논증만. 조사를 고쳐도 여기는 안 움직여야 한다.

    별칭 개수는 안 본다 — 말버릇 표가 그 뒤로 늘어서 다시 찍으면 별칭이
    더 나온다. 그건 나빠진 것이 아니다."""
    body, out = text.split("[대사]")[0], []
    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            out.append(line)
        elif "->" in line:                       # 논증
            out.append(re.sub(r"\s+", " ", line))
        elif ":" in line:                        # 노드 이름
            out.append(line.split(":", 1)[0].strip())
    return out


def repair(text):
    """되찍을 수 없는 파일의 조사를 제자리에서 고친다.

    되찍기가 낫지만, 원문에서 대상을 더는 못 뽑는 파일이 몇 개 있다.
    그것까지 깨진 채로 두지는 않는다.

    **아는 낱말 뒤만 건드린다.** 무엇이 낱말인지 정규식으로 짐작하면
    '걷는 게 더 빠르다' 의 '걷' 을 명사로 보고 '걷은 게' 로 만든다 —
    실제로 그랬다. 이 파일이 아는 낱말은 둘뿐이다: 말과 대상."""
    import hangul
    phrase = re.search(r"^역할:\s*(.+?)\s*상담\s*$", text, re.M)
    target = re.search(r"^(\S+?)있음:", text, re.M)
    words = [m.group(1) for m in (phrase, target) if m]
    if not words:
        return text
    detached = [(w, re.compile(r"%s (가|를|을|이|은|는|와|과|로|으로)(?=[ \"]|$)" % re.escape(w)))
                for w in words]

    def one(alias):
        body = alias.group(1)
        for word, pat in detached:
            body = pat.sub(lambda m, w=word: w + m.group(1), body)
        return '"%s"' % hangul.fix_particles(body, words)

    return re.sub(r'"([^"]*)"', one, text)


def main(write=False):
    same, fixed, moved, unread = 0, [], [], []
    for path in sorted(glob.glob("graphs/*.kg")):
        old = io.open(path, encoding="utf-8").read()
        got = inputs(old)
        if got is None:
            if _MARK in old:
                unread.append(path)
            continue
        new = purpose_graph.build(**got)
        if not new:
            mended = repair(old)
            unread.append(path)
            if write and mended != old:
                io.open(path, "w", encoding="utf-8").write(mended)
            continue
        if skeleton(new) != skeleton(old):
            moved.append(path)
            continue
        if new == old:
            same += 1
            continue
        fixed.append(path)
        if write:
            io.open(path, "w", encoding="wtf-8" if False else "utf-8").write(new)
    print("그대로       %5d" % same)
    print("고칠 것      %5d %s" % (len(fixed), "(썼다)" if write else "(안 썼다. --쓰기)"))
    print("뼈대가 달라짐 %5d" % len(moved))
    print("못 읽어 제자리에서 고침 %5d" % len(unread))
    for p in moved[:5]:
        print("   뼈대 다름:", p)
    for p in unread[:5]:
        print("   못 읽음:", p)
    return fixed


if __name__ == "__main__":
    main("--쓰기" in sys.argv)
