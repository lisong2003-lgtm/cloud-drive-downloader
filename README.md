# 网盘通（cloud-drive-downloader）

通用下载调度层。用户链接可从 Agent / MCP / CLI、Web UI 或浏览器插件进入 pan 调度层，再交由本机、NAS Docker、服务器 Docker 或远程引擎执行。
支持 macOS / Windows / Linux；默认本机 Agent / CLI 下载，NAS 不是前置条件。

## 三类入口

- **Agent / MCP / CLI**：`scripts/pan.py get`；无服务模式可直接调用，也可通过 `scripts/pan_mcp.py` 接入 Codex 或通用 MCP 客户端。
- **Web UI**：`python3 scripts/pan.py serve` 后访问 `http://127.0.0.1:<port>`；NAS/服务器模式访问 `http://<nas>:<port>` 或 `http://<server>:<port>`。
- **浏览器插件**：加载 `extensions/chrome/`，支持 Chrome 与 Edge，可投递到本机、NAS 或服务器地址。

## 能力

- 识别网盘、直链、磁力、种子、网页视频，统一调度已有引擎（BaiduPCS-Go / AList / rclone / aria2 / yt-dlp / curl / 官方 CLI）。
- 公开搜索与网页候选：`search` / `crawl` / `movie` / `movie x`，只处理你有权访问的内容。
- 可选部署：`docker` 生成 Dockerfile、compose 与 install.sh；NAS 或服务器均可运行。
- 远程模式：`remote` 把任务交给你自己的 SSH 主机、挂载盘或私有存储。

配置优先级：`CLI 参数 > 环境变量 > config.json > 内置默认值`。示例占位符：`<api-url>`、`<download-dir>`、`<port>`、`<pan-root>`。

快速开始与三系统用法见 `SKILL.md`；Docker 属于可选部署，详见 `references/33-Docker部署与一键搜索.md`。

合规说明：不实现网盘私有协议，不解析分享页，不绕过验证码/风控/限速/会员/DRM；插件不读取网页登录态；凭据只放系统凭据库；用户对下载内容合法性负责。
