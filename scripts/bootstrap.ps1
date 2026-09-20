[CmdletBinding()]
param([switch]$Recreate)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) { throw 'Conda was not found on PATH.' }
if ($Recreate) { conda env remove -n lastdance -y }
$Exists = conda env list --json | ConvertFrom-Json | Select-Object -ExpandProperty envs | Where-Object { $_ -match '[\\/]lastdance$' }
if ($Exists) { conda env update -n lastdance -f environment.yml --prune }
else { conda env create -f environment.yml }
conda run -n lastdance python -m lastdance doctor
