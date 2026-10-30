param([string]$Python, [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$engineRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$explicitPython = [bool]$Python
if (-not $Python) { $Python = Join-Path $engineRoot '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $Python)) {
    if ($explicitPython) { throw "Specified build Python does not exist: $Python" }
    if ($SkipInstall) { throw 'Build Python is missing. Run without -SkipInstall or specify -Python.' }
    & python -m venv (Join-Path $engineRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create build Python environment.' }
    $Python = Join-Path $engineRoot '.venv/Scripts/python.exe'
}
$Python = (Resolve-Path -LiteralPath $Python).Path
& $Python -c "import sys, struct; assert sys.version_info >= (3,10) and struct.calcsize('P') == 8, 'Build requires Python 3.10+ x64'"
if ($LASTEXITCODE -ne 0) { throw 'Unsupported build Python.' }
Push-Location $engineRoot
try {
    if (-not $SkipInstall) {
        & $Python -m pip install -e '.[audio,ableton]' 'pyinstaller==6.22.3'
        if ($LASTEXITCODE -ne 0) { throw 'Engine build dependencies failed.' }
    }
    & $Python -m PyInstaller --noconfirm --distpath "$PSScriptRoot/bin" --workpath "$PSScriptRoot/bin/engine-build" "$PSScriptRoot/packaging/DAW2BMS.spec"
    if ($LASTEXITCODE -ne 0) { throw 'Engine packaging failed.' }
    & $Python "$PSScriptRoot/packaging/verify_bundle.py" "$PSScriptRoot/bin/daw-engine/DAW2BMS.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Bundled engine validation failed.' }
} finally { Pop-Location }
