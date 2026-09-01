# -*- coding: utf-8 -*-
"""모든 .kg를 한 개의 탐색 가능한 HTML로 만든다. 표준 라이브러리만 쓴다."""
import html, json, os, sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.insert(0, root_dir)
from engine import kg읽기, _포함, _관련개념


def load_graph(path):
    """엔진이 실제로 쓰는 모양으로 만든다. load() 에서 벡터 계산만 뺀 것이다.

    kg읽기만 쓰면 두 군데가 어긋난다.
      - 사건 .kg 는 `포함:` 으로 법리를 빌려오는데 안 풀려서 공통층이 0이 된다.
        (cases/사건_대표이사어깨흔듦: 노드 16/엣지 26 으로 보이지만 실제는 44/53)
      - graph.kg 는 절도·사기·명예훼손 같은 다른 죄명이 남는다. 엔진은
        _관련개념으로 걸러 무관층에 넣는데, 화면에는 목표와 안 이어진
        조각 그래프로 흩뿌려져 배치를 통째로 망가뜨린다.
    벡터가 필요 없으므로 모델을 올리지 않는다."""
    graph = kg읽기(path)
    _포함(graph, os.path.dirname(os.path.abspath(path)))
    relevant_concepts = _관련개념(graph)
    graph.setdefault("무관층", {}).update(
        {"_타죄명:" + key: value for key, value in graph["공통층"].items() if key not in relevant_concepts})
    graph["공통층"] = relevant_concepts
    included_nodes = set(graph["공통층"]) | set(graph["사례층"])
    graph["엣지"] = [edge for edge in graph["엣지"] if edge[0] in included_nodes and edge[2] in included_nodes]
    return graph


def list_graphs():
    files = [os.path.join(root_dir, "graphs", filename) for filename in os.listdir(os.path.join(root_dir, "graphs"))
            if filename.endswith(".kg") and "템플릿" not in filename]
    cases_dir = os.path.join(root_dir, "cases")
    files += [os.path.join(cases_dir, filename) for filename in os.listdir(cases_dir)
             if filename.startswith("사건_") and filename.endswith(".kg")]
    out = {}
    for path in sorted(files):
        graph = load_graph(path)
        nodes = []
        evidence_nodes = {source for source, relation, _ in graph["엣지"] if relation == "증명"}
        for layer in ("공통층", "사례층", "무관층"):
            for node, examples in graph[layer].items():
                node_type = "목표" if node == graph["목표"] else ("증거" if node in evidence_nodes else layer)
                nodes.append({"id": node, "type": node_type, "examples": examples[:3]})
        out[os.path.relpath(path, root_dir).replace("\\", "/")] = {
            "role": graph["역할"], "target": graph["목표"], "nodes": nodes,
            "edges": [{"source": source, "relation": relation, "target": target} for source, relation, target in graph["엣지"]]
        }
    return out


