---
name: cloud-drive-downloader
slug: cloud-drive-downloader
displayName: 多网盘统一下载
version: "0.6.0"
author: lis
license: CC-BY-NC-SA-4.0
description: 统一从百度、阿里云盘、夸克、天翼、迅雷、115、123云盘、移动云盘、沃盘、UC、PikPak、坚果云、OneDrive/SharePoint、Google Drive、Dropbox、微云、蓝奏及更多网盘下载分享链接、转存文件夹或直链到本机、Windows、NAS 或远程私有存储。用户只需提供网盘下载地址；技能通过统一命令行和共享下载引擎完成识别、登录引导、目录规划和下载，不必逐个安装各家官方客户端。支持群晖、威联通、飞牛、TrueNAS、Unraid、绿联、极空间、华为家庭存储、蒲公英外接盘等通过 SSH/WebDAV/SMB/S3/rclone/挂载路径接入。免费账号默认单线程+断点续传，账号等级从已配置的可信探测器读取，探测不到按免费处理；会员仅按平台官方权益调整本地并发，不承诺不限速，不绕过平台风控。
metadata:
  version: "0.6.0"
---

# 多网盘下载

## 概述

本技能把“用户给出网盘地址 → 识别平台 → 按官方要求登录/授权 → 规划目录 → 下载到本机或远程设备”做成统一入口。

把“贴链接 → 选目录 → 自动下载”做成一个统一入口。技能本身不实现各网盘私有协议，也不要求逐个安装百度、夸克、天翼等官方客户端；它只维护一套统一 CLI，把链接交给共享引擎（AList / rclone / BaiduPCS-Go / 夸克 CLI / WebDAV / aria2 / curl）执行。

典型用法：任何 agent 拿到用户提供的网盘地址后调用 `scripts/pan.py get "<链接>"`；需要登录时只给出本机授权步骤，账号密码由用户在本机系统凭据库保存，不进入聊天、不进配置文件、不写日志。

## 铁律（先读完再执行）

1. 不破解会员、限速、验证码、广告或风控；`tier=vip` 只调整本工具调度并发，不改变平台限制，也不承诺“不限速”。
2. 账号密码、Cookie、Token、BDUSS 等凭据只允许存操作系统凭据库（macOS Keychain、Windows Credential Manager 或 Linux secret-tool），或由 AList/rclone/BaiduPCS-Go 自己保存在受保护配置中；技能不把明文写进 `config.json`，不打印，不上传云端，不进 Git。
3. 不允许用户把账号密码、Cookie、Token 发到 agent 聊天里。需要输入时执行 `python3 scripts/pan.py secret set <凭据名>`，在用户自己的本机终端不显式输入；Windows 使用 `scripts\pan.ps1` 或 `scripts\pan.cmd`。
4. 分享提取码不是账号密码，可以随下载命令传入；仍需按最小必要原则使用。
5. 公司内部资料默认只下载、不上传；下载目录不进 iCloud，也不把公司内容上传到第三方云盘或远程第三方服务。
6. 账号等级默认 `tier=auto`：优先读取 `drives.<盘>.account_tier`；配置了可信 `tier_detector` 时执行探测；全局无法可靠判断时按免费账号处理（并发 1）。不能凭账号名、用户名或链接猜会员。
7. 会员账号自动提速只做本地调度：aria2 调整 `-x/-s`，rclone 调整 `--transfers`；实际速度仍由各网盘官方规则决定。
8. 免费账号默认：并发 1、重试 3、断点续传、单任务日志。
9. 默认下载根目录：macOS 优先 `/Volumes/拓展/网盘下载` 和 `/Volumes/办公/网盘下载`；Windows 为 `%USERPROFILE%\\Downloads\\网盘下载`；其他平台为 `~/Downloads/网盘下载`。用户可用 `pan set --root`、`get --to` 或 `remote` 覆盖。
10. 目录递归下载优先使用 AList + rclone；curl 回退只适合单文件。共享引擎缺失时给出配置说明，不假装成功。
11. 远程设备按能力接入，不按品牌写死：SSH 适合远程执行，WebDAV/SMB/S3/rclone/已挂载路径适合远程落地。远程部署不上传本机凭据文件。

