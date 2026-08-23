// 灯笼知识库 · reader —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 阅读（存与看协同） ---------------- */
let rdMode = 'preview';
let rdRev = null;   // 当前打开正文的内容版本指纹（乐观并发守卫用）
// 大纲收集器（每次渲染重置）：[{id,text,lv}]
let rdToc = [];
function slugify(s, used){
  // 标题文本 → 稳定且唯一的锚点 id（含中文也能用，但不依赖中文做 id 可读性）
  let base = (s||'').toLowerCase().replace(/[^\w一-龥]+/g,'-').replace(/^-+|-+$/g,'').slice(0,40) || 'h';
  let id = base, n = 2;
  while(used.has(id)){ id = base + '-' + n; n++; }
  used.add(id);
  return id;
}
// 数字序列开头的「短标题」判定：1、 / 1. / 1.2. 这类前缀。
// 必须是不成句的简短短语（≤30字且整行无句末标点。！？）才算标题；
// 长句或带句末标点的段落不当标题，避免把正文长句误加粗成小标题。
function isShortNumberedHeading(t){
  if(/^\d+(?:\.\d+)*\s*版/.test(t)) return false;   // 版号（1.0版：）交给专门的版号规则
  const m = t.match(/^\d+(?:\.\d+)*[、.]\s*(.*)$/);
  if(!m) return false;
  const rest = m[1] || "";
  if(t.length > 30) return false;                       // 超长 → 不是标题
  if(/[。！？!?]$/.test(t)) return false;               // 以句末标点收尾 → 是句子不是标题
  if(/[。！？!?]/.test(rest)) return false;             // 行内已含句末标点 → 多句/长句
  return true;
}
function renderRdPreview(content){
  // 轻量 Markdown 渲染（先整体转义防注入，再在转义文本上做解析）：
  // 标题 / 表格 / 列表 / 引用 / 围栏代码块 / 加粗 / 斜体 / 删除线 / 行内代码 / 链接 / 图片
  rdToc = [];
  const used = new Set();
  const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const src = esc(content||'');
  if(!src.trim()) return '<p class="muted">（暂无内容）</p>';
  const lines = src.split('\n');
  const inline = s => s
    .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/~~([^~]+)~~/g,'<del>$1</del>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*([^*\n]+)\*/g,'<em>$1</em>')
    // 图片 ![alt](src)：src 可为 http(s) 或本地相对路径（相对 /articles/ 目录）
    .replace(/!\[([^\]]*)\]\(((?:https?:\/\/|\.\.?\/|\/)[^)\s]*)\)/g,
      (m,alt,src2)=>`<img alt="${alt}" src="${src2}" loading="lazy">`)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  let html = '', i = 0;
  const emitHeading = (lv, text)=>{
    const id = slugify(text.replace(/<[^>]+>/g,''), used);
    rdToc.push({id, text: text.replace(/<[^>]+>/g,''), lv});
    html += `<h${lv} id="${id}">${text}</h${lv}>`;
  };
  while(i < lines.length){
    const t = lines[i].trim();
    // 围栏代码块 ```...```（可选语言：```js）
    if(/^```/.test(t)){
      const lang = t.replace(/^```/,'').trim();
      const buf = [];
      i++;
      while(i < lines.length && !/^```/.test(lines[i].trim())){ buf.push(lines[i]); i++; }
      i++;
      const code = buf.join('\n');
      const copyBtn = `<div class="rd-pre__bar"><button class="rd-pre__copy" type="button" data-code="${encodeURIComponent(code)}">复制</button></div>`;
      html += `<div class="rd-pre">${copyBtn}<pre><code>${code}</code></pre></div>`;
      continue;
    }
    // 表格块：| a | b |  + 分隔行 |---|---|
    if(/^\|.*\|\s*$/.test(t) && i+1 < lines.length && /^\|[\s:|-]+\|\s*$/.test(lines[i+1].trim())){
      const header = t.replace(/^\||\|$/g,'').split('|').map(s=>s.trim());
      const rows = [];
      i += 2;
      while(i < lines.length && /^\|.*\|\s*$/.test(lines[i].trim())){
        rows.push(lines[i].replace(/^\||\|$/g,'').split('|').map(s=>s.trim()));
        i++;
      }
      html += '<table><thead><tr>'+header.map(h=>'<th>'+inline(h)+'</th>').join('')+'</tr></thead>'+
        (rows.length ? '<tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>').join('')+'</tbody>' : '')+'</table>';
      continue;
    }
    // 标题 # ~ ######
    const hm = t.match(/^(#{1,6})\s+(.*)$/);
    if(hm){ emitHeading(hm[1].length, inline(hm[2])); i++; continue; }
    // 中文常见小标题（很多文章不用 markdown，直接写「一、」「1、」「1.0版」「为什么……？」）：
    //   一、/（一）→ h3；1、/1.0版：/第X章 → h4；短问句 / 「xx——yy」破折号行 → h4
    // 数字序列（1、 / 1. ）须是「简短句式」才算标题：长度 ≤30 且整行无句末标点
    //（不成句的短语），长句或带。！？的段落不当标题（避免把正文长句误加粗）。
    const cn = t.match(/^[一二三四五六七八九十百]+、/) ||
               t.match(/^\d+(?:\.\d+)*\s*版/) ||
               t.match(/^第[0-9一二三四五六七八九十百]+[章节部分篇]/) ||
               t.match(/^（[一二三四五六七八九十百]+）/) ||
               t.match(/^[^\n]{1,28}[？?]$/) ||
               t.match(/^[^\n]{1,14}——[^\n]{0,22}$/) ||
               isShortNumberedHeading(t);
    if(cn){
      const lv = (/^[一二三四五六七八九十百]+、/.test(t) || /^（[一二三四五六七八九十百]+）/.test(t)) ? 3 : 4;
      emitHeading(lv, inline(t));
      i++; continue;
    }
    // 引用块 > ...（行首 > 已被转义为 &gt;，用转义后的形式匹配）
    if(/^&gt;\s?/.test(t)){
      const buf = [];
      while(i < lines.length && /^&gt;\s?/.test(lines[i].trim())){ buf.push(lines[i].trim().replace(/^&gt;\s?/,'')); i++; }
      html += '<blockquote>'+buf.map(b=>'<p>'+inline(b)+'</p>').join('')+'</blockquote>';
      continue;
    }
    // 无序 / 有序列表（数字序列若不是短标题才走这里；短标题已在上面 emitHeading）
    const ulm = t.match(/^[-*]\s+(.*)$/), olm = t.match(/^\d+\.\s+(.*)$/);
    if(ulm || olm){
      const tag = ulm ? 'ul' : 'ol', items = [];
      while(i < lines.length){
        const t2 = lines[i].trim();
        const m2 = ulm ? t2.match(/^[-*]\s+(.*)$/) : t2.match(/^\d+\.\s+(.*)$/);
        if(!m2) break;
        items.push('<li>'+inline(m2[1])+'</li>');
        i++;
      }
      html += `<${tag}>`+items.join('')+`</${tag}>`;
      continue;
    }
    if(!t){ i++; continue; }
    // 普通段落（连续非空行，遇块级标记停）
    const buf = [lines[i]];
    i++;
    while(i < lines.length && lines[i].trim()){
      const nx = lines[i].trim();
      if(/^(#{1,6})\s/.test(nx) || /^[-*]\s/.test(nx) || /^\d+\.\s/.test(nx) ||
         /^&gt;\s?/.test(nx) || /^\|.*\|\s*$/.test(nx) || /^```/.test(nx)) break;
      buf.push(lines[i]); i++;
    }
    html += '<p>'+inline(buf.join('<br>'))+'</p>';
  }
  return html;
}
function setRdMode(m){
  rdMode = m;
  $('rdPreview').style.display = (m==='preview') ? '' : 'none';
  $('rdHint').style.display = (m==='preview') ? '' : 'none';
  const toc = $('rdToc'); if(toc) toc.style.display = (m==='preview' && rdToc.length) ? '' : 'none';
  $('rdEdit').style.display = (m==='edit') ? '' : 'none';
  $('btnRdMode').textContent = (m==='preview') ? '切换到编辑' : '切换到预览';
  if(m==='edit'){ try{ $('rdBody').focus(); }catch(e){} }
}
function bindResultClicks(boxId){
  $(boxId).querySelectorAll('[data-id]').forEach(el=>el.onclick=()=>openReader(+el.dataset.id));
}
async function openReader(id){
  curId = id;
  window._pendingGraphFocus = id;   // 进入图谱时聚焦此节点（高亮邻居、虚化非邻居）
  selectView('reader');
}
async function renderReader(){
  const it = cur();
  if(!it){ $('rdTitle').textContent='（没有可阅读的内容）'; return; }
  let r = {};
  try { r = await api('/api/kb/article?id='+it.id); } catch(e){ r = {}; }
  const title = r.title || it.title || '';
  const content = (r.content != null ? r.content : (it.content || it.excerpt || ''));
  const file = r.file || '';
  rdRev = r.rev || null;   // 记下打开时正文版本，保存时回传做并发守卫
  $('rdTitle').textContent = title;
  $('rdTitleEdit').value = title;
  $('rdBody').value = content;
  $('rdPreview').innerHTML =
    (it.summary ? `<div class="rd-sum">一句话：${esc(it.summary)}</div>` : '') +
    renderRdPreview(content);
  $('rdPreview').ondblclick = ()=>setRdMode('edit');
  rewriteRdImages(it.id);        // 正文内相对图片路径 → 后端 asset 接口（受控、防穿越）
  renderRdToc();                 // 右侧浮动大纲（基于本次渲染收集到的标题）
  bindRdCopyBtns();              // 代码块「复制」按钮
  setRdMode('preview');
  $('rdChips').innerHTML =
    `<span class="tag">${it.band}</span>`+
    `<span class="tag">位置 ${it.main_pos}</span>`+
    `<span class="tag">严密度 ${it.vernier}</span>`+
    `<span class="tag">偏差 ${it.offset>0?'+':''}${it.offset}</span>`+
    (r.file_exists
      ? `<span class="tag">本地文件已同步</span>`
      : `<span class="tag">本地文件待生成</span>`);
  $('rdPath').textContent = file
    ? ('本地文件：'+file+(r.file_exists?'':'（本地文件待生成，保存后生成）'))
    : '';
  $('btnRdLocate').onclick = ()=>selectView('visualize');   // 「看偏差」：进入偏差地图并聚焦本篇
  $('btnRdCopy').onclick = async ()=>{
    if(!file){ toast('这篇还没有对应的本地文件'); return; }
    try{
      const r = await api('/api/kb/open_folder', {item_id: it.id});
      if(r && r.ok){ toast('已打开本地文件夹'); }
      else toast('打开失败：'+(r&&r.msg||'未知错误'));
    }catch(e){ toast('打开失败'); }
  };
  $('btnRdMode').onclick = ()=>setRdMode(rdMode==='preview'?'edit':'preview');
  $('btnRdCancel').onclick = ()=>setRdMode('preview');
  $('btnRdDelete').onclick = async ()=>{
    if(!confirm(`确定删除《${title}》吗？\n\n数据库记录将永久删除、不可找回；本地 .md 文件会移入系统回收站（可找回）。`)){
      return;
    }
    const rr = await api('/api/kb/delete', {item_id: it.id});
    if(rr.ok){ toast('已删除《'+title+'》'); await load(); selectView('knowledge'); }
    else alert('删除失败：'+(rr.msg||'未知错误'));
  };
  $('btnRdSave').onclick = async ()=>{
    const t = $('rdTitleEdit').value.trim(), c = $('rdBody').value.trim();
    if(!c){ alert('正文不能为空'); return; }
    const btn = $('btnRdSave');
    btn.disabled = true; btn.textContent = '保存中…';
    try {
      const rr = await api('/api/kb/update', {item_id: it.id, title:t, content:c, rev: rdRev});
      if(rr.ok){
        // 后端已秒回（启发式落库），llm 重算在后台默默跑；前端只局部刷新，不整页重载
        it.title = t;                         // 让知识列表立即反映新标题
        await openReader(it.id);              // 仅重渲染当前 reader（1 次轻量往返，rev 同步刷新）
        // 后台 llm 整理通常数秒完成：若用户仍处于「编辑态」且仍停在此文，过一会儿轻量重渲染一下来「默默替换」；
        // 若用户只是只读浏览，则只静默刷新 chips/摘要/关联（不动正文预览、不丢滚动位置）。
        setTimeout(() => {
          if (curId !== it.id) return;
          if (rdMode === 'edit') { openReader(it.id); }
          else { syncRdMetaOnly(it.id); }
        }, 2500);
      } else if(rr.conflict){
        // 乐观并发冲突：自打开后正文已被其它改动更新，把抉择权交回用户
        if(confirm('正文版本冲突：自你打开后，内容已被其它改动更新。\n\n'
                   + '点「确定」载入最新内容继续编辑；点「取消」放弃本次保存。')){
          await openReader(it.id);            // 重新载入最新（含新 rev）
          setRdMode('edit');
        }
      } else {
        alert('保存失败：'+(rr.msg||'未知错误'));
      }
    } finally {
      btn.disabled = false; btn.textContent = '保存';
    }
  };
  // ---- 关联（展示为主，连接由智能助手维护） ----
  const tags = String(it.tags||'').split(',').map(s=>s.trim()).filter(Boolean);
  $('rdTags').innerHTML = tags.length
    ? `<label style="font-size:11px;">话题</label><div class="chips" style="margin-top:4px;">${tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>`
    : '';
  const renderRdLinks = ()=>{
    const out = (r.outlinks||[]), back = (r.backlinks||[]);
    // 出链 / 入链按 id 合并去重：双向互链只列一次，去掉「连 / 被引用」冗余措辞
    const rel = new Map();
    for (const o of out)  if (o && o.id != null) rel.set(o.id, o.title);
    for (const o of back) if (o && o.id != null) rel.set(o.id, o.title);
    $('rdLinks').innerHTML = rel.size
      ? '<label style="font-size:11px;">互链（智能助手织入）</label>' +
        '<div class="chips" style="margin-top:4px;">' +
        [...rel.entries()].map(([id,t])=>`<span class="tag">${esc(t)}</span>`).join('') +
        '</div>'
      : '<span class="muted">这篇文章还没有被织入 [[...]] 互链——这类确定的引用关系由智能助手在加工知识库时自动建立（而非凭空猜测）。</span>';
  };
  renderRdLinks();
  const renderRdRelated = async ()=>{
    const box = $('rdRelated');
    box.innerHTML = '<div class="muted">正在找…</div>';
    try{
      // 优先：图谱里引擎连上的「相邻知识」（语义/桥接/共现）——这些是相似关系，不是引用
      let r = await api('/api/kb/linked_neighbors', {item_id: it.id, k: 8});
      let ns = (r.neighbors||[]).filter(o => o.kind !== 'hard'), source = 'link';
      if(!ns.length){
        // 兜底：尚未被引擎连上的，按双尺度位置找最近邻
        const rp = await api('/api/kb/neighbors', {item_id: it.id, k: 5});
        ns = (rp.neighbors||[]).slice(0,5); source = 'pos';
      }
      if(!ns.length){ box.innerHTML = '<span class="muted">库里的知识还太少，暂时找不出相近的。</span>'; return; }
      box.innerHTML = ns.map(o=>{
        let tag, basis;
        if(source === 'link'){
          if(o.provenance === 'semantic'){ tag = '引擎语义关联'; basis = '嵌入语义相似'; }
          else if(o.provenance === 'bridge'){ tag = '跨主题桥接'; basis = '跨领域共核心概念'; }
          else { tag = '关键词共现'; basis = '正文共同提及的关键词'; }
        } else { tag = '位置相近'; basis = '双尺度定位接近'; }
        // 依据：引擎连线的证据（语义=相似度分数；共现/桥接=共享词），给事实来源，不下"引用"断言。
        const ev = o.provenance === 'semantic'
          ? '引擎语义关联（嵌入相似，信号已恢复可信）'
          : ((o.evidence && o.evidence.length) ? o.evidence.join('、') : basis);
        return `<div class="edge clickable" data-id="${o.id}" style="padding:7px 8px;margin:0 -8px;">
          <div style="display:flex;align-items:baseline;gap:6px;">
            <span class="tag">${tag}</span>
            <b style="color:var(--ink);flex:1;min-width:0;">${esc(o.title)}</b>
            <span class="muted" style="font-size:11px;white-space:nowrap;">${esc(o.band||'')}</span>
          </div>
          <div class="muted" style="font-size:11px;margin-top:2px;padding-left:2px;">依据：${esc(ev)}</div>
        </div>`;
      }).join('');
      bindResultClicks('rdRelated');
    }catch(e){ box.innerHTML = '<span class="muted">暂时找不出相近的。</span>'; }
  };
  renderRdRelated();
  // ---- 插入互链（[[...]] 双链，催生 AI 织入硬链/蓝实线） ----
  $('btnRdLink').onclick = ()=>openRdLinkModal();
  $('rdLinkClose').onclick = ()=>closeRdLinkModal();
  $('rdLinkModal').onclick = (e)=>{ if(e.target===$('rdLinkModal')) closeRdLinkModal(); };
}

