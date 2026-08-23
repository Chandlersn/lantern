# -*- coding: utf-8 -*-
"""真实大模型摘要（带熔断与本地兜底）。"""

import re
import time
import collections

def local_summarize(content):
    """离线兜底摘要：取首句做概要，按词频挑标签。不依赖网络，保存必定有结果。"""
    text = (content or "").strip()
    if not text:
        return None, None
    # 摘要取第一个完整陈述句。需先剥离开头的 markdown 标题/空行/纯标题行，
    # 否则文章以「# 标题」或标题式短语开头时，摘要会退化成标题而非陈述。
    # 步骤：① 去掉每行前导 # 号（markdown 标题标记）；② 跳过空行与「像标题」的短行
    #      （无句末标点、长度≤20、且不以陈述符结尾）；③ 取第一个以陈述符收尾的句子。
    _MD = re.compile(r"^\s{0,3}#{1,6}\s*")          # 行首 markdown 标题 # 号
    _STMT = re.compile(r"[。！；.!;]")               # 陈述句收尾符
    _TITLEISH = re.compile(r"[？?：:]")              # 问句/冒号标题式收尾（不取作摘要）
    cleaned_lines = []
    for line in text.splitlines():
        line = _MD.sub("", line).strip()            # 剥 # 号
        if not line:
            continue
        cleaned_lines.append(line)
    # 跳过开头「像标题」的行（无陈述符收尾、且含问号/冒号或偏短），定位正文起始
    start = 0
    for i, line in enumerate(cleaned_lines):
        looks_title = (not _STMT.search(line)) and (
            _TITLEISH.search(line) or len(line) <= 20)
        if looks_title:
            start = i + 1
        else:
            break
    body = "\n".join(cleaned_lines[start:]) or "\n".join(cleaned_lines)
    # _SENT 已按句末标点（。！？；等）切分，切出的非空片段原本都以句末标点收尾，
    # 故它们都是「完整句候选」；句末标点已被切掉，无需再判 _STMT。
    # 优先选「不以连词/因果词开头」的独立陈述句，避免摘要以「因为/所以/但是」起头。
    _LEAD = re.compile(r"^(因为|所以|但是|然而|于是|而且|并且|如果|虽然|尽管|换句话说|也就是说|即|但)")
    sentences = [c.strip() for c in _SENT.split(body) if c.strip()]
    standalone = [s for s in sentences if not _LEAD.match(s)]
    stmt = (standalone or sentences or [None])[0]
    if stmt is None:
        # 全文无句子（极端情况）：取最长非标题行兜底
        stmt = max(cleaned_lines, key=len) if cleaned_lines else ""
    summary = re.sub(r"[*_`>#]", "", stmt).strip()  # 清残留 markdown 符号
    summary = summary[:40] + ("…" if len(summary) > 40 else "")

    # 标签候选：中文连续片段 + 英文词。英文词整体保留；中文长片段才切二元组
    grams = collections.Counter()
    for seg in re.findall(r"[一-鿿]+|[A-Za-z][A-Za-z0-9_\-]{2,}", text):
        if not _CJK.match(seg):                    # 英文词永远整体计数，不切碎
            grams[seg.lower()] += 2.0
        elif len(seg) <= 4:
            grams[seg] += 2.0                      # 完整中文词组权重更高
        else:
            # 长中文片段无法真正分词，只能滑窗取二元组；
            # 含虚字的组合（"是白""色的"）直接丢弃，剩下的还要求复现过才算数
            for i in range(len(seg) - 1):
                w = seg[i:i + 2]
                if w in _STOP or (set(w) & _FUNC):
                    continue
                grams[w] += 1.0
    def clashes(w, p):
        if w in p or p in w:                       # 「相对论」已选则丢掉「对论」
            return True
        if _CJK.match(w) and _CJK.match(p):        # 中文再按共享字去重，避免滑窗碎片
            return bool(set(w) & set(p))
        return False

    def is_strong(w, c):
        """复现过的、或本来就是完整词的，才算可靠候选。"""
        return c >= 2 or not _CJK.match(w) or len(w) > 2

    picked = []
    # 先取可靠候选；不足 2 个时再放宽，宁可弱一点也别让标签栏空着
    for relaxed in (False, True):
        for w, c in grams.most_common(40):
            if len(picked) >= 3:
                break
            if w in _STOP or w in picked:
                continue
            if not relaxed and not is_strong(w, c):
                continue
            if any(clashes(w, p) for p in picked):
                continue
            picked.append(w)
        if len(picked) >= 2:
            break
    return (summary or None), (",".join(picked) or None)

