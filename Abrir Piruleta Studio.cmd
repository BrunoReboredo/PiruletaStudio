@echo off
setlocal
title Piruleta Studio 0.8.5
cd /d "%~dp0"
if exist "%~dp0portable\Piruleta Studio 0.8.5 Velocidad\Piruleta Studio.exe" (
    start "Piruleta Studio 0.8.5" "%~dp0portable\Piruleta Studio 0.8.5 Velocidad\Piruleta Studio.exe"
    exit /b
)
if exist "C:\Python313\pythonw.exe" (
    start "Piruleta Studio 0.8.5" "C:\Python313\pythonw.exe" -B -E "%~dp0launcher.py"
    exit /b
)
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "Piruleta Studio 0.8.5" pythonw.exe -B -E "%~dp0launcher.py"
    exit /b
)
python -B -E "%~dp0launcher.py"
if errorlevel 1 pause