// 灯笼知识库 · core —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
const $ = id => document.getElementById(id);
const esc = s => (s==null?'':(''+s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let S = null, KB = null, curId = null, busy = false, mapMode = 'near';
let selAxis = null;
const api = async (path, body) => {
  const opt = body ? {method:'POST', headers:{'Content-Type':'application/json'},
                      body: JSON.stringify(body)} : {};
  const r = await fetch(path, opt);
  return r.json();
};
const cur = () => (S.items.find(i => i.id === curId) || S.items[0]);

/* ---------------- 视图切换 ---------------- */
const VIEWS = {overview:['总览','Overview'], knowledge:['知识库','Knowledge'],
  reader:['阅读','Read'], visualize:['逻辑偏差','Logic'],
  graph:['知识图谱','Graph'],
  model:['设置','Settings']};
function selectView(name){
  Object.keys(VIEWS).forEach(v=>{
    $('view-'+v).classList.toggle('active', v===name);
    $('nav').querySelector(`[data-view="${v}"]`).classList.toggle('active', v===name);
  });
  $('viewTitle').textContent = VIEWS[name][0];
  $('viewEn').textContent = VIEWS[name][1];
  if(name==='knowledge') renderKnowledge();
  if(name==='reader') renderReader();
  if(name==='visualize') renderVisualize();
  if(name==='graph') renderGraph();
  if(name==='model') renderModel();
  if(name==='overview') renderOverview();
}
$('nav').querySelectorAll('a').forEach(a=>a.onclick=()=>selectView(a.dataset.view));

/* ---------------- 加载 ---------------- */
async function load(){
  S = await api('/api/state');
  KB = await api('/api/kb/state');
  _sig = dataSigOf(S.items);
  if(curId === null){
    curId = (S.items[0] && S.items[0].id);
  }
  renderTop();
  renderNavBadges();
  // 当前视图刷新
  selectView(document.querySelector('nav a.active').dataset.view);
}

/* ---------------- 自动感知后台补算 ---------------- */
// 后台 AI 补算会改写条目的领域/位置/严密度/摘要，这里每 20 秒静默对比一次，
// 数据变了就自动刷新当前视图——不用手动刷新页面。
// 编辑态或正聚焦在输入框时不打扰。
let _sig = '', _sigLinks = '';
function dataSigOf(items){
  return JSON.stringify((items||[]).map(i=>[i.id,i.band,i.main_pos,i.vernier,i.offset,i.ref_kind,i.summary,i.tags]));
}
function linksSigOf(links){
  // 图谱关联（硬链/共现/语义 + 确认态）一变，就重画图谱，让引擎的发现实时长出来
  return JSON.stringify((links||[]).map(l=>[l.src,l.dst,l.kind,l.confirmed,l.provenance]));
}
function startAutoRefresh(ms){
  _sig = dataSigOf((S||{}).items);
  _sigLinks = linksSigOf((S||{}).links);
  setInterval(async ()=>{
    const tag = (document.activeElement||{}).tagName || '';
    if(rdMode === 'edit' || /^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
    try{
      const r = await api('/api/state');
      const sig = dataSigOf(r.items);
      const lsig = linksSigOf(r.links);
      if(sig !== _sig || lsig !== _sigLinks){ _sig = sig; _sigLinks = lsig; load(); }
    }catch(e){ /* 网络抖动忽略 */ }
  }, ms || 20000);
}

function renderTop(){
  const llm = S.llm || {available:false}, isLLM = S.mode==='llm';
  $('modePill').textContent = isLLM ? '智能模型' : '简单规则';
  $('modePill').className = 'pill ' + (isLLM ? 'llm' : '');
  const g = S.independence;
  $('rPill').textContent = '关联度 ' + g.r;
  $('rPill').className = 'pill ' + (g.status==='fail'?'fail':(g.status==='warn'?'warn':'ok'));
  $('cntPill').textContent = `知识 ${S.items.length} 条`;
  // 菜单内徽标
  $('navItems').textContent = S.items.length;
  $('navTotal').textContent = S.items.length;
  $('navEdges').textContent = S.edges.length;
}
function renderNavBadges(){ /* 已在 renderTop 内更新 */ }

