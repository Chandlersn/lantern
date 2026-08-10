// 灯笼知识库 · sparks —— 灵感碎片（原料层）视图：随手记捕获 / 列表 / 聚类萌发 / 孵化
async function renderSparks(){
  const [list, cl] = await Promise.all([
    api('/api/sparks'), api('/api/sparks/clusters')
  ]);
  // 列表
  const items = (list && list.items) || [];
  $('spCount').textContent = `· ${items.length} 条`;
  if(!items.length){
    $('spList').innerHTML = '<div class="note">还没有灵感碎片。上面的「随手记」写一句试试。</div>';
  } else {
    $('spList').innerHTML = items.map(sp => sparkCard(sp)).join('');
    bindSparkCards();
  }
  // 聚类萌发
  const clusters = (cl && cl.clusters) || [];
  if(!clusters.length){
    $('spClusters').innerHTML = '<div class="note">碎片还不够多，暂无可辨的主题簇；多记几条相近的想法就会自动浮现。</div>';
  } else {
    $('spClusters').innerHTML = clusters.map(c => clusterCard(c)).join('');
    bindClusterCards();
  }
  bindSparkCapture();
}

function statusLabel(s){
  return s === 'hatched' ? '已孵化' : s === 'incubating' ? '孵化中' : '原料';
}