## 标准流程

1. `python3 scripts/pan.py doctor` —— 检查 Python、curl、系统凭据库、共享引擎和默认目录。
2. 首次使用：`python3 scripts/pan.py init` 创建 600 权限配置；Windows 用 `scripts\\pan.ps1 init` 或 `scripts\\pan.cmd init`。
3. 凭据：在本机终端执行 `python3 scripts/pan.py secret set engine.webdav`（或 `engine.alist`、`drive.<盘名>`），密码不会出现在命令行。
4. 查看登录/授权步骤：`python3 scripts/pan.py login <盘名>`。OAuth、扫码、Cookie 等按各平台官方要求完成。
5. 先预演：`python3 scripts/pan.py get "<链接>" --pwd <提取码> --dry-run --json`。
6. 确认无误后去掉 `--dry-run` 执行；目录递归时加 `--path /挂载名/子目录`。
7. 完成后报告：目标目录、成功/失败文件数、日志位置、缺失依赖或需人工核对项。

远程设备流程：`remote add` 登记 → `remote check --probe` 检查 → SSH 模式 `remote deploy` → `remote get`；WebDAV/SMB/S3 模式先在 rclone 配置 remote，再直接 `remote get` 或 `get --remote`。

## 命令速查

```bash
# 环境与识别
python3 scripts/pan.py doctor
python3 scripts/pan.py detect "https://pan.quark.cn/s/xxxx"

# 安全凭据（推荐在本机终端执行，不要在聊天中粘贴密码）
python3 scripts/pan.py secret set engine.webdav
printf '%s\n' "$WEBDAV_PASSWORD" | python3 scripts/pan.py secret set engine.webdav --stdin
python3 scripts/pan.py secret list
python3 scripts/pan.py secret check engine.webdav --json
python3 scripts/pan.py secret migrate

# 仅保存地址/用户名，密码引用系统凭据库
python3 scripts/pan.py set --webdav-url "https://dav.jianguoyun.com/dav" --webdav-user "账号"
python3 scripts/pan.py set --alist-url "http://127.0.0.1:5244" --alist-user "AList账号"

# 下载
python3 scripts/pan.py get "https://pan.baidu.com/s/1xxxx" --pwd 1234 --dry-run
python3 scripts/pan.py get "https://example.com/a.zip"                 # 直链，curl 立即可用
python3 scripts/pan.py get "<链接>" --to "/Volumes/拓展/资料"           # 指定目录
python3 scripts/pan.py get "<链接>" --path "/AList/目标目录"             # AList 目录递归

# 账号等级
python3 scripts/pan.py set --tier auto
python3 scripts/pan.py set-drive 115 --account-tier vip
python3 scripts/pan.py set-drive 115 --tier-detector '检测命令'
python3 scripts/pan.py get "<链接>" --tier vip

# Agent/脚本
python3 scripts/pan.py get "<链接>" --dry-run --json                   # 无凭据 JSON 计划

# Windows PowerShell（在 scripts 目录）
.\\pan.ps1 doctor
.\\pan.ps1 secret set engine.webdav

# 远程 NAS / 私有存储：SSH 远程执行
python3 scripts/pan.py remote add nas --kind ssh --host 192.168.1.10 --user lis --root /volume1
python3 scripts/pan.py remote check nas --probe
python3 scripts/pan.py remote deploy nas
python3 scripts/pan.py remote get nas "<链接>" --pwd <码> --dry-run

# 远程 NAS / 私有存储：rclone/WebDAV/SMB/S3 落地
python3 scripts/pan.py remote add vault --kind webdav --remote-name vault --root /downloads
python3 scripts/pan.py get "<链接>" --remote vault --dry-run --json
```

## 引擎对照

