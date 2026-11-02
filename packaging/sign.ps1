param(
    [string]$PfxPath = $env:CODESIGN_PFX,
    [string]$PfxPassword = $env:CODESIGN_PFX_PASSWORD,
    [string]$TimestampUrl = 'http://timestamp.digicert.com',
    [string]$CertificateThumbprint = $env:CODESIGN_THUMBPRINT
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $roots = @(
        'C:\Program Files (x86)\Windows Kits\10\bin',
        'C:\Program Files\Windows Kits\10\bin'
    )
    foreach ($base in $roots) {
        if (-not (Test-Path $base)) { continue }
        $candidate = Get-ChildItem $base -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    return $null
}

$signtool = Find-SignTool
if (-not $signtool) {
    throw 'signtool.exe not found. Install the Windows SDK (Signing Tools) and re-run.'
}

$setup = Get-ChildItem (Join-Path $root 'dist\CodexCallIdFix-Setup-*.exe') -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$files = @(
    (Join-Path $root 'dist\CodexCallIdFix.exe'),
    if ($setup) { $setup.FullName }
) | Where-Object { $_ -and (Test-Path $_) }

if ($files.Count -eq 0) {
    throw 'No release EXEs found in dist\. Run packaging\build.ps1 first.'
}

foreach ($file in $files) {
    Write-Host "Signing $file"
    if ($CertificateThumbprint) {
        & $signtool sign /fd SHA256 /sha1 $CertificateThumbprint /tr $TimestampUrl /td SHA256 $file
    } else {
        if (-not $PfxPath) {
            throw 'Set -PfxPath or CODESIGN_PFX (or -CertificateThumbprint / CODESIGN_THUMBPRINT) first.'
        }
        $signArgs = @('sign', '/fd', 'SHA256', '/f', $PfxPath)
        if ($PfxPassword) { $signArgs += @('/p', $PfxPassword) }
        $signArgs += @('/tr', $TimestampUrl, '/td', 'SHA256', $file)
        & $signtool @signArgs
    }
    if ($LASTEXITCODE -ne 0) { throw "signtool sign failed for $file" }
    & $signtool verify /pa /all $file
    if ($LASTEXITCODE -ne 0) { throw "signtool verify failed for $file" }
}

Write-Host 'All release files signed and verified.'
