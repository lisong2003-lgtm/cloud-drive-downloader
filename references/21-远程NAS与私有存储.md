# 远程 NAS 与私人存储

## 能做什么

把分享链接下载到远程设备，而不是只落到当前电脑。远程设备不按品牌写死；只要它提供以下任一能力，就能登记为 `remote`：

- SSH / SFTP：在设备上直接执行下载脚本。
- WebDAV：通过 rclone 读写，常用于群晖、坚果云、私有云和部分蒲公英网关。
- SMB / CIFS：通过本机挂载目录或 rclone SMB remote 接入。
- S3 / MinIO：通过 rclone S3 remote 接入。
- 本机已挂载盘：例如 macOS 的 `/Volumes/...`、Windows 的 `Z:\下载`。

品牌只作为接口示例，不代表官方 API 或原生支持：群晖 Synology、威联通 QNAP、铁威马 TerraMaster、华芸 ASUSTOR、TrueNAS、Unraid、绿联 UGREEN、极空间 ZSpace、华为家庭存储、联想个人云、海康存储、拾光坞、万由 U-NAS、飞牛 fnOS、奥睿科、雷克沙、西数 My Cloud、希捷、华硕，以及 OpenWrt/USB 硬盘、树莓派、迷你主机、VPS。私有云软件还可接 Nextcloud、ownCloud、Seafile、Syncthing、Resilio Sync、MinIO 等。

蒲公英/贝锐外接硬盘通常通过 VPN、SMB 或 WebDAV 暴露，是否可用取决于具体型号和网关配置；不要假设它有一个通用官方下载 API。先确认设备实际开放的协议，再按 `mount`、`rclone` 或 `webdav` 登记。

## 两种模式

### A. 远程执行模式（`kind=ssh`）

下载、校验和落盘都发生在远程设备上。适合能运行 Python 的群晖、QNAP、TrueNAS、Unraid、飞牛、Linux 小主机和 VPS。

```bash
python3 scripts/pan.py remote add nas \
  --kind ssh --host 192.168.1.10 --user lis --root /volume1
python3 scripts/pan.py remote check nas --probe
python3 scripts/pan.py remote deploy nas
python3 scripts/pan.py remote get nas "<分享链接>" --pwd <提取码>
```

远程设备第一次使用前，必须在该设备本机完成 AList/rclone/BaiduPCS-Go 等登录和凭据保存。部署包不上传本机 `config.json`、密码、Cookie 或 Token；SSH 使用密钥/agent，`BatchMode=yes` 不会在命令行传远程密码。

### B. 远程落地模式（`kind=rclone` / `webdav` / `smb` / `s3` / `mount`）

本机先下载到暂存目录，再用 rclone 复制到远处存储。适合只有 WebDAV、SMB、S3 的 NAS、私有云或外接硬盘。暂存目录默认在 `PAN_STATE_DIR/remote-staging/<remote>`，下载成功后再上传。

```bash
# 先在 rclone 里配置一个名为 vault 的 remote，再登记
python3 scripts/pan.py remote add vault \
  --kind webdav --remote-name vault --root /downloads
python3 scripts/pan.py remote check vault --probe
python3 scripts/pan.py remote get vault "<分享链接>"

# 本机已挂载的 SMB / 外接盘，直接写挂载目录
python3 scripts/pan.py remote add office-disk \
  --kind mount --root "/Volumes/办公盘"
```

也可以直接在主命令指定：

```bash
python3 scripts/pan.py get "<分享链接>" --remote vault
```

## 命令说明

```bash
python3 scripts/pan.py remote add <名称> --kind ssh --host <地址> --user <用户> --root <目录>
python3 scripts/pan.py remote add <名称> --kind webdav --remote-name <rclone名> --root <目录>
python3 scripts/pan.py remote add <名称> --kind mount --root "Z:\\下载"
python3 scripts/pan.py remote list --json
python3 scripts/pan.py remote check <名称> [--probe]
python3 scripts/pan.py remote deploy <名称> [--dry-run]
python3 scripts/pan.py remote get <名称> "<链接>" [--pwd <码>] [--dry-run]
python3 scripts/pan.py remote remove <名称>
```

## 凭据与隐私

- 远程账号密码只存远程设备的系统凭据库或对应工具的受保护配置；本技能不上传。
- `remote add --credential-stdin` 仅把凭据写入当前设备的系统凭据库，配置只留 `credential:` 引用。
- 不要把密码放进 `--host`、URL、命令参数、日志、聊天或 Git。
- 公司内部资料只下载到公司控制的设备或本地介质，不上传第三方云盘。
- 远程设备上的第三方工具仍需遵守网盘平台规则；本技能不绕过验证码、风控、会员限制或限速。

## 排障

| 现象 | 检查 |
|---|---|
| `remote check nas --probe` 失败 | SSH 端口、密钥/agent、远程 Python 3、`root` 路径 |
| rclone remote 不存在 | 在**执行下载的那台设备**运行 `rclone config` 配置 remote |
| WebDAV 401/403 | 使用应用密码或专用 token；不要把主密码写进配置 |
| SMB 盘未出现 | 先在系统挂载，Windows 可用 `net use`，macOS 用 Finder 挂载 |
| 群晖/飞牛无法 SSH | 改用 WebDAV/SMB/S3 的远程落地模式，或启用设备允许的 SSH |
| 蒲公英外接盘找不到 | 先建立 VPN，确认网关暴露的是 SMB 还是 WebDAV，再按协议登记 |
