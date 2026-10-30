param(
    [Parameter(Mandatory=$true)][string]$EngineRoot,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
$engine = (Resolve-Path -LiteralPath $EngineRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $engine 'daw2bms/bridge.py'))) { throw 'The engine folder must contain daw2bms/bridge.py.' }
if (-not $Python) { $Python = Join-Path $engine '.venv/Scripts/python.exe' }
$interpreter = (Resolve-Path -LiteralPath $Python).Path
$bin = Join-Path $PSScriptRoot 'bin'
New-Item -ItemType Directory -Path $bin -Force | Out-Null
$config = @{ mode='python'; python=$interpreter; engineRoot=$engine; language='system' } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $bin 'daw-import.json'), $config, [System.Text.UTF8Encoding]::new($false))
Write-Host 'Configured the DAW engine for this bin directory. User settings in BMSE take precedence.'
