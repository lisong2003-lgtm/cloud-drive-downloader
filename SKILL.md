---
name: cloud-drive-downloader
slug: cloud-drive-downloader
displayName: 网盘通
version: "0.18.0"
author: lis
license: CC-BY-NC-SA-4.0
description: 通用下载调度层：Agent/MCP/CLI、Web UI 与浏览器插件三类入口；支持 macOS/Windows/Linux；local 默认，NAS/服务器 Docker 可选。优先走官方网页会话/官方接口/浏览器捕获直链，不破解登录/付费/限速/风控/DRM。用户自行确保下载合法。
metadata:
  version: "0.18.0"
---

# 网盘通 · 通用下载调度层

网盘通不是 NAS 专用工具。它是一个跨 macOS / Windows / Linux 的下载调度层：
接收用户提供的链接、磁力、种子或公开搜索关键词，选择本机或远端引擎执行下载。

```
用户链接
  └─→ Agent / MCP / CLI ─┐
  └─→ Web UI ────────────┼─→ pan 调度层 ─→ 本机引擎
  └─→ 浏览器插件 ────────┘             └─→ Docker/远程引擎
```

核心原则：只走**官方网页会话、官方接口、用户在官方网页触发的下载 URL**和通用直链；不破解、不伪造登录态、不绕过验证码/风控/会员/付费/DRM/限速。官方不给直链时安全失败。
插件不读取网页登录态，只投递用户主动提供的链接。需要登录时**只用统一入口** `pan login <网盘> --qr`（百度扫码写 BaiduPCS-Go），禁止临时脚本直连网盘登录接口。用户对下载内容的合法性负全责；平台限制与工具失败如实报告。

## 三类通用入口

| 入口 | 典型用法 | 依赖 |
|---|---|---|
| Agent / MCP / CLI | `pan.py get`、`pan_get`、`pan_get_plan` | Python 3 与所选引擎；无服务模式可直接调 CLI |
| Web UI | 浏览器打开 `http://127.0.0.1:<port>`、`http://<nas>:<port>` 或 `http://<server>:<port>` | `pan serve` |
| 浏览器插件 | 粘贴或右键投递链接到本机 / NAS / 服务器地址 | Chrome 或 Edge 开发者模式加载插件 |

部署形态按需选择：`local` 是默认本机模式；`nas_docker` 和 `server_docker` 只是 Docker 部署模式，不是前置条件。

## 配置优先级

`CLI 参数 > 环境变量 > config.json > 内置默认值`。

示例统一使用占位符：`<api-url>`、`<download-dir>`、`<port>`、`<pan-root>`。

## 三系统用法

### macOS

```bash
# 安装常用依赖
brew install aria2 yt-dlp rclone

# 设置与检查；默认目录：<download-dir>
python3 <pan-root>/scripts/pan.py setup --mode local --root <download-dir> --port <port>
python3 <pan-root>/scripts/pan.py doctor --json

# 下载（普通终端会自动启动本地 Web UI，并打开实时状态页 /live）
python3 <pan-root>/scripts/pan.py get "<链接>" --to <download-dir>
# 不需要自动弹窗时：
python3 <pan-root>/scripts/pan.py get "<链接>" --no-web

# 本机 Web UI
python3 <pan-root>/scripts/pan.py serve --host 127.0.0.1 --port <port>
# 登录页：http://127.0.0.1:<port>/login
# 进度页：http://127.0.0.1:<port>/live（实时显示进度、速度、剩余时间和下载位置）
# 外部 BaiduPCS-Go 已在运行时，把它的进度日志接入同一个实时页：
# python3 <pan-root>/scripts/pan.py live attach --log <日志> --target <下载目录> \
#   --total-bytes <总字节> --files-total <文件数> --pid <BaiduPCS-Go PID> --open
# --json、--events、MCP 和后台任务默认不弹窗；端口不可用时自动降级，下载继续。

# Codex MCP：写入 <codex-home>/config.toml
# [mcp_servers.pan-cloud-drive]
# command = "<pan-root>/scripts/pan_mcp.py"
# enabled = true
```

