@echo off
setlocal
title Piruleta Studio 0.8.3
cd /d "%~dp0"
if exist "C:\Python313\pythonw.exe" (
    start "Piruleta Studio 0.8.3" "C:\Python313\pythonw.exe" -B -E "%~dp0launcher.py"
    exit /b
)
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "Piruleta Studio 0.8.3" pythonw.exe -B -E "%~dp0launcher.py"
    exit /b
)
python -B -E "%~dp0launcher.py"
if errorlevel 1 pause