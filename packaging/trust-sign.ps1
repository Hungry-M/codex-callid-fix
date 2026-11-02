param(
    [string]$AppPath = (Join-Path $PSScriptRoot 'CodexCallIdFix.exe'),
    [string]$SetupPath = '',
    [switch]$Relaunch,
    [switch]$Pause,
    [switch]$NoTrust,
    [switch]$NoWait,
    [switch]$RemoveCert
)

$ErrorActionPreference = 'Stop'
$subject = 'CN=Hungry-M (Codex Call ID Fix)'

function Write-Step([string]$message) {
    Write-Host "[trust-sign] $message" -ForegroundColor Cyan
}

if ($RemoveCert) {
    $found = 0
    foreach ($store in @('My', 'Root', 'TrustedPublisher')) {
        $certs = Get-ChildItem "Cert:\CurrentUser\$store" -ErrorAction SilentlyContinue |
            Where-Object { $_.Subject -eq $subject }
        foreach ($item in $certs) {
            certutil -user -delstore $store $item.Thumbprint | Out-Null
            Write-Host "Removed $store $($item.Thumbprint)"
            $found++
        }
    }
    if ($found -eq 0) { Write-Host 'No matching certificate found.' }
    if ($Pause) { Read-Host 'Press Enter to close' }
    exit 0
}

Write-Host 'Codex Call ID Fix — local self-signing tool' -ForegroundColor Green
Write-Host 'This creates a self-signed certificate in the CURRENT USER store and trusts it locally.'
Write-Host 'It is for this Windows account only; it does NOT make other machines trust the file.'
Write-Host ''

if (-not (Test-Path -LiteralPath $AppPath)) {
    throw "AppPath not found: $AppPath"
}
$AppPath = (Resolve-Path -LiteralPath $AppPath).Path
$appDir = Split-Path -Parent $AppPath

# If the GUI is running, give it a chance to close before signing.
$running = Get-Process -Name 'CodexCallIdFix' -ErrorAction SilentlyContinue
if ($running -and -not $NoWait) {
    Write-Step 'Close Codex Call ID Fix to let it be signed; waiting...'
    $running | Wait-Process -Timeout 180 -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Step 'Locating/creating the self-signed code-signing certificate...'
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $subject } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1
if (-not $cert) {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage DigitalSignature `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears(5) `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3')
    Write-Step "Created certificate thumbprint $($cert.Thumbprint)"
} else {
    Write-Step "Using existing certificate thumbprint $($cert.Thumbprint)"
}

if (-not $NoTrust) {
    Write-Step 'Trusting the certificate for the current user (Root + TrustedPublisher)...'
    $cer = Join-Path $PSScriptRoot ("codex-callidfix-$($cert.Thumbprint).cer")
    Export-Certificate -Cert $cert -FilePath $cer | Out-Null
    try {
        $root = Get-ChildItem Cert:\CurrentUser\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
        if (-not $root) {
            Import-Certificate -FilePath $cer -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
        }
        $publisher = Get-ChildItem Cert:\CurrentUser\TrustedPublisher | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
        if (-not $publisher) {
            Import-Certificate -FilePath $cer -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null
        }
    } finally {
        Remove-Item -LiteralPath $cer -Force -ErrorAction SilentlyContinue
    }
}

$files = @($AppPath)
if ($SetupPath) {
    if (-not (Test-Path -LiteralPath $SetupPath)) {
        throw "SetupPath not found: $SetupPath"
    }
    $files += (Resolve-Path -LiteralPath $SetupPath).Path
}

foreach ($file in $files) {
    Write-Step "Signing $file ..."
    $signature = Set-AuthenticodeSignature -FilePath $file -Certificate $cert -HashAlgorithm SHA256
    if ($signature.Status -eq 'Valid') {
        Write-Host "  OK: $($signature.StatusDescription)" -ForegroundColor Green
    } else {
        Write-Warning "  Signature status: $($signature.Status) — $($signature.StatusMessage)"
    }
}

Write-Host ''
Write-Host 'Done. To remove the local certificate later, run:' -ForegroundColor Yellow
Write-Host '  trust-sign.cmd -RemoveCert'
Write-Host 'or manually (PowerShell cannot delete Root-store items):'
Write-Host "  certutil -user -delstore Root $($cert.Thumbprint)"
Write-Host "  certutil -user -delstore TrustedPublisher $($cert.Thumbprint)"
Write-Host "  certutil -user -delstore My $($cert.Thumbprint)"

if ($Relaunch -and (Test-Path -LiteralPath $AppPath)) {
    Write-Step 'Relaunching Codex Call ID Fix...'
    Start-Process -FilePath $AppPath -WorkingDirectory $appDir
}

if ($Pause) {
    Read-Host 'Press Enter to close'
}
