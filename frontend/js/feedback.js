// 灯笼知识库 · feedback —— 由 index.html 脚本按功能分区拆出，勿手动改此注释
/* 自我对抗审查（反馈轴）的「推送通道 + 反馈邮箱」双通道，两者数据同源（feedback_inbox 表）、但入口与交互彻底分开：
   · 推送通道（QQ 式右下角弹窗）：实时、瞬时、逐条。新反馈到达时一条一条从右下角弹出，
     点击弹窗 → 就地展开看完整反馈内容 → 再决定后续操作（查看原文/标已读/应用更新/忽略）。不自动画成边、不污染文章正文。
   · 反馈邮箱（侧边收件箱）：持久、总览、可回溯。集中显示全部反馈（全部/未读/已采纳/已忽略），是归档与集中处理的地方。
   反馈不进文章正文（保持知识文章纯洁），单独落在 feedback_inbox 表。 */

let _fbLastUnread = 0;
let _fbPanelOpen = false;
let _fbBusy = false;
let _fbToastedIds = new Set();    // 本会话内已入队/弹过的反馈 id，避免重复推送
let _fbPushQueue = [];            // 待推送反馈 id 队列（受 ≥3 分钟最小间隔约束，绝不一起弹）
let _fbLastPushAt = 0;           // 上一条弹窗推送的时间戳（ms）
let _fbItemsById = {};           // 最近一次拉取的反馈 id→item 映射（弹前再确认最新状态）
let _fbSignal = null;            // 信号守卫状态（signal_integrity），用于邮箱说明克制原因
const FB_PUSH_INTERVAL = 3 * 60 * 1000;   // 推送最小间隔：≥3 分钟，避免多条一起弹让人手忙脚乱

const FB_FIELDS = [
  ["core_verdict_weakest_support", "核心判断最弱支撑点"],
  ["strongest_counter", "最强反论据"],
  ["hidden_assumptions", "隐藏假设"],
  ["blind_spots", "透镜盲区"],
  ["internal_tension", "内部张力"],
  ["over_reach", "过度推断"],
  ["verdict_revised", "修订后核心判断"],
];

const SEV_LABEL = { critical: "需修订", warn: "建议留意", info: "提示" };

