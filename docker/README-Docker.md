# 网盘通 Skill · Docker/NAS 部署

- 镜像基于 python:3.11-slim，内置 curl、aria2、yt-dlp、ffmpeg、ssh 客户端。
- 暴露 17890 端口（serve Web UI / 下载接口），配置与任务状态存 ./state，下载文件落 ./download。
- 本容器不包含、不上传本机 config.json / Cookie / Token；请在容器内重新配置登录态。
- 群晖：套件中心装 Container Manager → 本目录 `docker compose up -d`；威联通/飞牛/TrueNAS 同理。

```bash
bash install.sh
```
