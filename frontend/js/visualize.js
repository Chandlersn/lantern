// 灯笼知识库 · visualize —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 定位查看（可筛选条目列表） ---------------- */
let _vizInit = false;
function initVizPicker(){
  if(_vizInit) return; _vizInit = true;
  const f = $('vFilter');
  if(f) f.addEventListener('input', ()=>fillVizList(f.value));
  const list = $('vList');
  if(list) list.addEventListener('click', e=>{
    const row = e.target.closest('.viz-item'); if(!row) return;
    curId = +row.dataset.id;
    syncViz();
    const it = cur(); renderBeams('vBeams','vReadout', it); renderMap();
  });
}
// 让列表高亮与 curId 保持一致，并把选中项滚入可视区
function syncViz(){
  document.querySelectorAll('#vList .viz-item').forEach(d=>{
    d.classList.toggle('on', +d.dataset.id === curId);
  });
  const sel = document.querySelector('#vList .viz-item.on');
  if(sel && typeof sel.scrollIntoView === 'function') sel.scrollIntoView({block:'nearest'});
}
function renderVisualize(){
  initVizPicker();
  fillItemSelects(); populateBand();
  const it = cur(); if(!it){ $('vBeams').textContent=''; return; }
  fillVizList($('vFilter') ? $('vFilter').value : '');
  syncViz();
  renderBeams('vBeams','vReadout', it);
  renderMap();
}
document.querySelectorAll('[data-map]').forEach(b=>b.onclick=()=>{
  mapMode=b.dataset.map;
  document.querySelectorAll('[data-map]').forEach(x=>x.classList.toggle('active', x===b));
  renderMap();
});

