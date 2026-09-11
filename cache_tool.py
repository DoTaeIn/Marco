# -*- coding: utf-8 -*-
"""캐시가 얼마나 쌓였는지 보고, 죽은 것만 치운다.

    python cache_tool.py                 # 무엇이 얼마나 있나 (아무것도 안 지운다)
    python cache_tool.py --치우기         # 죽은 캐시만 지운다
    python cache_tool.py --치우기 --시늉   # 지울 것만 보여준다

무엇이 죽은 것인가. 그래프 벡터 캐시(.vec_*.npz)의 파일 이름은
`sha1(MODEL + 그래프 내용)` 이다. 그러니 지금 있는 그래프를 전부 해시해서
그 목록에 없는 파일이 죽은 것이다 — 짐작이 아니라 계산이다.

인코더 둘을 다 본다. MODEL 이 키에 들어가서 문자와 신경이 서로 다른
파일을 쓰는데, 한쪽으로만 재고 지우면 다른 쪽 캐시를 통째로 날린다.
그래서 두 MODEL 을 다 넣어 살아 있는 키를 모은다.

    문자   문자포함도2-4096-자모0.5-매끔0.0
    신경   jhgan/ko-sroberta-multitask

안 지우는 것들. 이건 캐시가 아니라 자료다.

    graphs/*.미지.log      못 알아들은 말의 기록. 개념 후보를 캐는 재료다
    graphs/*.학습.jsonl    되묻기로 배운 말투. 지우면 배운 것이 사라진다
    graphs/후보/.진도.json  어디까지 캤나. 지우면 사전을 처음부터 다시 훑는다
    물음기록.jsonl          자가학습이 무엇을 틀렸는지 재는 기록

.색인벡터.npz 와 .색인.kgbin 은 캐시지만 지우지 않는다. 내용이 바뀌면
저절로 다시 만들어지고, 지우면 다음 실행이 몇 분 느려질 뿐이다. 정말
비우고 싶으면 --색인까지 를 준다.
"""
import glob
import hashlib
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
os.environ.setdefault("KG_ENCODER", "문자")

_models = ("문자포함도2-4096-자모0.5-매끔0.0", "jhgan/ko-sroberta-multitask")
_no_purge = ("graphs/*.미지.log", "graphs/*.학습.jsonl",
          "graphs/후보/.진도.json", "물음기록.jsonl")


def _size(paths):
    return sum(os.path.getsize(p) for p in paths if os.path.exists(p))


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024.0


def live_key():
    """지금 그래프들이 쓰는 벡터 캐시 키. 인코더 둘 다."""
    import engine
    key = set()
    file = (sorted(glob.glob(os.path.join(here, "graphs", "*.kg")))
            + sorted(glob.glob(os.path.join(here, "cases", "*.kg"))))
    for p in file:
        try:
            g = engine.load(os.path.relpath(p, here).replace("\\", "/"))
        except Exception:
            continue
        material = {layer: g.get(layer, {}) for layer in ("공통층", "사례층", "무관층")}
        material["개념엣지"] = g.get("개념엣지", [])
        trunk = json.dumps(material, ensure_ascii=False, sort_keys=True)
        for m in _models:
            key.add(hashlib.sha1((m + trunk).encode("utf-8")).hexdigest()[:16])
    return key


def view(purge=False, dry_run=False, upto_index=False):
    vec = sorted(glob.glob(os.path.join(here, ".vec_*.npz")))
    print("캐시")
    print("  .vec_*.npz        %4d개  %8s" % (len(vec), _human_size(_size(vec))))
    for name in (".색인벡터.npz", ".색인예시.json", ".색인.kgbin"):
        p = os.path.join(here, name)
        if os.path.exists(p):
            print("  %-18s      %8s" % (name, _human_size(os.path.getsize(p))))
    print("\n자료 (캐시가 아니라 안 지운다)")
    for pattern in _no_purge:
        loc = glob.glob(os.path.join(here, pattern))
        if loc:
            print("  %-22s %4d개  %8s" % (pattern, len(loc), _human_size(_size(loc))))

    print("\n어느 것이 죽었나 — 그래프를 해시해서 견준다")
    alive_key = live_key()
    dead = [p for p in vec
          if os.path.basename(p)[len(".vec_"):-len(".npz")] not in alive_key]
    alive = len(vec) - len(dead)
    print("  살아 있음 %3d개 · 죽음 %3d개 (%s)"
          % (alive, len(dead), _human_size(_size(dead))))
    if not purge:
        print("\n지우려면 --치우기 (먼저 --시늉 으로 볼 것)")
        return
    if dry_run:
        for p in dead[:10]:
            print("    지울 것: %s" % os.path.basename(p))
        if len(dead) > 10:
            print("    … 그 밖에 %d개" % (len(dead) - 10))
        return
    erased = 0
    for p in dead:
        try:
            os.remove(p)
            erased += 1
        except OSError:
            pass
    print("  지웠다 %d개" % erased)
    if upto_index:
        for name in (".색인벡터.npz", ".색인예시.json", ".색인.kgbin"):
            p = os.path.join(here, name)
            if os.path.exists(p):
                os.remove(p)
                print("  지웠다 %s (다음 실행에서 다시 만든다)" % name)


def _selfcheck():
    # 살아 있는 키에는 인코더 둘의 것이 다 들어가야 한다. 한쪽만 재고
    # 지우면 다른 인코더의 캐시를 통째로 날린다.
    trunk = "테스트"
    key = {hashlib.sha1((m + trunk).encode("utf-8")).hexdigest()[:16] for m in _models}
    assert len(key) == 2, key
    assert _human_size(1024) == "1.0KB" and _human_size(10) == "10.0B"
    # 자료 무늬에 캐시가 섞여 있으면 안 된다
    assert not any("vec_" in x or "색인" in x for x in _no_purge), _no_purge
    print("자가검사 ok")


if __name__ == "__main__":
    if "--자가검사" in sys.argv:
        _selfcheck()
    else:
        view("--치우기" in sys.argv, "--시늉" in sys.argv, "--색인까지" in sys.argv)
