# -*- coding: utf-8 -*-
"""언어중립 알고리즘을 언어별 말투로 찍어내고, 실제로 돌려서 채점한다.

이 파일이 하는 일은 설명.py 가 경로를 한국어나 영어로 뽑는 것과 **같은
연산**이다. 내용(알고리즘)과 표현(문법)을 갈라두면 표현은 갈아끼우면 된다.
styles/한국어.json 이 있는 자리에 styles/코드/python.json 이 있을 뿐이다.

고르기가 아니라 짓기다. 자료에 없던 조합도 나온다 — 이진검색은 러스트로
쓴 적이 없어도 러스트 말투만 있으면 뽑힌다.

그리고 이 도메인에는 **검증자가 공짜다.** 돌려보면 맞았는지 알 수 있다.
문장은 사람이 봐줘야 하지만 코드는 아니다. 창작 루프를 여기서 먼저 만드는
이유가 그것이다.
"""
import copy
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(here, p)


def read_dialect(lang):
    """모르는 언어는 지어내지 않는다. 말투 파일이 곧 아는 언어의 목록이다."""
    path = _abs("styles/코드/%s.json" % lang)
    if not os.path.exists(path):
        raise ValueError("%s 는 모르는 언어입니다. 아는 언어: %s. "
                         "styles/코드/%s.json 을 지으면 그날부터 압니다."
                         % (lang, ", ".join(dialects()), lang))
    return json.load(io.open(path, encoding="utf-8"))


def dialects():
    return sorted(x[:-5] for x in os.listdir(_abs("styles/코드"))
                  if x.endswith(".json"))


def read_algo(path):
    return json.load(io.open(_abs(path), encoding="utf-8"))


_particle_pair = {"을": ("을", "를"), "이": ("이", "가"), "은": ("은", "는"),
           "와": ("과", "와"), "으로": ("으로", "로")}
_table = re.compile(r"\{~(을|이|은|와|으로)\}")


def _batchim(txt, pos):
    """조사 앞 글자에 받침이 있나. 닫는 괄호와 빈칸은 건너뛴다 —
    'target(정수)' 뒤에 붙는 조사는 '수' 를 보고 골라야 한다."""
    i = pos - 1
    while i >= 0 and txt[i] in ") ]\"'":
        i -= 1
    if i < 0:
        return True
    c = txt[i]
    if "가" <= c <= "힣":
        import hangul
        return bool(hangul.batchim(c))
    if c.isdigit():
        return c in "01367"          # 영 일 삼 육 칠 팔 에 받침이 있다
    return c.lower() not in "aeiouy"  # 로마자는 소리로 가른다


def _fit_particle(txt):
    """{~을} 같은 자리를 앞 글자에 맞춰 을/를로 굳힌다."""
    while True:
        m = _table.search(txt)
        if not m:
            return txt
        has, none = _particle_pair[m.group(1)]
        pick = has if _batchim(txt, m.start()) else none
        txt = txt[:m.start()] + pick + txt[m.end():]


def _template_variants(template):
    """읽을 때는 둘 다 받는다. 사람은 '정수를' 이라 쓰고 틀은 '정수을'
    이라 적혀 있어도 같은 말이다."""
    m = _table.search(template)
    if not m:
        return [template]
    parts = []
    for pick in _particle_pair[m.group(1)]:
        parts += _template_variants(template[:m.start()] + pick + template[m.end():])
    return parts


def _fill(template, **slot):
    """{이름} 같은 자리를 채운다. str.format 을 안 쓰는 이유는 틀 안에
    중괄호가 있기 때문이다 — 자바와 JS 의 블록이 그것이다."""
    for k, v in slot.items():
        template = template.replace("{%s}" % k, v)
    return template


def _indent(txt, dialect, level=1):
    slot = dialect["들여쓰기"] * level
    return "\n".join(slot + line if line.strip() else line for line in txt.split("\n"))


def _ARG_SEP(dialect):
    return dialect.get("인자사이") or dialect["입력사이"]


def emit_expr(dialect, expr):
    """식을 낸다. 잎(이름·수)은 값 그대로, 나머지는 재귀."""
    form = expr[0]
    if form == "부름":
        # 부르는 자리의 구분자는 선언하는 자리와 다를 수 있다. 파워셸이
        # 그렇다 — 선언은 f($a, $b) 인데 부르기는 f $a $b 이고, 식 안에서는
        # 괄호로 싸야 한다. C 계열만 보면 안 보이던 가정이었다.
        argv = _ARG_SEP(dialect).join(emit_expr(dialect, x) for x in expr[2:])
        return _fill(dialect.get("호출식") or dialect["호출"], **{"이름": expr[1], "인자": argv})
    template = dialect["식"].get(form)
    if template is None:
        raise KeyError("%s 말투에 식 '%s' 이(가) 없다" % (dialect["이름"], form))
    if form in ("이름", "수"):
        chunk = [str(expr[1])]
    else:
        chunk = [emit_expr(dialect, x) for x in expr[1:]]
    for i, c in enumerate(chunk):
        template = template.replace("{%d}" % i, c)
    return template


