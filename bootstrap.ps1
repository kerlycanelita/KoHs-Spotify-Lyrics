Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
} catch {}

function Write-Step([string]$Text) {
    Write-Host $Text -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Test-PythonCandidate([string]$Command, [string[]]$Prefix) {
    try {
        & $Command @Prefix '-c' 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

Write-Step '[1/5] Buscando Python 3.11 o superior...'
$PythonCommand = $null
$PythonPrefix = @()

if (Get-Command py -ErrorAction SilentlyContinue) {
    if (Test-PythonCandidate 'py' @('-3')) {
        $PythonCommand = 'py'
        $PythonPrefix = @('-3')
    }
}

if (-not $PythonCommand -and (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Test-PythonCandidate 'python' @()) {
        $PythonCommand = 'python'
        $PythonPrefix = @()
    }
}

if (-not $PythonCommand) {
    Fail 'No se encontro Python 3.11 o superior. Instala Python desde https://www.python.org/downloads/windows/ y activa Add Python to PATH.'
}

$VersionText = (& $PythonCommand @PythonPrefix '--version' 2>&1 | Out-String).Trim()
Write-Host "      $VersionText"

$VenvDir = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

if (Test-Path $VenvPython) {
    & $VenvPython '-c' 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '      El entorno virtual existente no es compatible; se recreara.' -ForegroundColor Yellow
        Remove-Item $VenvDir -Recurse -Force
    }
}

if (-not (Test-Path $VenvPython)) {
    Write-Host '      Creando entorno virtual...'
    & $PythonCommand @PythonPrefix '-m' 'venv' $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
        Fail 'No se pudo crear .venv.'
    }
} else {
    Write-Host '      Entorno virtual listo.'
}

Write-Step '[2/5] Verificando dependencias de Python...'
& $VenvPython '-m' 'pip' '--version' *> $null
if ($LASTEXITCODE -ne 0) {
    & $VenvPython '-m' 'ensurepip' '--upgrade'
    if ($LASTEXITCODE -ne 0) { Fail 'No se pudo preparar pip.' }
}

$Requirements = Join-Path $Root 'requirements.txt'
if (-not (Test-Path $Requirements)) { Fail 'No existe requirements.txt.' }
$ReqHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
$Stamp = Join-Path $VenvDir 'requirements.sha256'
$OldHash = ''
if (Test-Path $Stamp) {
    try { $OldHash = (Get-Content -LiteralPath $Stamp -Raw).Trim() } catch {}
}

$ImportsOk = $false
try {
    & $VenvPython '-c' 'import fastapi, httpx, jinja2, pydantic, uvicorn; import winrt.windows.foundation; import winrt.windows.media.control' *> $null
    $ImportsOk = ($LASTEXITCODE -eq 0)
} catch {}

if ($OldHash -ne $ReqHash -or -not $ImportsOk) {
    Write-Host '      Instalando/actualizando paquetes...'
    & $VenvPython '-m' 'pip' 'install' '--disable-pip-version-check' '-r' $Requirements
    if ($LASTEXITCODE -ne 0) {
        Fail 'pip no pudo instalar las dependencias. Comprueba tu conexion a Internet y vuelve a ejecutar iniciar.bat.'
    }
    Set-Content -LiteralPath $Stamp -Value $ReqHash -Encoding ASCII
} else {
    Write-Host '      Dependencias ya instaladas.'
}

Write-Step '[3/5] Verificando Cloudflare Tunnel...'
$ToolsDir = Join-Path $Root 'tools'
$Cloudflared = Join-Path $ToolsDir 'cloudflared.exe'
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

function Test-Cloudflared {
    if (-not (Test-Path $Cloudflared)) { return $false }
    try {
        & $Cloudflared '--version' *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (-not (Test-Cloudflared)) {
    Write-Host '      cloudflared no esta instalado; descargando la version oficial...'
    $DownloadUrl = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
    $TempCloudflared = "$Cloudflared.download"
    Remove-Item $TempCloudflared -Force -ErrorAction SilentlyContinue
    try {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        } catch {}
        Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $TempCloudflared
        Move-Item -LiteralPath $TempCloudflared -Destination $Cloudflared -Force
    } catch {
        Remove-Item $TempCloudflared -Force -ErrorAction SilentlyContinue
        Fail "No se pudo descargar cloudflared: $($_.Exception.Message)"
    }
    if (-not (Test-Cloudflared)) {
        Remove-Item $Cloudflared -Force -ErrorAction SilentlyContinue
        Fail 'El archivo cloudflared descargado no es valido.'
    }
} else {
    Write-Host '      cloudflared listo.'
}

Write-Step '[4/5] Preparando una sesion limpia...'
$ShutdownHelper = Join-Path $Root 'shutdown_all.py'
if (Test-Path $ShutdownHelper) {
    try {
        & $VenvPython $ShutdownHelper | Out-Host
    } catch {
        Write-Host '      No se pudo limpiar una sesion anterior; se continuara con el arranque.' -ForegroundColor Yellow
    }
}

$LogsDir = Join-Path $Root 'logs'
$RuntimeDir = Join-Path $Root 'runtime'
New-Item -ItemType Directory -Force -Path $LogsDir, $RuntimeDir | Out-Null
Remove-Item (Join-Path $Root 'tiktok-url.txt') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $LogsDir 'launcher.log') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $LogsDir 'launcher-error.log') -Force -ErrorAction SilentlyContinue

