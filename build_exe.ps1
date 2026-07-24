$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Invoke-Checked {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

if (-not (Test-Path $python)) {
    Invoke-Checked "python" @("-m", "venv", (Join-Path $PSScriptRoot ".venv"))
}

Invoke-Checked $python @("-m", "pip", "install", "--require-hashes", "-r", (Join-Path $PSScriptRoot "requirements\desktop-build.txt"))
Invoke-Checked $python @("-m", "pip", "install", "--no-build-isolation", "--no-deps", "-e", $PSScriptRoot)

& (Join-Path $PSScriptRoot "prepare_weasyprint.ps1")

Invoke-Checked $python @("-m", "mkdocs", "build", "--clean", "--strict")
Invoke-Checked $python @("-m", "pip_audit", "--strict", "--progress-spinner", "off")
Invoke-Checked $python @("-m", "PyInstaller", "--clean", "--noconfirm", "RainwaterCalculator.spec")
Invoke-Checked $python @("-m", "cyclonedx_py", "environment", "--pyproject", (Join-Path $PSScriptRoot "pyproject.toml"), "--output-reproducible", "--output-format", "JSON", "--output-file", (Join-Path $PSScriptRoot "dist\RainwaterCalculator.cdx.json"))

Write-Host ""
Write-Host "Built executable:"
Write-Host (Join-Path $PSScriptRoot "dist\RainwaterCalculator.exe")
