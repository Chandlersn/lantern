// 灯笼知识库 · search —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 共享：可视化面板条目列表（被 visualize.js / knowledge.js 复用，勿删） ---------------- */
// 『两项判断』条目选择列表：筛选输入框 + 可滚动点击列表（按标题/领域/学科域实时过滤）
function fillVizList(filter){
  const box = $('vList'); if(!box) return;
  const q = (filter==null ? ($('vFilter') ? $('vFilter').value : '') : filter).trim().toLowerCase();
  const items = S.items.filter(i=>{
    if(!q) return true;
    return (`${i.title||''} ${i.band||''} ${i.axis_domain||''}`).toLowerCase().includes(q);
  });
  if(!items.length){ box.innerHTML = '<div class="viz-empty">没有匹配的条目</div>'; box.style.maxHeight=''; return; }
  box.innerHTML = items.map(i=>
    `<div class="viz-item${i.id===curId?' on':''}" data-id="${i.id}" title="${esc(i.title)}">
       <span class="viz-title">${esc(i.title)}</span>
       <span class="tag">${esc(i.band||'—')}</span>
     </div>`).join('');
  capVizList(box);
}

// 两项判断条目列表：默认只露 7 行，多余靠滚轮滚动（按真实行高精确裁切，不因字体度量猜测）
const VIZ_LIST_CAP = 7;
function capVizList(box){
  if(!box) return;
  const rows = box.querySelectorAll('.viz-item');
  if(rows.length <= VIZ_LIST_CAP){ box.style.maxHeight=''; return; }
  const h = rows[0].getBoundingClientRect().height;     // 单行高度（含自身盒）
  const pad = parseFloat(getComputedStyle(box).paddingTop) + parseFloat(getComputedStyle(box).paddingBottom);
  box.style.maxHeight = (h * VIZ_LIST_CAP + pad) + 'px';
}
// 旧搜索「相似」用的条目下拉已随面板删除；此处仅保留对可视化面板的副作用（填充 vList），并对缺失元素空安全。
function fillItemSelects(){
  const sel = $('nSel');               // 搜索抽屉「相似」面板已移除，元素可能不存在
  if(sel) sel.innerHTML = S.items.map(i=>`<option value="${i.id}" ${i.id===curId?'selected':''}>${i.title}</option>`).join('');
  fillVizList();
}
// 旧搜索「筛选」用的领域下拉已随面板删除；空安全，避免可视化面板调用时报错。
function populateBand(){
  const el = $('dBand'); if(!el) return;
  const cnt = {};
  (S.items||[]).forEach(i=>{ cnt[i.band]=(cnt[i.band]||0)+1; });
  const names = Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a] || a.localeCompare(b,'zh'));
  el.innerHTML = '<option value="">（不限）</option>' +
    names.map(n=>`<option value="${esc(n)}">${esc(n)} (${cnt[n]})</option>`).join('');
}

/* ---------------- 搜索抽屉（右侧滑入竖向，虚化主页，参考工作台） ---------------- */
let qMode = 'kw';            // kw 关键词 / sem 按意思 / frag 定位段落
let groupByBand = false;     // 非线性索引原型：检索结果按主题轴（band）分组聚合
let liveTimer = null;        // 实时搜索防抖
let liveBox = null;          // 当前可见结果容器
let liveEls = [];            // 当前结果 DOM 列表（键盘导航用）
let activeIndex = 0;         // 键盘高亮项

// 标签筛选下拉：动态汇总库里所有标签（带条数），删除/改动后自动跟随
function populateTags(){
  const cnt = {};
  (S.items||[]).forEach(i=>{ String(i.tags||'').split(',').forEach(t=>{ t=t.trim(); if(t) cnt[t]=(cnt[t]||0)+1; }); });
  const names = Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a] || a.localeCompare(b,'zh'));
  const el = $('tTag'); if(!el) return;
  el.innerHTML = '<option value="">（全部）</option>' +
    names.map(t=>`<option value="${esc(t)}">${esc(t)} (${cnt[t]})</option>`).join('');
}
// 搜索抽屉初始化时只刷新标签下拉（查找/按标签两 tab 共用）
function renderSearchStatic(){ populateTags(); }

