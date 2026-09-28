"""실제 답의 뜻을 채점한다. 그래프를 맞게 골랐는지가 아니다.

`AppState.turn` 을 그대로 통과시킨다. 라우팅 정답·그래프 경로 존재·문장
유사도는 답 정답의 대체 지표가 **아니다** — 여기서는 사람이 미리 확정해 둔
필수 결론·금지 결론·필요 근거로만 판정한다.

문항은 개발/평가로 나뉜다. **평가 문항은 고치는 데 쓰지 않는다.**
"""
import argparse
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "data/benchmarks/answer_quality.json"
# 보류로 읽는 판정. 그래프가 근거를 못 댔다는 뜻이다.
HELD = {"미지", "B2", "조건부족", "근거없음", "A"}


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _stated_values(squeezed, unit):
    """답이 그 단위로 내놓은 수들. 단위가 다르면 내놓은 적이 없는 것이다.

    `15kg입니다` 는 `개` 를 묻는 문항의 답이 아니다. 단위 없는 수도 아니다.
    """
    if not unit:
        return [m.group() for m in _NUMBER.finditer(squeezed)]
    return [m.group() for m in _NUMBER.finditer(squeezed)
            if squeezed[m.end():m.end() + len(unit)] == unit]


def _same_number(said, expected):
    try:
        return said is not None and Decimal(said) == Decimal(expected)
    except InvalidOperation:
        return False


def _formulaic(squeezed, unit, target, suffix):
    """이 답이 **기계가 뜻을 확신할 수 있는 정형 답**인가.

    채점기를 또 하나의 언어 이해기로 만들지 않는다. 값·단위·대상이 그대로
    드러난 짧은 답만 자동으로 가르고, 부정·설명·딴 대상이 섞이면 사람에게 넘긴다.

        15개입니다.        가른다
        구슬은 15개입니다.  가른다 (대상이 물음의 대상과 같다)
        15개가 아닙니다.    못 가른다 — 부정이 붙었다
        단추는 15개입니다.  못 가른다 — 딴 대상이다
    """
    body = squeezed
    if target and body.startswith(_squeeze(target)):
        body = body[len(_squeeze(target)):]
        if body[:1] and not body[0].isdigit():
            body = body[1:]                  # 대상 뒤의 조사 한 글자
    tail = _squeeze(suffix)
    if tail and body.endswith(tail):
        body = body[:-len(tail)]
    return bool(_NUMBER.fullmatch(body[:-len(unit)] if unit and body.endswith(unit) else body))


def _squeeze(text):
    return "".join(str(text or "").split())


def _contains(squeezed, needle):
    """숫자는 숫자에 붙어 있으면 못 찾은 것으로 본다.

    `15` 가 `115개입니다` 안에 들어 있다고 통과시키면 채점이 거짓말을 한다.
    글자는 그대로 부분 일치를 쓴다 — `구슬` 은 `구슬이` 안에서 찾아야 한다.
    """
    needle = _squeeze(needle)
    if not needle:
        return False
    start = squeezed.find(needle)
    while start != -1:
        before = squeezed[start - 1] if start else ""
        after = squeezed[start + len(needle):start + len(needle) + 1]
        head_ok = not (needle[0].isdigit() and before.isdigit())
        tail_ok = not (needle[-1].isdigit() and after.isdigit())
        if head_ok and tail_ok:
            return True
        start = squeezed.find(needle, start + 1)
    return False


def _evidence_texts(trace):
    """이 답이 실제로 댄 근거. 관계 추론의 근거 구간과 KG 경로를 함께 본다."""
    out = []
    reasoning = trace.get("reasoning") or {}
    for step in reasoning.get("transitions") or []:
        got = ((step.get("evidence") or {}).get("text") or "").strip()
        if got:
            out.append(got)
    for key in ("path", "activated"):
        for item in trace.get(key) or []:
            out.append(item if isinstance(item, str) else str(item))
    return out


