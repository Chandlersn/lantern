# -*- coding: utf-8 -*-
"""灯笼 · 多维轴知识库 —— 核心持久化层（连接 / 迁移 / 元信息 / 快照 / 阈值与模式 / 调试）。"""

import json
import math
import os
import re
import sqlite3
import time
import hashlib
import collections
import binascii
import concurrent.futures
import threading
import sys
import subprocess
import ctypes
from ctypes import wintypes

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 · 游标卡尺 —— 持久化与度量层
仅使用 Python 标准库（sqlite3 / json / re / math），贴合灯笼框架技术栈。

设计要点：
  1. 双尺读数分行存入 readings 表，各带 provider 与 signal_family（语义标签）。
     注：本系统两尺当前同源（llm 共用模型 / 启发式共用本地函数），signal_family
     仅为语义标签，独立性靠实证皮尔逊相关 r 持续监测，并在坍缩时拦截自动写入。
  2. edges 表即知识图谱的候选边表：卡尺管发现，图谱管确定。
  3. calibrate() 修复了原型 v2 的收敛缺陷：主尺移动后必须重新判定所属领域带，
     typical 随之改变，偏移才可能真正收敛。
"""

import json
import math
import os
import re
import sqlite3
import time
import hashlib
import collections
import binascii
import concurrent.futures
import threading
import sys
import subprocess
import ctypes
from ctypes import wintypes

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "lantern.db")
SCHEMA_PATH = os.path.join(BASE, "schema.json")
# 本地文章文件镜像目录：每条知识对应 articles/<id>.md，人可读、可外部编辑。
ARTICLES_DIR = os.path.join(BASE, "articles")

# 后台补算线程池：保存时同步只做「本地启发式定位 + 落库」，把慢的模型推理
# （双尺读数 / 向量 / 摘要）挪到后台线程，让 HTTP 响应秒回。模型通时约 80s 的
# 干等由此消除；模型不通时后台自动退回本地，前台完全无感。
_refine_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="refine")

# 共现软边发现锁：写后自动发现(_refine) 与 服务端周期扫描(server 守护线程) 都走
# refresh_soft_links → suggest_links(persist=True)，用同一把锁防止两者并发重算互相踩。
_discovery_lock = threading.Lock()



# ---- 提升的顶层常量/配置（原 store.py 散落于 def 之间） ----
with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    SCHEMA = json.load(f)

BANDS = SCHEMA["scales"]["main"]["bands"]

MAIN_PROVIDER = SCHEMA["scales"]["main"]["provider"]

VERNIER_PROVIDER = SCHEMA["scales"]["vernier"]["provider"]

DEFAULT_THRESHOLD = SCHEMA["collision"]["threshold"]["default"]

MAX_ITER = SCHEMA["closure"]["convergence"]["max_iterations"]

DOMAIN_REGISTRY = SCHEMA["scales"]["main"].get("domain_registry", {})

_DOMAIN_REGISTRY = {k: v for k, v in DOMAIN_REGISTRY.items()
                    if isinstance(v, dict) and "band" in v}

DOMAIN_LEXICON = {
    "人文": ["文学", "诗", "意境", "审美", "叙事", "哲学", "历史", "艺术",
             "文化", "情感", "思想", "伦理", "语言"],
    "社会科学": ["经济", "市场", "社会", "政策", "均衡", "人口", "组织",
                 "法律", "政治", "制度", "判决", "价格", "需求", "被告"],
    "自然科学": ["物理", "化学", "生物", "进化", "实验", "能量", "细胞",
                 "量子", "自然", "物种", "神经", "观测", "动量", "代谢"],
    "形式科学": ["集合", "算法", "函数", "数学", "计算", "拓扑", "概率",
                 "矩阵", "图灵", "复杂度", "范畴", "数论"],
}

BACKBONE_BANDS = [dict(b) for b in BANDS]            # 人文/社科/自科/形式科学（永远在）

_DOMAIN_NARROW = set(
    "窗口 算法 模型 框架 协议 向量 检索 数据库 接口 函数 模块 缓存 索引 分词 "
    "模板 插件 组件 实例 节点 会话 仓库 中间件 管线 工作流 提示词 词元 嵌入 "
    "梯度 损失 卷积 注意力 归一化 量化 采样 蒸馏 采样率 比特 字节 编码器 解码器 "
    "分块 切分 编码 训练 微调 召回 重排 对齐 聚类 分类 回归 预测 生成 推理 "
    "下降 表征 特征 微调 增强 优化 部署 评测 "
    "rag gpt llm ai api sdk sql nlp cv gpu tpu".split()
)

_DOMAIN_ALLOW = set(
    "信息检索 机器学习 深度学习 强化学习 计算机视觉 自然语言处理 知识工程 "
    "认知科学 计算神经科学 组织行为 量子信息 人工智能 数据科学 软件工程 "
    "网络安全 控制系统 运筹学 统计学 应用数学 理论物理 凝聚态物理 分子生物 "
    "发展心理学 社会心理学 宏观经济学 微观经济学 政治学 法学 语言学 比较文学".split())

LOGIC_MARKERS = [
    "因为", "所以", "因此", "若", "则", "假设", "推论", "由此", "综上",
    "根据", "必然", "等价于", "推导", "反之", "故", "可见",
    "前提", "结论", "充分", "必要", "当且仅当",
]

QUANTIFIERS = ["所有", "任一", "任意", "每个", "至少", "至多",
               "存在", "不存在", "仅当", "唯一", "普遍"]

_SPLIT = re.compile(r"[\s，。；、,.;!?！？：:（）()\[\]【】\n\t]+")

try:
    import llm as _llm
    LLM_OK = _llm.AVAILABLE
except Exception:                                   # noqa: BLE001
    _llm, LLM_OK = None, False

LLM_MAIN_PROVIDER = {"id": f"llm:{getattr(_llm, 'MODEL', '?')}/domain-classifier",
                     "signal_family": "topical-lexicon-llm"}

LLM_VERNIER_PROVIDER = {"id": f"llm:{getattr(_llm, 'MODEL', '?')}/deduction-rater",
                        "signal_family": "argumentative-syntax-llm"}

DDL = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL,
  scale TEXT NOT NULL,              -- 'main' | 'vernier'
  value REAL NOT NULL,              -- 归一到共享横梁的 ld 读数
  label TEXT,                       -- 主尺存领域带名
  confidence REAL,
  provider TEXT NOT NULL,
  signal_family TEXT NOT NULL,      -- 独立性约束的落地字段
  revised INTEGER NOT NULL DEFAULT 0,
  computed_at REAL NOT NULL,
  UNIQUE(item_id, scale)
);
CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src_item INTEGER NOT NULL,
  src_band TEXT NOT NULL,
  dst_band TEXT NOT NULL,
  kind TEXT NOT NULL,               -- logic-isomorphism | under-formalized
  offset_ld REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'candidate',
  created_at REAL NOT NULL,
  UNIQUE(src_item, dst_band, kind)
);
CREATE TABLE IF NOT EXISTS calib_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER,
  direction TEXT NOT NULL,          -- yang->yin | yin->yang | system
  message TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

SEED = [
    ("诗词意境赏析", "这首诗的意境深远，叙事抒情，审美上追求空灵，文学价值在于情感的凝练与文化的沉淀。"),
    ("数学基础构造", "在集合论与数论的框架下，若该函数可计算，则其复杂度有界；由此推导，综上必然存在算法。"),
    ("进化论观测报告", "自然选择驱动物种进化，本实验观测细胞层面的能量代谢与量子尺度的涨落变化。"),
    ("经济学均衡模型", "假设市场出清，若价格上升则需求下降，由此推论均衡存在；根据模型推导，综上必然收敛。"),
    ("法律判例推理", "因为被告违约，所以判决赔偿；若情节轻微则可减轻，综上推论其必然担责，前提成立结论成立。"),
    ("物理动量守恒", "根据实验观测，若外力为零则动量守恒；由此推导该物理量在自然系统中必然不变，综上成立。"),
    ("哲学三段论演绎", "因为人皆会死，所以苏格拉底会死；若甲是乙则丙，综上推论其必然成立，前提充分且必要。"),
    ("计算神经科学笔记", "神经元的观测数据以矩阵表示，通过算法建模；若激活超阈值则放电，由此推导网络行为。"),
    ("量子力学科普", "量子世界很奇妙，粒子可以同时处在多个状态，实验中的观测会改变结果，物理学家至今仍在探索。"),
]

_WAL_DONE = False

_SEMANTIC_FB_TYPES = {"near_duplicate", "semantic_similar", "bridge"}

BACKUP_DIR = os.path.join(BASE, "backups")

BACKUP_KEEP = 12

_INDEP_TTL = 90.0                 # 秒：independence() 结果缓存，避免每次写库重算全表

_indep_cache = {"t": 0.0, "v": None}

_SIGNAL_TTL = 300.0

_signal_cache = {"t": 0.0, "v": None}

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*|[0-9]+|[\u4e00-\u9fff]")

_CJK = re.compile(r"^[\u4e00-\u9fff]+$")

_SENT = re.compile(r"[。！？!?；;\n]+")          # 只按句末标点断句，摘要才不会被空格/逗号截断

_STOP = {"这是", "那是", "就是", "都是", "不是", "只是", "所有", "任何", "一个", "一种",
         "可以", "能够", "属于", "对于", "由于", "因为", "所以", "如果", "然后", "但是",
         "而且", "以及", "并且", "我们", "他们", "自己", "什么", "怎么", "这个", "那个",
         "的话", "上的", "中的", "下的", "这一", "一只", "即可", "体现", "指出", "认为"}

_FUNC = set("的了是在和与也就都很不我你他她它这那之其为以及所有并且但却还再又"
            "把被让使从到对于把将会能可要有没个种些此该等则即若之乎者也")

_FUNC_CH = set(
    "的了是在和与及也都就而但却因所以此于若则即其之者这那有无不为对从到被把使让"
    "会能可要需应当并且或者虽然然后再还只仅各每某任何若干上下里外前中间时候我你他"
    "它们很更最又同样如此该由综很非常个种含并等第一二三四五六七八九十"
)

_STOP_TERM = set(
    "根据 通过 表明 说明 认为 指出 由此 综上 因此 可见 例如 总之 首先 其次 最后 "
    "以上 以下 如下 其中 之间 之后 之前 需要 可以 能够 已经 正在 于是 从而 进而".split()
)

_GENERIC_TERMS = set(
    "系统 模型 理论 方法 概念 问题 关系 结构 结果 过程 状态 机制 信息 数据 知识 内容 "
    "方向 方式 原则 视角 基础 框架 逻辑 规律 现象 要素 属性 特征 特性 特点 能力 作用 "
    "影响 方面 层面 价值 意义 条件 情况 性质 材料 工具 手段 目标 目的 领域 层次".split()
)

_GENERIC_BAN = set(
    # —— 抽象容器词 ——
    "系统 模型 理论 方法 概念 问题 关系 结构 结果 过程 状态 机制 信息 数据 知识 内容 "
    "方向 方式 原则 视角 基础 框架 逻辑 规律 现象 要素 属性 特征 特性 特点 能力 作用 "
    "影响 方面 层面 价值 意义 条件 情况 性质 材料 工具 手段 目标 目的 领域 层次 "
    # —— 日常 / 心理通用词（堵住"理解/解决/工作"这类漏网）——
    "自己 我们 他们 判断 信号 感受 纠正 重复 觉得 永远 本身 否定 怎么 "
    "一次 今天 真心 平静 知道 理解 记得 解决 工作 效果 设计 质量 思路 避免 注意 "
    "维度 改变 环境 完整 追溯 原始 说白 这种 那种 时候 其实 已经 进行 通过 表明 "
    "说明 认为 指出 由此 综上 因此 可见 例如 总之 首先 其次 最后 以上 以下 如下 "
    "其中 之间 之后 之前 需要 可以 能够 正在 于是 从而 进而 这个 那个 什么 一些 "
    "一定 一直 一种 一样 一般 起来 出来 过来 的话".split()
)

_sum_breaker = {"fails": 0, "until": 0.0}          # 摘要接口熔断：连续失败后暂时不再尝试

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "heuristic"
    reset = "--keep" not in sys.argv
    init(force=reset)
    if mode == "llm":
        print(f"真实大模型：{getattr(_llm,'MODEL','?')} @ {getattr(_llm,'API_BASE','?')}"
              f"  key={_llm.masked_key() if LLM_OK else '(无)'}")
        _dump("本地启发式（对照组）")
        t0 = time.time()
        r = remeasure_all("llm")
        print(f"\n重测完成：{r}  用时 {time.time()-t0:.1f}s")
    _dump("真实大模型" if mode == "llm" else "本地启发式")

def _current_mode():
    """读取当前 provider 模式（开新连接，避免复用被占用的事务连接）。"""
    try:
        c = connect()
        m = get_mode(c)
        c.close()
        return m
    except Exception:                                  # noqa: BLE001
        return "heuristic"

def connect():
    """打开数据库连接。

    服务是 ThreadingTCPServer（多线程），默认 journal_mode=delete 下
    并发写极易 "database is locked"。WAL 让读写互不阻塞，只需设一次；
    busy_timeout 再给偶发争用一个 5 秒的自动等待窗口，不必上层重试。
    """
    global _WAL_DONE
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    if not _WAL_DONE:
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            _WAL_DONE = True
        except sqlite3.Error:
            pass                                   # 只读介质等场景，静默退回默认模式
    return con

def _write_readings(con, item_id, content, mode="heuristic", allow_invent=True,
                     force=False):
    # 独立性守卫闸门：两尺坍缩时，自动写入被拦截（拉闸）——隔离偏移、保留条目，
    # 避免把相关噪声继续喂进 readings。force=True 供显式复位（remeasure_all/init）绕过。
    ok, ind = _guard_allows_write(force=force)
    if not ok:
        log(con, item_id, "system",
            f"⛔ 独立性守卫已拉闸（r={ind['r']}，n={ind['n']}）：本条目双尺读数"
            f"不予写入/信任，偏移已隔离。待更换其中一路 provider 或相关性回落后解除。")
        return None, None
    if mode == "llm" and LLM_OK and _llm.breaker_state()["open"]:
        mode = "heuristic"   # 熔断中：不空等模型，用本地启发式落库
    now = time.time()
    (band_name, pos, mconf, mprov, mwhy), (depth, vconf, vprov, vwhy) = \
        measure_pair(content, mode)
    # llm 模式下的同步快路径：启发式只允许「归入已有领域」，
    # 自创的新领域名一律先写「未分类」，留给后台 LLM 归纳正式名——
    # 避免坏名字先落库、LLM 见到已有领域后归入坏名（自指问题）。
    if mode == "heuristic" and not allow_invent:
        known = {d["name"] for d in list_domains()}
        if band_name not in known:
            band_name, pos = "未分类", 50.0
    con.execute(
        "INSERT OR REPLACE INTO readings"
        "(item_id,scale,value,label,confidence,provider,signal_family,revised,computed_at)"
        " VALUES(?,?,?,?,?,?,?,0,?)",
        (item_id, "main", pos, band_name, mconf,
         mprov["id"], mprov["signal_family"], now),
    )
    con.execute(
        "INSERT OR REPLACE INTO readings"
        "(item_id,scale,value,label,confidence,provider,signal_family,revised,computed_at)"
        " VALUES(?,?,?,?,?,?,?,0,?)",
        (item_id, "vernier", depth, None, vconf,
         vprov["id"], vprov["signal_family"], now),
    )
    _invalidate_indep_cache()      # 读数变化后让独立性守卫重算
    return mwhy, vwhy

def init(force=False):
    """force=True 时用 DROP TABLE 重置（不删文件，兼容受限文件系统）。
    注意：演示种子只在「首次建库」时种入；force 清空后保持空库，不会复活演示数据。"""
    first_run = not os.path.exists(DB_PATH)
    fresh = force or first_run
    con = connect()
    if force:
        con.executescript(
            "DROP TABLE IF EXISTS readings; DROP TABLE IF EXISTS edges; "
            "DROP TABLE IF EXISTS calib_log; DROP TABLE IF EXISTS items; "
            "DROP TABLE IF EXISTS meta;")
    con.executescript(DDL)
    migrate()
    n = con.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
    if n == 0 and first_run:
        for title, content in SEED:
            cur = con.execute(
                "INSERT INTO items(title,content,created_at,alias) VALUES(?,?,?,?)",
                (title, content, time.time(), title),
            )
            _write_readings(con, cur.lastrowid, content, force=True)
        con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('threshold',?)",
                    (str(DEFAULT_THRESHOLD),))
        log(con, None, "system",
            f"数据库初始化：{len(SEED)} 条种子条目，双尺读数已入库。")
    con.commit()
    con.close()
    return fresh

def log(con, item_id, direction, message):
    con.execute(
        "INSERT INTO calib_log(item_id,direction,message,created_at) VALUES(?,?,?,?)",
        (item_id, direction, message, time.time()),
    )

def get_threshold(con):
    row = con.execute("SELECT v FROM meta WHERE k='threshold'").fetchone()
    return float(row["v"]) if row else DEFAULT_THRESHOLD

def get_mode(con):
    row = con.execute("SELECT v FROM meta WHERE k='mode'").fetchone()
    return row["v"] if row else "heuristic"

def remeasure_all(mode):
    """
    用指定 provider 重测全部条目。llm 模式下并发调用（内建限流 + 缓存）。
    这是「接真实大模型只需替换 provider」这句话的兑现：
    偏移判定、候选边、闭环收敛逻辑一行未改。
    """
    if mode == "llm" and not LLM_OK:
        return {"ok": False, "msg": "未检测到可用 API_KEY，无法启用真实大模型"}
    # 显式复位手段：即便守卫已拉闸也强制重测。若不绕过，坍缩后永远无法写入
    # 新（不相关）读数，系统死锁。重测完成后独立性会基于新 provider 的读数重评。
    ind = independence()
    forced = bool(ind.get("blocked"))
    con = connect()
    rows = con.execute("SELECT * FROM items ORDER BY id").fetchall()
    jobs = [(r["id"], r["content"]) for r in rows]
    con.close()

    results, errors = {}, []
    if mode == "llm":
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            fut = {ex.submit(measure_pair, c, mode): i for i, c in jobs}
            for f in concurrent.futures.as_completed(fut):
                iid = fut[f]
                try:
                    results[iid] = f.result()
                except Exception as e:                       # noqa: BLE001
                    errors.append(f"#{iid}: {e}")
    else:
        for iid, c in jobs:
            results[iid] = measure_pair(c, mode)

    con = connect()
    now = time.time()
    for iid, ((band_name, pos, mconf, mprov, mwhy),
              (depth, vconf, vprov, vwhy)) in results.items():
        con.execute(
            "INSERT OR REPLACE INTO readings(item_id,scale,value,label,confidence,"
            "provider,signal_family,revised,computed_at) VALUES(?,?,?,?,?,?,?,0,?)",
            (iid, "main", pos, band_name, mconf, mprov["id"], mprov["signal_family"], now))
        con.execute(
            "INSERT OR REPLACE INTO readings(item_id,scale,value,label,confidence,"
            "provider,signal_family,revised,computed_at) VALUES(?,?,?,?,?,?,?,0,?)",
            (iid, "vernier", depth, None, vconf, vprov["id"], vprov["signal_family"], now))
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('mode',?)", (mode,))
    _invalidate_indep_cache()      # 批量重写读数后重算独立性
    label = "真实大模型" if mode == "llm" else "本地启发式"
    log(con, None, "system",
        f"已切换至【{label}】provider 并重测 {len(results)} 条"
        + (f"（{len(errors)} 条失败）" if errors else "")
        + ("；⚠ 本次已强制绕过独立性守卫以解除坍缩。" if forced else "")
        + "两尺输入互补切分，彼此不可见。")
    con.commit()
    con.close()
    return {"ok": True, "mode": mode, "count": len(results), "errors": errors}

def set_threshold(value):
    con = connect()
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('threshold',?)", (str(value),))
    con.commit()
    con.close()

def get_threshold_value():
    """无连接版阈值读取，供 kb.py 复用。"""
    con = connect()
    t = get_threshold(con)
    con.close()
    return t

def snapshot(reason="manual"):
    """用 sqlite3 在线备份 API 生成整库快照，滚动保留最近 BACKUP_KEEP 份。

    走 backup() 而不是复制文件：WAL 模式下直接 copy 可能拿到撕裂的状态。
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^a-z0-9_-]+", "", str(reason).lower())[:20] or "manual"
    path = os.path.join(BACKUP_DIR, f"lantern-{stamp}-{safe}.db")
    src = connect()
    try:
        dst = sqlite3.connect(path)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    # 滚动清理：按文件名（含时间戳）排序，只留最近的
    files = sorted(f for f in os.listdir(BACKUP_DIR)
                   if f.startswith("lantern-") and f.endswith(".db"))
    removed = 0
    for f in files[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f))
            removed += 1
        except OSError:
            pass
    return {"ok": True, "path": path, "size": os.path.getsize(path),
            "kept": min(len(files), BACKUP_KEEP), "removed": removed}