def emit_stmt(dialect, stmt):
    """한 문장. 블록을 안는 문은 몸을 한 겹 들여 안에 박는다."""
    form = stmt[0]
    if form == "선언":
        _, name, typ, expr = stmt
        return _fill(dialect["선언"], **{"이름": name, "형": dialect["형"][typ],
                                       "식": emit_expr(dialect, expr)})
    if form == "대입":
        return _fill(dialect["대입"], **{"이름": stmt[1], "식": emit_expr(dialect, stmt[2])})
    if form == "색인대입":
        return _fill(dialect["색인대입"], **{"열": emit_expr(dialect, stmt[1]),
                                         "자리": emit_expr(dialect, stmt[2]),
                                         "식": emit_expr(dialect, stmt[3])})
    if form == "반환":
        return _fill(dialect["반환"], **{"식": emit_expr(dialect, stmt[1])})
    if form == "반복":
        return _fill(dialect["반복"], **{"조건": emit_expr(dialect, stmt[1]),
                                       "몸": emit_body(dialect, stmt[2])})
    if form == "분기":
        orelse = stmt[3] if len(stmt) > 3 else []
        if orelse:
            return _fill(dialect["분기아니면"], **{"조건": emit_expr(dialect, stmt[1]),
                                              "몸": emit_body(dialect, stmt[2]),
                                              "아니면": emit_body(dialect, orelse)})
        return _fill(dialect["분기"], **{"조건": emit_expr(dialect, stmt[1]),
                                       "몸": emit_body(dialect, stmt[2])})
    raise KeyError("모르는 문 '%s'" % form)


def emit_body(dialect, stmts):
    return "\n".join(_indent(emit_stmt(dialect, f), dialect) for f in stmts)


def _emit_value(dialect, v):
    if isinstance(v, list):
        entry = ", ".join(_emit_value(dialect, x) for x in v)
        return _fill(dialect["열"], **{"항목": entry})
    return str(v)


def build(algo, dialect):
    """알고리즘 하나를 그 언어의 소스 한 벌로."""
    inp = dialect["입력사이"].join(
        _fill(dialect["입력항"], **{"이름": n, "형": dialect["형"][t]}) for n, t in algo["입력"])
    func = _fill(dialect["함수"], **{"이름": algo["이름"], "입력": inp,
                                   "반환형": dialect["형"][algo["반환형"]],
                                   "몸": emit_body(dialect, algo["몸"])})
    test = []
    for c in algo.get("시험", ()):
        argv = _ARG_SEP(dialect).join(_emit_value(dialect, v) for v in c["인자"])
        call = _fill(dialect["호출"], **{"이름": algo["이름"], "인자": argv})
        # 열은 언어마다 찍는 꼴이 달라(파이썬 [1, 2] · JS [1,2] · 자바 주소)
        # 그대로는 견줄 수 없다. 쉼표로 이은 한 줄로 맞춘다.
        template = (dialect["열시험줄"] if algo["반환형"] == "정수열"
              else dialect["시험줄"])
        test.append(_fill(template, **{"호출": call}))
    func = _fit_particle(func)
    test = [_fit_particle(x) for x in test]
    deep = dialect.get("겉들여쓰기", 0)
    hour_deep = dialect.get("시험들여쓰기", 0)
    return _fill(dialect["겉"], **{"함수들": _indent(func, dialect, deep) if deep else func, "시험": _indent("\n".join(test), dialect, hour_deep) if hour_deep
                 else "\n".join(test)})


def run(algo, lang, keep=None):
    """찍어서 실제로 돌리고 기댓값과 견준다. 검증자는 실행이다."""
    dialect = read_dialect(lang)
    source_code = build(algo, dialect)
    workdir = keep or tempfile.mkdtemp(prefix="kgbuild_")   # 한글 경로는 자바가 깨먹는다
    name = dialect.get("파일이름") or algo["이름"]
    path = os.path.join(workdir, "%s.%s" % (name, dialect["확장자"]))
    io.open(path, "w", encoding="utf-8").write(source_code)
    cmd = [x.replace("{파일}", path) for x in dialect["실행"]]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as e:                      # 실행기가 없을 수 있다
        return {"언어": lang, "소스": source_code, "탈": str(e), "맞": 0,
                "전체": len(algo.get("시험", ()))}
    if p.returncode != 0:
        return {"언어": lang, "소스": source_code, "탈": (p.stderr or "")[:400],
                "맞": 0, "전체": len(algo.get("시험", ()))}
    got = [x.strip() for x in p.stdout.strip().split("\n") if x.strip()]
    expected = [str(c["기대"]) for c in algo.get("시험", ())]
    hit = sum(1 for a, b in zip(got, expected) if a == b)
    return {"언어": lang, "소스": source_code, "탈": None, "맞": hit, "전체": len(expected),
            "난것": got, "기대": expected}


def measure(algo, langs):
    acc = []
    for lang_ in langs:
        r = run(algo, lang_)
        acc.append(r)
        table = "O" if r["탈"] is None and r["맞"] == r["전체"] else "X"
        print("  %s %-12s %d/%d %s"
              % (table, lang_, r["맞"], r["전체"],
                 ("← " + r["탈"].strip().split("\n")[0][:90]) if r["탈"] else ""))
    return acc


