# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 —— 演示数据生成器
================================================================
本仓库**不附带真实知识库数据**（lantern.db / articles 已被 .gitignore 排除），
以免泄露个人数据。首次运行服务时 `server.py` 会自动建库并种入一份合成演示数据；
本脚本提供一条显式、可重复的生成/重置入口。

用法：
    python seed_demo.py            # 库不存在则生成演示数据；已存在则仅补全文章镜像
    python seed_demo.py --force    # 清空现有库与文章镜像，重新生成一份干净的演示数据

说明：
    - 演示数据来自 lantern_caliper.core.SEED（合成、无个人信息的样例知识）。
    - 离线即可运行：没有配置大模型时，双尺定位走本地启发式；配置后后台自动升级。
    - 生成完成后即可 `python server.py` 启动，访问 http://127.0.0.1:8731/。
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lantern_caliper as store


def _reset():
    """删除本地库文件与文章镜像目录（仅本地数据，不影响代码）。"""
    for suffix in ("", "-shm", "-wal"):
        p = store.DB_PATH + suffix
        if os.path.exists(p):
            os.remove(p)
            print(f"  已删除 {os.path.basename(p)}")
    if os.path.isdir(store.ARTICLES_DIR):
        shutil.rmtree(store.ARTICLES_DIR)
        print(f"  已清空 {os.path.relpath(store.ARTICLES_DIR)}/")


def main():
    ap = argparse.ArgumentParser(description="生成灯笼演示知识库（合成数据，无个人信息）")
    ap.add_argument("--force", action="store_true",
                    help="清空现有库与文章镜像，重新生成一份干净的演示数据")
    args = ap.parse_args()

    if args.force:
        print("重置演示库（请先停止正在运行的服务，否则 WAL 文件可能被占用）…")
        _reset()

    # 建表；库不存在（首次）时 store.init() 会自动种入 SEED 原始条目。
    store.init()

    # 若因 --force 清空后处于空库，用标准入库流程补一份带文章镜像的演示数据。
    con = store.connect()
    n = con.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
    con.close()
    if n == 0:
        print(f"写入 {len(store.SEED)} 条演示知识…")
        for title, content in store.SEED:
            store.add_item(title, content)
        print("  双尺读数已由本地启发式落库（配置大模型后后台自动升级）。")

    # 为所有条目补全/重排本地文章镜像（含 init 原始种子路径未写镜像的条目）。
    written = store.export_all_articles()
    print(f"文章镜像：{written} 篇已写入 {os.path.relpath(store.ARTICLES_DIR)}/")
    store.recategorize_articles(remove_orphans=True)

    con = store.connect()
    n = con.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
    con.close()
    print(f"\n演示库就绪：{n} 条知识。")
    print("启动服务： python server.py   →   http://127.0.0.1:8731/")


if __name__ == "__main__":
    main()
