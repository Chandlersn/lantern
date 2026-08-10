// 灯笼知识库 · reader —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 阅读（存与看协同） ---------------- */
let rdMode = 'preview';
let rdRev = null;   // 当前打开正文的内容版本指纹（乐观并发守卫用）
function renderRdPreview(content){
  // 轻量 Markdown 渲染（先整体转义防注入，再在转义文本上做解析）：
  // 标题 / 表格 / 列表 / 引用 / 围栏代码块 / 加粗 / 斜体 / 删除线 / 行内代码 / 链接
  const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const src = esc(content||'');
  if(!src.trim()) return '<p class="muted">（暂无内容）</p>';
  const lines = src.split('\n');
  const inline = s => s
    .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/~~([^~]+)~~/g,'<del>$1</del>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*([^*\n]+)\*/g,'<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  let html = '', i = 0;
  while(i < lines.length){
    const t = lines[i].trim();
    // 围栏代码块 ```...```
    if(/^```/.test(t)){
      const buf = [];
      i++;
      while(i < lines.length && !/^```/.test(lines[i].trim())){ buf.push(lines[i]); i++; }
      i++;
      html += '<pre><code>'+buf.join('\n')+'</code></pre>';
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
    if(hm){ const n = hm[1].length; html += `<h${n}>${inline(hm[2])}</h${n}>`; i++; continue; }
    // 中文常见小标题（很多文章不用 markdown，直接写「一、」「1、」「1.0版」「为什么……？」）：
    //   一、/（一）→ h3；1、/1.0版：/第X章 → h4；短问句 / 「xx——yy」破折号行 → h4
    const cn = t.match(/^[一二三四五六七八九十百]+、/) ||
               t.match(/^\d+、/) ||
               t.match(/^\d+(?:\.\d+)*\s*版/) ||
               t.match(/^第[0-9一二三四五六七八九十百]+[章节部分篇]/) ||
               t.match(/^（[一二三四五六七八九十百]+）/) ||
               t.match(/^[^\n]{1,28}[？?]$/) ||
               t.match(/^[^\n]{1,14}——[^\n]{0,22}$/);
    if(cn){
      const lv = (/^[一二三四五六七八九十百]+、/.test(t) || /^（[一二三四五六七八九十百]+）/.test(t)) ? 3 : 4;
      html += `<h${lv}>${inline(t)}</h${lv}>`;
      i++; continue;
    }
    // 引用块 > ...（行首 > 已被转义为 &gt;，用转义后的形式匹配）
    if(/^&gt;\s?/.test(t)){
      const buf = [];
      while(i < lines.length && /^&gt;\s?/.test(lines[i].trim())){ buf.push(lines[i].trim().replace(/^&gt;\s?/,'')); i++; }
      html += '<blockquote>'+buf.map(b=>'<p>'+inline(b)+'</p>').join('')+'</blockquote>';
      continue;
    }
    // 无序 / 有序列表
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
    ? ('本地文件：'+file+(r.file_exists?'':'（点「从文件重新载入」可生成）'))
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
  $('btnRdReload').onclick = async ()=>{
    const rr = await api('/api/kb/reload', {item_id: it.id});
    if(rr.ok){ alert('已从本地文件重新载入'); await load(); await openReader(it.id); }
    else alert('重新载入失败：'+(rr.msg||'未知错误'));
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
        // 后台 llm 整理通常数秒完成：若用户仍停在此文，过一会儿轻量重渲染一下来「默默替换」
        setTimeout(() => { if (curId === it.id) openReader(it.id); }, 2500);
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
    $('rdLinks').innerHTML = (out.length || back.length)
      ? '<label style="font-size:11px;">引用 / 被引用 · 作者手写的 [[...]] 双链（有正文事实依据）</label>' +
        (out.length? '<div class="chips" style="margin-top:4px;">'+out.map(o=>`<span class="tag">连 ${esc(o.title)}</span>`).join('')+'</div>' : '') +
        (back.length? '<div class="chips" style="margin-top:6px;">'+back.map(o=>`<span class="tag col">被 ${esc(o.title)} 引用</span>`).join('')+'</div>' : '')
      : '<span class="muted">这篇文章还没有用手写 [[...]] 引用其它条目——引用关系需要作者在正文里明确写出，不能由系统凭空生成。</span>';
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
          if(o.provenance === 'semantic'){ tag = '引擎推测·存疑'; basis = '嵌入相似度（暂不可信）'; }
          else if(o.provenance === 'bridge'){ tag = '跨主题桥接'; basis = '跨领域共核心概念'; }
          else { tag = '关键词共现'; basis = '正文共同提及的关键词'; }
        } else { tag = '位置相近'; basis = '双尺度定位接近'; }
        // 依据：引擎连线的证据（语义=相似度分数；共现/桥接=共享词），给事实来源，不下"引用"断言。
        // 语义类：嵌入相似度当前不可信（实测与真实词重叠矛盾），明确标注"仅推测、非事实关联"
        const ev = o.provenance === 'semantic'
          ? '引擎推测·相似度存疑（嵌入暂不可信，仅供参考，非事实关联）'
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
}

