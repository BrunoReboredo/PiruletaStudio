@echo off
setlocal
cd /d "%~dp0"
if exist "portable\Piruleta Studio 0.8.2\Piruleta Studio.exe" (
    start "" "portable\Piruleta Studio 0.8.2\Piruleta Studio.exe"
    exit /b
)
python -B launcher.py
if errorlevel 1 pause