def _judge(case, answer_text, known, trace, error=False):
    """(단정했나, 과제 성공, 근거 충족). 근거는 단정했을 때만 센다.

    `error` 는 실행이 예외로 끝났다는 뜻이다. 그건 올바른 보류가 아니라
    아무 답도 못 낸 것이므로, 답가능 여부와 무관하게 실패로 센다.
    """
    if error:
        return False, False, None
    verdict = (trace or {}).get("verdict")
    asserted = bool(known) and verdict not in HELD
    squeezed = _squeeze(answer_text)
    unit = (case.get("판정기준") or {}).get("단위", "")
    target = (case.get("판정기준") or {}).get("대상", "")
    suffix = case.get("answer_suffix", "입니다.")

    def holds(expected):
        """맞으면 True, 틀리면 False, **자동으로 못 가르면 None.**

        수는 글자 겹침이 아니라 값으로 견준다. 값이 여럿 나오면 어느 것이
        결론인지 채점기가 정할 수 없다 — `15개입니다. 원래는 18개였어요` 와
        `18개입니다. 15개가 아닙니다` 는 같은 두 수를 담는다. 끝에 있는 것이
        결론이라는 규칙은 둘 중 하나를 반드시 틀린다. 그러니 **미검토로 남긴다.**
        판정 불가를 정답이나 오답으로 몰래 바꾸지 않는다.
        """
        if not _NUMBER.fullmatch(str(expected)):
            return _contains(squeezed, expected)
        said = {str(x) for x in _stated_values(squeezed, unit)}
        if len(said) > 1 or not _formulaic(squeezed, unit, target, suffix):
            return None
        return _same_number(next(iter(said), None), str(expected))

    if not case["답가능"]:
        # 보류해야 하는 문항. 단정하면 그것으로 실패다.
        forbidden = any(holds(x) for x in case["금지결론"])
        return asserted, (not asserted) and not forbidden, None

    if not asserted:
        return False, False, None
    must = case.get("필수결론") or {}

    checks = [holds(x) for x in must.get("포함", [])]
    if must.get("포함후보"):
        candidates = [holds(x) for x in must["포함후보"]]
        checks.append(True if any(c is True for c in candidates)
                      else (None if any(c is None for c in candidates) else False))
    forbidden = [holds(x) for x in case["금지결론"]]
    if not must.get("포함") and not must.get("포함후보"):
        return True, False, None         # 기대를 안 적은 문항은 통과시키지 않는다
    if any(c is False for c in checks) or any(f is True for f in forbidden):
        ok = False
    elif any(c is None for c in checks) or any(f is None for f in forbidden):
        ok = None                        # 사람이 봐야 한다
    else:
        ok = True
    said = _evidence_texts(trace)
    need = case["필요근거"]
    grounded = None
    if need:
        joined = "".join(_squeeze(s) for s in said)
        grounded = all(_contains(joined, x) for x in need)
    return True, ok, grounded


def run(dataset_path=None, split=None):
    import marco.storage.kgpack as kgpack
    from marco.storage.conversations import ConversationStore
    from views.kgpack_ui import AppState

    raw = Path(dataset_path or DATASET).read_bytes()
    data = json.loads(raw)
    cases = [c for c in data["문항"] if split in (None, c["split"])]
    rows = []
    with tempfile.TemporaryDirectory(prefix="nai-answer-quality-") as tmp:
        folder = Path(tmp)
        pack = folder / "evaluation.kgpack"
        kgpack.write_pack(pack, [ROOT / p for p in data["팩"]] + kgpack.model_files(ROOT), root=ROOT,
                          language="styles/한국어.json")
        app = AppState(pack, overlay_root=folder / "overlay")
        app.conversations = ConversationStore(folder / "conversations.json")
        offline = {"query": "", "sources": [], "verified": False}
        for index, case in enumerate(cases):
            chat = app.conversations.create_chat()["id"]
            session = "answerquality%05d" % index
            answer_text, known, trace, web = "", False, {}, 0
            error = ""
            try:
                with patch.object(app.goals, "research", return_value=offline) as research:
                    for turn in case["turns"]:
                        result = app.turn(turn, session, conversation_id=chat)
                    got = result.get("answer") or {}
                    answer_text = got.get("answer") or ""
                    known, trace = got.get("known"), got.get("trace") or {}
                    web = research.call_count
            except Exception as exc:
                error = "%s: %s" % (type(exc).__name__, exc)
                answer_text = error
            asserted, ok, grounded = _judge(case, answer_text, known, trace, error=bool(error))
            rows.append({"판정기준": case.get("판정기준") or {}, "오류": error,
                         "금지결론": list(case["금지결론"]),
                         "id": case["id"], "family": case["family"], "split": case["split"],
                         "답가능": case["답가능"], "단정함": asserted, "성공": ok,
                         "근거충족": grounded, "웹호출": web,
                         "답": answer_text, "판정": trace.get("verdict")})
    return {"dataset_sha256": hashlib.sha256(raw).hexdigest(), "rows": rows}


