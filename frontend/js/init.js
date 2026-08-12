// 灯笼知识库 · init —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
enhanceSelects();
load().then(()=>{ startAutoRefresh(20000); initSearchDrawer(); bindNBodyExpand(); });
initFeedback();

// 录入新知识：正文输入框双击/聚焦开始编辑时自动放大；失焦且为空才缩回（有内容保持展开，避免编辑中途切换焦点被打断）
function bindNBodyExpand(){
  const ta = document.getElementById('nBody'); if(!ta) return;
  ta.addEventListener('focus', ()=> ta.classList.add('expanded'));
  ta.addEventListener('dblclick', ()=> ta.classList.add('expanded'));
  ta.addEventListener('blur', ()=>{ if(!ta.value.trim()) ta.classList.remove('expanded'); });
}
