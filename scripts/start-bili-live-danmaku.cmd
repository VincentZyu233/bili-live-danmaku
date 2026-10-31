@echo off
setlocal
title Bili Live Danmaku - 6161
cd /d "%~dp0.."

curl.exe -fsS --max-time 2 "http://127.0.0.1:6161/api/config" >nul 2>&1
if not errorlevel 1 (
    echo Bili Live Danmaku is already running.
    start "" "http://127.0.0.1:6161/admin"
    exit /b 0
)

where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv was not found in PATH.
    echo Install uv or add it to PATH, then try again.
    pause
    exit /b 1
)

echo Starting Bili Live Danmaku on http://127.0.0.1:6161/admin
uv run bili-live-danmaku
if errorlevel 1 (
    echo [ERROR] Bili Live Danmaku exited with an error.
    pause
)
