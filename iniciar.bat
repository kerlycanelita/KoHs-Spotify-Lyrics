@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title KoH's Spotify Lyrics para TikTok

echo.
echo  KoH's Spotify Lyrics
echo  ====================
echo.

set "PYTHON_LAUNCHER="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_LAUNCHER=py -3"
if not defined PYTHON_LAUNCHER (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_LAUNCHER=python"
)

if not defined PYTHON_LAUNCHER (
    echo [ERROR] No se encontro Python 3.
    echo Instala Python desde https://www.python.org/downloads/windows/
    echo Durante la instalacion activa "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creando el entorno virtual...
    %PYTHON_LAUNCHER% -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/4] Entorno virtual encontrado.
)

echo [2/4] Verificando dependencias...
set "REQ_STAMP=.venv\requirements.stamp"
set "REQ_HASH="
for /f "skip=1 tokens=1" %%H in ('certutil -hashfile requirements.txt SHA256') do if not defined REQ_HASH set "REQ_HASH=%%H"
set "REQ_CACHED="
if exist "%REQ_STAMP%" set /p "REQ_CACHED="<"%REQ_STAMP%"
set "SKIP_PIP="
if defined REQ_HASH if /i "%REQ_CACHED%"=="%REQ_HASH%" set "SKIP_PIP=1"
if defined SKIP_PIP (
    echo       Dependencias ya instaladas.
) else (
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :error
    if defined REQ_HASH (
        >"%REQ_STAMP%" echo %REQ_HASH%
    )
)

if not exist "tools\cloudflared.exe" (
    echo [ERROR] Falta tools\cloudflared.exe.
    echo Vuelve a descargar la carpeta completa de la aplicacion.
    goto :error
)

if not exist "logs" mkdir "logs"
if not exist "runtime\launcher.pid" del /q "tiktok-url.txt" >nul 2>nul

echo [3/4] Iniciando servicios en segundo plano...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$root=(Get-Location).Path; Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList '-u','tunnel_launcher.py' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'logs\launcher.log') -RedirectStandardError (Join-Path $root 'logs\launcher-error.log') | Out-Null"
if errorlevel 1 goto :error

echo [4/4] Esperando el enlace HTTPS...
for /L %%I in (1,1,90) do (
    if exist "tiktok-url.txt" goto :ready
    ping -n 2 127.0.0.1 >nul
)
echo [ERROR] El servicio no entrego un enlace en 90 segundos.
echo Revisa logs\launcher.log y logs\tunnel.log.
goto :error

:ready
set /p "TIKTOK_URL="<"tiktok-url.txt"
echo.
echo Servicio iniciado. Puedes cerrar esta ventana.
echo Enlace para TikTok:  %TIKTOK_URL%
echo Overlay local:       https://localhost:3443/overlay
echo Configuracion:       https://localhost:3443/config
echo Usa shutdown-all.bat para apagar todo.
ping -n 5 127.0.0.1 >nul
exit /b 0

:error
echo.
echo [ERROR] No se pudo iniciar el enlace para TikTok.
echo La ventana permanecera abierta para que puedas copiar el error.
echo.
pause
exit /b 1
