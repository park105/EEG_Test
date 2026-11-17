@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    python -m venv .venv
  ) else (
    py -3 -m venv .venv
  )
)
if not exist ".venv\Scripts\python.exe" goto failed
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, scipy, pandas, sklearn, pylsl; from pydantic import model_validator; pylsl.library_version()" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt pylsl
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" launch_lab.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Python 3.12 또는 설치/실행 오류를 확인해 주세요.
pause
exit /b 1