def regression(folder="algorithms", langs=None):
    """있는 알고리즘 전부를 있는 언어 전부로 찍어 돌린다.

    N개 알고리즘 x M개 언어 = N*M 벌이고, 사람이 쓴 것은 N + M 벌뿐이다.
    나머지는 이 파일이 지었다. 자료에 없던 조합도 돈다 — 그것이 고르기와
    짓기의 차이다."""
    if langs is None:
        langs = [x for x in dialects() if not read_dialect(x).get("산문")]
    alive, before = 0, 0
    for f in sorted(os.listdir(_abs(folder))):
        if not f.endswith(".json"):
            continue
        algo = read_algo(os.path.join(folder, f))
        print("%s — %s" % (algo["이름"], algo.get("설명", "")))
        for r in measure(algo, list(langs)):
            before += 1
            alive += (r["탈"] is None and r["맞"] == r["전체"])
        print()
    print("돌아가는 벌 %d/%d (%.0f%%)" % (alive, before, 100.0 * alive / max(before, 1)))
    return alive, before


def _selfcheck():
    """찍기만 보는 검사. 실행기가 없는 데서도 돈다."""
    # 채점기가 제 원본을 못 알아보면 그 아래 숫자가 전부 거짓이다.
    # 선택정렬이 0/4 였을 때 코드는 완벽했다 — 통과율만 보고 있었으면
    # '아직 안 되는구나' 로 지나갔을 것이다. 가장 먼저 본다.
    _pass_count, _whole, _leaked, _penalty = groups()
    assert _whole and _pass_count == _whole, (_pass_count, _whole)
    assert _penalty, "망가뜨릴 자리가 없다 — 묶임을 못 잰다"
    know = read_algo("algorithms/이진검색.json")
    py = build(know, read_dialect("python"))
    assert "def binary_search(a, target):" in py, py
    assert "(lo + hi) // 2" in py, py
    java = build(know, read_dialect("java"))
    assert "static int binary_search(int[] a, int target)" in java, java
    assert "(lo + hi) / 2" in java and "//" not in java, java
    skin = build(know, read_dialect("powershell"))
    assert "$lo -le $hi" in skin, skin
    # 같은 내용이 말투만 갈려 나온다 - 한국어/영어와 같은 연산이다.
    for txt in (py, java, skin):
        assert txt.count("return") >= 2, txt
    ps = build(read_algo("algorithms/최대공약수.json"), read_dialect("powershell"))
    assert "(gcd $b ($a % $b))" in ps, ps    # 부르는 자리 구분자가 다르다
    # 왕복 - 찍은 산문을 도로 뜯으면 처음 설계도가 그대로 나와야 한다
    one_ = read_dialect("한국어")
    parsed = parse_algo(one_, build(know, one_))
    for k in ("이름", "입력", "반환형", "몸"):
        assert parsed[k] == know[k], (k, parsed[k])
    print("selfcheck ok")


# ── 거꾸로: 산문에서 설계도를 뜯어낸다 ──────────────────────────────
#
# 찍는 데 쓴 틀을 그대로 뒤집어 쓴다. 틀이 하나뿐이니 찍기와 읽기가 어긋날
# 수 없다 — 어긋나면 왕복이 깨져서 바로 안다.
#
# 왕복이 곧 채점기다. 설계도 → 한국어 → 설계도 → 코드 → 실행 을 돌려
# 답이 그대로 맞으면 제대로 읽은 것이다. 사람이 봐줄 필요가 없다.


def _split(template):
    """틀을 글자 조각과 구멍으로 가른다. '({0}이 {1}과 같으)' 는
    ['(', '이 ', '과 같으)'] 와 ['0', '1'] 이 된다."""
    chunk, hole, other = [], [], template
    while True:
        i = other.find("{")
        if i < 0:
            chunk.append(other)
            return chunk, hole
        j = other.index("}", i)
        chunk.append(other[:i])
        hole.append(other[i + 1:j])
        other = other[j + 1:]


def _fit(template, txt):
    if "{~" in template:
        for x in _template_variants(template):
            m = _fit(x, txt)
            if m is not None:
                return m
        return None
    return _fit_one(template, txt)


def _fit_one(template, txt):
    """글을 틀에 맞춰 구멍의 내용을 뽑는다. 없으면 None.

    괄호 깊이를 센다. 안 세면 '((a의 mid번째)이 target과 같으)' 에서
    안쪽 괄호의 글자가 바깥 틀의 글자로 잘못 걸린다."""
    chunk, hole = _split(template)
    if not txt.startswith(chunk[0]):
        return None
    pos, value = len(chunk[0]), []
    for k in range(1, len(chunk)):
        find = chunk[k]
        depth, here, found = 0, pos, -1
        while here < len(txt):
            # 맞춰본 뒤에 깊이를 옮긴다. 먼저 옮기면 여는 괄호로 시작하는
            # 조각('(' 하나짜리)이 제 자리에서 안 걸린다.
            if depth == 0 and find and txt.startswith(find, here):
                found = here
                break
            c = txt[here]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth < 0:
                    return None
            here += 1
        if find == "":                      # 마지막 조각이 비면 끝까지
            found = len(txt)
        if found < 0 or found <= pos:
            return None
        value.append(txt[pos:found])
        pos = found + len(find)
    if pos != len(txt):
        return None
    return dict(zip(hole, value)) if hole else {}


