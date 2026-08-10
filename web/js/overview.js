// 灯笼知识库 · overview —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 总览 ---------------- */
function statCard(n, t, kind){
  return `<div class="stat ${kind||''}"><div class="accent"></div>
    <div class="n">${n}</div><div class="t">${t}</div></div>`;
}
function renderOverview(){
  const g = S.independence;
  const linked = new Set();
  (S.links||[]).forEach(l=>{ linked.add(l.src); linked.add(l.dst); });
  const isolated = S.items.filter(i=>!linked.has(i.id));
  const softN = (S.links||[]).filter(l=>l.kind==='soft').length;
  $('stats').innerHTML =
    statCard(S.items.length, '知识条目', 'ink') +
    statCard(softN, '引擎关联', softN?'':'stone') +
    statCard((S.links||[]).length, '条目互链') +
    statCard(isolated.length, '还没有连接', isolated.length?'':'stone') +
    statCard(S.mode==='llm'?'智能':'简单', '判断方式');
  const sb = S.summary_backend || {};
  $('sumBackend').innerHTML = sb.backend === 'llm'
    ? '摘要与标签由模型生成。'
    : '摘要与标签当前用<b>离线方式</b>生成' + (sb.reason ? '（' + esc(sb.reason) + '）' : '') +
      '：取首句作概要、按词频挑标签，够用但不如模型精准。';
  // 语义信号守卫状态（融合 Karpathy Lint 的"信号可信度"检查，用 Lantern 实证统计实现）
  const sig = S.signal || {};
  if(sig.status){
    const scls = sig.status==='degraded' ? '#A32D2D' : sig.status==='warn' ? '#BA7517' : '#3B6D11';
    const stxt = sig.status==='degraded' ? '语义信号退化：检测到跨领域条目却呈极高相似，语义关联已自动挂起。'
               : sig.status==='warn' ? '语义信号偏弱，建议核查嵌入来源。'
               : '语义信号健康，区分度良好。';
    $('sigGuard').innerHTML = `语义信号：<b style="color:${scls}">${sig.status}</b>`
      + ` · 跨带高相似 ${sig.cross_band_highsim||0} 对 · 均值 ${sig.mean_sim}`
      + `<br><span class="muted">${stxt}</span>`;
  }
  // 尚未连接的知识（按条目去重），引擎会自动为它们发现关联
  const byId = new Map();
  const ensure = id => { let o = byId.get(id); if(!o){ o = {it:null, reasons:[]}; byId.set(id, o); } return o; };
  isolated.forEach(i=>{ const o = ensure(i.id); o.it = i; o.reasons.push({why:'还没有连接', cls:''}); });
  const warn = [...byId.values()];
  $('ovWarnCount').textContent = `· ${warn.length} 条`;
  if(!warn.length){
    $('ovWarn').innerHTML = '<div class="note">都挺好：每条知识都连上了至少一条。</div>';
  } else {
    $('ovWarn').innerHTML = warn.slice(0,8).map(({it,reasons})=>`
      <div class="edge clickable" data-id="${it.id}" style="padding:7px 8px;margin:0 -8px;">
        <b style="color:var(--ink)">${esc(it.title)}</b>
        <span class="tag">${it.band}</span>
        ${reasons.map(r=>`<span class="tag ${r.cls}">${r.why}</span>`).join('')}
        <span class="muted" style="font-size:11.5px;">偏差 ${it.offset>0?'+':''}${it.offset}</span>
      </div>`).join('');
    bindResultClicks('ovWarn');
  }
  // 知识分布：各领域条数（简单条形清单，非坐标图，与逻辑偏差页不重复）
  const byBand = {};
  S.items.forEach(i=>{ const b=i.disp_band||i.band; byBand[b] = (byBand[b]||0)+1; });
  const total = S.items.length || 1;
  $('ovBandCount').textContent = `· ${(S.bands||[]).length} 个领域`;
  $('ovBands').innerHTML = (S.bands||[]).map(b=>{
    const n = byBand[b.name]||0;
    const w = Math.round(n/total*100);
    const c = bandColor(b.name);
    return `<div class="ov-band">
      <span class="dot" style="background:${c}"></span>
      <span style="flex:0 0 84px;font-size:13px;">${esc(b.name)}</span>
      <div class="ov-bar"><div style="width:${w}%;background:${c};"></div></div>
      <b style="flex:0 0 26px;text-align:right;font-size:12.5px;">${n}</b>
    </div>`;
  }).join('');
}