def list_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not (f.startswith("lantern-") and f.endswith(".db")):
            continue
        p = os.path.join(BACKUP_DIR, f)
        out.append({"name": f, "size": os.path.getsize(p),
                    "at": os.path.getmtime(p)})
    return out

def migrate():
    """为新能力（双向引用 / 多维轴 / 向量 / 摘要 / wiki 软链）补表补列，已存在则跳过。"""
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS links (
      src_item_id INTEGER NOT NULL,
      dst_item_id INTEGER NOT NULL,
      created_at REAL NOT NULL,
      kind TEXT NOT NULL DEFAULT 'hard',   -- hard=[[...]]显式链 | soft=关键词共现
      evidence TEXT,                       -- soft 链：共享关键词 JSON；hard 链为 NULL
      confirmed INTEGER NOT NULL DEFAULT 1, -- soft 链待用户确认前为 0
      UNIQUE(src_item_id, dst_item_id)
    );
    CREATE TABLE IF NOT EXISTS axes (
      domain TEXT NOT NULL,
      dimension TEXT NOT NULL,
      weight REAL NOT NULL DEFAULT 0,
      UNIQUE(domain, dimension)
    );
    CREATE TABLE IF NOT EXISTS embeddings (
      item_id INTEGER PRIMARY KEY,
      vec TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS feedback_inbox (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id INTEGER,                 -- 目标知识条目（新建前可为空）
      title TEXT NOT NULL,             -- 反馈标题（概念名 / 条目标题）
      axis_domain TEXT,                -- 学科域
      severity TEXT NOT NULL DEFAULT 'info',   -- info | warn | critical
      review TEXT NOT NULL,            -- 反馈轴对抗审查完整 JSON
      must_revise INTEGER NOT NULL DEFAULT 0,  -- 写回前是否需先修订核心判断
      status TEXT NOT NULL DEFAULT 'unread',   -- unread | read | applied | dismissed
      created_at REAL NOT NULL,
      read_at REAL,
      applied_at REAL
    );
    CREATE TABLE IF NOT EXISTS hatch_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      spark_id INTEGER NOT NULL,
      item_id INTEGER,
      decision TEXT NOT NULL,            -- new | merged
      near_match_item_id INTEGER,        -- 检索到的近似条目（未达合并阈值）
      cluster_terms TEXT,                -- 来源簇 shared_terms JSON
      sibling_spark_ids TEXT,            -- 同簇被标 incubating 的兄弟碎片 JSON
      links_found INTEGER NOT NULL DEFAULT 0,   -- 全库关联发现写出的软边数
      feedback_ids TEXT,                 -- 反馈收件箱 id JSON
      axis_domain TEXT,
      created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS auto_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at REAL NOT NULL,
      kind TEXT NOT NULL,        -- sweep(周期心跳) | discover(发现新关联) | health(健康自检)
      message TEXT NOT NULL
    );
    """)
    # 概念衍生层：Karpathy「概念页」的 Lantern 式实现——
    # 概念带双尺度坐标（与文章条目同源），独立于正文，经 concept_links 与文章双向链。
    con.execute("""
    CREATE TABLE IF NOT EXISTS concepts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      definition TEXT,
      main_pos REAL NOT NULL DEFAULT 50.0,   -- 主尺（领域带轴）
      vernier REAL NOT NULL DEFAULT 45.0,    -- 游标（演绎深度轴）
      axis_domain TEXT,
      band TEXT,
      source TEXT NOT NULL DEFAULT 'heuristic',  -- heuristic | llm
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL
    )""")
    con.execute("""
    CREATE TABLE IF NOT EXISTS concept_links (
      concept_id INTEGER NOT NULL,
      item_id INTEGER NOT NULL,
      weight REAL NOT NULL DEFAULT 1.0,
      created_at REAL NOT NULL,
      UNIQUE(concept_id, item_id)
    )""")
    # 灵感碎片（原料层）：最上游的随手记捕获，刻意【无坐标】——投影（领域/演绎深度）
    # 发生在孵化环节，不在此落双尺度。status: raw→incubating→hatched；hatched_item_id
    # 打通原料→成品溯源；embedding 仅 LLM 可用时存，否则 NULL（不依赖它也能跑）。
    con.execute("""
    CREATE TABLE IF NOT EXISTS sparks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT,
      content TEXT NOT NULL,
      tags TEXT,                       -- JSON 数组（自由标签）
      source TEXT NOT NULL DEFAULT 'manual',  -- manual | import | clip
      status TEXT NOT NULL DEFAULT 'raw',     -- raw | incubating | hatched
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL,
      hatched_item_id INTEGER,        -- 孵化后关联的知识条目 id
      embedding TEXT
    )""")
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
    for col, ddl in [
        ("axis_domain", "ALTER TABLE items ADD COLUMN axis_domain TEXT"),
        ("summary", "ALTER TABLE items ADD COLUMN summary TEXT"),
        ("tags", "ALTER TABLE items ADD COLUMN tags TEXT"),
        ("alias", "ALTER TABLE items ADD COLUMN alias TEXT"),
    ]:
        if col not in cols:
            try:
                con.execute(ddl)
            except sqlite3.OperationalError:
                pass
    # 旧条目别名回填：取首次入库时的标题固化，避免后续改标题断链
    con.execute("UPDATE items SET alias=title WHERE alias IS NULL OR alias=''")
    # links 补列（旧库可能缺 kind/evidence/confirmed/provenance）
    lcols = {r[1] for r in con.execute("PRAGMA table_info(links)")}
    for col, ddl in [
        ("kind", "ALTER TABLE links ADD COLUMN kind TEXT NOT NULL DEFAULT 'hard'"),
        ("evidence", "ALTER TABLE links ADD COLUMN evidence TEXT"),
        ("confirmed", "ALTER TABLE links ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 1"),
        ("provenance", "ALTER TABLE links ADD COLUMN provenance TEXT"),
    ]:
        if col not in lcols:
            try:
                con.execute(ddl)
            except sqlite3.OperationalError:
                pass
    # provenance 回填：硬链=作者意图；软链=共现（语义由发现管线另写）
    con.execute("UPDATE links SET provenance='author' WHERE kind='hard' AND (provenance IS NULL OR provenance='')")
    con.execute("UPDATE links SET provenance='cooccur' WHERE kind='soft' AND (provenance IS NULL OR provenance='')")
    _ensure_fts(con)
    _ensure_chunks(con)
    # feedback_inbox.pushable：推送资格（v 后新增），兼容已存在的旧库
    try:
        fcols = [r["name"] for r in con.execute("PRAGMA table_info(feedback_inbox)")]
        if "pushable" not in fcols:
            con.execute("ALTER TABLE feedback_inbox ADD COLUMN pushable INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    con.commit(); con.close()
    migrate_article_files()

def get_meta(k, default=None):
    """读 meta 表键值（统一字符串返回）。"""
    try:
        con = connect()
        row = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        con.close()
        return row["v"] if row else default
    except Exception:
        return default

def set_meta(k, v):
    """写 meta 表键值（值统一转字符串，ON CONFLICT 覆盖）。"""
    con = connect()
    con.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, str(v)))
    con.commit(); con.close()

def _dump(tag):
    d = list_items()
    print(f"\n=== {tag} ===  条目 {len(d['items'])}，阈值 {d['threshold']}")
    for it in d["items"]:
        flag = "★碰撞" if it["collision"] else "  对齐"
        print(f"{flag} {it['title']:<12} 主尺={it['band']}@{it['main_pos']:<6} "
              f"游标={it['vernier']:<6} 典型={it['typical']:<4} 偏移={it['offset']:<7}"
              f"主尺信心={it['main_conf']}")
    ind = independence()
    print(f"独立性检验：r={ind['r']}  {ind['status']} —— {ind['msg']}")
    print(f"  信号族：{ind['families']}")
    return d, ind