$env:KOHS_HTTP_ONLY = '1'
$env:KOHS_LOCAL_BASE_URL = 'http://127.0.0.1:3000'
$env:KOHS_NO_BROWSER = '1'

$LauncherLog = Join-Path $LogsDir 'launcher.log'
$LauncherError = Join-Path $LogsDir 'launcher-error.log'
$Launcher = Start-Process -FilePath $VenvPython `
    -ArgumentList @('-u', 'tunnel_launcher.py') `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $LauncherLog `
    -RedirectStandardError $LauncherError `
    -PassThru

$UrlFile = Join-Path $Root 'tiktok-url.txt'
$Deadline = (Get-Date).AddSeconds(180)

Write-Step '[5/5] Iniciando servidor y creando el enlace HTTPS publico...'
while (-not (Test-Path $UrlFile)) {
    try { $Launcher.Refresh() } catch {}
    if ($Launcher.HasExited) {
        Write-Host ''
        Write-Host 'El lanzador se cerro antes de crear el enlace.' -ForegroundColor Red
        if (Test-Path $LauncherLog) {
            Write-Host '--- logs\launcher.log ---'
            Get-Content $LauncherLog -Tail 40 | Out-Host
        }
        if (Test-Path $LauncherError) {
            Write-Host '--- logs\launcher-error.log ---'
            Get-Content $LauncherError -Tail 40 | Out-Host
        }
        exit 1
    }
    if ((Get-Date) -gt $Deadline) {
        Write-Host ''
        Write-Host 'Tiempo agotado esperando el enlace publico.' -ForegroundColor Red
        if (Test-Path $LauncherLog) {
            Get-Content $LauncherLog -Tail 40 | Out-Host
        }
        try { & $VenvPython $ShutdownHelper | Out-Null } catch {}
        exit 1
    }
    Start-Sleep -Seconds 1
}

$OverlayUrl = (Get-Content -LiteralPath $UrlFile -Raw).Trim()
if ($OverlayUrl -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com/overlay$') {
    try { & $VenvPython $ShutdownHelper | Out-Null } catch {}
    Fail "Se genero una URL inesperada: $OverlayUrl"
}

try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:3000/api/health' -TimeoutSec 8 | Out-Null
} catch {
    try { & $VenvPython $ShutdownHelper | Out-Null } catch {}
    Fail 'El tunel genero una URL, pero el servidor local no responde en 127.0.0.1:3000.'
}

try { $OverlayUrl | & "$env:SystemRoot\System32\clip.exe" } catch {}

$ConfigUrl = 'http://127.0.0.1:3000/config'
try { Start-Process $ConfigUrl | Out-Null } catch {}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor DarkMagenta
Write-Host ' KOHS SPOTIFY LYRICS LISTO' -ForegroundColor Green
Write-Host ('=' * 72) -ForegroundColor DarkMagenta
Write-Host "Enlace para TikTok/OBS: $OverlayUrl" -ForegroundColor White
Write-Host "Configuracion local:     $ConfigUrl" -ForegroundColor White
Write-Host 'El enlace publico tambien se copio al portapapeles.' -ForegroundColor Gray
Write-Host 'Para apagar todo, ejecuta shutdown-all.bat.' -ForegroundColor Gray
Write-Host ('=' * 72) -ForegroundColor DarkMagenta
exit 0
