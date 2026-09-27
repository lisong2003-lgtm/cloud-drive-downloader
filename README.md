# 多网盘统一下载（cloud-drive-downloader）

## 概述

本 Skill 的功能是：让 AI 助手接收用户给出的**网盘分享链接、转存文件夹地址或 HTTP 直链**，自动识别网盘、引导官方登录或授权、规划下载目录，并调用共享下载引擎把资源下载到用户指定的位置。用户不必逐个安装百度、阿里、夸克、天翼、迅雷等官方客户端。

主要能力包括：

- 统一入口：一条命令完成链接识别、目录规划、下载执行和结果报告。
- 多网盘适配：百度、阿里云盘、夸克、天翼、迅雷，以及 115、123、UC、移动云盘、沃盘、PikPak、坚果云、微云、蓝奏云、OneDrive/SharePoint、Google Drive、Dropbox 等。
- 可扩展：未内置的网盘可通过自定义引擎命令或共享引擎接入。
- 多种目标：本机 macOS、Windows、Linux，远程 NAS，WebDAV/SMB/S3 私人存储，以及已挂载的公司介质或外接硬盘。
- 账号等级：默认自动读取可信探测器；无法确认时按免费账号策略运行。会员账号只在平台官方权益内调整本地并发，不承诺不限速。
- 凭据保护：账号密码、Cookie、Token、BDUSS 等敏感信息只允许保存到系统凭据库或受保护的第三方工具配置，不进入聊天、命令行参数、日志、Git 或第三方云盘。
- 合规边界：不破解会员、限速、验证码、广告或风控；平台要求授权、扫码、OAuth 或二次验证时，回到官方页面完成。

> 身份说明：这是 AI 助手调用的工具型 Skill，不伪装成网盘官方客户端，也不冒充任何人物或外部产品。

## 支持的网盘和存储

| 范围 | 已登记对象 |
|---|---|
| 首批网盘 | 百度网盘、阿里云盘、夸克网盘、天翼云盘、迅雷云盘 |
| 扩展网盘 | 115、123 云盘、移动云盘/和彩云、联通沃盘、UC 网盘、PikPak、坚果云、腾讯微云、蓝奏云、悟空网盘、豆包新盘、城通网盘 |
| 国际网盘 | OneDrive/SharePoint、Google Drive、Dropbox、Mega、TeraBox、pCloud、Proton Drive、Yandex Disk、MediaFire、Trainbit |
| 小型网盘 | 光雅盘、飞鸡云、闪电盘；其他站点可通过扩展配置接入 |
| 远程设备 | SSH/SFTP、WebDAV、SMB/CIFS、S3/MinIO、rclone remote、本机挂载路径 |
| NAS/私人存储示例 | 群晖 Synology、威联通 QNAP、铁威马 TerraMaster、华芸 ASUSTOR、TrueNAS、Unraid、绿联 UGREEN、极空间 ZSpace、华为家庭存储、联想个人云、海康存储、拾光坞、万由 U-NAS、飞牛 fnOS、奥睿科、雷克沙、西数 My Cloud、希捷、华硕，以及 OpenWrt/USB 硬盘、树莓派、迷你主机、VPS；私有云软件可接 Nextcloud、ownCloud、Seafile、Syncthing、Resilio Sync、MinIO |
| 私有云网关 | 蒲公英/贝锐外接硬盘按实际开放的 VPN、SMB 或 WebDAV 能力接入，不假设存在通用官方下载 API |

## 快速开始

```bash
python3 scripts/pan.py doctor
python3 scripts/pan.py init
python3 scripts/pan.py detect "<网盘分享链接>"
python3 scripts/pan.py get "<网盘分享链接>" --pwd <提取码> --dry-run --json
python3 scripts/pan.py get "<网盘分享链接>" --pwd <提取码> --to "<用户指定目录>"
```

Windows 可在 `scripts` 目录使用 `pan.ps1` 或 `pan.cmd`。首次登录按 `pan.py login <盘名>` 的官方步骤在本机完成；密码不要粘贴到聊天中。

## 账号等级与速度

- `tier=auto`：优先读取用户配置的账号等级；配置了可信 `tier_detector` 时执行探测；无法可靠确认时按免费账号处理。
- 免费账号：并发 1、重试 3、断点续传、单任务日志。
- 会员账号：只通过已配置的官方权益信息调整本地并发，实际速度仍由对应平台规则决定。
- 下载中断：保留已完成文件和任务目录，优先断点续传，不重复清空或危险覆盖。

不支持绕开平台限速、付费限制、验证码、广告或风控，也不把网络传闻中的“提速插件”当作合规能力。

## 远程 NAS / 私人存储

```bash
python3 scripts/pan.py remote add nas --kind ssh --host 192.168.1.10 --user lis --root /volume1
python3 scripts/pan.py remote check nas --probe
python3 scripts/pan.py remote deploy nas
python3 scripts/pan.py remote get nas "<链接>" --pwd <码>

python3 scripts/pan.py remote add vault --kind webdav --remote-name vault --root /downloads
python3 scripts/pan.py get "<链接>" --remote vault --dry-run --json
```

远程模式不会把本机 `config.json`、密码、Cookie 或 Token 上传到远程设备；远程设备上的登录态也必须在该设备本机保存。

## 安全边界

- 不破解会员、限速、验证码、广告或风控。
- 账号密码、Cookie、Token、BDUSS 等敏感值不进入聊天、argv、日志、明文配置、Git 或第三方云盘。
- 公司资料只下载到公司控制的设备或本机介质，不上传到第三方云盘或 Git 远端。
- 只下载用户有权访问的内容；分享提取码按最小必要原则使用。
- 平台接口变化时，以官方页面和当前维护中的共享引擎为准，不假装成功。

## 市场定位

同类能力主要分散在几类产品中：

| 类型 | 代表 | 与本 Skill 的关系 |
|---|---|---|
| 共享下载引擎 | rclone、AList、aria2 | 能力相近，擅长挂载、同步和多存储，但通常不负责完整的分享链接识别、登录引导和 Agent 统一入口 |
| 单网盘工具 | BaiduPCS-Go、夸克 CLI 等 | 主要覆盖单一平台，适合作为本 Skill 的底层引擎 |
| Agent Skill 市场 | SkillHub 等 | 可发现和安装单网盘、NAS 或下载相关 Skill；相邻技能较多，但统一聚合度、远程目标范围和凭据保护边界需要用户自行拼接 |
| MCP/工具注册中心 | MCP Registry 等 | 提供工具协议和发现机制，不是完整的网盘下载 Skill |

本 Skill 的差异化是：一个统一入口同时处理分享链接、转存文件夹和直链，统一适配多个网盘，支持本机与远程设备落盘，并提供系统凭据保护和免费/会员合规判断。它不是网盘官方客户端，也不承诺绕过任何平台限制。

## 许可

文档与脚本采用 CC BY-NC-SA 4.0，详见 `LICENSE.md`。
