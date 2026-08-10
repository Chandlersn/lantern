// 灯笼知识库 · knowledge —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 知识库 ---------------- */
let kbPage = 1;
const KB_PAGE_SIZE = 10;
function renderKbPager(totalPages){
  const box = $('kbPager'); if(!box) return;
  if(totalPages <= 1){ box.innerHTML = ''; return; }
  const pageBtn = (p, label) =>
    `<button class="pg${p===kbPage?' active':''}" data-p="${p}">${label}</button>`;
  let nums = [];
  if(totalPages <= 7){
    for(let p=1;p<=totalPages;p++) nums.push(pageBtn(p, p));
  } else {
    nums.push(pageBtn(1, 1));
    if(kbPage > 4) nums.push('<span class="pg-ell">…</span>');
    const lo = Math.max(2, kbPage-1), hi = Math.min(totalPages-1, kbPage+1);
    for(let p=lo;p<=hi;p++) nums.push(pageBtn(p, p));
    if(kbPage < totalPages-3) nums.push('<span class="pg-ell">…</span>');
    nums.push(pageBtn(totalPages, totalPages));
  }
  box.innerHTML = `<button class="pg" data-p="prev"${(kbPage===1)?' disabled':''}>上一页</button>`
    + nums.join('')
    + `<button class="pg" data-p="next"${(kbPage===totalPages)?' disabled':''}>下一页</button>`;
  box.querySelectorAll('button[data-p]').forEach(b=>{
    if(b.disabled) return;
    b.onclick=()=>{
      const v=b.dataset.p;
      if(v==='prev') kbPage=Math.max(1,kbPage-1);
      else if(v==='next') kbPage=Math.min(totalPages,kbPage+1);
      else kbPage=+v;
      renderKnowledge();
    };
  });
}
function renderKnowledge(){
  const tb = $('kbBody');
  const total = S.items.length;
  const totalPages = Math.max(1, Math.ceil(total / KB_PAGE_SIZE));
  if(kbPage > totalPages) kbPage = totalPages;
  const start = (kbPage - 1) * KB_PAGE_SIZE;
  const pageItems = total > KB_PAGE_SIZE ? S.items.slice(start, start + KB_PAGE_SIZE) : S.items;
  tb.innerHTML = pageItems.map(i=>{
    return `<tr data-id="${i.id}" class="${i.id===curId?'sel':''}">
      <td><b>${esc(i.title)}</b>${i.summary?`<div class="muted" style="font-weight:400;font-size:11px;margin-top:2px;">${esc(i.summary)}</div>`:''}</td>
      <td><span class="tag">${i.band}</span>${i.axis_domain?` <span class="tag">${esc(i.axis_domain)}</span>`:''}</td>
      <td>${i.main_pos}${i.revised?' *':''}</td>
      <td>${i.vernier}</td>
      <td>${i.offset>0?'+':''}${i.offset}</td>
      <td style="text-align:right;"><button class="soft tiny" data-del="${i.id}" title="删除这条">删除</button></td>
    </tr>`;
  }).join('');
  tb.querySelectorAll('tr').forEach(tr=>tr.onclick=e=>{
    if(e.target.closest('[data-del]')) return;      // 删除按钮不触发打开
    openReader(+tr.dataset.id);
  });
  tb.querySelectorAll('[data-del]').forEach(b=>b.onclick=async e=>{
    e.stopPropagation();
    const id = +b.dataset.del;
    const it = S.items.find(x=>x.id===id) || {};
    if(!await confirmBox(`确定删除「${it.title||id}」？\n\n它的分类、向量、互链、日志会从数据库永久移除；本地 .md 文档会移入系统回收站（可找回）。`, true)) return;
    b.disabled = true; b.textContent = '删除中';
    const r = await api('/api/kb/delete', {item_id:id});
    if(r.ok===false){ alert(r.msg||'删除失败'); b.disabled=false; b.textContent='删除'; return; }
    if(curId===id) curId = null;
    await load();
    alert(`已删除「${r.title}」`);
  });
  $('kbCount').textContent = `· 共 ${total} 条` + (total > KB_PAGE_SIZE ? ` · 第 ${kbPage}/${totalPages} 页` : '');
  renderKbPager(totalPages);
  // 检索页的 select 也会用到，顺带填充
  fillItemSelects(); populateTags();
  renderAxisChips();
}
function renderAxisChips(){
  const box=$('axisChips'); if(!box) return;
  const doms = (S.axis_domains||[]);
  box.innerHTML = doms.map(d=>`<span class="tag ${selAxis===d?'sel':''}" data-axis="${d}" style="cursor:pointer;">${d}</span>`).join('')
    || '<span class="muted">（暂无可选细分）</span>';
  box.querySelectorAll('[data-axis]').forEach(c=>c.onclick=()=>{
    selAxis = selAxis===c.dataset.axis ? null : c.dataset.axis;
    box.querySelectorAll('[data-axis]').forEach(x=>x.classList.toggle('sel', x===c && selAxis!==null));
  });
}


