## 2026-10-14 v0.14.1（三平台发布简介与脱敏修订）

- 统一更新发布简介：明确 Agent / MCP / CLI、Web UI、浏览器插件三类入口。
- 明确 macOS / Windows / Linux 支持；`local` 为默认模式，NAS / 服务器 Docker 仅是可选部署。
- 发布摘要去除本机绝对路径，SHA256SUMS 使用相对文件名。
- 保持纯调度层：不新增解析分享页、破解或绕过登录 / 付费 / 限速 / DRM 能力。

## 2026-10-14 v0.14.0（通用下载调度层定位）

- 首屏与 README 从 NAS 优先改为“通用下载调度层”，三类入口统一为 Agent/MCP/CLI、Web UI、浏览器插件。
- 新增 macOS / Windows / Linux 用法：brew/winget/apt/dnf、默认路径和系统凭据库；Web UI 使用占位地址。
- 浏览器插件更名“通用 pan 下载插件”，支持本机/NAS/服务器地址，明确不读取网页登录态。
- MCP 文档补充 `pan_get` / `pan_task` / `pan_get_plan`、通用 MCP 客户端配置和无服务模式。
- setup/doctor 以 local 为默认；NAS/server Docker 只是可选部署模式；本机模式不再检查远程依赖。
- 新增自检：三入口/三系统/占位符、插件一致性、local/nas_docker/server_docker 配置生成；`SELF_TEST_OK checks=375`。

## 2026-10-14 结构优化·之二（拆分 Web 子模块）

- 抽出 `scripts/pancli/web.py`（883 行）：Web/Agent 一站式页面、PWA、实时速度、serve HTTP 服务全部外移。
- `scripts/pancli/engine.py` 从 5985 行降到 5119 行；`pan.py serve`、`pan task` 等通过懒加载调用 web 子模块，行为不变。
- `self_test.py` 离线自检继续通过：`SELF_TEST_OK checks=358`。

## 2026-10-14 结构优化（方案 A：保留全部功能，拆分入口）

- `scripts/pan.py` 改为 CLI 轻入口（约 30 行），实现迁移到 `scripts/pancli/engine.py`。
- 修正 `engine.py` 中的 `SKILL_DIR` 与 `pan_mcp.py` 相对路径，使其在 `scripts/pancli/` 下仍指向技能根目录。
- `self_test.py` 改为直接加载 `pancli/engine.py`，离线自检 358 项通过（SELF_TEST_OK checks=358）。
- `config.example.json` 恢复 `http.live_status: true` 默认值，与新版实时监控自检一致。
- 备份：先前的完整回滚备份与本次修改前备份见 `work/skill-backup-cdd-full-20261013/`。

## 2026-10-13 回滚到旧版（搜索/爬虫/movie/docker）

- 按用户指令回滚到 9:16 功能版：恢复 `pan search`（公开搜索一键下载）、`pan crawl`（网页爬虫）、`pan movie sources/get/x`、`pan docker`（Docker/NAS 一键安装）。
- 恢复 `scripts/pan.py` 旧完整入口、`scripts/self_test.py`、`scripts/pan_mcp.py`、`scripts/pan_web.*`、`scripts/clipboard_monitor.py`、`scripts/feishu_bot.py`。
- 恢复 `references/`（33 篇详细文档）与 `extensions/chrome`。
- 恢复旧 Docker 模板：python:3.11-slim + curl + aria2 + yt-dlp + ffmpeg + ssh，暴露 17890。
- 当前版合规重构已备份到 `work/restore-backup-refactor-20261013/`。

---

## v0.8.0（合规重构）

