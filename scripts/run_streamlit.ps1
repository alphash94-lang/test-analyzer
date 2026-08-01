$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

& ".\.venv\Scripts\python.exe" -m streamlit run app/main.py `
    --server.headless=true `
    --server.port=8501
