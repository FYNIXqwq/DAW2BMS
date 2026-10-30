param([switch]$SkipInstall, [switch]$SkipEngine, [string]$Python)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not $SkipInstall) {
        & npm.cmd --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    }
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    & go test ./...
    if ($LASTEXITCODE -ne 0) { throw 'Chart/storage tests failed' }
    if (Get-Command wails3 -ErrorAction SilentlyContinue) {
        & wails3 generate syso -arch amd64 -icon build/windows/icon.ico -manifest build/windows/wails.exe.manifest -info build/windows/info.json -out bmse_windows_amd64.syso
        if ($LASTEXITCODE -ne 0) { throw 'Windows resource generation failed' }
    }
    & go build -trimpath -tags production '-ldflags=-s -w -H windowsgui' -o bin/BMSE3.exe .
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    Copy-Item -LiteralPath ../LICENSE -Destination bin/LICENSE -Force
    Copy-Item -LiteralPath ../NOTICE -Destination bin/NOTICE -Force
    Copy-Item -LiteralPath LICENSE -Destination bin/BMSE-LICENSE.txt -Force
    if (-not $SkipEngine) {
        & "$PSScriptRoot/build-engine.ps1" -Python $Python -SkipInstall:$SkipInstall
        Copy-Item -LiteralPath packaging/README.txt -Destination bin/README.txt -Force
        Compress-Archive -LiteralPath bin/BMSE3.exe,bin/daw-engine,bin/LICENSE,bin/NOTICE,bin/BMSE-LICENSE.txt,bin/README.txt -DestinationPath bin/BMSE3-Windows-x64.zip -Force
        Write-Host 'Packaged bin/BMSE3-Windows-x64.zip (includes the DAW conversion runtime)'
    }
    Write-Host 'Built bin/BMSE3.exe'
} finally { Pop-Location }
