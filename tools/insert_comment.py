import codecs

with codecs.open("vision.py", "r", "utf-8") as f:
    content = f.read()

commented_code = '''
# ──────────────────────────────────────────────────────────────────────────
# [폐기된 실험: 볼록 껍질(Convex Hull) 유도 부분그래프]
# 
# 아이디어: 1홉 스캔에서 네모 상자(Bounding Box)를 치면 모서리 쪽에 거대한
# 배경 노이즈가 들어오므로, 매칭된 노드들을 팽팽하게 감싸는 '볼록 껍질'을 
# 씌워 노이즈를 물리적으로 깎아내려 시도함.
# 
# 폐기 이유 (정확도 69.8% -> 60.6% 하락):
# 1. 1홉 스캔 결과가 물체 전체를 덮는 게 아니라 양끝 등 파편적으로 잡힘.
# 2. 네모 상자는 여백 덕분에 미매칭된 '몸통'까지 우연히 포섭(문맥 보존)하지만, 
#    볼록 껍질은 매칭된 끝점만 얇게 이어버려서 그 밖에 있던 진짜 뼈대 노드들을
#    유도 그래프에서 가혹하게 탈락(침식)시켜버림.
# 3. 매 후보마다 `convex_hull_image` 수행으로 정밀 검사 시간 40배 폭증.
# (결론: 1홉 스캔이 파편적인 현 상황에서는 엉성한 네모 상자가 오히려 안전함)
#
# def _볼록껍질영역만(seg, 라벨, 이웃, 덩이, 여백=0.12):
#     from skimage.morphology import convex_hull_image, dilation, disk
#     import numpy as np
#     m = np.isin(seg, list(덩이))
#     if not m.any(): return [], []
#     m_hull = convex_hull_image(m)
#     yy, xx = np.where(m)
#     pad = max(4, int(max(yy.max() - yy.min() + 1, xx.max() - xx.min() + 1) * 여백))
#     if pad > 0: m_hull = dilation(m_hull, disk(pad))
#     
#     yy_cen, xx_cen = _영역중심(seg)
#     남 = [i for i in range(len(라벨)) 
#           if 0 <= int(yy_cen[i]) < m_hull.shape[0] and 0 <= int(xx_cen[i]) < m_hull.shape[1] 
#           and m_hull[int(yy_cen[i]), int(xx_cen[i])]]
#     새번호 = {i: k for k, i in enumerate(남)}
#     return ([라벨[i] for i in 남],
#             [[새번호[j] for j in 이웃[i] if j in 새번호] for i in 남])
# ──────────────────────────────────────────────────────────────────────────

def _상자영역만(seg, 라벨, 이웃, 상자):'''

content = content.replace("def _상자영역만(seg, 라벨, 이웃, 상자):", commented_code.strip())

with codecs.open("vision.py", "w", "utf-8") as f:
    f.write(content)

