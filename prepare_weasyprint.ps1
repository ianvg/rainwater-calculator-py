$ErrorActionPreference = "Stop"
$weasyprintVersion = "69.0"
$weasyprintSha256 = "330101FF3EA50EBDE4ABF805283B6D703D5F3D71C77C983DB94357EC4524A3EF"
$weasyprintDirectory = Join-Path $PSScriptRoot "build\weasyprint"
$weasyprintExecutable = Join-Path $weasyprintDirectory "weasyprint.exe"
$weasyprintLicense = Join-Path $weasyprintDirectory "LICENSE.txt"

if ((Test-Path -LiteralPath $weasyprintExecutable) -and (Test-Path -LiteralPath $weasyprintLicense)) {
    Write-Host "WeasyPrint $weasyprintVersion is already prepared."
    return
}

$downloadDirectory = Join-Path $PSScriptRoot "build\weasyprint-download"
$archive = Join-Path $downloadDirectory "weasyprint-windows.zip"
$expanded = Join-Path $downloadDirectory "expanded"
New-Item -ItemType Directory -Force -Path $downloadDirectory | Out-Null
Invoke-WebRequest `
    -Uri "https://github.com/Kozea/WeasyPrint/releases/download/v$weasyprintVersion/weasyprint-windows.zip" `
    -OutFile $archive
$actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actualHash -ne $weasyprintSha256) {
    throw "WeasyPrint archive checksum mismatch. Expected $weasyprintSha256, got $actualHash."
}
Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
New-Item -ItemType Directory -Force -Path $weasyprintDirectory | Out-Null
Copy-Item `
    -LiteralPath (Join-Path $expanded "dist\weasyprint.exe") `
    -Destination $weasyprintExecutable
Copy-Item `
    -LiteralPath (Join-Path $expanded "LICENSE") `
    -Destination $weasyprintLicense
Write-Host "Prepared WeasyPrint $weasyprintVersion at $weasyprintExecutable"
