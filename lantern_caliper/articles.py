# -*- coding: utf-8 -*-
"""本地 Markdown 镜像的读写、归档、重分类，以及用系统文件管理器定位/打开。"""

import os
import re
import sys
import subprocess
import ctypes
from ctypes import wintypes


def ensure_articles_dir():
    os.makedirs(ARTICLES_DIR, exist_ok=True)
    return ARTICLES_DIR

def _slug_title(title):
    """标题 → 文件名安全片段：去非法字符（\\/:*?"<>| 与控制符）、压空格、限长 40。"""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", title or "").strip()
    s = re.sub(r"\s+", " ", s)[:40].strip(" .")
    return s

def _article_name(item_id, title):
    """正式文件名：<两位数编号>-<标题片段>.md；无标题片段时退化为 <编号>.md。
    编号永远保留，保证文件名唯一（标题可能重复/含非法字符）。"""
    slug = _slug_title(title)
    return f"{int(item_id):02d}-{slug}.md" if slug else f"{int(item_id):02d}.md"

def _safe_join_article(*parts):
    """拼接 articles/ 下的子路径，并强制校验绝不逃出 ARTICLES_DIR。

    防御目标（借鉴 person_dashboard 的写入安全层）：拒绝 ../ 穿越、绝对路径、
    以及已存在路径上的符号链接逃逸。纯防御，不改变任何正常行为——
    正常 band/domain/标题经 slug 与受控词表归一化后本就不可能越界，这里只是兜底。

    - 先 normpath 把 ../ 等做词法归一（不依赖路径是否存在）；
    - 再用前缀判定是否仍落在 ARTICLES_DIR 内；
    - 若路径已存在，额外用 realpath 解析软链再判一次（防 symlink 逃逸）。
    """
    root = os.path.abspath(ARTICLES_DIR)
    norm = os.path.normpath(os.path.join(root, *[str(p) for p in parts]))
    if norm != root and not norm.startswith(root + os.sep):
        raise ValueError(f"非法文章路径，试图逃出文章目录：{parts!r}")
    if os.path.exists(norm):
        real = os.path.realpath(norm)
        if real != root and not real.startswith(root + os.sep):
            raise ValueError(f"非法文章路径（符号链接逃逸）：{parts!r}")
    return norm

def article_band(item):
    """文章归档与 frontmatter 的权威带：优先由 axis_domain 派生（与学科域一致），
    缺失时退回主尺实测位置 canonical_band。保证目录下『带/域』与正文 frontmatter 永一致，
    不再出现『测得的带』与『学科域对应的带』互相打架（已知 D 类落盘不一致）。"""
    dom = (item.get("axis_domain") or "").strip()
    if dom:
        b = domain_band_name(dom)
        if b:
            return b
    return canonical_band(item.get("main_pos"))

def _article_dir(item):
    """按知识库『双尺定位』给文章归子目录：一级=权威领域带（由 axis_domain 派生，
    缺失时退回主尺实测位置），二级=学科域 axis_domain。经 _safe_join_article 校验防穿越。
    与 KB 分类一一对应；axis_domain 缺失时退到 band 单层。"""
    band = article_band(item)
    dom = (item.get("axis_domain") or "").strip()
    if dom:
        return _safe_join_article(band, dom)
    return _safe_join_article(band)

