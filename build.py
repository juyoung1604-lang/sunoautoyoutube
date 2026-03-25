#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_NAME = "SunoUploader"


def current_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform


def data_separator(target: str) -> str:
    return ";" if target == "windows" else ":"


def run_command(cmd: list[str], *, dry_run: bool = False) -> None:
    print("$", " ".join(shlex.quote(part) for part in cmd))
    if dry_run:
        return
    subprocess.run(cmd, cwd=ROOT, check=True)


def require_native_build(target: str, *, dry_run: bool = False) -> None:
    platform_name = current_platform()
    if target == platform_name or dry_run:
        return
    raise SystemExit(
        f"{target} 빌드는 {platform_name}에서 직접 만들 수 없습니다. "
        "PyInstaller는 Windows/macOS 크로스컴파일을 지원하지 않습니다."
    )


def remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def ensure_windows_package(*, dry_run: bool = False) -> None:
    windows_dist = ROOT / "dist" / "windows"
    raw_exe = windows_dist / f"{APP_NAME}.exe"
    package_dir = windows_dist / APP_NAME
    readme_src = ROOT / "packaging" / "windows" / "README-windows.txt"

    if dry_run:
        print(f"Would package {raw_exe} -> {package_dir}")
        return

    if not raw_exe.exists():
        raise SystemExit(f"빌드 결과가 없습니다: {raw_exe}")

    remove_path(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(raw_exe, package_dir / raw_exe.name)
    shutil.copy2(ROOT / ".env.example", package_dir / ".env.example")
    shutil.copy2(readme_src, package_dir / "README-windows.txt")


def build_windows(*, dry_run: bool = False) -> None:
    require_native_build("windows", dry_run=dry_run)

    windows_dist = ROOT / "dist" / "windows"
    build_dir = ROOT / "build" / "windows"
    specs_dir = build_dir / "spec"

    if not dry_run:
        windows_dist.mkdir(parents=True, exist_ok=True)
        build_dir.mkdir(parents=True, exist_ok=True)
        specs_dir.mkdir(parents=True, exist_ok=True)
        remove_path(windows_dist / APP_NAME)
        remove_path(windows_dist / f"{APP_NAME}.exe")

    sep = data_separator("windows")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(windows_dist),
        "--workpath",
        str(build_dir / "pyinstaller"),
        "--specpath",
        str(specs_dir),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{ROOT / 'templates'}{sep}templates",
        "--hidden-import",
        "anthropic",
        "--hidden-import",
        "groq",
        "--collect-submodules",
        "google",
        "--collect-submodules",
        "googleapiclient",
        "--collect-submodules",
        "google_auth_oauthlib",
        "--collect-submodules",
        "google.generativeai",
        "--collect-submodules",
        "google.ai.generativelanguage",
        "--collect-submodules",
        "google.genai",
        str(ROOT / "suno_web_app.py"),
    ]
    run_command(cmd, dry_run=dry_run)
    ensure_windows_package(dry_run=dry_run)


def build_macos(*, dry_run: bool = False) -> None:
    require_native_build("macos", dry_run=dry_run)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(ROOT / "SunoUploader.spec"),
    ]
    run_command(cmd, dry_run=dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SunoUploader packaging helper")
    parser.add_argument("target", choices=["windows", "macos"], help="빌드 대상 플랫폼")
    parser.add_argument("--dry-run", action="store_true", help="실행 대신 빌드 명령만 출력")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.target == "windows":
        build_windows(dry_run=args.dry_run)
    else:
        build_macos(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
