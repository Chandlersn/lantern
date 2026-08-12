// 灯笼知识库 · render —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 公共渲染：两项判断 / 地图 / 守卫 / 关联 ---------------- */
function renderBeams(boxId, readId, it){
  const x0=56, span=576, W=690, X = p => x0 + p/100*span;
  const mainX=X(it.main_pos), vX=X(it.vernier), eX=X(it.typical);
  // 偏差只作数值呈现，不再区分异常/正常，不做价值提示
  // 领域带条带：只画主干带，且严格按 schema 的 order 左→右排列（人文→社科→自科→形式），
  // 不受条数与细领域影响；细领域在地图里按其真实主尺范围定位，不进这条带。
  const bb = (S.bands||[]).filter(b=>b.backbone);
  let bands='';
  bb.forEach((b,i)=>{ const bx=x0+i*span/4, on=b.name===it.band;
    bands+=`<rect x="${bx}" y="104" width="${span/4}" height="36" fill="${on?'#EFE7D6':(i%2?'#F3EFE4':'#FCFAF3')}" stroke="#D8D0C0"/>`;
    bands+=`<text x="${bx+span/8}" y="127" font-size="12" fill="${on?'#23201C':'#7d7970'}" text-anchor="middle">${b.name}</text>`;});
  const mainTick=`<line x1="${mainX}" y1="92" x2="${mainX}" y2="140" stroke="#23201C" stroke-width="2.5"/>
    <circle cx="${mainX}" cy="92" r="4.5" fill="#23201C"/>
    <text x="${mainX}" y="84" font-size="11" fill="#23201C" text-anchor="middle">${it.main_pos}</text>`;
  const beam=`<line x1="${x0}" y1="206" x2="${x0+span}" y2="206" stroke="#23201C" stroke-width="2"/>`;
  let ticks='';
  for(let v=0;v<=100;v+=10){ const tx=X(v), big=v%50===0;
    ticks+=`<line x1="${tx}" y1="${big?194:199}" x2="${tx}" y2="206" stroke="#23201C" stroke-width="${big?1.6:1}"/>`;
    if(big) ticks+=`<text x="${tx}" y="189" font-size="10.5" fill="#5F5E5A" text-anchor="middle">${v}</text>`;}
  const anchors=[[0,'描述'],[25,'归纳'],[50,'假设'],[75,'推理'],[100,'证明']]
    .map(([v,l])=>`<text x="${X(v)}" y="248" font-size="10" fill="#9a968c" text-anchor="middle">${l}</text>`).join('');
  const refLabel = '领域基准' + (it.band_count!=null && it.band_count<2 ? '（样本少）' : '');
  const expTick=`<line x1="${eX}" y1="206" x2="${eX}" y2="230" stroke="#888780" stroke-width="1.5" stroke-dasharray="3 3"/>
    <text x="${eX}" y="233" font-size="10.5" fill="#888780" text-anchor="middle">${refLabel} ${it.typical}</text>`;
  const actTick=`<line x1="${vX}" y1="168" x2="${vX}" y2="206" stroke="#B5302A" stroke-width="2.5"/>
    <circle cx="${vX}" cy="168" r="4.5" fill="#B5302A"/>
    <text x="${vX}" y="160" font-size="11" fill="#B5302A" text-anchor="middle">${it.vernier}</text>`;
  const lo=Math.min(eX,vX), hi=Math.max(eX,vX);
  const gap=`<rect x="${lo}" y="202" width="${hi-lo}" height="8" fill="#B9B4A6" opacity=".5"/>`;
  const refScope = it.ref_kind==='global' ? '全库的常规范围内' : '在该领域的常规范围内';
  const badge=`<text x="${x0}" y="274" font-size="11.5" fill="#5F5E5A">偏移 ${it.offset>0?'+':''}${it.offset}（${refScope}）</text>`;
  $(boxId).innerHTML=`<svg viewBox="0 0 ${W} 300" xmlns="http://www.w3.org/2000/svg">
    <text x="34" y="32" font-size="13.5" font-weight="500" fill="#23201C">领域</text>
    <text x="34" y="152" font-size="13.5" font-weight="500" fill="#23201C">形式化读数</text>
    ${bands}${mainTick}${beam}${ticks}${anchors}${gap}${expTick}${actTick}${badge}
    <g font-size="11" fill="#23201C">
      <rect x="${x0+398}" y="288" width="12" height="12" fill="#23201C"/><text x="${x0+415}" y="298">领域</text>
      <rect x="${x0+449}" y="288" width="12" height="12" fill="#B5302A"/><text x="${x0+466}" y="298">形式化读数</text>
      <rect x="${x0+542}" y="288" width="12" height="12" fill="#888780"/><text x="${x0+559}" y="298">领域平均线</text>
    </g></svg>`;
  $(readId).innerHTML =
    `<span class="pill">领域 ${it.band}</span>`+
    `<span class="pill">位置 ${it.main_pos}${it.revised?' · 已调整':''}</span>`+
    `<span class="pill" title="系统对这条内容落在哪个领域 / 谱系位置的把握程度（主尺读数置信度，0–100%）">归类把握 ${Math.round((it.main_conf||0)*100)}%</span>`+
    `<span class="pill">形式化 ${it.vernier}</span>`+
    `<span class="pill">${it.band_count!=null && it.band_count<2 ? '领域基准（样本少）' : '领域基准'} ${it.typical}</span>`+
    `<span class="pill>偏差 ${it.offset>0?'+':''}${it.offset}</span>`+
    (it.main_conf<0.35?`<span class="pill hot">归类把握较低 · 可能是跨领域内容</span>`:'');
}

