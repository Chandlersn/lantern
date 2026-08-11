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
    # 摘要取第一个完整句子（只按句末标点断，不按空格/逗号断）
    first = next((c.strip() for c in _SENT.split(text) if c.strip()), "")
    summary = first[:40] + ("…" if len(first) > 40 else "")

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

