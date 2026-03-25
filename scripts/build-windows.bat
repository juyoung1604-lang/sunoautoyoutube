@echo off
setlocal

cd /d "%~dp0\.."

if exist "venv\Scripts\python.exe" (
  set "PYTHON_BIN=venv\Scripts\python.exe"
  "%PYTHON_BIN%" -m pip install -r requirements.txt pyinstaller
  "%PYTHON_BIN%" build.py windows
) else (
  py -3 -m pip install -r requirements.txt pyinstaller
  py -3 build.py windows
)