def summarize(content, timeout=25, retries=1):
    """一句话摘要 + 关键词标签。优先真实大模型；不可用/超时则退回离线兜底。

    保存时顺带做，属附加能力 —— 给短预算，且连续失败后熔断，绝不拖慢主流程。
    """
    now = time.time()
    if LLM_OK and now >= _sum_breaker["until"]:
        sys_p = ("你是知识整理助手。用一句话（≤30字）概括下面这段知识的要点，"
                 "并给出 2-4 个关键词标签（逗号分隔）。只输出严格 JSON："
                 '{"summary":"…","tags":"标签1,标签2"}')
        usr = "内容：\n" + (content or "")[:1400]
        try:
            raw, _ = _llm.chat(sys_p, usr, temperature=0.2, max_tokens=200,
                               timeout=timeout, retries=retries)
            d = _llm.parse_json(raw)
            s = (d.get("summary") or d.get("摘要") or "").strip()
            tg = d.get("tags") or d.get("标签") or ""
            if isinstance(tg, list):
                tg = ",".join(tg)
            if s:
                _sum_breaker["fails"] = 0
                _sum_breaker["until"] = 0.0
                return s, (tg.strip() or None)
        except Exception:                          # noqa: BLE001
            _sum_breaker["fails"] += 1
            # 退避 60s / 120s / 240s …（上限 10 分钟），期间直接走离线兜底
            _sum_breaker["until"] = now + min(600, 60 * 2 ** (_sum_breaker["fails"] - 1))
    return local_summarize(content)

def summary_backend():
    """当前摘要走哪条路：真实模型 / 离线兜底（含熔断剩余秒数）。"""
    left = max(0, int(_sum_breaker["until"] - time.time()))
    if not LLM_OK:
        return {"backend": "local", "reason": "未配置模型接口"}
    if left:
        return {"backend": "local", "reason": f"模型接口连续失败，{left}s 后重试"}
    return {"backend": "llm", "reason": ""}


_MD_RESIDUE = re.compile(r"[*_`>#~\-]{1,}")      # markdown 残留符号
_TAIL_PUNCT = re.compile(r"^[，。、；：:,.!?！？\s]+|[，。、；：:,.!?！？\s]+$")


def sanitize_summary(text, max_len=80):
    """L0 收口（A2 · 入库校验）：把任意来源（LLM / 本地兜底）的摘要归一化为

    满足 DOMAIN_CLASSIFICATION_CONTRACT §7 的 L0 字段——纯陈述、无 markdown 残留、
    长度 ≤ max_len 汉字、非空。落库前最后一道关，保证无论模型怎么抽风，写进
    items.summary 的一定是合规的一句人话。

    返回清洗后的字符串；若清洗后为空（极罕见，如原文全为符号），返回 None，
    由调用方回到「首句 / 标题」兜底，不允许空 summary 落库。
    """
    if not text:
        return None
    s = _MD_RESIDUE.sub("", text)                 # 去 markdown 符号
    s = re.sub(r"\s+", " ", s).strip()            # 折叠空白
    s = _TAIL_PUNCT.sub("", s)                    # 去首尾标点/空白
    if not s:
        return None
    # 长度约束：优先在句末标点处断，避免硬切中文词；无标点则按字符截断。
    if len(s) > max_len:
        cut = s[:max_len]
        m = re.search(r"[。！？!?；;，,、\s]", cut[::-1])   # 从末尾向前找最近断点
        if m:
            cut = cut[:max_len - m.start()]
        s = cut.rstrip("，。、；:：,.; ") + "…"
    return s

