// 灯笼知识库 · model —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* ---------------- 设置 ---------------- */
function renderModel(){
  const llm = S.llm || {available:false}, isLLM = S.mode==='llm';
  $('mMode').innerHTML = `<div class="row">
    <span class="pill ${isLLM?'llm':''}">${isLLM?'智能模型':'简单规则'}</span>
    ${llm.available?`<span class="pill">${llm.key}</span><span class="pill">已缓存 ${llm.cached_calls} 次</span>`:''}
  </div>` + (llm.available?`<div class="kv" style="margin-top:8px;">端点 <code>${llm.api_base}</code> · 凭据 <code>${llm.env_source}</code></div>`:'<div class="note">未找到 API_KEY，仅可运行简单规则。</div>');
  $('btnLLM').disabled = !llm.available || isLLM || busy;
  $('btnHeu').disabled = !isLLM || busy;
  $('mNote').textContent = busy ? '正在用智能模型重新判断所有内容，请稍候…' : '';
  renderGuard('mGuard','mFamilies');
  // 模型配置表单：打开设置页即拉取当前配置并填充
  api('/api/kb/config').then(c=>{
    if($('cfgBase')) $('cfgBase').value = c.api_base || '';
    if($('cfgModel')) $('cfgModel').value = c.model || '';
    const keyInput = $('cfgKey');
    if(keyInput){
      keyInput.value = '';
      keyInput.type = 'password';
      keyInput.placeholder = c.api_key_set ? ('已配置（'+(c.key_masked||'')+'），留空则不修改') : 'sk-... 留空表示不修改';
    }
    const st = $('cfgStatus');
    if(st){
      const custom = (c.source||'').indexOf('llm_config') >= 0;
      st.style.display = '';
      st.className = 'pill ' + (c.available ? 'llm' : 'ghost');
      st.textContent = c.available ? ('可用 · '+(custom?'自定义':'环境变量')) : '未配置密钥';
    }
    const note = $('cfgNote');
    if(note) note.textContent = c.available
      ? '当前配置来源：'+(c.source||'')+'。保存会写入 llm_config.json 并覆盖 .env。'
      : '当前没有可用密钥（来自 '+(c.source||'')+'）。填好端点与密钥后，先「测试连接」再「保存」。';
  }).catch(()=>{});
}

/* ---------------- 模型配置：保存 / 测试连接 ---------------- */
$('btnCfgSave').onclick = async ()=>{
  const btn = $('btnCfgSave'); btn.disabled = true;
  try{
    const r = await api('/api/kb/config_set', {
      api_base: $('cfgBase').value.trim(),
      model: $('cfgModel').value.trim(),
      api_key: $('cfgKey').value,
    });
    const st = $('cfgStatus');
    if(st){
      st.style.display = '';
      st.className = 'pill ' + (r.available ? 'llm' : 'ghost');
      st.textContent = r.available ? '已保存 · 可用' : '已保存 · 仍缺密钥';
    }
    $('cfgNote').textContent = '配置已保存到 llm_config.json，立即生效。若要从「简单规则」切到「智能模型」，点上方「改用智能模型」。';
    await load();
  }catch(e){ alert('保存失败：' + e); }
  btn.disabled = false;
};

$('btnCfgTest').onclick = async ()=>{
  const btn = $('btnCfgTest'); btn.disabled = true; btn.textContent = '测试中…';
  const st = $('cfgStatus');
  try{
    const r = await api('/api/kb/config_test', {
      api_base: $('cfgBase').value.trim(),
      model: $('cfgModel').value.trim(),
      api_key: $('cfgKey').value,
    });
    if(st){
      st.style.display = '';
      st.className = 'pill ' + (r.ok ? 'llm' : 'ghost');
      st.textContent = r.ok ? ('连接成功 · '+(r.model||'')) : ('失败：'+(r.error||''));
    }
    $('cfgNote').textContent = r.ok
      ? '连接成功，端点 / 密钥 / 模型都通。点「保存配置」让它生效。'
      : '连接失败：'+(r.error||'未知错误')+'。请检查端点、密钥与模型名。';
  }catch(e){ $('cfgNote').textContent = '测试请求出错：' + e; }
  btn.disabled = false; btn.textContent = '测试连接';
};
$('btnIso').onclick = async ()=>{
  const t = $('isoText').value.trim(); if(!t){ alert('请粘贴文字'); return; }
  const r = await api('/api/isolation?text='+encodeURIComponent(t));
  if(!r.ok){ $('isoOut').innerHTML='<div class="note">（需启用智能模型接入层）</div>'; return; }
  const row = (who,cls,txt,blind)=>`<div style="margin:8px 0;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:#FBF8F0;">
    <div style="font-size:11.5px;color:${cls};margin-bottom:3px;">${who}</div>
    <div style="font-size:13px;line-height:1.7;">${txt||'（空）'}</div>
    <div style="font-size:11px;color:var(--stone);margin-top:3px;">${blind}</div></div>`;
  $('isoOut').innerHTML =
    `<div style="font-size:12.5px;color:var(--muted);">原文：${r.raw}</div>` +
    row('从「属于什么领域」角度看到的','var(--ink)', r.main_sees, '连接词已去掉，只看讲了什么主题') +
    row('从「论证有多严密」角度看到的','var(--cinnabar)', r.vernier_sees, '具体内容已隐去，只看论证的结构');
};


/* ---------------- 语义向量重建（模型 embedding 优先，接口不可用回退本地） ---------------- */
$('btnEmbRebuild').onclick = async ()=>{
  if(!await confirmBox('重新生成全部条目的语义向量？会调用模型接口（若支持 embedding），可能稍慢。')) return;
  const btn = $('btnEmbRebuild'); btn.disabled = true; btn.textContent = '生成中…';
  try{
    const r = await api('/api/kb/embed_rebuild', {});
    alert('完成：' + r.done + ' 条成功' + (r.failed ? '，' + r.failed + ' 条失败' : '') + '，维度 ' + r.dim + '。' +
      (r.dim === 256 ? '当前是本地向量；接入支持 embedding 的模型后，再点一次就会自动用真实语义向量。' : ''));
    await load();
  }catch(e){ alert('重建失败：' + e); }
  btn.disabled = false; btn.textContent = '用模型重新生成语义向量';
};
