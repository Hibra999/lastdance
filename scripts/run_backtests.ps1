[CmdletBinding()]
param([switch]$Smoke)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) { throw 'Conda was not found on PATH.' }
conda run -n lastdance python scripts/verify_environment.py
$Arguments = @('-m', 'lastdance', 'all', '--open')
if ($Smoke) { $Arguments += '--smoke' }
conda run -n lastdance python @Arguments
