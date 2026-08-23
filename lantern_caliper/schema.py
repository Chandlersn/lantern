# -*- coding: utf-8 -*-
"""双尺规范与受控词表：领域带、学科域注册表、axes 分类法（单点真相）。"""

import json
import os

def domain_typical_vernier(domain):
    """受控学科域的带内典型游标；非受控域返回 None（调用方回退带级）。"""
    d = _DOMAIN_REGISTRY.get((domain or "").strip())
    return d["typical_vernier"] if d else None

def domain_intra_order(domain):
    """受控学科域在所属带内的递增序（仅视角差异的客观呈现，不代表优劣）。"""
    d = _DOMAIN_REGISTRY.get((domain or "").strip())
    return d["intra_band_order"] if d else None

def domain_band_name(domain):
    """受控学科域 → 主干领域带名；非受控域（含维度『时间』）返回 None。"""
    d = _DOMAIN_REGISTRY.get((domain or "").strip())
    return d["band"] if d else None

def import_axes(path=None):
    """把 领域|维度 分类法并入本库，作为比学科带更细的学科方向参考。

    分类文件需显式提供；若不传 path，默认在知识库目录内查找 axis_meta.json。
    （历史来源已从外部项目迁入本库，KB 不依赖任何外部目录。）
    """
    if path is None:
        path = os.path.join(os.path.dirname(BASE), "axis_meta.json")
    if not os.path.exists(path):
        return {"ok": False, "msg": f"未找到分类文件：{path}"}
    with open(path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    con = connect()
    n = 0
    for key, val in meta.items():
        if "|" not in key:
            continue
        dom, dim = key.split("|", 1)
        w = float(val.get("used", 0) or 0)
        con.execute("INSERT OR IGNORE INTO axes(domain,dimension,weight) VALUES(?,?,?)",
                    (dom.strip(), dim.strip(), w))
        n += 1
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('axes_source',?)", (path,))
    con.commit(); con.close()
    return {"ok": True, "imported": n, "source": path}

def list_axes():
    con = connect()
    rows = con.execute("SELECT domain, dimension, weight FROM axes "
                      "ORDER BY weight DESC, domain, dimension").fetchall()
    con.close()
    return [dict(r) for r in rows]

def domains_of_axes():
    """「更细学科域」可选选择器——只返回注册表中的**可见受控学科域**。

    C2 收口（防脏域自我强化）：候选名单**完全不依赖 items.axis_domain 的内容**。
    此前实现会把 items.axis_domain 命中过的隐藏域自动开放进下拉，导致一旦写入
    脏域（如「重叠窗口」），它就会进入选择器被反复选用、自我强化污染图谱。
    现在：
      - axes 表的受控学科域（透镜维度，已登记 band）保留；
      - 注册表所有「可见」学科域全部开放；
      - **不再**因 items.axis_domain 命中而开放隐藏域（该列本就是设计态全 None，
        且写入已走 normalize_axis_domain 归一化，无脏值可触发）。
    领域「涌现」由 readings.label（经 normalize_band 守门）+ list_domains() 承担，
    不在此选择器内自我繁殖。
    """
    con = connect()
    rows = con.execute("SELECT DISTINCT domain FROM axes").fetchall()
    # 维度（如「时间」）是轴向而非学科域，不进入「更细的领域」可选选择器；
    # 只保留受控学科域（在 registry 中登记了主干带 band 的）。
    doms = [r["domain"] for r in rows
            if isinstance(_DOMAIN_REGISTRY.get(r["domain"]), dict)
            and "band" in _DOMAIN_REGISTRY.get(r["domain"])]
    # 智能开放：注册表中「可见学科域」全部可选。隐藏域不再因内容映射自动开放，
    # 切断「脏域 → 进下拉 → 被反复选 → 自我强化」的污染链路。
    reg_visible = [name for name, d in _DOMAIN_REGISTRY.items()
                   if isinstance(d, dict) and "band" in d and not d.get("hidden")]
    con.close()
    allset = list(dict.fromkeys(doms + reg_visible))
    # 按 (主干带 order, 带内 intra_band_order) 递增排序，客观呈现带内视角差异；
    # 维度类（如『时间』）已在上面过滤，不会进入选择器。绝不按字典序或条数排序。
    bb_order = {b["name"]: b.get("order", i + 1) for i, b in enumerate(BACKBONE_BANDS)}
    def keyfn(d):
        reg = _DOMAIN_REGISTRY.get(d)
        if reg:
            return (bb_order.get(reg["band"], 99), reg.get("intra_band_order", 99))
        return (99, 99)
    return sorted(allset, key=keyfn)

