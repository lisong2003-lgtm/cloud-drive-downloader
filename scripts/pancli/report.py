#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pan-downloader — 下载报告 / 实时速度 / 任务控制（LiveMonitor、TaskControl）子模块。"""
from __future__ import annotations

import json
import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

# 共享工具函数从 engine 懒加载（engine 的命令为懒代理，运行期才 import 本模块，避免循环引用）。
from pancli.engine import *  # noqa: F401,F403

def report_path_for_target(cfg, target):
    report_dir = ((cfg.get("http") or {}).get("report_dir") or "").strip()
    base = Path(report_dir).expanduser() if report_dir else Path(target or ".")
    return base / "下载报告.json"


def write_download_report(cfg, plan, results, started, finished, ok, url=""):
    path = report_path_for_target(cfg, plan.get("target", ""))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "schema": 1,
            "ok": bool(ok),
            "url": url,
            "drive": plan.get("drive", ""),
            "drive_name": plan.get("drive_name", ""),
            "engine": plan.get("engine", ""),
            "tier": plan.get("tier", ""),
            "target": plan.get("target", ""),
            "started": started.isoformat() if hasattr(started, "isoformat") else str(started),
            "finished": finished.isoformat() if hasattr(finished, "isoformat") else str(finished),
            "elapsed": round((finished - started).total_seconds(), 2) if hasattr(finished, "timestamp") else 0.0,
            "steps": results,
            "missing": plan.get("missing", []),
            "warnings": plan.get("warnings", []),
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(body, fh, ensure_ascii=False, indent=2)
        return str(path)
    except OSError as exc:
        log_line("REPORT_FAILED %s %s" % (path, exc))
        return ""