function sparkCard(sp){
  const tags = (sp.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
  const when = new Date((sp.created_at || 0) * 1000).toLocaleString('zh-CN',
    {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
  let acts;
  if(sp.hatched_item_id){
    acts = `<button class="soft sp-view" data-id="${sp.hatched_item_id}">查看条目</button>`;
  } else {
    acts = `<button class="soft sp-hatch" data-id="${sp.id}">孵化成知识</button>`;
  }
  return `<div class="det-card sp-card">
    <div class="sp-head">
      <b>${esc(sp.title || '未命名')}</b>
      <span class="pill ${sp.status==='hatched'?'llm':sp.status==='incubating'?'warn':'hot'}">${statusLabel(sp.status)}</span>
    </div>
    <div class="sp-body">${esc(sp.content)}</div>
    <div class="sp-tags">${tags}<span class="muted" style="margin-left:auto;">${when}</span></div>
    <div class="sp-acts">
      ${acts}
      <button class="ghost sp-del" data-id="${sp.id}">删除</button>
    </div>
  </div>`;
}

function clusterCard(c){
  const members = (c.members || []).map(m =>
    `<span class="tag can" title="${esc(m.content || '')}">${esc(m.title || '')}</span>`).join('');
  const shared = (c.shared_terms || []).map(t => `<span class="tag col">${esc(t)}</span>`).join('');
  const ids = (c.members || []).map(m => m.id).join(',');
  return `<div class="det-card sp-cluster">
    <div class="sp-head"><b>${esc(c.title)}</b><span class="muted">${c.size} 条碎片</span></div>
    <div class="sp-tags">${shared}</div>
    <div class="sp-tags" style="margin-top:4px;">${members}</div>
    <div class="sp-acts"><button class="soft sp-hatch-cluster" data-ids="${ids}">整簇孵化</button></div>
  </div>`;
}

function bindSparkCards(){
  document.querySelectorAll('#spList .sp-hatch').forEach(b => b.onclick = async () => {
    const id = b.dataset.id;
    b.disabled = true; b.textContent = '孵化中';
    try {
      const r = await api('/api/sparks/' + id + '/hatch', {});
      if(r && r.ok){ showHatchReport(r); await renderSparks(); }
      else toast((r && r.msg) ? r.msg : '孵化失败');
    } catch(e){ toast('孵化失败'); }
    finally { b.disabled = false; b.textContent = '孵化成知识'; }
  });
  document.querySelectorAll('#spList .sp-del').forEach(b => b.onclick = async () => {
    if(!(await confirmBox('确定删除这条灵感碎片？此操作不可恢复。', true))) return;
    const r = await api('/api/sparks/' + b.dataset.id + '/delete', {});
    if(r && r.ok){ toast('已删除'); await renderSparks(); }
  });
  document.querySelectorAll('#spList .sp-view').forEach(b => b.onclick = () => {
    if(typeof openReader === 'function') openReader(parseInt(b.dataset.id, 10));
  });
}

// 智能孵化报告：把「决策 / 关联发现 / 自检反馈 / 兄弟联动」摊开给用户看，
// 让孵化从「静默搬运」变成一次可见的系统事件。
function showHatchReport(r){
  const out = $('spOut');
  if(!out) return;
  const merged = r.decision === 'merged';
  const terms = (r.cluster_terms || []).map(t => `<span class="tag col">${esc(t)}</span>`).join('');
  const fb = (r.feedback_ids || []).length;
  const sibs = (r.siblings_incubating || []);
  const sibBtns = sibs.length
    ? `<div class="sp-tags" style="margin-top:6px;">同簇 ${sibs.length} 条已标「孵化中」：${
        sibs.map(id => `<button class="ghost sp-sib" data-id="${id}">孵化 #${id}</button>`).join('')
      }</div>`
    : '';
  out.innerHTML = `<div class="det-card sp-report">
    <div class="sp-head"><b>智能孵化报告</b>
      <span class="pill ${merged ? 'warn' : 'llm'}">${merged ? '已合并' : '新建'}</span></div>
    <div class="sp-body">
      <div>条目 <b>#${r.item_id}</b> · ${merged
        ? `已并入既有条目（保留其双尺定位）`
        : `已落库并接入知识图谱`}</div>
      ${terms ? `<div class="sp-tags" style="margin-top:4px;">来源簇主题：${terms}</div>` : ''}
      <div class="sp-tags" style="margin-top:6px;">
        关联发现：<b>${r.links_found}</b> 条潜在关联
        ${r.links_found ? `<button class="soft sp-graph">查看图谱</button>` : ''}
      </div>
      <div class="sp-tags">自检反馈：<b>${fb}</b> 条已入收件箱${fb ? '（🔔）' : ''}</div>
      ${sibBtns}
    </div></div>`;
  out.querySelectorAll('.sp-graph').forEach(b => b.onclick = () => {
    if(typeof selectView === 'function') selectView('graph');
  });
  out.querySelectorAll('.sp-sib').forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = '孵化中';
    try {
      const sr = await api('/api/sparks/' + b.dataset.id + '/hatch', {});
      if(sr && sr.ok){ showHatchReport(sr); await renderSparks(); }
      else toast((sr && sr.msg) ? sr.msg : '孵化失败');
    } catch(e){ toast('孵化失败'); }
    finally { b.disabled = false; b.textContent = '孵化 #' + b.dataset.id; }
  });
}

function bindClusterCards(){
  document.querySelectorAll('#spClusters .sp-hatch-cluster').forEach(b => b.onclick = async () => {
    const ids = (b.dataset.ids || '').split(',').filter(Boolean).map(Number);
    if(!ids.length) return;
    b.disabled = true; b.textContent = '孵化中';
    try {
      let ok = 0, fail = 0;
      for(const id of ids){
        const r = await api('/api/sparks/' + id + '/hatch', {});
        if(r && r.ok) ok++; else fail++;
      }
      toast(`整簇孵化完成：${ok} 条成知识${fail ? `，${fail} 条跳过` : ''}`);
      await renderSparks();
    } catch(e){ toast('孵化失败'); }
    finally { b.disabled = false; b.textContent = '整簇孵化'; }
  });
}

// 随手记捕获（捕获盒静态，onclick 幂等，可随视图反复渲染重绑）
function bindSparkCapture(){
  const btn = $('spSave');
  if(!btn) return;
  btn.onclick = async () => {
    const content = ($('spContent').value || '').trim();
    if(!content){ alert('先写点什么再记。'); return; }
    const title = ($('spTitle').value || '').trim();
    const tags = ($('spTags').value || '').trim();
    btn.disabled = true; btn.textContent = '记录中';
    try {
      const r = await api('/api/sparks', {content, title, tags, source: 'manual'});
      if(r && r.ok){
        $('spContent').value = ''; $('spTitle').value = ''; $('spTags').value = '';
        toast('已记下'); await renderSparks();
      } else { toast('记录失败'); }
    } catch(e){ toast('记录失败'); }
    finally { btn.disabled = false; btn.textContent = '记下来'; }
  };
}