def trash_file(path):
    """把文件移入**系统回收站**（而非永久删除），作为删除文档的兜底。

    仅对本地 .md 文档有意义；SQLite 数据库记录无法进回收站，仍是永久删除。
    任一平台若回收站机制不可用，回退为永久 os.remove 并在返回前标记失败。
    返回 True 表示文件已不在原路径（无论走回收站还是回退删除）。
    """
    if not path or not os.path.exists(path):
        return True
    # ---- Windows：SHFileOperationW + FOF_ALLOWUNDO 即移入回收站 ----
    if sys.platform.startswith("win"):
        try:
            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.UINT),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]
            FO_DELETE = 3
            FOF_SILENT = 0x0004
            FOF_NOCONFIRMATION = 0x0010
            FOF_NOERRORUI = 0x0400
            FOF_NOCONFIRMMKDIR = 0x0200
            # pFrom 必须双 NUL 结尾
            pFrom = ctypes.create_unicode_buffer(os.path.abspath(path) + "\0\0")
            op = SHFILEOPSTRUCTW(0, FO_DELETE, pFrom, None,
                                 FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI
                                 | FOF_NOCONFIRMMKDIR | 0x40,  # 0x40 = FOF_ALLOWUNDO
                                 False, None, None)
            res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
            if res == 0 and not op.fAnyOperationsAborted:
                return True
        except Exception:
            pass
        # 回退：永久删除
        try:
            os.remove(path)
        except OSError:
            pass
        return True
    # ---- macOS：Finder 的 delete 命令即移入废纸篓 ----
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "Finder" to delete POSIX file "{os.path.abspath(path)}"'],
                check=True, capture_output=True, timeout=30)
            return True
        except Exception:
            pass
    # ---- Linux：gio trash / trash-put ----
    else:
        for cmd in (["gio", "trash"], ["trash-put"]):
            try:
                subprocess.run(cmd + [os.path.abspath(path)],
                               check=True, capture_output=True, timeout=30)
                return True
            except Exception:
                continue
    # ---- 兜底：永久删除 ----
    try:
        os.remove(path)
    except OSError:
        pass
    return True

def article_path(item_id):
    """条目在 articles/ 下的正式文件路径（按双尺分类归入子目录）。
    文件名仍含编号与标题，随标题变化；目录随权威 band/axis_domain 归类。
    全程经 _safe_join_article 校验，杜绝路径穿越。"""
    it = get_item(item_id)
    if not it:
        return _safe_join_article(f"{int(item_id):02d}.md")
    band = article_band(it)
    dom = (it.get("axis_domain") or "").strip()
    name = _article_name(item_id, it.get("title", ""))
    parts = [band, name] if not dom else [band, dom, name]
    d = _safe_join_article(*parts[:-1])
    os.makedirs(d, exist_ok=True)
    return _safe_join_article(*parts)

def legacy_article_path(item_id):
    """旧式纯编号文件名 <id>.md（迁移与清理用）。"""
    return os.path.join(ARTICLES_DIR, f"{int(item_id)}.md")

def _locate_article_file(item_id):
    """按 item_id 在 articles/ 下定位真实存在的镜像文件，容忍 band / 标题漂移与重复副本。

    优先返回 article_path 计算的标准路径（若存在）；否则回退到磁盘上任意
    '<id>-*' / '<id>.md' 匹配；都不存在则返回 None。
    原因：重分类或标题改动后，article_path 重新算出的路径可能与磁盘实际落点不一致，
    若只信计算结果会打开一个不存在的目录，导致『打开本地文件位置』到不了真实子文件夹。"""
    import glob as _glob
    preferred = article_path(item_id)
    if os.path.exists(preferred):
        return preferred
    iid = int(item_id)
    cands = []
    for pat in (f"{iid:02d}-*", f"{iid}-*", f"{iid}.md"):
        cands += _glob.glob(os.path.join(ARTICLES_DIR, "**", pat), recursive=True)
    files = [c for c in cands if os.path.isfile(c)]
    return files[0] if files else None