def run_completion_hook(cfg, plan, report_path, url=""):
    hook = ((cfg.get("http") or {}).get("on_complete_hook") or "").strip()
    if not hook:
        return ""
    target = plan.get("target", "")
    argv = shlex.split(hook.format(
        target=target, drive=plan.get("drive", ""), engine=plan.get("engine", ""),
        report=report_path or "", url=url, tier=plan.get("tier", ""),
    ))
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        log_line("HOOK exit=%s argv=%s" % (proc.returncode, " ".join(mask_argv(argv))))
        msg = (proc.stdout or "").strip().splitlines()
        return (msg[0][:200] if msg else "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_line("HOOK_FAILED %s %s" % (" ".join(mask_argv(argv)), exc))
        return ""


LIVE_FILE_NAME = "下载速度.live.json"


def live_file_for(cfg, plan, target=None):
    http = cfg.get("http") or {}
    live_dir = (http.get("live_dir") or "").strip()
    if live_dir:
        base = Path(live_dir).expanduser()
    else:
        report_dir = (http.get("report_dir") or "").strip()
        base = Path(report_dir).expanduser() if report_dir else Path(target or plan.get("target") or ".")
    return base / LIVE_FILE_NAME


class LiveMonitor:
    """下载期间周期性采样目标目录字节增量，写入实时速度状态 JSON 文件。"""

    HISTORY_CAP = 300

    def __init__(self, cfg, plan, url="", interval=1.0):
        self.cfg = cfg
        self.plan = plan
        self.url = url or ""
        self.interval = max(0.3, float(interval or 1.0))
        self.target = Path(plan.get("target") or ".")
        self.live_path = live_file_for(cfg, plan)
        self._stop = threading.Event()
        self._thread = None
        self.state = "running"
        self.started = time.time()
        self.last_bytes = 0
        self.last_ts = None
        self.current_step = ""
        self._baseline = self._total_bytes()
        self.total_bytes = 0
        try:
            self.total_bytes = int(plan.get("total_bytes") or 0)
        except (TypeError, ValueError):
            self.total_bytes = 0
        self.history = []  # [(elapsed_seconds, speed_kbps), ...] 画曲线用

    def _total_bytes(self):
        total = 0
        try:
            if self.target.exists():
                for p in self.target.iterdir():
                    if p.is_file() and p.name != LIVE_FILE_NAME:
                        try:
                            total += p.stat().st_size
                        except OSError:
                            pass
        except OSError:
            pass
        return total

    def set_step(self, note=""):
        self.current_step = note or ""

    def set_total_bytes(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return self.total_bytes
        self.total_bytes = max(0, value)
        return self.total_bytes

    def start(self):
        """启动后台线程：按 interval 周期采样并写入实时速度 JSON，直到 stop() 为止。"""
        if self._thread and self._thread.is_alive():
            return self._thread

        def _loop():
            interval = max(0.3, self.interval)
            while not self._stop.is_set():
                try:
                    self.write(state=self.state)
                except Exception as exc:  # 监控线程异常不应中断下载
                    log_line("LIVE_LOOP_ERR %s" % exc)
                self._stop.wait(interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="pan-live-monitor")
        self._thread.start()
        return self._thread

    def _sample(self):
        now = time.time()
        cur = self._total_bytes()
        dt = (now - self.last_ts) if self.last_ts else 0.0
        speed = 0.0
        if dt and dt > 0:
            speed = (cur - self.last_bytes) / dt / 1024.0
        self.last_bytes, self.last_ts = cur, now
        elapsed = max(0.0, now - self.started)
        done = max(0, cur - self._baseline)
        avg = (done / elapsed / 1024.0) if elapsed > 0 else 0.0
        self.history.append((round(elapsed, 2), max(speed, 0.0)))
        if len(self.history) > self.HISTORY_CAP:
            self.history = self.history[-self.HISTORY_CAP:]
        return done, max(speed, 0.0), max(avg, 0.0), elapsed

    def write(self, state=None):
        done, speed, avg, elapsed = self._sample()
        body = {
            "schema": 1,
            "state": state or self.state,
            "url": self.url,
            "drive": self.plan.get("drive", ""),
            "drive_name": self.plan.get("drive_name", ""),
            "engine": self.plan.get("engine", ""),
            "tier": self.plan.get("tier", ""),
            "target": str(self.target),
            "started": datetime.fromtimestamp(self.started).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
            "elapsed": round(elapsed, 2),
            "bytes_done": int(done),
            "speed_kbps": round(speed, 2),
            "avg_speed_kbps": round(avg, 2),
            "total_bytes": int(self.total_bytes or 0),
            "percent": round(done * 100.0 / self.total_bytes, 1) if self.total_bytes and self.total_bytes > 0 else None,
            "eta_seconds": round((self.total_bytes - done) / 1024.0 / avg, 1) if (self.total_bytes and self.total_bytes > 0 and avg and avg > 0) else None,
            "history": [[t, v] for (t, v) in self.history],
            "current_step": self.current_step,
        }
        try:
            self.live_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.live_path.with_suffix(self.live_path.suffix + ".tmp")
            tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.live_path)
        except OSError as exc:
            log_line("LIVE_WRITE_FAIL %s %s" % (self.live_path, exc))
        return body

    def stop(self, ok=True):
        if self._stop.is_set() and self.state not in ("done", "failed"):
            self.state = "running"
        self.state = "done" if ok else "failed"
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval * 3 + 1)
        self.write(state=self.state)


# ------------------------------------------------------------------ 任务控制
# 任务登记在 http.live_dir / http.report_dir / 目标目录 的“任务控制.json”，
# 供 serve 任务中心和 `pan task ...` 实现 暂停/继续/取消/删除/重试。
TASK_FILE_NAME = "任务控制.json"


def _task_file_for_dir(reports_dir):
    return Path(reports_dir) / TASK_FILE_NAME


