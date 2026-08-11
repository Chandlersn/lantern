# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 · 游标卡尺（lantern_caliper 包）
================================================================
原单体 store.py 已按职责拆分为子模块；本文件负责：
  1) 在包加载时导入全部子模块；
  2) 把每个子模块定义的名字（函数/类/常量，含下划线私有名）注入到
     其它子模块与包自身的命名空间，从而让跨模块的无限定调用照常工作，
     且彻底规避循环 import。
"""
import os
import sys

# 让包内模块能 import 仓库根的兄弟模块（llm.py 等）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入全部子模块（顺序无关，子模块不互相 import）
from . import (core, schema, measure, items, articles, feedback, guard, links, concepts, search, graph, summarize, audit, sparks)

_MODS = [core, schema, measure, items, articles, feedback, guard, links, concepts, search, graph, summarize, audit, sparks]
_G = globals()
for _m in _MODS:
    for _n, _v in vars(_m).items():
        if _n.startswith('__'):
            continue
        # 仅跳过“包自身的子模块”（core/schema/...），不要跳过外部模块别名
        # 如 `import llm as _llm` —— 它是 ModuleType 但必须注入，否则
        # 子模块运行期调用 _llm.xxx 会 NameError，且 store._llm 取不到。
        if _v in _MODS:
            continue
        for _t in _MODS:            # 注入到每一个子模块（含自身）
            setattr(_t, _n, _v)
        _G.setdefault(_n, _v)        # 暴露到包级别（store.foo 可用）

__all__ = [n for n in _G if not n.startswith('_') and n not in _MODS]

