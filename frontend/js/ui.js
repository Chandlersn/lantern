// 灯笼知识库 · ui —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 自定义下拉组件（原生弹层是方的，样式管不到；换成自绘圆角列表） ---------------- */
function enhanceSelects(){
  document.querySelectorAll('select').forEach(sel=>{
    if(sel.dataset.selx) return;
    sel.dataset.selx = '1';
    const wrap = document.createElement('div');
    wrap.className = 'sel-wrap' + (sel.classList.contains('grow') ? ' grow' : '');
    if(sel.classList.contains('grow')) sel.classList.remove('grow');
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(sel);
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'sel-btn';
    btn.innerHTML = '<span class="txt"></span><span class="arr"></span>';
    wrap.appendChild(btn);
    const list = document.createElement('div');
    list.className = 'sel-list';
    wrap.appendChild(list);
    const build = ()=>{
      const o = [...sel.options].find(x=>x.selected) || sel.options[0];
      const txt = btn.querySelector('.txt');
      txt.textContent = o ? o.text : '—'; txt.title = o ? o.text : '';
      list.innerHTML = [...sel.options].map((op,i)=>
        `<div class="opt${op.selected?' on':''}" data-i="${i}">${esc(op.text)}</div>`).join('');
    };
    const close = ()=>wrap.classList.remove('open');
    btn.addEventListener('click', e=>{
      e.stopPropagation();
      wrap.classList.contains('open') ? close() : (build(), wrap.classList.add('open'));
    });
    list.addEventListener('click', e=>{
      const it = e.target.closest('.opt'); if(!it) return;
      const o = sel.options[+it.dataset.i];
      if(o){ sel.value = o.value; sel.dispatchEvent(new Event('change',{bubbles:true})); }
      close();
    });
    document.addEventListener('click', e=>{ if(!wrap.contains(e.target)) close(); });
    sel.addEventListener('keydown', e=>{ if(e.key==='Escape') close(); });
    // 选项被重设（fillItemSelects / populateBand / populateTags）时自动重建列表
    new MutationObserver(build).observe(sel,{childList:true});
    build();
  });
}

/* ---------------- 主题弹窗（替代系统原生 alert/confirm，宣纸墨韵风格） ---------------- */
let _dlgCancel = null;
function dlgShow(msg, btns, cancelFn){
  $('dlgMsg').textContent = String(msg);
  const wrap = $('dlgBtns');
  wrap.innerHTML = '';
  btns.forEach(b=>{
    const el = document.createElement('button');
    el.type = 'button'; el.textContent = b.label;
    if(b.kind==='soft') el.className = 'soft';
    else if(b.kind==='ghost') el.className = 'ghost';
    else if(b.kind==='danger') el.className = 'danger';
    el.onclick = ()=>{ $('dlgMask').style.display='none'; _dlgCancel=null; if(b.onclick) b.onclick(); };
    wrap.appendChild(el);
  });
  _dlgCancel = cancelFn || null;
  $('dlgMask').style.display = 'flex';
}
function dlgMaskClick(e){
  if(e.target !== $('dlgMask')) return;
  if(_dlgCancel){ const f=_dlgCancel; _dlgCancel=null; f(); }
  else $('dlgMask').style.display = 'none';
}
$('dlgMask').addEventListener('click', dlgMaskClick);
// 原生 alert → 主题弹窗（fire-and-forget，返回值没人用）
window.alert = msg => dlgShow(msg, [{label:'知道了', kind:'primary'}]);
// 确认框：async，返回 Promise<boolean>；危险操作用 danger 样式
function confirmBox(msg, danger){
  return new Promise(res=>{
    dlgShow(msg, [
      {label:'取消', kind:'soft', onclick:()=>res(false)},
      {label:'确定', kind: danger?'danger':'primary', onclick:()=>res(true)}
    ], ()=>{ $('dlgMask').style.display='none'; res(false); });
  });
}
// 兜底：就算将来有代码直接调 confirm/prompt，也不走系统原生弹窗
window.confirm = msg => confirmBox(msg);
window.prompt = () => null;

