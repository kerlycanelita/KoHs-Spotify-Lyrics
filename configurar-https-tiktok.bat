@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Configurar HTTPS local para TikTok

echo.
echo  HTTPS local para TikTok LIVE Studio
echo  ====================================
echo.
echo Este proceso crea una autoridad local privada y un certificado
echo valido solamente para localhost y 127.0.0.1. Solo la autoridad
echo publica se agrega al almacen de confianza del usuario de Windows.
echo.
choice /C SN /M "Deseas continuar"
if errorlevel 2 exit /b 1

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

".venv\Scripts\python.exe" https_setup.py
if errorlevel 1 goto :error

certutil.exe -user -addstore Root "certs\kohs-local-ca.cer"
if errorlevel 1 goto :error

echo.
echo [LISTO] HTTPS local configurado.
echo URL para TikTok LIVE Studio:
echo https://localhost:3443/overlay
echo.
echo Ahora ejecuta iniciar.bat.
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] No se pudo configurar HTTPS. Revisa el mensaje anterior.
echo.
pause
exit /b 1