- **改为纯下载调度层**：不再解析网盘分享页、不提取直链、不猜签名、不抓 Cookie/Token、不做 UA 伪装/IP 轮换、不绕过登录/VIP/限速/验证码/风控/DRM。
- **不再搜索/索引/推荐资源**：输入只来自用户明确提供的 URL/文件 ID/分享链接；删除旧 `search`/`crawl`/`movie`/`x` 逻辑和网页爬虫。
- 新增引擎适配器 `scripts/engines/`：curl / wget / aria2 / rclone / AList（透传用户已配置的命令）。
- 新增命令：`get`、`engines`、`doctor`，全部支持 `--json`。
- `credentials.py`：凭据只从 macOS Keychain / Windows Credential Manager / Linux secret-tool 读取；Cookie 经 0600 临时文件传给工具，用完即删。
- 引擎未安装时只提示安装，不内置替代破解方案；不承诺不限速。
- 测试：`tests/test_pan.py` 只使用公开直链与本机引擎检测。
- 旧实现（含 references / 网盘解析逻辑）已迁出到 `work/legacy-*` 存档，不进本 Skill 目录。

## Unreleased（本地迭代 R16）

- 新增通用 HTTP/HTTPS 直链下载模块 `scripts/http_downloader/`：
  - 新命令 `pan direct <直链>`：只接受 http/https 直链，支持 Range 并发分片、断点续传、重试、超时、SHA-256/MD5 校验、`--to`、`--json`。
  - `pan get --generic-direct` 与 `pan movie get --generic-direct`：把 http/https 直链切换到通用模块，非交互必须 `--confirm-own-use`。
  - 合规边界：不解析网盘分享链接、不绕过登录/验证码/防盗链/会员、不搜索盗版资源；下载前强制确认用户对该文件拥有授权或公开许可。
  - 本机与 NAS 容器均已部署；容器内 `python3 -m http_downloader.self_test` 通过（单流/并发分片/拒绝非 http）。

## Unreleased（本地迭代 R15）

- v0.13 新增 `pan crawl` 网络爬虫能力：
  - 新增 `pan crawl <网页URL>`：抓取网页/目录页里可直接下载的媒体、文件、magnet、torrent 候选，支持 `--kind movie|video|music|file`、`--limit`、`--timeout`、`--depth`（同域分页跟进最多 5 个子页）、`--json`。
  - 一键下载：`pan crawl "<URL>" --pick 1 [--kind movie] [--remote nas] [--to 目录] [--dry-run]`，复用现有下载管线；网页候选默认需 `--assume-own` 确认有权访问，`--dry-run` 预览不受限。
  - 自动识别并优先排序 torrent/video/movie 候选；支持相对链接归一化和磁力/BT 种子识别。
  - 搜索与爬虫共用同一套“选中即下载”逻辑（`dispatch_chosen_download`），行为保持一致。
  - 离线自测增至 358 项，覆盖单页提取、相对链接、磁力/BT、分类过滤、授权确认与 dry-run。

## Unreleased（本地迭代 R14）

- v0.12 解决搜索与 Docker 验证遗留风险：
  - 新增 `pan search "关键词" --check`：离线/真机逐个测试搜索源连通性（archive.org / DuckDuckGo / yt-dlp），JSON 给 Agent 解析；沙箱外网受限时本机用它确认。
  - 网页搜索候选增加授权确认：`--pick` 网页候选默认禁止直接下载，须加 `--assume-own` 或 `--force`（`--dry-run` 预览不受限），避免误下未授权内容。
  - 新增 `pan docker check`：检测本机 docker/podman 与生成文件完整性；无 Docker 的主机也能静态校验并得到明确的 NAS 部署指引。
  - 离线自测增至 340 项，覆盖搜索连通性检测、网页候选授权确认与 docker check。

## Unreleased（本地迭代 R13）

- v0.11 一键搜索下载 + Docker/NAS 部署：
  - 新增 `pan search "关键词"`：聚合搜索公开/官方资源（archive.org 公版电影音频、DuckDuckGo 网页候选、yt-dlp 公开视频搜索），支持 `--kind movie|video|music|file`、`--limit`、`--json`、`--list-providers`。
  - 一键下载：`pan search "关键词" --pick 1` 选中候选直接走现有下载管线；支持 `--remote nas`、`--to`、`--dry-run`、`--split`、`--live`。
  - 搜索对齐合规边界：只列公开/公版/你有权下载的内容，不破解会员、验证码、限速或风控；网页搜索结果需自行确认授权。
  - 新增 `pan docker` 子命令：在技能根 `docker/`（或自定义 `--out`）生成 `Dockerfile`、`docker-compose.yml`、`install.sh`、`README-Docker.md`；镜像内置 python+curl+aria2+yt-dlp+ffmpeg+ssh，容器里 serve 默认监听 `0.0.0.0:17890`。
  - Docker 部署到 NAS 场景：群晖 Container Manager / 威联通、飞牛、TrueNAS 等装好 Docker 后执行 `bash install.sh`，`state/` 与 `download/` 用卷挂载持久化；容器不包含本机 config/cookie/token。
  - 离线自测增至 322 项，覆盖 search 候选解析与 Docker 文件生成。

