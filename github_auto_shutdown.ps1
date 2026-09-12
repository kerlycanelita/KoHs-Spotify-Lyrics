param(
    [Parameter(Mandatory = $true)]
    [string]$BaseRoot,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 24)]
    [int]$Hours,

    [Parameter(Mandatory = $true)]
    [string]$SessionToken
)

$ErrorActionPreference = 'SilentlyContinue'

$tokenFile = Join-Path $BaseRoot 'active-session-token.txt'
$activePathFile = Join-Path $BaseRoot 'active-runtime.txt'
$logFile = Join-Path $BaseRoot 'auto-shutdown.log'

function Write-AutoShutdownLog {
    param([string]$Message)
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logFile -Value "[$stamp] $Message" -Encoding UTF8
}

Write-AutoShutdownLog "Timer armed for $Hours hour(s). Runtime: $RuntimeRoot"
Start-Sleep -Seconds ($Hours * 3600)

$currentToken = if (Test-Path $tokenFile) {
    (Get-Content $tokenFile -Raw).Trim()
} else {
    ''
}
$currentRuntime = if (Test-Path $activePathFile) {
    (Get-Content $activePathFile -Raw).Trim()
} else {
    ''
}

if ($currentToken -ne $SessionToken -or $currentRuntime -ne $RuntimeRoot) {
    Write-AutoShutdownLog 'Timer ignored because a newer overlay session is active.'
    exit 0
}

$python = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
$shutdown = Join-Path $RuntimeRoot 'shutdown_all.py'

if ((Test-Path $python) -and (Test-Path $shutdown)) {
    Write-AutoShutdownLog 'Automatic shutdown started.'
    & $python $shutdown 2>&1 | ForEach-Object {
        Write-AutoShutdownLog $_
    }
} else {
    Write-AutoShutdownLog 'Automatic shutdown could not run because the runtime is incomplete.'
}

$tokenStillMatches = (Test-Path $tokenFile) -and ((Get-Content $tokenFile -Raw).Trim() -eq $SessionToken)
$runtimeStillMatches = (Test-Path $activePathFile) -and ((Get-Content $activePathFile -Raw).Trim() -eq $RuntimeRoot)

if ($tokenStillMatches) {
    Remove-Item $tokenFile -Force
}
if ($runtimeStillMatches) {
    Remove-Item $activePathFile -Force
}

Write-AutoShutdownLog 'Automatic shutdown finished.'