def read_task_records(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        recs = data.get("tasks")
        return recs if isinstance(recs, dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def _atomic_write_json(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)


def task_control_file_for(cfg, plan, target=None):
    """任务控制文件与实时速度文件同目录，便于任务中心集中管理。"""
    return live_file_for(cfg, plan, target=target).with_name(TASK_FILE_NAME)


def _task_id(target):
    import hashlib
    return hashlib.sha1(str(target).encode("utf-8")).hexdigest()[:12]


class TaskControl:
    """任务状态机：running / paused / cancelled / done / failed，落盘到任务控制.json。"""

    def __init__(self, cfg, plan, url="", args=None):
        self.cfg = cfg
        self.plan = plan
        self.url = url or ""
        self.args = dict(args or {})
        self.target = plan.get("target") or "."
        self.path = task_control_file_for(cfg, plan)
        self.task_id = _task_id(self.target)
        self._lock = threading.Lock()

    def register(self):
        rec = self._rec()
        rec["state"] = "running"
        self._mutate(lambda recs: recs.update({self.task_id: rec}) or recs)
        return rec

    def _rec(self):
        return {
            "id": self.task_id,
            "schema": 1,
            "state": "running",
            "url": self.url,
            "drive": self.plan.get("drive", ""),
            "drive_name": self.plan.get("drive_name", ""),
            "engine": self.plan.get("engine", ""),
            "tier": self.plan.get("tier", ""),
            "target": str(self.target),
            "pwd_present": bool(self.args.get("pwd")),
            "args": {k: v for k, v in self.args.items() if k != "pwd"},
            "pid": os.getpid(),
            "started": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
            "current_step": "",
            "finished": "",
            "rc": None,
        }

    def _mutate(self, fn):
        with self._lock:
            recs = read_task_records(self.path)
            recs = fn(recs) or recs
            _atomic_write_json(self.path, {"schema": 1, "tasks": recs})

    def read_state(self):
        rec = read_task_records(self.path).get(self.task_id) or {}
        return rec.get("state", "running")

    def set_step(self, note=""):
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
        self._mutate(lambda recs: (recs.get(self.task_id) or {}).update(
            {"current_step": note or "", "updated": now}) or recs)

    def finish(self, ok=True, rc=0):
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
        _rc = int(rc or 0)
        state = "cancelled" if _rc == 130 else ("done" if ok else "failed")
        self._mutate(lambda recs: (recs.get(self.task_id) or {}).update(
            {"state": state, "rc": _rc, "finished": now, "updated": now}) or recs)
        return state


def _signal_group(proc, sig):
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (OSError, ProcessLookupError, PermissionError):
        pass


def _terminate_group(proc):
    _signal_group(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _signal_group(proc, signal.SIGKILL)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def _wait_controlled(proc, tc):
    """在任务状态机控制下等待单个子进程结束；支持暂停/继续/取消。返回 (rc, status)。"""
    suspended = False
    try:
        while True:
            state = tc.read_state()
            if state == "cancelled":
                _terminate_group(proc)
                return (proc.returncode if proc.poll() is not None else 130), "cancelled"
            if state == "paused":
                if not suspended and proc.poll() is None:
                    _signal_group(proc, signal.SIGSTOP)
                    suspended = True
                if proc.poll() is None:
                    while tc.read_state() == "paused" and proc.poll() is None:
                        time.sleep(0.2)
                    if proc.poll() is None:
                        _signal_group(proc, signal.SIGCONT)
                    suspended = False
            elif suspended:
                if proc.poll() is None:
                    _signal_group(proc, signal.SIGCONT)
                suspended = False
            if proc.poll() is not None:
                return proc.returncode, "ok"
            time.sleep(0.2)
    except KeyboardInterrupt:
        _terminate_group(proc)
        return 130, "cancelled"


def _run_step_controlled(argv, kwargs, tc, timeout=0):
    """以可暂停/取消的方式执行单个子进程；返回 (rc, status, error)。"""
    kwargs = dict(kwargs)
    kwargs.pop("timeout", None)
    input_data = kwargs.pop("input", None)
    kwargs.pop("text", None)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE if input_data is not None else None,
                                start_new_session=True, **kwargs)
    except (OSError, ValueError) as exc:
        return 127, "error", exc
    if input_data is not None:
        try:
            data = input_data if isinstance(input_data, bytes) else str(input_data).encode("utf-8")
            proc.stdin.write(data)
            proc.stdin.flush()
            proc.stdin.close()
        except (OSError, ValueError):
            pass
    deadline = (time.time() + timeout) if timeout else None
    rc, status = _wait_controlled(proc, tc)
    if status == "cancelled":
        return rc, status, None
    if deadline and time.time() >= deadline:
        _terminate_group(proc)
        return 124, "timeout", None
    return rc, status, None


