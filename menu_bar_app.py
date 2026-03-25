#!/usr/bin/env python3
import fcntl
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import json
import urllib.request
import urllib.error
from pathlib import Path

# 1. 경로 설정 및 venv 라이브러리 강제 주입
PROJECT_DIR = Path(__file__).resolve().parent
VENV_LIB = list(PROJECT_DIR.glob("venv/lib/python3.*/site-packages"))
if VENV_LIB:
    sys.path.insert(0, str(VENV_LIB[0]))

import rumps
from runtime_paths import get_app_data_dir

# 기본 설정
PYTHON = PROJECT_DIR / "venv" / "bin" / "python"
APP_PY = PROJECT_DIR / "suno_web_app.py"
PORT = 5001
INSTALL_AUTOSTART = PROJECT_DIR / "scripts" / "install-menu-bar-autostart.sh"
UNINSTALL_AUTOSTART = PROJECT_DIR / "scripts" / "uninstall-menu-bar-autostart.sh"
LAUNCH_AGENT_LABEL = "com.richard.sunouploader.menubar"
LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
LOCK_FILE = get_app_data_dir() / "menu_bar.lock"
LOCK_HANDLE = None

def get_server_info():
    """서버 API를 통해 현재 상태 정보를 가져옵니다."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/server/info", timeout=0.8) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

def acquire_single_instance():
    global LOCK_HANDLE
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_HANDLE = LOCK_FILE.open("a+", encoding="utf-8")
    try:
        fcntl.flock(LOCK_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    LOCK_HANDLE.seek(0)
    LOCK_HANDLE.truncate()
    LOCK_HANDLE.write(str(os.getpid()))
    LOCK_HANDLE.flush()
    return True

def auto_start_enabled():
    return LAUNCH_AGENT_PATH.exists()

def run_helper_script(script_path: Path):
    if not script_path.exists():
        return False, f"스크립트를 찾을 수 없습니다: {script_path.name}"
    result = subprocess.run(["/bin/bash", str(script_path)], cwd=str(PROJECT_DIR), capture_output=True, text=True)
    message = (result.stdout or result.stderr).strip()
    return result.returncode == 0, message

class SunoMenuBarApp(rumps.App):
    def __init__(self):
        super(SunoMenuBarApp, self).__init__("Suno", quit_button=None)

        self.status_item = rumps.MenuItem("상태 확인 중...", callback=None)
        self.auto_start_item = rumps.MenuItem("로그인 자동 실행 켜기", callback=self.toggle_auto_start)
        
        self.menu = [
            self.status_item,
            None,
            rumps.MenuItem("🌐 웹 UI 열기", callback=self.open_ui),
            rumps.MenuItem("▶ 서버 시작", callback=self.start_server_cmd),
            rumps.MenuItem("⏹ 서버 중지", callback=self.stop_server_cmd),
            self.auto_start_item,
            None,
            rumps.MenuItem("종료", callback=self.quit_app),
        ]
        print("Menu Bar App Initialized.")
        self.update_status()
        # 서버가 꺼져 있으면 자동 시작
        threading.Thread(target=self._auto_start, daemon=True).start()

    def _wait_and_open_browser(self):
        """서버가 준비될 때까지 기다렸다가 브라우저를 연다."""
        for _ in range(30):
            time.sleep(0.5)
            if get_server_info():
                webbrowser.open(f"http://127.0.0.1:{PORT}")
                self.update_status()
                break

    def _auto_start(self):
        """앱 실행 시 서버가 꺼져 있으면 자동으로 시작하고 브라우저를 연다."""
        time.sleep(0.8)
        if get_server_info():
            webbrowser.open(f"http://127.0.0.1:{PORT}")
            return
        # 서버 시작
        python_bin = str(PYTHON) if PYTHON.exists() else "python3"
        try:
            subprocess.Popen(
                [python_bin, str(APP_PY), "--no-browser"],
                cwd=str(PROJECT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            return
        self._wait_and_open_browser()

    @rumps.timer(4)
    def update_status(self, _=None):
        info = get_server_info()
        if info:
            self.title = "🎵 Suno"
            uptime = info.get('uptime', '')
            self.status_item.title = f"✅ 서버 실행 중 ({uptime})"
        else:
            self.title = "⏸ Suno"
            self.status_item.title = "❌ 서버 중지됨"
        self.auto_start_item.title = "로그인 자동 실행 끄기" if auto_start_enabled() else "로그인 자동 실행 켜기"

    def open_ui(self, _):
        webbrowser.open(f"http://127.0.0.1:{PORT}")

    def start_server_cmd(self, _):
        if get_server_info():
            rumps.notification("Suno Uploader", "알림", "서버가 이미 실행 중입니다.")
            return
        
        python_bin = str(PYTHON) if PYTHON.exists() else "python3"
        if not APP_PY.exists():
            rumps.alert("실행 오류", f"서버 파일이 없습니다:\n{APP_PY}")
            return

        try:
            subprocess.Popen(
                [python_bin, str(APP_PY), "--no-browser"],
                cwd=str(PROJECT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            rumps.notification("Suno Uploader", "알림", "서버를 시작했습니다.")
            # 서버 준비 후 브라우저 오픈
            threading.Thread(target=self._wait_and_open_browser, daemon=True).start()
        except Exception as e:
            rumps.alert("실행 오류", f"서버 시작 실패: {str(e)}")

    def stop_server_cmd(self, _):
        # 1. API를 통한 종료 시도
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/server/shutdown", method="POST")
            with urllib.request.urlopen(req, timeout=1):
                pass
            rumps.notification("Suno Uploader", "알림", "서버를 안전하게 종료했습니다.")
        except Exception:
            # 2. 실패 시 강제 종료
            subprocess.run(["pkill", "-f", str(APP_PY)], check=False)
            rumps.notification("Suno Uploader", "알림", "서버 프로세스를 중지했습니다.")
        
        time.sleep(1)
        self.update_status()

    def toggle_auto_start(self, _):
        enabling = not auto_start_enabled()
        script_path = INSTALL_AUTOSTART if enabling else UNINSTALL_AUTOSTART
        ok, message = run_helper_script(script_path)
        if ok:
            text = "로그인 시 메뉴바 자동 실행을 켰습니다." if enabling else "로그인 자동 실행을 해제했습니다."
            rumps.notification("Suno Uploader", "자동 실행", text)
        else:
            rumps.alert("자동 실행 오류", message or "설정 중 오류가 발생했습니다.")
        self.update_status()

    def quit_app(self, _):
        # 서버도 함께 종료
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/server/shutdown", method="POST")
            with urllib.request.urlopen(req, timeout=1):
                pass
        except Exception:
            subprocess.run(["pkill", "-f", str(APP_PY)], check=False)
        rumps.quit_application()

if __name__ == "__main__":
    if not acquire_single_instance():
        print("Menu bar app is already running.")
        raise SystemExit(0)
    app = SunoMenuBarApp()
    app.run()