// 在光标处插入文本（用于插入 [[标题]] 互链标记）
function insertAtCursor(el, text){
  const s = (el.selectionStart != null) ? el.selectionStart : el.value.length;
  const e = (el.selectionEnd != null) ? el.selectionEnd : el.value.length;
  el.value = el.value.slice(0, s) + text + el.value.slice(e);
  el.selectionStart = el.selectionEnd = s + text.length;
  el.focus();
}
// 打开「插入互链」弹窗：列出全部条目（可搜索），选中即在正文光标处插入 [[标题]]
function openRdLinkModal(){
  const box = $('rdLinkList');
  const items = (S.items || []).filter(i => i.id !== curId);
  const render = (q)=>{
    q = (q || '').trim().toLowerCase();
    const list = q ? items.filter(i => (i.title || '').toLowerCase().includes(q)) : items;
    if(!list.length){ box.innerHTML = '<div class="rd-link-empty muted">没有匹配的条目</div>'; return; }
    box.innerHTML = list.map(i =>
      `<div class="rd-link-item" data-title="${esc(i.title)}"><span>${esc(i.title)}</span><span class="muted">${esc(i.band || '')}</span></div>`
    ).join('');
    box.querySelectorAll('.rd-link-item').forEach(el=>{
      el.onclick = ()=>{ insertAtCursor($('rdBody'), `[[${el.dataset.title}]]`); closeRdLinkModal(); };
    });
  };
  render('');
  const modal = $('rdLinkModal');
  modal.setAttribute('aria-hidden', 'false');
  const inp = $('rdLinkSearch');
  inp.value = ''; inp.oninput = ()=>render(inp.value);
  setTimeout(()=>inp.focus(), 0);
}
function closeRdLinkModal(){ $('rdLinkModal').setAttribute('aria-hidden', 'true'); }