凭据保存在 macOS Keychain；配置引用形如 `credential:<名称>`，不保存明文。

### Windows

```powershell
winget install --id aria2.aria2 --accept-source-agreements --accept-package-agreements
winget install --id yt-dlp.yt-dlp --accept-source-agreements --accept-package-agreements

# 路径写法示例：<download-dir> = D:\Downloads
python <pan-root>\scripts\pan.py setup --mode local --root <download-dir> --port <port>
python <pan-root>\scripts\pan.py doctor --json
python <pan-root>\scripts\pan.py get "<链接>" --to <download-dir>
python <pan-root>\scripts\pan.py serve --host 127.0.0.1 --port <port>
```

凭据保存在 Windows Credential Manager。配置默认在 `%APPDATA%\pan-downloader\config.json`，日志在 `%LOCALAPPDATA%\pan-downloader\logs\`。

### Linux

```bash
# Debian/Ubuntu
sudo apt-get install -y aria2 yt-dlp libsecret-tools
# Fedora/RHEL
sudo dnf install -y aria2 yt-dlp libsecret

python3 <pan-root>/scripts/pan.py setup --mode local --root <download-dir> --port <port>
python3 <pan-root>/scripts/pan.py doctor --json
python3 <pan-root>/scripts/pan.py get "<链接>" --to <download-dir>
python3 <pan-root>/scripts/pan.py serve --host 127.0.0.1 --port <port>

# 检查 secret-tool
secret-tool lookup service pan-downloader
```

凭据通过 libsecret / `secret-tool` 保存；桌面环境不满足时 Skill 拒绝保存明文。

## 常用命令

```bash
python3 <pan-root>/scripts/pan.py route "<链接>" --json --brief
python3 <pan-root>/scripts/pan.py auth "<链接>" --json
python3 <pan-root>/scripts/pan.py engines "<链接>" --json
python3 <pan-root>/scripts/pan.py detect "<链接>"
python3 <pan-root>/scripts/pan.py test "<链接>" --pwd <提取码>
python3 <pan-root>/scripts/pan.py get "<链接>" --pwd <码> --dry-run
python3 <pan-root>/scripts/pan.py get "<链接>" --to <download-dir>
python3 <pan-root>/scripts/pan.py serve --host 127.0.0.1 --port <port>
python3 <pan-root>/scripts/pan.py setup --mode local --root <download-dir> --port <port>
```

公开搜索、网页候选、磁力/种子仍只处理用户主动提供的候选或公开源；不解析需登录的分享页，不绕过平台限制。

## 部署模式

```bash
# 本机模式（默认）
python3 <pan-root>/scripts/pan.py setup --mode local --root <download-dir> --port <port>