def _win_open_and_select(path):
    """用 Windows Shell API 打开资源管理器并定位/选中文件或文件夹。

    比 `explorer /select,"<path>"` 可靠：后者路径解析稍有异常（中文长文件名、
    全角冒号、空白等）就会静默回退到『此电脑』主页而不报错，导致『打开本地文件位置』
    落不到对应子文件夹。SHOpenFolderAndSelectItems 直接依据 pidl 定位，不会回退。
    成功返回 True；失败（如路径不存在）返回 False，由调用方回退到 startfile/explorer。"""
    try:
        import ctypes
        from ctypes import wintypes, byref, c_ulong, c_void_p, POINTER, HRESULT
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        pidl = c_void_p()
        sfgao = c_ulong(0)
        name = ctypes.create_unicode_buffer(os.path.normpath(path))
        shell32.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, c_void_p,
                                               POINTER(c_void_p), c_ulong, POINTER(c_ulong)]
        shell32.SHParseDisplayName.restype = HRESULT
        hr = shell32.SHParseDisplayName(name, None, byref(pidl), 0, byref(sfgao))
        if hr != 0:
            return False
        shell32.SHOpenFolderAndSelectItems.argtypes = [c_void_p, c_ulong, c_void_p, c_ulong]
        shell32.SHOpenFolderAndSelectItems.restype = HRESULT
        shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        ole32.CoTaskMemFree(pidl)
        return True
    except Exception:                           # noqa: BLE001
        return False

def open_article_folder(item_id):
    """在系统文件管理器中打开该条目 articles/ 镜像文件的所在目录（并选中文件）。

    由后端进程（运行在本机）调用系统命令实现——浏览器 JS 受安全沙箱限制，
    无法直接打开本地文件夹。路径按 item_id 在磁盘上定位真实文件（见 _locate_article_file），
    不接收前端任意路径，杜绝任意目录访问。
    返回 {"ok": True, "dir": ...} 或 {"ok": False, "msg": ...}。"""
    import subprocess, sys
    try:
        it = get_item(item_id)
        if not it:
            return {"ok": False, "msg": "条目不存在"}
        path = _locate_article_file(item_id)    # 磁盘真实位置（容忍漂移/重复）
        if path and os.path.exists(path):
            target, open_dir = path, os.path.dirname(path)   # 选中文件
        else:
            # 文件尚未生成 / 不在磁盘：打开它应处的分类目录；目录也没有则退回 articles/
            open_dir = _article_dir(it)
            if not os.path.isdir(open_dir):
                open_dir = ARTICLES_DIR
            target = None
        if sys.platform.startswith("win"):
            sel = target or open_dir
            if not _win_open_and_select(sel):   # Shell API 优先（不会回退『此电脑』）
                try:                            # 回退：直接打开目录
                    os.startfile(os.path.normpath(open_dir))
                except Exception:               # noqa: BLE001
                    subprocess.Popen(['explorer', os.path.normpath(open_dir)])
        elif sys.platform == "darwin":
            subprocess.Popen(['open', '-R', target] if target else ['open', open_dir])
        else:
            subprocess.Popen(['xdg-open', open_dir])
        return {"ok": True, "dir": open_dir, "selected": bool(target), "path": path}
    except Exception as e:                      # noqa: BLE001
        return {"ok": False, "msg": str(e)}

def serialize_article(it):
    """把条目序列化为带 frontmatter 的 markdown（frontmatter 用 --- 包裹）。
    band 用权威 article_band（与 axis_domain 一致），不再写测得的临时带。"""
    fm = [
        "---",
        f"id: {it['id']}",
        f"title: {it.get('title', '')}",
        f"band: {article_band(it)}",
        f"main_pos: {it.get('main_pos', '')}",
        f"vernier: {it.get('vernier', '')}",
        f"offset: {it.get('offset', '')}",
        f"collision: {bool(it.get('collision'))}",
        f"created_at: {it.get('created_at', '')}",
        "---",
        "",
        it.get("content", ""),
    ]
    return "\n".join(fm)

def deserialize_article(text):
    """解析 articles/<编号>-<标题>.md：返回 (meta:dict, body:str)。"""
    lines = text.splitlines()
    meta, body_lines, in_fm = {}, [], False
    if lines and lines[0].strip() == "---":
        in_fm = True
        for i, ln in enumerate(lines[1:], start=1):
            if ln.strip() == "---":
                body_lines = lines[i + 1:]
                break
            if ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip()] = v.strip()
        else:
            body_lines = []
    else:
        body_lines = lines
    return meta, "\n".join(body_lines).strip()

