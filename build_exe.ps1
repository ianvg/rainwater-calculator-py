param(
    [switch]$InstallBuildTools
)

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

Invoke-Checked $python @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked $python @("-m", "pip", "install", "-e", ".[desktop-build]")

if ($InstallBuildTools) {
    Invoke-Checked $python @("-m", "pip", "install", "pyinstaller")
}

Invoke-Checked $python @("-m", "PyInstaller", "--clean", "--noconfirm", "RainwaterCalculator.spec")

Write-Host ""
Write-Host "Built executable:"
Write-Host (Join-Path $PSScriptRoot "dist\RainwaterCalculator.exe")
