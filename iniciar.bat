@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title KoH's Spotify Lyrics

echo.
echo  KoH's Spotify Lyrics
echo  ====================
echo  Preparando el overlay local y el enlace HTTPS publico...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] El inicio no termino correctamente.
    echo Revisa los mensajes anteriores y la carpeta logs.
    echo.
    pause
    exit /b %EXIT_CODE%
)

echo.
echo El overlay sigue ejecutandose en segundo plano.
echo Usa shutdown-all.bat cuando termines.
echo.
echo Presiona una tecla para cerrar esta ventana...
pause >nul
exit /b 0