// 单条结果 → HTML（domain 徽标 + 标题 + 片段 + 元信息），兼容三种模式
function itemHTML(x){
  const badge = x.band ? `<span class="tag">${esc(x.band)}</span>` : '';
  const sc = x.score!=null ? `得分 <b>${x.score}</b>` : '';
  const col = x.collision ? `` : '';
  const extra = x.metaExtra || '';
  const snip = x.snippet ? `<div class="search-item__snippet">${x.snippet}</div>` : '';
  return `<div class="search-item" data-id="${x.id}">
    <div class="search-item__top"><span class="search-item__title">${esc(x.title)}</span>${badge}</div>
    ${snip}
    <div class="search-item__meta">${sc}${extra}</div>
  </div>`;
}
// 把结果数组画进容器，并接管键盘导航
function paintResults(box, items){
  liveBox = box; liveEls = [];
  if(!items || !items.length){ box.innerHTML = '<div class="search-empty">没有找到相关内容。</div>'; return; }
  if(groupByBand){
    paintGroupedResults(box, items);
    return;
  }
  box.innerHTML = items.map(itemHTML).join('');
  bindResultItems(box);
  setActive(0,false);
}

// 非线性索引原型：把扁平结果按主题轴（band）聚合，组间按「组内最高分」排序，
// 组内保持原相关度序。时间线（条目顺序）降级为组内细节，主题轴升为主键。
function paintGroupedResults(box, items){
  const groups = new Map();   // band -> [{item, score}]
  for(const x of items){
    const b = x.band || '未分类';
    if(!groups.has(b)) groups.set(b, []);
    groups.get(b).push(x);
  }
  // 组间排序：组内最高分降序（让最相关的主题簇排在最前）
  const sortedGroups = [...groups.entries()].sort((a,b)=>{
    const ma = Math.max(...a[1].map(x=>x.score||0));
    const mb = Math.max(...b[1].map(x=>x.score||0));
    return mb - ma;
  });
  box.innerHTML = sortedGroups.map(([band, list])=>{
    const top = Math.max(...list.map(x=>x.score||0));
    const rows = list.map(itemHTML).join('');
    return `<div class="search-group" data-band="${esc(band)}">
      <div class="search-group__head">
        <span class="search-group__name">${esc(band)}</span>
        <span class="search-group__count">${list.length} 篇</span>
        <span class="search-group__top">最高 ${top}</span>
      </div>
      <div class="search-group__body">${rows}</div>
    </div>`;
  }).join('');
  bindResultItems(box);
  setActive(0,false);
}

// 绑定 .search-item 的点击 / hover（分组与扁平共用）
function bindResultItems(box){
  box.querySelectorAll('.search-item').forEach((el,i)=>{
    liveEls.push(el);
    el.onclick = ()=>openSearchItem(+el.dataset.id);
    el.onmouseenter = ()=>setActive(i,false);
  });
}
function setActive(i, scroll){
  if(!liveEls.length) return;
  activeIndex = (i + liveEls.length) % liveEls.length;
  liveEls.forEach((el,k)=>el.classList.toggle('search-item--active', k===activeIndex));
  if(scroll) liveEls[activeIndex].scrollIntoView({block:'nearest'});
}
// 三种模式统一拉平为 itemHTML 所需结构
function normalizeResults(list, mode){
  if(mode==='frag'){
    return (list||[]).map(x=>({
      id:x.item_id, title:x.title, band:x.band, snippet:x.snippet,
      metaExtra:`<span class="tag">${(x.signals||[]).map(s=>s==='fts'?'关键词':'语义').join('+')}</span>`
    }));
  }
  return (list||[]).map(x=>({
    id:x.id, title:x.title, band:x.band, score:x.score, snippet:x.snippet,
    tags:x.tags, collision:x.collision
  }));
}
// 实时搜索（防抖触发）
function scheduleLive(){
  clearTimeout(liveTimer);
  const v = $('qText').value.trim();
  $('qClear').hidden = !v;
  liveTimer = setTimeout(doLiveSearch, 240);
}
async function doLiveSearch(){
  const text = $('qText').value.trim();
  if(!text){
    $('qResults').innerHTML = '<div class="search-hint">输入关键词即可实时检索；支持「按意思找」（语义相似）与「定位到段落」（命中原文片段）。</div>';
    return;
  }
  let list = [];
  try{
    if(qMode==='sem'){
      const r = await api('/api/kb/similar', {text, k:12});
      list = normalizeResults(r.results, 'sem');
    } else if(qMode==='frag'){
      const r = await api('/api/kb/fragments', {query:text, top_k:12});
      list = normalizeResults(r.results, 'frag');
    } else {
      const r = await api('/api/kb/query', {text, top_k:12});
      list = normalizeResults(r.results, 'kw');
    }
  }catch(e){ $('qResults').innerHTML = '<div class="search-empty">检索出错，请稍后再试。</div>'; return; }
  paintResults($('qResults'), list);
}

