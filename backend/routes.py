#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 —— REST API 路由表
================================================================
把 server.py 里「巨型 if 分支分发」重构为显式的路由注册表：每条路由
(method + path 模板) 对应一个纯 handler 函数，handler 只负责业务逻辑、
返回 JSON-serializable 的 payload（或 (payload, status_code) 元组），
与 HTTP 传输层（连接 / 状态码 / body 解析 / 静态托管）完全解耦。

handler 签名统一为：  handler(query: dict, body: dict, captures: dict) -> payload
  · query     ：GET 查询参数（urllib.parse.parse_qs 的结果，值为列表）
  · body      ：POST 请求体（已解析的 JSON dict，无 body 时为 {}）
  · captures  ：path 模板里的命名捕获组（如 /api/sparks/<id>/... 的 rest）

本文件与 kb.py / lantern_caliper 同源：REST（本文件）、MCP（mcp_server.py）、
CLI（kb_cli.py）三通道共用同一份 kb.TOOLS / kb.dispatch 实现。
"""
import os
import re
import sys

# routes.py 位于 backend/ 子目录：引擎包 lantern_caliper 与 kb.py 均在仓库根，
# 统一把 backend/ 与仓库根注入 sys.path，保证可被导入。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lantern_caliper as store
import kb


# ----------------------------------------------------------------- 工具
def _q(query, key, default=""):
    """取 parse_qs 结果的第一个值（值为列表）。"""
    v = query.get(key)
    return v[0] if v else default


def _qi(query, key, default=0):
    """取整数型查询参数。"""
    try:
        return int(_q(query, key, default))
    except (TypeError, ValueError):
        return default


# =====================================================================
#  GET 路由 handlers
# =====================================================================
def h_schema(q, b, c):
    return store.SCHEMA


def h_state(q, b, c):
    data = store.list_items()
    # 列表不需要全文：整站轮询的这份响应里，正文占了绝大部分体积。
    # 保留一段摘录供预览，真要看全文时前端走 /api/kb/article。
    for it in data.get("items", []):
        _body = it.get("content") or ""
        it["excerpt"] = _body[:120] + ("…" if len(_body) > 120 else "")
        it["content_len"] = len(_body)
        it.pop("content", None)
    data["edges"] = store.list_edges()
    data["links"] = store.list_links()
    data["axes"] = store.list_axes()
    data["axis_domains"] = store.domains_of_axes()
    data["logs"] = store.list_logs()
    data["independence"] = store.independence()
    data["signal"] = store.signal_integrity()
    data["concept_count"] = len(store.list_concepts())
    data["concepts"] = store.list_concepts()
    data["schema_version"] = store.SCHEMA["version"]
    con = store.connect()
    data["mode"] = store.get_mode(con)
    con.close()
    _llm_info = store._llm.info() if store._llm.AVAILABLE else {"available": False}
    _llm_info.pop("key", None)          # 不向前端回传密钥（安全）
    data["llm"] = _llm_info
    data["metrics"] = kb.health()
    data["summary_backend"] = store.summary_backend()
    data["sparks"] = store.spark_stats()
    return data


def h_llm(q, b, c):
    info = store._llm.info() if store._llm.AVAILABLE else {"available": False}
    info.pop("key", None)               # 不向前端回传密钥（安全）
    return info


def h_isolation(q, b, c):
    text = _q(q, "text")
    if not text or not store.LLM_OK:
        return {"ok": False}
    return {
        "ok": True, "raw": text,
        "main_sees": store._llm.strip_logic(text),
        "vernier_sees": store._llm.mask_domain(text),
    }


def h_edges(q, b, c):
    return store.list_edges()


def h_logs(q, b, c):
    return store.list_logs()


def h_independence(q, b, c):
    return store.independence()


def h_feedback_list(q, b, c):
    status = _q(q, "status") or None
    return {"unread": store.count_unread_feedback(),
            "items": store.list_feedback(status),
            "signal": store.signal_integrity()}


def h_sparks_list(q, b, c):
    status = _q(q, "status") or None
    items = store.list_sparks(status)
    return {"items": items, "count": len(items)}


def h_sparks_clusters(q, b, c):
    return {"clusters": store.spark_clusters()}


def h_hatch_stats(q, b, c):
    return kb.hatch_stats()


def h_kb_state(q, b, c):
    return kb.state()


def h_kb_schema(q, b, c):
    return kb.schema()


def h_kb_config(q, b, c):
    return store._llm.get_config()


def h_kb_edges(q, b, c):
    return {"edges": kb.list_edges(_q(q, "status") or None)}


def h_kb_article(q, b, c):
    iid = _q(q, "id")
    if not iid:
        return ({"error": "缺少 id"}, 400)
    return kb.get_article(int(iid))


def h_kb_asset(q, b, c):
    """读取文章目录下的本地图片等静态资源（用于正文 ![alt](相对路径) 渲染）。
    路径经 article_path 所在目录约束，杜绝目录穿越；仅允许常见资源后缀。
    返回 (bytes, code, headers) 三元组；server._respond 识别并写出二进制。"""
    import os as _os
    from urllib.parse import unquote
    iid = _q(q, "id")
    rel = unquote(_q(q, "path") or "")
    if not iid or not rel:
        return ({"error": "缺少参数"}, 400)
    if _os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/") or rel.startswith("/"):
        return ({"error": "非法路径"}, 400)
    if not re.search(r"\.(png|jpe?g|gif|webp|svg|bmp|ico)$", rel, re.I):
        return ({"error": "不支持的资源类型"}, 400)
    try:
        base = _os.path.dirname(kb.store.article_path(int(iid)))
        full = _os.path.normpath(_os.path.join(base, rel))
        if not _os.path.abspath(full).startswith(_os.path.abspath(base)):
            return ({"error": "越权访问"}, 403)
        if not _os.path.exists(full):
            return ({"error": "资源不存在"}, 404)
        ctype = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","gif":"image/gif",
                 "webp":"image/webp","svg":"image/svg+xml","bmp":"image/bmp","ico":"image/x-icon"}.get(
                 rel.rsplit(".",1)[-1].lower(), "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        return (data, 200, {"Content-Type": ctype, "Cache-Control": "no-store"})
    except Exception as e:
        return ({"error": str(e)}, 500)



def h_kb_attachments(q, b, c):
    """上传附件（图片/视频等）到 _ROOT/attachments/，返回可访问 URL。
    入参：{filename, data(base64)}。文件名安全清洗，防目录穿越；加时间戳前缀防重名。"""
    import base64 as _b64, re as _re, time as _t
    fn = (b.get("filename") or "").strip()
    data = b.get("data") or ""
    if not fn or not data:
        return ({"error": "缺少 filename 或 data"}, 400)
    fn = os.path.basename(fn)
    fn = _re.sub(r"[^\w.\-\u4e00-\u9fa5]", "_", fn)   # 去目录与非法字符
    if not _re.search(r"\.(png|jpe?g|gif|webp|svg|bmp|ico|mp4|webm|ogg|mov|pdf)$", fn, _re.I):
        return ({"error": "不支持的文件类型"}, 400)
    fn = f"{int(_t.time()*1000)}_{fn}"
    d = os.path.join(_ROOT, "attachments")
    os.makedirs(d, exist_ok=True)
    try:
        raw = _b64.b64decode(data, validate=True)
    except Exception:
        return ({"error": "data 不是合法 base64"}, 400)
    with open(os.path.join(d, fn), "wb") as f:
        f.write(raw)
    return {"url": "/attachments/" + fn, "filename": fn}


def h_kb_backlinks(q, b, c):
    iid = _q(q, "id")
    if not iid:
        return ({"error": "缺少 id"}, 400)
    return kb.backlinks(int(iid))


def h_kb_axes(q, b, c):
    return kb.axes()


def h_kb_similar(q, b, c):
    text = _q(q, "text") or _q(q, "q")
    k = _qi(q, "k", 5)
    return kb.semantic(text, k)


def h_kb_suggest_links(q, b, c):
    return kb.suggest_links(
        _qi(q, "k", 8),
        float(_q(q, "min_score", 0.0) or 0.0),
        _qi(q, "min_shared", 2))


def h_kb_backups(q, b, c):
    return {"backups": store.list_backups()}


def h_graph(q, b, c):
    return kb.graph()


def h_concepts(q, b, c):
    concepts = store.list_concepts()
    fallback = not concepts
    if not concepts:
        # LLM 概念层为空：从 items 的 tags 聚合成"概念雏形"，保证图有内容
        concepts = store.tag_concepts_fallback()
    else:
        # 概念层已有（LLM 提取）：补充 tag 聚合的概念，合并去重，让共现网络更密
        tags = store.tag_concepts_fallback()
        have = {c["name"] for c in concepts}
        for t in tags:
            if t["name"] not in have:
                concepts.append(t)
                have.add(t["name"])
    return {"concepts": concepts, "fallback": fallback}


def h_kb_concept_neighbors(q, b, c):
    iid = _q(q, "id")
    if not iid:
        return ({"error": "缺少 id"}, 400)
    return {"item_id": int(iid), "neighbors": store.concept_neighbors(int(iid))}


def h_audit_log(q, b, c):
    return {"items": kb.audit_log(), "stats": kb.audit_stats()}


# =====================================================================
#  POST 路由 handlers
# =====================================================================
def h_items(q, b, c):
    title = (b.get("title") or "").strip()
    content = (b.get("content") or "").strip()
    if not title or not content:
        return ({"error": "标题与内容不能为空"}, 400)
    return store.add_item(title, content)


def h_threshold(q, b, c):
    store.set_threshold(float(b.get("value", 18)))
    return {"ok": True}


def h_edge(q, b, c):
    return store.gen_edge(int(b["item_id"]))


def h_edge_status(q, b, c):
    return store.set_edge_status(int(b["edge_id"]), b.get("status", "accepted"))


def h_calibrate(q, b, c):
    return store.calibrate(int(b["item_id"]))


def h_mode(q, b, c):
    return store.remeasure_all(b.get("mode", "heuristic"))


def h_reset(q, b, c):
    store.init(force=True)
    return {"ok": True}


def h_kb_consolidate(q, b, c):
    return store.consolidate_domains(float(b.get("merge_jaccard", 0.5)))


def h_kb_add(q, b, c):
    title = (b.get("title") or "").strip()
    content = (b.get("content") or "").strip()
    if not content:
        return ({"error": "content 不能为空"}, 400)
    return kb.add_knowledge(title, content,
                            bool(b.get("run_closure", True)),
                            (b.get("axis_domain") or None),
                            (b.get("source_url") or None))


def h_kb_query(q, b, c):
    return kb.query(b.get("text", ""), int(b.get("top_k", 5)))


def h_kb_retrieve(q, b, c):
    return kb.retrieve(b.get("query", b.get("text", "")),
                       b.get("filters") or {},
                       int(b.get("top_k", 10)))


def h_kb_fragments(q, b, c):
    return kb.fragments(b.get("query", b.get("text", "")),
                        b.get("filters") or {},
                        int(b.get("top_k", 8)))


def h_kb_neighbors(q, b, c):
    return kb.neighbors(b.get("item_id"), b.get("text"), int(b.get("k", 5)))


def h_kb_linked_neighbors(q, b, c):
    return kb.linked_neighbors(b.get("item_id"), int(b.get("k", 8)))


def h_kb_search(q, b, c):
    dm = b.get("depth_min")
    dx = b.get("depth_max")
    return kb.search_dual(b.get("band"),
                          float(dm) if dm is not None else None,
                          float(dx) if dx is not None else None,
                          int(b.get("top_k", 20)))


def h_kb_position(q, b, c):
    return kb.position(b.get("text", ""))


def h_kb_multidim(q, b, c):
    """多维联合检索：语义 + 主尺 + 游标 + 领域带 + 标签 + 偏差上限，一次跨轴返回。"""
    def _f(key):
        v = b.get(key)
        return float(v) if v not in (None, "") else None
    return store.multidim_search(
        text=b.get("text", "") or "",
        k=int(b.get("k", 10)),
        band=b.get("band") or None,
        main_min=_f("main_min"), main_max=_f("main_max"),
        vernier_min=_f("vernier_min"), vernier_max=_f("vernier_max"),
        tags=b.get("tags") or None,
        offset_max=_f("offset_max"),
        grouped=bool(b.get("grouped")))


def h_kb_calibrate(q, b, c):
    return kb.calibrate(int(b.get("item_id")))


def h_kb_mode(q, b, c):
    return kb.set_mode(b.get("mode", "heuristic"))


def h_kb_config_set(q, b, c):
    return store._llm.apply_config(b)


def h_kb_config_test(q, b, c):
    return store._llm.test_connection(b)


def h_kb_relate(q, b, c):
    return kb.relate(b.get("item_id"), b.get("text"))


def h_kb_context(q, b, c):
    return kb.context(b.get("query", ""),
                      int(b.get("top_k", 5)),
                      bool(b.get("include_edges", True)),
                      int(b.get("max_chars", 2200)))


def h_kb_traverse(q, b, c):
    return kb.traverse(b.get("start_id"),
                       int(b.get("hops", 2)),
                       b.get("kind"))


def h_kb_update(q, b, c):
    return kb.update_article(int(b.get("item_id")),
                             (b.get("title") or "").strip(),
                             (b.get("content") or "").strip(),
                             (b.get("axis_domain") or None),
                             b.get("rev"),
                             (b.get("source_url") or None))


def h_kb_reload(q, b, c):
    return kb.reload_article(int(b.get("item_id")))


def h_kb_open_folder(q, b, c):
    return store.open_article_folder(b.get("item_id"))


def h_kb_link(q, b, c):
    return kb.link(b.get("src_id"), b.get("dst_id"))


def h_kb_unlink(q, b, c):
    return kb.unlink(b.get("src_id"), b.get("dst_id"))


def h_kb_import_axes(q, b, c):
    return kb.import_axes(b.get("path"))


def h_kb_import(q, b, c):
    return kb.import_kb(b.get("text"), b.get("entries"), b.get("directory"))


def h_kb_embed_rebuild(q, b, c):
    return kb.rebuild_embeddings()


def h_kb_delete(q, b, c):
    iid = b.get("item_id") or b.get("id")
    if iid is None:
        return ({"error": "缺少 item_id"}, 400)
    return kb.delete(int(iid), bool(b.get("backup", False)))


def h_kb_backup(q, b, c):
    return kb.backup(b.get("reason") or "manual")


def h_kb_create_draft(q, b, c):
    return kb.create_draft((b.get("title") or "").strip())


def h_sparks_add(q, b, c):
    content = (b.get("content") or "").strip()
    if not content:
        return ({"error": "content 不能为空"}, 400)
    return store.add_spark(content, b.get("title"), b.get("tags"),
                           b.get("source", "manual"))


def h_sparks_action(q, b, c):
    """POST /api/sparks/<id>[/hatch|draft|commit|update|delete] —— 灵感碎片原料层动作。"""
    rest = (c.get("rest") or "").strip("/")
    parts = [x for x in rest.split("/") if x]
    if not parts or not parts[0].isdigit():
        return ({"error": "bad path"}, 400)
    sid = int(parts[0])
    if len(parts) >= 2 and parts[1] == "hatch":
        return kb.hatch_spark(sid, b.get("title"), b.get("axis_domain"),
                              bool(b.get("run_closure", True)),
                              float(b.get("hit_threshold", 4.0)))
    if len(parts) >= 2 and parts[1] == "draft":
        # 阶段一：生成碰撞创作草稿（不落库），供前端展示/编辑
        return kb.draft_hatch(sid, b.get("title"), b.get("axis_domain"),
                              bool(b.get("run_closure", True)),
                              float(b.get("hit_threshold", 4.0)))
    if len(parts) >= 2 and parts[1] == "commit":
        # 阶段二：用户微调草稿后确认入库
        return kb.commit_hatch(sid, b.get("content"), b.get("title"),
                               b.get("axis_domain"),
                               float(b.get("hit_threshold", 4.0)))
    if len(parts) >= 2 and parts[1] == "update":
        return store.update_spark(sid, b.get("content"), b.get("title"), b.get("tags"))
    if len(parts) >= 2 and parts[1] == "delete":
        return {"ok": store.delete_spark(sid)}
    # 默认：改状态 / 标签
    return {"ok": store.update_spark_status(sid, b.get("status", "raw"), b.get("tags"))}


def h_feedback_read(q, b, c):
    return {"ok": store.mark_feedback_read(int(b.get("id")))}


def h_feedback_applied(q, b, c):
    return {"ok": store.mark_feedback_applied(int(b.get("id")))}


def h_feedback_correct(q, b, c):
    # 对话式闭环：人在同一条反馈下给出修正，立即落回文章
    try:
        fid = int(b.get("id"))
        correction = {
            "corrected_domain": (b.get("corrected_domain") or "").strip(),
            "corrected_summary": (b.get("corrected_summary") or "").strip(),
            "note": (b.get("note") or "").strip(),
        }
        if not any(correction.values()):
            return ({"ok": False, "msg": "请至少填写正确领域、正确摘要或一条修正意见"}, 400)
        return {"ok": True, **store.apply_human_correction(fid, correction)}
    except Exception as e:  # noqa: BLE001
        return ({"ok": False, "msg": str(e)}, 400)


def h_feedback_dismiss(q, b, c):
    return {"ok": store.dismiss_feedback(int(b.get("id")))}


def h_feedback_delete(q, b, c):
    return {"ok": store.delete_feedback(int(b.get("id")))}


def h_feedback_clear(q, b, c):
    return {"ok": True, "deleted": store.clear_feedback()}


def h_feedback_not_duplicate(q, b, c):
    a = int(b.get("a")); b_ = int(b.get("b"))
    store.ignore_dupe_pair(a, b_)
    return {"ok": True}


def h_feedback_apply(q, b, c):
    # 应用更新闭环第 1 步：仅生成修订稿，不落库；前端 diff 预览 + 用户确认后才回写
    try:
        return {"ok": True, **kb.revise_with_feedback(int(b.get("id")))}
    except Exception as e:  # noqa: BLE001
        return ({"ok": False, "msg": str(e)}, 400)


def h_soft_link_confirm(q, b, c):
    return kb.confirm_soft_link(b.get("src_id") or b.get("src"),
                                b.get("dst_id") or b.get("dst"))


def h_soft_link_dismiss(q, b, c):
    return kb.dismiss_soft_link(b.get("src_id") or b.get("src"),
                                b.get("dst_id") or b.get("dst"))


def h_soft_links_refresh(q, b, c):
    res = kb.refresh_soft_links()
    # 写入引擎自主核对审计：用户手动触发也算一次「核对」
    if res.get("written"):
        kb.auto_log("discover",
                    f"主动核对：发现 {res['written']} 组新关联"
                    f"（共现 {res.get('cooccur_written',0)} · 语义 {res.get('semantic_written',0)}），"
                    f"已自动接入图谱。")
    return res


def h_audit_log_purge(q, b, c):
    return kb.purge_audit_log(int(b.get("keep_days", 30)))


# =====================================================================
#  路由注册表（method, path 模板, handler）
#  path 模板为正则（re.fullmatch），(?P<name>...) 捕获组经 captures 传给 handler。
#  顺序无关（fullmatch 不会误匹配更长路径），但同 (method, 模板) 不可重复。
# =====================================================================
ROUTES = [
    # ---- 系统 / 引擎状态 ----
    ("GET", r"^/api/schema$", h_schema),
    ("GET", r"^/api/state$", h_state),
    ("GET", r"^/api/llm$", h_llm),
    ("GET", r"^/api/isolation$", h_isolation),
    ("GET", r"^/api/edges$", h_edges),
    ("GET", r"^/api/logs$", h_logs),
    ("GET", r"^/api/independence$", h_independence),
    ("GET", r"^/api/audit-log$", h_audit_log),
    ("POST", r"^/api/audit-log/purge$", h_audit_log_purge),

    # ---- 反馈收件箱 ----
    ("GET", r"^/api/feedback$", h_feedback_list),
    ("POST", r"^/api/feedback/read$", h_feedback_read),
    ("POST", r"^/api/feedback/applied$", h_feedback_applied),
    ("POST", r"^/api/feedback/dismiss$", h_feedback_dismiss),
    ("POST", r"^/api/feedback/delete$", h_feedback_delete),
    ("POST", r"^/api/feedback/clear$", h_feedback_clear),
    ("POST", r"^/api/feedback/not_duplicate$", h_feedback_not_duplicate),
    ("POST", r"^/api/feedback/apply$", h_feedback_apply),
    ("POST", r"^/api/feedback/correct$", h_feedback_correct),

    # ---- 灵感碎片（原料层）----
    ("GET", r"^/api/sparks$", h_sparks_list),
    ("GET", r"^/api/sparks/clusters$", h_sparks_clusters),
    ("GET", r"^/api/hatch/stats$", h_hatch_stats),
    ("POST", r"^/api/sparks$", h_sparks_add),
    ("POST", r"^/api/sparks/(?P<rest>.*)$", h_sparks_action),

    # ---- 软链（引擎发现）确认 / 驳回 / 刷新 ----
    ("POST", r"^/api/soft-link/confirm$", h_soft_link_confirm),
    ("POST", r"^/api/soft-link/dismiss$", h_soft_link_dismiss),
    ("POST", r"^/api/soft-links/refresh$", h_soft_links_refresh),

    # ---- 知识库 REST 接口 ----
    ("GET", r"^/api/kb/state$", h_kb_state),
    ("GET", r"^/api/kb/schema$", h_kb_schema),
    ("GET", r"^/api/kb/config$", h_kb_config),
    ("GET", r"^/api/kb/edges$", h_kb_edges),
    ("GET", r"^/api/kb/article$", h_kb_article),
    ("GET", r"^/api/kb/asset$", h_kb_asset),
    ("GET", r"^/api/kb/backlinks$", h_kb_backlinks),
    ("GET", r"^/api/kb/axes$", h_kb_axes),
    ("GET", r"^/api/kb/similar$", h_kb_similar),
    ("GET", r"^/api/kb/suggest_links$", h_kb_suggest_links),
    ("GET", r"^/api/kb/backups$", h_kb_backups),
    ("GET", r"^/api/kb/concept_neighbors$", h_kb_concept_neighbors),
    ("GET", r"^/api/graph$", h_graph),
    ("GET", r"^/api/concepts$", h_concepts),

    ("POST", r"^/api/kb/add$", h_kb_add),
    ("POST", r"^/api/kb/query$", h_kb_query),
    ("POST", r"^/api/kb/retrieve$", h_kb_retrieve),
    ("POST", r"^/api/kb/fragments$", h_kb_fragments),
    ("POST", r"^/api/kb/neighbors$", h_kb_neighbors),
    ("POST", r"^/api/kb/linked_neighbors$", h_kb_linked_neighbors),
    ("POST", r"^/api/kb/search$", h_kb_search),
    ("POST", r"^/api/kb/position$", h_kb_position),
    ("POST", r"^/api/kb/multidim$", h_kb_multidim),
    ("POST", r"^/api/kb/calibrate$", h_kb_calibrate),
    ("POST", r"^/api/kb/mode$", h_kb_mode),
    ("POST", r"^/api/kb/config_set$", h_kb_config_set),
    ("POST", r"^/api/kb/config_test$", h_kb_config_test),
    ("POST", r"^/api/kb/relate$", h_kb_relate),
    ("POST", r"^/api/kb/context$", h_kb_context),
    ("POST", r"^/api/kb/traverse$", h_kb_traverse),
    ("POST", r"^/api/kb/update$", h_kb_update),
    ("POST", r"^/api/kb/reload$", h_kb_reload),
    ("POST", r"^/api/kb/open_folder$", h_kb_open_folder),
    ("POST", r"^/api/kb/link$", h_kb_link),
    ("POST", r"^/api/kb/unlink$", h_kb_unlink),
    ("POST", r"^/api/kb/import_axes$", h_kb_import_axes),
    ("POST", r"^/api/kb/similar$", h_kb_similar),
    ("POST", r"^/api/kb/backlinks$", h_kb_backlinks),
    ("POST", r"^/api/kb/axes$", h_kb_axes),
    ("POST", r"^/api/kb/suggest_links$", h_kb_suggest_links),
    ("POST", r"^/api/kb/import$", h_kb_import),
    ("POST", r"^/api/kb/embed_rebuild$", h_kb_embed_rebuild),
    ("POST", r"^/api/kb/delete$", h_kb_delete),
    ("POST", r"^/api/kb/backup$", h_kb_backup),
    ("POST", r"^/api/kb/create_draft$", h_kb_create_draft),
    ("POST", r"^/api/kb/attachments$", h_kb_attachments),

    # ---- 旧版（store 直接暴露）接口，保留向后兼容 ----
    ("POST", r"^/api/items$", h_items),
    ("POST", r"^/api/threshold$", h_threshold),
    ("POST", r"^/api/edge$", h_edge),
    ("POST", r"^/api/edge/status$", h_edge_status),
    ("POST", r"^/api/calibrate$", h_calibrate),
    ("POST", r"^/api/mode$", h_mode),
    ("POST", r"^/api/reset$", h_reset),
    ("POST", r"^/api/kb/consolidate$", h_kb_consolidate),
]


def match_route(method, path):
    """返回 (handler, captures) 或 (None, None)。"""
    for m, pat, handler in ROUTES:
        if m != method:
            continue
        mo = re.compile(pat).fullmatch(path)
        if mo:
            return handler, mo.groupdict()
    return None, None
