@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Apagar KoH's Spotify Lyrics

echo.
echo  Apagando KoH's Spotify Lyrics
echo  =============================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0shutdown.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo [AVISO] El apagado termino con advertencias. Revisa los mensajes anteriores.
)
echo Presiona una tecla para cerrar...
pause >nul
exit /b %EXIT_CODE%