## Unreleased（本地迭代 R12）

- v0.10 免费电影 / NAS 下载 / X(推特) 视频：
  - 新增 `pan movie sources`：列出公开/公版/官方免费电影入口（Internet Archive、Public Domain Torrents、archive.org 磁力、官方公开资源）；只列你有权下载的内容，不搬运盗版源，不破解会员/验证码/风控。
  - 新增 `pan movie get <url> [--candidates url2,url3]`：多候选直链真实测速，自动选最快源再下载；支持 `--remote <nas>`、`--to`、`--tier`、`--dry-run`、`--split` 分片并发。
  - 新增 `pan movie x <url>`：下载 X（原推特）推文视频，识别 `x.com/i/status`、`twitter.com/...`、`mobile.twitter.com/...`，走内置 yt-dlp 多分段下载；登录/私密推文请配置 `ytdlp.cookies_from_browser`。
  - `detect_drive` 已将 twitter/x.com 归入 stream（yt-dlp），无需额外客户端。
  - NAS 场景：`movie get`/`movie x` 都支持 `--remote nas`，先测速选最快，再交给远程设备下载。
  - 离线自测新增 movie sources / X 识别 / movie get 最快候选 / movie x dry-run 用例。

## Unreleased（本地迭代 R11）

- v0.9 统一入口 + 最快下载体验：
  - 新增网页视频/HLS/流媒体识别（YouTube、bilibili、vimeo、twitch 等），自动走 yt-dlp 多分段下载。
  - 新增内置 `pan probe` 命令：对多个候选直链逐源真实测速（默认各采样前 200KB），按速度排序并推荐最快链接。
  - 新增技能自带便携引擎：`tools/pylib` 预装 yt-dlp（已在本机装载）；`find_engine_binary` 自动在 `tools/bin、tools/pylib/bin、tools/aria2/bin` 查找，无需用户逐个装客户端。
  - 配置新增 `ytdlp.format / concurrent_fragments / cookies_from_browser`（对流媒体多站可用性）与 `engines.yt-dlp`。
  - 新增 `rank_fastest_urls` 测速函数与 `DRIVES.stream`。
  - 离线自测增至 300 项。

## Unreleased（本地迭代 R10）

- 多协议下载扩展（HTTP/FTP/BT/磁力）：
  - 新增 `ftp://`、`ftps://` 直链识别，自动走 curl/aria2 断点续传。
  - 新增 `magnet:` 磁力链接与 `.torrent` 种子识别，自动路由到 aria2（DHT → P2P + tracker）。
  - aria2 分支新增多连接并发（HTTP/FTP 用 `-x/-s`，免费默认 4、会员 16，可在 `bt.connections_free/vip` 调整）与磁力/BT 专属参数（`--enable-dht`、`--bt-save-metadata`、`--bt-max-peers`、`--seed-time`、`--bt-tracker`）。
  - 新增配置段 `bt`（trackers / seed_time / enable_dht / dht_listen_port / bt_max_peers / connections_free / connections_vip），`config.example.json` 同步。
  - 新增 `is_magnet_url`、`is_torrent_path`、`is_ftp_url` 识别助手。
  - 离线自测新增 ftp/ftps/磁力/.torrent 识别与计划拼接用例。

## Unreleased（本地迭代 R8）

- 发布后小白上手：
  - 新增 `references/29-小白快速上手指南.md`：面向完全没碰过代码的用户，步骤式说明装 Python、拿工具、一键配置、网页下载、找文件、常见问题与安全提醒。
  - 新增 `scripts/pan_web.ps1`：Windows 一键网页下载助手（启动 serve + 剪贴板监听 + 打开 Web UI），与 `pan_web.sh` 对齐。
  - 离线自测从 272 增至 274 项，覆盖 Windows 一键脚本与小白指南存在性。

