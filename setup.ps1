$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Install Python 3.13 and enable Add Python to PATH first.' }
if (-not (Test-Path '.venv\Scripts\python.exe')) {
  python -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}
& python -m pip --python '.venv\Scripts\python.exe' install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Output 'Setup complete. Run start.cmd.'