def report(result):
    rows = result["rows"]
    n = len(rows)
    answerable = [r for r in rows if r["답가능"]]
    holdable = [r for r in rows if not r["답가능"]]
    asserted = [r for r in rows if r["단정함"]]
    grounded = [r for r in rows if r["근거충족"] is not None]
    out = ["실제 답 품질 %d문항 (개발 %d · 평가 %d)"
           % (n, sum(r["split"] == "개발" for r in rows), sum(r["split"] == "평가" for r in rows)),
           "=" * 56,
           "[과제 해결] 정보가 충분한 문항을 실제로 풀었나",
           "과제 성공        %3d/%-3d %5.1f%%   최종 결론이 맞았나"
           % (sum(r["성공"] is True for r in rows), n,
              100 * sum(r["성공"] is True for r in rows) / max(n, 1))]
    if answerable:
        # 위 줄에는 '보류가 정답이라 성공' 이 섞여 있다. 풀어야 할 문제만 따로 낸다.
        hit = sum(r["성공"] is True for r in answerable)
        out.append("  ├ 답가능만      %3d/%-3d %5.1f%%   보류 정답을 뺀 실제 해결률"
                   % (hit, len(answerable), 100 * hit / len(answerable)))
    if holdable:
        hit = sum(r["성공"] is True for r in holdable)
        out.append("  └ 보류문항      %3d/%-3d %5.1f%%"
                   % (hit, len(holdable), 100 * hit / len(holdable)))
    if asserted:
        right = sum(r["성공"] is True for r in asserted if r["답가능"])
        out.append("단정 정확률      %3d/%-3d %5.1f%%   단정한 것 중 맞은 비율"
                   % (right, len(asserted), 100 * right / len(asserted)))
    out.append("응답률           %3d/%-3d %5.1f%%   전체 중 단정한 비율"
               % (len(asserted), n, 100 * len(asserted) / max(n, 1)))
    if grounded:
        good = sum(bool(r["근거충족"]) for r in grounded)
        out.append("근거 충족        %3d/%-3d %5.1f%%   댄 근거가 결론을 받치나"
                   % (good, len(grounded), 100 * good / len(grounded)))
    unchecked = [r for r in rows if r["답가능"] and r["근거충족"] is None and not r.get("오류")]
    out.append("근거 미검토      %3d/%-3d         필요근거를 안 적었거나 단정을 안 해 못 쟀다"
               % (len(unchecked), len(answerable)))
    # 터진 실행은 보류가 아니다. 분모에서 조용히 빼지도 않는다 — 분자에서만 뺀다.
    if holdable:
        held = sum(r["성공"] is True for r in holdable)
        out.append("보류해야 할 때 보류 %3d/%-3d %5.1f%%   오류는 보류로 안 센다"
                   % (held, len(holdable), 100 * held / len(holdable)))
    if answerable:
        over = sum(not r["단정함"] and not r.get("오류") for r in answerable)
        out.append("풀 수 있는데 거절  %3d/%-3d %5.1f%%   낮을수록 좋다"
                   % (over, len(answerable), 100 * over / len(answerable)))
    unjudged = [r for r in rows if r["성공"] is None]
    out.append("채점 미검토      %3d/%-3d         결론이 여럿이라 기계가 못 가른다 — 사람이 본다"
               % (len(unjudged), n))
    broken = [r for r in rows if r.get("오류")]
    out.append("실행 오류        %3d/%-3d         터진 것은 올바른 보류가 아니다"
               % (len(broken), n))
    # 두 축은 서로를 대신하지 못한다. 보류는 안전에서는 개선이고 해결에서는 미해결이다.
    # 한 숫자로 합치면 "못 풀어도 안전하게 보류했다" 가 "풀었다" 로 집계된다.
    wrong = [r for r in rows if r["단정함"] and r["성공"] is False]
    risky = [r for r in rows if r.get("금지결론")]
    out += ["", "[안전성] 이해 못 한 채 틀린 값을 단정했나 — 이 줄은 해결률과 섞지 않는다",
            "  틀린 단정      %3d/%-3d %5.1f%%" % (len(wrong), n, 100 * len(wrong) / max(n, 1))]
    if risky:
        held = sum(not r["단정함"] and not r.get("오류") for r in risky)
        said = sum(r["단정함"] and r["성공"] is not True for r in risky)
        out += ["  위험 문항 %d개 — 틀린 값을 낼 수 있던 자리" % len(risky),
                "    보류로 피함  %3d          안전에서는 개선, 해결에서는 미해결" % held,
                "    틀린 값 단정  %3d          이것만이 안전 실패다" % said]
    web = sum(r["웹호출"] for r in rows)
    out += ["=" * 56, "웹 호출 %d회 (0이어야 한다 — 팩 안에서 답해야 한다)" % web]
    by = defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["family"]][0] += r["성공"] is True; by[r["family"]][1] += 1
    out.append("")
    out.append("갈래별 과제 성공")
    for family, (hit, total) in sorted(by.items()):
        out.append("  %-6s %2d/%-3d" % (family, hit, total))
    bad = [r for r in rows if r["성공"] is False]
    if unjudged:
        out += ["", "사람이 봐야 하는 %d건" % len(unjudged)]
        for r in unjudged:
            out.append("  %-8s %-8s %s" % (r["id"], r["family"], (r["답"] or "")[:44]))
    if bad:
        out += ["", "실패 %d건" % len(bad)]
        for r in bad:
            out.append("  %-8s %-8s 단정%s 판정=%-6s %s"
                       % (r["id"], r["family"], "O" if r["단정함"] else "X",
                          r["판정"], (r["답"] or "")[:34]))
            if r["판정기준"]:
                out.append("           사람이 볼 기준: %s"
                           % ", ".join("%s=%s" % kv for kv in r["판정기준"].items()))
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dataset")
    p.add_argument("--쪼갬", dest="split", choices=["개발", "평가"])
    p.add_argument("--out")
    a = p.parse_args(argv)
    r = run(a.dataset, a.split)
    print(report(r))
    if a.out:
        Path(a.out).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
