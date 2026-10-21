@echo off
rem SYNCAMP telepítése: Python-környezet, csomagok, MilkDrop-látványok.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" setup_milkdrop.py
echo.
echo Kesz! Inditas: Syncamp.bat
pause