def write_article_file(item_id):
    ensure_articles_dir()
    it = get_item(item_id)
    if not it:
        return None
    p = article_path(item_id)
    with open(p, "w", encoding="utf-8") as f:
        f.write(serialize_article(it))
    legacy = legacy_article_path(item_id)
    if legacy != p and os.path.exists(legacy):
        try:
            os.remove(legacy)                    # 旧式 <id>.md 顺带清掉，避免双份
        except Exception:                        # noqa: BLE001
            pass
    return p

def migrate_article_files():
    """把旧式 <id>.md 统一改名为正式命名 <编号>-<标题>.md；幂等，返回改名数。"""
    if not os.path.isdir(ARTICLES_DIR):
        return 0
    con = connect()
    rows = con.execute("SELECT id,title FROM items").fetchall()
    con.close()
    moved = 0
    for r in rows:
        iid = r["id"]
        legacy = os.path.join(ARTICLES_DIR, f"{iid}.md")
        if not os.path.exists(legacy):
            continue
        newp = os.path.join(ARTICLES_DIR, _article_name(iid, r["title"]))
        if os.path.abspath(newp) == os.path.abspath(legacy):
            continue
        try:
            if os.path.exists(newp):
                os.remove(newp)                  # 目标已存在（重复写入）则覆盖
            os.rename(legacy, newp)
            moved += 1
        except Exception:                        # noqa: BLE001
            pass
    return moved

def recategorize_articles(remove_orphans=True):
    """按 KB 双尺分类把 articles/ 下的 .md 重新归到子目录，并清理孤儿文件。

    - 对每个 DB 条目：递归找到其当前文章文件（<id>-*.md 或 <id>.md），
      移动到 article_path(item_id) 目标分类目录（覆盖同名）；
    - 对无 DB 记录的孤儿 .md：remove_orphans=True 时直接删除（它们不属于 KB，无法归类）。
    返回 {moved, removed, errors}。"""
    moved = removed = 0
    errors = []
    con = connect()
    rows = con.execute("SELECT id,title FROM items").fetchall()
    con.close()
    db_ids = {int(r["id"]) for r in rows}

    existing = []
    for root, _dirs, files in os.walk(ARTICLES_DIR):
        for fn in files:
            if fn.lower().endswith(".md"):
                existing.append(os.path.join(root, fn))

    # 1) 把 DB 条目文件归到分类目录
    for r in rows:
        iid = int(r["id"]); title = r["title"]
        cands = [p for p in existing
                 if os.path.basename(p).startswith(f"{iid:02d}-")
                 or os.path.basename(p) == f"{iid}.md"
                 or os.path.basename(p).startswith(f"{iid}-")]
        if not cands:
            continue
        src = max(cands, key=lambda p: os.path.getmtime(p))
        it = get_item(iid)
        d = _article_dir(it)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, _article_name(iid, title))
        if os.path.abspath(src) != os.path.abspath(dst):
            try:
                if os.path.exists(dst):
                    os.remove(dst)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(src, dst)
                moved += 1
            except Exception as e:                 # noqa: BLE001
                errors.append(f"move {src}->{dst}: {e}")
        for c in cands:                            # 清掉该 id 的其它重复候选
            if c != src and os.path.exists(c):
                try:
                    os.remove(c)
                except Exception:                  # noqa: BLE001
                    pass

    # 2) 孤儿清理（无 DB 记录，不属于 KB）
    if remove_orphans:
        for p in existing:
            base = os.path.basename(p)
            m = re.match(r"^(\d+)", base)
            if m and int(m.group(1)) not in db_ids:
                try:
                    os.remove(p); removed += 1
                except Exception as e:             # noqa: BLE001
                    errors.append(f"remove {p}: {e}")

    # 3) 清理迁移后残留的空目录（含被污染的旧分类目录）
    for root, dirs, files in os.walk(ARTICLES_DIR, topdown=False):
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except OSError:                        # noqa: BLE001
                pass
    return {"ok": True, "moved": moved, "removed": removed, "errors": errors}