## Unreleased（本地迭代 R7）

- 第 3 步·飞书机器人（桥接层）：
  - `notify` 新增 `feishu` 通道：群机器人 Webhook 文本消息 `{"msg_type":"text","content":{"text":...}}`，支持 `pan notify --channel feishu`；默认配置与 `config.example.json` 同步加入 `notify.feishu_secret`。
  - 新增 `scripts/feishu_bot.py`：飞书事件回调桥（`url_verification` challenge 应答、自动抽取 http(s) 链接与“提取码/密码/pwd”后的 4-6 位码、POST 到 `serve` 的 `/api/download`），纯标准库、支持 `--check` 离线自检、`--host/--port/--target`。
  - 新增 `references/28-飞书机器人.md`：说明群机器人 Webhook 只能发通知、自建应用事件订阅才能收消息；给出事件回调地址配置与 SSH 反向隧道/VPS 公网方案；秘钥走系统凭据库，不写 config/Git。
  - 离线自测从 258 增至 272 项，覆盖飞书 notify payload、桥接脚本存在性与自检、回调消息转发。

## Unreleased（本地迭代 R6）

- 第 2 步：远程 NAS 常驻 + 网页控制。
  - `remote deploy <name> --web-port <端口> [--web-host <0.0.0.0|127.0.0.1>] [--web-reports-dir <目录>]`：部署后通过 SSH nohup 在远程设备后台启动 `scripts/pan.py serve`，Web 页面通过 `--reports-dir` 指向远程 root，自动扫描任务中心/实时速度/历史报告。
  - 新增 `remote web <name>` 帮助命令：打印远程 Web 地址、SSH 反向隧道命令与本地访问地址（不实际连接）。
  - 部署计划/JSON 输出新增 `web_port/web_host/web_url/web_guide` 字段，供 Agent 与 Web 控制使用。
  - `serve` 新增本机任务投递回跳字段（`live_url/home_url`）与远程报告目录兼容；离线自测从 244 增至 256 项，覆盖远程 Web 命令拼装与 0.0.0.0 直连 URL。
  - 远程 Web 安全提示：默认监听 127.0.0.1，需局域网直连才用 0.0.0.0 并确认防火墙；推荐 SSH 反向隧道访问，不直接暴露公网。

## Unreleased（本地迭代 R2）

- 新增一键安装+配置向导 `pan setup`：创建/刷新 config，检测系统包管理器（brew/apt/dnf/winget），列出缺失依赖的安装命令；`--apply` 实际执行；`--root` 可同时设定下载目录；`--json` 供 agent 使用。
- 新增任务控制（真实落地 v2）：`get` 实际下载前登记 `任务控制.json`（目标/链接/引擎/档次/PID/状态/当前步骤），提供 `pan task list|show|pause|resume|delete|retry <id>` 子命令。
- 暂停/继续实现为「进程级真实暂停」，对当前引擎子进程发送 SIGSTOP/SIGCONT；取消发送 SIGTERM 后兜底 SIGKILL，不依赖轮询猜状态。
- `serve` 首页升级到任务中心 v2：表格增加「操作」列，运行中可暂停/取消，暂停中可继续/删除，已结束可重试/删除；新增 `GET /api/task/action?task=<id>&action=pause|resume|delete|retry` 接口。
- `serve_unified_tasks` / `serve_task_controls` 递归收集 任务控制.json（覆盖任务目录、live_dir、report_dir），暂停/取消状态在任务中心正确显示。
- 重试基于任务控制记录自动重新拉起 `get` 子进程（不保存提取码明文；有提取码的任务会提示补充 `--pwd`）。
- 离线自测从 161 增至 170 项，覆盖任务登记、状态机、递归合并与控制动作。
- 新增智能默认 + 自动重试：`smart.auto_classify` 与 `get --classify` 按扩展名自动归档（影视/音乐/文档/图片/压缩包/其他）；默认重试 3 次 + 断点续传已有能力对齐说明。
- 新增 Web UI PWA：`/manifest.webmanifest`、`/sw.js`、动态 PNG 图标路由，网页可安装为独立窗口。
- 离线自测增至 213 项，覆盖内容分类、分类目录、PWA 清单/图标/页面注入。