function renderMap(){
  const W=1160,H=560;
  const x0=104,x1=1116,yTop=58,yBot=482,span=x1-x0,h=yBot-yTop;
  const X=p=>x0+p/100*span, Y=d=>yBot-d/100*h;
  let grid='';
  // 领域列（背景+标签）按"该领域真实主尺范围"定位，与数据点和基线共用同一套坐标，
  // 这样每条基线、每个点都落在自己领域的格里，不会串到别的领域列。
  S.bands.forEach((b)=>{ const bx=X(b.x0!=null?b.x0:(b.center-8)); const bw2=X(b.x1!=null?b.x1:(b.center+8))-bx;
    const tint=(Math.floor((b.x0!=null?b.x0:b.center)/25)%2)?'#F3EFE4':'#FCFAF3';
    grid+=`<rect x="${bx.toFixed(1)}" y="${yTop}" width="${bw2.toFixed(1)}" height="${h}" fill="${tint}" opacity=".65"/>`;});
  // 横轴领域标签：碰撞交给统一的「重叠→当前常显/其余 hover」解析（resolveLabelOverlaps）。
  // 主干带必显（提供谱系上下文），细分域同样纳入；当前选中项所属领域标签标记为 .on 常显优先。
  const _ci = cur();
  const curBand = _ci ? (_ci.disp_band || _ci.band) : null;
  S.bands
    .map(b=>({ name:b.name,
               cx:(b.center!=null?b.center:(b.x0!=null?(b.x0+b.x1)/2:50)),
               backbone:!!b.backbone }))
    .filter(l=>l.cx!=null && l.name)
    .sort((a,b)=>(b.backbone-a.backbone)||(a.cx-b.cx))
    .forEach(l=>{
      const on = (l.name===curBand) ? ' on' : '';
      grid+=`<g class="dlabel${on}">`
          + `<circle class="hit" cx="${X(l.cx).toFixed(1)}" cy="${(yBot+18).toFixed(1)}" r="14" fill="transparent"/>`
          + `<text x="${X(l.cx).toFixed(1)}" y="${(yBot+22).toFixed(1)}" font-size="12" fill="${l.backbone?'#5F5E5A':'#9a968c'}" text-anchor="middle">${esc(l.name)}</text>`
          + `</g>`;
    });
  [0,25,50,75,100].forEach(v=>{ grid+=`<line x1="${x0}" y1="${Y(v)}" x2="${x1}" y2="${Y(v)}" stroke="#E2DACA" stroke-width="1"/>`;
    grid+=`<text x="${x0-10}" y="${Y(v)+4}" font-size="12" fill="#888780" text-anchor="end">${v}</text>`;});
  // 领域基准趋势线（斜向上·贯穿全图）：连接【固定基准曲线】S.baseline_curve 的各
  // (center, typical_vernier)——该曲线由全注册表（与库内数据无关）按 (主干带, 带内
  // intra_band_order) 均匀铺开中心后连成，已消除带内倒挂、单调上升。偏差线顶端
  // （连 Y(it.typical)，即该条目所属学科域的典型游标）正好落在这条固定基线上——
  // 「从领域基准线开始偏移」语义统一，且成为全谱参照（不受当前库里有没有该域文章影响）。
  // 主干带仍由顶部领域条带提供谱系上下文。
  let baseLines = '';
  // 优先用「固定基准曲线」（baseline_curve，过滤 hidden）；不足 2 点回退到数据驱动的
  // domain_bands；再不足回退主干带——保证背景基准线始终存在、偏差线不悬空。
  const bc = (S.baseline_curve||[]).filter(d=>!d.hidden && d.center!=null && d.typical_vernier!=null)
                                   .sort((a,b)=>a.center-b.center);
  const db = (S.domain_bands||[]).filter(d=>d.center!=null && d.typical_vernier!=null)
                                .sort((a,b)=>a.center-b.center);
  const trendSrc = bc.length>=2 ? bc
              : (db.length>=2 ? db
              : (S.bands||[]).filter(b=>b.backbone && b.center!=null).sort((a,b)=>a.center-b.center));
  if(trendSrc.length>=2){
    const lineStr = trendSrc.map(d=>`${X(d.center).toFixed(1)},${Y(d.typical_vernier).toFixed(1)}`).join(' ');
    baseLines += `<polyline points="${lineStr}" fill="none" stroke="#9a968c" stroke-width="2" stroke-dasharray="7 5" opacity=".92"/>`;
  }
  // 领域基准线插值：给定主尺位置 x(0-100)，返回【画出的灰色基准线】(baseline_curve 过滤
  // hidden，即上面绘制的趋势线) 在该 x 处的典型游标读数。与灰色基线共用同一组
  // (center, typical_vernier) 控制点，因此偏差线顶端正好落在基线上——只从基线向具体点
  // 引出，绝不穿越基线。
  function baselineValAtX(x){
    if(!bc.length) return null;
    if(x<=bc[0].center) return bc[0].typical_vernier;
    const last=bc[bc.length-1];
    if(x>=last.center) return last.typical_vernier;
    for(let i=0;i<bc.length-1;i++){
      const a=bc[i], b=bc[i+1];
      if(x>=a.center && x<=b.center){
        const t=(x-a.center)/((b.center-a.center)||1);
        return a.typical_vernier + t*(b.typical_vernier-a.typical_vernier);
      }
    }
    return last.typical_vernier;
  }
  // 全部可见学科域的淡锚点（仅标点、不标字，呈现细化后的基准密度）
  (S.baseline_curve||[]).filter(d=>!d.hidden && d.center!=null && d.typical_vernier!=null).forEach(d=>{
    const cx=X(d.center), cy=Y(d.typical_vernier);
    baseLines += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="2.4" fill="#bdb8ac" opacity=".7"/>`;
  });
  // 有数据的学科域：标圆点（常显，落在基准线上）+「域名 典型值」标签（.dlabel：
  // 无重叠全显；重叠时当前项所属域常显、其余 hover 浮现）。
  const _ci2 = cur();
  const curDom = _ci2 ? (_ci2.axis_domain || '') : '';
  (S.domain_bands||[]).filter(d=>d.count>0 && d.center!=null).forEach(d=>{
    const cx=X(d.center), cy=Y(d.typical_vernier);
    baseLines += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="3.6" fill="#9a968c"/>`;
    const on = (d.name===curDom) ? ' on' : '';
    baseLines += `<g class="dlabel${on}">`
        + `<circle class="hit" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="14" fill="transparent"/>`
        + `<g class="tip"><text x="${cx.toFixed(1)}" y="${(cy-7).toFixed(1)}" font-size="10.5" fill="#6b685f" text-anchor="middle">${esc(d.name)} ${d.typical_vernier}</text></g>`
        + `</g>`;
  });
  // 选中的这条永远是焦点，必画；其余按显示模式收窄，避免一多就乱
  const curIt=cur(); let disp=S.items;
  if(!curIt){ $('vMap').innerHTML='<div class="note">还没有内容可以画。</div>'; return; }
  if(mapMode==='near'){
    const near=S.items.map(it=>({it, dd: it.id===curId?-1:Math.hypot((it.main_pos||0)-(curIt.main_pos||0),(it.vernier||0)-(curIt.vernier||0))}))
                  .sort((a,b)=>a.dd-b.dd).slice(0,11);  // 自己 + 最近 10 条（画布变大，可多容纳）
    const ids=new Set(near.map(x=>x.it.id)); ids.add(curId);
    disp=S.items.filter(it=>ids.has(it.id));
  } else if(mapMode==='band'){
    disp=S.items.filter(it=>it.band===curIt.band);
  }
  // 计算各点坐标（含「属于当前选中项」的连线）
  const pts0=disp.map(it=>({it, cx:X(it.main_pos), cy:Y(it.vernier), sel:it.id===curId}));
  let pts='';
  pts0.forEach(o=>{
    const title=(o.it.title||'').slice(0,14);
    const tw=Math.min(title.length*12.5+8, 190);
    // 竖向偏差线：从【画出的领域基准线】上该点的正下方/正上方引出到该点（严格垂直、
    // 终止于基线，永不穿越）。基准值在各点 x 处对 baseline_curve 线性插值得到，与灰虚线
    // 同源，故「点在基准上方=offset 正、下方=offset 负」且线段长度严格 == |offset|。
    const baseVal = baselineValAtX(o.it.main_pos);
    if(baseVal!=null){
      const baseY = Y(baseVal);
      // 偏差线一律虚线：当前选中项→朱砂红稍粗（凸显焦点），其余→淡灰细虚线（背景参照）。
      // 起点严格落在领域基准线上（baselineValAtX 同源），绝不穿越基线。
      if(o.sel){
        pts+=`<line x1="${o.cx.toFixed(1)}" y1="${o.cy.toFixed(1)}" x2="${o.cx.toFixed(1)}" y2="${baseY.toFixed(1)}" stroke="#B5302A" stroke-width="1.8" stroke-dasharray="5 4" opacity=".92"/>`;
      } else {
        pts+=`<line x1="${o.cx.toFixed(1)}" y1="${o.cy.toFixed(1)}" x2="${o.cx.toFixed(1)}" y2="${baseY.toFixed(1)}" stroke="#9a968c" stroke-width="1" stroke-dasharray="4 4" opacity=".32"/>`;
      }
    }
    // 偏移量与该竖向线段同源（offset = vernier − 基准线在该点 x 处的值），徽章与线段一致。
    const off = (baseVal!=null) ? Math.round((o.it.vernier-baseVal)*10)/10 : (o.it.offset||0);
    if(o.sel){
      // 当前选中项：外圈 + 常显名字（唯一常显标签）
      // 以当前点为中心，紧贴点正上/正下，不甩到一侧（避免长标题横在远处、脱离点）
      pts+=`<circle cx="${o.cx.toFixed(1)}" cy="${o.cy.toFixed(1)}" r="15" fill="none" stroke="#23201C" stroke-width="1" opacity=".3"/>`;
      pts+=`<circle cx="${o.cx.toFixed(1)}" cy="${o.cy.toFixed(1)}" r="10" fill="#B5302A" stroke="#FFFFFF" stroke-width="2.5"/>`;
      const boxH=22, gap=12;
      let boxY=o.cy-15-gap-boxH;                       // 优先：点正上方
      if(boxY<yTop+2) boxY=o.cy+15+gap;                // 上方空间不足→正下方
      if(boxY+boxH>yBot-2) boxY=o.cy-15-gap-boxH;      // 下方也不足（极端）→回上方
      pts+=`<g class="map-lbl on">`;
      pts+=`<rect x="${(o.cx-tw/2-4).toFixed(1)}" y="${boxY.toFixed(1)}" width="${(tw+8).toFixed(1)}" height="${boxH}" rx="3" fill="#23201C"/>`;
      pts+=`<text x="${o.cx.toFixed(1)}" y="${(boxY+boxH/2+4).toFixed(1)}" font-size="12.5" fill="#fff" font-weight="600" text-anchor="middle">${esc(title)}</text>`;
      pts+=`</g>`;
    } else {
      // 其余点：只画圆点（含透明命中区放大 hover），名字与偏移 hover 时才浮现。
      // 与选中项一致：以当前点为中心、紧贴点正上/正下，消除横向甩开导致的"脱离点"
      pts+=`<g class="map-dot dim">`;
      pts+=`<circle class="hit" cx="${o.cx.toFixed(1)}" cy="${o.cy.toFixed(1)}" r="14" fill="transparent"/>`;
      pts+=`<circle cx="${o.cx.toFixed(1)}" cy="${o.cy.toFixed(1)}" r="6.5" fill="#5F5E5A"/>`;
      const boxH=34, gap=10;
      let boxY=o.cy-boxH-gap;                 // 优先：紧贴点正上方（框底距点 gap）
      if(boxY<yTop+2) boxY=o.cy+gap;          // 上方空间不足→紧贴点正下方
      if(boxY+boxH>yBot-2) boxY=o.cy-boxH-gap;// 下方也不足（极端）→回上方
      const ty1=boxY+15, ty2=boxY+30;
      pts+=`<g class="tip">`;
      pts+=`<rect x="${(o.cx-tw/2-4).toFixed(1)}" y="${boxY.toFixed(1)}" width="${(tw+8).toFixed(1)}" height="${boxH}" rx="3" fill="#FFFFFF" opacity="0.94" stroke="#D8D0C0"/>`;
      pts+=`<text x="${o.cx.toFixed(1)}" y="${ty1.toFixed(1)}" font-size="12.5" fill="#23201C" font-weight="600" text-anchor="middle">${esc(title)}</text>`;
      pts+=`<text x="${o.cx.toFixed(1)}" y="${ty2.toFixed(1)}" font-size="11" fill="#6b685f" text-anchor="middle">${off}</text>`;
      pts+=`</g>`;
      pts+=`</g>`;
    }
  });
  const lgY=H-24;
  $('vMap').innerHTML=`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block;">
    ${grid}${baseLines}
    <line x1="${x0}" y1="${yBot}" x2="${x1}" y2="${yBot}" stroke="#23201C" stroke-width="2"/>
    <line x1="${x0}" y1="${yTop}" x2="${x0}" y2="${yBot}" stroke="#23201C" stroke-width="2"/>
    ${pts}
    <text x="32" y="${(yTop+yBot)/2}" font-size="13" fill="#5F5E5A" text-anchor="middle" transform="rotate(-90 32 ${(yTop+yBot)/2})">形式化读数</text>
    <text x="${(x0+x1)/2}" y="${lgY}" font-size="13" fill="#5F5E5A" text-anchor="middle">领域</text>
    <g font-size="12" fill="#23201C">
      <line x1="${x1-360}" y1="${lgY-4}" x2="${x1-326}" y2="${lgY-4}" stroke="#9a968c" stroke-width="2" stroke-dasharray="7 5"/>
      <text x="${x1-318}" y="${lgY}">基准趋势</text>
      <line x1="${x1-252}" y1="${lgY-4}" x2="${x1-216}" y2="${lgY-4}" stroke="#B5302A" stroke-width="1.8" stroke-dasharray="5 4"/>
      <text x="${x1-208}" y="${lgY}">偏差</text>
      <circle cx="${x1-34}" cy="${lgY-4}" r="6" fill="#B5302A" stroke="#FFFFFF" stroke-width="2"/><text x="${x1-20}" y="${lgY}">当前</text>
    </g></svg>`;
  // 后处理：用真实文本包围盒贴合背景框，根治中英文宽度估算误差导致的溢出/错位
  const svg = $('vMap').querySelector('svg');
  if (svg) {
    svg.querySelectorAll('g.map-lbl.on, g.map-dot').forEach(g => {
      const rect = g.querySelector('rect');
      const texts = g.querySelectorAll('text');
      if (!rect || !texts.length) return;
      let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
      texts.forEach(t => { const b=t.getBBox();
        if(b.x<minX)minX=b.x; if(b.y<minY)minY=b.y;
        if(b.x+b.width>maxX)maxX=b.x+b.width; if(b.y+b.height>maxY)maxY=b.y+b.height; });
      const padX=6, padY=4;
      let bx=minX-padX, by=minY-padY, bw=maxX-minX+padX*2, bh=maxY-minY+padY*2;
      // 防止标签框越出画布左右边界
      if (bx < x0) { const dx=x0-bx; bx+=dx; texts.forEach(t=>t.setAttribute('x',(parseFloat(t.getAttribute('x'))+dx).toFixed(1))); }
      else if (bx+bw > x1) { const dx=x1-(bx+bw); bx+=dx; texts.forEach(t=>t.setAttribute('x',(parseFloat(t.getAttribute('x'))+dx).toFixed(1))); }
      rect.setAttribute('x', bx.toFixed(1));
      rect.setAttribute('y', by.toFixed(1));
      rect.setAttribute('width', bw.toFixed(1));
      rect.setAttribute('height', bh.toFixed(1));
    });
    // 领域标签重叠解析：无重叠→全显；重叠→当前域常显、其余 hover 浮现
    resolveLabelOverlaps(svg);
  }
}

