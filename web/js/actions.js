// 灯笼知识库 · actions —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 操作 ---------------- */
async function switchMode(mode){
  busy=true; renderModel();
  const r=await api('/api/mode',{mode}); busy=false;
  if(r && r.ok===false) alert(r.msg||'切换失败');
  await load();
  if(mode==='llm') selectView('model');
}
$('btnLLM').onclick=async()=>{ if(!await confirmBox('将会用智能模型重新判断所有内容，可能稍慢并消耗额度。继续？')) return; switchMode('llm'); };
$('btnHeu').onclick=()=>switchMode('heuristic');

/* llm 模式下读数与向量在后台补算，这里轮询到补算完成再刷新界面，
   让用户最终看到真实模型结果；模型不通时会自动停在启发式并结束轮询。 */
function awaitRefine(id){
  if((S.mode||'heuristic')!=='llm') return;
  let n=0;
  const tick=async()=>{
    if(++n>10) return;
    await load();
    const it=(S.items||[]).find(x=>x.id===id);
    const done = it && String(it.main_provider||'').startsWith('llm:');
    if(done || n>=10) return;
    setTimeout(tick, 2000);
  };
  setTimeout(tick, 2000);
}

$('btnAdd').onclick=async()=>{
  const title=$('nTitle').value.trim(), content=$('nBody').value.trim();
  if(!content){ alert('正文必填'); return; }
  const r=await api('/api/kb/add',{title,content,axis_domain:selAxis});
  if(r.ok===false){ alert(r.msg||'保存失败'); return; }
  $('nTitle').value=''; $('nBody').value=''; selAxis=null; curId=r.item.id; await load(); populateTags();
  openReader(r.item.id);
  awaitRefine(r.item.id);
};
$('btnReset').onclick=$('btnReset2').onclick=async()=>{
  if(!await confirmBox('清空全部内容？所有知识、关联和记录都会删除。', true)) return;
  await api('/api/reset',{}); curId=null; await load(); populateTags();
};

