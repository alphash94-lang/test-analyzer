[CmdletBinding()]
param(
    [datetime]$RunDate = (Get-Date)
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogDirectory = Join-Path $ProjectRoot "data\logs"
$AsOfDate = $RunDate.ToString("yyyy-MM-dd")
$LogPath = Join-Path $LogDirectory "update_all_$AsOfDate.log"
$BackupLogPath = Join-Path $LogDirectory "backup_$AsOfDate.log"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Project Python was not found: $PythonPath"
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$env:PYTHONIOENCODING = "utf-8"

Push-Location $ProjectRoot
try {
    & $PythonPath -m scripts.backup_data --label pre-update 2>&1 |
        Tee-Object -FilePath $BackupLogPath -Append
    $BackupExitCode = $LASTEXITCODE
    if ($BackupExitCode -ne 0) {
        & $PythonPath -m scripts.send_failure_alert `
            --source "windows-scheduler" `
            --title "데이터 백업 실패" `
            --message "예약 수집을 시작하지 않았습니다. 종료코드: $BackupExitCode" `
            --log-path $BackupLogPath
        exit $BackupExitCode
    }

    & $PythonPath -m scripts.update_all --as-of $AsOfDate 2>&1 |
        Tee-Object -FilePath $LogPath -Append
    $UpdateExitCode = $LASTEXITCODE
    if ($UpdateExitCode -ne 0) {
        & $PythonPath -m scripts.send_failure_alert `
            --source "windows-scheduler" `
            --title "전체 데이터 수집 실패" `
            --message "update_all 종료코드: $UpdateExitCode" `
            --log-path $LogPath
    }
}
finally {
    Pop-Location
}

exit $UpdateExitCode
