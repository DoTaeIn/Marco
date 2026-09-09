import re

with open("vision.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Modify _표적덩어리후보 signature and return logic
def repl_cand(m):
    # m.group(1) is the append line
    # m.group(2) is the rest of the function
    return m.group(0).replace(
        '점수.append((float(s), (y0, y0 + 창h, x0, x0 + 창w)))',
        '점수.append((float(s), (y0, y0 + 창h, x0, x0 + 창w), 덩이))'
    ).replace(
        'for s, 상자 in 점수:',
        'for s, 상자, 덩이 in 점수:'
    ).replace(
        'if all(_창겹침(상자, 앞상자) < .5 for _, 앞상자 in 답):',
        'if all(_창겹침(상자, 앞상자) < .5 for _, 앞상자, _ in 답):'
    ).replace(
        '답.append((s, 상자))',
        '답.append((s, 상자, 덩이))'
    )

content = re.sub(r'(def _표적덩어리후보.*?(?=def _상자영수증))', repl_cand, content, flags=re.DOTALL)

# 2. Modify _상자영수증
def repl_receipt(m):
    return m.group(0).replace(
        'for _, (y0, y1, x0, x1) in 묶음:',
        'for 항목 in 묶음:\n            y0, y1, x0, x1 = 항목[1]'
    )

content = re.sub(r'(def _상자영수증.*?(?=def _국소다시맞히기))', repl_receipt, content, flags=re.DOTALL)

# 3. Add _볼록껍질영역만 above _영역중심
new_func = """
def _볼록껍질영역만(seg, 라벨, 이웃, 덩이, 여백=0.12):
    \"\"\"1홉 매칭 영역의 볼록 껍질 내부에 든 SLIC 영역만 남긴 유도 부분그래프.\"\"\"
    from skimage.morphology import convex_hull_image, dilation, disk
    m = np.isin(seg, list(덩이))
    if not m.any():
        return [], []
    m_hull = convex_hull_image(m)
    yy, xx = np.where(m)
    pad = max(4, int(max(yy.max() - yy.min() + 1, xx.max() - xx.min() + 1) * 여백))
    if pad > 0:
        m_hull = dilation(m_hull, disk(pad))
    yy_cen, xx_cen = _영역중심(seg)
    남 = []
    for i in range(len(라벨)):
        yc, xc = int(yy_cen[i]), int(xx_cen[i])
        if 0 <= yc < m_hull.shape[0] and 0 <= xc < m_hull.shape[1]:
            if m_hull[yc, xc]:
                남.append(i)
    새번호 = {i: k for k, i in enumerate(남)}
    return ([라벨[i] for i in 남],
            [[새번호[j] for j in 이웃[i] if j in 새번호] for i in 남])

def _영역중심(seg):
"""
content = content.replace("def _영역중심(seg):", new_func.strip() + "\n", 1)

# 4. Modify 표적스캔시험
# a) signature
content = content.replace(
    '표적번호=None, 씨=1, 유도=False, 연결=False):',
    '표적번호=None, 씨=1, 유도=False, 연결=False, 볼록껍질=False):'
)

# b) logic inside 표적스캔시험
old_for_loop = """            for _, (y0, y1, x0, x1) in 후보들:
                if 유도:
                    라벨, 옆 = _상자영역만(seg, 장라벨, 장옆, (y0, y1, x0, x1))"""
new_for_loop = """            for 후보 in 후보들:
                if len(후보) == 3:
                    _, 상자, 덩이 = 후보
                else:
                    _, 상자 = 후보
                    덩이 = None
                y0, y1, x0, x1 = 상자
                if 유도:
                    if 볼록껍질 and 덩이 is not None:
                        라벨, 옆 = _볼록껍질영역만(seg, 장라벨, 장옆, 덩이)
                    else:
                        라벨, 옆 = _상자영역만(seg, 장라벨, 장옆, 상자)"""
content = content.replace(old_for_loop, new_for_loop)
content = content.replace(
    '결과 = _자른화폭맞히기(판[y0:y1, x0:x1], 틀, 낱, 3)',
    '결과 = _자른화폭맞히기(판[y0:y1, x0:x1], 틀, 낱, 3)' # No change here, just checking
)

# 5. Modify args parsing in __main__
content = content.replace(
    '연결="--연결" in sys.argv)',
    '연결="--연결" in sys.argv, 볼록껍질="--볼록껍질" in sys.argv)'
)

with open("vision.py", "w", encoding="utf-8") as f:
    f.write(content)
