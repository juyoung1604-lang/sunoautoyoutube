# -*- mode: python ; coding: utf-8 -*-
"""
SunoUploader macOS 빌드 스펙
결과: dist/SunoUploader.app
  - SunoUploader: 메뉴바 앱 (메인)
  - SunoServer:   웹 서버 (서브 프로세스)
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

# ─── 웹 서버 (SunoServer) ───────────────────────────────────────────
a_srv = Analysis(
    [str(ROOT / 'suno_web_app.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'templates'), 'templates'),
    ],
    hiddenimports=[
        'flask', 'werkzeug', 'jinja2', 'click',
        'pydub', 'PIL', 'openai', 'google.oauth2',
        'google.auth', 'googleapiclient',
        *collect_submodules('google'),
        *collect_submodules('googleapiclient'),
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz_srv = PYZ(a_srv.pure)
exe_srv = EXE(
    pyz_srv,
    a_srv.scripts,
    a_srv.binaries,
    a_srv.datas,
    [],
    name='SunoServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    onefile=True,
)

# ─── 메뉴바 앱 (SunoUploader) ──────────────────────────────────────
a_app = Analysis(
    [str(ROOT / 'menu_bar_app.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=['rumps', 'runtime_paths', 'settings_store'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz_app = PYZ(a_app.pure)
exe_app = EXE(
    pyz_app,
    a_app.scripts,
    a_app.binaries,
    a_app.datas,
    [],
    name='SunoUploader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    onefile=True,
)

# ─── .app 번들 ──────────────────────────────────────────────────────
app = BUNDLE(
    exe_app,
    exe_srv,
    name='SunoUploader.app',
    icon=str(ROOT / 'SunoUploader.app' / 'Contents' / 'Resources' / 'applet.icns'),
    bundle_identifier='com.richard.sunouploader',
    info_plist={
        'CFBundleName': 'SunoUploader',
        'CFBundleDisplayName': 'Suno Uploader',
        'CFBundleShortVersionString': '2.0',
        'CFBundleVersion': '2.0',
        'LSUIElement': True,          # Dock 아이콘 숨김 (메뉴바 전용)
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'NSAppleEventsUsageDescription': 'Suno Uploader needs Automation access.',
    },
)