function initFeedback(){
  const bell = $("fbBell");
  if(bell) bell.onclick = toggleFbPanel;
  refreshFeedback(false);
  // 轮询：新反馈到达时弹 QQ 式 toast（编辑态不打扰）
  setInterval(async ()=>{
    const tag = (document.activeElement||{}).tagName || "";
    if(/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
    if(_fbBusy) return;
    try { await refreshFeedback(true); } catch(e){ /* 网络抖动忽略 */ }
  }, 15000);
  // 点击页面其他位置 → 收起右下角 toast + 侧边面板（避免一直遮挡内容）
  document.addEventListener("click", (e)=>{
    const box = $("fbToasts");
    if(box && box.children.length && !box.contains(e.target)) closeAllFbToasts();
    // 侧边「自我审查反馈」面板：点面板外（且非铃铛按钮）即收起
    const p = $("fbPanel"), bell = $("fbBell");
    if(_fbPanelOpen && p && !p.contains(e.target) && !(bell && bell.contains(e.target))) closeFbPanel();
  }, true);
}

async function refreshFeedback(poll){
  _fbBusy = true;
  try{
    const r = await api("/api/feedback");
    const unread = r.unread || 0;
    const badge = $("fbBadge");
    if(badge){
      badge.textContent = unread ? (unread > 99 ? "99+" : unread) : "";
      badge.style.display = unread ? "inline-block" : "none";
    }
    const items = r.items || [];
    items.forEach(it=> { _fbItemsById[it.id] = it; });
    _fbSignal = r.signal || null;
    // 待推送：未读 + 有推送资格(pushable) + 本会话未入队过。统一进队列，由 scheduleFbToast 按 ≥3 分钟间隔弹出。
    const candidates = items.filter(x => x.status === "unread" && x.pushable && !_fbToastedIds.has(x.id));
    candidates.forEach(it=>{ _fbToastedIds.add(it.id); _fbPushQueue.push(it.id); });
    _fbLastUnread = unread;
    if(_fbPanelOpen) renderFbPanel(items);
    scheduleFbToast();
  } finally { _fbBusy = false; }
}

function toggleFbPanel(){
  _fbPanelOpen = !_fbPanelOpen;
  const p = $("fbPanel");
  if(p) p.classList.toggle("open", _fbPanelOpen);
  if(_fbPanelOpen) refreshFeedback(false);
}

function closeFbPanel(){
  _fbPanelOpen = false;
  const p = $("fbPanel");
  if(p) p.classList.remove("open");
}

/* 推送节流：从队列取队首，距上一条推送 ≥3 分钟才弹；否则等下次轮询再试。绝不一起弹。 */
function scheduleFbToast(){
  while(_fbPushQueue.length){
    const id = _fbPushQueue[0];
    const it = _fbItemsById[id];
    // 已被读/采纳/忽略，或失去推送资格 → 出队跳过（不弹）
    if(!it || it.status !== "unread" || !it.pushable){ _fbPushQueue.shift(); continue; }
    // 距上一条推送不足 3 分钟 → 暂不弹，返回等待下次轮询
    if(Date.now() - _fbLastPushAt < FB_PUSH_INTERVAL) return;
    _fbPushQueue.shift();
    _fbLastPushAt = Date.now();
    showFbToast(it);
    break;
  }
}

/* ---------------- 推送通道：QQ 式右下角弹窗（逐条） ---------------- */
function showFbToast(it){
  const box = $("fbToasts");
  if(!box) return;
  const el = document.createElement("div");
  el.className = "fb-toast sev-" + (it.severity || "info");
  el.dataset.id = it.id;
  const prev = fbPreview(it);
  el.innerHTML =
    `<div class="fb-av">灯</div>` +
    `<div class="fb-tbody">` +
      `<div class="fb-tname">灯笼 · 自我审查 <span class="fb-pushtag">推送</span><span class="fb-dot sev-${it.severity||'info'}"></span></div>` +
      `<div class="fb-tmsg"><b>${esc(it.title)}</b><br>${esc(prev)}</div>` +
      `<div class="fb-expand" hidden></div>` +
    `</div>` +
    `<button class="fb-tclose" title="关闭">×</button>`;
  // 未展开时 9s 自动消失；展开后由 expandFbToast 清掉这个计时，停留到用户操作
  const autoTimer = setTimeout(()=>{ if(el.parentNode && !el.classList.contains("expanded")) fadeOutFbToast(el); }, 9000);
  el.onclick = (e)=>{
    if(e.target.classList.contains("fb-tclose")){ clearTimeout(autoTimer); el.remove(); return; }
    if(e.target.closest("[data-act]")) return;   // 操作按钮自行处理，不触发展开
    if(!el.classList.contains("expanded")) expandFbToast(el, it, ()=>clearTimeout(autoTimer));
  };
  box.appendChild(el);
  // 最多堆叠 4 条（老的先走）
  while(box.children.length > 4) box.removeChild(box.firstChild);
}

// 点击弹窗 → 就地展开：先看完整反馈内容，再给后续操作
function expandFbToast(el, it, clearAuto){
  if(el.classList.contains("expanded")) return;
  el.classList.add("expanded");
  if(clearAuto) clearAuto();
  const dom = it.axis_domain ? `<span class="tag">${esc(it.axis_domain)}</span>` : "";
  const t = it.created_at ? new Date(it.created_at*1000).toLocaleString("zh-CN",{hour12:false}) : "";
  const body = fbReviewBody(it);
  const ex = el.querySelector(".fb-expand");
  ex.hidden = false;
  ex.innerHTML =
    (body || `<div class="fb-rev fb-rev-empty">（这条反馈没有结构化细节）</div>`) +
    `<div class="fb-meta">${dom}<span class="muted">${t}</span><span class="fb-sev">${SEV_LABEL[it.severity]||""}</span></div>` +
    `<div class="fb-acts">` +
      (it.item_id ? `<button class="soft" data-act="open">查看原文</button>` : "") +
      (it.status==="unread" ? `<button class="soft" data-act="read">标已读</button>` : "") +
      (fbCanApply(it) ? `<button data-act="applied">应用更新</button>` : "") +
      (it.status!=="dismissed" ? `<button class="soft" data-act="dismiss">忽略</button>` : "") +
      (it.review && it.review.type === "near_duplicate" ? `<button class="soft" data-act="notdup">标记非重复</button>` : "") +
      (!it.item_id ? `<span class="fb-hint muted">此提示针对「条目对关系」，无单篇可应用更新</span>` : "") +
    `</div>`;
  // 展开即视为已读（看过内容 = 读过了），同步徽标
  if(it.status === "unread"){ api("/api/feedback/read", { id: it.id }).catch(()=>{}); it.status = "read"; refreshFeedback(false); }
  ex.querySelectorAll("[data-act]").forEach(btn=>{
    btn.onclick = async (e)=>{
      e.stopPropagation();
      const act = btn.dataset.act;
      if(act==="open"){ openFbItem(it); el.remove(); return; }
      if(act==="applied"){ applyFbRevision(it); el.remove(); return; }
      if(act==="read"){ await api("/api/feedback/read",{id:it.id}).catch(()=>{}); el.remove(); refreshFeedback(false); return; }
      if(act==="dismiss"){ await api("/api/feedback/dismiss",{id:it.id}).catch(()=>{}); el.remove(); refreshFeedback(false); return; }
      if(act==="notdup"){
        const rv = it.review || {};
        if(rv.self_id == null || rv.partner_id == null) return;
        if(confirm("标记为「非重复」？之后不再就这一对提醒。")){
          await api("/api/feedback/not_duplicate",{a:rv.self_id,b:rv.partner_id}).catch(()=>{});
          el.remove(); refreshFeedback(false);
        }
        return;
      }
    };
  });
}

// 单条淡出后移除
function fadeOutFbToast(el){
  if(!el || !el.parentNode || el.classList.contains("leaving")) return;
  el.classList.add("leaving");
  setTimeout(()=>{ if(el.parentNode) el.remove(); }, 220);
}

// 关闭全部 toast（点页面其他位置时调用）—— 已展开（用户正在看内容/操作）的不收，停留到用户处理完
function closeAllFbToasts(){
  const box = $("fbToasts");
  if(!box) return;
  Array.from(box.children).forEach(el=>{ if(!el.classList.contains("expanded")) fadeOutFbToast(el); });
}

function fbPreview(it){
  const rv = it.review || {};
  const pick = rv.strongest_counter || rv.core_verdict_weakest_support ||
               rv.over_reach || (SEV_LABEL[it.severity] || "收到一条反馈");
  const s = ("" + pick).replace(/\n/g, " ");
  return s.length > 60 ? s.slice(0, 60) + "…" : s;
}

// 「应用更新」只对「对抗审查」类反馈有意义（有修订稿可生成）；
// domain_corrected（领域守门纠正）走人「修正」入口，near_duplicate（重复检测）走「标记非重复」。
// 这两者点「应用更新」无修订稿、会弹 alert 误导。
function fbCanApply(it){
  const t = it.review && it.review.type;
  if(t === "domain_corrected" || t === "near_duplicate") return false;
  return !!(it.item_id && it.status !== "applied");
}

/* ---------------- 收件箱面板 ---------------- */
function renderFbPanel(items){
  const p = $("fbPanel");
  if(!p) return;
  const counts = { unread:0, read:0, applied:0, dismissed:0 };
  items.forEach(i=>{ counts[i.status] = (counts[i.status]||0)+1; });
  let html = `<div class="fb-ph">`;
  html += `<div class="fb-ptitle">反馈邮箱 <span class="muted">${items.length} 条</span></div>`;
  html += `<div class="fb-psub">自我审查反馈 · 集中收件箱（与右下角逐条推送区分开）</div>`;
  html += `<div class="fb-phbar"><button class="soft danger sm" id="fbClear" title="永久删除全部反馈">清空收件箱</button></div>`;
  if(_fbSignal && _fbSignal.status === "degraded"){
    html += `<div class="fb-sysbar">嵌入信号当前退化：语义相似类反馈已自动暂停弹窗推送，仅存入此处备查，避免误报打扰。待信号恢复后再评估。</div>`;
  }
  html += `<button class="fb-close" id="fbClose" title="关闭">×</button>`;
  html += `<div class="fb-tabs">`;
  html += `<span class="on" data-f="all">全部 ${items.length}</span>`;
  html += `<span data-f="unread">未读 ${counts.unread||0}</span>`;
  html += `<span data-f="applied">已采纳 ${counts.applied||0}</span>`;
  html += `<span data-f="dismissed">已忽略 ${counts.dismissed||0}</span>`;
  html += `</div></div>`;
  html += `<div class="fb-list" id="fbList"></div>`;
  p.innerHTML = html;

  const closeBtn = $("fbClose");
  if(closeBtn) closeBtn.onclick = ()=> closeFbPanel();

  const clearBtn = $("fbClear");
  if(clearBtn) clearBtn.onclick = async ()=>{
    if(!confirm("确定清空收件箱？全部反馈将被永久删除，此操作不可恢复。")) return;
    const r = await api("/api/feedback/clear").catch(()=>null);
    if(r && r.ok){ refreshFeedback(false); }
    else alert("清空失败");
  };

  const list = $("fbList");
  p.querySelectorAll(".fb-tabs span").forEach(sp=>{
    sp.onclick = ()=>{
      p.querySelectorAll(".fb-tabs span").forEach(x=>x.classList.remove("on"));
      sp.classList.add("on");
      const f = sp.dataset.f;
      const shown = f==="all" ? items : items.filter(i=>i.status===f);
      list.innerHTML = shown.length ? shown.map(fbCard).join("") : `<div class="fb-empty">这里空空如也</div>`;
      bindFbCards(shown);
    };
  });
  list.innerHTML = items.length ? items.map(fbCard).join("") : `<div class="fb-empty">还没有反馈。运行 Skill 的「反馈轴（自我对抗审查）」后会在这里收到消息。</div>`;
  bindFbCards(items);
}

// 结构化审查内容（推送展开态与邮箱卡片共用的渲染）
// 既渲染受控的「反馈轴」字段（FB_FIELDS），也兜底渲染引擎产生的其它字段（如 near_duplicate 的 partner/sim/note），
// 保证「查看具体内容」永远有东西可看，不依赖某一套固定字段。
const REVIEW_TYPE_LABEL = { near_duplicate:"近似重复", bridge:"跨主题桥接", redundancy:"冗余", collision:"离域较远", tension:"内部张力" };
const REVIEW_LABELS = {
  type:"类型", partner:"配对条目", sim:"相似度", note:"说明",
  core_verdict_weakest_support:"核心判断最弱支撑点", strongest_counter:"最强反论据",
  hidden_assumptions:"隐藏假设", blind_spots:"透镜盲区", internal_tension:"内部张力",
  over_reach:"过度推断", verdict_revised:"修订后核心判断"
};

function fbFieldHTML(label, v){
  if(Array.isArray(v)){
    return `<div class="fb-f"><span class="fb-fl">${esc(label)}</span><ul>${v.map(x=>`<li>${esc(x)}</li>`).join("")}</ul></div>`;
  }
  return `<div class="fb-f"><span class="fb-fl">${esc(label)}</span><span class="fb-fv">${esc(v)}</span></div>`;
}

function fbReviewBody(it){
  const rv = it.review || {};
  const shown = new Set();
  let body = "";
  // 1) 优先按受控顺序渲染「反馈轴」字段
  for(const [k,label] of FB_FIELDS){
    const v = rv[k];
    if(v == null || v === "" || (Array.isArray(v) && !v.length)) continue;
    shown.add(k);
    body += fbFieldHTML(label, v);
  }
  // 2) 兜底渲染其余字段（引擎检测类反馈），type 值做中文映射
  for(const k of Object.keys(rv)){
    if(shown.has(k)) continue;
    const v = rv[k];
    if(v == null || v === "" || (Array.isArray(v) && !v.length)) continue;
    let label = REVIEW_LABELS[k] || k;
    let val = v;
    if(k === "type" && REVIEW_TYPE_LABEL[v]) val = REVIEW_TYPE_LABEL[v];
    body += fbFieldHTML(label, val);
  }
  if(it.must_revise) body += `<div class="fb-flag">注意 · 反馈轴判定：写回前需先修订核心判断</div>`;
  return body;
}

function fbCard(it){
  const body = fbReviewBody(it);
  const dom = it.axis_domain ? `<span class="tag">${esc(it.axis_domain)}</span>` : "";
  const t = it.created_at ? new Date(it.created_at*1000).toLocaleString("zh-CN",{hour12:false}) : "";
  const st = { unread:"未读", read:"已读", applied:"已采纳", dismissed:"已忽略" }[it.status] || it.status;
  return `<div class="fb-card sev-${it.severity||'info'}" data-id="${it.id}">`
    + `<div class="fb-ch"><span class="fb-dot sev-${it.severity||'info'}"></span>`
    + `<div class="fb-ctitle">${esc(it.title)}</div>`
    + `<span class="fb-st fb-st-${it.status}">${st}</span>`
    + (it.pushable ? "" : `<span class="fb-st fb-st-muted">未推送·系统暂存</span>`)
    + `</div>`
    + `<div class="fb-meta">${dom}<span class="muted">${t}</span><span class="fb-sev">${SEV_LABEL[it.severity]||""}</span></div>`
    + (body ? `<div class="fb-rev">${body}</div>` : "")
    + fbHumanCorrectionHTML(it)                       // 已有人修正 → 显示对话记录
    + fbCorrectFormHTML(it)                            // 内联修正区（对话式：人在本条下回一句）
    + `<div class="fb-acts">`
    + (it.item_id ? `<button class="soft" data-act="open">查看原文</button>` : "")
    + (it.status==="unread" ? `<button class="soft" data-act="read">标已读</button>` : "")
    + (fbCanApply(it) ? `<button data-act="applied">应用更新</button>` : "")
    + (it.status!=="dismissed" ? `<button class="soft" data-act="dismiss">忽略</button>` : "")
    + (it.review && it.review.type === "near_duplicate" ? `<button class="soft" data-act="notdup">标记为非重复</button>` : "")
    + (it.item_id && !it.human_correction ? `<button class="soft" data-act="correct">修正</button>` : "")
    + `<button class="soft danger" data-act="delete">删除</button>`
    + (!it.item_id ? `<div class="fb-hint muted">此提示针对「条目对关系」，无单篇可应用更新</div>` : "")
    + `</div></div>`;
}

// 人已在同一条反馈下给出修正 → 在反馈下方显示「人原话 + 已落库」，形成对话记录
function fbHumanCorrectionHTML(it){
  const hc = it.human_correction;
  if(!hc || typeof hc !== "object") return "";
  const parts = [];
  if(hc.corrected_domain) parts.push(`<div>· 正确领域：<b>${esc(hc.corrected_domain)}</b></div>`);
  if(hc.corrected_summary) parts.push(`<div>· 正确摘要：<b>${esc(hc.corrected_summary)}</b></div>`);
  if(hc.note) parts.push(`<div>· 意见：${esc(hc.note)}</div>`);
  if(!parts.length) return "";
  const when = hc.at ? new Date(hc.at*1000).toLocaleString("zh-CN",{hour12:false}) : "";
  return `<div class="fb-hc"><div class="fb-hc-h">人修正 · 已落回文章 <span class="muted">${when}</span></div>`
    + parts.join("") + `</div>`;
}

// 内联修正区：点「修正」后就地展开，人填正确领域/摘要/意见，提交即落回
function fbCorrectFormHTML(it){
  if(it.human_correction) return "";   // 已修正过就不再显示表单（避免重复覆盖）
  return `<div class="fb-correct" data-correct-for="${it.id}" hidden>`
    + `<div class="fb-correct-h">在这条反馈下直接修正（系统立即落回文章）：</div>`
    + `<label>正确领域<input type="text" class="fb-c-domain" placeholder="如：社会心理学"></label>`
    + `<label>正确摘要<input type="text" class="fb-c-summary" placeholder="一句话摘要"></label>`
    + `<label>其它意见<textarea class="fb-c-note" placeholder="或其它修正说明（可不填）"></textarea></label>`
    + `<div class="fb-correct-acts">`
    + `<button class="fb-c-submit" data-id="${it.id}">确认修正</button>`
    + `<button class="soft fb-c-cancel">取消</button>`
    + `</div></div>`;
}

function bindFbCards(items){
  const list = $("fbList");
  if(!list) return;
  list.querySelectorAll(".fb-card").forEach(card=>{
    const id = +card.dataset.id;
    const it = items.find(x=>x.id===id) || {};
    card.querySelectorAll("[data-act]").forEach(btn=>{
      btn.onclick = async (e)=>{
        e.stopPropagation();
        const act = btn.dataset.act;
        if(act==="open"){ openFbItem(it); return; }
        if(act==="applied"){ applyFbRevision(it); return; }   // 应用更新 → 生成修订稿 + diff 预览，确认才回写
        if(act==="delete"){
          if(!confirm("确定彻底删除这条反馈？此操作不可恢复。")) return;
          const r = await api("/api/feedback/delete", { id });
          if(r && r.ok){ card.remove(); refreshFeedback(false); }
          else alert("删除失败");
          return;
        }
        if(act==="notdup"){
          const rv = it.review || {};
          if(rv.self_id == null || rv.partner_id == null){ alert("缺少条目 ID，无法标记"); return; }
          if(!confirm("标记为「非重复」？之后健康自检将不再就这一对提醒你。")) return;
          const r = await api("/api/feedback/not_duplicate", { a: rv.self_id, b: rv.partner_id });
          if(r && r.ok){ card.remove(); refreshFeedback(false); }
          else alert("操作失败");
          return;
        }
        if(act==="correct"){
          const box = card.querySelector(`.fb-correct[data-correct-for="${id}"]`);
          if(box) box.hidden = !box.hidden;
          return;
        }
        const map = { read:"/api/feedback/read", dismiss:"/api/feedback/dismiss" };
        if(map[act]){ await api(map[act], { id }); refreshFeedback(false); }
      };
    });
    // 对话式修正：提交 / 取消
    const submit = card.querySelector(".fb-c-submit");
    if(submit){
      submit.onclick = async (e)=>{
        e.stopPropagation();
        const box = card.querySelector(`.fb-correct[data-correct-for="${id}"]`);
        const dom = box.querySelector(".fb-c-domain").value.trim();
        const sum = box.querySelector(".fb-c-summary").value.trim();
        const note = box.querySelector(".fb-c-note").value.trim();
        if(!dom && !sum && !note){ alert("请至少填写一项（正确领域 / 摘要 / 意见）"); return; }
        submit.disabled = true; submit.textContent = "修正中…";
        try{
          const r = await api("/api/feedback/correct",
            { id, corrected_domain: dom, corrected_summary: sum, note });
          if(r && r.ok){
            const what = (r.applied||[]).map(x=>x==="domain"?"领域":"摘要").join("、");
            refreshFeedback(false);
            if(what) alert(`已按你的意见修正 ${what}，并落回文章。`);
            else alert("已记录你的修正意见。");
          } else {
            alert("修正失败：" + ((r&&r.msg) || "未知错误"));
            submit.disabled = false; submit.textContent = "确认修正";
          }
        }catch(err){
          alert("修正失败：" + err.message);
          submit.disabled = false; submit.textContent = "确认修正";
        }
      };
    }
    const cancel = card.querySelector(".fb-c-cancel");
    if(cancel){
      cancel.onclick = (e)=>{ e.stopPropagation();
        const box = card.querySelector(`.fb-correct[data-correct-for="${id}"]`);
        if(box) box.hidden = true;
      };
    }
  });
}

/* ---------------- 应用更新真闭环（生成 → diff 预览 → 确认回写） ---------------- */
async function applyFbRevision(it){
  if(!it.item_id){ alert("该反馈未关联文章，无法应用"); return; }
  const r = await api("/api/feedback/apply", { id: it.id });
  if(!r.ok){ alert("生成修订稿失败：" + (r.msg || "未知错误")); return; }
  showFbApplyModal(it, r);
}

function showFbApplyModal(it, r){
  const m = $("fbApplyModal");
  if(!m) return;
  $("fbApplyOld").value = r.old_content || "";
  $("fbApplyNew").value = r.new_content || "";
  m.classList.add("open");
  const cancel = $("fbApplyCancel");
  const confirm = $("fbApplyConfirm");
  cancel.onclick = ()=> m.classList.remove("open");
  confirm.onclick = async ()=>{
    const newc = $("fbApplyNew").value;
    confirm.disabled = true; confirm.textContent = "应用中…";
    try{
      // 取当前正文版本指纹做并发守卫，避免静默覆盖他人改动
      let rev = null;
      try { const ar = await api("/api/kb/article?id=" + r.item_id); rev = ar.rev || null; } catch(e){}
      const ur = await api("/api/kb/update",
        { item_id: r.item_id, title: r.title, content: newc, rev });
      if(ur.conflict){
        alert("保存冲突：正文已被其它改动更新，请重试应用。"); m.classList.remove("open"); return;
      }
      if(!ur.ok){ alert("应用失败：" + (ur.msg || "未知错误")); return; }
      await api("/api/feedback/applied", { id: it.id });   // 标记为指导的自我更新已采纳
      m.classList.remove("open");
      refreshFeedback(false);
      // 若用户正看着这篇文章，刷新 reader 让修订稿即时可见
      try { if(typeof curId !== "undefined" && curId === r.item_id && typeof openReader === "function") openReader(r.item_id); } catch(e){}
    } finally { confirm.disabled = false; confirm.textContent = "确认应用"; }
  };
}

async function openFbItem(it){
  if(it.item_id){
    try { await openReader(it.item_id); } catch(e){}
  }
  // 打开即视为已读（仅当当前是未读）
  if(it.status === "unread"){
    await api("/api/feedback/read", { id: it.id });
    it.status = "read";
  }
  // 收起面板，回到阅读视图
  _fbPanelOpen = false;
  const p = $("fbPanel"); if(p) p.classList.remove("open");
  refreshFeedback(false);
}
