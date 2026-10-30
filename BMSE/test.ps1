param([switch]$Browser, [string]$Spec)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$previewProcess = $null
$bridgeProcess = $null
try {
    & go test ./...
    if ($LASTEXITCODE -ne 0) { throw 'Go tests failed' }
    & npm.cmd --prefix frontend test
    if ($LASTEXITCODE -ne 0) { throw 'Editor model tests failed' }
    if ($Browser) {
        & npm.cmd --prefix frontend run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
        & go build -o bin/preview-test.exe ./cmd/preview
        if ($LASTEXITCODE -ne 0) { throw 'Preview build failed' }
        & go build -tags server -o bin/bridge-test.exe .
        if ($LASTEXITCODE -ne 0) { throw 'Wails bridge build failed' }
        $previewProcess = Start-Process -FilePath "$PSScriptRoot/bin/preview-test.exe" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
        $env:WAILS_SERVER_HOST = '127.0.0.1'
        $env:WAILS_SERVER_PORT = '9247'
        $env:BMSE_CONFIG_DIR = "$PSScriptRoot/bin/test-config"
        $bridgeProcess = Start-Process -FilePath "$PSScriptRoot/bin/bridge-test.exe" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
        Remove-Item Env:WAILS_SERVER_HOST,Env:WAILS_SERVER_PORT,Env:BMSE_CONFIG_DIR
        for ($i = 0; $i -lt 30; $i++) {
            try { $null = Invoke-WebRequest 'http://127.0.0.1:9247/' -UseBasicParsing; break } catch { Start-Sleep -Milliseconds 200 }
        }
        Push-Location frontend
        try {
            if ($Spec) { & npm.cmd run test:e2e -- $Spec } else { & npm.cmd run test:e2e }
            if ($LASTEXITCODE -ne 0) { throw 'Browser tests failed' }
        } finally { Pop-Location }
    }
} finally {
    if ($previewProcess -and -not $previewProcess.HasExited) { Stop-Process -Id $previewProcess.Id }
    if ($bridgeProcess -and -not $bridgeProcess.HasExited) { Stop-Process -Id $bridgeProcess.Id }
    Pop-Location
}
