#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 游标卡尺 —— 真实大模型接入层
纯标准库（urllib / json / hashlib / sqlite3 / threading），OpenAI 兼容 /chat/completions。

═══ 核心设计：两尺独立性由「输入信息隔离」在工程上强制实现 ═══

schema 规定 main.signal_family != vernier.signal_family。但如果两尺都去问同一个
大模型，仅靠 prompt 措辞区分，读数必然高度相关 —— 偏移退化为噪声，闭环破产。

所以这里在【输入层】做真隔离：
  · 主尺（学科领域）: 输入 = strip_logic(text)  —— 抹掉全部论证连接词与量化词，
    模型只看得到主题词，看不到"这段推理有多严密"。
  · 游标（演绎深度）: 输入 = mask_domain(text) —— 全部实义词替换为 甲/乙/丙 变量符号，
    只留论证骨架，模型根本不知道这段属于什么学科。

两路模型看不到对方赖以判断的信息，读数才可能真正不相关（r→0），偏移才携带信息。
这是把「两尺必须独立」从告诫落成机制。
"""

import concurrent.futures
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DB = os.path.join(BASE, "llm_cache.db")

# ------------------------------------------------------------------ 配置

CONFIG_PATH = os.path.join(BASE, "llm_config.json")   # 用户自定义配置（覆盖 .env）
_DEFAULT_BASE = "https://api.openai.com/v1"

# 运行期可变配置：用户可在「设置」页面修改，无需改代码 / 重启服务。
_cfg = {
    "api_key": "",
    "api_base": _DEFAULT_BASE,
    "model": "gpt-4o-mini",
    "_source": "(none)",
}


def load_env():
    """启动时读取 .env：仅从知识库自身目录（BASE/.env）加载凭据默认值；
    用户自定义的 llm_config.json 优先级更高（见 _load_config）。
    KB 不依赖任何外部目录。"""
    candidates = [
        os.path.join(BASE, ".env"),
    ]
    cfg = {}
    for path in candidates:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
                if m and m.group(1) not in cfg:
                    cfg[m.group(1)] = m.group(2).strip().strip("\"'")
        if cfg.get("API_KEY"):
            cfg["_source"] = path
            break
    return cfg


def _load_config():
    """合并配置：.env 默认值 → 用户自定义 llm_config.json（优先）。"""
    env = load_env()
    _cfg["api_key"] = env.get("API_KEY", "")
    _cfg["api_base"] = env.get("API_BASE", _DEFAULT_BASE).rstrip("/")
    _cfg["model"] = env.get("MODEL", "gpt-4o-mini")
    _cfg["_source"] = env.get("_source", "(none)")
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                u = json.load(f)
            if isinstance(u, dict):
                _cfg["api_key"] = u.get("api_key", _cfg["api_key"])
                _cfg["api_base"] = (u.get("api_base") or _cfg["api_base"]).rstrip("/")
                _cfg["model"] = u.get("model") or _cfg["model"]
                _cfg["_source"] = CONFIG_PATH
        except Exception:                      # noqa: BLE001
            pass


# 形如 abcd****wxyz 的掩码占位（用户没改密钥时回传，避免覆盖原值）
_KEY_MASK = re.compile(r"^[A-Za-z0-9_\-]{3,}\*{2,}[A-Za-z0-9]{1,6}$")


def _sync_globals():
    """把运行期配置同步到模块全局变量（chat / embed 直接读这些全局）。"""
    global API_KEY, API_BASE, MODEL, AVAILABLE, ENV_SOURCE
    API_KEY = _cfg["api_key"]
    API_BASE = _cfg["api_base"]
    MODEL = _cfg["model"]
    ENV_SOURCE = _cfg["_source"]
    AVAILABLE = bool(API_KEY)


_load_config()
_sync_globals()


# ---------------------------------------------------- 运行期可改配置（设置页用）

def get_config():
    """当前生效的模型配置（密钥只回显掩码，不泄露原文）。"""
    return {
        "api_base": API_BASE,
        "model": MODEL,
        "key_masked": masked_key(),
        "api_key_set": bool(API_KEY),
        "available": AVAILABLE,
        "source": ENV_SOURCE,
    }


def apply_config(d):
    """运行期更新「模型 / 端点 / 密钥」并持久化到 llm_config.json（覆盖 .env）。

    返回更新后的配置。密钥若传回的是掩码占位（表示用户没改），保留原值。
    """
    global _breaker
    key = (d.get("api_key") or "").strip()
    if key and not _KEY_MASK.match(key):           # 非掩码 → 真的新密钥
        _cfg["api_key"] = key
    if d.get("api_base"):
        _cfg["api_base"] = d["api_base"].strip().rstrip("/")
    if d.get("model"):
        _cfg["model"] = d["model"].strip()
    _cfg["_source"] = CONFIG_PATH
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"api_base": _cfg["api_base"], "api_key": _cfg["api_key"],
                   "model": _cfg["model"]}, f, ensure_ascii=False, indent=2)
    _sync_globals()
    _breaker = {"fails": 0, "until": 0.0}           # 换了凭据/端点：清掉旧熔断
    return get_config()


def test_connection(d=None):
    """用给定（或当前）配置做一次最小对话调用，验证端点+密钥+模型可用。

    测试不持久化、不污染全局熔断状态 —— 用完即还原。
    """
    saved_cfg = dict(_cfg)
    saved_breaker = dict(_breaker)
    try:
        if d:
            key = (d.get("api_key") or "").strip()
            if key and not _KEY_MASK.match(key):
                _cfg["api_key"] = key
            if d.get("api_base"):
                _cfg["api_base"] = d["api_base"].strip().rstrip("/")
            if d.get("model"):
                _cfg["model"] = d["model"].strip()
            _sync_globals()
        if not API_KEY:
            return {"ok": False, "error": "未填写 API 密钥"}
        out, _cached = chat("你是连接测试助手。只回复两个字：成功。",
                            "测试模型连接", temperature=0.0,
                            max_tokens=8, timeout=15)
        return {"ok": True, "model": MODEL, "api_base": API_BASE,
                "reply": out[:40]}
    except Exception as e:                          # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}
    finally:
        _cfg.clear(); _cfg.update(saved_cfg); _sync_globals()
        _breaker.clear(); _breaker.update(saved_breaker)

TIMEOUT = 120          # 推理模型单次实测 ~25s，留足余量
RETRIES = 3

# 全局熔断状态：接口不通时避免每次调用都空等 TIMEOUT×RETRIES。
# 由 chat() 维护，breaker_state() 供上层展示。
_breaker = {"fails": 0, "until": 0.0}
RATE_MAX = 16          # 每分钟上限，留余量
RATE_WINDOW = 60.0

_rate_lock = threading.Lock()
_recent = []
_cache_lock = threading.Lock()


def masked_key():
    if not API_KEY:
        return "(未配置)"
    return f"{API_KEY[:7]}****{API_KEY[-4:]}"


# ------------------------------------------------------------ 缓存（省钱）

def _cache_init():
    con = sqlite3.connect(CACHE_DB)
    con.execute("CREATE TABLE IF NOT EXISTS cache("
                "k TEXT PRIMARY KEY, v TEXT NOT NULL, created_at REAL NOT NULL)")
    con.commit()
    con.close()


def _cache_get(k):
    with _cache_lock:
        con = sqlite3.connect(CACHE_DB)
        row = con.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
        con.close()
    return row[0] if row else None


def _cache_put(k, v):
    with _cache_lock:
        con = sqlite3.connect(CACHE_DB)
        con.execute("INSERT OR REPLACE INTO cache(k,v,created_at) VALUES(?,?,?)",
                    (k, v, time.time()))
        con.commit()
        con.close()


def cache_stats():
    _cache_init()
    con = sqlite3.connect(CACHE_DB)
    n = con.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    con.close()
    return n


# ------------------------------------------------------------- 调用

def _throttle():
    while True:
        with _rate_lock:
            now = time.time()
            while _recent and now - _recent[0] >= RATE_WINDOW:
                _recent.pop(0)
            if len(_recent) < RATE_MAX:
                _recent.append(now)
                return
            wait = RATE_WINDOW - (now - _recent[0]) + 0.5
        time.sleep(wait)


def chat(system, user, temperature=0.0, max_tokens=600, use_cache=True,
         timeout=None, retries=None):
    """OpenAI 兼容对话调用，带缓存 / 限流 / 超时 / 重试。

    timeout / retries 可单独指定：附加性质的调用（如保存时顺带生成摘要）
    应给一个短预算，避免主流程被慢接口拖住。
    """
    _timeout = TIMEOUT if timeout is None else timeout
    _retries = RETRIES if retries is None else max(1, int(retries))
    if not AVAILABLE:
        raise RuntimeError("未配置 API_KEY，无法调用真实模型")
    _cache_init()
    key = hashlib.sha1(
        f"{MODEL}\x00{temperature}\x00{system}\x00{user}".encode("utf-8")
    ).hexdigest()
    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return hit, True                       # 缓存命中不受熔断影响

    # 熔断：接口不通时，每次调用都白等 timeout×retries。一旦连续失败，
    # 在退避窗口内直接抛错，让上层立刻降级到规则/离线路径，而不是干等。
    now = time.time()
    if now < _breaker["until"]:
        raise RuntimeError(
            "模型接口暂不可用（熔断中，%d 秒后重试）" % int(_breaker["until"] - now))

    payload = json.dumps({
        "model": MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")

    last = None
    for attempt in range(_retries):
        _throttle()
        req = urllib.request.Request(
            f"{API_BASE}/chat/completions", data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {API_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            content = content.strip()
            if not content:
                raise RuntimeError("模型返回空 content（推理模型偶发只吐 reasoning）")
            if use_cache:
                _cache_put(key, content)
            _breaker["fails"] = 0                       # 通了就复位
            _breaker["until"] = 0.0
            return content, False
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            last = RuntimeError(f"HTTP {e.code}: {body}")
            if re.search(r"insufficient|quota|余额|额度|balance", body, re.I):
                raise last                              # 额度问题不重试
            if attempt + 1 < _retries:
                time.sleep(2.0 * (attempt + 1))
        except Exception as e:                          # noqa: BLE001
            last = e
            if attempt + 1 < _retries:
                time.sleep(1.5 * (attempt + 1))
    _breaker["fails"] += 1
    # 30s → 60s → 120s …最多 10 分钟；期间所有调用立即失败，不再空等网络
    _breaker["until"] = time.time() + min(600, 30 * 2 ** (_breaker["fails"] - 1))
    raise last


def breaker_state():
    """当前熔断状态，供界面说明「为什么走的是规则/离线路径」。"""
    left = max(0, int(_breaker["until"] - time.time()))
    return {"open": left > 0, "fails": _breaker["fails"], "retry_in": left}


def parse_json(text):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            return json.loads(m.group(0))
        raise


# ═══════════════════════════════════════════════════════════════════
#  信息隔离过滤器 —— 两尺独立性的工程根基
# ═══════════════════════════════════════════════════════════════════

# 论证功能词：主尺看不到它们；游标只看得到它们
FUNCTION_WORDS = [
    # 因果 / 推导
    "因为", "所以", "因此", "由此", "从而", "进而", "故而", "是故", "综上",
    "根据", "据此", "推导", "推论", "推出", "得出", "可见", "故", "则",
    # 条件 / 假设
    "如果", "假设", "假定", "倘若", "只要", "只有", "除非", "那么", "否则",
    "当且仅当", "充分", "必要", "前提", "结论", "反之", "若",
    # 量化 / 模态
    "所有", "任一", "任意", "每个", "至少", "至多", "存在", "不存在",
    "仅当", "唯一", "普遍", "必然", "可能", "必须", "应当",
    # 逻辑联结 / 系词
    "并且", "或者", "但是", "然而", "而且", "不过", "同时", "等价于",
    "属于", "大于", "小于", "等于", "不等于", "于是", "无论", "即使",
    "尽管", "以及", "成立", "不成立", "矛盾", "一致",
    # 单字功能词（仅收录极少混入复合实义词的，避免把「均衡/有机/无穷」切碎）
    "若", "则", "故", "皆", "是", "非",
]
# 长词优先匹配，避免 "是" 抢在 "是故"/"但是" 前面
_FW_SORTED = sorted(set(FUNCTION_WORDS), key=len, reverse=True)
_PUNCT = "，。；、,.;!?！？：:（）()「」“”‘’《》\n\t "
_VARS = list("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉")


def _tokenize(text):
    """把文本切成 (kind, token) 序列：kind ∈ {func, content, punct}。"""
    toks, buf = [], []

    def flush():
        if buf:
            toks.append(("content", "".join(buf)))
            buf.clear()

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in _PUNCT:
            flush()
            toks.append(("punct", ch))
            i += 1
            continue
        matched = next((w for w in _FW_SORTED if text.startswith(w, i)), None)
        if matched:
            flush()
            toks.append(("func", matched))
            i += len(matched)
        else:
            buf.append(ch)
            i += 1
    flush()
    return toks


def mask_domain(text):
    """
    游标的输入：只保留【功能词 + 标点】，实义词一律替换为 甲/乙/丙 变量符号。
    同一实义词映射到同一符号，故指代结构（三段论骨架）完整保留，
    但模型无从得知这段属于哪个学科。
    """
    out, mapping = [], {}
    for kind, tok in _tokenize(text):
        if kind == "content":
            if tok not in mapping:
                idx = len(mapping)
                mapping[tok] = _VARS[idx % len(_VARS)] + (
                    str(idx // len(_VARS)) if idx >= len(_VARS) else "")
            out.append(mapping[tok])
        else:
            out.append(tok)
    return "".join(out)


def strip_logic(text):
    """
    主尺的输入：只保留【实义词】，功能词一律丢弃。

    与 mask_domain 构成严格互补切分 —— 两路输入的 token 集合完全不相交：
    主尺拿到全部主题信息、零论证信息；游标拿到全部论证信息、零主题信息。
    这不是 prompt 层的君子协定，是输入层的硬隔离。
    """
    out = []
    for kind, tok in _tokenize(text):
        if kind == "content":
            out.append(tok)
        elif kind == "punct" and tok in "，。；\n":
            out.append(" ")
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


# ═══════════════════════════════════════════════════════════════════
#  两尺的真实 provider
# ═══════════════════════════════════════════════════════════════════

def _main_system(domains):
    """动态领域归纳 prompt：归入已有领域，或自创新领域 —— 学科体系由内容长出来。"""
    if domains:
        lines = "\n".join(
            f"  - {d['name']}（代表词：{'、'.join(d['reps'][:6]) or '暂无'}，位于 {d['center']} 附近）"
            for d in domains)
        rules = (
            "当前知识库中已有的领域：\n" + lines + "\n\n"
            "规则：\n"
            "1. 若文本主题与某个已有领域实质一致，就归入它（用它的名字）。\n"
            "2. 若都不匹配，发明一个新领域名（2-8 个汉字）。\n"
            "   【关键】领域名必须是「学科 / 主题领域」这种够宽、能容纳多条不同\n"
            "   内容的范畴（如「信息检索」「人工智能」「认知科学」「组织行为」），\n"
            "   **绝不能用某项具体技术、方法、模型或实体当领域名** —— 例如讲 RAG、\n"
            "   「重叠窗口」、梯度下降、某个框架的文章，应归入其上位学科领域，\n"
            "   把具体技术留在正文要点里，而不是自立为「领域」。\n"
            "   避免「综合」「其他」「杂项」这类空名，也不要用「RAG」「向量」这种词。\n"
            "3. 【守门阈值】先数待分类文本命中了某个领域几个「代表词」：\n"
            "   命中 ≥ 2 个才归入/立该领域；命中 < 2 个说明文本只聊某项具体技术/实体，\n"
            "   **不立领域**，退回其上位学科领域（讲 RAG→归「信息检索」），技术进标签。\n"
            "4. 【防过粗】不要把主题仅名义相关、代表词重叠度低的内容硬塞进同一主干带；\n"
            "   若文本明显属于某个更贴的细学科，应另立该细领域，而非强塞主干带。"
        )
    else:
        rules = ("当前库还没有任何领域。请发明一个新领域名（2-8 个汉字）。\n"
                 "   【关键】领域名必须是「学科 / 主题领域」这种够宽的范畴\n"
                 "   （如「信息检索」「人工智能」「认知科学」），**不要**用某项具体技术、\n"
                 "   方法或实体（如「RAG」「重叠窗口」「梯度下降」）当领域名；\n"
                 "   若文本只讲一项技术，请给出它所属的上位学科领域名。\n"
                 "   避免「综合」「其他」「杂项」这类空名。")
    return (
        "你是知识领域归纳器。仅依据文本的【主题词汇】判断它属于什么知识领域，\n"
        "严禁评估其论证是否严密、推理是否形式化 —— 那是另一把尺子的事，与你无关。\n"
        "（输入文本已被系统抹去论证连接词，以「·」占位，请忽略这些占位符。）\n\n"
        f"{rules}\n\n"
        "position：0-100 的谱系位置。归入已有领域时靠近该领域中心（±15 内）；"
        "新领域则自行定一个合理位置。\n"
        "只输出严格 JSON，不要任何解释文字：\n"
        '{"band":"领域名","position":数字,"confidence":0到1的小数,"reason":"20字内"}'
    )


VERNIER_SYSTEM = (
    "你是逻辑演绎深度评估器。你将看到一段【已抹去全部学科词汇】的论证骨架：\n"
    "所有实义名词都被替换成了 甲/乙/丙 等变量符号，只保留论证连接词与句法结构。\n"
    "严禁猜测这段文字属于什么学科、讲的是什么内容 —— 那是另一把尺子的事，与你无关。\n"
    "你只评估一件事：它的推理形态有多形式化。\n\n"
    "0-100 刻度锚点：\n"
    "  0-20   纯描述 / 叙事，无推理动作\n"
    "  20-40  归纳举证，靠例子支撑\n"
    "  40-60  条件推断，出现 若…则… 结构\n"
    "  60-80  结构化论证，前提→推论→结论链条完整\n"
    "  80-100 形式化证明，含量化词、充要条件、公理化表述\n\n"
    "只输出严格 JSON，不要任何解释文字：\n"
    '{"depth":数字,"confidence":0到1的小数,"reason":"20字内"}'
)


def measure_main_llm(content, domains):
    """主尺（阳·感知归类）：真实大模型做知识领域归纳 —— 归入已有领域或自创新领域。"""
    payload = strip_logic(content)
    raw, cached = chat(_main_system(domains), f"待分类文本：\n{payload}")
    d = parse_json(raw)
    name = str(d.get("band", "")).strip()
    cur = next((x for x in domains if x["name"] == name), None) if domains else None
    if not name:
        name = cur["name"] if cur else (domains[0]["name"] if domains else "未分类")
    try:
        pos = float(d.get("position", (cur or {}).get("center", 50.0)))
    except (TypeError, ValueError):
        pos = (cur or {}).get("center", 50.0)
    if cur:                                        # 归入已有领域：靠拢其中心，保持同领域聚拢
        pos = cur["center"] + max(-15.0, min(15.0, pos - cur["center"]))
    pos = max(0.0, min(100.0, pos))
    conf = float(d.get("confidence", 0.5) or 0.5)
    return {"band": name, "pos": round(pos, 1),
            "conf": round(max(0.0, min(1.0, conf)), 3),
            "reason": str(d.get("reason", ""))[:40], "cached": cached,
            "input_preview": payload[:60]}


def measure_vernier_llm(content):
    """游标（阴·深层推理）：真实大模型评估演绎深度，输入已抹去学科身份。"""
    payload = mask_domain(content)
    raw, cached = chat(VERNIER_SYSTEM, f"待评估论证骨架：\n{payload}")
    d = parse_json(raw)
    try:
        depth = float(d.get("depth", 0))
    except (TypeError, ValueError):
        depth = 0.0
    conf = float(d.get("confidence", 0.5) or 0.5)
    return {"depth": round(max(0.0, min(100.0, depth)), 1),
            "conf": round(max(0.0, min(1.0, conf)), 3),
            "reason": str(d.get("reason", ""))[:40], "cached": cached,
            "input_preview": payload[:60]}


def measure_pair(content, domains):
    """并发跑两尺（互不传递信息）。domains=当前动态领域列表。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        fm = ex.submit(measure_main_llm, content, domains)
        fv = ex.submit(measure_vernier_llm, content)
        return fm.result(), fv.result()


