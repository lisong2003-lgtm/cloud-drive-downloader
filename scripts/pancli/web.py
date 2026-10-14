"""网盘通 Web/Agent 一站式服务子模块（从 engine.py 拆分，命令入口由 engine 懒加载）。"""
# 自动继承 engine 的全部共享工具（SKILL_DIR、配置、日志、下载调度等）
from pancli.engine import *  # noqa: F401,F403
from pancli.engine import _probe_link_checks  # noqa: F401
from pancli.report import _atomic_write_json, LIVE_FILE_NAME, TASK_FILE_NAME, read_task_records  # noqa: F401
import struct as _struct  # noqa: F401
import zlib as _zlib  # noqa: F401


def read_report_summary(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {"path": str(path), "ok": data.get("ok"), "engine": data.get("engine"),
            "drive": data.get("drive"), "target": data.get("target"),
            "finished": data.get("finished"), "elapsed": data.get("elapsed")}


def serve_reports_json(reports_dir, limit=50):
    base = Path(reports_dir)
    out = []
    if base.exists():
        for p in sorted(base.glob("**/下载报告.json"))[:limit]:
            item = read_report_summary(p)
            if item:
                out.append(item)
    return out


def serve_live_json(reports_dir, limit=50):
    """扫描实时速度状态文件（下载速度.live.json），返回最近 limit 个。"""
    base = Path(reports_dir)
    out = []
    if not base.exists():
        return out
    files = sorted(base.glob("**/%s" % LIVE_FILE_NAME), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data["path"] = str(f)
        data["mtime"] = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S%z")
        out.append(data)
    return out


def _task_id(target):
    import hashlib
    return hashlib.sha1(str(target).encode("utf-8")).hexdigest()[:12]


def serve_unified_tasks(reports_dir, limit=100, state=None):
    """统一任务中心：实时任务 + 历史报告 + 任务控制记录汇总成一张任务表。"""
    control = serve_task_controls(reports_dir, limit=limit * 2)
    tasks = []
    # 实时任务（优先以 live 文件为准）
    live = serve_live_json(reports_dir, limit=limit)
    for item in live:
        st = item.get("state", "")
        ctl = control.get(_task_id(item.get("target", "")))
        if ctl and ctl.get("state") in ("paused", "cancelled"):
            st = ctl["state"]
        if state and st != state:
            continue
        tasks.append({
            "id": _task_id(item.get("target", "")),
            "source": "live",
            "state": st,
            "drive": item.get("drive", ""),
            "drive_name": item.get("drive_name", ""),
            "engine": item.get("engine", ""),
            "tier": item.get("tier", ""),
            "url": item.get("url", ""),
            "target": item.get("target", ""),
            "current_step": item.get("current_step", ""),
            "speed_kbps": item.get("speed_kbps"),
            "avg_speed_kbps": item.get("avg_speed_kbps"),
            "bytes_done": item.get("bytes_done", 0),
            "started": item.get("started", ""),
            "updated": item.get("updated", "") or item.get("mtime", ""),
            "finished": item.get("updated", "") if st in ("done", "failed", "cancelled") else "",
            "elapsed": item.get("elapsed", 0),
            "ok": st not in ("failed", "cancelled"),
        })
    # 历史报告（不在 live 里重复/或已结束的兜底）
    seen = {t["target"] for t in tasks}
    reports = serve_reports_json(reports_dir, limit=limit)
    for r in reports:
        if r.get("target") in seen:
            continue
        st = "done" if r.get("ok") else "failed"
        if state and st != state:
            continue
        tasks.append({
            "id": _task_id(r.get("target", "")),
            "source": "report",
            "state": st,
            "drive": r.get("drive", ""),
            "drive_name": "",
            "engine": r.get("engine", ""),
            "tier": "",
            "url": "",
            "target": r.get("target", ""),
            "current_step": "",
            "speed_kbps": None,
            "avg_speed_kbps": None,
            "bytes_done": 0,
            "started": "",
            "updated": r.get("finished", ""),
            "finished": r.get("finished", ""),
            "elapsed": r.get("elapsed", 0),
            "ok": bool(r.get("ok")),
        })
    # 任务控制记录兜底（paused/cancelled/done/failed 等不在 live/报告中的）
    seen = {t["target"] for t in tasks}
    for tid, rec in sorted(control.items(), key=lambda kv: str(kv[1].get("updated") or ""), reverse=True):
        if rec.get("target") in seen:
            continue
        st = rec.get("state") or "running"
        if state and st != state:
            continue
        tasks.append({
            "id": tid,
            "source": "task",
            "state": st,
            "drive": rec.get("drive", ""),
            "drive_name": rec.get("drive_name", ""),
            "engine": rec.get("engine", ""),
            "tier": rec.get("tier", ""),
            "url": rec.get("url", ""),
            "target": rec.get("target", ""),
            "current_step": rec.get("current_step", ""),
            "speed_kbps": None,
            "avg_speed_kbps": None,
            "bytes_done": 0,
            "started": rec.get("started", ""),
            "updated": rec.get("updated", ""),
            "finished": rec.get("finished", ""),
            "elapsed": 0,
            "ok": st not in ("failed", "cancelled"),
        })
    # 去掉内部用路径字段后返回
    for t in tasks:
        t.pop("_control_path", None)
    # 去语气归一：live 优先，报告/控制记录排后
    tasks.sort(key=lambda t: (t.get("updated") or ""), reverse=True)
    return tasks[:limit]


def _spawn_retry_task(rec):
    """按任务控制记录里的参数重新拉起一个 get 子进程；返回 (pid, 错误)。"""
    url = rec.get("url", "")
    if not url:
        return "", "任务记录缺少 url，无法重试"
    args = rec.get("args") or {}
    argv = [sys.executable, str(Path(__file__).resolve()), "get", url,
            "--to", str(args.get("to") or ""), "--engine", str(args.get("engine") or ""),
            "--tier", str(args.get("tier") or "")]
    if args.get("path"):
        argv += ["--path", str(args["path"])]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as exc:
        return "", "启动重试失败：%s" % exc
    return str(proc.pid), ""


def serve_task_controls(reports_dir, limit=200):
    """递归收集 reports_dir 下所有任务控制记录（按 target 去重）。"""
    base = Path(reports_dir)
    out = {}
    if base.exists():
        for f in sorted(base.glob("**/" + TASK_FILE_NAME), key=lambda p: p.stat().st_mtime, reverse=True):
            recs = read_task_records(f)
            for k, v in recs.items():
                out.setdefault(k, dict(v))
                out[k]["_control_path"] = str(f)
            if len(out) >= limit:
                break
    return out


def _locate_task_control(reports_dir, task_id):
    base = Path(reports_dir)
    if not base.exists():
        return None, {}
    for f in base.glob("**/" + TASK_FILE_NAME):
        recs = read_task_records(f)
        if task_id in recs:
            return f, recs[task_id]
    return None, {}


def _apply_task_action(reports_dir, task_id, action):
    """对任务控制记录执行 pause/resume/delete/retry；返回 (ok, message)。"""
    path, rec = _locate_task_control(reports_dir, task_id)
    if not path or not rec:
        return False, "未找到任务 %s" % task_id
    if "_control_path" in rec:
        rec.pop("_control_path", None)
    recs = read_task_records(path)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    if action == "pause":
        if rec.get("state") != "running":
            return False, "只有运行中的任务可以暂停（当前：%s）" % rec.get("state")
        rec["state"] = "paused"
    elif action == "resume":
        if rec.get("state") != "paused":
            return False, "只有已暂停的任务可以继续（当前：%s）" % rec.get("state")
        rec["state"] = "running"
    elif action == "delete":
        if rec.get("state") == "running":
            rec["state"] = "cancelled"
            rec["updated"] = now
            rec["finished"] = rec.get("finished") or now
            _atomic_write_json(path, {"schema": 1, "tasks": recs})
            return True, "已发送取消并删除标记"
        recs.pop(task_id, None)
        _atomic_write_json(path, {"schema": 1, "tasks": recs})
        return True, "已删除任务记录"
    elif action == "retry":
        if rec.get("state") not in ("done", "failed", "cancelled"):
            return False, "仅已结束（done/failed/cancelled）任务可重试"
        pid, err = _spawn_retry_task(rec)
        if err:
            return False, err
        new_rec = dict(rec)
        new_rec["state"] = "running"
        new_rec["pid"] = pid
        new_rec["started"] = now
        new_rec["updated"] = now
        new_rec["finished"] = ""
        new_rec["rc"] = None
        recs[task_id] = new_rec
        _atomic_write_json(path, {"schema": 1, "tasks": recs})
        return True, "已重新启动下载（新 PID %s）；若原链接需要提取码，请用 `pan task show %s` 查看后补充 --pwd" % (pid, task_id)
    rec["updated"] = now
    recs[task_id] = rec
    _atomic_write_json(path, {"schema": 1, "tasks": recs})
    return True, "任务已%s" % action


def _spawn_download_task(url, pwd="", to="", engine="", tier="", path=""):
    """后台启动 pan get --live；返回 (pid, 错误)。供浏览器扩展 POST /api/download 调用。"""
    if not url or not url.strip():
        return "", "url 为空"
    argv = [sys.executable, str(Path(__file__).resolve()), "get", url.strip(), "--live"]
    if pwd:
        argv += ["--pwd", pwd]
    if to:
        argv += ["--to", to]
    if engine:
        argv += ["--engine", engine]
    if tier:
        argv += ["--tier", tier]
    if path:
        argv += ["--path", path]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as exc:
        return "", "启动下载失败：%s" % exc
    return str(proc.pid), ""


def serve_live_page_html(content, items_json="[]"):
    """渲染实时速度页 HTML（与任务中心同款深色风格），items_json 供前端画速度曲线。"""
    return ("""<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"""
            """<meta name=viewport content="width=device-width,initial-scale=1">"""
            """<meta http-equiv=refresh content=2><title>多网盘实时速度</title>"""
            """<link rel="manifest" href="/manifest.webmanifest">"""
            """<script>if('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js')}</script>"""
            """<style>
:root{--bg:#0f172a;--panel:#1e293b;--line:#334155;--text:#e2e8f0;--muted:#94a3b8;--acc:#38bdf8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 18px 40px}
header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:16px}
header h1{font-size:20px;margin:0}
.nav a{color:var(--acc);text-decoration:none;font-size:13px;margin-left:12px}
.nav a:hover{text-decoration:underline}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
table{width:100%%;border-collapse:collapse;font-size:13px}
thead th{background:#0b1120;color:var(--muted);text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody td{padding:10px 14px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.speed{color:#facc15;font-weight:600}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600}
.badge.running{background:#f59e0b;color:#1a1206}
.badge.done{background:#22c55e;color:#052e16}
.badge.failed{background:#ef4444;color:#fff}
.badge.paused{background:#64748b;color:#f1f5f9}
.empty{background:var(--panel);border:1px solid var(--line);border-radius:12px;color:var(--muted);text-align:center;padding:40px;font-size:15px;line-height:1.8}
.empty span{font-size:12px}
#charts{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin:16px 0 4px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.card h4{margin:0 0 8px;font-size:14px}
.card canvas{width:100%%;height:140px;display:block}
.card .meta{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.6}
</style></head><body><div class=wrap>
<header><h1>⚡ 多网盘实时速度</h1><div class=nav>
<a href=/guide>使用教程</a><a href=/>任务中心</a><a href=/api/live>API 实时</a><a href=/api/status>API 状态</a>
</div></header>
<div class=panel><table>%(content)s</table><div id="CURVE_DATA" style="display:none">%(items_json)s</div></div>
<script>
(() => {
  const wrap = document.getElementById('charts');
  if (!wrap) return;
  let data = [];
  const el = document.getElementById('CURVE_DATA');
  try { data = JSON.parse(el ? el.textContent : '[]'); } catch (e) { data = []; }
  data.forEach((d, i) => {
    const his = d.history || [];
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = '<h4>' + d.name + '</h4><canvas width="600" height="140"></canvas><div class="meta">当前 ' + d.speed + ' KB/s · 平均 ' + d.avg + ' KB/s<br>已下载 ' + d.done + ' · 剩余 ' + d.eta + (d.percent != null ? ' · ' + d.percent + '%%' : '') + '</div>';
    wrap.appendChild(div);
    const cv = div.querySelector('canvas');
    const ctx = cv.getContext('2d');
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.strokeStyle = '#475569'; ctx.lineWidth = 1;
    for (let gx = 0; gx <= 4; gx++) {
      const x = gx * cv.width / 4;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, cv.height); ctx.stroke();
    }
    if (!his.length) return;
    let m = 0;
    his.forEach(pp => { m = Math.max(m, pp[1] || 0); });
    const top = Math.max(1, Math.ceil(m * 1.1 / 10) * 10);
    const grad = ctx.createLinearGradient(0, 0, 0, cv.height);
    grad.addColorStop(0, 'rgba(56,189,248,0.35)'); grad.addColorStop(1, 'rgba(56,189,248,0.02)');
    ctx.beginPath();
    his.forEach((pp, j) => {
      const x = cv.width * j / Math.max(1, his.length - 1);
      const y = cv.height - (cv.height - 16) * (pp[1] / top) - 8;
      if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2; ctx.stroke();
    ctx.lineTo(cv.width, cv.height); ctx.lineTo(0, cv.height); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.fillStyle = '#94a3b8'; ctx.font = '11px sans-serif';
    ctx.fillText('峰值 ' + (m.toFixed ? m.toFixed(1) : m) + ' KB/s', 8, cv.height - 8);
  });
})();
</script>
</div></body></html>""" % {"content": content, "items_json": items_json})


def serve_guide_html():
    """内置「使用教程」页：新手打开网页即可看到完整操作说明。"""
    return """<!doctype html><html lang=zh-CN><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>网盘通 · 使用教程</title>
<link rel="manifest" href="/manifest.webmanifest">
<script>if('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js')}</script>
<style>
:root{--bg:#0f172a;--panel:#1e293b;--line:#334155;--text:#e2e8f0;--muted:#94a3b8;--acc:#38bdf8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:24px 18px 40px}
header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:16px}
header h1{font-size:20px;margin:0}
.nav a{color:var(--acc);text-decoration:none;font-size:13px;margin-left:12px}
.nav a:hover{text-decoration:underline}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px;line-height:1.8}
.card h3{margin:0 0 8px;font-size:15px}
.step{display:flex;gap:10px;align-items:flex-start;margin:7px 0}
.num{flex:0 0 22px;height:22px;border-radius:999px;background:var(--acc);color:#052e16;font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center}
code{background:#0b1120;border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:12px}
a{color:var(--acc)}
.ok{color:#4ade80}.warn{color:#fbbf24}.tip{color:var(--muted);font-size:13px}
</style></head><body><div class=wrap>
<header><h1>📖 网盘通 · 使用教程</h1><div class=nav>
<a href=/>任务中心</a><a href=/test>测试连接</a><a href=/live>实时速度</a>
</div></header>

<div class=card><h3>3 秒学会：复制链接 → 粘贴 → 开始 → 看实时速度</h3>
<div class="step"><span class=num>1</span><div>复制你想下载的网盘分享链接（可带提取码）。</div></div>
<div class="step"><span class=num>2</span><div>回到 <a href=/>任务中心</a>，把链接粘贴到「粘贴链接开始下载」输入框。</div></div>
<div class="step"><span class=num>3</span><div>提取码可不填；目标目录可不填（默认 <code>下载 / Downloads/网盘下载</code>）。</div></div>
<div class="step"><span class=num>4</span><div>点「开始下载」，网页自动识别网盘类型并开始下载。</div></div>
<div class="step"><span class=num>5</span><div>打开 <a href=/live>实时速度</a> 页，可看当前速度、平均速度、已下载大小、剩余时间和速度曲线。</div></div>
</div>

<div class=card><h3>第一次用，先测一下</h3>
<div class="step"><span class=num>1</span><div>打开 <a href=/test>测试连接</a> 页。</div></div>
<div class="step"><span class=num>2</span><div>粘贴网盘链接（提取码留空也可以）。</div></div>
<div class="step"><span class=num>3</span><div>点「开始测试」，几秒内会告诉你这个网盘能不能连、缺什么。</div></div>
<p class=tip>测试只做本地检查，不会真下载，也不会向你选择的网盘发请求。</p>
</div>

<div class=card><h3>常见问题</h3>
<p><b>「提示登录过期」怎么办？</b> 部分网盘首次要官方扫码或网页登录一次，这是官方要求，工具不会绕过。</p>
<p><b>下载会更快吗？</b> 免费档按网盘官方限速执行，不能承诺更快；会员走本机并发调度。</p>
<p><b>密码安全吗？</b> 账号/Cookie/OAuth 凭据只存系统钥匙串，不存明文、不进聊天记录、不上传云端。</p>
<p><b>下载到哪了？</b> 默认 <code>下载 / Downloads/网盘下载</code>；可在「目标目录」填写 NAS、U盘等路径。</p>
<p><b>卡在某个网盘不会用？</b> 先用「测试连接」，再按它的建议补配置即可。</p>
</div>
</div></body></html>"""


def pwa_manifest_json():
    """Web 应用清单：让任务中心可被 Chrome/Safari 安装为独立窗口 PWA。"""
    m = {
        "name": "多网盘任务中心",
        "short_name": "pan 任务中心",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "lang": "zh-CN",
        "icons": [
            {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ]
    }
    return json.dumps(m, ensure_ascii=False)


def pwa_service_worker_js():
    """离线优先外壳：只缓存首页与实时速度页，读取时仍从服务器取最新数据。"""
    return ("""const CACHE = 'pan-pwa-v1';
const PAGES = ['/', '/live', '/test', '/guide'];
self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PAGES)));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', (e) => {
  e.respondWith(
    fetch(e.request).then((res) => {
      const clone = res.clone();
      if (e.request.method === 'GET') {
        caches.open(CACHE).then((c) => c.put(e.request, clone));
      }
      return res;
    }).catch(() => caches.match(e.request).then((hit) => hit || Response.error()))
  );
});
""")


def pwa_icon_png(size):
    """生成本地 PWA 图标 PNG（无需外部文件，尺寸 192/512）。"""
    import struct as _struct
    import zlib as _zlib

    def _chunk(t, d):
        c = _struct.pack('>I', len(d)) + t + d
        return c + _struct.pack('>I', _zlib.crc32(t + d) & 0xffffffff)

    w = h = size
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            dx = min(x, w - 1 - x); dy = min(y, h - 1 - y)
            r = int(size * 0.12)
            if dx < r and dy < r and ((r - dx) ** 2 + (r - dy) ** 2 > r * r):
                a = 0
            else:
                a = 255
            cy = y
            in_arrow = (0.45 * w <= x <= 0.55 * w and 0.30 * h <= cy <= 0.62 * h) or                        (0.42 * h <= cy <= 0.58 * h and 0.25 * w <= x <= 0.75 * w) or                        (cy >= 0.55 * h and cy <= int(0.62 * h) + (int(0.50 * w) - x))
            if in_arrow:
                c = (255, 255, 255, a)
            else:
                c = (40, 110, 210, a)
            row += bytes(c)
        rows.append(bytes(row))
    raw = b''.join(rows)
    ihdr = _chunk(b'IHDR', _struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    return b'\x89PNG\r\n\x1a\n' + ihdr + _chunk(b'IDAT', _zlib.compress(raw)) + _chunk(b'IEND', b'')



def _human_error(text):
    """把常见失败转成人话；原始错误保留在 detail。"""
    raw = str(text or "")
    low = raw.lower()
    rules = [
        ("could not resolve host", "域名解析失败：可能是 NAS 容器 DNS 或外网不可用。"),
        ("connection refused", "连接被拒绝：目标服务/端口没有开启，或地址端口写错。"),
        ("timeout", "连接超时：网络慢、目标站点无响应或被防火墙拦截。"),
        ("no space left on device", "NAS/目标盘空间不足，请清理或换目录。"),
        ("authorization", "没有访问权限：先在 AList/网盘官方授权，或检查凭据。"),
        ("forbidden", "目标拒绝访问：链接可能已失效，或站点限制下载。"),
        ("password", "缺少或提取码错误，请重新输入。"),
        ("engine", "下载引擎未安装或未配置，先到快速诊断处理。"),
    ]
    for key, msg in rules:
        if key in low:
            return msg + "（原始信息：%s）" % (raw[:180] or "-")
    return raw or "未知错误。"


def diagnostics_payload():
    """Web 快速诊断：只读检测，不做绕过。"""
    import shutil as _sh
    import socket as _socket
    cfg = load_config()
    checks = []
    for name in ("curl", "aria2", "rclone"):
        binpath = find_engine_binary(name, cfg)
        checks.append({"name": name, "ok": bool(binpath), "detail": binpath or "未安装"})
    alist = ((cfg.get("engines") or {}).get("alist_url") or "").strip()
    checks.append({"name": "AList", "ok": bool(alist), "detail": alist or "未配置"})
    root = default_root(cfg)
    root_path = Path(root)
    if not root_path.exists() and Path("/data/download").exists():
        root_path = Path("/data/download")
    try:
        usage = _sh.disk_usage(root_path)
        free_gb = usage.free / 1024 ** 3
        checks.append({"name": "磁盘空间", "ok": free_gb >= 1, "detail": "%.1f GB 可用 / %s" % (free_gb, root_path)})
    except Exception as exc:
        checks.append({"name": "磁盘空间", "ok": False, "detail": _human_error(exc)})
    try:
        _socket.setdefaulttimeout(2.5)
        _socket.gethostbyname("www.baidu.com")
        checks.append({"name": "外网 DNS", "ok": True, "detail": "域名解析正常"})
    except Exception as exc:
        checks.append({"name": "外网 DNS", "ok": False, "detail": _human_error(exc)})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def runtime_payload():
    """通用运行时信息：所有 UI/Agent/插件都不再依赖固定主机或目录。"""
    cfg = load_config()
    dep = cfg.get("deployment") or {}
    port = int(dep.get("web_port") or 17890)
    mode = dep.get("mode") or ("docker" if (os.environ.get("PAN_CONFIG") or Path("/.dockerenv").exists()) else "local")
    root = str(default_root(cfg))
    dirs = dep.get("download_dirs")
    if not isinstance(dirs, dict) or not dirs:
        dirs = {"默认": root, "电影": str(Path(root) / "电影"), "音乐": str(Path(root) / "音乐"),
                "资料": str(Path(root) / "资料"), "临时": "/tmp"}
    return {
        "ok": True,
        "mode": mode,
        "mode_name": {"local": "本机", "nas_docker": "NAS Docker", "server_docker": "服务器 Docker", "docker": "Docker 容器"}.get(mode, mode),
        "web_host": dep.get("web_host") or "",
        "web_port": port,
        "api_url": dep.get("api_url") or "http://127.0.0.1:%d" % port,
        "download_root": root,
        "download_dirs": dirs,
        "services": {
            "alist": (cfg.get("engines") or {}).get("alist_url") or "",
            "rclone": (cfg.get("engines") or {}).get("rclone_remote") or "",
            "aria2": (cfg.get("engines") or {}).get("aria2_url") or "",
        },
    }


def recent_log_lines(limit=50):
    """读取最近关键日志；无权限或无文件时返回提示。"""
    p = Path(os.environ.get("PAN_LOG") or (SKILL_DIR / "pan.log"))
    if not p.exists():
        return ["暂无日志文件：%s" % p]
    try:
        return [x for x in p.read_text(errors="replace").splitlines()[-limit:]]
    except OSError as exc:
        return [_human_error(exc)]


def serve_settings_html():
    return """<!doctype html><html lang=zh-CN><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>网盘通 · 设置</title>
<style>:root{--bg:#0b1120;--panel:#111827;--line:#243244;--text:#e5edf8;--muted:#94a3b8;--acc:#38bdf8}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,PingFang SC,system-ui,sans-serif}.w{max-width:820px;margin:auto;padding:20px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}input,select{width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);background:#020617;color:var(--text);margin-bottom:10px}button{width:100%;border:0;border-radius:8px;background:var(--acc);color:#06283d;font-weight:700;padding:11px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:640px){.grid{grid-template-columns:1fr}}a{color:var(--acc);text-decoration:none}.msg{margin-top:8px;color:var(--muted)}</style></head><body><div class=w>
<h1>设置</h1><p><a href="/">← 返回控制台</a></p>
<div class=panel><label>AList 地址</label><input id=alist placeholder="http://127.0.0.1:5244"><label>rclone 远端</label><input id=remote placeholder="alist:"><label>默认下载目录</label><input id=root placeholder="/data/download"><div class=grid><label>并发数</label><input id=conn type=number min=1 max=16 value=4><label>通知钩子</label><input id=hook placeholder="可留空"></div><button id=save>保存设置</button><div class=msg id=msg></div></div>
<script>fetch('/api/settings').then(r=>r.json()).then(d=>{const c=d.config||{};const e=c.engines||{};alist.value=e.alist_url||'';remote.value=e.rclone_remote||'';root.value=c.download_root||'';conn.value=(c.http||{}).max_connections_vip||4;hook.value=(c.http||{}).on_complete_hook||''});save.onclick=async()=>{save.disabled=1;msg.textContent='保存中…';try{const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alist_url:alist.value,rclone_remote:remote.value,download_root:root.value,max_connections:Number(conn.value)||4,on_complete_hook:hook.value})});const j=await r.json();msg.textContent=j.ok?'✅ 已保存':'❌ '+(j.error||'失败')}catch(e){msg.textContent='❌ '+e}save.disabled=0};</script></div></body></html>"""


def serve_logs_html():
    rows = "".join("<div class=log>%s</div>" % x.replace("&", "&amp;").replace("<", "&lt;") for x in recent_log_lines(50))
    return """<!doctype html><html lang=zh-CN><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>网盘通 · 日志</title><style>body{background:#0b1120;color:#e5edf8;font-family:ui-monospace,Menlo,monospace;margin:0;padding:20px}a{color:#38bdf8;text-decoration:none}.box{background:#020617;border:1px solid #243244;border-radius:10px;padding:12px;white-space:pre-wrap;overflow:auto;max-height:80vh}.log{padding:3px 0;border-bottom:1px solid #16212f;font-size:12px}</style></head><body><h1>最近日志</h1><p><a href="/">← 返回控制台</a></p><div class=box>%s</div></body></html>""" % (rows or "<div class=log>暂无日志</div>")


def serve_home_html(tasks):
    """一体化下载控制台。"""
    def fmt_speed(v):
        return "%.1f KB/s" % float(v) if v not in (None, "") else "-"
    def fmt_size(n):
        n = float(n or 0)
        return ("%.1f MB" % (n / 1048576)) if n >= 1048576 else ("%.1f KB" % (n / 1024)) if n else "-"
    def fmt_eta(v):
        try:
            v = float(v)
            return "即将完成" if v <= 0 else ("%d分%02d秒" % (v // 60, v % 60)) if v < 3600 else ("%d时%02d分" % (v // 3600, (v % 3600) // 60))
        except Exception:
            return "-"
    cards = "".join("""<article class="task %s"><div class=top><span class=state>%s</span><span>%s</span></div>
<div class=name>%s</div><div class=meta>%s · %s · %s</div>
<div class=bar><i style="width:%s%%"></i></div>
<div class=stats><span>%s</span><span>%s</span><span>%s</span></div>
<div class=ops>%s</div></article>""" % (
        t.get("state") or "unknown", t.get("state") or "unknown", t.get("id"), t.get("current_step") or t.get("target") or t.get("url") or "未命名任务",
        t.get("drive_name") or t.get("drive") or "直链", t.get("engine") or "-", t.get("updated") or "-",
        max(0, min(100, int(t.get("percent") or 0))), fmt_speed(t.get("speed_kbps")), fmt_size(t.get("bytes_done")), fmt_eta(t.get("eta_seconds")),
        ('<a href="/api/task/action?task=%s&action=pause">暂停</a><a href="/api/task/action?task=%s&action=delete">删除</a>' % (t["id"], t["id"])) if t.get("state") == "running"
        else ('<a href="/api/task/action?task=%s&action=resume">继续</a><a href="/api/task/action?task=%s&action=delete">删除</a>' % (t["id"], t["id"])) if t.get("state") == "paused"
        else ('<a href="/api/task/action?task=%s&action=retry">重试</a><a href="/api/task/action?task=%s&action=delete">删除</a>' % (t["id"], t["id"])))
        for t in tasks[:60]) or '<div class=empty>暂无任务。粘贴链接后点击开始下载。</div>'
    dir_options = '<option value="">默认目录</option>' + "".join('<option value="%s">%s</option>' % (v, k) for k, v in runtime_payload().get("download_dirs", {}).items())
    return """<!doctype html><html lang=zh-CN><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>网盘通控制台</title>
<link rel="manifest" href="/manifest.webmanifest"><script>if('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js')}</script>
<style>:root{--bg:#07111f;--panel:#0f172a;--line:#22314a;--text:#e5edf8;--muted:#94a3b8;--acc:#38bdf8}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,PingFang SC,system-ui,sans-serif}.w{max-width:1180px;margin:auto;padding:20px}header{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}nav a{color:var(--acc);text-decoration:none;margin-right:12px;font-size:13px}.grid{display:grid;grid-template-columns:1.3fr .7fr;gap:14px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px}label{font-size:12px;color:var(--muted);display:block;margin-bottom:4px}textarea,input,select{width:100%;background:#020617;border:1px solid var(--line);color:var(--text);border-radius:9px;padding:9px;margin-bottom:8px}button{border:0;border-radius:9px;background:var(--acc);color:#06283d;font-weight:700;padding:10px;width:100%}.tasks{display:grid;gap:10px}.task{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px}.top,.stats,.ops{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted)}.state{text-transform:uppercase}.name{font-size:14px;margin:5px 0;word-break:break-all}.bar{height:8px;background:#1e293b;border-radius:99px;overflow:hidden}.bar i{display:block;height:100%;background:var(--acc)}.ops a{color:var(--acc);text-decoration:none}.diag div{display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid var(--line)}.ok{color:#4ade80}.bad{color:#f87171}.empty{color:var(--muted);font-size:13px}.theme{position:fixed;right:14px;bottom:14px;border-radius:99px;width:38px;height:38px;padding:0}@media(max-width:820px){.grid{grid-template-columns:1fr}}</style></head><body><div class=w>
<header><h1>⏬ 网盘通控制台 <small id=runtimeInfo class=empty>读取中…</small></h1><nav><a href=/guide>教程</a><a href=/live>速度</a><a href=/test>测试</a><a href=/settings>设置</a><a href=/logs>日志</a><a href=/api/diagnostics>诊断API</a></nav></header>
<div class=grid><section class=panel><h2>批量下载</h2><textarea id=url rows=4 placeholder="每行一个 HTTP/HTTPS/AList/官方工具支持的链接"></textarea><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div><label>提取码</label><input id=pwd></div><div><label>下载目录</label><select id=to><option value="">默认目录</option>__DIR_OPTIONS__</select></div><div><label>引擎</label><select id=engine><option value="">自动</option><option value=curl>curl</option><option value=aria2>aria2</option><option value=alist>AList/rclone</option><option value=ytdlp>yt-dlp</option></select></div><div><label>优先级</label><select id=tier><option value="">自动</option><option value=free>普通</option><option value=vip>高优先</option></select></div></div><button id=start>开始下载</button><div id=msg class=empty style="margin-top:8px">支持多行，每行一个链接。</div></section>
<section class=panel><h2>快速诊断</h2><div id=diag class=diag><div class=empty>检测中…</div></div><button id=refresh style="margin-top:10px">重新诊断</button></section></div>
<section class=panel style="margin-top:14px"><h2>任务中心</h2><div class=tasks>__CARDS__</div></section>
<button class=theme onclick="document.documentElement.style.filter=document.documentElement.style.filter?'':'invert(1) hue-rotate(180deg)'">🌗</button>
<script>
function render(){fetch('/api/tasks').then(r=>r.json()).then(d=>location.reload()).catch(()=>{})}
async function diag(){const d=document.getElementById('diag');d.innerHTML='<div class=empty>检测中…</div>';try{const j=await (await fetch('/api/diagnostics')).json();d.innerHTML=j.checks.map(x=>'<div><span>'+x.name+'</span><span class="'+(x.ok?'ok':'bad')+'">'+(x.ok?'✅ ':'❌ ')+x.detail+'</span></div>').join('')}catch(e){d.innerHTML='<div class=bad>诊断失败</div>'}}
document.getElementById('start').onclick=async()=>{const urls=(url.value||'').split(/\\s+/).filter(x=>/^https?:\\/\\//i.test(x));if(!urls.length){msg.textContent='请先粘贴至少一个链接';return}msg.textContent='正在投递 '+urls.length+' 个任务…';try{const r=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({urls,pwd:pwd.value,to:to.value,engine:engine.value,tier:tier.value})});const j=await r.json();msg.textContent=(j.ok?'✅ ':'❌ ')+(j.message||j.error||'');if(j.ok)setTimeout(render,700)}catch(e){msg.textContent='❌ '+e}};refresh.onclick=diag;diag();fetch('/api/runtime').then(r=>r.json()).then(r=>{runtimeInfo.textContent='运行模式：'+(r.mode_name||r.mode)+' · API：'+r.api_url+' · 目录：'+r.download_root;to.innerHTML='<option value="">默认目录</option>'+Object.entries(r.download_dirs||{}).map(([k,v])=>`<option value="${v}">${k}</option>`).join('')}).catch(()=>{runtimeInfo.textContent='运行模式：未知 · 请先运行 pan setup --mode local'});
</script></div></body></html>""".replace("__CARDS__", cards).replace("__DIR_OPTIONS__", dir_options)


def serve_test_html():
    """独立「测试连接」页：粘贴链接→调用 /api/test→人话结果（不自动刷新，避免打断输入）。"""
    return """<!doctype html><html lang=zh-CN><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>多网盘 · 测试连接</title>
<link rel="manifest" href="/manifest.webmanifest">
<script>if('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js')}</script>
<style>
:root{--bg:#0f172a;--panel:#1e293b;--line:#334155;--text:#e2e8f0;--muted:#94a3b8;--acc:#38bdf8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:24px 18px 40px}
header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:18px}
header h1{font-size:20px;margin:0}
.nav a{color:var(--acc);text-decoration:none;font-size:13px;margin-left:12px}
.nav a:hover{text-decoration:underline}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}
form{display:grid;gap:10px;margin-bottom:6px}
input{background:#0b1120;border:1px solid var(--line);border-radius:8px;color:var(--text);padding:10px 12px;font-size:14px}
button{border:0;border-radius:8px;background:var(--acc);color:#052e16;font-size:14px;font-weight:600;padding:11px;cursor:pointer}
button:hover{opacity:.9}
.row{display:flex;justify-content:space-between;gap:12px;padding:9px 2px;border-bottom:1px solid var(--line);font-size:13px}
.row:last-child{border-bottom:none}
.row .name{white-space:nowrap}
.row .detail{color:var(--muted);text-align:right;word-break:break-all}
.ok{color:#4ade80}.bad{color:#f87171}
.sum{font-size:16px;font-weight:700;padding:10px 2px}
.empty{color:var(--muted);font-size:13px;padding:8px 2px}
</style></head><body><div class=wrap>
<header><h1>🧪 多网盘 · 测试连接</h1><div class=nav>
<a href=/guide>使用教程</a><a href=/>任务中心</a><a href=/live>实时速度</a>
</div></header>
<div class=panel>
<form id=testForm>
<input id=testUrl type=text placeholder="粘贴网盘分享链接或 HTTP 直链" required>
<input id=testPwd type=text placeholder="提取码（没有可留空）" autocomplete=off>
<button type=submit>开始测试</button>
</form>
<p style="color:var(--muted);font-size:12px;margin:6px 0 0">只做本地静态检查：识别网盘、依赖与配置、目标目录、提取码提示。不会下载文件、不发请求到网盘页面。</p>
<div id=result></div>
</div>
<script>
document.getElementById('testForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  const url = document.getElementById('testUrl').value.trim();
  if (!url) { return; }
  const pwd = document.getElementById('testPwd').value.trim();
  const out = document.getElementById('result');
  out.innerHTML = '<div class=empty>测试中…</div>';
  try {
    const qs = new URLSearchParams({ url: url });
    if (pwd) { qs.append('pwd', pwd); }
    const resp = await fetch('/api/test?' + qs.toString());
    const j = await resp.json();
    let html = '';
    const marks = [];
    (j.checks || []).forEach(function (c) {
      const mark = c.ok ? '✅' : '❌';
      marks.push(c.ok);
      html += '<div class="row"><span class="name ' + (c.ok ? 'ok' : 'bad') + '">' + mark + ' ' + (c.name || '') + '</span><span class="detail">' + (c.detail || '') + '</span></div>';
    });
    const allOk = marks.length > 0 && marks.every(Boolean);
    html = '<div class="sum ' + (allOk ? 'ok' : 'bad') + '">' + (allOk ? '✅ 可以开始下载' : '❌ 当前还不能直接下载') + '</div>' + html;
    out.innerHTML = html;
  } catch (err) {
    out.innerHTML = '<div class="row"><span class="name bad">❌ 通信失败</span><span class="detail">请确认本机服务已运行：python3 scripts/pan.py serve</span></div>';
  }
});
</script>
</div></body></html>"""





def bookmarklet_js():
    """生成书签栏一键投递脚本（拖到书签栏，在任何网页点一下即可把媒体链接投给本机/NAS pan serve）。"""
    return (
        "javascript:(function(){"
        "var d=document;var u='';"
        "var s=window.getSelection?String(window.getSelection()):'';"
        "if(/^https?:\/\//.test(s)){u=s;}else{"
        "var cands=[];d.querySelectorAll('a[href],video[src],source[src],audio[src]').forEach(function(el){"
        "var h=el.href||el.src||'';if(/^(https?:)?\/\//.test(h)){cands.push(h)}});"
        "if(cands.length){u=cands[0]}else{u=location.href}}"
        "u=prompt('投递到网盘通\n（回车确认，ESC 取消）',u);"
        "if(!u){return}"
        "var api=location.origin.replace(/:\\d+$/',':17890')+'/api/download';"
        "if(location.port==='17890'){api='/api/download'}"
        "fetch(api,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({url:u})}).then(function(r){return r.json()}).then(function(j){"
        "alert(j.ok?('✅ 已投递：'+(j.live_url||j.home_url||'')):('❌ '+(j.error||'失败')))"
        "}).catch(function(e){alert('❌ 连接失败：'+e)})})()"
    )


def cmd_serve(args):
    try:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    except ImportError:
        print("❌ 当前环境无 http.server")
        return 1
    import threading
    reports_dir = os.path.expanduser(args.reports_dir) if args.reports_dir else ""
    if not reports_dir:
        reports_dir = str(Path((load_config().get("http") or {}).get("report_dir") or default_root(load_config())))
    host, port = args.host, int(args.port)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj):
            data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _html(self, text):
            data = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _raw(self, data, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = b""
            if length:
                raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                body = {}
            if self.path.startswith("/api/download"):
                urls = body.get("urls") or ([body.get("url")] if body.get("url") else [])
                if not isinstance(urls, list):
                    urls = [urls]
                urls = [str(x).strip() for x in urls if str(x).strip()]
                if not urls:
                    self._json({"ok": False, "error": "缺少下载链接", "human": "请先粘贴至少一个 HTTP/HTTPS 链接。"})
                    return
                results, errors = [], []
                for url in urls[:100]:
                    pid, err = _spawn_download_task(
                        url, pwd=(body.get("pwd") or ""), to=(body.get("to") or ""),
                        engine=(body.get("engine") or ""), tier=(body.get("tier") or ""),
                        path=(body.get("path") or ""))
                    if err:
                        errors.append({"url": url, "error": err, "human": _human_error(err)})
                    else:
                        results.append({"url": url, "pid": pid})
                self._json({"ok": not errors, "message": "已投递 %d 个任务，失败 %d 个。" % (len(results), len(errors)),
                            "results": results, "errors": errors,
                            "home_url": "http://%s:%d/" % (host, port)})
            elif self.path.startswith("/api/settings"):
                cfg = load_config()
                cfg.setdefault("engines", {})["alist_url"] = str(body.get("alist_url") or "").strip()
                cfg.setdefault("engines", {})["rclone_remote"] = str(body.get("rclone_remote") or "").strip()
                cfg["download_root"] = str(body.get("download_root") or "").strip()
                cfg.setdefault("http", {})["max_connections_vip"] = max(1, min(16, int(body.get("max_connections") or 4)))
                cfg["http"]["on_complete_hook"] = str(body.get("on_complete_hook") or "").strip()
                save_config(cfg)
                self._json({"ok": True, "message": "设置已保存"})
            elif self.path.startswith("/api/task/action"):
                q = dict(parse_qs(self.path.split("?", 1)[1])) if "?" in self.path else {}
                action = (body.get("action") or q.get("action") or [""])
                task = (body.get("task") or q.get("task") or [""])
                action = action[0] if isinstance(action, list) else action
                task = task[0] if isinstance(task, list) else task
                if action not in ("pause", "resume", "delete", "retry"):
                    self._json({"ok": False, "error": "未知操作"})
                elif not task:
                    self._json({"ok": False, "error": "缺少 task"})
                else:
                    ok, msg = _apply_task_action(reports_dir, task, action)
                    self._json({"ok": ok, "action": action, "task": task, "message": msg})
            else:
                self.send_error(404, "Not Found")

        def do_GET(self):
            if self.path in ("/manifest.webmanifest", "/manifest.json"):
                self._raw(pwa_manifest_json().encode("utf-8"), "application/manifest+json; charset=utf-8")
            elif self.path in ("/bookmarklet.js", "/bookmarklet"):
                self._raw(bookmarklet_js().encode("utf-8"), "application/javascript; charset=utf-8")
            elif self.path == "/sw.js":
                self._raw(pwa_service_worker_js().encode("utf-8"), "application/javascript; charset=utf-8")
            elif self.path.startswith("/icons/icon-") and self.path.endswith(".png"):
                size = int("".join(ch for ch in self.path.split("-")[-1].split(".")[0] if ch.isdigit()) or 192)
                self._raw(pwa_icon_png(size), "image/png")
            elif self.path.startswith("/api/runtime"):
                self._json(runtime_payload())
            elif self.path.startswith("/api/diagnostics"):
                self._json(diagnostics_payload())
            elif self.path.startswith("/api/settings"):
                self._json({"ok": True, "config": load_config()})
            elif self.path.startswith("/api/reports"):
                self._json({"reports": serve_reports_json(reports_dir)})
            elif self.path.startswith("/api/test"):
                q = dict(parse_qs(self.path.split("?", 1)[1])) if "?" in self.path else {}
                url = (q.get("url") or [""])[0]
                if not url:
                    self._json({"ok": False, "error": "缺少 url 参数"})
                else:
                    rel = _probe_link_checks(load_config(), url,
                                             pwd=(q.get("pwd") or [""])[0],
                                             engine=(q.get("engine") or [""])[0],
                                             tier=(q.get("tier") or [""])[0],
                                             path=(q.get("path") or [""])[0])
                    self._json(rel)
            elif self.path.startswith("/api/tasks"):
                st = ""
                for part in self.path.split("?")[-1].split("&"):
                    if part.startswith("state="):
                        st = part.split("=", 1)[1]
                self._json({"tasks": serve_unified_tasks(reports_dir, limit=100, state=st or None)})
            elif self.path.startswith("/api/status"):
                self._json({"ok": True, "reports_dir": reports_dir,
                            "reports": len(serve_reports_json(reports_dir)),
                            "live": len(serve_live_json(reports_dir)),
                            "tasks": len(serve_unified_tasks(reports_dir))})
            elif self.path.startswith("/api/live"):
                self._json({"live": serve_live_json(reports_dir)})
            elif self.path.startswith("/api/task/action"):
                q = dict(parse_qs(self.path.split("?", 1)[1])) if "?" in self.path else {}
                action = (q.get("action") or [""])[0]
                task = (q.get("task") or [""])[0]
                if action not in ("pause", "resume", "delete", "retry"):
                    self._json({"ok": False, "error": "未知操作"})
                elif not task:
                    self._json({"ok": False, "error": "缺少 task 参数"})
                else:
                    ok, msg = _apply_task_action(reports_dir, task, action)
                    self._json({"ok": ok, "action": action, "task": task, "message": msg})
            elif self.path.startswith("/api/tasks") or self.path.startswith("/api/task-json"):
                st = ""
                for part in self.path.split("?")[-1].split("&"):
                    if part.startswith("state="):
                        st = part.split("=", 1)[1]
                self._json({"tasks": serve_unified_tasks(reports_dir, limit=100, state=st or None)})
            elif self.path in ("/live", "/live.html"):
                live = serve_live_json(reports_dir)
                items_json = "[]"
                if not live:
                    body = '<div class="empty">暂无进行中的实时下载<br><span>下载时执行 get --live 生成 下载速度.live.json</span></div>'
                else:
                    shown = []
                    for item in live[:8]:
                        st = item.get("state", "")
                        badge = st if st else "unknown"
                        sp = item.get("speed_kbps")
                        av = item.get("avg_speed_kbps")
                        sps = ("%.1f" % float(sp)) if sp not in (None, "") else "-"
                        avs = ("%.1f" % float(av)) if av not in (None, "") else "-"
                        by = int(item.get("bytes_done") or 0)
                        if by >= 1024 * 1024:
                            btxt = "%.2f MB" % (by / 1048576.0)
                        else:
                            btxt = "%.2f KB" % (by / 1024.0)
                        eta = item.get("eta_seconds")
                        ets = "-"
                        if eta is not None:
                            eta = float(eta)
                            if eta <= 0:
                                ets = "即将完成"
                            elif eta < 60:
                                ets = "约 %d 秒" % int(eta)
                            elif eta < 3600:
                                ets = "约 %d 分 %d 秒" % (int(eta // 60), int(eta % 60))
                            else:
                                ets = "约 %d 小时 %d 分" % (int(eta // 3600), int((eta % 3600) // 60))
                        shown.append({
                            "name": item.get("drive_name", ""), "step": item.get("current_step", ""),
                            "speed": sps, "avg": avs, "done": btxt, "state": badge,
                            "eta": ets, "history": item.get("history", [])[:300],
                            "total": item.get("total_bytes", 0), "percent": item.get("percent"),
                        })
                        rows.append(
                            "<tr><td>%s</td><td>%s</td><td><span class=speed>%s KB/s</span></td>"
                            "<td>%s KB/s</td><td>%s</td><td>%s</td><td><span class='badge %s'>%s</span></td>"
                            "<td class=mono>%s</td></tr>" % (
                                item.get("drive_name", ""), item.get("current_step", ""),
                                sps, avs, btxt, ets, badge, badge, item.get("updated", "")))
                    items_json = json.dumps(shown, ensure_ascii=False)
                    table = ("<thead><tr><th>网盘</th><th>当前文件 / 步骤</th><th>实时速度</th>"
                             "<th>平均速度</th><th>已下载</th><th>剩余时间</th><th>状态</th><th>更新时间</th></tr></thead>"
                             "<tbody>%s</tbody>" % "".join(rows))
                    body = table + '<div id="charts"></div>'
                self._html(serve_live_page_html(body, items_json=items_json))
            elif self.path in ("/test", "/test.html"):
                self._html(serve_test_html())
            elif self.path in ("/settings", "/settings.html"):
                self._html(serve_settings_html())
            elif self.path in ("/logs", "/logs.html"):
                self._html(serve_logs_html())
            elif self.path in ("/guide", "/guide.html"):
                self._html(serve_guide_html())
            elif self.path in ("/", "/index.html"):
                self._html(serve_home_html(serve_unified_tasks(reports_dir)))
            else:
                self.send_error(404, "Not Found")

    try:
        httpd = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print("❌ 启动失败 %s:%s：%s" % (host, port, exc))
        return 1
    print("只读状态页：http://%s:%s/（仅本机访问；不读取任何凭据）" % (host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
