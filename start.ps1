$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$journalLocalConfig = Join-Path $PSScriptRoot 'local-config.ps1'
if (Test-Path -LiteralPath $journalLocalConfig) { . $journalLocalConfig }
$journalPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $journalPython)) { throw 'Run setup.cmd first.' }
$journalOpenD = $env:MOOMOO_OPEND_PATH
if ($journalOpenD -and -not (Get-Process -Name 'moomoo_OpenD','moomoo_OpenD-GUI*','OpenD' -ErrorAction SilentlyContinue)) {
  if (Test-Path -LiteralPath $journalOpenD) {
    Start-Process -FilePath $journalOpenD -WorkingDirectory (Split-Path -Parent $journalOpenD) -WindowStyle Hidden
  } else { Write-Warning 'Configured OpenD path does not exist; start OpenD manually.' }
}
$journalOnline = $false
try { $journalState = Invoke-RestMethod 'http://127.0.0.1:8765/api/state' -TimeoutSec 2; $journalOnline = $true } catch {}
if (-not $journalOnline) {
  New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'data') | Out-Null
  Start-Process -FilePath $journalPython -ArgumentList 'app.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data\server.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data\server.error.log')
  for ($journalAttempt=0; $journalAttempt -lt 30; $journalAttempt++) {
    Start-Sleep -Milliseconds 500
    try { $journalState=Invoke-RestMethod 'http://127.0.0.1:8765/api/state' -TimeoutSec 1; $journalOnline=$true; break } catch {}
  }
}
if (-not $journalOnline) { throw 'Startup failed. Check data/server.error.log or run .venv/Scripts/python.exe app.py.' }
if ($journalState.settings.account -and $journalState.settings.auto -and -not $journalState.status.running) {
  $journalHeaders=@{'X-Journal-Token'=$journalState.token}
  $journalDates=@{start=(Get-Date).AddDays(-2).ToString('yyyy-MM-dd');end=(Get-Date).AddDays(1).ToString('yyyy-MM-dd')}
  try { $null=Invoke-RestMethod 'http://127.0.0.1:8765/api/sync' -Method Post -ContentType 'application/json' -Headers $journalHeaders -Body ($journalDates | ConvertTo-Json -Compress) } catch { Write-Warning 'Check the sync status in the application.' }
}
Start-Process 'http://127.0.0.1:8765'