| 网盘 | 推荐引擎 | 状态 |
|---|---|---|
| 直链 HTTP/HTTPS | curl（内置） | 开箱可用 |
| 任意可直链 | aria2（可选） | 装了自动用；会员可提高本地并发，但速度仍受平台限制 |
| 百度网盘 | BaiduPCS-Go | 需登录 BDUSS；分享先转存再下载 |
| 阿里云盘 | AList | 需 AList 挂载或开放平台授权 |
| 夸克网盘 | 夸克 CLI / AList | Cookie 登录，非官方接口 |
| 天翼云盘 | AList | Cookie/账号登录 |
| 迅雷云盘 | AList | refresh_token/Cookie |
| 115 / 123 / 移动云盘 / 沃盘 / UC / PikPak / OneDrive / Google Drive / Dropbox / 微云 / 蓝奏 | AList + rclone | 先挂载/转存，再按 `--path` 递归下载；免费 `--transfers 1`，会员按 `max_connections_vip` |
| 坚果云 | WebDAV | 使用应用密码，凭据从系统凭据库/stdin 传入，支持断点续传 |
| 悟空 / 豆包新盘 / Mega / TeraBox / pCloud / Proton Drive / Yandex Disk / MediaFire / Trainbit / 光雅盘 / 飞鸡云 / 闪电盘 | AList（可选自定义 CLI） | 以当前驱动支持为准 |
| 城通网盘 | 自定义 `engine_command` | AList 兼容性不稳定 |
| 远程 NAS/私有存储 | SSH / rclone / WebDAV / SMB / S3 / mount | 不绑定品牌；有这些协议之一即可接入，详见 `references/21-远程NAS与私有存储.md` |

## 安全边界

- 默认安全路径：`config.json` 只保存 `credential:名称`/旧 `keychain:名称` 引用、用户名、URL 和路径；密码只存系统凭据库。
- 旧配置里如果存在明文 `alist_password`、`webdav_password` 或 drive 凭据字段，执行 `secret migrate` 迁移；迁移失败时拒绝继续保存新明文。
- 运行时日志和 `--json` 计划会打码或省略凭据；Basic Auth 通过 `curl --config -` 从 stdin 注入，不进入 argv。
- 第三方 CLI/AList/rclone 的登录态由其自身保存；技能不复制、不读取其内部密码。远程设备上的登录态也必须在远程设备本机保存。
- 平台要求验证码、二次验证、扫码或客户端授权时，回到官方页面完成；技能不绕过。
- 只下载你有权访问的内容，公司资料只下载不上传。

## 扩展新网盘

不改脚本，只在 `~/.config/pan-downloader/config.json` 增加：

```json
"extensions": {
  "mydrive": {
    "name": "某网盘",
    "domains": ["pan.example.com"],
    "engine_command": "mytool dl {url} --pwd {pwd} -o {dir}"
  }
}
```

占位符：`{url}` `{pwd}` `{dir}` `{name}` `{tier}`。先用 `detect` + `--dry-run` 验证。

## 按需读取

- 通用说明与排障：`references/00-使用说明.md`
- Agent 调用与凭据保护：`references/20-Agent调用与隐私.md`
- 百度：`references/01-百度网盘.md`
- 阿里：`references/02-阿里云盘.md`
- 夸克：`references/03-夸克网盘.md`
- 天翼：`references/04-天翼云盘.md`
- 迅雷：`references/05-迅雷云盘.md`
- 扩展新盘：`references/06-扩展新网盘.md`
- 115：`references/07-115网盘.md`
- 123：`references/08-123云盘.md`
- 移动云盘：`references/09-移动云盘.md`
- 沃盘：`references/10-联通沃盘.md`
- UC：`references/11-UC网盘.md`
- PikPak：`references/12-PikPak.md`
- 坚果云 / WebDAV：`references/13-坚果云.md`
- OneDrive/SharePoint：`references/14-OneDrive与SharePoint.md`
- Google Drive：`references/15-GoogleDrive.md`
- Dropbox：`references/16-Dropbox.md`
- 腾讯微云：`references/17-腾讯微云.md`
- 蓝奏云：`references/18-蓝奏云.md`
- 其他网盘：`references/19-其他网盘.md`
- 远程 NAS/私有存储：`references/21-远程NAS与私有存储.md`
- Windows 配置：`references/22-Windows配置.md`

## 自测

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/self_test.py
```

必须输出 `SELF_TEST_OK`。
