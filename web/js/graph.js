// 灯笼知识库 · graph —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 知识关联（wiki 内容驱动图谱） ----------------
   边来自正文 [[...]] 硬链 + 关键词共现软链，与 band/domain 解耦；
   band 只作「透镜」着色 / 过滤器，不再决定图的结构（结构交给力导）。
*/
const _BAND_PALETTE = ['#B5302A','#C98A2B','#2F6B66','#3A5A8C','#8B5A2B','#7A4E8C','#2E7D6E','#B0651F','#4E6E8C','#A06A3C'];
function bandColor(name){
  let h = 0;
  for(const ch of (name||'')) h = (h*31 + ch.codePointAt(0)) >>> 0;
  return _BAND_PALETTE[h % _BAND_PALETTE.length];
}
function toast(msg){
  let t=document.getElementById('gToast');
  if(!t){ t=document.createElement('div'); t.id='gToast';
    t.style.cssText='position:fixed;left:50%;bottom:32px;transform:translateX(-50%);'
      +'background:rgba(26,26,26,.92);color:#fff;padding:9px 16px;border-radius:8px;font-size:13px;'
      +'z-index:9999;box-shadow:0 6px 20px rgba(26,26,26,.28);opacity:0;transition:opacity .2s;';
    document.body.appendChild(t); }
  t.textContent=msg; t.style.opacity='1';
  clearTimeout(t._tm); t._tm=setTimeout(()=>{ t.style.opacity='0'; }, 2400);
}
let GV = null;
function nodeRadius(n){
  const d = Math.max(0, (n.degree||0));
  return Math.min(19, 6 + Math.sqrt(d) * 2.0);   // 节点大小 = 连接数（度）
}
function graphBuildData(data){
  const keepSel = GV ? GV.selectedNode : null;
  const keepEdge = GV ? GV.selectedEdge : null;
  const prev = GV ? GV.nodes : {};
  const nodes = {};
  (data.nodes||[]).forEach(it=>{
    const id = it.id;
    // 图谱只含文章节点（type 恒为 item）+ 虚节点；概念不进图谱（退化为后端桥接中间件）
    const n = prev[id] || {id, type:'item', x:0, y:0, vx:0, vy:0, fixed:false};
    n.type = 'item';
    n.label=it.title; n.band=it.band; n.axis_domain=it.axis_domain;
    n.tags=it.tags||[]; n.degree=it.degree||0; n.inDegree=it.inDegree||0; n.outDegree=it.outDegree||0;
    nodes[id]=n;
  });
  // 虚节点：正文 [[目标]] 但库里没有这篇 —— 知识网络的可生长性
  (data.unresolved||[]).forEach(u=>{
    const vid='v:'+u.target;
    if(!nodes[vid]){
      const n = prev[vid] || {id:vid, type:'virtual', x:0, y:0, vx:0, vy:0, fixed:false};
      n.type='virtual'; n.label=u.target; n.band=null; n.degree=0; n.inDegree=0; n.outDegree=0; n.srcTitle=u.src_title;
      nodes[vid]=n;
    }
  });
  const edges=[];
  (data.edges||[]).forEach(e=>{
    const src = e.source, dst = (e.target!=null && nodes['v:'+e.target]) ? 'v:'+e.target : e.target;
    const id = (e.kind==='hard'?'h:':'s:') + src + '-' + dst;
    edges.push({id, source:src, target:dst, kind:e.kind, confirmed:!!e.confirmed,
                 provenance:e.provenance||(e.kind==='hard'?'author':'cooccur'),
                 evidence:e.evidence||[], stale:false});
  });
  // 虚节点边（unresolved：源条目 → 虚节点）
  (data.unresolved||[]).forEach(u=>{ edges.push({id:'u:'+u.src_id+'-'+u.target, source:u.src_id, target:'v:'+u.target, kind:'unresolved', confirmed:false, evidence:[], stale:false}); });
  // 初始位置（确定性铺开，力导再收敛；保留旧坐标避免每次跳动）
  const ids=Object.keys(nodes);
  ids.forEach((id,i)=>{
    const n=nodes[id];
    if(prev[id]){ n.x=prev[id].x; n.y=prev[id].y; n.vx=prev[id].vx; n.vy=prev[id].vy; }
    else { const ang=i/Math.max(1,ids.length)*Math.PI*2; n.x=480+Math.cos(ang)*190; n.y=295+Math.sin(ang)*150; }
  });
  GV = GV || {};
  GV.nodes=nodes; GV.edges=edges;
  GV.lens = GV.lens || {band:null, unconfirmed:false};
  GV.selectedNode = (keepSel && nodes[keepSel]) ? keepSel : null;
  GV.selectedEdge = (keepEdge && edges.some(e=>e.id===keepEdge)) ? keepEdge : null;
  GV.layout = GV.layout || {tx:24, ty:14, k:1};
  if(GV.insetLeft===undefined) GV.insetLeft=0;
  GV.alpha=0; GV.drag=null; GV.raf=null;
  if(GV.bound===undefined) GV.bound=false;
}
function graphTick(){
  const ns=Object.values(GV.nodes);
  for(let i=0;i<ns.length;i++) for(let j=i+1;j<ns.length;j++){
    const a=ns[i],b=ns[j]; let dx=a.x-b.x, dy=a.y-b.y; let d2=dx*dx+dy*dy||0.01; let d=Math.sqrt(d2);
    const f=22000/d2, fx=dx/d*f, fy=dy/d*f;
    if(!a.fixed){a.vx+=fx; a.vy+=fy;} if(!b.fixed){b.vx-=fx; b.vy-=fy;}
  }
  GV.edges.forEach(ed=>{
    const a=GV.nodes[ed.source], b=GV.nodes[ed.target]; if(!a||!b) return;
    let dx=b.x-a.x, dy=b.y-a.y; let d=Math.sqrt(dx*dx+dy*dy)||0.01;
    const L = ed.kind==='hard'?150:(ed.kind==='soft'?175:110);
    const fs=0.03*(d-L), fx=dx/d*fs, fy=dy/d*fs;
    if(!a.fixed){a.vx+=fx; a.vy+=fy;} if(!b.fixed){b.vx-=fx; b.vy-=fy;}
  });
  ns.forEach(n=>{ if(n.type==='item'){ n.vx+=(480-n.x)*0.0006; n.vy+=(295-n.y)*0.0006; } });
  ns.forEach(n=>{ if(n.fixed){n.vx=0;n.vy=0;return;}
    n.vx*=0.85; n.vy*=0.85; n.x+=n.vx*GV.alpha; n.y+=n.vy*GV.alpha;
    n.x=Math.max(20,Math.min(960,n.x)); n.y=Math.max(40,Math.min(540,n.y)); });
  for(let pass=0; pass<3; pass++){
    for(let i=0;i<ns.length;i++) for(let j=i+1;j<ns.length;j++){
      const a=ns[i],b=ns[j];
      const min=nodeRadius(a)+nodeRadius(b)+8;
      let dx=b.x-a.x, dy=b.y-a.y; let d=Math.hypot(dx,dy)||0.01;
      if(d<min){ const push=(min-d)/2, ux=dx/d, uy=dy/d;
        if(!a.fixed){a.x-=ux*push; a.y-=uy*push;}
        if(!b.fixed){b.x+=ux*push; b.y+=uy*push;}
        a.x=Math.max(20,Math.min(960,a.x)); a.y=Math.max(40,Math.min(540,a.y));
        b.x=Math.max(20,Math.min(960,b.x)); b.y=Math.max(40,Math.min(540,b.y));
      }
    }
  }
}
function graphStart(){
  if(GV.raf) return;
  const step=()=>{ if(GV.alpha>0.012){ graphTick(); GV.alpha*=0.992; graphPaint(); GV.raf=requestAnimationFrame(step);} else { GV.raf=null; graphPaint(); } };
  GV.raf=requestAnimationFrame(step);
}
function graphReheat(a){ GV.alpha=Math.max(GV.alpha,a||0.6); graphStart(); }
function graphSettle(steps){ for(let i=0;i<steps;i++) graphTick(); }
function neighborSet(id){
  const s=new Set([id]);
  GV.edges.forEach(e=>{ if(e.source===id) s.add(e.target); if(e.target===id) s.add(e.source); });
  return s;
}
function graphPaint(){
  const svg=$('gSvg'); if(!svg) return;
  const L=GV.layout;
  const sel=GV.selectedNode; const nb=sel?neighborSet(sel):null;
  const edgeSel = GV.selectedEdge;
  const nodeDim=(n)=>{
    if(sel && !nb.has(n.id)) return true;
    if(GV.lens.band && n.type==='item' && n.band!==GV.lens.band) return true;
    return false;
  };
  const edgeDim=(ed)=>{
    // 借鉴工作台：默认（未选中任何节点）连线全部隐藏，只铺节点 —— 先见全貌，点节点才展开关联
    if(!sel) return true;
    // 选中节点后：只显示与该节点直接相连的入射边，其余藏起
    if(!(ed.source===sel || ed.target===sel)) return true;
    // 领域透镜可进一步过滤
    if(GV.lens.band){ const a=GV.nodes[ed.source],b=GV.nodes[ed.target]; if(!a||!b)return true;
      if(a.type==='item'&&a.band!==GV.lens.band)return true;
      if(b.type==='item'&&b.band!==GV.lens.band)return true; }
    return false;
  };
  let s=`<g transform="translate(${L.tx.toFixed(1)},${L.ty.toFixed(1)}) scale(${L.k.toFixed(3)})">`;
  GV.edges.forEach(ed=>{
    const a=GV.nodes[ed.source], b=GV.nodes[ed.target]; if(!a||!b) return;
    if(edgeDim(ed)) return;   // 默认隐藏连线；仅选中节点的入射边展开显示
    let col='#CFC6B2', w=2, dash='';
    if(ed.kind==='hard'){ col='#3A5A8C'; w=2; }                       // 作者互链（蓝实线）
    else if(ed.kind==='soft'){
      if(ed.provenance==='bridge'){ col='#B5482F'; w=2; dash='stroke-dasharray="7 5"'; }  // 引擎桥接（朱砂虚线，跨主题）
      else if(ed.provenance==='semantic'){ col='#9a968c'; w=1.6; dash='stroke-dasharray="2 4"'; }  // 引擎推测·存疑（灰细点线，嵌入暂不可信）
      else { col='#2f6b34'; w=2; }                  // 引擎发现（绿实线，共现自动接入）
    }
    else { col='#bdb6a6'; w=1.6; dash='stroke-dasharray="3 4"'; }     // 待补写（灰虚线）
    const selEd = edgeSel && edgeSel===ed.id; if(selEd) w+=2.2;
    const mx=(a.x+b.x)/2, my=(a.y+b.y)/2;
    s+=`<line data-edge="${ed.id}" x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${col}" stroke-width="${w}" ${dash} vector-effect="non-scaling-stroke" style="cursor:pointer"/>`;
    if(ed.kind==='soft' && selEd && ed.evidence.length){
      s+=`<text x="${mx.toFixed(1)}" y="${(my-5).toFixed(1)}" font-size="10" fill="${col}" text-anchor="middle" style="pointer-events:none;">${esc(ed.evidence.slice(0,3).join('·'))}</text>`;
    }
  });
  Object.values(GV.nodes).forEach(n=>{
    const dim=nodeDim(n) ? 'opacity="0.22"' : '';
    const r=nodeRadius(n);
    if(n.type==='virtual'){
      s+=`<g data-node="${n.id}" style="cursor:pointer" ${dim}>
        <circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${r.toFixed(1)}" fill="#fff" stroke="#bdb6a6" stroke-width="1.6" stroke-dasharray="3 3"/>
        <text x="${n.x.toFixed(1)}" y="${(n.y+r+12).toFixed(1)}" font-size="10.5" fill="#8a8275" text-anchor="middle" style="pointer-events:none;">${esc((n.label||'').slice(0,8))}?</text></g>`;
      return;
    }
    const c=bandColor(n.band); const on=GV.selectedNode===n.id;
    s+=`<g data-node="${n.id}" style="cursor:pointer" ${dim}>
      ${on?`<circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${(r+6).toFixed(1)}" fill="none" stroke="#23201C" stroke-width="2" opacity=".75"/>`:''}
      <circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${r.toFixed(1)}" fill="${c}"/>
      <text x="${n.x.toFixed(1)}" y="${(n.y+r+13).toFixed(1)}" font-size="11" ${on?'font-weight="700"':''} fill="#3A352C" text-anchor="middle" style="pointer-events:none;">${esc((n.label||'').slice(0,9))}</text></g>`;
  });
  s+='</g>';
  svg.innerHTML=s;
}
function graphBind(){
  const cv=$('gCanvas'); if(!cv||GV.bound) return; GV.bound=true;
  const svg=$('gSvg');
  const rect=()=>svg.getBoundingClientRect();
  const toWorld=(cx,cy)=>{ const r=rect(), L=GV.layout; return {x:(cx-r.left-L.tx)/L.k, y:(cy-r.top-L.ty)/L.k}; };
  const nodeAt=(wx,wy)=>{ let best=null,bd=1e9; Object.values(GV.nodes).forEach(n=>{ const rr=nodeRadius(n); const d=Math.hypot(n.x-wx,n.y-wy); if(d<rr+5 && d<bd){bd=d;best=n;} }); return best; };
  let panning=false, panStart=null, panMoved=false;
  // 检查器 UI 是画布上的浮层，点击它不应被当成「画布空白」（否则会误触发平移/清选）
  const _onOverlay = e => !!(e.target && e.target.closest && e.target.closest('#gInspector'));
  cv.addEventListener('pointerdown',e=>{
    if(_onOverlay(e)) return;
    const w=toWorld(e.clientX,e.clientY), n=nodeAt(w.x,w.y);
    if(n){ GV.drag={node:n,moved:false,sx:e.clientX,sy:e.clientY,wasFixed:n.fixed}; n.fixed=true; try{cv.setPointerCapture(e.pointerId);}catch(_){} }
    else { panning=true; panMoved=false; panStart={x:e.clientX,y:e.clientY,tx:GV.layout.tx,ty:GV.layout.ty}; }
  });
  cv.addEventListener('pointermove',e=>{
    if(_onOverlay(e)){ const t=$('gTip'); if(t) t.classList.add('hidden'); return; }
    if(GV.drag){
      if(Math.hypot(e.clientX-GV.drag.sx, e.clientY-GV.drag.sy) < 5) return;
      const w=toWorld(e.clientX,e.clientY); GV.drag.node.x=Math.max(20,Math.min(960,w.x)); GV.drag.node.y=Math.max(40,Math.min(540,w.y)); GV.drag.moved=true; graphReheat(0.22);
    } else if(panning){ panMoved=true; GV.layout.tx=panStart.tx+(e.clientX-panStart.x); GV.layout.ty=panStart.ty+(e.clientY-panStart.y); graphPaint(); }
    else { const w=toWorld(e.clientX,e.clientY), n=nodeAt(w.x,w.y), tip=$('gTip'), r=rect();
      if(n){ tip.classList.remove('hidden'); tip.style.left=(e.clientX-r.left)+'px'; tip.style.top=(e.clientY-r.top)+'px';
        tip.innerHTML = n.type==='virtual'
          ? `<b>${esc(n.label)}?</b><br>提到了但还没写的文章`
          : `<b>${esc(n.label)}</b><br>领域：${esc(n.band||'—')} · 连接 ${n.degree}${n.inDegree?'（入 '+n.inDegree+' · 出 '+n.outDegree+'）':''}`; }
      else tip.classList.add('hidden');
    }
  });
  cv.addEventListener('pointerup',e=>{
    if(_onOverlay(e)) return;
    if(GV.drag){ const n=GV.drag.node, click=!GV.drag.moved; n.fixed=false; GV.drag=null;
      if(click){ graphSelectNode(n.id); return; } }
    // 点空白处（未拖动平移）= 恢复全显示，清掉节点/连线聚焦锁定
    if(panning && !panMoved && (GV.selectedNode||GV.selectedEdge)) graphClearSelection();
    panning=false; panMoved=false; graphPaint();
  });
  cv.addEventListener('pointerleave',()=>{ const t=$('gTip'); if(t) t.classList.add('hidden'); });
  cv.addEventListener('wheel',e=>{ e.preventDefault(); const r=rect(), L=GV.layout, mx=e.clientX-r.left, my=e.clientY-r.top, f=e.deltaY<0?1.12:0.89, nk=Math.max(0.4,Math.min(2.6,L.k*f)); L.tx=mx-(mx-L.tx)*(nk/L.k); L.ty=my-(my-L.ty)*(nk/L.k); L.k=nk; graphPaint(); },{passive:false});
  svg.addEventListener('click',e=>{ const ln=e.target.closest('[data-edge]'); if(ln){ const id=ln.getAttribute('data-edge'); if(id) graphSelectEdge(id); } });
  // 双击节点 → 直接跳转到对应内容阅读页（工作台：onDoubleClick → onActivate）
  svg.addEventListener('dblclick',e=>{
    const w=toWorld(e.clientX,e.clientY), n=nodeAt(w.x,w.y);
    if(n && n.type==='item'){ openReader(n.id); }
  });
  const ci=$('gInspectorClose'); if(ci) ci.onclick=()=>graphClearSelection();
}
function fmtMD(ts){
  if(!ts) return '';
  const d=new Date(ts*1000), p=n=>String(n).padStart(2,'0');
  return p(d.getMonth()+1)+'-'+p(d.getDate());
}
async function graphSelectNode(id){
  GV.selectedEdge=null; GV.selectedNode=id;
  const n=GV.nodes[id]; if(!n) return;
  if(n.type==='virtual'){
    $('gDetail').innerHTML = `<div class="det-title">虚节点 · 提到了但还没写</div>
      <div class="det-row">「${esc(n.label)}」在 <b>${esc(n.srcTitle||'')}</b> 里被引用，但库里还没有这篇。</div>
      <div class="det-row muted">这是知识网络的可生长点——可以立刻为它建一篇草稿，连线会自动接上。</div>
      <div class="det-actions"><button class="soft" id="gDraft" style="background:#7A4E8C;color:#fff;">创建这篇草稿</button></div>`;
    const db=$('gDraft'); if(db) db.onclick=async()=>{
      db.disabled=true; db.textContent='创建中';
      try{
        const r=await api('/api/kb/create_draft',{title:n.label});
        if(r&&r.ok){ toast('已创建草稿，连线已接上'); await renderGraph(); }
        else toast(r&&r.msg?r.msg:'创建失败');
      }catch(e){ toast('创建失败');     } finally { db.disabled=false; db.textContent='创建这篇草稿'; }
    };
    graphOpenInspector(); return;
  }
  const inc=GV.edges.filter(e=>e.source===id||e.target===id);
  const neighbors=inc.map(e=>{
    const other=e.source===id?e.target:e.source; const n2=GV.nodes[other];
    const dir = e.source===id ? '出链' : '入链';
    return {other, n2, dir, e};
  }).filter(x=>x.n2);
  const detail = (S.items||[]).find(i=>i.id===id);
  const summary = detail&&detail.summary?detail.summary:'';
  const tags=(n.tags||[]).map(t=>`<span class="tag">#${esc(t)}</span>`).join('');
  const cAt = (detail&&detail.created_at) ? fmtMD(detail.created_at) : '';
  let html = `<div class="det-eyebrow">`
    + (n.band?`<span>${esc(n.band)}</span>`:'')
    + (n.axis_domain?`<span>${esc(n.axis_domain)}</span>`:'')
    + (cAt?`<span>${cAt} 创建</span>`:'')
    + (detail&&detail.collision?``:'')
    + `</div>`
    + `<div class="det-title">${esc(n.label)}</div>`
    + (summary?`<div class="det-row det-summary">${esc(summary)}</div>`:'')
    + (tags?`<div class="det-tags">${tags}</div>`:'')
    + `<div class="det-stats">`
    +   `<div><b>${n.degree}</b><span>连接</span></div>`
    +   `<div><b>${n.outDegree}</b><span>出链</span></div>`
    +   `<div><b>${n.inDegree}</b><span>入链</span></div>`
    + `</div>`
    + `<div class="det-actions"><button class="soft" id="gOpen">打开阅读</button></div>`;
  if(neighbors.length){
    html += `<div class="det-sub"><span class="mono">LOCAL GRAPH</span><strong>相邻知识</strong><b class="mono det-count">${neighbors.length}</b></div>` + neighbors.map(x=>{
      const ev=(x.e.kind==='soft'&&x.e.evidence&&x.e.evidence.length)?` · ${(x.e.provenance==='semantic'?'推测·存疑':'共现')}：${x.e.evidence.map(esc).join('、')}`:'';
      let tag, cls='';
      if(x.e.kind==='hard'){ tag='互链（你写的）'; }
      else if(x.e.provenance==='semantic'){ tag='引擎推测·存疑'; cls='col'; }
      else if(x.e.provenance==='bridge'){ tag='桥接（跨主题）'; cls='col'; }
      else { tag='关键词共现'; cls='col'; }
      // 方向词（出链/入链）只对硬链有意义；软链是对称关联，硬加方向会误导「谁引用谁」
      const dirTag = x.e.kind==='hard' ? `${x.dir} ` : '';
      return `<div class="det-row" style="cursor:pointer;" data-gn="${x.other}">· <span class="tag ${cls}">${dirTag}${esc(tag)}</span> ${esc(x.n2.label)}${ev}</div>`;
    }).join('');
  }
  // 概念桥接推荐占位：后端中间件（concepts/concept_links 被动列表）只作桥接依据，不画成图边
  html += '<div id="gConceptRec" class="det-row muted">概念桥接推荐加载中…</div>';
  $('gDetail').innerHTML=html;
  $('gDetail').querySelectorAll('[data-gn]').forEach(d=>d.onclick=()=>openReader(Number(d.dataset.gn)));
  const op=$('gOpen'); if(op) op.onclick=()=>openReader(id);
  graphOpenInspector();
  // 异步拉取概念桥接推荐，填进占位块；共享概念即「桥接依据」，点击跳阅读页
  (async()=>{
    try{
      const r = await api('/api/kb/concept_neighbors?id='+id);
      const recs = (r&&r.neighbors)||[];
      const box = $('gConceptRec');
      if(!box) return;
      if(!recs.length){ box.outerHTML=''; return; }
      let h = `<div class="det-sub"><span class="mono">CONCEPT BRIDGE</span><strong>相关文档 · 概念桥接</strong><b class="mono det-count">${recs.length}</b></div>`
        + recs.map(x=>`<div class="det-row" style="cursor:pointer;" data-cn="${x.item_id}" title="共享概念：${esc(x.shared_concepts.join('、'))}">· ${esc(x.title)} <span class="tag col">共享：${esc(x.shared_concepts.join('、'))}</span></div>`).join('');
      box.outerHTML = h;
      $('gDetail').querySelectorAll('[data-cn]').forEach(d=>d.onclick=()=>openReader(Number(d.dataset.cn)));
    }catch(e){ const box=$('gConceptRec'); if(box) box.outerHTML=''; }
  })();
}
// 把某个节点平移到画布中心（搜索结果点选后，让目标节点进入视野）
function graphCenterOn(id){
  const n = GV.nodes[id]; if(!n) return;
  const svg = $('gSvg'); if(!svg) return;
  const r = svg.getBoundingClientRect();
  const L = GV.layout;
  const inset = GV.insetLeft||0;
  L.tx = inset + (r.width - inset)/2 - n.x * L.k;
  L.ty = r.height/2 - n.y * L.k;
  graphPaint();
}
function graphSelectEdge(id){
  GV.selectedNode=null; GV.selectedEdge=id;
  const ed=GV.edges.find(e=>e.id===id); if(!ed) return;
  const a=GV.nodes[ed.source], b=GV.nodes[ed.target];
  // B · 双来源叙事：明确这条边是「作者意图」还是「引擎发现」，以及引擎用的哪种信号
  let srcTxt, tag;
  if(ed.kind==='hard'){ srcTxt='作者互链（正文 [[...]] 显式引用）'; tag='作者意图'; }
  else if(ed.kind==='unresolved'){ srcTxt='提到了但还没写'; tag='待补写'; }
  else if(ed.provenance==='semantic'){ srcTxt='引擎推测·相似度存疑（嵌入暂不可信，仅供参考，非事实关联）'; tag='引擎·存疑'; }
  else if(ed.provenance==='bridge'){ srcTxt='跨主题桥接（分属不同学科带，但共享核心概念词，引擎自动发现）'; tag='引擎·桥接'; }
  else { srcTxt='共现（按关键词自动发现）'; tag='引擎·共现'; }
  let html = `<div class="det-title">${esc(a?a.label:'?')} ↔ ${esc(b?b.label:'?')}</div>
    <div class="det-row">来源：<span class="tag ${ed.kind==='hard'?'':'col'}">${tag}</span> ${srcTxt}</div>`;
  if(ed.kind==='soft' && ed.evidence && ed.evidence.length)
    html += ed.provenance==='semantic'
      ? `<div class="det-row">${ed.evidence.map(esc).join('、')}（嵌入相似度暂不可信，仅作引擎推测，非事实关联）</div>`
      : `<div class="det-row">共享关键词：${ed.evidence.map(esc).join('、')}</div>`;
  if(ed.kind==='soft')
    html += `<div class="det-row">引擎判定：已自动接入图谱（无需确认）</div>`;
  if(ed.kind==='soft')
    html += `<div class="edge-act"><button class="soft" id="gDel">移除连接</button></div>`;
  $('gDetail').innerHTML=html;
  if(ed.kind==='soft'){
    $('gDel').onclick=async()=>{ await api('/api/soft-link/dismiss',{src_id:ed.source,dst_id:ed.target}); await renderGraph(); };
  }
  graphOpenInspector();
}
function graphClearSelection(){
  if(!GV) return;
  GV.selectedNode=null; GV.selectedEdge=null;
  const d=$('gDetail'); if(d) d.innerHTML='<div class="note">点一个节点或一条连线，详情会显示在这里。</div>';
  graphCloseInspector();
}
/* 借鉴 person_dashboard：选中节点时左侧竖条检查器滑入，画布「让出」左侧空间重排，
   而非简单盖住。关闭时再平滑展开。 */
const INSPECTOR_W = 324;
function graphSyncInspector(){
  const ins=$('gInspector'); if(!ins) return;
  const open = !!(GV && (GV.selectedNode||GV.selectedEdge));
  ins.classList.toggle('open', open);
  ins.setAttribute('aria-hidden', open?'false':'true');
}
// 把世界坐标系(0..960 × 0..540)按比例塞进「可见区」：可见区左侧让出 insetLeft 给检查器
function graphRefit(animate){
  const svg=$('gSvg'); if(!svg||!GV) return;
  const r=svg.getBoundingClientRect();
  const PAD=18;
  const inset=GV.insetLeft||0;
  const visW=Math.max(140, r.width - inset - 2*PAD);
  const visH=Math.max(140, r.height - 2*PAD);
  let k=Math.min(visW/960, visH/540);
  k=Math.max(0.4, Math.min(2.6, k));
  const tx = inset + PAD + (visW - 960*k)/2;
  const ty = PAD + (visH - 540*k)/2;
  if(animate){
    const from={tx:GV.layout.tx, ty:GV.layout.ty, k:GV.layout.k}, to={tx,ty,k};
    const dur=270, t0=performance.now();
    const ease=x=> x<0.5 ? 2*x*x : 1-Math.pow(-2*x+2,2)/2;
    const step=()=>{ const p=Math.min(1,(performance.now()-t0)/dur), e=ease(p);
      GV.layout.tx=from.tx+(to.tx-from.tx)*e;
      GV.layout.ty=from.ty+(to.ty-from.ty)*e;
      GV.layout.k=from.k+(to.k-from.k)*e;
      graphPaint();
      if(p<1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  } else { GV.layout.tx=tx; GV.layout.ty=ty; GV.layout.k=k; graphPaint(); }
}
function graphOpenInspector(){
  if(!GV) return;
  GV.insetLeft=INSPECTOR_W;
  graphSyncInspector();
  graphRefit(true);
}
function graphCloseInspector(){
  if(!GV) return;
  GV.insetLeft=0;
  graphSyncInspector();
  graphRefit(true);
}
/* -------- 图谱渲染（wiki 内容驱动） -------- */
async function renderGraph(){
  let data;
  try { data = await api('/api/graph'); }
  catch(e){ const box=$('gDetail'); if(box) box.innerHTML='<div class="note">图谱数据加载失败</div>'; return; }
  graphBuildData(data);
  // 图例领域色点
  const lgDom=$('gLegendDomains');
  const bands=[...new Set(Object.values(GV.nodes).filter(n=>n.type==='item'&&n.band).map(n=>n.band))];
  if(lgDom) lgDom.innerHTML = bands.map(d=>`<div class="lg"><span class="dot" style="background:${bandColor(d)}"></span>${esc(d)}</div>`).join('');
  // 透镜 chips：全部 + 各领域（band 作过滤器，不再做结构主轴）；引擎发现的软边默认接入，不另设确认开关
  const chips=$('gChips');
  if(chips){
    chips.innerHTML = `<button class="chip active" data-f="all">全部</button>`
      + bands.map(b=>`<button class="chip" data-f="band:${esc(b)}">${esc(b)}</button>`).join('')
      + `<button class="chip ghost" id="btnRelayout">重新布局</button>`
      + `<button class="chip ghost" id="btnFindSoft" title="按关键词共现，自动发现该连未连的候选">发现共现</button>`
      + `<button class="chip ghost" id="btnConsolidate" title="把近义碎片领域并回正确的上位领域">整理领域</button>`;
    // 领域 / 全部（互斥）
    chips.querySelectorAll('.chip[data-f]').forEach(b=>b.onclick=()=>{
      chips.querySelectorAll('.chip[data-f]').forEach(x=>x.classList.remove('active'));
      b.classList.add('active');
      const f=b.dataset.f;
      GV.lens.band = f.startsWith('band:')?f.slice(5):null;
      if(f==='all') graphClearSelection();   // 「全部」= 恢复全显示，清掉节点聚焦锁定
      graphPaint();
    });
    const rl=$('btnRelayout'); if(rl) rl.onclick=()=>{ Object.values(GV.nodes).forEach((n,i)=>{ if(!n.fixed){ const ang=i/Math.max(1,Object.keys(GV.nodes).length)*Math.PI*2; n.x=480+Math.cos(ang)*190+(Math.random()-0.5)*40; n.y=295+Math.sin(ang)*150+(Math.random()-0.5)*40; n.vx=0;n.vy=0; } }); graphReheat(0.7); };
    const fs=$('btnFindSoft'); if(fs) fs.onclick=async()=>{ fs.disabled=true; fs.textContent='发现中'; try{ const r=await api('/api/soft-links/refresh'); toast(r&&r.written?`发现 ${r.written} 组新关联，已自动接入图谱`:'没有新的关联'); }catch(e){ toast('发现失败'); } finally { fs.disabled=false; fs.textContent='发现共现'; await renderGraph(); } };
    const bc=$('btnConsolidate'); if(bc) bc.onclick=async()=>{ bc.disabled=true; bc.textContent='整理中'; try{ const r=await api('/api/kb/consolidate',{merge_jaccard:0.5}); if(r&&r.merged&&r.merged.length) toast(`已合并 ${r.merged.length} 组近义领域：`+r.merged.map(m=>`${m.dropped}→${m.kept}`).join('，')); else toast('领域已经很干净'); }catch(e){ toast('整理失败'); } finally { bc.disabled=false; bc.textContent='整理领域'; await load(); } };
  }
  graphBind();
  graphSettle(220);
  GV.insetLeft = (GV.selectedNode||GV.selectedEdge) ? INSPECTOR_W : 0;
  graphSyncInspector();
  graphRefit(false);
  graphReheat(0.4);
  // 阅读页点「相关条目」→ 进图谱自动聚焦该节点（高亮邻居、虚化非邻居，工作台式）
  const _active = document.querySelector('nav a.active');
  if(window._pendingGraphFocus && _active && _active.dataset.view==='graph' && GV.nodes[window._pendingGraphFocus]){
    const fid = window._pendingGraphFocus; window._pendingGraphFocus = null;
    graphSelectNode(fid);
  }
  renderAutoLog();                       // 自动核对记录（引擎自主核对审计，移到图谱下方）
}
let _autoLogTimer = null;
function _fmtTime(ts){
  const d = new Date(ts*1000);
  const p = n => (n<10?'0':'')+n;
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
async function renderAutoLog(){
  const box = $('gLog'); if(!box) return;
  try{
    const r = await api('/api/audit-log');
    const items = (r&&r.items)||[];
    if(!items.length){ box.innerHTML='<div class="muted">暂无核对记录。写入或编辑知识后，引擎会自主扫描关联，阴阳互纠与系统消息也会留在这里。</div>'; }
    else {
      // items 已由后端合并：auto_log(心跳/发现/自检) + calib_log(系统/阳→阴/阴→阳)，按时间倒序带时间戳
      box.innerHTML = items.map(l=>{
        const cls = l.cls||'d-sys', tag = l.tag||'核对';
        return `<div><span class="dir ${cls}">${tag}</span>`
             + `<span class="lg-time">${_fmtTime(l.created_at)}</span> ${esc(l.message)}</div>`;
      }).join('');
    }
    // 日志/缓存占用：默认显示体量，悬停变「清理」（见 css #gLogPurge）
    const st = (r&&r.stats)||{};
    const szEl = $('gLogPurge');
    if(szEl){
      const lb = st.log_bytes||0, db = st.db_bytes||0;
      const fmt = b => b>=1048576 ? (b/1048576).toFixed(1)+' MB'
                    : b>=1024 ? (b/1024).toFixed(1)+' KB' : b+' B';
      const sz = szEl.querySelector('.sz'); if(sz) sz.textContent = `≈ ${fmt(lb)}`;
      szEl.title = `日志与缓存占用 ${fmt(lb)}（共 ${st.auto_count||0} 条引擎审计 · ${st.calib_count||0} 条阴阳/系统）；`
                  + `整库文件 ${fmt(db)}。悬停可清理超过保留期的记录。`;
    }
  }catch(e){ /* 网络抖动忽略 */ }
  // 轻轮询：图谱视图激活时，每 15s 刷新一次自动核对记录（不打扰力导布局）
  if(!_autoLogTimer){
    _autoLogTimer = setInterval(()=>{ if($('gLog')) renderAutoLog(); }, 15000);
  }
  // 「立即核对」：手动触发一次全库关联核对（含周期扫描同样的共现+语义+健康自检）
  const bn = $('btnAutoLogNow');
  if(bn && !bn._bound){ bn._bound = true; bn.onclick = async ()=>{
    bn.disabled = true; bn.textContent = '核对中';
    try{
      const r = await api('/api/soft-links/refresh');
      if(r && r.written) toast(`核对完成：发现 ${r.written} 组新关联`);
      else toast('核对完成：暂未发现新的关联');
    }catch(e){ toast('核对失败'); }
    finally { bn.disabled = false; bn.textContent = '立即核对'; await renderAutoLog(); await renderGraph(); }
  };}
  // 「清理」：删除超过保留期的日志/缓存型数据（auto_log 30 天、calib_log 90 天），并回收磁盘
  const pb = $('gLogPurge');
  if(pb && !pb._bound){ pb._bound = true; pb.onclick = async ()=>{
    pb.disabled = true; const sz = pb.querySelector('.sz'); if(sz) sz.textContent = '清理中';
    try{
      const r = await api('/api/audit-log/purge', {keep_days: 30});
      const dA = (r&&r.deleted_auto)||0, dC = (r&&r.deleted_calib)||0;
      toast(dA+dC ? `已清理 ${dA} 条引擎审计 · ${dC} 条阴阳/系统记录`
                  : '没有超过保留期的记录需要清理');
    }catch(e){ toast('清理失败'); }
    finally { pb.disabled = false; await renderAutoLog(); }
  };}
}