function resolveLabelOverlaps(svg){
  // 与数据点标签同源思路：把学科域标签（横轴列标签 + 「域名 典型值」标签）按真实
  // 包围盒做重叠聚类——彼此不重叠的标签全部常显；一旦成簇重叠，则簇内「当前选中项
  // 所属域」(.on) 强制常显，其余加 .dim（隐藏、hover 才浮现），既不挤作一团也不丢信息。
  const groups = [...svg.querySelectorAll('g.dlabel')];
  if(groups.length < 2) return;
  const PAD = 2;
  const info = groups.map(g=>{
    const t = g.querySelector('text');
    const b = t.getBBox();
    return {g, x:b.x, y:b.y, w:b.width, h:b.height,
            current: g.classList.contains('on')};
  });
  const n = info.length;
  const adj = Array.from({length:n}, ()=>[]);
  for(let i=0;i<n;i++) for(let j=i+1;j<n;j++){
    const a=info[i], b=info[j];
    const ox = a.x < b.x+b.w+PAD && b.x < a.x+a.w+PAD;
    const oy = a.y < b.y+b.h+PAD && b.y < a.y+a.h+PAD;
    if(ox && oy){ adj[i].push(j); adj[j].push(i); }
  }
  const seen = new Array(n).fill(false);
  for(let i=0;i<n;i++){
    if(seen[i]) continue;
    const stack=[i], comp=[];
    seen[i]=true;
    while(stack.length){
      const u=stack.pop(); comp.push(u);
      for(const v of adj[u]) if(!seen[v]){ seen[v]=true; stack.push(v); }
    }
    if(comp.length>1){
      for(const k of comp){
        if(!info[k].current) info[k].g.classList.add('dim');
      }
    }
  }
}

