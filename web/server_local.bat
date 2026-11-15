@echo off
title Local Web Server ICT Terminal Pro
cd /d "%~dp0"
echo ===================================================
echo   ICT TERMINAL PRO - LOCAL WEB SERVER
echo   Menjalankan server di http://localhost:8080
echo ===================================================
start "" "http://localhost:8080/index.html"
python -m http.server 8080
pause
