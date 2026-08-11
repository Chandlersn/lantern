// 灯笼知识库 · sparks —— 灵感碎片（原料层）视图：随手记捕获 / 列表 / 聚类萌发 / 孵化
async function renderSparks(){
  const [list, cl] = await Promise.all([
    api('/api/sparks'), api('/api/sparks/clusters')
  ]);
  // 列表
  const items = (list && list.items) || [];
  sparkCache = {};
  items.forEach(it => { sparkCache[it.id] = it; });
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

// 双击编辑用：缓存当前列表数据，避免从渲染后的 HTML 反向解析
let sparkCache = {};
function escAttr(s){
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
  const cardCls = sp.hatched_item_id ? 'det-card sp-card sp-card--hatched' : 'det-card sp-card sp-card--raw';
  return `<div class="${cardCls}" data-id="${sp.id}" data-item="${sp.hatched_item_id||''}">
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
    const card = b.closest('.sp-card');
    b.disabled = true; b.textContent = '创作中';
    try {
      const r = await api('/api/sparks/' + id + '/draft', {});
      if(r && r.ok){ renderDraftEditor(card, r); }
      else { toast((r && r.msg) ? r.msg : '生成草稿失败'); await renderSparks(); }
    } catch(e){ toast('生成草稿失败'); await renderSparks(); }
  });
  document.querySelectorAll('#spList .sp-del').forEach(b => b.onclick = async () => {
    if(!(await confirmBox('确定删除这条灵感碎片？此操作不可恢复。', true))) return;
    const r = await api('/api/sparks/' + b.dataset.id + '/delete', {});
    if(r && r.ok){ toast('已删除'); await renderSparks(); }
  });
  document.querySelectorAll('#spList .sp-view').forEach(b => b.onclick = () => {
    if(typeof openReader === 'function') openReader(parseInt(b.dataset.id, 10));
  });
  // 双击：所有灵感碎片卡片都在当前页面就地进入编辑状态（不再跳转阅读页）；
  // 已孵化碎片想看对应知识条目，用卡片上的「查看条目」按钮。
  document.querySelectorAll('#spList .sp-card').forEach(card => {
    card.ondblclick = () => {
      const id = parseInt(card.dataset.id, 10);
      if(!isNaN(id)) startEdit(id);
    };
  });
}

// 碰撞创作草稿编辑器：孵化阶段一返回的 proposal 在此内联渲染，用户可微调正文/标题，
// 点「确认入库」调 /commit 走阶段二（六阶段落地）；取消则恢复原卡片。
function renderDraftEditor(card, r){
  const merged = r.decision === 'merged';
  const rel = (r.related_items || []).map(it =>
    `<li><b>#${it.id}</b> ${esc(it.title || '')} <span class="muted">· 相关度 ${it.score}</span>
      <div class="muted" style="margin-top:2px;">${esc((it.excerpt || '').slice(0, 100))}</div></li>`).join('');
  const mergeNote = merged
    ? `将【并入】已有条目《${esc(r.merge_target_title || '')}》 #${r.merge_target_id}（保留其双尺定位，下方草稿作为补充内容追加）`
    : `将【新建】为独立知识条目（下方草稿作为正文）`;
  const terms = (r.cluster_terms || []).map(t => `<span class="tag col">${esc(t)}</span>`).join('');
  card.innerHTML = `<div class="sp-draft">
    <div class="sp-head"><b>碰撞创作草稿</b>
      <span class="pill ${merged ? 'warn' : 'llm'}">${merged ? '将合并' : '将新建'}</span></div>
    <div class="sp-body">
      <div class="sp-draft-meta">${mergeNote}</div>
      ${terms ? `<div class="sp-tags" style="margin-top:4px;">来源簇主题：${terms}</div>` : ''}
      ${rel ? `<details class="sp-rel"><summary>知识库相关素材（${r.related_items.length}）</summary><ul class="sp-rel-list">${rel}</ul></details>` : ''}
      <textarea class="sp-draft-area" spellcheck="false" placeholder="AI 结合知识库相关内容创作的草稿，可在此微调后确认入库">${esc(r.draft || '')}</textarea>
    </div>
    <div class="sp-acts">
      <input class="sp-draft-title" type="text" value="${escAttr(r.title || '')}" placeholder="标题（可选）" style="flex:1;min-width:140px;" />
      <button class="soft sp-draft-cancel">取消</button>
      <button class="sp-draft-confirm" data-id="${r.spark_id}">确认入库</button>
    </div>
  </div>`;
  const ta = card.querySelector('.sp-draft-area');
  const titleInput = card.querySelector('.sp-draft-title');
  card.querySelector('.sp-draft-cancel').onclick = () => renderSparks();
  card.querySelector('.sp-draft-confirm').onclick = async (e) => {
    const btn = e.currentTarget;
    const draft = (ta.value || '').trim();
    const title = (titleInput.value || '').trim();
    if(!draft){ toast('草稿内容不能为空'); return; }
    btn.disabled = true; btn.textContent = '入库中';
    try {
      const rr = await api(`/api/sparks/${r.spark_id}/commit`, {content: draft, title, axis_domain: r.axis_domain});
      if(rr && rr.ok){ showHatchReport(rr); await renderSparks(); }
      else toast((rr && rr.msg) || '入库失败');
    } catch(err){ toast('入库失败'); }
    finally { btn.disabled = false; btn.textContent = '确认入库'; }
  };
  if(ta) ta.focus();
}

// 双击进入内联编辑：标题/正文/标签就地改，保存调用 /api/sparks/<id>/update
function startEdit(id){
  const sp = sparkCache[id];
  const card = document.querySelector(`#spList .sp-card[data-id="${id}"]`);
  if(!sp || !card || card.classList.contains('sp-editing')) return;
  card.classList.add('sp-editing');
  card.innerHTML =
    `<div class="sp-edit">
       <input class="sp-edit-title" type="text" value="${escAttr(sp.title||'')}" placeholder="标题（可选，不填取首句）" />
       <textarea class="sp-edit-content" placeholder="想法内容">${esc(sp.content||'')}</textarea>
       <input class="sp-edit-tags" type="text" value="${escAttr((sp.tags||[]).join(','))}" placeholder="标签，逗号分隔（可选）" />
       <div class="sp-acts">
         <button class="soft sp-edit-cancel">取消</button>
         <button class="sp-edit-save">保存</button>
       </div>
     </div>`;
  const saveBtn = card.querySelector('.sp-edit-save');
  const cancelBtn = card.querySelector('.sp-edit-cancel');
  cancelBtn.onclick = () => renderSparks();
  saveBtn.onclick = async () => {
    const content = (card.querySelector('.sp-edit-content').value || '').trim();
    const title = (card.querySelector('.sp-edit-title').value || '').trim();
    const tags = (card.querySelector('.sp-edit-tags').value || '').trim();
    if(!content){ toast('内容不能为空'); return; }
    saveBtn.disabled = true; saveBtn.textContent = '保存中';
    try {
      const r = await api(`/api/sparks/${id}/update`, {content, title, tags});
      if(r && r.ok){ toast('已保存'); await renderSparks(); }
      else toast((r && r.msg) || '保存失败');
    } catch(e){ toast('保存失败'); }
    finally { saveBtn.disabled = false; saveBtn.textContent = '保存'; }
  };
  const eta = card.querySelector('.sp-edit-content');
  const autoGrow = () => { eta.style.height = 'auto'; eta.style.height = Math.min(eta.scrollHeight, 560) + 'px'; };
  eta.addEventListener('input', autoGrow);
  autoGrow();
  eta.focus();
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
  const cap = $('spContent');
  if(cap){
    const grow = () => { cap.style.height = 'auto'; cap.style.height = Math.min(Math.max(cap.scrollHeight, 120), 320) + 'px'; };
    cap.onfocus = grow;
    cap.oninput = grow;
    cap.onblur = () => { if(!cap.value.trim()) cap.style.height = ''; };
  }
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