// ---- 预览增强：右侧浮动大纲 + 代码块复制 + 只读态静默元数据刷新 ----

// 把正文里的相对图片路径改写成受控的 /api/kb/asset 接口（防目录穿越，支持本地配图）
function rewriteRdImages(itemId){
  document.querySelectorAll('#rdPreview img').forEach(img=>{
    const src = img.getAttribute('src') || '';
    if(/^(https?:|data:|\/api\/)/i.test(src)) return;   // 外链 / dataURI / 已改写 跳过
    const rel = src.replace(/^\.\//, '');               // 去掉开头的 ./
    img.setAttribute('src', '/api/kb/asset?id=' + encodeURIComponent(itemId) + '&path=' + encodeURIComponent(rel));
  });
}

// 把本次 renderRdPreview 收集的标题渲染成大纲；空则隐藏栏
function renderRdToc(){
  const box = $('rdToc');
  if(!box) return;
  if(!rdToc.length){ box.style.display = 'none'; box.innerHTML = ''; return; }
  box.style.display = '';
  box.innerHTML = '<div class="rd-toc__title">本文大纲</div>' +
    rdToc.map(h => `<a href="#${h.id}" class="lv${h.lv}" data-anchor="${h.id}">${esc(h.text)}</a>`).join('');
  box.querySelectorAll('a').forEach(a=>{
    a.onclick = (e)=>{
      e.preventDefault();
      const el = document.getElementById(a.dataset.anchor);
      if(el){ el.scrollIntoView({behavior:'smooth', block:'start'}); }
    };
  });
  bindRdTocScroll();
}
// 大纲滚动高亮当前章节（preview 区在页面内滚动，监听 window scroll）
let rdTocScrollBound = false;
function bindRdTocScroll(){
  if(rdTocScrollBound) return;
  rdTocScrollBound = true;
  window.addEventListener('scroll', ()=>{
    const box = $('rdToc'); if(!box || box.style.display === 'none') return;
    const heads = rdToc.map(h=>document.getElementById(h.id)).filter(Boolean);
    if(!heads.length) return;
    let active = heads[0].id;
    const y = window.scrollY + 120;
    for(const h of heads){ if(h.offsetTop <= y) active = h.id; else break; }
    box.querySelectorAll('a').forEach(a=>a.classList.toggle('active', a.dataset.anchor === active));
  }, {passive:true});
}
// 代码块「复制」按钮：data-code 存了 encodeURIComponent 后的原文
function bindRdCopyBtns(){
  document.querySelectorAll('#rdPreview .rd-pre__copy').forEach(btn=>{
    btn.onclick = async ()=>{
      const code = decodeURIComponent(btn.dataset.code || '');
      try{
        if(navigator.clipboard && navigator.clipboard.writeText){
          await navigator.clipboard.writeText(code);
        } else {
          const ta = document.createElement('textarea'); ta.value = code;
          document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
        }
        const old = btn.textContent; btn.textContent = '已复制'; btn.disabled = true;
        setTimeout(()=>{ btn.textContent = old; btn.disabled = false; }, 1200);
      }catch(e){ toast('复制失败'); }
    };
  });
}
// 只读态：后台 llm 整理完成后只刷新顶部 chips / 摘要 / 关联，不动正文预览、不丢滚动位置
async function syncRdMetaOnly(id){
  try{
    const r = await api('/api/kb/article?id='+id);
    if(r && r.summary != null){
      const sumEl = $('rdPreview').querySelector('.rd-sum');
      const html = r.summary ? `<div class="rd-sum">一句话：${esc(r.summary)}</div>` : '';
      if(sumEl) sumEl.outerHTML = html; else if(html) $('rdPreview').insertAdjacentHTML('afterbegin', html);
    }
    // chips / 路径（基于 cur() 数据，不重刷正文）
    const it = cur(); if(!it) return;
    $('rdChips').innerHTML =
      `<span class="tag">${it.band}</span>`+
      `<span class="tag">位置 ${it.main_pos}</span>`+
      `<span class="tag">严密度 ${it.vernier}</span>`+
      `<span class="tag">偏差 ${it.offset>0?'+':''}${it.offset}</span>`+
      (r.file_exists ? `<span class="tag">本地文件已同步</span>` : `<span class="tag">本地文件待生成</span>`);
  }catch(e){ /* 静默失败，不影响阅读 */ }
}