def info():
    return {"available": AVAILABLE, "model": MODEL, "api_base": API_BASE,
            "key": masked_key(), "env_source": ENV_SOURCE,
            "cached_calls": cache_stats() if AVAILABLE else 0}


_EMB_DIM = 64
# 对话模型"写向量"实测判别力极差（无关条目相似度也 0.8+，检索结果明显错误），
# 默认关闭；只有 /embeddings 接口可用时才用真实模型向量，否则上层回退本地向量。
# 当前 provider（agnes-2.5-flash）无 /embeddings 接口，embed() 必然失败 → 全库退回 256 维
# 本地哈希，导致语义发现（设计上只在真实 embedding 在线时跑）被永久跳过、知识图谱无任何连线。
# 故为这类 provider 打开应急开关：用对话模型直接产出 64 维语义向量（判别力弱于真实 embedding，
# 但足以支撑同主题聚类的软链发现）。
EMBED_CHAT_FALLBACK = True
_EMB_SYS = ("你是一个文本语义向量化工具。把下面的文本编码成一个 %d 维的语义向量"
            "（数值在 -1 到 1 之间）。只输出一个 JSON 数组，共 %d 个数字，"
            "不要任何其它文字或解释。") % (_EMB_DIM, _EMB_DIM)


def _embed_via_chat(text, timeout):
    """用对话模型生成语义向量：agnes 无 /embeddings 接口，让模型直接产出固定维向量。
    输出可能多/少一两个数，这里统一截断/补零到 _EMB_DIM 再 L2 归一化，保证跨条目可比。"""
    out, _cached = chat(_EMB_SYS, (text or "")[:800], temperature=0.0,
                        max_tokens=1200, timeout=timeout)
    # 容忍模型输出未用 ] 闭合（被 max_tokens 截断）或夹带多余文字：
    # 直接抓「[」后的连续数字序列，取前 _EMB_DIM 个，避免「向量输出不可解析」误杀。
    m = re.search(r"\[([-\d.,\s]+)", out)
    if not m:
        raise RuntimeError("向量输出不可解析")
    arr = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m.group(1))]
    if not isinstance(arr, list) or not arr or \
            not all(isinstance(x, (int, float)) for x in arr):
        raise RuntimeError("向量格式错误")
    vec = [float(x) for x in arr[:_EMB_DIM]]
    while len(vec) < _EMB_DIM:
        vec.append(0.0)
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def embed(text, model=None, timeout=None):
    """返回文本的语义向量。
    优先走真实 /embeddings 接口；该接口不可用（如 agnes 无 embedding 模型）时，
    退回用对话模型生成固定 64 维向量；两者都失败则抛异常（由调用方退回本地向量）。

    timeout 可单独指定：后台补算时给短预算，避免慢接口拖住整条链路。
    """
    if not AVAILABLE:
        raise RuntimeError("未配置 API_KEY，无法调用 embedding 接口")
    _timeout = TIMEOUT if timeout is None else timeout
    key = "emb:" + hashlib.sha1((text or "").encode("utf-8")).hexdigest()
    hit = _cache_get(key)
    if hit is not None:                      # 内容哈希命中缓存：不重复计费
        try:
            return json.loads(hit)
        except Exception:                    # noqa: BLE001
            pass
    # 1) 真实 embedding 接口
    try:
        payload = json.dumps({
            "model": model or MODEL,
            "input": text,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/embeddings", data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {API_KEY}"})
        with urllib.request.urlopen(req, timeout=_timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        arr = (data.get("data") or [{}])[0].get("embedding")
        if arr:
            _cache_put(key, json.dumps(arr))
            return arr
    except Exception:                        # noqa: BLE001
        pass
    # 2) 对话模型生成语义向量（默认关闭：实测判别力差，仅 /embeddings 不可用时的应急开关）
    if EMBED_CHAT_FALLBACK:
        v = _embed_via_chat(text, _timeout)
        _cache_put(key, json.dumps(v))
        return v
    raise RuntimeError("embedding 接口不可用（当前模型不支持 /embeddings）")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("配置：", json.dumps(info(), ensure_ascii=False, indent=2))
    demo = "因为人皆会死，所以苏格拉底会死；若甲是乙则丙，综上推论其必然成立，前提充分且必要。"
    print("\n原文      ：", demo)
    print("主尺看到的：", strip_logic(demo))
    print("游标看到的：", mask_domain(demo))
    demo2 = "假设市场出清，若价格上升则需求下降，由此推论均衡存在；根据模型推导，综上必然收敛。"
    print("\n原文      ：", demo2)
    print("主尺看到的：", strip_logic(demo2))
    print("游标看到的：", mask_domain(demo2))