def parse_expr(dialect, txt):
    """산문 한 토막을 식으로. 잎이 아니면 반드시 괄호로 싸여 있다."""
    txt = txt.strip()
    if not txt.startswith("("):
        try:
            return ["수", int(txt)]
        except ValueError:
            return ["이름", txt]
    call_template = dialect.get("호출식")
    if call_template:
        m = _fit(call_template, txt)
        if m and "이름" in m:
            argv = _split_by_depth(m["인자"], _ARG_SEP(dialect))
            return ["부름", m["이름"]] + [parse_expr(dialect, x) for x in argv]
    for form, template in dialect["식"].items():
        if form in ("이름", "수"):
            continue
        m = _fit(template, txt)
        if m is not None:
            order = sorted(m, key=int)
            return [form] + [parse_expr(dialect, m[k]) for k in order]
    raise ValueError("못 읽는 식: %s" % txt)


def _split_by_depth(txt, between):
    """괄호 밖에서만 가른다."""
    depth, pos, parts = 0, 0, []
    i = 0
    while i < len(txt):
        c = txt[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0 and txt.startswith(between, i):
            parts.append(txt[pos:i])
            i += len(between)
            pos = i
            continue
        i += 1
    parts.append(txt[pos:])
    return [x for x in parts if x.strip()]


def _strip(lines, slot):
    return [x[len(slot):] if x.startswith(slot) else x for x in lines]


def parse_body(dialect, lines):
    """들여쓰기로 블록을 가른다. 찍을 때 쓴 그 들여쓰기다."""
    slot = dialect["들여쓰기"]
    trunk, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        inner = []
        j = i + 1
        while j < len(lines) and (lines[j].startswith(slot) or not lines[j].strip()):
            inner.append(lines[j])
            j += 1
        inner = _strip(inner, slot)

        head = dialect["반복"].split("\n")[0]
        m = _fit(head, line)
        if m is not None:
            trunk.append(["반복", parse_expr(dialect, m["조건"]), parse_body(dialect, inner)])
            i = j
            continue
        head = dialect["분기"].split("\n")[0]
        m = _fit(head, line)
        if m is not None:
            then = parse_body(dialect, inner)
            orelse = []
            divide = dialect["분기아니면"].split("\n")[2]
            if j < len(lines) and lines[j].strip() == divide.strip():
                k = j + 1
                inside = []
                while k < len(lines) and (lines[k].startswith(slot)
                                         or not lines[k].strip()):
                    inside.append(lines[k])
                    k += 1
                orelse = parse_body(dialect, _strip(inside, slot))
                j = k
            trunk.append(["분기", parse_expr(dialect, m["조건"]), then, orelse])
            i = j
            continue
        for form in ("선언", "색인대입", "대입", "반환"):   # 좁은 틀을 먼저
            m = _fit(dialect[form], line)
            if m is None:
                continue
            if form == "선언":
                trunk.append(["선언", m["이름"], "정수", parse_expr(dialect, m["식"])])
            elif form == "대입":
                trunk.append(["대입", m["이름"], parse_expr(dialect, m["식"])])
            elif form == "색인대입":
                trunk.append(["색인대입", parse_expr(dialect, m["열"]),
                           parse_expr(dialect, m["자리"]), parse_expr(dialect, m["식"])])
            else:
                trunk.append(["반환", parse_expr(dialect, m["식"])])
            break
        else:
            raise ValueError("못 읽는 줄: %s" % line)
        i += 1
    return trunk


def parse_algo(dialect, txt):
    """산문 한 벌을 설계도로.

    '시험: [5] -> 120' 줄은 따로 걷는다. 무엇을 하는지는 산문이
    말하지만 무엇이 맞는지는 말하지 않는다 — 그건 채점기의 몫이다."""
    lines, test = [], []
    for line in txt.rstrip().split(chr(10)):
        if line.strip().startswith("시험:"):
            left, _, right = line.split(":", 1)[1].partition("->")
            right = right.strip()
            expected = json.loads(right) if right[:1] in "-0123456789[" else right
            # 열을 내놓는 알고리즘의 기대값은 '찍힌 꼴' 이다. 채점이
            # 표준출력을 문자열로 견주므로(재기·셈하기 둘 다), 산문의
            # [1, 2, 3] 을 여기서 '1, 2, 3' 으로 맞춘다. 안 맞추면 코드가
            # 옳아도 시험이 전부 떨어진다 — 선택정렬이 0/3 이었다.
            if isinstance(expected, list):
                expected = ", ".join(str(x) for x in expected)
            test.append({"인자": json.loads(left.strip()), "기대": expected})
        else:
            lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    head = dialect["함수"].split("\n")[0]
    m = _fit(head, lines[0].strip())
    if m is None:
        raise ValueError("머리를 못 읽는다: %s" % lines[0])
    reverse_form = {v: k for k, v in dialect["형"].items()}
    inp = []
    for t in _split_by_depth(m["입력"], dialect["입력사이"]):
        s = _fit(dialect["입력항"], t.strip())
        if s is None:
            raise ValueError("입력을 못 읽는다: %s" % t)
        inp.append([s["이름"], reverse_form.get(s["형"], s["형"])])
    algo = {"이름": m["이름"], "입력": inp,
            "반환형": reverse_form.get(m["반환형"], m["반환형"]),
            "몸": parse_body(dialect, _strip(lines[1:], dialect["들여쓰기"])),
            "시험": test}
    # 산문에는 변수의 형이 안 적힌다. 길이·색인을 받는 이름은 열이다.
    col_name = set(n for n, t in inp if t == "정수열")
    _fill_shape(algo["몸"], col_name)
    return algo


def _fill_shape(trunk, col_name):
    for stmt in trunk:
        if stmt[0] == "선언":
            stmt[2] = "정수열" if (stmt[3][0] == "이름"
                                 and stmt[3][1] in col_name) else "정수"
        for x in stmt:
            if isinstance(x, list) and x and isinstance(x[0], list):
                _fill_shape(x, col_name)


def prose_regression(folder="algorithms/산문", lang="한국어"):
    """사람이 손으로 쓴 한국어를 그대로 코드로 만들어 돌린다.

    왕복과 다르다. 왕복은 제가 찍은 산문을 도로 읽는 것이라 문체가 제
    것이다. 여기 든 글은 사람이 쓴 것이고 조사도 사람 마음대로다 —
    '정수를' 이라 써도 틀에는 '정수을' 이라 적혀 있다."""
    dialect = read_dialect(lang)
    target_langs = [x for x in dialects()
              if x != lang and not read_dialect(x).get("산문")]
    alive, penalty = 0, 0
    workdir = _abs(folder)
    if not os.path.isdir(workdir):
        return 0, 0
    for f in sorted(os.listdir(workdir)):
        if not f.endswith(".txt"):
            continue
        txt = io.open(os.path.join(workdir, f), encoding="utf-8").read()
        try:
            algo = parse_algo(dialect, txt)
        except Exception as e:
            print("  X %-20s 못 읽음 — %s" % (f, e))
            penalty += len(target_langs)
            continue
        print("%s ← %s" % (algo["이름"], f))
        for r in measure(algo, target_langs):
            penalty += 1
            alive += (r["탈"] is None and r["맞"] == r["전체"])
        print()
    print("  사람이 쓴 한국어에서 도는 벌 %d/%d" % (alive, penalty))
    return alive, penalty


def roundtrip(folder="algorithms", lang="한국어"):
    """설계도 → 산문 → 설계도. 그리고 뜯어낸 것으로 코드를 찍어 돌린다.

    앞의 견줌이 읽기가 맞았는지 보고, 뒤의 실행이 그 읽은 것이 진짜 도는
    물건인지 본다. 둘 다 사람 없이 매겨진다."""
    dialect = read_dialect(lang)
    same, before, alive, penalty = 0, 0, 0, 0
    target_langs = [x for x in dialects()
              if x != lang and not read_dialect(x).get("산문")]
    for f in sorted(os.listdir(_abs(folder))):
        if not f.endswith(".json"):
            continue
        orig = read_algo(os.path.join(folder, f))
        alive_stmt = build(orig, dialect)
        before += 1
        try:
            parsed = parse_algo(dialect, alive_stmt)
        except Exception as e:
            print("  X %-14s 못 읽음 — %s" % (orig["이름"], e))
            continue
        must = ["이름", "입력", "반환형", "몸"]
        hit = all(parsed[k] == orig[k] for k in must)
        same += hit
        print("  %s %-14s 왕복 %s" % ("O" if hit else "X", orig["이름"],
                                      "같음" if hit else "다름"))
        if not hit:
            for k in must:
                if parsed[k] != orig[k]:
                    print("      %s: %s" % (k, json.dumps(parsed[k],
                                                          ensure_ascii=False)[:160]))
            continue
        parsed["시험"] = orig.get("시험", [])       # 시험은 산문에 안 적힌다
        for r in measure(parsed, target_langs):
            penalty += 1
            alive += (r["탈"] is None and r["맞"] == r["전체"])
    print()
    print("  왕복 같음 %d/%d · 뜯은 설계도로 찍어 도는 벌 %d/%d"
          % (same, before, alive, penalty))
    return same, before, alive, penalty


# ── 생각: 머릿속으로 셈하고, 틀리면 고쳐서 다시 ────────────────────
#
# 토큰 기반 AI 의 생각은 토큰 하나씩 고르며 되풀이하는 것이다. 우리의
# 생각은 이 단계들을 오가며 되풀이하는 것이다. 다른 점은 뒤지는 자리다 —
# 토큰 공간은 5만 차원이고 설계도 공간은 작고 구조가 있다.
#
# 뒤지려면 빨라야 한다. 매번 파이썬을 띄우면 한 번에 50ms 라 생각을 몇 번
# 못 한다. 그래서 설계도를 머릿속에서 바로 셈한다. 답이 나오면 그때 진짜
# 언어로 찍어 돌려 확인한다 — 머릿속 셈이 틀렸을 수도 있으니.


class _Returned(Exception):
    def __init__(self, value):
        self.value = value


def evaluate(algo, argv, wall=200000):
    """설계도를 그 자리에서 셈한다. 벽은 무한 되풀이를 끊는다."""
    other = [wall]

    def expr(e, room):
        form = e[0]
        if form == "이름":
            return room[e[1]]
        if form == "수":
            return e[1]
        if form == "부름":
            return evaluate(algo, [expr(x, room) for x in e[2:]], other[0])
        a = expr(e[1], room)
        if form == "길이":
            return len(a)
        b = expr(e[2], room)
        if form == "색인":
            return a[b]
        if form == "더하기":
            return a + b
        if form == "빼기":
            return a - b
        if form == "곱하기":
            return a * b
        if form == "몫":
            return a // b
        if form == "나머지":
            return a % b
        if form == "==":
            return a == b
        if form == "<":
            return a < b
        if form == "<=":
            return a <= b
        if form == ">":
            return a > b
        raise KeyError(form)

    def trunk(stmts, room):
        for f in stmts:
            other[0] -= 1
            if other[0] <= 0:
                raise TimeoutError("벽")
            form = f[0]
            if form in ("선언", "대입"):
                room[f[1]] = expr(f[-1], room)
            elif form == "색인대입":
                expr(f[1], room)[expr(f[2], room)] = expr(f[3], room)
            elif form == "반환":
                raise _Returned(expr(f[1], room))
            elif form == "반복":
                while expr(f[1], room):
                    other[0] -= 1
                    if other[0] <= 0:
                        raise TimeoutError("벽")
                    trunk(f[2], room)
            elif form == "분기":
                trunk(f[2] if expr(f[1], room) else (f[3] if len(f) > 3 else []), room)
            else:
                raise KeyError(form)

    room = {n: (list(v) if isinstance(v, list) else v)
          for (n, _t), v in zip(algo["입력"], argv)}
    try:
        trunk(algo["몸"], room)
    except _Returned as r:
        return r.value
    return None


def mental_score(algo, cut=False):
    """머릿속으로만 채점한다. 실행기를 안 띄우니 1000배 빠르다.

    뒤질 때는 만점인지만 알면 되므로 첫 실패에서 끊는다. 후보 대부분은
    첫 시험에서 떨어지니 이것만으로 시험 수에 안 끌려간다."""
    hit = 0
    for c in algo.get("시험", ()):
        try:
            parts = evaluate(algo, copy.deepcopy(c["인자"]))
        except Exception:
            if cut:
                return hit
            continue
        expected = c["기대"]
        if isinstance(parts, list):
            parts = ", ".join(str(x) for x in parts)
        if str(parts) != str(expected):
            if cut:
                return hit
            continue
        hit += 1
    return hit


_changed = {"<": ("<=",), "<=": ("<",), ">": ("<", "<="), "==": ("<", ">"),
         "더하기": ("빼기",), "빼기": ("더하기",)}


def _paths(trunk, front=()):
    """설계도 안의 모든 마디 자리. 여기가 고칠 수 있는 자리다."""
    for i, x in enumerate(trunk):
        if not isinstance(x, list):
            continue
        yield front + (i,)
        for p in _paths(x, front + (i,)):
            yield p


def _locate(trunk, path):
    x = trunk
    for i in path:
        x = x[i]
    return x


def neighbor(algo):
    """한 군데만 고친 설계도들. 흔한 잘못을 되돌리는 손질만 한다 —
    하나 차이(0/1), 부등호 갈아끼우기, 더하기/빼기 뒤집기."""
    for path in list(_paths(algo["몸"])):
        segment = _locate(algo["몸"], path)
        if not segment or not isinstance(segment[0], str):
            continue
        form = segment[0]
        fixes = []
        if form == "수" and isinstance(segment[1], int):
            fixes = [("수", segment[1] + 1), ("수", segment[1] - 1)]
        elif form in _changed:
            fixes = [(x, None) for x in _changed[form]]
        for new_form, new_value in fixes:
            penalty = copy.deepcopy(algo)
            m = _locate(penalty["몸"], path)
            m[0] = new_form
            if new_value is not None:
                m[1] = new_value
            yield penalty, "%s → %s%s" % (form, new_form,
                                     "" if new_value is None else " %s" % new_value)


def fix(algo, depth=2, wall=4000):
    """틀렸으면 고쳐서 다시. 이것이 이 엔진의 생각이다.

    채점기가 공짜라서 뒤질 수 있다. 사람한테 물어볼 필요가 없다.
    돌려주는 것은 (고친 설계도, 손질 자취) 이고, 못 고치면 (None, 시도수).
    """
    full_score = len(algo.get("시험", ()))
    if not full_score:
        return None, 0
    if mental_score(algo, True) == full_score:
        return algo, []
    seen = {json.dumps(algo["몸"], ensure_ascii=False)}
    head_line = [(algo, [])]
    acc = 0
    for _ in range(depth):
        nxt = []
        for cand, trace in head_line:
            for penalty, phrase in neighbor(cand):
                key = json.dumps(penalty["몸"], ensure_ascii=False)
                if key in seen:
                    continue
                seen.add(key)
                acc += 1
                if acc > wall:
                    return None, acc
                if mental_score(penalty, True) == full_score:
                    return penalty, trace + [phrase]
                nxt.append((penalty, trace + [phrase]))
        head_line = nxt
    return None, acc


def mutate(algo, n_, rng):
    """일부러 망가뜨린다. 고치기를 재려면 고칠 것이 있어야 한다."""
    penalty = copy.deepcopy(algo)
    for _ in range(n_):
        cand = list(neighbor(penalty))
        if not cand:
            return None
        penalty = rng.choice(cand)[0]
    full_score = len(algo.get("시험", ()))
    return penalty if mental_score(penalty, True) < full_score else None


def gather_algo(folder="algorithms"):
    """설계도(.json)와 산문(.txt) 을 한 목록으로. 채점기는 출처를 안 가린다."""
    parts = []
    workdir = _abs(folder)
    if os.path.isdir(workdir):
        for f in sorted(os.listdir(workdir)):
            if f.endswith(".json"):
                parts.append((f, read_algo(os.path.join(folder, f))))
    alive_stmt_dir = os.path.join(workdir, "산문")
    if os.path.isdir(alive_stmt_dir):
        dialect = read_dialect("한국어")
        for f in sorted(os.listdir(alive_stmt_dir)):
            if not f.endswith(".txt"):
                continue
            txt = io.open(os.path.join(alive_stmt_dir, f), encoding="utf-8").read()
            try:
                parts.append((f, parse_algo(dialect, txt)))
            except Exception as e:
                print("  X %-18s 못 읽음 — %s" % (f, e))
    return parts


def groups(folder="algorithms", n__penalty=12, seed=11):
    """시험이 프로그램을 묶는가 — 채점기가 옳고 그름을 **구별하는지** 잰다.

    통과 개수만 세면 채점기가 전부 통과시켜도 전부 떨어뜨려도 모른다.
    실제로 선택정렬이 0/4 였는데 찍힌 코드는 완벽했다 — 기대값을 견주는
    모양이 어긋나 시험이 제 원본조차 못 알아본 것이다. 통과율만 보고
    있었으면 '아직 안 되는구나' 로 지나갔다.

    두 쪽을 다 본다. 한 쪽만 보면 못 잡는다.
      성함  원본이 제 시험을 다 맞히는가. 아니면 채점기가 깨진 것이다.
      묶임  한 군데 망가뜨린 것이 떨어지는가. 안 떨어지면 시험이 헐렁하다.

    `부수기` 는 이미 이 판별을 하고 있었다 — 망가뜨렸는데 만점이 나오면
    None 을 돌려 그 벌을 버린다. 버리지 않고 세면 그것이 곧 이 숫자다.

    손질이 늘 뜻을 바꾸지는 않는다. 안 닿는 자리를 건드리면 답이 그대로인
    것이 맞다. 그래서 이 값은 합격/불합격이 아니라 비율로 읽는다 — 갑자기
    치솟으면 시험이 헐거워졌다는 신호다."""
    rng = random.Random(seed)
    pass_count, whole, leaked, penalty_count = 0, 0, 0, 0
    grade_broken = []
    for name, algo in gather_algo(folder):
        whole += 1
        full_score = len(algo.get("시험", ()))
        pt = mental_score(algo)
        if pt == full_score and full_score:
            pass_count += 1
        else:
            grade_broken.append((name, pt, full_score))
            continue                    # 원본도 못 맞히면 묶임을 잴 수 없다
        cand = [x for x, _ in neighbor(algo)]
        rng.shuffle(cand)
        for penalty in cand[:n__penalty]:
            penalty_count += 1
            leaked += (mental_score(penalty) == full_score)
    print("  원본이 제 시험에 성함     %d/%d" % (pass_count, whole))
    for name, pt, full_score in grade_broken:
        print("    X %-18s %d/%d — 채점기가 이 알고리즘을 못 알아본다"
              % (name, pt, full_score))
    print("  망가뜨렸는데 통과한 벌   %d/%d (%.0f%%)  낮을수록 시험이 좁다"
          % (leaked, penalty_count, 100.0 * leaked / max(penalty_count, 1)))
    return pass_count, whole, leaked, penalty_count


def fix_regression(folder="algorithms", n__penalty=8, seed=7, self_test=12):
    """망가뜨린 설계도를 혼자 고쳐내는가. 그리고 고친 것이 진짜로 도는가.

    두 가지를 갈라 센다.
      통과    시험을 다 맞히는 무언가를 찾았다.
      복구    그것이 원본과 글자 그대로 같다.
    둘이 크게 벌어지면 시험이 프로그램을 못 묶고 있다는 뜻이다. 사람이
    쓴 시험 셋으로는 통과 94%에 복구 56% 였다. 제가 지은 시험 열둘을
    보태면 복구가 75%로 오른다 - 시험은 사람 없이 늘릴 수 있다.
    """
    rng = random.Random(seed)
    alive, exact, before = 0, 0, 0
    check = None
    for f in sorted(os.listdir(_abs(folder))):
        if not f.endswith(".json"):
            continue
        algo = read_algo(os.path.join(folder, f))
        if self_test:
            built = build_test(algo, self_test)
            if len(built) >= 5:
                algo = dict(algo, **{"시험": algo.get("시험", []) + built})
        orig = json.dumps(algo["몸"], ensure_ascii=False)
        for deep in (1, 2):
            parts = 0
            for _ in range(n__penalty * 6):
                if parts >= n__penalty:
                    break
                broken = mutate(algo, deep, rng)
                if broken is None:
                    continue
                parts += 1
                before += 1
                fixed, _trace = fix(broken, depth=deep)
                if fixed is None:
                    continue
                alive += 1
                exact += (json.dumps(fixed["몸"], ensure_ascii=False) == orig)
                if check is None:
                    check = (algo, fixed)
    print("  망가뜨린 설계도 %d벌 → 통과 %d (%.0f%%) · 원본 복구 %d (%.0f%%)"
          % (before, alive, 100.0 * alive / max(before, 1), exact, 100.0 * exact / max(before, 1)))

    # 머릿속 셈이 맞았는지는 진짜로 돌려봐야 안다.
    spin = 0
    if check:
        know_orig, fixed = check
        fixed = dict(fixed, **{"시험": know_orig.get("시험", [])[:3] or know_orig["시험"][:3]})
        to_use = [x for x in dialects() if not read_dialect(x).get("산문")]
        print("  고친 설계도를 진짜 언어로 찍어 돌린다 (%s):" % fixed["이름"])
        for r in measure(fixed, to_use):
            spin += (r["탈"] is None and r["맞"] == r["전체"])
    return alive, exact, before, spin


def build_test(algo, n_=20, seed=3):
    """제가 제 시험을 짓는다. 아무 값이나 넣고 머릿속으로 돌린 답을 적는다.

    사람이 시험을 세 개밖에 안 써주면 그 셋만 통과하는 딴 프로그램이
    수두룩하다 — 고치기가 88% 통과하는데 원본 복구는 64% 였다. 시험은
    많을수록 프로그램을 좁게 묶는다. 그리고 이건 사람 없이 늘릴 수 있다."""
    rng = random.Random(seed)
    got = []
    for _ in range(n_ * 4):
        if len(got) >= n_:
            break
        argv = []
        for _n, t in algo["입력"]:
            if t == "정수열":
                argv.append([rng.randint(-20, 20)
                             for _ in range(rng.randint(1, 7))])
            else:
                argv.append(rng.randint(0, 30))
        try:
            ans = evaluate(algo, copy.deepcopy(argv), 20000)
        except Exception:
            continue
        if ans is None:
            continue
        if isinstance(ans, list):
            ans = ", ".join(str(x) for x in ans)
        got.append({"인자": argv, "기대": ans})
    return got


if __name__ == "__main__":
    if "--check" in sys.argv:
        _selfcheck()
        sys.exit(0)
    argv = [x for x in sys.argv[1:] if not x.startswith("--")]
    if "--고치기" in sys.argv:
        alive, exact, before, spin = fix_regression()
        sys.exit(0 if (before and alive and spin) else 1)
    if "--산문" in sys.argv:
        alive, penalty = prose_regression()
        sys.exit(0 if (penalty and alive == penalty) else 1)
    if "--묶임" in sys.argv:
        pass_count, whole, _leaked, penalty_count = groups()
        sys.exit(0 if (whole and pass_count == whole and penalty_count) else 1)
    if "--왕복" in sys.argv:
        same, before, alive, penalty = roundtrip()
        sys.exit(0 if (same == before and alive == penalty) else 1)
    if "--읽기" in sys.argv:
        dialect = read_dialect("한국어")
        txt = io.open(_abs(argv[0]), encoding="utf-8").read()
        print(json.dumps(parse_algo(dialect, txt), ensure_ascii=False, indent=2))
        sys.exit(0)
    if "--regress" in sys.argv:
        alive, before = regression()
        sys.exit(0 if alive == before else 1)
    langs = argv[1:] or ["python", "javascript", "java"]
    for lang_ in langs:
        try:
            read_dialect(lang_)                  # 안내 문구는 말투읽기 한 곳에만 둔다
        except ValueError as e:
            print(e)
            sys.exit(1)
    algo = read_algo(argv[0] if argv else "algorithms/이진검색.json")
    if "--show" in sys.argv:
        for lang_ in langs:
            print("=" * 60)
            print("# %s" % lang_)
            print(build(algo, read_dialect(lang_)))
        sys.exit(0)
    print("%s — %s" % (algo["이름"], algo.get("설명", "")))
    acc = measure(algo, langs)
    alive = sum(1 for r in acc if r["탈"] is None and r["맞"] == r["전체"])
    print()
    print("  %d/%d 언어에서 돈다" % (alive, len(acc)))
