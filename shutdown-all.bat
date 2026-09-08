@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Apagar KoH's Spotify Lyrics

echo.
echo  Apagando KoH's Spotify Lyrics
echo  =============================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" shutdown_all.py
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 shutdown_all.py
    ) else (
        python shutdown_all.py
    )
)

echo.
pause
exit /b 0
