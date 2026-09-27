#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pan-downloader 离线自测：不联网、不下载，只验证识别、配置和命令拼装。"""
import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="pan-selftest-"))
os.environ["PAN_CONFIG"] = str(TMP / "config.json")
os.environ["PAN_LOG"] = str(TMP / "pan.log")
os.environ["PAN_STATE_DIR"] = str(TMP / "state")


def load_module():
    spec = importlib.util.spec_from_file_location("pan", HERE / "pan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def capture_call(func, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = func(*args, **kwargs)
    return rc, out.getvalue()


def main():
    pan = load_module()
    checks = 0

    # 1) 链接识别：首批 + 常用扩展网盘 + 自定义扩展
    cases = [
        ("https://pan.baidu.com/s/1abcdEFG", "baidu"),
        ("https://www.aliyundrive.com/s/abc123", "aliyun"),
        ("https://pan.quark.cn/s/abc123", "quark"),
        ("https://cloud.189.cn/t/abc123", "tianyi"),
        ("https://pan.xunlei.com/s/abc123", "thunder"),
        ("https://115.com/s/abc123", "115"),
        ("https://www.123pan.com/s/abc123", "123pan"),
        ("https://yun.139.com/shareweb/#/w/i/abc123", "139yun"),
        ("https://wopan.wo.cn/s/abc123", "wopan"),
        ("https://drive.uc.cn/s/abc123", "uc"),
        ("https://mypikpak.com/s/abc123", "pikpak"),
        ("https://www.jianguoyun.com/p/abc123", "jianguoyun"),
        ("https://1drv.ms/u/s!abc123", "onedrive"),
        ("https://drive.google.com/file/d/abc123/view", "googledrive"),
        ("https://www.dropbox.com/s/abc123/file.zip", "dropbox"),
        ("https://share.weiyun.com/abc123", "weiyun"),
        ("https://wwx.lanzoue.com/abc123", "lanzou"),
        ("https://pan.wukong.com/s/abc123", "wukong"),
        ("https://pan.doubao.com/s/abc123", "doubao"),
        ("https://mega.nz/file/abc123", "mega"),
        ("https://terabox.com/s/abc123", "terabox"),
        ("https://u.pcloud.link/publink/show?code=abc", "pcloud"),
        ("https://drive.proton.me/urls/abc123", "protondrive"),
        ("https://disk.yandex.com/d/abc123", "yandexdisk"),
        ("https://www.mediafire.com/file/abc123/file.zip", "mediafire"),
        ("https://trainbit.com/files/abc123/file.zip", "trainbit"),
        ("https://guangyapan.com/s/abc123", "guangyapan"),
        ("https://feijipan.com/s/abc123", "feijipan"),
        ("https://shandianpan.com/s/abc123", "shandian"),
        ("https://www.ctfile.com/f/abc123", "chengtong"),
        ("https://example.com/file.zip", "direct"),
    ]
    for url, expected in cases:
        got, spec = pan.detect_drive(url)
        assert got == expected, "detect %s -> %s (期望 %s)" % (url, got, expected)
        assert spec.get("name"), "drive %s 缺少 name" % got
        checks += 1

    # 2) 未知非 http 链接
    assert pan.detect_drive("ftp://x")[0] == "", "ftp 不应被识别"
    checks += 1

    # 3) 文件名与 slug 清洗
    assert pan.sanitize('a/b:c*?"<>|') == "a_b_c" + "_" * 6
    assert pan.filename_from_url("https://x.com/%E6%96%87%E4%BB%B6.zip") == "文件.zip"
    assert pan.url_slug("https://pan.quark.cn/s/abc123/") == "abc123"
    checks += 3

    # 4) 凭据打码：不打印参数值，也不把密码写进 config
    masked = pan.mask_value("config", {"cookie": "abc", "token": "xyz", "tier": "free"})
    assert masked == {"cookie": "***", "token": "***", "tier": "free"}, masked
    masked_argv = pan.mask_argv(["rclone", "--user", "me", "--password", "secret", "remote:path"])
    assert masked_argv == ["rclone", "--user", "***", "--password", "***", "remote:path"], masked_argv
    masked_inline = pan.mask_argv(["tool", "--token=abc", "--cookie", "xyz"])
    assert "abc" not in " ".join(masked_inline) and "xyz" not in " ".join(masked_inline), masked_inline
    masked_remote_command = pan.mask_argv(["ssh", "host", "pan.py get x --pwd 1234 --force"])
    assert "1234" not in masked_remote_command[-1], masked_remote_command
    checks += 4

    # 5) 默认目录可覆盖 + 任务目录命名
    cfg = pan.load_config()
    cfg["download_root"] = str(TMP / "下载")
    root = pan.default_root(cfg)
    assert root == TMP / "下载", root
    tdir = pan.task_dir(cfg, "百度网盘", "https://pan.baidu.com/s/1abc")
    assert tdir.parent == root / "百度网盘" and tdir.name.endswith("-1abc"), tdir
    checks += 2

    # 6) 直链 HTTP 计划：curl 断点续传
    plan = pan.build_plan("https://example.com/a/b.zip", cfg=cfg)
    assert plan["ok"] and plan["engine"] == "http"
    argv = plan["steps"][0]["argv"]
    assert argv[0] == "curl" and "-C" in argv and argv[-1].endswith("b.zip")
    checks += 1

    # 7) 百度分享计划（未装引擎时给缺失项和两步计划）
    p2 = pan.build_plan("https://pan.baidu.com/s/1abc", pwd="1234", cfg=cfg)
    assert p2["drive"] == "baidu" and p2["engine"] == "baidupcs"
    assert len(p2["steps"]) == 2 and p2["steps"][0]["argv"][1] == "transfer"
    assert "BaiduPCS-Go" in p2["missing"], p2["missing"]
    checks += 3

    # 8) 自定义引擎模板
    cfg2 = json.loads(json.dumps(cfg))
    cfg2["drives"]["quark"]["engine_command"] = "mytool get {url} --pwd {pwd} --out {dir}"
    p3 = pan.build_plan("https://pan.quark.cn/s/zzz", pwd="9x9", cfg=cfg2)
    assert p3["steps"][0]["engine"] == "custom"
    assert p3["steps"][0]["argv"][:3] == ["mytool", "get", "https://pan.quark.cn/s/zzz"]
    checks += 2

    # 9) WebDAV / 坚果云直链计划
    cfg_dav = json.loads(json.dumps(cfg))
    cfg_dav["engines"]["webdav_user"] = "me@example.com"
    cfg_dav["engines"]["webdav_password_ref"] = pan.keychain_ref("engine.webdav")
    original_keychain_get = pan.keychain_get
    pan.keychain_get = lambda name: "secret" if name == "engine.webdav" else ""
    p_dav = pan.build_plan("https://dav.jianguoyun.com/dav/%E6%96%87%E4%BB%B6.zip", cfg=cfg_dav)
    assert p_dav["engine"] == "webdav", p_dav
    dav_argv = p_dav["steps"][0]["argv"]
    assert p_dav["steps"][0]["engine"] == "webdav" and dav_argv[0] == "curl"
    assert "-C" in dav_argv and dav_argv[-1].startswith("https://dav.jianguoyun.com/dav/")
    assert "secret" not in " ".join(dav_argv), dav_argv
    assert p_dav["steps"][0].get("stdin") == 'user = "me@example.com:secret"\n'
    assert "secret" not in json.dumps(pan.public_plan(p_dav), ensure_ascii=False)
    pan.keychain_get = original_keychain_get
    checks += 5

    # 10) AList + rclone：目录递归复制，并自动补远端冒号
    fake_bin = TMP / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_rclone = fake_bin / "rclone"
    fake_rclone.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_rclone.chmod(0o755)
    cfg_rclone = json.loads(json.dumps(cfg))
    cfg_rclone["engines"]["alist_url"] = "http://127.0.0.1:5244"
    cfg_rclone["engines"]["rclone_remote"] = "alist"
    cfg_rclone["engines"]["rclone"] = str(fake_rclone)
    p_rclone = pan.build_plan("https://pan.quark.cn/s/zzz", cfg=cfg_rclone, engine="alist", path="/夸克网盘/目录")
    rclone_step = p_rclone["steps"][0]
    assert p_rclone["engine"] == "alist" and rclone_step["engine"] == "rclone", p_rclone
    assert Path(rclone_step["argv"][0]).name == "rclone", rclone_step
    assert "alist:/夸克网盘/目录" in rclone_step["argv"], rclone_step
    assert rclone_step["argv"][rclone_step["argv"].index("--transfers") + 1] == "1", rclone_step
    cfg_rclone["drives"]["quark"]["account_tier"] = "vip"
    p_rclone_vip = pan.build_plan("https://pan.quark.cn/s/zzz", cfg=cfg_rclone, engine="alist", path="/夸克网盘/目录")
    assert p_rclone_vip["tier"] == "vip", p_rclone_vip
    vip_argv = p_rclone_vip["steps"][0]["argv"]
    assert vip_argv[vip_argv.index("--transfers") + 1] == "4", p_rclone_vip
    checks += 5

    # 11) 配置保存/读取 + 600 权限
    pan.save_config(cfg, TMP / "config.json")
    path = pan.save_config(cfg2, TMP / "saved.json")
    assert path.exists() and json.loads(path.read_text(encoding="utf-8"))["drives"]["quark"]["engine_command"]
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)
    checks += 2

    # 12) dry-run 缺依赖也完整展示计划，不提前返回
    dry_args = type("Args", (), {
        "url": "https://pan.baidu.com/s/1abc", "pwd": "1234", "to": str(TMP / "dry"),
        "engine": None, "tier": None, "path": None, "dry_run": True, "force": False,
    })()
    rc, output = capture_call(pan.cmd_get, dry_args)
    assert rc == 0, (rc, output)
    assert "缺少依赖" in output and "DRY-RUN:" in output and "DRY-RUN 完成" in output, output
    checks += 3

    # 13) VIP 参数只影响并发，不做绕过
    cfg3 = json.loads(json.dumps(cfg))
    cfg3["http"]["max_connections_vip"] = 4
    p4 = pan.build_plan("https://example.com/x.bin", cfg=cfg3, engine="aria2", tier="vip")
    if p4["missing"]:
        assert p4["missing"] == ["aria2c"]
    else:
        argv = p4["steps"][0]["argv"]
        assert "-x" in argv and argv[argv.index("-x") + 1] == "4"
    checks += 1

    # 14) tier=auto：无探测器先按免费；账号记录/探测器给出 vip 时自动升为会员
    p_auto = pan.build_plan("https://example.com/auto.bin", cfg=cfg)
    assert p_auto["requested_tier"] == "auto" and p_auto["tier"] == "free", p_auto
    assert any("未自动识别" in w for w in p_auto["warnings"]), p_auto

    cfg_account = json.loads(json.dumps(cfg))
    cfg_account["drives"]["direct"]["account_tier"] = "vip"
    p_account = pan.build_plan("https://example.com/vip.bin", cfg=cfg_account)
    assert p_account["tier"] == "vip" and p_account["tier_source"] == "配置记录", p_account

    cfg_detector = json.loads(json.dumps(cfg))
    cfg_detector["drives"]["quark"]["tier_detector"] = "printf SVIP"
    p_detector = pan.build_plan("https://pan.quark.cn/s/vip", cfg=cfg_detector)
    assert p_detector["tier"] == "vip", p_detector
    assert "tier_detector" in p_detector["tier_source"], p_detector
    checks += 5

    # 15) 示例配置与内置默认值同步
    example_path = pan.SKILL_DIR / "config.example.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    assert example["version"] == 5, example["version"]
    assert set(example["drives"]) == set(pan.DEFAULT_CONFIG["drives"]), "config.example.json drives 不同步"
    assert set(example["engines"]) == set(pan.DEFAULT_CONFIG["engines"]), "config.example.json engines 不同步"
    assert "remotes" in example and "remote" in example, "config.example.json 缺少远程配置"
    checks += 4

    # 16) 每个内置网盘都同时具备配置项和说明文件
    all_cfg = pan.load_config()
    for key, spec in pan.DRIVES.items():
        assert key in all_cfg["drives"], "DEFAULT_CONFIG 缺少 drives.%s" % key
        ref = pan.SKILL_DIR / spec["reference"]
        assert ref.is_file(), "缺少说明文件 %s" % ref
        checks += 2

    # 17) Windows 路径与启动包装器
    win_paths = pan.platform_paths(
        "windows",
        env={"APPDATA": "/tmp/AppData/Roaming", "LOCALAPPDATA": "/tmp/AppData/Local", "HOME": "/tmp/home"},
        home="/tmp/home",
    )
    assert str(win_paths["config"]).endswith("pan-downloader/config.json"), win_paths
    assert str(win_paths["log"]).endswith("pan-downloader/logs/pan-downloader.log"), win_paths
    assert str(win_paths["download"]).endswith("Downloads/网盘下载"), win_paths
    assert (pan.SKILL_DIR / "scripts/pan.cmd").is_file(), "缺少 Windows CMD 包装器"
    assert (pan.SKILL_DIR / "scripts/pan.ps1").is_file(), "缺少 Windows PowerShell 包装器"
    checks += 5

    # 18) 跨平台凭据后端：模拟 Windows Credential Manager，不写真实系统
    original_store = pan._windows_credential_store
    original_get = pan._windows_credential_get
    original_delete = pan._windows_credential_delete
    original_backend = pan.credential_backend
    fake_vault = {}
    pan.credential_backend = lambda: "windows"
    pan._windows_credential_store = lambda name, value: fake_vault.__setitem__(name, value)
    pan._windows_credential_get = lambda name: fake_vault.get(name, "")
    pan._windows_credential_delete = lambda name: bool(fake_vault.pop(name, None))
    ref = pan.credential_store("remote.test", "secret-value")
    assert ref == "credential:remote.test", ref
    assert pan.credential_get(ref) == "secret-value", fake_vault
    assert fake_vault["remote.test"] == "secret-value"
    assert pan.credential_delete(ref) is True and not fake_vault
    pan._windows_credential_store = original_store
    pan._windows_credential_get = original_get
    pan._windows_credential_delete = original_delete
    pan.credential_backend = original_backend
    checks += 4

    # 19) 远程 SSH：计划在远程执行，不把远程密码放进 argv
    cfg_remote = json.loads(json.dumps(cfg))
    cfg_remote["remotes"] = {
        "nas": {"kind": "ssh", "host": "192.168.1.10", "user": "lis", "root": "/volume1"}
    }
    remote_profile = dict(cfg_remote["remotes"]["nas"], name="nas")
    remote_plan = pan.build_remote_plan(remote_profile, "https://pan.quark.cn/s/abc", pwd="1234", cfg=cfg_remote)
    assert remote_plan["ok"] and remote_plan["remote_kind"] == "ssh-execute", remote_plan
    ssh_argv = remote_plan["steps"][0]["argv"]
    assert ssh_argv[0] == "ssh" and "BatchMode=yes" in ssh_argv, ssh_argv
    assert "pan.py get" in ssh_argv[-1] and "/volume1" in ssh_argv[-1], ssh_argv
    assert "secret" not in json.dumps(pan.public_plan(remote_plan), ensure_ascii=False)
    assert "1234" not in json.dumps(pan.public_plan(remote_plan), ensure_ascii=False)
    checks += 4

    # 20) 远程落地：本机先下载，再用 rclone 上传到 WebDAV/SMB/S3 remote
    cfg_sink = json.loads(json.dumps(cfg))
    cfg_sink["engines"]["rclone"] = str(fake_rclone)
    cfg_sink["remotes"] = {
        "vault": {"kind": "webdav", "remote_name": "vault", "root": "/downloads"}
    }
    sink_profile = dict(cfg_sink["remotes"]["vault"], name="vault")
    sink_plan = pan.build_remote_plan(sink_profile, "https://example.com/a.zip", cfg=cfg_sink)
    assert sink_plan["ok"] and sink_plan["remote_kind"] == "rclone-upload", sink_plan
    assert sink_plan["staging"] and sink_plan["target"] == "vault:/downloads/%s" % pan.remote_task_name("vault", "https://example.com/a.zip"), sink_plan
    assert sink_plan["steps"][-1]["engine"] == "rclone", sink_plan
    assert sink_plan["steps"][-1]["argv"][0] == str(fake_rclone), sink_plan
    checks += 4

    # 21) 远程部署包不包含 config.json 或凭据目录
    archive = pan.create_remote_deploy_archive()
    try:
        names = []
        import tarfile
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        assert "scripts/pan.py" in names and "references/21-远程NAS与私有存储.md" in names, names
        assert not any(name.endswith("config.json") for name in names), names
        deploy_plan = pan.build_remote_deploy_plan(remote_profile, archive)
        assert deploy_plan["ok"] and len(deploy_plan["steps"]) == 3, deploy_plan
    finally:
        archive.unlink(missing_ok=True)
    checks += 3

    # 22) 远程说明文件存在
    assert (pan.SKILL_DIR / "references/21-远程NAS与私有存储.md").is_file()
    assert (pan.SKILL_DIR / "references/22-Windows配置.md").is_file()
    checks += 2

    print("SELF_TEST_OK checks=%d tmp=%s" % (checks, TMP))
    return 0


if __name__ == "__main__":
    sys.exit(main())
