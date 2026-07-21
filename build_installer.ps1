param(
    [switch]$SkipExecutableBuild
)

$ErrorActionPreference = "Stop"
$executable = Join-Path $PSScriptRoot "dist\RainwaterCalculator.exe"
$installerScript = Join-Path $PSScriptRoot "installer\RainwaterCalculator.iss"

if (-not $SkipExecutableBuild -or -not (Test-Path -LiteralPath $executable)) {
    & (Join-Path $PSScriptRoot "build_exe.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Executable build failed with exit code $LASTEXITCODE."
    }
}

$compilerCandidates = @(
    Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
)
if (${env:ProgramFiles(x86)}) {
    $compilerCandidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if ($env:LOCALAPPDATA) {
    $compilerCandidates += Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
}
$compilerCandidates = $compilerCandidates | Where-Object {
    $_ -and (Test-Path -LiteralPath $_)
}

$compiler = $compilerCandidates | Select-Object -First 1
if (-not $compiler) {
    throw "Inno Setup 6 was not found. Install it, then rerun build_installer.ps1."
}

& $compiler $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Built installer:"
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "dist") -Filter "RainwaterCalculator-Setup-*.exe" |
    Select-Object -ExpandProperty FullName
