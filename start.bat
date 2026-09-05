@echo off
chcp 65001 >nul 2>&1
title Cockpit Frontend

cd /d "%~dp0"

echo ========================================
echo   DesayMem Cockpit Frontend
echo ========================================
echo.

REM Check Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

REM Check .env
if not exist ".env" (
    echo [WARNING] .env not found. Creating from template...
    (
        echo LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        echo LLM_MODEL=qwen-plus
        echo LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
        echo PROXY_PORT=8767
    ) > .env
    echo [INFO] .env created. Please edit it with your DashScope API Key.
    echo.
    type .env
    echo.
    pause
    exit /b 0
)

REM Check if LLM_API_KEY is still placeholder
findstr "xxxxxxxx" .env >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [WARNING] LLM_API_KEY in .env is still placeholder!
    echo [INFO] Please edit .env with your real DashScope API Key.
    echo.
    pause
)

REM Install deps if needed
pip show fastapi >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing dependencies...
    pip install fastapi uvicorn httpx pydantic
)

REM Start LLM proxy in background
echo [INFO] Starting LLM proxy on port 8767...
start /min "LLM Proxy" python llm_proxy.py

REM Wait for proxy to start
timeout /t 3 /nobreak >nul

REM Open browser
echo [INFO] Opening browser...
start "" "index.html"

echo.
echo ========================================
echo   Frontend is running!
echo   - LLM Proxy: http://127.0.0.1:8767
echo   - Backend:   http://47.115.228.135/memory
echo ========================================
echo.
echo Press Ctrl+C to stop.
echo.
pause