/* ---------------- 批量导入（选本地文件夹） ---------------- */
function renderImpOut(r){
  const box = $('impOut'); if(!box) return;
  const parts = [];
  if((r.imported||[]).length) parts.push('成功导入 ' + r.imported.length + ' 条');
  if((r.skipped||[]).length) parts.push('跳过重复 ' + r.skipped.length + ' 条');
  if((r.failed||[]).length) parts.push('失败 ' + r.failed.length + ' 条');
  box.innerHTML = '<div class="note">' + (parts.join(' · ') || (r.msg || '没有可导入的内容')) + '</div>' +
    ((r.failed||[]).length
      ? '<div class="edge">' + r.failed.map(f =>
          '<div class="muted" style="font-size:11.5px;">' + esc(f.title) + '：' + esc(f.msg) + '</div>').join('') + '</div>'
      : '');
}
function readFile(f){
  return new Promise((res, rej)=>{
    if(typeof f.text === 'function'){ f.text().then(res, rej); return; }
    const rd = new FileReader();
    rd.onload = ()=>res(rd.result);
    rd.onerror = ()=>rej(rd.error || new Error('读取失败'));
    rd.readAsText(f, 'utf-8');
  });
}
function entryFromFile(name, text){
  // 文件首行是 # 标题 → 用它当标题；否则用文件名（去扩展名）
  const lines = (text||'').split('\n');
  const m = lines[0] && lines[0].trim().match(/^#{1,6}\s+(.+)$/);
  if(m) return {title: m[1].trim(), content: lines.slice(1).join('\n').trim()};
  return {title: name.replace(/\.(md|markdown|txt|text)$/i, ''), content: (text||'').trim()};
}
async function importFolder(files){
  const texts = files.filter(f=>/\.(md|markdown|txt|text)$/i.test(f.name));
  if(!texts.length){ renderImpOut({failed:[{title:'文件夹', msg:'里面没有 .md/.txt 文件'}]}); return; }
  const btn = $('btnImpFolder'), old = btn.textContent;
  btn.disabled = true;
  const merged = {ok:true, imported:[], skipped:[], failed:[]};
  const BATCH = 20;
  for(let s = 0; s < texts.length; s += BATCH){
    const batch = texts.slice(s, s + BATCH), entries = [];
    for(const f of batch){
      try{ entries.push(entryFromFile(f.name, await readFile(f))); }
      catch(e){ merged.failed.push({title: f.name, msg: '读取失败'}); }
    }
    btn.textContent = `导入中 ${Math.min(s + BATCH, texts.length)}/${texts.length}…`;
    const r = await api('/api/kb/import', {entries});
    merged.imported.push(...(r.imported||[]));
    merged.skipped.push(...(r.skipped||[]));
    merged.failed.push(...(r.failed||[]));
  }
  btn.disabled = false; btn.textContent = old;
  renderImpOut(merged);
  await load(); populateTags();
  if(merged.imported.length) alert(`已从文件夹导入 ${merged.imported.length} 条知识。`);
  else if(merged.failed.length) alert('没有可导入的内容，详见下方明细。');
  else alert('文件夹里的内容都已存在（标题重复）。');
}
$('btnImpFolder').onclick = ()=>{
  $('impPick').textContent = '';
  $('impFiles').click();
};
$('impFiles').onchange = e=>{
  const files = [...(e.target.files||[])];
  if(!files.length) return;
  $('impPick').textContent = `已选 ${files.length} 个文件`;
  importFolder(files);
  e.target.value = '';                       // 允许再次选择同一文件夹
};