# NAS 或服务器 Docker（可选）
python3 <pan-root>/scripts/pan.py docker --out ./pan-docker
cd ./pan-docker && bash install.sh
# Web UI：http://<nas>:<port> 或 http://<server>:<port>
```

远程 SSH/存储模式见 `references/21-远程NAS与私有存储.md`；Docker 详情见 `references/33-Docker部署与一键搜索.md`。

## Agent / MCP

无服务模式：Agent 直接调用 `<pan-root>/scripts/pan.py`，不启动 Web UI。推荐先 `get --dry-run --json`，核对缺失项后再实际下载。

MCP 工具：

- `pan_get`：执行下载，默认 `dry_run=true`。
- `pan_task`：查看或控制任务。
- `pan_get_plan`：只读生成下载计划，不读取凭据明文。

通用 MCP 客户端配置（stdio）：

```json
{
  "mcpServers": {
    "pan-cloud-drive": {
      "command": "python3",
      "args": ["<pan-root>/scripts/pan_mcp.py"]
    }
  }
}
```

Codex 配置：

```toml
[mcp_servers.pan-cloud-drive]
command = "python3"
args = ["<pan-root>/scripts/pan_mcp.py"]
enabled = true
```

## 凭据与合规

- 密码、Cookie、Token 只允许通过系统凭据库保存：macOS Keychain / Windows Credential Manager / Linux secret-tool。
- 配置只保存 `credential:名称` 引用；不在聊天、命令行、日志、config.json 明文保存。
- 不绕过验证码、风控、限速、会员鉴权；不做危险删除；用户对下载内容的版权与授权负责。
- 网页/爬虫/搜索候选在下载前请自行确认有权访问；`--assume-own` 用于你确已获得授权的场景。

## 代码结构

- `scripts/pan.py`：CLI 轻入口。
- `scripts/pancli/engine.py`：核心调度。
- `scripts/pancli/engines.py`：引擎适配器。
- `scripts/pancli/webengine.py`：零客户端网页引擎桥（逐文件任务、.part 续传、实时进度）。
- `scripts/pancli/tasklock.py`：同来源单实例锁，防止多进程抢同一批文件。
- `scripts/pancli/guard.py`：后台守护、限速采样、ETA 与错误分类。
- `scripts/pancli/baidu_web.py`：百度官方网页会话驱动。
- `scripts/pancli/report.py`：下载报告 / 实时速度 / 任务控制。
- `scripts/pancli/setup.py`：doctor / setup / 向导 / MCP 指引。
- `scripts/pancli/carriers.py`：任务、目录、直链、转存等载具逻辑。
- `scripts/pancli/docker.py`：可选 Docker 部署与分片下载。
- `scripts/pancli/remote.py`：远程 SSH/rclone/WebDAV/SMB/S3/mount。
- `scripts/pancli/web.py`：Web UI 与 API。
- `references/35-登录与WebUI统一流程.md`：跨网盘登录/授权与 Web UI 进度规范；`pan route --brief` 一次返回省 token 的登录门禁/预检/下一步，`pan auth` 做秒级本地门禁。
- `references/36-WebUI实时进度规范.md`：Web UI 实时进度要求。
- `references/37-零客户端引擎桥.md`：不装各家网盘客户端的官方网页会话、浏览器/AList/OAuth 桥与边界。
- `references/38-百度官方网页会话桥.md`：百度默认零客户端流程、接口与安全失败边界。
- `references/39-单实例与续传安全.md`：**同一来源只允许一个下载进程**、续传禁用 `--ow`、后台用双 fork 守护化、限速如实报告与错误分类。
- `OPENING_PROMPT.md`：网盘通维护开工提示词。
- `TOKEN_SAVING_PLAN.md`：省 token 与长会话规则。
- `scripts/self_test.py`：离线自检。

## 单实例与续传安全（v0.16.0 硬规则）

2026-10-15 实测教训：同来源起多个下载进程会互相抢带宽/覆盖断点，表现为"跑了很久没进展"。

- **同一 `(drive, source, target)` 只允许一个下载进程**；计划步骤/官方网页路径带锁，抢不到直接退出码 `9`。
  查看/清理：`pan guard status`、`pan guard clean`。
- **续传一律禁止 `--ow`**：会让已下分片从头重下；计划构建阶段自动剥离（含 config 里写死的）。
- **后台常驻用双 fork**：`pan guard daemon --cmd '...' --log <日志>`，不要用 `nohup ... &`。
- **限速如实报告、不混同登录失败**：`pan guard speed --target <目录>` 采样；低于 200 KB/s 判定为
  网盘侧限速/免费账号特征，输出明确提示，不破解限速。`pan guard eta` 换算剩余时间。
- **错误分类**：`pan guard error --text '<原始错误>'` → login_required / dlink_missing / captcha /
  risk_control / http_403 / not_found / disk_full / throttle，并给处置建议。
- **扫码稳定**：百度只走 `pan login baidu --qr`；每次生成时间戳+随机后缀的唯一二维码文件，避免扫到缓存旧码。

详见 `references/39-单实例与续传安全.md`。

## 测试

```bash
python3 <pan-root>/scripts/self_test.py
python3 <pan-root>/scripts/pan.py docker check --json
```

## 权限边界

- 公司数据上云、删除原始资料、未授权系统级配置变更仍需用户确认。
- 本 Skill 只做下载能力调度，不替代专业判定，不新增解析分享页或绕过平台限制能力。
