@echo off
cd /d "%~dp0"
if exist "portable\Piruleta Studio 0.7\Piruleta Studio.exe" (
    start "" "portable\Piruleta Studio 0.7\Piruleta Studio.exe"
    exit /b
)
python app.py
if errorlevel 1 pause
