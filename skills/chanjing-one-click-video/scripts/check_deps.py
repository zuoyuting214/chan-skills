#!/usr/bin/env python3
"""
依赖检查脚本 — 在运行 chanjing-one-click-video 前验证所有前置条件。

用法:
  python scripts/check_deps.py
  python scripts/check_deps.py --quiet   # 只在出错时输出

退出码:
  0 全部通过
  1 有缺失项（已打印具体原因）
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _ok(msg: str, quiet: bool) -> None:
    if not quiet:
        print(f"  \033[32m✓\033[0m  {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m  {msg}")


def check_python(quiet: bool) -> bool:
    v = sys.version_info
    if v >= (3, 9):
        _ok(f"Python {v.major}.{v.minor}.{v.micro}", quiet)
        return True
    _fail(f"Python >= 3.9 required, got {v.major}.{v.minor}.{v.micro}")
    return False


def check_ffmpeg(quiet: bool) -> bool:
    ok = True
    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        if path:
            try:
                r = subprocess.run([binary, "-version"], capture_output=True, timeout=5)
                version_line = r.stdout.decode().splitlines()[0] if r.stdout else binary
                _ok(f"{binary}: {version_line[:60]}", quiet)
            except Exception:
                _ok(binary, quiet)
        else:
            _fail(
                f"{binary} not found in PATH. Install via:\n"
                "      macOS:  brew install ffmpeg\n"
                "      Ubuntu: sudo apt install ffmpeg"
            )
            ok = False
    return ok


def check_chan_skills(quiet: bool) -> bool:
    # 优先环境变量，否则从本文件位置自动推导（scripts/ → skill/ → skills/）
    d = os.environ.get("CHAN_SKILLS_DIR", "").strip()
    if d:
        p = Path(d)
    else:
        p = Path(__file__).resolve().parent.parent.parent

    if not p.is_dir():
        _fail(f"chan-skills/skills 目录不存在: {p}\n"
              "      如需手动指定：export CHAN_SKILLS_DIR=/path/to/chan-skills/skills")
        return False

    required_skills = [
        "chanjing-video-compose",
        "chanjing-tts",
        "chanjing-ai-creation",
        "chanjing-credentials-guard",
    ]
    missing = [s for s in required_skills if not (p / s).is_dir()]
    if missing:
        _fail(
            f"chan-skills 缺少子 skill: {', '.join(missing)}\n"
            f"      请确认已 clone 完整的 chan-skills 仓库，当前路径: {p}"
        )
        return False
    _ok(f"chan-skills: {p}", quiet)
    return True


def check_deerapi(quiet: bool) -> bool:
    key = os.environ.get("DEERAPI_API_KEY", "").strip()
    if not key:
        _fail(
            "DEERAPI_API_KEY not set (needed for LLM script/storyboard generation).\n"
            "      export DEERAPI_API_KEY=sk-..."
        )
        return False
    masked = key[:8] + "..." + key[-4:]
    _ok(f"DEERAPI_API_KEY: {masked}", quiet)
    return True


def check_chanjing_credentials(quiet: bool) -> bool:
    config_dir = Path(
        os.environ.get("CHANJING_CONFIG_DIR", Path.home() / ".chanjing")
    )
    creds_path = config_dir / "credentials.json"
    if not creds_path.exists():
        _fail(
            f"Chanjing credentials not found: {creds_path}\n"
            "      Run chanjing-credentials-guard or create the file manually:\n"
            '      {"app_id": "...", "secret_key": "..."}'
        )
        return False
    try:
        creds = json.loads(creds_path.read_text())
        if not creds.get("app_id") or not creds.get("secret_key"):
            _fail(f"{creds_path}: missing app_id or secret_key fields")
            return False
    except Exception as exc:
        _fail(f"{creds_path}: invalid JSON — {exc}")
        return False
    _ok(f"Chanjing credentials: {creds_path} (app_id={creds['app_id'][:8]}...)", quiet)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Check chanjing-one-click-video dependencies")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only print failures")
    args = parser.parse_args()

    if not args.quiet:
        print("\nchanjing-one-click-video — dependency check\n")

    checks = [
        check_python(args.quiet),
        check_ffmpeg(args.quiet),
        check_chan_skills(args.quiet),
        check_deerapi(args.quiet),
        check_chanjing_credentials(args.quiet),
    ]

    passed = sum(checks)
    total = len(checks)

    if not args.quiet:
        print()

    if all(checks):
        print(f"\033[32m{passed}/{total} checks passed — ready to run.\033[0m\n")
        sys.exit(0)
    else:
        failed = total - passed
        print(f"\033[31m{failed}/{total} checks failed — fix the issues above before running.\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