TEMPLATE = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Objection 지식 그래프</title>
<style>
:root{color-scheme:light dark;--bg:light-dark(#f8fafc,#111827);--fg:light-dark(#172033,#edf2f7);--muted:light-dark(#64748b,#9ca3af);--line:light-dark(#94a3b8,#64748b);--panel:light-dark(#ffffff,#1f2937);--border:light-dark(#dbe3ed,#374151);--blue:light-dark(#2563eb,#60a5fa);--green:light-dark(#059669,#34d399);--orange:light-dark(#d97706,#fbbf24);--red:light-dark(#dc2626,#f87171);--purple:light-dark(#7c3aed,#a78bfa)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}header{padding:20px 24px 12px}h1{font-size:20px;font-weight:500;margin:0 0 4px}p{margin:0;color:var(--muted)}.controls{display:flex;flex-wrap:wrap;gap:12px;padding:12px 24px}.controls label{display:grid;gap:4px;color:var(--muted)}select,input,button{font:inherit;color:var(--fg);background:var(--panel);border:1px solid var(--border);padding:7px 9px;border-radius:6px}button{align-self:end;cursor:pointer}button:hover{border-color:var(--fg)}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--blue);outline-offset:2px}.checks{display:flex;align-items:end;gap:10px;flex-wrap:wrap;padding-bottom:7px}.checks label{display:flex;align-items:center;gap:4px;color:var(--fg)}main{display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:16px;padding:0 24px 24px}.graph{height:680px;border:1px solid var(--border);background:var(--panel);border-radius:8px;overflow:hidden;position:relative;cursor:grab;touch-action:none}.graph svg{display:block;width:100%;height:100%}.graph.dragging{cursor:grabbing}.stats{position:absolute;left:12px;top:10px;color:var(--muted);pointer-events:none;z-index:1}.detail{border-left:1px solid var(--border);padding-left:16px}.detail h2{font-size:16px;font-weight:500;margin:0 0 10px}.detail dl{margin:0;display:grid;grid-template-columns:54px 1fr;gap:7px}.detail dt{color:var(--muted)}.detail dd{margin:0;overflow-wrap:anywhere}.detail ul{padding-left:18px}.legend{display:flex;gap:12px;flex-wrap:wrap;padding:0 24px 12px;color:var(--muted)}.legend span::before{content:"";display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--c);margin-right:5px}.node text{font-size:11px;fill:var(--fg);pointer-events:none}.node circle{stroke:var(--panel);stroke-width:2;cursor:grab}.node:active circle{cursor:grabbing}.node.dim,.edge.dim{opacity:.1}.node.selected circle{stroke:var(--fg);stroke-width:3}.edge{stroke:var(--line);stroke-width:1.2;opacity:.62;marker-end:url(#arrow)}.edge[data-r="부정"]{stroke:var(--red);stroke-dasharray:5 4}.edge[data-r="증명"]{stroke:var(--blue)}.edge.path{stroke-width:3;opacity:1}.empty{color:var(--muted);padding-top:20px}@media(max-width:760px){main{grid-template-columns:1fr}.graph{height:560px}.detail{border-left:0;border-top:1px solid var(--border);padding:14px 0 0}.controls,header,main,.legend{padding-left:14px;padding-right:14px}}
</style></head><body>
<header><h1>Objection 지식 그래프</h1><p>생성하지 않고, 근거 경로를 따라 결론에 도달하는 AI</p></header>
<div class="controls"><label>그래프<select id="dataset"></select></label><label>노드 찾기<input id="search" type="search" placeholder="예: 상당성"></label><label>노드 간격<input id="spacing" type="range" min="60" max="250" value="100"></label><div class="checks" aria-label="관계 필터"><label><input type="checkbox" value="증명" checked>증명</label><label><input type="checkbox" value="충족" checked>충족</label><label><input type="checkbox" value="부정" checked>부정</label></div><button id="reset" type="button">뷰 초기화</button></div>
<div class="legend"><span style="--c:var(--purple)">목표</span><span style="--c:var(--green)">공통 개념</span><span style="--c:var(--orange)">사례 사실</span><span style="--c:var(--blue)">증거</span></div>
<main><div class="graph" id="graph"><div class="stats" id="stats"></div><svg width="100%" height="100%" role="img" aria-label="지식 그래프"></svg></div><aside class="detail" id="detail"><h2>노드를 선택하세요</h2><p>휠로 노드 사이 간격을 벌리거나 좁히고, 빈 공간을 끌어 이동하고, 노드를 직접 배치할 수 있습니다. 노드를 누르면 목표까지의 최단 근거 경로를 표시합니다.</p></aside></main>
<script>
const DATA=__DATA__;
const sel=document.querySelector('#dataset'),svg=document.querySelector('svg'),box=document.querySelector('#graph'),detail=document.querySelector('#detail'),search=document.querySelector('#search');
Object.keys(DATA).forEach(k=>sel.add(new Option(k,k))); sel.value=Object.keys(DATA).find(k=>k==='graphs/graph.kg')||Object.keys(DATA)[0];
let state={},raf,view={x:0,y:0,spread:1},gesture=null;
const color=t=>({목표:'var(--purple)',증거:'var(--blue)',공통층:'var(--green)',사례층:'var(--orange)',무관층:'var(--muted)'})[t]||'var(--muted)';
// 근거 경로는 전진 관계(증명/충족)만 탄다. 엔진의 reachable 과 같은 규칙이다.
// 부정까지 타면 '침해의종료 -부정-> 침해의현재성 -충족-> 정당방위' 가 정당방위의
// 근거처럼 표시된다 — 뜻이 정반대다. 실제로 44개 노드 중 19개가 그랬다.
const 전진=new Set(['증명','충족']);
function shortest(start,target,edges){const q=[start],prev=new Map([[start,null]]),pe=new Map; while(q.length){const n=q.shift();if(n===target)break;for(const [i,e] of edges.entries()){if(전진.has(e.relation)&&e.source===n&&!prev.has(e.target)){prev.set(e.target,n);pe.set(e.target,i);q.push(e.target)}}}if(!prev.has(target))return[];const out=[];for(let n=target;prev.get(n)!==null;n=prev.get(n))out.push(pe.get(n));return out}
// 목표로 가는 전진 경로가 없다면, 목표에 닿는 무언가를 부정하는 노드인지 본다.
function 깨는것(id,target,edges){const 닿음=new Set([target]);let 늘었나=true;
 while(늘었나){늘었나=false;for(const e of edges)if(전진.has(e.relation)&&닿음.has(e.target)&&!닿음.has(e.source)){닿음.add(e.source);늘었나=true}}
 return edges.filter(e=>e.relation==='부정'&&e.source===id&&닿음.has(e.target)).map(e=>e.target)}
function render(){cancelAnimationFrame(raf);const g=DATA[sel.value],active=new Set([...document.querySelectorAll('.checks input:checked')].map(x=>x.value));const edges=g.edges.filter(e=>active.has(e.relation));const ids=new Set(edges.flatMap(e=>[e.source,e.target]));let nodes=g.nodes.filter(n=>ids.has(n.id)||n.id===g.target).map(n=>({...n,x:0,y:0,vx:0,vy:0,fixed:false}));const map=new Map(nodes.map(n=>[n.id,n]));const E=edges.filter(e=>map.has(e.source)&&map.has(e.target)).map(e=>({...e,a:map.get(e.source),b:map.get(e.target)}));svg.innerHTML='<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="context-stroke"/></marker></defs>';const w=box.clientWidth,h=box.clientHeight,ns='http://www.w3.org/2000/svg',scene=document.createElementNS(ns,'g');scene.id='viewport';svg.append(scene);nodes.forEach((n,i)=>{const a=2*Math.PI*i/nodes.length;n.x=w/2+Math.cos(a)*Math.min(w,h)*.34;n.y=h/2+Math.sin(a)*Math.min(w,h)*.34});const lines=E.map(e=>{const x=document.createElementNS(ns,'line');x.classList.add('edge');x.dataset.r=e.relation;scene.append(x);return x});const groups=nodes.map(n=>{const x=document.createElementNS(ns,'g');x.classList.add('node');x.dataset.id=n.id;const c=document.createElementNS(ns,'circle');c.setAttribute('r',n.type==='목표'?10:7);c.setAttribute('fill',color(n.type));const t=document.createElementNS(ns,'text');t.setAttribute('x',12);t.setAttribute('y',4);t.textContent=n.id;x.append(c,t);x.addEventListener('pointerdown',e=>startNodeDrag(e,n,x,E,groups,lines,g));scene.append(x);return x});view={x:0,y:0,spread:1};document.querySelector('#spacing').value=100;state={nodes,E,groups,lines,w,h,g,scene};applyView();tick(260);filter()}
// Fruchterman-Reingold. 앞의 구현은 반발력 600/d^2 가 감쇠를 이겨 노드 81개에서
// 좌표가 1e114 까지 발산하다 NaN 이 됐다(화면이 통째로 비었다). 여기서는 한 스텝
// 이동량을 온도로 잘라 발산 자체가 불가능하다. 중력은 분리된 조각들이 무한히
// 멀어지는 것을 막는다 — .kg 에는 목표와 안 이어진 짝이 흔하다.
function tick(left,total){const {nodes,E,w,h}=state;if(!nodes.length)return;total=total||left;
const k=Math.sqrt(w*h/nodes.length),t=Math.max(w,h)/10*Math.max(left/total,.01);
nodes.forEach(n=>{n.dx=0;n.dy=0});
for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=nodes[i],b=nodes[j];
 let dx=a.x-b.x,dy=a.y-b.y,d=Math.hypot(dx,dy);
 if(d<.01){dx=Math.random()-.5;dy=Math.random()-.5;d=.01}
 const f=k*k/(d*d);a.dx+=dx*f;a.dy+=dy*f;b.dx-=dx*f;b.dy-=dy*f}
E.forEach(e=>{let dx=e.b.x-e.a.x,dy=e.b.y-e.a.y,d=Math.hypot(dx,dy)||.01,f=d/k;
 e.a.dx+=dx*f;e.a.dy+=dy*f;e.b.dx-=dx*f;e.b.dy-=dy*f});
nodes.forEach(n=>{n.dx+=(w/2-n.x)*.03;n.dy+=(h/2-n.y)*.03});
nodes.forEach(n=>{if(n.fixed)return;const d=Math.hypot(n.dx,n.dy)||1,m=Math.min(d,t);n.x+=n.dx/d*m;n.y+=n.dy/d*m});
draw();if(left>1){raf=requestAnimationFrame(()=>tick(left-1,total))}else{fit()}}
// 배치가 끝나면 화면에 맞춘다. 힘 상수를 그래프마다 맞출 필요가 없어진다.
function fit(){const{nodes,w,h}=state;if(!nodes.length)return;
const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y);
const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
const s=Math.max(.05,Math.min(2,Math.min((w-110)/Math.max(x1-x0,1),(h-50)/Math.max(y1-y0,1))));
const cx=(x0+x1)/2,cy=(y0+y1)/2;
nodes.forEach(n=>{n.x=w/2+(n.x-cx)*s;n.y=h/2+(n.y-cy)*s});draw()}
function draw(){const{E,groups,lines,nodes}=state;lines.forEach((l,i)=>{const e=E[i],dx=e.b.x-e.a.x,dy=e.b.y-e.a.y,d=Math.hypot(dx,dy)||1;l.setAttribute('x1',e.a.x);l.setAttribute('y1',e.a.y);l.setAttribute('x2',e.b.x-dx*10/d);l.setAttribute('y2',e.b.y-dy*10/d)});groups.forEach((x,i)=>x.setAttribute('transform',`translate(${nodes[i].x} ${nodes[i].y})`))}
function applyView(){state.scene?.setAttribute('transform',`translate(${view.x} ${view.y})`);if(state.g)document.querySelector('#stats').textContent=`${state.g.role} · 목표 ${state.g.target} · 노드 ${state.nodes.length} · 엣지 ${state.E.length} · 간격 ${Math.round(view.spread*100)}%`}
function point(e){const r=svg.getBoundingClientRect();return{x:e.clientX-r.left-view.x,y:e.clientY-r.top-view.y}}
function startNodeDrag(e,n,el,E,groups,lines,g){e.stopPropagation();el.setPointerCapture(e.pointerId);const start={x:e.clientX,y:e.clientY};gesture={kind:'node',n,moved:false};n.fixed=true;n.vx=n.vy=0;const move=ev=>{const p=point(ev);n.x=p.x;n.y=p.y;gesture.moved ||= Math.hypot(ev.clientX-start.x,ev.clientY-start.y)>3;draw()};const up=ev=>{el.releasePointerCapture(ev.pointerId);el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',up);if(!gesture.moved)selectNode(n,E,groups,lines,g);gesture=null};el.addEventListener('pointermove',move);el.addEventListener('pointerup',up)}
function selectNode(n,E,groups,lines,g){groups.forEach(x=>x.classList.toggle('selected',x.dataset.id===n.id));lines.forEach(x=>x.classList.remove('path'));
const idx=shortest(n.id,g.target,E);idx.forEach(i=>lines[i]?.classList.add('path'));
let 역할;
if(n.id===g.target)역할='<p>이 재판의 결론입니다.</p>';
else if(idx.length)역할='<p><b>'+idx.length+'홉</b>으로 '+escapeHtml(g.target)+'에 닿습니다.</p><ul>'+idx.slice().reverse().map(i=>`<li>${escapeHtml(E[i].source)} <b>${E[i].relation}</b> ${escapeHtml(E[i].target)}</li>`).join('')+'</ul>';
else{const 깸=깨는것(n.id,g.target,E);
 역할=깸.length?'<p>목표로 가는 근거 경로가 없습니다. 이 노드는 <b>'+깸.map(escapeHtml).join(', ')+'</b>을(를) <b>부정</b>합니다 — 결론을 무너뜨리는 쪽입니다.</p>'
                :'<p class="empty">목표로 가는 근거 경로가 없습니다.</p>'}
detail.innerHTML=`<h2>${escapeHtml(n.id)}</h2><dl><dt>종류</dt><dd>${n.type}</dd><dt>목표</dt><dd>${escapeHtml(g.target)}</dd></dl><h2>근거 경로</h2>${역할}<h2>말 예시</h2>${n.examples.length?'<ul>'+n.examples.map(x=>`<li>${escapeHtml(x)}</li>`).join('')+'</ul>':'<p class="empty">예시 없음</p>'}`}
function escapeHtml(s){const x=document.createElement('span');x.textContent=s;return x.innerHTML}function filter(){const q=search.value.trim().toLowerCase();state.groups?.forEach(x=>x.classList.toggle('dim',q&&!x.dataset.id.toLowerCase().includes(q)))}
function setSpread(next){next=Math.max(.6,Math.min(2.5,next));if(next===view.spread)return;cancelAnimationFrame(raf);const ratio=next/view.spread,anchor=state.nodes.find(n=>n.id===state.g.target)||state.nodes[0];state.nodes.forEach(n=>{n.x=anchor.x+(n.x-anchor.x)*ratio;n.y=anchor.y+(n.y-anchor.y)*ratio;n.vx=n.vy=0;n.fixed=true});view.spread=next;view.x=state.w/2-anchor.x;view.y=state.h/2-anchor.y;document.querySelector('#spacing').value=Math.round(next*100);draw();applyView()}
svg.addEventListener('wheel',e=>{e.preventDefault();setSpread(view.spread*Math.exp(-e.deltaY*.0015))},{passive:false});
svg.addEventListener('pointerdown',e=>{if(e.target.closest?.('.node'))return;svg.setPointerCapture(e.pointerId);gesture={kind:'pan',x:e.clientX,y:e.clientY,vx:view.x,vy:view.y};box.classList.add('dragging')});
svg.addEventListener('pointermove',e=>{if(gesture?.kind!=='pan')return;view.x=gesture.vx+e.clientX-gesture.x;view.y=gesture.vy+e.clientY-gesture.y;applyView()});
svg.addEventListener('pointerup',e=>{if(gesture?.kind!=='pan')return;svg.releasePointerCapture(e.pointerId);gesture=null;box.classList.remove('dragging')});
document.querySelector('#reset').addEventListener('click',render);
document.querySelector('#spacing').addEventListener('input',e=>setSpread(Number(e.target.value)/100));
sel.addEventListener('change',render);search.addEventListener('input',filter);document.querySelectorAll('.checks input').forEach(x=>x.addEventListener('change',render));
// 레이아웃 전에는 box.clientWidth 가 14 로 나온다. 그 폭으로 배치하면 노드가
// 한 점에 뭉쳐 힘이 폭발한다. 크기가 잡힌 뒤 그리고, 창이 바뀌면 다시 맞춘다.
let 첫번째=true;
new ResizeObserver(()=>{const w=box.clientWidth,h=box.clientHeight;if(w<80||h<80)return;
 if(첫번째){첫번째=false;render()}else if(state.nodes){state.w=w;state.h=h;fit()}}).observe(box);
</script></body></html>'''


if __name__ == "__main__":
    out = os.path.join(current_dir, "지식그래프.html")
    data = json.dumps(list_graphs(), ensure_ascii=False, separators=(",", ":"))
    open(out, "w", encoding="utf-8").write(TEMPLATE.replace("__DATA__", data))
    print("Visualization generated.")