- Web UI 重新美化：任务中心首页与实时速度页从朴素表格改为深色卡片式界面（运行中/已完成/失败/全部统计卡、状态徽章、速度高亮、圆角按钮、移动端两列自适应）。
- 修复 Web UI 打不开：任务中心首页模板中 `width:100%` 里的 `%` 被 Python `%` 格式化误当占位符，导致首页 `ValueError: unsupported format character '}'` 返回空响应；已改为 `width:100%%` 并把首页渲染抽成 `serve_home_html(tasks)`，离线自测新增回归项，checks 从 191 增至 199。

- 新增浏览器扩展 + 剪贴板监听（`extensions/chrome/`，Manifest V3）：右键「发送 网盘链接 到 pan 下载」、复制/选区自动识别链接、popup 手动提交，接入 `POST /api/download` 后台启动下载；扩展仅允许访问 `http://127.0.0.1:17890/*`，不读取网盘页面登录态。
- `serve` 新增 `POST /api/download`（url/pwd/to/engine/tier/path）供扩展与 Agent 直接投递下载任务；URL 为空或启动失败返回人话错误。
- 离线自测增至 191 项：覆盖 `_spawn_download_task` 参数拼装/空链接/启动异常、Chrome 扩展清单 manifest_version=3 且 host_permissions 仅本机端口、扩展文件完整性与 JS 语法检查（node --check，无 node 退化为括号平衡校验）。

- 新增任务中心 Web UI v1：`serve` 首页从只读状态页升级为「跨网盘任务中心」，实时任务与历史报告统一成一张表（任务ID/网盘/当前步骤/实时与平均速度/状态/更新时间）；新增 `/api/tasks` 与 `?state=` 筛选接口。
- 新增实时速度监控：`get --live`（或配置 `http.live_status=true`）在下载期间周期性采样目标目录字节增量，写入 `下载速度.live.json`（含实时/平均速度 KB/s、已下载字节、当前步骤、状态）；`serve` 页面新增 `/live` 自动刷新视图与 `/api/live` 接口。
- 新增 R9：常见错误人话提示。`get` 失败时终端和 `下载报告.json` 的 `steps[].hint` 输出中文动作建议（超时/依赖缺失/连接失败/非 2xx/WebDAV/百度/夸克），无法判断时保留原文退出码不猜测。
- 新增下载统计与可观测性：实际下载完成后在目标目录生成 `下载报告.json`（起始/结束时间、耗时、逐步骤退出码/耗时、缺失与警告）。
- 新增 `get --events`：实际下载过程输出逐步 JSON 事件（NDJSON），便于 Agent 与上层可视化消费，凭据仍全部打码。
- 新增配置项 `http.report_dir` 与 `http.on_complete_hook`：支持自定义报告目录和在下载成功后执行本地完成钩子（如 rsync 到远端）。
- 新增 R6-R8：
  - `init --wizard` 环境检测向导、`doctor` JSON/文本给出安装建议命令；
  - `mcp guide` 输出 Codex `[mcp_servers]` 注册片段；新增 OpenAPI 稳定接口文档 `references/26-OpenAPI.md`；
  - `notify` 扩展 telegram/discord；新增 `serve` 只读本地状态页（127.0.0.1:17890，/、/api/reports、/api/status）。