// 按标签浏览：选标签即列出命中文章（客户端，无需请求）
function renderTagList(){
  const box = $('tResults'); if(!box) return;
  const tag = ($('tTag').value||'').trim();
  const items = (S.items||[]).filter(i=>{
    if(!tag) return true;
    return (i.tags||'').split(',').map(s=>s.trim()).includes(tag);
  });
  const list = items.map(i=>({
    id:i.id, title:i.title, band:i.band,
    metaExtra:(i.tags||'').split(',').map(s=>s.trim()).filter(Boolean)
      .map(t=>`<span class="tag">${esc(t)}</span>`).join(' ')
  }));
  paintResults(box, list);
}

// 点开结果：搜索/筛选命中 = 想阅读该条目 → 始终跳到阅读页（不再仅仅高亮节点）。
function openSearchItem(id){
  closeSearchDrawer();
  selectView('reader'); openReader(id);
}

function openSearchDrawer(){
  const d = $('searchDrawer'), b = $('searchBackdrop');
  if(!d) return;
  d.classList.add('open'); b.classList.add('open');
  setTimeout(()=>{ try{ $('qText').focus(); }catch(_){} }, 40);
}
function closeSearchDrawer(){
  const d = $('searchDrawer'), b = $('searchBackdrop');
  if(d) d.classList.remove('open');
  if(b) b.classList.remove('open');
}

function initSearchDrawer(){
  // 填充标签下拉（查找/按标签 共用）
  renderSearchStatic();

  // 触发入口：全局悬浮按钮（常驻所有视图，不在图谱内）
  const fab = $('globalSearch'); if(fab) fab.onclick = openSearchDrawer;
  const close = $('searchClose'); if(close) close.onclick = closeSearchDrawer;
  const backdrop = $('searchBackdrop'); if(backdrop) backdrop.onclick = closeSearchDrawer;

  // 快捷键提示按平台显示（Mac 显示 ⌘K，其余显示 Ctrl K）
  const kbd = $('searchKbd');
  if(kbd && !/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent)) kbd.textContent = 'Ctrl K';

  // tab 切换：查找 / 按标签
  const tabs = $('searchTabs');
  if(tabs) tabs.querySelectorAll('[data-st]').forEach(b=>b.onclick=()=>{
    const st = b.dataset.st;
    tabs.querySelectorAll('[data-st]').forEach(x=>x.classList.toggle('active', x===b));
    document.querySelectorAll('.stab').forEach(t=>{ t.hidden = (t.dataset.stab!==st); });
    liveBox = null; liveEls = [];           // 重置键盘导航上下文
    if(st==='find') setTimeout(()=>{ try{ $('qText').focus(); }catch(_){} }, 30);
    else if(st==='tag') renderTagList();
  });

  // 查找：实时搜索输入
  const q = $('qText');
  if(q){
    q.addEventListener('input', scheduleLive);
    q.addEventListener('keydown', e=>{
      if(e.key==='Enter'){ e.preventDefault(); const el=liveEls[activeIndex]; if(el) openSearchItem(+el.dataset.id); }
    });
  }
  const clear = $('qClear'); if(clear) clear.onclick = ()=>{
    $('qText').value=''; clear.hidden=true; $('qText').focus(); doLiveSearch();
  };

  // 查找模式：关键词 / 意思 / 段落
  const modes = $('qModes');
  if(modes) modes.querySelectorAll('[data-qm]').forEach(b=>b.onclick=()=>{
    qMode = b.dataset.qm;
    modes.querySelectorAll('[data-qm]').forEach(x=>x.classList.toggle('active', x===b));
    if($('qText').value.trim()) doLiveSearch();
  });

  // 非线性索引原型开关：按主题轴（band）分组聚合检索结果
  const gb = $('qGroupBy');
  if(gb) gb.onclick = ()=>{
    groupByBand = !groupByBand;
    gb.classList.toggle('active', groupByBand);
    if($('qText').value.trim()) doLiveSearch();
  };

  // 按标签：选择即刷新列表
  const tTag = $('tTag'); if(tTag) tTag.onchange = renderTagList;

  // 全局键盘：⌘K / Ctrl+K 打开；Esc 关闭；在查找输入框内用上下键浏览、回车打开
  document.addEventListener('keydown', e=>{
    const d = $('searchDrawer');
    if((e.metaKey||e.ctrlKey) && e.key.toLowerCase()==='k'){
      e.preventDefault();
      if(d && d.classList.contains('open')) closeSearchDrawer(); else openSearchDrawer();
      return;
    }
    if(!d || !d.classList.contains('open')) return;
    if(e.key==='Escape'){ closeSearchDrawer(); return; }
    if(document.activeElement!==$('qText')) return;
    if(e.key==='ArrowDown'){ e.preventDefault(); setActive(activeIndex+1); }
    else if(e.key==='ArrowUp'){ e.preventDefault(); setActive(activeIndex-1); }
  });
}
