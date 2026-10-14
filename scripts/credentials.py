"""credentials.py — 只从系统凭据库读取凭据。

- macOS: security find-generic-password
- Linux: secret-tool
- Windows: CredentialManager PowerShell module（未安装时返回不可用）
本模块绝不把凭据写入 config.json、聊天或日志；也不从浏览器/页面抓取凭据。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class CredentialUnavailableError(RuntimeError):
    pass


@dataclass
class CredentialRef:
    """系统凭据库中的一条引用，只包含 name / account，不包含明文值。"""

    name: str
    account: Optional[str] = None
    service: Optional[str] = None


def parse_ref(ref: str) -> CredentialRef:
    """把 'name[:account]' 或 'name' 转成 CredentialRef。"""
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("credential ref 不能为空")
    parts = ref.split(":", 1)
    return CredentialRef(name=parts[0], account=parts[1] if len(parts) > 1 else None)


def _macos_read(ref: CredentialRef) -> str:
    security = shutil.which("security")
    if not security:
        raise CredentialUnavailableError("未找到 macOS security 命令")
    cmd = [security, "find-generic-password"]
    if ref.service:
        cmd += ["-s", ref.service]
    cmd += ["-a", ref.account or ref.name, "-w"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise CredentialUnavailableError("macOS security 读取超时") from None
    if out.returncode != 0:
        raise CredentialUnavailableError(
            f"系统凭据库未找到 '{ref.name}'（macOS Keychain）；请先用 security add-generic-password 或你的凭据库工具保存。"
        )
    value = out.stdout.rstrip("\n")
    # 不允许把空值当作有效凭据
    if not value:
        raise CredentialUnavailableError(f"凭据 '{ref.name}' 在系统凭据库中为空。")
    return value


def _linux_read(ref: CredentialRef) -> str:
    secret_tool = shutil.which("secret-tool")
    if not secret_tool:
        raise CredentialUnavailableError("未找到 secret-tool（需要安装 libsecret-tools）")
    if not ref.service:
        raise CredentialUnavailableError("Linux secret-tool 需要 service 字段；请用 --credential-service 或 Config.CredSets 配置")
    cmd = [secret_tool, "lookup", "service", ref.service, "account", ref.account or ref.name]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise CredentialUnavailableError("secret-tool 读取超时") from None
    if out.returncode != 0:
        raise CredentialUnavailableError(
            f"系统 secret-tool 未找到 '{ref.name}'；请先用 secret-tool store service/account 保存。"
        )
    value = out.stdout.rstrip("\n")
    if not value:
        raise CredentialUnavailableError(f"凭据 '{ref.name}' 在系统 secret-tool 中为空。")
    return value


def _windows_read(ref: CredentialRef) -> str:
    # Windows Credential Manager 需要一个可调用 Get-StoredCredential 的模块，
    # 本模块不自行解析/伪造 Cookie；没有该模块则明确不可用。
    ps = shutil.which("powershell")
    if not ps:
        raise CredentialUnavailableError("未找到 Windows PowerShell")
    script = f"""
$ErrorActionPreference='Stop'
Import-Module CredentialManager -ErrorAction Stop
$c = Get-StoredCredential -Target '{ref.account or ref.name}'
if (-not $c) {{ throw 'credential not found' }}
Write-Output $c.Password
"""
    try:
        out = subprocess.run([ps, "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise CredentialUnavailableError("Windows Credential Manager 读取超时") from None
    if out.returncode != 0:
        raise CredentialUnavailableError(
            f"Windows Credential Manager 未找到 '{ref.name}' 或未安装 CredentialManager 模块。"
        )
    value = out.stdout.rstrip("\n")
    if not value:
        raise CredentialUnavailableError(f"凭据 '{ref.name}' 在 Windows Credential Manager 中为空。")
    return value


def read_secret(ref: str, service: Optional[str] = None) -> str:
    """只从本机系统凭据库读取并返回明文；调用方必须确保不打印、不落盘、不上传。"""
    parsed = parse_ref(ref)
    if service:
        parsed.service = service
    system = os.environ.get("PAN_CRED_SYSTEM") or sys.platform
    value: Optional[str] = None
    if system == "darwin":
        value = _macos_read(parsed)
    elif system in ("win32", "cygwin"):
        value = _windows_read(parsed)
    elif system.startswith("linux"):
        value = _linux_read(parsed)
    else:
        raise CredentialUnavailableError(f"暂不支持凭据库平台: {system}")
    return value


def check_available(ref: Optional[str] = None, service: Optional[str] = None) -> bool:
    """检查凭据库是否可用（不读取具体值，不打印）。"""
    if ref:
        read_secret(ref, service=service)  # 若失败会抛异常
    return True


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="只读系统凭据库；绝不打印明文")
    ap.add_argument("--check", action="store_true", help="只检查可用性，不输出明文")
    ap.add_argument("--cookie-ref", help="credential ref，如 name 或 name:account")
    ap.add_argument("--service", help="服务名（Linux secret-tool 需要）")
    args = ap.parse_args()
    try:
        if args.check:
            check_available(args.cookie_ref, args.service)
            print("credentials-ok")
        else:
            # CLI 默认不打印明文；只打印是否存在
            check_available(args.cookie_ref, args.service)
            print("credential-exists")
    except Exception as e:  # noqa: BLE001
        print(f"credentials-error: {e}")
        raise SystemExit(2)
