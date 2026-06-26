@echo off
title Harel's - Alex AI Calling Agent
cd /d "%~dp0"

REM Real Google Calendar invites + Israel timezone for the webhook server.
set GCAL_ENABLED=true
set SLOT_IANA_TZ=Asia/Jerusalem
set SLOT_TZ_LABEL=Israel time

echo ===========================================================
echo   Harel's - Alex AI Calling Agent
echo   Starting: webhook (:8000), ngrok, dashboard (:8001)
echo ===========================================================
echo.

REM Public webhook server (Vapi calls back to this via ngrok).
start "Harel's Webhook :8000" /min cmd /k "python -m uvicorn alex.server:app --port 8000"

REM Public tunnel (uses your reserved ngrok domain already in .env).
start "Harel's ngrok" /min cmd /k "ngrok http 8000"

REM Private operator dashboard (NOT tunnelled).
start "Harel's Dashboard :8001" /min cmd /k "python -m uvicorn alex.dashboard:app --port 8001"

echo Waiting for the dashboard to come up, then opening the browser...
timeout /t 6 /nobreak >nul
start "" http://localhost:8001

echo.
echo Three minimized windows are now running (webhook, ngrok, dashboard).
echo Close them to stop the services. This window can be closed.
timeout /t 3 /nobreak >nul
exit
