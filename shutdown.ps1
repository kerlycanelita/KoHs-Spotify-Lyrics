Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Helper = Join-Path $Root 'shutdown_all.py'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$UsedHelper = $false

function Invoke-ShutdownHelper([string]$Command, [string[]]$Prefix) {
    if (-not (Test-Path $Helper)) { return $false }
    try {
        & $Command @Prefix $Helper
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (Test-Path $VenvPython) {
    $UsedHelper = Invoke-ShutdownHelper $VenvPython @()
}

if (-not $UsedHelper -and (Get-Command py -ErrorAction SilentlyContinue)) {
    $UsedHelper = Invoke-ShutdownHelper 'py' @('-3')
}

if (-not $UsedHelper -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $UsedHelper = Invoke-ShutdownHelper 'python' @()
}

if ($UsedHelper) {
    Remove-Item (Join-Path $Root 'tiktok-url.txt') -Force -ErrorAction SilentlyContinue
    Write-Host 'Apagado completado.' -ForegroundColor Green
    exit 0
}

Write-Host '[AVISO] Python no esta disponible; usando apagado de emergencia por PID.' -ForegroundColor Yellow
$RuntimeDir = Join-Path $Root 'runtime'

function Read-Pid([string]$Name) {
    $Path = Join-Path $RuntimeDir $Name
    if (-not (Test-Path $Path)) { return $null }
    try {
        $Text = (Get-Content -LiteralPath $Path -Raw).Trim()
        if ($Text -match '^\d+$') { return [int]$Text }
    } catch {}
    return $null
}

function Get-ProcessInfo([int]$Pid) {
    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId = $Pid" -ErrorAction Stop
    } catch {
        return $null
    }
}

$Stopped = 0
$LauncherPid = Read-Pid 'launcher.pid'
if ($LauncherPid) {
    $Info = Get-ProcessInfo $LauncherPid
    if ($Info -and $Info.CommandLine -and $Info.CommandLine.ToLowerInvariant().Contains('tunnel_launcher.py')) {
        & taskkill.exe /PID $LauncherPid /T /F | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[APAGADO] Supervisor y procesos hijos (PID $LauncherPid)"
            $Stopped++
        }
    }
}

foreach ($Pair in @(@('tunnel.pid','cloudflared.exe'), @('server.pid','app.py'))) {
    $Pid = Read-Pid $Pair[0]
    if (-not $Pid) { continue }
    $Info = Get-ProcessInfo $Pid
    if (-not $Info) { continue }
    $Safe = $false
    if ($Pair[0] -eq 'tunnel.pid') {
        if ($Info.Name -and $Info.Name.ToLowerInvariant() -eq 'cloudflared.exe') { $Safe = $true }
    } else {
        if ($Info.CommandLine -and $Info.CommandLine.ToLowerInvariant().Contains('app.py')) { $Safe = $true }
    }
    if ($Safe) {
        try {
            Stop-Process -Id $Pid -Force -ErrorAction Stop
            Write-Host "[APAGADO] $($Pair[1]) (PID $Pid)"
            $Stopped++
        } catch {}
    }
}

Remove-Item (Join-Path $Root 'tiktok-url.txt') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $RuntimeDir 'launcher.pid') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $RuntimeDir 'tunnel.pid') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $RuntimeDir 'server.pid') -Force -ErrorAction SilentlyContinue

if ($Stopped -gt 0) {
    Write-Host "Listo: se detuvieron $Stopped grupo(s) de procesos." -ForegroundColor Green
} else {
    Write-Host 'No se encontraron servicios activos de KoHs Spotify Lyrics.'
}
exit 0
