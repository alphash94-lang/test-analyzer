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

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Project Python was not found: $PythonPath"
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$env:PYTHONIOENCODING = "utf-8"

Push-Location $ProjectRoot
try {
    & $PythonPath -m scripts.update_all --as-of $AsOfDate 2>&1 |
        Tee-Object -FilePath $LogPath -Append
    $UpdateExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $UpdateExitCode
