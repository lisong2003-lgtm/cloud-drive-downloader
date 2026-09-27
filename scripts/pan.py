#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pan-downloader v0.6 — 多网盘统一下载入口（本机 + Windows + 远程设备）。

Ponytail full 设计原则：
- 不自己实现各家网盘协议；协议差异交给各网盘已有 CLI / AList / aria2。
- 核心只做四件事：识别链接、管理配置与目录、拼装引擎命令、执行并记录日志。
- 直链 HTTP 下载用系统 curl，开箱即用；分享链接走引擎适配器，未安装引擎时给出安装指引。

免费账号默认：并发 1、重试 3、断点续传、单任务日志。
会员账号可选：在配置里把 tier 设为 vip，引擎按自身能力提高并发，但本工具不做任何限速绕过。

远程设备不绑定品牌：只要目标开放 SSH/SFTP、WebDAV、SMB、S3 或 rclone，即可登记为 remote。
远程执行模式让 NAS 自己跑下载；远程落地模式在本机下载后通过 rclone 写入目标存储。
"""
from __future__ import annotations

import argparse
import copy
import getpass
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

APP = "pan-downloader"
VALID_TIERS = ("free", "vip", "auto")
KEYCHAIN_SERVICE = "com.lis.pan-downloader"
SECURITY_BIN = os.environ.get("PAN_SECURITY_BIN", "/usr/bin/security")
SKILL_DIR = Path(__file__).resolve().parent.parent


def platform_paths(system=None, env=None, home=None):
    """返回跨平台配置、状态、日志和默认下载目录。"""
    env = dict(os.environ if env is None else env)
    home = Path(home or env.get("HOME") or Path.home())
    system = (system or env.get("PAN_PLATFORM") or platform.system()).lower()
    if system.startswith("win"):
        appdata = Path(env.get("APPDATA") or (home / "AppData" / "Roaming"))
        local = Path(env.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        return {
            "config": appdata / APP / "config.json",
            "state": local / APP / "state",
            "log": local / APP / "logs" / (APP + ".log"),
            "download": home / "Downloads" / "网盘下载",
        }
    if system == "darwin":
        return {
            "config": home / ".config" / APP / "config.json",
            "state": home / ".local" / "share" / APP,
            "log": home / "Library" / "Logs" / (APP + ".log"),
            "download": home / "Downloads" / "网盘下载",
        }
    xdg_config = Path(env.get("XDG_CONFIG_HOME") or (home / ".config"))
    xdg_state = Path(env.get("XDG_STATE_HOME") or (home / ".local" / "state"))
    return {
        "config": xdg_config / APP / "config.json",
        "state": xdg_state / APP,
        "log": xdg_state / APP / "logs" / (APP + ".log"),
        "download": home / "Downloads" / "网盘下载",
    }


PATHS = platform_paths()
CONFIG_PATH = Path(os.environ.get("PAN_CONFIG", str(PATHS["config"])))
STATE_DIR = Path(os.environ.get("PAN_STATE_DIR", str(PATHS["state"])))
LOG_PATH = Path(os.environ.get("PAN_LOG", str(PATHS["log"])))
CREDENTIAL_REF_PREFIX = "credential:"

# ---------------------------------------------------------------- 网盘定义
DRIVES = {
    "baidu": {
        "name": "百度网盘",
        "domains": [
            "pan.baidu.com",
            "yun.baidu.com"
        ],
        "engine": "baidupcs",
        "reference": "references/01-百度网盘.md"
    },
    "aliyun": {
        "name": "阿里云盘",
        "domains": [
            "aliyundrive.com",
            "alipan.com",
            "www.aliyundrive.com"
        ],
        "engine": "alist",
        "reference": "references/02-阿里云盘.md"
    },
    "quark": {
        "name": "夸克网盘",
        "domains": [
            "pan.quark.cn"
        ],
        "engine": "quarkcli",
        "reference": "references/03-夸克网盘.md"
    },
    "tianyi": {
        "name": "天翼云盘",
        "domains": [
            "cloud.189.cn"
        ],
        "engine": "alist",
        "reference": "references/04-天翼云盘.md"
    },
    "thunder": {
        "name": "迅雷云盘",
        "domains": [
            "pan.xunlei.com"
        ],
        "engine": "alist",
        "reference": "references/05-迅雷云盘.md"
    },
    "115": {
        "name": "115 网盘",
        "domains": [
            "115.com",
            "anxia.com",
            "115cdn.com",
            "115.com.cn"
        ],
        "engine": "alist",
        "reference": "references/07-115网盘.md"
    },
    "123pan": {
        "name": "123 云盘",
        "domains": [
            "123pan.com",
            "123684.com",
            "123912.com",
            "123865.com"
        ],
        "engine": "alist",
        "reference": "references/08-123云盘.md"
    },
    "139yun": {
        "name": "移动云盘 / 和彩云",
        "domains": [
            "yun.139.com",
            "cloud.139.com",
            "caiyun.139.com"
        ],
        "engine": "alist",
        "reference": "references/09-移动云盘.md"
    },
    "wopan": {
        "name": "联通沃盘",
        "domains": [
            "wopan.wo.cn",
            "pan.wo.cn"
        ],
        "engine": "alist",
        "reference": "references/10-联通沃盘.md"
    },
    "uc": {
        "name": "UC 网盘",
        "domains": [
            "drive.uc.cn",
            "pan.uc.cn",
            "fast.uc.cn"
        ],
        "engine": "alist",
        "reference": "references/11-UC网盘.md"
    },
    "pikpak": {
        "name": "PikPak",
        "domains": [
            "mypikpak.com",
            "pikpak.com"
        ],
        "engine": "alist",
        "reference": "references/12-PikPak.md"
    },
    "jianguoyun": {
        "name": "坚果云",
        "domains": [
            "jianguoyun.com",
            "dav.jianguoyun.com"
        ],
        "engine": "webdav",
        "reference": "references/13-坚果云.md"
    },
    "onedrive": {
        "name": "OneDrive / SharePoint",
        "domains": [
            "onedrive.live.com",
            "1drv.ms",
            "sharepoint.com",
            "sharepoint.cn",
            "onedrive.com"
        ],
        "engine": "alist",
        "reference": "references/14-OneDrive与SharePoint.md"
    },
    "googledrive": {
        "name": "Google Drive",
        "domains": [
            "drive.google.com",
            "docs.google.com",
            "photos.google.com"
        ],
        "engine": "alist",
        "reference": "references/15-GoogleDrive.md"
    },
    "dropbox": {
        "name": "Dropbox",
        "domains": [
            "dropbox.com",
            "db.tt"
        ],
        "engine": "alist",
        "reference": "references/16-Dropbox.md"
    },
    "weiyun": {
        "name": "腾讯微云",
        "domains": [
            "weiyun.com"
        ],
        "engine": "alist",
        "reference": "references/17-腾讯微云.md"
    },
    "lanzou": {
        "name": "蓝奏云 / 新蓝奏",
        "domains": [
            "lanzou.com",
            "lanzoui.com",
            "lanzoux.com",
            "lanzouw.com",
            "lanzoup.com",
            "lanzoub.com",
            "lanzoue.com",
            "lanzous.com",
            "lanzoa.com",
            "lanzn.com",
            "ilanzou.com"
        ],
        "engine": "alist",
        "reference": "references/18-蓝奏云.md"
    },
    "wukong": {
        "name": "悟空网盘",
        "domains": [
            "wukong.com",
            "pan.wukong.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "doubao": {
        "name": "豆包新盘",
        "domains": [
            "doubao.com",
            "pan.doubao.com",
            "www.doubao.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "mega": {
        "name": "Mega",
        "domains": [
            "mega.nz",
            "mega.io"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "terabox": {
        "name": "TeraBox",
        "domains": [
            "terabox.com",
            "1024terabox.com",
            "teraboxapp.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "pcloud": {
        "name": "pCloud",
        "domains": [
            "pcloud.com",
            "pcloud.link"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "protondrive": {
        "name": "Proton Drive",
        "domains": [
            "drive.proton.me",
            "proton.me"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "yandexdisk": {
        "name": "Yandex Disk",
        "domains": [
            "disk.yandex.com",
            "disk.yandex.ru",
            "yadi.sk"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "mediafire": {
        "name": "MediaFire",
        "domains": [
            "mediafire.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "trainbit": {
        "name": "Trainbit",
        "domains": [
            "trainbit.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "guangyapan": {
        "name": "光雅盘",
        "domains": [
            "guangyapan.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "feijipan": {
        "name": "飞鸡云",
        "domains": [
            "feijipan.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "shandian": {
        "name": "闪电盘",
        "domains": [
            "shandianpan.com"
        ],
        "engine": "alist",
        "reference": "references/19-其他网盘.md"
    },
    "chengtong": {
        "name": "城通网盘",
        "domains": [
            "ctfile.com",
            "400gb.com"
        ],
        "engine": "custom",
        "reference": "references/19-其他网盘.md"
    },
    "direct": {
        "name": "HTTP 直链",
        "domains": [],
        "engine": "http",
        "reference": "references/00-使用说明.md"
    }
}
ENGINE_BINARIES = {
    "alist": ["alist", "AList"],
    "baidupcs": ["BaiduPCS-Go", "baidupcs-go", "BaiduPCS"],
    "quarkcli": ["quark", "quark-cli", "kuake"],
    "aria2": ["aria2c"],
    "rclone": ["rclone"],
    "ssh": ["ssh"],
    "scp": ["scp"],
    "tar": ["tar"],
}
DEFAULT_CONFIG = {
    "version": 5,
    "download_root": "",
    "tier": "auto",
    "http": {
        "retries": 3,
        "retry_delay": 5,
        "connect_timeout": 30,
        "timeout": 0,
        "max_connections_free": 1,
        "max_connections_vip": 4
    },
    "remote": {
        "staging_root": "",
        "keep_staging": False
    },
    "remotes": {},
    "engines": {
        "alist": "",
        "baidupcs": "",
        "quarkcli": "",
        "aria2c": "",
        "rclone": "",
        "alist_url": "",
        "alist_user": "",
        "alist_password_ref": "",
        "rclone_remote": "",
        "webdav_url": "",
        "webdav_user": "",
        "webdav_password_ref": ""
    },
    "drives": {
        "baidu": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": "",
            "save_path": "/网盘下载"
        },
        "aliyun": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "quark": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "tianyi": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "thunder": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "115": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "123pan": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "139yun": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "wopan": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "uc": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "pikpak": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "jianguoyun": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "onedrive": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "googledrive": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "dropbox": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "weiyun": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "lanzou": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "wukong": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "doubao": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "mega": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "terabox": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "pcloud": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "protondrive": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "yandexdisk": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "mediafire": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "trainbit": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "guangyapan": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "feijipan": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "shandian": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "chengtong": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        },
        "direct": {
            "tier": "auto",
            "account_tier": "",
            "tier_detector": "",
            "cookie_file": "",
            "credential_ref": "",
            "engine_command": ""
        }
    },
    "extensions": {}
}
SECRET_RE = re.compile(r"(cookie|token|password|passwd|secret|bduss|credential|authorization|auth|pass)", re.I)
KEYCHAIN_REF_PREFIX = "keychain:"


# ---------------------------------------------------------------- 基础工具
def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path=None):
    path = Path(path or CONFIG_PATH)
    if not path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return copy.deepcopy(DEFAULT_CONFIG)
    return deep_merge(DEFAULT_CONFIG, user)


def save_config(cfg, path=None):
    path = Path(path or CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # 凭据文件只允许本人读写
    except OSError:
        pass
    return path


def mask_value(key, value):
    if isinstance(value, dict):
        return {k: mask_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(key, v) for v in value]
    if SECRET_RE.search(str(key)) and value:
        return "***"
    return value


def _valid_secret_name(name):
    name = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._@-]{1,80}", name):
        raise ValueError("凭据名只允许字母、数字、点、下划线、@ 和连字符")
    return name


def credential_ref(name):
    return CREDENTIAL_REF_PREFIX + _valid_secret_name(name)


def normalize_secret_ref(value):
    text = str(value or "").strip()
    if is_secret_ref(text):
        return text
    return credential_ref(text)


def keychain_ref(name):
    """兼容旧调用；新配置统一推荐 credential: 引用。"""
    return credential_ref(name)


def is_secret_ref(value):
    return isinstance(value, str) and value.startswith((CREDENTIAL_REF_PREFIX, KEYCHAIN_REF_PREFIX))


def secret_ref_name(ref):
    if not is_secret_ref(ref):
        return ""
    for prefix in (CREDENTIAL_REF_PREFIX, KEYCHAIN_REF_PREFIX):
        if ref.startswith(prefix):
            return ref[len(prefix):].strip()
    return ""


def is_keychain_ref(value):
    return is_secret_ref(value)


def keychain_name(ref):
    return secret_ref_name(ref)


def credential_backend(system=None):
    system = (system or platform.system()).lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    if shutil.which("secret-tool"):
        return "secret-tool"
    return "unsupported"


def credential_available(system=None):
    backend = credential_backend(system)
    if backend == "macos":
        return bool(SECURITY_BIN and Path(SECURITY_BIN).exists())
    return backend in ("windows", "secret-tool")


def keychain_available():
    """兼容旧函数名；返回当前平台的系统凭据库是否可用。"""
    return credential_available()


def _secret_name(name):
    return re.sub(r"[^A-Za-z0-9._@-]+", "_", str(name or "").strip())


def _macos_keychain_store(name, value):
    if not (SECURITY_BIN and Path(SECURITY_BIN).exists()):
        raise RuntimeError("macOS security 命令不可用，拒绝保存明文；请在正常终端执行")
    proc = subprocess.run(
        [SECURITY_BIN, "add-generic-password", "-U", "-a", name, "-s", KEYCHAIN_SERVICE, "-w"],
        input=value + "\n" + value + "\n", text=True, capture_output=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "钥匙串写入失败").strip().splitlines()
        raise RuntimeError(msg[-1] if msg else "钥匙串写入失败")


def _macos_keychain_get(name):
    if not (SECURITY_BIN and Path(SECURITY_BIN).exists()):
        return ""
    proc = subprocess.run(
        [SECURITY_BIN, "find-generic-password", "-a", name, "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.rstrip("\r\n")


def _macos_keychain_delete(name):
    if not (SECURITY_BIN and Path(SECURITY_BIN).exists()):
        return False
    proc = subprocess.run(
        [SECURITY_BIN, "delete-generic-password", "-a", name, "-s", KEYCHAIN_SERVICE],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _windows_target(name):
    return "%s:%s" % (APP, name)


def _windows_credential_store(name, value):
    """Windows Credential Manager 写入；密码不经过 argv / stdin。"""
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL_ATTRIBUTE(ctypes.Structure):
        _fields_ = [
            ("Keyword", wintypes.LPWSTR),
            ("Flags", wintypes.DWORD),
            ("ValueSize", wintypes.DWORD),
            ("Value", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTE)),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    blob = value.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob, len(blob))
    cred = CREDENTIAL()
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = _windows_target(name)
    cred.UserName = name
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise RuntimeError("Windows 凭据管理器写入失败（错误码 %s）" % ctypes.get_last_error())


def _windows_credential_get(name):
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL_ATTRIBUTE(ctypes.Structure):
        _fields_ = [
            ("Keyword", wintypes.LPWSTR),
            ("Flags", wintypes.DWORD),
            ("ValueSize", wintypes.DWORD),
            ("Value", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTE)),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    ptr = ctypes.POINTER(CREDENTIAL)()
    if not ctypes.windll.advapi32.CredReadW(_windows_target(name), 1, 0, ctypes.byref(ptr)):
        return ""
    try:
        cred = ptr.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return raw.decode("utf-16-le").rstrip("\x00")
    finally:
        ctypes.windll.advapi32.CredFree(ptr)


def _windows_credential_delete(name):
    import ctypes

    return bool(ctypes.windll.advapi32.CredDeleteW(_windows_target(name), 1, 0))


def _secret_tool_store(name, value):
    proc = subprocess.run(
        ["secret-tool", "store", "--label", APP + " " + name, "service", APP, "account", name],
        input=value, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "secret-tool 写入失败").strip())


def _secret_tool_get(name):
    proc = subprocess.run(
        ["secret-tool", "lookup", "service", APP, "account", name],
        capture_output=True, text=True,
    )
    return proc.stdout.rstrip("\r\n") if proc.returncode == 0 else ""


def _secret_tool_delete(name):
    proc = subprocess.run(
        ["secret-tool", "clear", "service", APP, "account", name],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def credential_store(name, value):
    """把密码写入当前平台的系统凭据库；不把明文写入 config。"""
    name = _secret_name(name)
    if not name:
        raise ValueError("凭据名为空")
    if not value:
        raise ValueError("凭据为空")
    backend = credential_backend()
    if backend == "macos":
        _macos_keychain_store(name, value)
    elif backend == "windows":
        _windows_credential_store(name, value)
    elif backend == "secret-tool":
        _secret_tool_store(name, value)
    else:
        raise RuntimeError("当前系统没有可用的系统凭据库；拒绝把密码保存为明文")
    return credential_ref(name)


def keychain_store(name, value):
    """兼容旧函数名；实际写入当前平台的系统凭据库。"""
    return credential_store(name, value)


def credential_get(name):
    name = secret_ref_name(name) or _secret_name(name)
    if not name:
        return ""
    backend = credential_backend()
    if backend == "macos":
        return _macos_keychain_get(name)
    if backend == "windows":
        return _windows_credential_get(name)
    if backend == "secret-tool":
        return _secret_tool_get(name)
    return ""


def keychain_get(name):
    """兼容旧函数名。"""
    return credential_get(name)


def credential_delete(name):
    name = secret_ref_name(name) or _secret_name(name)
    if not name:
        return False
    backend = credential_backend()
    if backend == "macos":
        return _macos_keychain_delete(name)
    if backend == "windows":
        return _windows_credential_delete(name)
    if backend == "secret-tool":
        return _secret_tool_delete(name)
    return False


def keychain_delete(name):
    """兼容旧函数名。"""
    return credential_delete(name)


def resolve_secret(value):
    """解析 credential:/keychain: 引用；兼容旧配置里的明文值但不主动展示。"""
    if not value:
        return ""
    if is_secret_ref(value):
        # 通过兼容入口读取，便于旧测试/旧调用方替换 keychain_get。
        return keychain_get(secret_ref_name(value))
    return str(value)


def resolve_engine_secret(cfg, ref_key, legacy_key=""):
    eng = cfg.get("engines") or {}
    return resolve_secret(eng.get(ref_key) or eng.get(legacy_key) or "")


def configured_secret_refs(cfg):
    refs = {}
    eng = cfg.get("engines") or {}
    for key, label in (("alist_password_ref", "engine.alist"), ("webdav_password_ref", "engine.webdav")):
        ref = str(eng.get(key) or "")
        if ref:
            refs[label] = ref
    for drive, entry in (cfg.get("drives") or {}).items():
        ref = str((entry or {}).get("credential_ref") or "")
        if ref:
            refs["drive." + drive] = ref
    for remote, entry in (cfg.get("remotes") or {}).items():
        ref = str((entry or {}).get("credential_ref") or "")
        if ref:
            refs["remote." + remote] = ref
    return refs


def migrate_plaintext_secrets(cfg):
    """迁移已知明文凭据到系统凭据库，返回 (migrated, errors)。"""
    migrated, errors = [], []
    eng = cfg.setdefault("engines", {})
    for plain_key, ref_key, secret_name in (
        ("alist_password", "alist_password_ref", "engine.alist"),
        ("webdav_password", "webdav_password_ref", "engine.webdav"),
    ):
        value = str(eng.get(plain_key) or "")
        if not value:
            continue
        try:
            eng[ref_key] = keychain_store(secret_name, value)
            eng.pop(plain_key, None)
            migrated.append(secret_name)
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append("%s: %s" % (secret_name, exc))
    for drive, entry in (cfg.get("drives") or {}).items():
        if not isinstance(entry, dict) or entry.get("credential_ref"):
            continue
        for plain_key in ("password", "passwd", "token", "cookie", "credential", "bduss"):
            value = str(entry.get(plain_key) or "")
            if not value:
                continue
            secret_name = "drive." + drive
            try:
                entry["credential_ref"] = keychain_store(secret_name, value)
                entry.pop(plain_key, None)
                migrated.append(secret_name)
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append("%s: %s" % (secret_name, exc))
            break
    for remote, entry in (cfg.get("remotes") or {}).items():
        if not isinstance(entry, dict) or entry.get("credential_ref"):
            continue
        for plain_key in ("password", "passwd", "token", "secret", "credential"):
            value = str(entry.get(plain_key) or "")
            if not value:
                continue
            secret_name = "remote." + remote
            try:
                entry["credential_ref"] = keychain_store(secret_name, value)
                entry.pop(plain_key, None)
                migrated.append(secret_name)
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append("%s: %s" % (secret_name, exc))
            break
    return migrated, errors


def all_drives(cfg):
    drives = dict(DRIVES)
    for name, spec in (cfg.get("extensions") or {}).items():
        drives[name] = {
            "name": spec.get("name", name),
            "domains": spec.get("domains", []),
            "engine": spec.get("engine", "custom"),
            "reference": spec.get("reference", "references/06-扩展新网盘.md"),
        }
    return drives


def detect_drive(url, cfg=None):
    """返回 (drive_key, spec)；未知 http(s) 链接回退为 direct。"""
    cfg = cfg or load_config()
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return "direct", all_drives(cfg)["direct"]
    for key, spec in all_drives(cfg).items():
        for domain in spec.get("domains", []):
            d = domain.lower()
            if host == d or host.endswith("." + d):
                return key, spec
    if url.lower().startswith(("http://", "https://")):
        return "direct", all_drives(cfg)["direct"]
    return "", {}


def sanitize(name, fallback="download"):
    name = unquote(name or "").strip()
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:80] or fallback


def filename_from_url(url):
    path = urlparse(url).path
    base = sanitize(Path(path).name)
    if not base or base in (".", ".."):
        return "download.bin"
    return base


def url_slug(url):
    path = urlparse(url).path.rstrip("/")
    tail = sanitize(Path(path).name, fallback="share")
    return tail or "share"


def default_root(cfg):
    configured = (cfg.get("download_root") or "").strip()
    if configured:
        return Path(os.path.expanduser(configured))
    if platform.system().lower() == "darwin":
        for vol in ("/Volumes/拓展", "/Volumes/办公"):
            p = Path(vol)
            if p.is_dir() and os.access(str(p), os.W_OK):
                return p / "网盘下载"
    return Path(PATHS["download"])


def task_dir(cfg, drive_name, url, to=None):
    if to:
        return Path(os.path.expanduser(to))
    stamp = datetime.now().strftime("%Y%m%d")
    return default_root(cfg) / sanitize(drive_name) / (stamp + "-" + url_slug(url))


def find_engine_binary(engine, cfg):
    configured = ((cfg.get("engines") or {}).get(engine) or "").strip()
    if configured:
        p = Path(os.path.expanduser(configured))
        return str(p) if p.exists() else ""
    for name in ENGINE_BINARIES.get(engine, []):
        found = shutil.which(name)
        if found:
            return found
    return ""


# ---------------------------------------------------------------- 远程设备
REMOTE_KINDS = ("ssh", "rclone", "webdav", "smb", "s3", "mount")


def normalize_remote_kind(value):
    kind = str(value or "").strip().lower()
    aliases = {
        "sftp": "ssh",
        "synology": "ssh",
        "fnos": "ssh",
        "nas": "ssh",
        "ftp": "rclone",
        "nfs": "mount",
        "local-mount": "mount",
    }
    kind = aliases.get(kind, kind)
    return kind if kind in REMOTE_KINDS else ""


def remote_entry(cfg, name):
    name = str(name or "").strip()
    if not name:
        return None
    entry = (cfg.get("remotes") or {}).get(name)
    return entry if isinstance(entry, dict) else None


def validate_remote_profile(name, entry):
    """返回 (normalized_profile, missing)；只校验配置，不触碰网络。"""
    entry = dict(entry or {})
    kind = normalize_remote_kind(entry.get("kind"))
    entry["kind"] = kind
    entry["name"] = str(name or entry.get("name") or "").strip()
    missing = []
    if not entry["name"]:
        missing.append("remote 名称")
    if not kind:
        missing.append("kind（ssh/rclone/webdav/smb/s3/mount）")
    if kind == "ssh":
        for key, label in (("host", "host"), ("user", "user"), ("root", "root")):
            if not str(entry.get(key) or "").strip():
                missing.append(label)
    elif kind == "mount":
        if not str(entry.get("root") or "").strip():
            missing.append("root（本机挂载路径，Windows 示例 Z:\\下载）")
    elif kind in ("rclone", "webdav", "smb", "s3"):
        for key, label in (("remote_name", "remote_name（rclone 配置名）"), ("root", "root")):
            if not str(entry.get(key) or "").strip():
                missing.append(label)
    return entry, missing


def remote_ssh_argv(profile, command):
    host = str(profile["host"]).strip()
    user = str(profile["user"]).strip()
    destination = "%s@%s" % (user, host)
    argv = ["ssh", "-o", "BatchMode=yes"]
    port = str(profile.get("port") or "").strip()
    if port:
        argv += ["-p", port]
    argv += [destination, command]
    return argv


def remote_scp_argv(profile, source, destination):
    host = str(profile["host"]).strip()
    user = str(profile["user"]).strip()
    argv = ["scp", "-q", "-o", "BatchMode=yes"]
    port = str(profile.get("port") or "").strip()
    if port:
        argv += ["-P", port]
    argv += [str(source), "%s@%s:%s" % (user, host, destination)]
    return argv


def remote_display(profile):
    if profile.get("kind") == "ssh":
        return "ssh://%s@%s:%s%s" % (
            profile.get("user", ""), profile.get("host", ""), profile.get("port", "22"), profile.get("root", "")
        )
    if profile.get("kind") == "mount":
        return str(profile.get("root") or "")
    return "%s:%s" % (str(profile.get("remote_name") or "").rstrip(":"), profile.get("root", ""))


def remote_rclone_destination(profile, task_name):
    remote = str(profile.get("remote_name") or "").strip()
    if not remote:
        return ""
    remote = remote.rstrip(":") + ":"
    root = str(profile.get("root") or "").strip().replace("\\", "/").strip("/")
    path = "/".join([p for p in (root, sanitize(task_name)) if p])
    return remote + "/" + path if path else remote


def remote_task_name(drive_name, url):
    return "%s-%s" % (datetime.now().strftime("%Y%m%d"), url_slug(url))


def build_ssh_remote_plan(profile, url, pwd="", to=None, path=None, tier=None, engine=None):
    """远程执行模式：在 SSH 设备上调用已部署的 pan.py，文件直接落到远程磁盘。"""
    plan = {
        "ok": True,
        "drive": "remote-ssh",
        "drive_name": profile.get("name") or "远程设备",
        "engine": "ssh",
        "tier": tier or "",
        "target": remote_display(profile),
        "steps": [],
        "missing": [],
        "warnings": [],
        "reference": str(SKILL_DIR / "references/21-远程NAS与私有存储.md"),
        "remote_kind": "ssh-execute",
        "remote_name": profile.get("name", ""),
    }
    deploy_dir = str(profile.get("deploy_dir") or ".pan-downloader").strip().strip("/")
    python_bin = str(profile.get("python") or "python3").strip()
    remote_root = str(profile.get("root") or "").strip()
    task_name = remote_task_name(profile.get("name") or "remote", url)
    remote_target = str(to or ("%s/网盘下载/%s" % (remote_root.rstrip("/"), task_name)))
    script = "%s/scripts/pan.py" % deploy_dir
    cmd = "cd %s && %s %s get %s --to %s" % (
        shlex.quote(remote_root), shlex.quote(python_bin), shlex.quote(script),
        shlex.quote(url), shlex.quote(remote_target),
    )
    if pwd:
        cmd += " --pwd " + shlex.quote(pwd)
    if path:
        cmd += " --path " + shlex.quote(path)
    if tier:
        cmd += " --tier " + shlex.quote(tier)
    if engine:
        cmd += " --engine " + shlex.quote(engine)
    cmd += " --force"
    plan["steps"].append({
        "engine": "ssh",
        "argv": remote_ssh_argv(profile, cmd),
        "cwd": str(SKILL_DIR),
        "note": "在远程设备执行 pan.py，下载直接落到 %s（需要预先把 SSH 密钥/agent 配置好）" % remote_target,
    })
    plan["target"] = remote_target
    return plan


def build_remote_sink_plan(profile, url, pwd="", to=None, path=None, tier=None, engine=None, cfg=None):
    """远程落地模式：本机取文件，再通过 rclone 写入 NAS/私有存储。"""
    cfg = cfg or load_config()
    profile = dict(profile)
    name = profile.get("name") or "remote"
    remote_task = remote_task_name(name, url)
    if profile.get("kind") == "mount":
        mount_root = Path(os.path.expanduser(str(profile.get("root") or "")))
        target = Path(to) if to else mount_root / "网盘下载" / remote_task
        local_plan = build_plan(url, pwd=pwd, to=str(target), cfg=cfg, engine=engine, tier=tier, path=path)
        local_plan["remote_kind"] = "mounted-target"
        local_plan["remote_name"] = name
        local_plan["reference"] = str(SKILL_DIR / "references/21-远程NAS与私有存储.md")
        return local_plan

    staging_root = str((cfg.get("remote") or {}).get("staging_root") or "").strip()
    staging = Path(os.path.expanduser(staging_root)) if staging_root else STATE_DIR / "remote-staging" / sanitize(name)
    staging_task = staging / remote_task
    local_plan = build_plan(url, pwd=pwd, to=str(staging_task), cfg=cfg, engine=engine, tier=tier, path=path)
    local_plan["remote_kind"] = "rclone-upload"
    local_plan["remote_name"] = name
    local_plan["staging"] = str(staging_task)
    local_plan["reference"] = str(SKILL_DIR / "references/21-远程NAS与私有存储.md")
    destination = remote_rclone_destination(profile, remote_task)
    if destination:
        local_plan["target"] = destination
    binary = find_engine_binary("rclone", cfg)
    if not binary:
        local_plan["missing"].append("rclone")
    if not destination:
        local_plan["missing"].append("remote_name")
    if binary and destination:
        try:
            conn = int((cfg.get("http") or {}).get(
                "max_connections_vip" if local_plan.get("tier") == "vip" else "max_connections_free", 1
            ))
        except (TypeError, ValueError):
            conn = 1
        conn = max(1, conn)
        argv = [
            binary, "copy", "--progress", "--transfers", str(conn),
            "--checkers", str(max(1, min(conn * 2, 8))),
            str(staging_task), destination,
        ]
        local_plan["steps"].append({
            "engine": "rclone",
            "argv": argv,
            "note": "把 %s 上传到远程存储 %s（tier=%s）" % (staging_task, destination, local_plan.get("tier", "free")),
        })
    return local_plan


def build_remote_plan(profile, url, pwd="", to=None, path=None, tier=None, engine=None, cfg=None):
    cfg = cfg or load_config()
    profile, missing = validate_remote_profile(profile.get("name", ""), profile)
    if missing:
        return {
            "ok": False,
            "error": "远程配置缺少：" + "、".join(missing),
            "missing": missing,
        }
    if profile["kind"] == "ssh":
        return build_ssh_remote_plan(profile, url, pwd=pwd, to=to, path=path, tier=tier, engine=engine)
    return build_remote_sink_plan(profile, url, pwd=pwd, to=to, path=path, tier=tier, engine=engine, cfg=cfg)


def create_remote_deploy_archive():
    """打包技能文本与脚本，不含 config.json、凭据、缓存和用户数据。"""
    fd, tmp_name = tempfile.mkstemp(prefix="pan-downloader-deploy-", suffix=".tar.gz")
    os.close(fd)
    archive = Path(tmp_name)
    include = [SKILL_DIR / "SKILL.md", SKILL_DIR / "config.example.json", SKILL_DIR / "agents", SKILL_DIR / "references", SKILL_DIR / "scripts"]
    with tarfile.open(archive, "w:gz") as tar:
        for source in include:
            if source.is_file():
                tar.add(source, arcname=source.name)
            elif source.is_dir():
                for item in sorted(source.rglob("*")):
                    if item.is_file() and "__pycache__" not in item.parts and item.name not in ("config.json",):
                        tar.add(item, arcname=str(item.relative_to(SKILL_DIR)))
    return archive


def build_remote_deploy_plan(profile, archive_path):
    profile, missing = validate_remote_profile(profile.get("name", ""), profile)
    if missing:
        return {"ok": False, "error": "远程配置缺少：" + "、".join(missing), "steps": []}
    if profile.get("kind") != "ssh":
        return {"ok": False, "error": "remote deploy 只支持 kind=ssh；WebDAV/SMB/S3 请直接用 rclone", "steps": []}
    deploy_dir = str(profile.get("deploy_dir") or ".pan-downloader").strip().strip("/")
    remote_dir = str(profile.get("root") or "").rstrip("/") + "/" + deploy_dir
    remote_archive = "/tmp/pan-downloader-deploy-%s.tar.gz" % os.getpid()
    mkdir_cmd = "mkdir -p %s" % shlex.quote(remote_dir)
    extract_cmd = "tar -xzf %s -C %s && rm -f %s" % (
        shlex.quote(remote_archive), shlex.quote(remote_dir), shlex.quote(remote_archive)
    )
    steps = [
        {"engine": "ssh", "argv": remote_ssh_argv(profile, mkdir_cmd), "cwd": str(SKILL_DIR), "note": "创建远程技能目录 %s" % remote_dir},
        {"engine": "scp", "argv": remote_scp_argv(profile, archive_path, remote_archive), "cwd": str(SKILL_DIR), "note": "上传无凭据的部署包"},
        {"engine": "ssh", "argv": remote_ssh_argv(profile, extract_cmd), "cwd": str(SKILL_DIR), "note": "在远程设备解压技能脚本"},
    ]
    return {
        "ok": True,
        "drive": "remote-deploy",
        "drive_name": profile.get("name", ""),
        "engine": "ssh",
        "tier": "free",
        "target": remote_dir,
        "steps": steps,
        "missing": [],
        "warnings": ["远程设备首次使用仍需在设备本机配置网盘凭据；本工具不会上传本机 config 或密码"],
        "reference": str(SKILL_DIR / "references/21-远程NAS与私有存储.md"),
    }


def log_line(text, path=None):
    path = Path(path or LOG_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def _redact_argument(item):
    text = str(item)
    text = re.sub(
        r"(?i)(--(?:password|passwd|pwd|cookie|token|secret|credential|bduss|authorization|webdav-pass|alist-password)(?:\s+|=))(\S+)",
        r"\1***", text,
    )
    if re.match(r"(?i)^(--?(?:password|passwd|cookie|token|secret|credential|bduss|authorization)=)", text):
        return "***"
    if re.match(r"(?i)^(--?(?:password|passwd|pwd|cookie|token|secret|credential|bduss|authorization))$", text):
        return text
    if re.match(r"(?i)^(authorization|cookie):", text):
        return "***"
    if re.match(r"(?i)^-bduss=", text):
        return "***"
    return text


def mask_argv(argv):
    """隐藏命令行凭据；真正推荐路径是把密码放系统凭据库并从 stdin 传给引擎。"""
    out = []
    skip_next = False
    secret_flags = {
        "--password", "--passwd", "--pwd", "-p", "--cookie", "--token", "--secret",
        "--credential", "--bduss", "--user", "-u", "--webdav-pass", "--alist-password",
        "--webdav-password", "--alist-pass",
    }
    for i, item in enumerate(argv):
        if skip_next:
            out.append("***")
            skip_next = False
            continue
        current = _redact_argument(item)
        out.append(current)
        if item in secret_flags and i + 1 < len(argv):
            skip_next = True
    return out


def public_plan(plan):
    """给 agent/JSON 输出用的无凭据计划。"""
    steps = []
    for step in plan.get("steps", []):
        steps.append({
            "engine": step.get("engine", ""),
            "note": step.get("note", ""),
            "argv": mask_argv(step.get("argv") or []),
            "uses_stdin_credential": bool(step.get("stdin")),
        })
    return {
        "ok": plan.get("ok", False),
        "drive": plan.get("drive", ""),
        "drive_name": plan.get("drive_name", ""),
        "engine": plan.get("engine", ""),
        "tier": plan.get("tier", ""),
        "tier_source": plan.get("tier_source", ""),
        "target": plan.get("target", ""),
        "remote_kind": plan.get("remote_kind", ""),
        "remote_name": plan.get("remote_name", ""),
        "staging": plan.get("staging", ""),
        "steps": steps,
        "missing": plan.get("missing", []),
        "warnings": plan.get("warnings", []),
        "reference": plan.get("reference", ""),
    }


def curl_basic_auth_step(argv, user, password):
    """用 curl --config - 从 stdin 读取 Basic Auth，避免密码出现在 argv/日志。"""
    step = {"engine": "curl", "argv": list(argv), "note": "curl 下载（凭据通过 stdin，不写入命令行）"}
    if user and password:
        escaped_user = str(user).replace("\\", "\\\\").replace('"', '\\"')
        escaped_pass = str(password).replace("\\", "\\\\").replace('"', '\\"')
        step["stdin"] = 'user = "%s:%s"\n' % (escaped_user, escaped_pass)
        step["argv"].insert(-1, "--config")
        step["argv"].insert(-1, "-")
    return step


# ---------------------------------------------------------------- 账号等级探测
def detect_account_tier(drive_key, drive_cfg, cfg):
    """尽力探测账号等级；无法可靠判断时返回空值，绝不把普通账号当会员。"""
    recorded = str(drive_cfg.get("account_tier") or "").strip().lower()
    if recorded in ("free", "vip"):
        return recorded, "配置记录"

    detector = str(drive_cfg.get("tier_detector") or "").strip()
    if not detector:
        return "", "未配置检测器"

    env = os.environ.copy()
    env["PAN_DRIVE"] = drive_key
    env["PAN_COOKIE_FILE"] = str(drive_cfg.get("cookie_file") or "")
    try:
        cmd = shlex.split(detector.format(drive=drive_key))
        if not cmd:
            return "", "检测器为空"
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
    except subprocess.TimeoutExpired:
        return "", "检测器超时"
    except (OSError, ValueError):
        return "", "检测器不可执行"

    text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
    if re.search(r"(vip|会员|supervip|svip|premium|pro\b)", text):
        return "vip", "tier_detector（%s）" % detector
    if re.search(r"(free|免费|普通)", text):
        return "free", "tier_detector（%s）" % detector
    return "", "检测器未返回明确等级"


# ---------------------------------------------------------------- 计划构建
def http_step(url, target, cfg, tier):
    filename = filename_from_url(url)
    http = cfg.get("http", {})
    argv = [
        "curl", "-L", "--fail", "--retry", str(http.get("retries", 3)),
        "--retry-delay", str(http.get("retry_delay", 5)),
        "--connect-timeout", str(http.get("connect_timeout", 30)),
        "-C", "-", "-o", str(Path(target) / filename), url,
    ]
    return {"engine": "http", "argv": argv, "note": "curl 断点续传下载（免费/会员参数一致）"}


def build_plan(url, pwd="", to=None, cfg=None, engine=None, tier=None, path=None):
    cfg = cfg or load_config()
    key, spec = detect_drive(url, cfg)
    if not key:
        return {"ok": False, "error": "无法识别的链接（既不是已知网盘域名，也不是 http(s) 直链）"}
    drive_cfg = (cfg.get("drives") or {}).get(key, {})
    requested_tier = str(tier or drive_cfg.get("tier") or cfg.get("tier") or "auto").strip().lower()
    target = task_dir(cfg, spec["name"], url, to)
    engine = engine or (cfg.get("extensions", {}).get(key, {}) or {}).get("engine") or spec.get("engine", "http")
    plan = {
        "ok": True,
        "drive": key,
        "drive_name": spec["name"],
        "engine": engine,
        "tier": "",
        "requested_tier": requested_tier,
        "tier_source": "",
        "target": str(target),
        "reference": str(SKILL_DIR / spec.get("reference", "")),
        "steps": [],
        "missing": [],
        "warnings": [],
    }

    if requested_tier not in VALID_TIERS:
        plan["warnings"].append("tier=%s 不合法，已按 free 处理" % requested_tier)
        requested_tier = "free"

    if requested_tier == "auto":
        detected, source = detect_account_tier(key, drive_cfg, cfg)
        if detected:
            tier = detected
            plan["tier_source"] = source
            plan["warnings"].append("账号等级自动识别为 %s（%s）" % (detected, source))
        else:
            tier = "free"
            plan["tier_source"] = source
            plan["warnings"].append(
                "账号等级未自动识别（%s），先按免费账号处理；登录后可用"
                " set-drive %s --account-tier free|vip 记录，或本次加 --tier vip 强制" % (source, key)
            )
    else:
        tier = requested_tier

    plan["tier"] = tier

    custom_cmd = (drive_cfg.get("engine_command") or "").strip()

    if custom_cmd:
        argv = shlex.split(
            custom_cmd.format(url=url, pwd=pwd or "", dir=str(target), name=sanitize(spec["name"]), tier=tier)
        )
        plan["steps"].append({"engine": "custom", "argv": argv, "note": "自定义引擎命令"})
        return plan

    if engine == "http":
        plan["steps"].append(http_step(url, target, cfg, tier))

    elif engine == "aria2":
        binary = find_engine_binary("aria2", cfg)
        if not binary:
            plan["missing"].append("aria2c")
        conn = cfg.get("http", {}).get("max_connections_vip" if tier == "vip" else "max_connections_free", 1)
        filename = filename_from_url(url)
        argv = [binary or "aria2c", "-c", "--retry-wait=5", "-m", str(cfg.get("http", {}).get("retries", 3)),
                "-x", str(conn), "-s", str(conn), "-d", str(target), "-o", filename, url]
        plan["steps"].append({"engine": "aria2", "argv": argv, "note": "aria2 多线程下载（tier=%s，并发 %s）" % (tier, conn)})

    elif engine == "alist":
        server = ((cfg.get("engines") or {}).get("alist_url") or "").strip()
        dav_user = ((cfg.get("engines") or {}).get("alist_user") or "").strip()
        dav_ref = ((cfg.get("engines") or {}).get("alist_password_ref") or "").strip()
        dav_pass = resolve_engine_secret(cfg, "alist_password_ref", "alist_password")
        if dav_ref and not dav_pass:
            plan["warnings"].append("AList 凭据引用无法从系统凭据库读取；请在本机终端运行 secret set engine.alist")
        if not path:
            plan["missing"].append("AList 路径：分享链接需先在 AList 中挂载/转存，再用 --path /挂载名/子目录 指定")
            plan["steps"].append({"engine": "alist", "argv": [], "note": "建议流程：1) AList 添加对应网盘存储 2) 浏览器打开分享链接转存到自己账号 3) 用 --path 指向 AList 中的目录"})
        elif not server:
            plan["missing"].append("alist_url（在 config.json 的 engines.alist_url 填写 AList 地址）")
        else:
            remote = path if path.startswith("/") else "/" + path
            filename = sanitize(Path(remote).name, fallback="download")
            rclone_bin = find_engine_binary("rclone", cfg)
            rclone_remote = ((cfg.get("engines") or {}).get("rclone_remote") or "").strip()
            if rclone_bin and rclone_remote:
                # rclone 远端名必须带冒号；允许用户只填 alist，脚本自动补成 alist:。
                if ":" not in rclone_remote:
                    rclone_remote += ":"
                remote_path = rclone_remote.rstrip("/") + remote
                try:
                    conn = int(cfg.get("http", {}).get("max_connections_vip" if tier == "vip" else "max_connections_free", 1))
                except (TypeError, ValueError):
                    conn = 1
                conn = max(1, conn)
                checkers = max(1, min(conn * 2, 8))
                argv = [
                    rclone_bin, "copy", "--progress",
                    "--transfers", str(conn), "--checkers", str(checkers),
                    remote_path, str(target),
                ]
                plan["steps"].append({"engine": "rclone", "argv": argv,
                                      "note": "通过 rclone/AList WebDAV 递归下载（tier=%s，并发 %s，远端 %s）" % (tier, conn, remote_path)})
            else:
                if rclone_bin and not rclone_remote:
                    plan["warnings"].append("已安装 rclone 但未配置 engines.rclone_remote，回退为 curl 单文件下载")
                elif not rclone_bin:
                    plan["warnings"].append("未安装 rclone；curl 回退只适合单文件，目录请在 Finder 挂载 AList WebDAV 或安装 rclone")
                argv = ["curl", "-L", "--fail", "-C", "-", "-o", str(target / filename), server.rstrip("/") + "/dav" + remote]
                step = curl_basic_auth_step(argv, dav_user, dav_pass)
                step["engine"] = "alist"
                step["note"] = "通过 AList WebDAV 下载单文件（挂载路径 %s；凭据走 stdin）" % remote
                plan["steps"].append(step)

    elif engine == "webdav":
        eng = cfg.get("engines") or {}
        server = (eng.get("webdav_url") or "").strip().rstrip("/")
        dav_user = (eng.get("webdav_user") or "").strip()
        dav_ref = (eng.get("webdav_password_ref") or "").strip()
        dav_pass = resolve_engine_secret(cfg, "webdav_password_ref", "webdav_password")
        if dav_ref and not dav_pass:
            plan["warnings"].append("WebDAV 凭据引用无法从系统凭据库读取；请在本机终端运行 secret set engine.webdav")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        download_url = ""
        if host == "dav.jianguoyun.com" and parsed.path.startswith("/dav"):
            download_url = url
        elif path and server:
            download_url = server + "/" + path.lstrip("/")
        if not download_url:
            plan["missing"].append("webdav_url + --path，或直接使用 dav.jianguoyun.com 的 WebDAV 文件地址")
        else:
            filename = sanitize(Path(urlparse(download_url).path).name or filename_from_url(url), fallback="download")
            argv = ["curl", "-L", "--fail", "-C", "-", "-o", str(target / filename), download_url]
            step = curl_basic_auth_step(argv, dav_user, dav_pass)
            step["engine"] = "webdav"
            step["note"] = "通过 WebDAV 断点续传下载（坚果云/通用 WebDAV；凭据走 stdin）"
            plan["steps"].append(step)

    elif engine == "baidupcs":
        binary = find_engine_binary("baidupcs", cfg)
        if not binary:
            plan["missing"].append("BaiduPCS-Go")
        save_path = ((cfg.get("drives") or {}).get("baidu", {}).get("save_path") or "/网盘下载").strip()
        binary = binary or "BaiduPCS-Go"
        plan["steps"].append({"engine": "baidupcs", "argv": [binary, "transfer", url, pwd or "", save_path],
                              "note": "转存到自己网盘（需已用 BaiduPCS-Go login 登录）"})
        plan["steps"].append({"engine": "baidupcs", "argv": [binary, "download", save_path, "--saveto", str(target)],
                              "note": "从自己网盘批量下载到本地（断点续传）"})

    elif engine == "quarkcli":
        binary = find_engine_binary("quarkcli", cfg)
        if not binary:
            plan["missing"].append("quark-cli（夸克命令行工具）")
        argv = [binary or "quark", "download", url]
        if pwd:
            argv += ["--pwd", pwd]
        argv += ["--dir", str(target)]
        plan["steps"].append({"engine": "quarkcli", "argv": argv, "note": "夸克分享链接转存并下载（Cookie 登录）"})

    else:
        plan["missing"].append("引擎 %s 未配置 engine_command" % engine)
        plan["steps"].append({"engine": engine, "argv": [], "note": "在 config.json 的 drives.%s.engine_command 配置命令模板" % key})

    return plan


def run_plan(plan, timeout=0, dry_run=True):
    if not plan.get("ok"):
        return 1
    for step in plan["steps"]:
        argv = step.get("argv") or []
        if not argv:
            continue
        if dry_run:
            print("DRY-RUN:", " ".join(shlex.quote(x) for x in mask_argv(argv)))
            continue
        print("RUN:", " ".join(shlex.quote(x) for x in mask_argv(argv)))
        log_line("RUN: " + " ".join(mask_argv(argv)))
        started = time.time()
        try:
            cwd = str(step.get("cwd") or plan.get("run_cwd") or plan.get("target") or "")
            kwargs = {"timeout": timeout or None}
            if cwd and Path(cwd).exists():
                kwargs["cwd"] = cwd
            if step.get("stdin"):
                kwargs["input"] = step["stdin"]
                kwargs["text"] = True
            proc = subprocess.run(argv, **kwargs)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            print("❌ 超时：%s" % step.get("note", argv[0]))
            log_line("TIMEOUT: " + " ".join(mask_argv(argv)))
            return 124
        except OSError as exc:
            print("❌ 执行失败：%s（%s）" % (argv[0], exc))
            log_line("ERROR: %s %s" % (argv[0], exc))
            return 127
        log_line("EXIT %s (%.1fs): %s" % (rc, time.time() - started, " ".join(mask_argv(argv))))
        if rc != 0:
            print("❌ 步骤失败（exit=%s）：%s" % (rc, step.get("note", "")))
            return rc
    return 0


# ---------------------------------------------------------------- 子命令
def cmd_doctor(args):
    cfg = load_config()
    backend_names = {
        "macos": "macOS Keychain",
        "windows": "Windows Credential Manager",
        "secret-tool": "libsecret / secret-tool",
        "unsupported": "不可用（拒绝保存明文）",
    }
    backend = credential_backend()
    checks = [
        ("python3", sys.version.split()[0]),
        ("系统", "%s / %s" % (platform.system() or "unknown", backend_names.get(backend, backend))),
        ("curl", shutil.which("curl") or "缺失"),
        ("aria2c", find_engine_binary("aria2", cfg) or "未安装（可选）"),
        ("alist", find_engine_binary("alist", cfg) or "未安装（多数网盘挂载需要）"),
        ("BaiduPCS-Go", find_engine_binary("baidupcs", cfg) or "未安装（百度分享需要）"),
        ("quark-cli", find_engine_binary("quarkcli", cfg) or "未安装（夸克分享需要）"),
        ("rclone", find_engine_binary("rclone", cfg) or "未安装（可选，目录递归需要）"),
        ("ssh", find_engine_binary("ssh", cfg) or "未安装（远程执行/部署需要）"),
        ("scp", find_engine_binary("scp", cfg) or "未安装（远程部署需要）"),
        ("webdav", ((cfg.get("engines") or {}).get("webdav_url") or "未配置（坚果云 WebDAV 需要）")),
        ("系统凭据库", backend_names.get(backend, backend) if credential_available() else "不可用（拒绝保存明文）"),
        ("配置文件", str(CONFIG_PATH) if CONFIG_PATH.exists() else "未创建（运行 init）"),
        ("默认下载目录", str(default_root(cfg))),
        ("远程设备", "%d 个已登记" % len(cfg.get("remotes") or {})),
    ]
    if args.json:
        print(json.dumps({"checks": checks, "config": mask_value("config", cfg)}, ensure_ascii=False, indent=2))
        return 0
    print("pan-downloader doctor")
    for name, value in checks:
        print("  %-14s %s" % (name, value))
    return 0


def cmd_init(args):
    cfg = load_config()
    if CONFIG_PATH.exists() and not args.force:
        print("已存在，未变更：%s" % CONFIG_PATH)
        return 0
    path = save_config(cfg)
    print("已创建：%s（权限 600；账号密码另存系统凭据库，不写入此文件）" % path)
    return 0


def cmd_show(args):
    cfg = load_config()
    print(json.dumps(mask_value("config", cfg), ensure_ascii=False, indent=2))
    return 0


def cmd_detect(args):
    key, spec = detect_drive(args.url)
    if not key:
        print("❌ 无法识别")
        return 1
    print(json.dumps({"drive": key, "name": spec["name"], "engine": spec["engine"],
                      "reference": spec.get("reference", "")}, ensure_ascii=False, indent=2))
    return 0


def _read_stdin_secret():
    value = sys.stdin.read().rstrip("\r\n")
    if not value:
        raise ValueError("stdin 没有收到密码")
    return value


def _save_engine_secret(eng, ref_key, legacy_key, value, secret_name):
    if not value:
        return True
    try:
        eng[ref_key] = keychain_store(secret_name, value)
        eng.pop(legacy_key, None)
    except (OSError, ValueError, RuntimeError) as exc:
        print("❌ 凭据未保存：%s" % exc)
        return False
    return True


def cmd_secret_set(args):
    try:
        value = _read_stdin_secret() if args.stdin else getpass.getpass("凭据（不回显）：")
        ref = keychain_store(args.name, value)
    except (OSError, EOFError, KeyboardInterrupt, ValueError, RuntimeError) as exc:
        print("❌ 凭据保存失败：%s" % exc)
        return 1
    print("✅ 已存入系统凭据库：%s（明文不写入 config.json）" % ref)
    return 0


def cmd_secret_check(args):
    names = [args.name] if args.name else sorted(configured_secret_refs(load_config()))
    rows = []
    for name in names:
        rows.append({"name": name, "present": bool(keychain_get(name))})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print("%s  %s" % ("✅" if row["present"] else "❌", row["name"]))
    return 0 if all(row["present"] for row in rows) else 1


def cmd_secret_delete(args):
    if keychain_delete(args.name):
        print("✅ 已从系统凭据库删除：%s" % args.name)
        return 0
    print("❌ 未找到或删除失败：%s" % args.name)
    return 1


def cmd_secret_list(args):
    cfg = load_config()
    refs = configured_secret_refs(cfg)
    rows = [{"name": name, "ref": ref, "present": bool(keychain_get(keychain_name(ref)))}
            for name, ref in sorted(refs.items())]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        if not rows:
            print("未配置凭据引用。保存方式：pan secret set engine.webdav --stdin")
        for row in rows:
            print("%s  %-18s %s" % ("✅" if row["present"] else "❌", row["name"], row["ref"]))
    return 0


def cmd_secret_migrate(args):
    cfg = load_config()
    migrated, errors = migrate_plaintext_secrets(cfg)
    if errors:
        for item in errors:
            print("❌ %s" % item)
        return 1
    if migrated:
        path = save_config(cfg)
        print("✅ 已迁移 %d 项到系统凭据库：%s" % (len(migrated), path))
    else:
        print("未发现需要迁移的明文凭据")
    return 0


def cmd_set(args):
    cfg = load_config()
    if args.root is not None:
        cfg["download_root"] = args.root
    if args.tier is not None:
        cfg["tier"] = args.tier
    if args.engine is not None and args.engine_name:
        cfg.setdefault("engines", {})[args.engine_name] = args.engine
    eng = cfg.setdefault("engines", {})
    if args.alist_url:
        eng["alist_url"] = args.alist_url
    if args.alist_user:
        eng["alist_user"] = args.alist_user
    if args.rclone_remote:
        eng["rclone_remote"] = args.rclone_remote
    if args.webdav_url:
        eng["webdav_url"] = args.webdav_url
    if args.webdav_user:
        eng["webdav_user"] = args.webdav_user

    secret_values = (
        ("alist_password_ref", "alist_password", "engine.alist", args.alist_password, args.alist_password_stdin),
        ("webdav_password_ref", "webdav_password", "engine.webdav", args.webdav_password, args.webdav_password_stdin),
    )
    for ref_key, legacy_key, secret_name, legacy_value, from_stdin in secret_values:
        if legacy_value and from_stdin:
            print("❌ 同一凭据不能同时使用命令行和 --stdin")
            return 1
        try:
            value = _read_stdin_secret() if from_stdin else (legacy_value or "")
        except ValueError as exc:
            print("❌ %s" % exc)
            return 1
        if not _save_engine_secret(eng, ref_key, legacy_key, value, secret_name):
            return 1
        if legacy_value:
            print("⚠️ 为兼容旧命令已改存系统凭据库；以后请用 --stdin 或 secret set，避免命令行暴露")
    path = save_config(cfg)
    print("已保存：%s" % path)
    return 0


def cmd_set_drive(args):
    cfg = load_config()
    drives = cfg.setdefault("drives", {})
    entry = drives.setdefault(args.drive, {})
    if args.tier:
        entry["tier"] = args.tier
    if args.account_tier:
        entry["account_tier"] = args.account_tier
    if args.tier_detector:
        entry["tier_detector"] = args.tier_detector
    if args.cookie_file:
        entry["cookie_file"] = args.cookie_file
    if args.engine_command:
        entry["engine_command"] = args.engine_command
    if args.save_path:
        entry["save_path"] = args.save_path
    if args.credential_ref:
        try:
            entry["credential_ref"] = normalize_secret_ref(args.credential_ref)
        except ValueError as exc:
            print("❌ %s" % exc)
            return 1
    if args.credential_stdin:
        try:
            entry["credential_ref"] = keychain_store("drive." + args.drive, _read_stdin_secret())
        except (OSError, EOFError, ValueError, RuntimeError) as exc:
            print("❌ 凭据未保存：%s" % exc)
            return 1
    path = save_config(cfg)
    print("已保存 %s 配置：%s" % (args.drive, path))
    return 0


def cmd_login(args):
    drive_key, spec = detect_drive(args.drive) if "://" in args.drive else (args.drive, all_drives(load_config()).get(args.drive, {}))
    if not spec:
        print("❌ 未找到网盘：%s（可用 detect 或 references/06-扩展新网盘.md 自定义）" % drive_key)
        return 1
    ref = SKILL_DIR / (spec.get("reference") or "references/00-使用说明.md")
    print("按以下文件完成一次登录（凭据只存本机系统凭据库/客户端配置）：%s" % ref)
    print("安全提示：账号、密码、Cookie、Token 不要发到聊天里；在本机终端用 pan secret set 保存。")
    if ref.exists():
        text = ref.read_text(encoding="utf-8").splitlines()
        for line in text[:80]:
            print(line)
    return 0


def _remote_public(entry):
    return {
        "name": entry.get("name", ""),
        "kind": entry.get("kind", ""),
        "host": entry.get("host", ""),
        "port": entry.get("port", ""),
        "user": entry.get("user", ""),
        "root": entry.get("root", ""),
        "remote_name": entry.get("remote_name", ""),
        "python": entry.get("python", ""),
        "deploy_dir": entry.get("deploy_dir", ""),
        "credential_ref": entry.get("credential_ref", ""),
        "description": entry.get("description", ""),
    }


def cmd_remote_add(args):
    cfg = load_config()
    remotes = cfg.setdefault("remotes", {})
    name = str(args.name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._@-]{1,80}", name):
        print("❌ remote 名称只允许字母、数字、点、下划线、@ 和连字符")
        return 1
    entry = remotes.setdefault(name, {})
    if args.kind:
        entry["kind"] = normalize_remote_kind(args.kind) or args.kind
    for attr, key in (
        ("host", "host"), ("port", "port"), ("user", "user"), ("root", "root"),
        ("remote_name", "remote_name"), ("python", "python"), ("deploy_dir", "deploy_dir"),
        ("description", "description"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            entry[key] = value
    if args.credential_ref:
        try:
            entry["credential_ref"] = normalize_secret_ref(args.credential_ref)
        except ValueError as exc:
            print("❌ %s" % exc)
            return 1
    if args.credential_stdin:
        try:
            entry["credential_ref"] = credential_store("remote." + name, _read_stdin_secret())
        except (OSError, EOFError, ValueError, RuntimeError) as exc:
            print("❌ 凭据未保存：%s" % exc)
            return 1
    profile, missing = validate_remote_profile(name, entry)
    if missing:
        print("⚠️ 已保存，但配置不完整：%s" % "、".join(missing))
    path = save_config(cfg)
    print("已保存 remote.%s：%s" % (name, path))
    return 0


def cmd_remote_list(args):
    cfg = load_config()
    rows = []
    for name, entry in sorted((cfg.get("remotes") or {}).items()):
        profile, missing = validate_remote_profile(name, entry)
        row = _remote_public(profile)
        row["ready"] = not missing
        row["missing"] = missing
        rows.append(row)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print("尚未登记远程设备。示例：pan remote add nas --kind ssh --host 192.168.1.10 --user lis --root /volume1")
    else:
        for row in rows:
            print("%s %-18s %-8s %s" % ("✅" if row["ready"] else "⚠️", row["name"], row["kind"], row["host"] or row["remote_name"] or row["root"]))
    return 0


def cmd_remote_remove(args):
    cfg = load_config()
    remotes = cfg.setdefault("remotes", {})
    if args.name not in remotes:
        print("❌ 未找到 remote：%s" % args.name)
        return 1
    remotes.pop(args.name, None)
    path = save_config(cfg)
    print("✅ 已移除 remote.%s：%s" % (args.name, path))
    return 0


def _remote_checks(profile):
    checks = []
    kind = profile.get("kind")
    if kind == "ssh":
        checks.append(("ssh", find_engine_binary("ssh", {}) or "未安装（远程执行需要）"))
        checks.append(("scp", find_engine_binary("scp", {}) or "未安装（远程部署需要）"))
        checks.append(("认证方式", "SSH key/agent（BatchMode=yes，禁止把远程密码放进命令行）"))
    elif kind == "mount":
        root = Path(os.path.expanduser(str(profile.get("root") or "")))
        checks.append(("挂载路径", "%s（%s）" % (root, "可写" if root.exists() and os.access(str(root), os.W_OK) else "不可用或未挂载")))
    else:
        checks.append(("rclone", find_engine_binary("rclone", {}) or "未安装（远程落地需要）"))
        checks.append(("rclone remote", str(profile.get("remote_name") or "未配置")))
    return checks


def cmd_remote_check(args):
    cfg = load_config()
    entry = remote_entry(cfg, args.name)
    if entry is None:
        print("❌ 未找到 remote：%s" % args.name)
        return 1
    profile, missing = validate_remote_profile(args.name, entry)
    if missing:
        if args.json:
            print(json.dumps({"name": args.name, "ready": False, "missing": missing}, ensure_ascii=False, indent=2))
        else:
            print("❌ remote.%s 配置不完整：%s" % (args.name, "、".join(missing)))
        return 1
    checks = _remote_checks(profile)
    probe = ""
    if getattr(args, "probe", False):
        if profile["kind"] == "ssh":
            cmd = "python3 --version && mkdir -p %s" % shlex.quote(str(profile.get("root") or ""))
            try:
                proc = subprocess.run(remote_ssh_argv(profile, cmd), capture_output=True, text=True, timeout=20)
                probe = "成功：%s" % ((proc.stdout or proc.stderr or "").strip().splitlines()[-1] if (proc.stdout or proc.stderr) else "远程响应正常")
                if proc.returncode != 0:
                    probe = "失败：SSH/远程 Python 不可用（exit=%s）" % proc.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                probe = "失败：%s" % exc
        elif profile["kind"] != "mount":
            destination = remote_rclone_destination(profile, "")
            try:
                proc = subprocess.run(["rclone", "lsd", destination], capture_output=True, text=True, timeout=20)
                probe = "成功：%s" % ((proc.stdout or proc.stderr or "").strip().splitlines()[-1] if (proc.stdout or proc.stderr) else "远端响应正常")
                if proc.returncode != 0:
                    probe = "失败：rclone 远端不可用（exit=%s）" % proc.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                probe = "失败：%s" % exc
    result = {"name": args.name, "kind": profile.get("kind"), "ready": True, "checks": checks, "probe": probe}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("remote.%s（%s）" % (args.name, profile.get("kind")))
        for name, value in checks:
            print("  %-14s %s" % (name, value))
        if probe:
            print("  探测            %s" % probe)
    return 0 if not probe.startswith("失败") else 1


def cmd_remote_deploy(args):
    cfg = load_config()
    entry = remote_entry(cfg, args.name)
    if entry is None:
        print("❌ 未找到 remote：%s" % args.name)
        return 1
    profile, missing = validate_remote_profile(args.name, entry)
    if missing:
        print("❌ remote.%s 配置不完整：%s" % (args.name, "、".join(missing)))
        return 1
    profile["name"] = args.name
    archive = None
    try:
        archive = create_remote_deploy_archive()
        plan = build_remote_deploy_plan(profile, archive)
        if not plan.get("ok"):
            print("❌ %s" % plan.get("error"))
            return 1
        if args.dry_run:
            run_plan(plan, dry_run=True)
            print("DRY-RUN 完成：未上传部署包")
            return 0
        if args.json:
            print(json.dumps(public_plan(plan), ensure_ascii=False, indent=2))
            return 0
        rc = run_plan(plan, dry_run=False)
        if rc == 0:
            print("✅ 已部署到 remote.%s：%s" % (args.name, plan["target"]))
        return rc
    finally:
        if archive:
            try:
                archive.unlink()
            except OSError:
                pass


def _plan_dirs(plan):
    if plan.get("remote_kind") == "ssh-execute":
        return []
    path = plan.get("staging") or plan.get("target")
    if path:
        return [Path(str(path))]
    return []


def cmd_remote_get(args):
    cfg = load_config()
    name = getattr(args, "name", None) or getattr(args, "remote", None)
    entry = remote_entry(cfg, name)
    if entry is None:
        print("❌ 未找到 remote：%s" % name)
        return 1
    profile, missing = validate_remote_profile(name, entry)
    if missing:
        print("❌ remote.%s 配置不完整：%s" % (name, "、".join(missing)))
        return 1
    profile["name"] = name
    plan = build_remote_plan(profile, args.url, pwd=args.pwd or "", to=getattr(args, "to", None),
                             path=getattr(args, "path", None), tier=getattr(args, "tier", None),
                             engine=getattr(args, "engine", None), cfg=cfg)
    if not plan.get("ok"):
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": plan.get("error", ""), "missing": plan.get("missing", [])}, ensure_ascii=False, indent=2))
        else:
            print("❌ %s" % plan.get("error"))
        return 1
    if getattr(args, "json", False):
        print(json.dumps(public_plan(plan), ensure_ascii=False, indent=2))
    else:
        print("远程：%s｜模式：%s｜引擎：%s｜目标：%s" % (name, plan.get("remote_kind", ""), plan.get("engine", ""), plan.get("target", "")))
        for step in plan.get("steps", []):
            print("  - %s" % step.get("note", ""))
        for warn in plan.get("warnings", []):
            print("  ⚠️ %s" % warn)
        if plan.get("missing"):
            print("缺少依赖：")
            for item in plan["missing"]:
                print("  - %s" % item)
    if plan.get("missing") and not args.dry_run and not getattr(args, "force", False):
        return 2
    if args.dry_run:
        if not getattr(args, "json", False):
            run_plan(plan, dry_run=True)
            print("DRY-RUN 完成：未执行远程操作")
        return 0
    for directory in _plan_dirs(plan):
        directory.mkdir(parents=True, exist_ok=True)
    log_line("REMOTE name=%s kind=%s engine=%s target=%s url=%s" % (name, plan.get("remote_kind", ""), plan.get("engine", ""), plan.get("target", ""), args.url))
    rc = run_plan(plan, timeout=cfg.get("http", {}).get("timeout", 0), dry_run=False)
    if rc == 0:
        print("✅ 远程下载完成：%s" % plan.get("target", ""))
    return rc


def cmd_get(args):
    if getattr(args, "remote", None):
        return cmd_remote_get(args)
    cfg = load_config()
    plan = build_plan(args.url, pwd=args.pwd or "", to=args.to, cfg=cfg,
                      engine=args.engine, tier=args.tier, path=args.path)
    if not plan.get("ok"):
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": plan.get("error", "")}, ensure_ascii=False, indent=2))
        else:
            print("❌ %s" % plan.get("error"))
        return 1
    if getattr(args, "json", False):
        print(json.dumps(public_plan(plan), ensure_ascii=False, indent=2))
    else:
        print("网盘：%s｜引擎：%s｜账号：%s｜目录：%s" % (plan["drive_name"], plan["engine"], plan["tier"], plan["target"]))
        for step in plan["steps"]:
            print("  - %s" % step.get("note", ""))
        for warn in plan.get("warnings", []):
            print("  ⚠️ %s" % warn)
        if plan["missing"]:
            print("缺少依赖：")
            for item in plan["missing"]:
                print("  - %s" % item)
            print("安装/配置说明：%s" % plan["reference"])
    # 预演本身不执行外部命令，缺依赖也先把计划完整展示出来；实际下载才拦截。
    if plan["missing"] and not args.dry_run and not args.force:
        return 2
    if args.dry_run:
        if not getattr(args, "json", False):
            Path(plan["target"]).mkdir(parents=True, exist_ok=True)
            run_plan(plan, timeout=cfg.get("http", {}).get("timeout", 0), dry_run=True)
            print("DRY-RUN 完成：未执行实际下载（去掉 --dry-run 执行）")
        return 0
    Path(plan["target"]).mkdir(parents=True, exist_ok=True)
    log_line("TASK drive=%s engine=%s tier=%s target=%s url=%s" % (plan["drive"], plan["engine"], plan["tier"], plan["target"], args.url))
    rc = run_plan(plan, timeout=cfg.get("http", {}).get("timeout", 0), dry_run=False)
    if rc == 0:
        print("✅ 下载完成：%s" % plan["target"])
    return rc


def cmd_dirs(args):
    cfg = load_config()
    print("默认根目录：%s" % default_root(cfg))
    print("示例任务目录：%s" % task_dir(cfg, "百度网盘", "https://pan.baidu.com/s/1abcd"))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="pan", description="多网盘统一下载入口（免费账号默认）")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("doctor", help="检查环境与依赖")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)

    sub.add_parser("init", help="创建配置文件").add_argument("--force", action="store_true")

    sub.add_parser("show", help="显示配置（凭据打码）").set_defaults(func=cmd_show)

    p_detect = sub.add_parser("detect", help="识别链接属于哪个网盘")
    p_detect.add_argument("url")
    p_detect.set_defaults(func=cmd_detect)

    p_set = sub.add_parser("set", help="修改全局配置")
    p_set.add_argument("--root")
    p_set.add_argument("--tier", choices=["free", "vip", "auto"])
    p_set.add_argument("--engine-name")
    p_set.add_argument("--engine")
    p_set.add_argument("--alist-url")
    p_set.add_argument("--alist-user")
    p_set.add_argument("--alist-password", help=argparse.SUPPRESS)
    p_set.add_argument("--alist-password-stdin", action="store_true", help="从 stdin 读取 AList 密码并存入系统凭据库")
    p_set.add_argument("--rclone-remote")
    p_set.add_argument("--webdav-url")
    p_set.add_argument("--webdav-user")
    p_set.add_argument("--webdav-password", help=argparse.SUPPRESS)
    p_set.add_argument("--webdav-password-stdin", action="store_true", help="从 stdin 读取 WebDAV 密码并存入系统凭据库")
    p_set.set_defaults(func=cmd_set)

    p_sd = sub.add_parser("set-drive", help="修改单个网盘配置")
    p_sd.add_argument("drive")
    p_sd.add_argument("--tier", choices=["free", "vip", "auto"])
    p_sd.add_argument("--account-tier", choices=["free", "vip"])
    p_sd.add_argument("--tier-detector")
    p_sd.add_argument("--cookie-file")
    p_sd.add_argument("--credential-ref", help="绑定现有 credential:/keychain: 名称，不会打印密码")
    p_sd.add_argument("--credential-stdin", action="store_true", help="从 stdin 读取本网盘密码并存入系统凭据库")
    p_sd.add_argument("--engine-command")
    p_sd.add_argument("--save-path")
    p_sd.set_defaults(func=cmd_set_drive)

    p_secret = sub.add_parser("secret", help="安全保存、检查、删除或迁移凭据")
    secret_sub = p_secret.add_subparsers(dest="secret_cmd")
    ps = secret_sub.add_parser("set", help="把密码写入系统凭据库")
    ps.add_argument("name")
    ps.add_argument("--stdin", action="store_true", help="从 stdin 读取，适合脚本/agent")
    ps.set_defaults(func=cmd_secret_set)
    pc = secret_sub.add_parser("check", help="检查指定凭据是否存在")
    pc.add_argument("name", nargs="?")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_secret_check)
    pl = secret_sub.add_parser("list", help="列出配置引用的凭据状态")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_secret_list)
    pd = secret_sub.add_parser("delete", help="从系统凭据库删除指定凭据")
    pd.add_argument("name")
    pd.set_defaults(func=cmd_secret_delete)
    pm = secret_sub.add_parser("migrate", help="把旧配置里的已知明文凭据迁入系统凭据库")
    pm.set_defaults(func=cmd_secret_migrate)

    p_login = sub.add_parser("login", help="查看某网盘的登录/授权步骤")
    p_login.add_argument("drive")
    p_login.set_defaults(func=cmd_login)

    p_get = sub.add_parser("get", help="下载分享链接或直链")
    p_get.add_argument("url")
    p_get.add_argument("--pwd", help="分享提取码")
    p_get.add_argument("--to", help="指定下载目录")
    p_get.add_argument("--engine")
    p_get.add_argument("--tier", choices=["free", "vip", "auto"])
    p_get.add_argument("--path", help="AList 中已挂载的路径")
    p_get.add_argument("--remote", help="下载到已登记的远程设备（remote add 创建）")
    p_get.add_argument("--dry-run", action="store_true", help="只打印计划，不实际下载")
    p_get.add_argument("--force", action="store_true", help="依赖缺失时也尝试执行")
    p_get.add_argument("--json", action="store_true", help="给 agent 输出无凭据 JSON")
    p_get.set_defaults(func=cmd_get)

    p_remote = sub.add_parser("remote", help="管理 NAS、飞牛、群晖、私有云盘等远程设备")
    remote_sub = p_remote.add_subparsers(dest="remote_cmd")
    ra = remote_sub.add_parser("add", help="登记或修改远程设备（不保存明文密码）")
    ra.add_argument("name")
    ra.add_argument("--kind", choices=REMOTE_KINDS)
    ra.add_argument("--host")
    ra.add_argument("--port")
    ra.add_argument("--user")
    ra.add_argument("--root", help="远程下载根目录；mount 类型填本机挂载路径")
    ra.add_argument("--remote-name", help="rclone 配置里的 remote 名，例如 nas")
    ra.add_argument("--python", default=None, help="SSH 远程 Python 命令，默认 python3")
    ra.add_argument("--deploy-dir", help="SSH 远程技能目录，默认 .pan-downloader")
    ra.add_argument("--description")
    ra.add_argument("--credential-ref", help="已有系统凭据引用；只保存引用，不保存明文")
    ra.add_argument("--credential-stdin", action="store_true", help="从 stdin 读取远程凭据并存系统凭据库")
    ra.set_defaults(func=cmd_remote_add)

    rl = remote_sub.add_parser("list", help="列出远程设备（不含密码）")
    rl.add_argument("--json", action="store_true")
    rl.set_defaults(func=cmd_remote_list)

    rr = remote_sub.add_parser("remove", help="删除远程设备配置（不删除下载文件）")
    rr.add_argument("name")
    rr.set_defaults(func=cmd_remote_remove)

    rc = remote_sub.add_parser("check", help="检查远程配置；可选 --probe 联网探测")
    rc.add_argument("name")
    rc.add_argument("--probe", action="store_true")
    rc.add_argument("--json", action="store_true")
    rc.set_defaults(func=cmd_remote_check)

    rd = remote_sub.add_parser("deploy", help="把无凭据技能包部署到 SSH 设备")
    rd.add_argument("name")
    rd.add_argument("--dry-run", action="store_true")
    rd.add_argument("--json", action="store_true", help="输出打码后的部署计划，不执行上传")
    rd.set_defaults(func=cmd_remote_deploy)

    rg = remote_sub.add_parser("get", help="从分享链接下载到指定远程设备")
    rg.add_argument("name")
    rg.add_argument("url")
    rg.add_argument("--pwd", help="分享提取码")
    rg.add_argument("--to", help="覆盖远程目标目录")
    rg.add_argument("--engine")
    rg.add_argument("--tier", choices=["free", "vip", "auto"])
    rg.add_argument("--path", help="AList 中已挂载的路径")
    rg.add_argument("--dry-run", action="store_true", help="只打印计划，不实际下载")
    rg.add_argument("--force", action="store_true", help="依赖缺失时也尝试执行")
    rg.add_argument("--json", action="store_true", help="给 agent 输出无凭据 JSON")
    rg.set_defaults(func=cmd_remote_get)

    sub.add_parser("dirs", help="查看默认下载目录").set_defaults(func=cmd_dirs)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
