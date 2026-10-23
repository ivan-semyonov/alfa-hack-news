param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Create .venv and install backend/requirements-dev.txt first. See README.md.'
}
Push-Location -LiteralPath $projectDirectory
try {
    & $projectPython -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Server exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