function renderGuard(boxId, famId){
  const g=S.independence;
  const blocked = g.blocked;
  const gtxt = blocked
             ? '⛔ 两尺独立性已坍缩，新条目偏移已被隔离（拉闸）。请通过「重测全部」更换其中一路 provider 以复位。'
             : g.status==='fail' ? '两项判断高度相关，独立性受损，建议检查。'
             : g.status==='warn' ? '两项判断略有相关，需留意。'
             : '两项判断互不影响，结果可靠。';
  const cls = blocked ? 'fail' : (g.status==='fail'?'fail':(g.status==='warn'?'warn':'healthy'));
  $(boxId).className='guard g-'+cls;
  $(boxId).innerHTML=`关联度 <b>${g.r}</b> · 样本 ${g.n||0}` + (blocked?' · <b>已拉闸</b>':'') + `<br>${gtxt}`;
  const sig = S.signal || {};
  if(sig.status){
    const slabel = sig.status==='degraded' ? '退化·已挂起' : sig.status==='warn' ? '偏弱' : '健康';
    $(boxId).innerHTML += `<br>语义信号：<b>${sig.status}</b>（${slabel} · 跨带高相似 ${sig.cross_band_highsim||0} 对）`;
  }
  $(famId).innerHTML=`系统实时检查两项判断是否互相干扰（关联度越低越好）`
    + (g.same_underlying_source? '<br><span class="muted">注：两尺当前同源，独立性为实证量而非结构保证</span>':'');
}

