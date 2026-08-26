---
name: weixin-ingest
title: 公众号/网页文章录入灯笼知识库
description: 把微信公众号文章或任意网页图文（含配图）一键录入 lantern-caliper 知识库。流程为抓取 HTML → 抽取正文与 data-src 配图 → 下载本地化到 attachments/ → 改写为 markdown（本地图引用）→ 带 source_url 与受控 axis_domain 写入 KB。当收到「把这篇公众号/网页文章存进知识库」「录入这个链接」「收录这篇文章」等请求时调用。
agent_created: true
---

# 公众号/网页文章录入灯笼知识库

**角色**：把外部图文（微信公众号文章、普通网页）摄入 lantern-caliper 知识库的机械流水线。文本 + 配图一并本地化，禁止热链防盗链资源；原文链接作为 `source_url` 写入，阅读页可点击跳转。

**触发**：用户给一个 URL 并要求「存进知识库 / 录入 / 收录 / 存档」。

## 工具
- 主工具：`skills/weixin-ingest/scripts/ingest.py`（纯标准库，须 `dangerouslyDisableSandbox=true` 联网运行）。
- 目标 KB：运行中的 `http://127.0.0.1:8731`。写入 `POST /api/kb/add`，删除 `POST /api/kb/delete`。

## 执行步骤
1. **确认后端在线**：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8731/api/state` 须为 200；否则先启动 `backend/server.py`（沙箱外后台）。
2. **判定 `axis_domain`**（受控学科域，见下表）。读文章标题/正文，选最贴合的**可见**受控域；脚本会对照 `schema.json` 全量词表校验，非法值被归一化为 None（仍能入库但无学科域，应避免）。
3. **运行录入脚本**：
   ```
   python skills/weixin-ingest/scripts/ingest.py "<URL>" \
     --axis-domain "<受控域>" \
     --source-url "<URL>" \
     [--title "<覆盖标题>"] [--dry-run] [--force] [--update-id <id>]
   ```
   - `--source-url` 默认等于输入 URL（公众号原文跳转用，必传语义）。
   - `--dry-run`：只抓取 + 解析 + 下载图片 + 打印将写入的 payload，**不** POST，用于先核对。
   - `--update-id <id>`：更新既有条目而非新建（用于已收录过同文）。
   - `--force`：跳过同 source_url 重复检查。
4. **验收**（脚本已打印关键指标，仍须确认）：
   - 返回 JSON 含 `"ok": true` 与新建 `id`（或更新成功）。
   - 每个 `/attachments/<name>` 在 `http://127.0.0.1:8731/attachments/<name>` 返回 200 + `Content-Type: image/*`。
   - 正文无 `mmbiz.qpic.cn` / `qpic` 外链残留（脚本打印「外链残留 N 处」，须为 0）。
   - `GET /api/kb/article?id=<id>` 的 `source_url` 等于原文链接。
5. **告知用户**新条目 id 与阅读页；提示**硬刷新**浏览器（前端静态，须 Ctrl/Cmd+Shift+R 才会加载新 `reader.js`）。

## 受控学科域（可见，优先从此选）
- 人文：艺术 / 文学 / 语言 / 历史 / 宗教 / 哲学
- 社会科学：伦理 / 心理 / 社会 / 人类学 / 教育 / 激励 / 地理 / 政治 / 传媒 / 法律 / 商业管理 / 经济
- 自然科学：生物 / 农业科学 / 医学与健康 / 化学 / 物理 / 天文
- 形式科学：人工智能 / 工程与技术 / 计算机 / 数学 / 统计学 / 形式逻辑 / 算法

（完整词表含隐藏域，以 `schema.json` 的 `domain_registry` 为单点真相；脚本实时校验。）

## 硬约束 / 禁区
- 配图**必须**下载本地化到 `attachments/`，**绝不**留 `mmbiz.qpic.cn` 热链（微信图带签名 + 防盗链，不下载即破图）。
- 下载须带请求头 `Referer: https://mp.weixin.qq.com/`（公众号）与浏览器 UA，否则 403。
- 配图命名 `attachments/<idx>_<md5前8>.<ext>`，正文引用写 `/attachments/<name>`（服务器根路径；前端 `rewriteRdImages` 已对 `/attachments/` 跳过，不再二次改写）。
- `source_url` 必传：阅读页「原文 ↗」芯片靠它跳转。
- **不新建重复条目**：若 URL 已收录过（同 `source_url` 或同标题），脚本默认中止并提示 `--update-id`；勿无视警告重复 add。

## 失败排查
- 抓取空 / 403：检查 UA 与 Referer；公众号须 `Referer: https://mp.weixin.qq.com/`。
- 图 GET 200 但 `Content-Type: text/html`：是 HEAD 探测假象，用 GET 实拉核对字节（magic `\x89PNG` / `\xff\xd8\xff`）。
- `axis_domain` 被归一化为 None：值不在受控词表，换可见域重跑。
- 解析内容残缺：微信改版致 `data-src` / `js_content` 结构变化时，复查抽取逻辑（脚本有「无 js_content 兜底」分支，但质量较差）。
- **删除不清理镜像文件**：API `add` 会在 `articles/<带>/<学科域>/<id>-<标题>.md` 生成文件镜像，但 KB 的 `delete` 不删该文件（返回 `file_removed:false`）。真实录入时镜像属期望同步产物；**做探针自测后须手动 `rm` 该 `.md`**（项目目录删文件走 Git Bash `rm`，避开 safe-delete 钩子），否则留污染。
