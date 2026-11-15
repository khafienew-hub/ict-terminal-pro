@echo off
title Push ICT Terminal Pro ke GitHub
cd /d "%~dp0.."

echo ==========================================================
echo   PUSH KE GITHUB: https://github.com/khafienew-hub/ict-terminal-pro
echo ==========================================================
echo.

if not exist ".git" (
    echo [1/5] Inisialisasi Git...
    git init
) else (
    echo [1/5] Git sudah diinisialisasi.
)

echo [2/5] Menambahkan remote GitHub...
git remote remove origin 2>nul
git remote add origin https://github.com/khafienew-hub/ict-terminal-pro.git

echo [3/5] Memilih branch main...
git branch -M main

echo [4/5] Menyiapkan file web dan source code...
git add web/
git add README.md
git add requirements.txt
git add main.py
git add ictterm/
git add reports/*.png
git add assets/

echo [5/5] Melakukan commit dan push...
git commit -m "feat: rilis web promosi dan aplikasi ICT Terminal Pro v2.0.4"
git push -u origin main

echo.
echo ==========================================================
echo   SELESAI!
echo   Buka: https://github.com/khafienew-hub/ict-terminal-pro
echo ==========================================================
pause