- 新增 R5：`notify send`（Bark/企业微信，webhook 存系统凭据库，默认 dry-run）+ 真机验证脚本 `scripts/verify_real_env.py` 与 `references/25-真机验证清单.md`（覆盖 Range 分片、rclone 转存、MCP 注册、通知发送）。
- 新增 R4：`transfer` / `sync` 子命令（rclone 跨盘转存/增量同步，默认 dry-run）、公司目录红线默认拒绝、`sync` 需显式 `--delete + --apply`；新增 `references/24-跨盘转存与同步.md`。
- 新增 R3：CLI JSON 覆盖补齐（`detect/dirs --json`）+ 最小 stdio MCP 服务器 `scripts/pan_mcp.py`（纯 Python），暴露 `pan_doctor/pan_detect/pan_dirs/pan_get_plan`；新增 `references/23-MCP与Agent接口.md`。注册到 Codex 的 `[mcp_servers]` 需在本机配置，本 skill 原版不含平台配置。
- 新增 R2：http 直链单文件 Range 分片（`get --split N` / `http.range_split`），服务端不支持时自动回退整文件；分片结果进 `下载报告.json`。
- 保持 v0.6.0 的既有铁律不变：不绕过限速/风控，凭据不落盘不输出。

## Unreleased（本地迭代 R3）

- 新增「测试连接」入口 `pan test <url>`：只读验证一条链接能否下载（识别网盘、依赖/配置是否齐备、目标目录是否可写、是否提供提取码），不下载不写盘；`--json` 供 Agent 使用。
- `pan login <盘名> --open`：用默认程序打开对应网盘的授权教程，降低找登录步骤的成本（仍不绕过平台验证码/风控）。
- Web UI 新增独立「测试连接」页 `/test`：粘贴链接/提取码即可调用 `/api/test` 显示人话检查结果；任务中心导航与 PWA 缓存已包含该页。
- `serve` 新增 `GET /api/test?url=...`，Web UI/扩展可直接使用测试连接能力。
- MCP 新增 `pan_test` 工具：返回一条链接的测试连接 JSON。
- 离线自测新增第 30 项，checks 从 221 增至 227。

## Unreleased（本地迭代 R4）

- 新增下载后处理链样板 `scripts/hooks/post_media.sh`：下载完成自动解压 ZIP/TGZ，预留 Jellyfin/Emby/Plex 媒体库扫描命令位；默认 AUTO=0 只预览，改 1 生效。
- 浏览器扩展弹窗新增「测试连接」区块：粘贴链接（可选提取码）直接调用 `/api/test` 显示人话检查结果，不真正下载。
- 提取码智能提示：百度/夸克/蓝奏/123/微云等常见分享盘未传 `--pwd` 时提前 output 提示，避免下载失败后无头绪。
- 新增定时/低峰下载骨架：`get --at HH:MM` 或 `http.schedule_at`，到点再开始；dry-run/JSON 不阻塞。
- 离线自测新增第 32 项，checks 从 232 增至 238。

## Unreleased（本地迭代 R5：网页/Agent 一站式）

- 首页新增「粘贴链接开始下载」表单：提交后自动跳转 `/live` 看实时进度；修复首页 `width:100%%` 转义回归。
- `POST /api/download` 新增返回 `live_url` / `home_url`，让 Agent/扩展直接把实时进度链接给用户。
- 新增全局剪贴板监听 `scripts/clipboard_monitor.py`（macOS `pbpaste` / Linux `xclip/xsel` / Windows PowerShell）：剪贴板出现网盘链接自动投递本机 serve，去重 10 分钟，`--once` 支持单检。
- 新增一键脚本 `scripts/pan_web.sh`：启动 serve + 剪贴板监听 + 自动打开 Web UI。
- 离线自测新增第 33 项，checks 从 238 增至 244。

# Changelog

## 0.6.0 - 2026-09-27

- 新增 `README.md` 概述，明确本 Skill 的功能、支持网盘、远程存储、账号等级、凭据保护和合规边界。
- 补充市场定位：与 rclone、AList、单网盘工具及 Skill 市场的关系和差异化。
- 完善发布元数据：新增 `manifest.json`、`LICENSE.md`，同步 `agents/openai.yaml` 展示说明。
- 保持核心下载逻辑不变，继续通过离线自测和发布合规检查。

## 0.5.0 - 2026-09-27

- 增加 Windows 启动包装器、系统凭据库后端和远程 NAS/私人存储能力。
- 扩展网盘覆盖和本地/远程引擎适配。

## 0.1.0 - 2026-09-24

- 首个可用版本：统一识别、目录规划、下载引擎适配、免费账号策略和凭据安全边界。
