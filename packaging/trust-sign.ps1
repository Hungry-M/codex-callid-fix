param(
    [string]$AppPath = (Join-Path $PSScriptRoot 'CodexCallIdFix.exe'),
    [string]$SetupPath = '',
    [int]$WaitPid = 0,
    [string]$RootSubject = 'CN=Hungry-M',
    [string]$ChildSubject = 'CN=codex-callid-fix',
    [switch]$Relaunch,
    [switch]$Pause,
    [switch]$NoTrust,
    [switch]$NoWait,
    [switch]$RemoveCert
)

$ErrorActionPreference = 'Stop'
$legacySubjects = @('CN=Hungry-M (Codex Call ID Fix)')
$logDir = Join-Path $env:LOCALAPPDATA 'CodexCallIdFix'
$logPath = Join-Path $logDir 'trust-sign.log'
$transcript = $false

function Write-Step([string]$message) {
    Write-Host "[trust-sign] $message" -ForegroundColor Cyan
}

function Stop-TranscriptIfNeeded {
    if ($script:transcript) {
        try { Stop-Transcript | Out-Null } catch { }
        $script:transcript = $false
    }
}

function Get-StoreCerts([string]$store, [string]$subject) {
    Get-ChildItem "Cert:\CurrentUser\$store" -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $subject }
}

function Remove-CertFromStore([string]$store, [string]$thumbprint) {
    if (-not $thumbprint) { return }
    certutil -user -delstore $store $thumbprint 2>$null | Out-Null
}

function Remove-ProjectCertificate {
    $removed = 0

    # Remove the project child and the legacy single self-signed certificate.
    foreach ($subject in @($ChildSubject) + $legacySubjects) {
        foreach ($store in @('My', 'Root', 'TrustedPublisher')) {
            foreach ($cert in Get-StoreCerts $store $subject) {
                Remove-CertFromStore $store $cert.Thumbprint
                Write-Host "Removed $store $subject $($cert.Thumbprint)"
                $removed++
            }
        }
    }

    # Find the root(s) by subject.
    $roots = @()
    foreach ($store in @('My', 'Root', 'TrustedPublisher')) {
        $roots += Get-StoreCerts $store $RootSubject
    }
    $roots = $roots | Sort-Object Thumbprint -Unique

    if ($roots.Count -eq 0) {
        Write-Host 'No Hungry-M root certificate found.'
        if ($Pause) { Read-Host 'Press Enter to close' }
        exit 0
    }

    # Other projects may have their own child certificates issued by this root.
    $otherChildren = @()
    foreach ($store in @('My', 'TrustedPublisher')) {
        $otherChildren += Get-ChildItem "Cert:\CurrentUser\$store" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Subject -ne $RootSubject -and
                $_.Issuer -eq $RootSubject -and
                $_.Subject -notin $legacySubjects
            }
    }
    $otherChildren = $otherChildren | Sort-Object Thumbprint -Unique

    if ($otherChildren.Count -gt 0) {
        Write-Host "Keeping root: $($otherChildren.Count) other child certificate(s) still use it."
        $otherChildren | Select-Object Subject, Thumbprint | Format-Table -AutoSize
    } else {
        foreach ($cert in $roots) {
            foreach ($store in @('My', 'Root', 'TrustedPublisher')) {
                foreach ($item in Get-StoreCerts $store $RootSubject) {
                    if ($item.Thumbprint -eq $cert.Thumbprint) {
                        Remove-CertFromStore $store $item.Thumbprint
                        Write-Host "Removed $store $RootSubject $($item.Thumbprint)"
                        $removed++
                    }
                }
            }
        }
    }

    if ($removed -eq 0) { Write-Host 'Nothing removed.' }
    if ($Pause) { Read-Host 'Press Enter to close' }
    exit 0
}

function Start-AppIfRequested {
    if (-not $script:Relaunch) { return }
    $path = $script:AppPath
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return }
    Write-Step 'Relaunching the application...'
    try {
        Start-Process -FilePath $path -WorkingDirectory (Split-Path -Parent $path)
    } catch {
        Write-Warning "Relaunch failed: $($_.Exception.Message)"
    }
}

function Get-AppProcesses {
    @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -eq $script:AppPath } catch { $false }
    })
}

if ($RemoveCert) {
    Remove-ProjectCertificate
}

try {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    try {
        Start-Transcript -Path $logPath -Append | Out-Null
        $transcript = $true
    } catch {
        Write-Host "Could not start transcript: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    Write-Host 'Local self-signing tool (root + project child)' -ForegroundColor Green
    Write-Host "Root:  $RootSubject"
    Write-Host "Child: $ChildSubject"
    Write-Host 'This trusts the root and child only for the CURRENT USER; other machines are unaffected.'
    Write-Host ''

    if (-not (Test-Path -LiteralPath $AppPath)) {
        throw "AppPath not found: $AppPath"
    }
    $AppPath = (Resolve-Path -LiteralPath $AppPath).Path
    $appDir = Split-Path -Parent $AppPath

    if (-not $NoWait) {
        $running = @()
        if ($WaitPid -gt 0) {
            $byPid = Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
            if ($byPid) { $running += $byPid }
        }
        # A PyInstaller onefile app can have more than one process with the
        # same executable path. Wait for all of them, not just the GUI PID.
        $running += Get-AppProcesses
        $running = $running | Sort-Object Id -Unique
        if ($running) {
            Write-Step 'Close the application to let it be signed; waiting...'
            $running | Wait-Process -Timeout 180 -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 700
        }

        # Give any surviving parent/child or second instance time to release
        # the file. Never sign while another instance is still running.
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline) {
            $remaining = Get-AppProcesses
            if ($remaining.Count -eq 0) { break }
            $remaining | Wait-Process -Timeout 3 -ErrorAction SilentlyContinue
        }
    }

    $unlocked = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $stream = [System.IO.File]::Open($AppPath, 'Open', 'ReadWrite', 'None')
            $stream.Close()
            $unlocked = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $unlocked) {
        throw "EXE is still locked after waiting: $AppPath"
    }

    Write-Step 'Locating/creating the root CA...'
    $root = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq $RootSubject } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
    if (-not $root) {
        $root = New-SelfSignedCertificate `
            -Type Custom `
            -Subject $RootSubject `
            -KeyUsage CertSign, CRLSign `
            -KeyUsageProperty Sign `
            -KeyExportPolicy Exportable `
            -KeyLength 4096 `
            -HashAlgorithm SHA256 `
            -CertStoreLocation Cert:\CurrentUser\My `
            -NotAfter (Get-Date).AddYears(10) `
            -TextExtension @('2.5.29.19={text}ca=1&pathlength=1')
        Write-Step "Created root $($root.Thumbprint)"
    } else {
        Write-Step "Using root $($root.Thumbprint)"
    }

    Write-Step 'Locating/creating the project child certificate...'
    $child = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object {
            $_.Subject -eq $ChildSubject -and
            $_.Issuer -eq $RootSubject
        } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
    if (-not $child -or $child.NotAfter -lt (Get-Date).AddDays(30)) {
        $child = New-SelfSignedCertificate `
            -Type CodeSigningCert `
            -Subject $ChildSubject `
            -Signer $root `
            -CertStoreLocation Cert:\CurrentUser\My `
            -KeyUsage DigitalSignature `
            -KeyExportPolicy Exportable `
            -NotAfter (Get-Date).AddYears(3) `
            -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3')
        Write-Step "Created child $($child.Thumbprint)"
    } else {
        Write-Step "Using child $($child.Thumbprint)"
    }

    if (-not $NoTrust) {
        Write-Step 'Trusting the root and publisher certificate for the current user...'
        $rootCer = Join-Path $logDir ("hungry-m-root-$($root.Thumbprint).cer")
        $childCer = Join-Path $logDir ("$($child.Thumbprint).cer")
        Export-Certificate -Cert $root -FilePath $rootCer | Out-Null
        Export-Certificate -Cert $child -FilePath $childCer | Out-Null
        try {
            if (-not (Get-StoreCerts 'Root' $RootSubject | Where-Object Thumbprint -eq $root.Thumbprint)) {
                Import-Certificate -FilePath $rootCer -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
            }
            if (-not (Get-StoreCerts 'TrustedPublisher' $ChildSubject | Where-Object Thumbprint -eq $child.Thumbprint)) {
                Import-Certificate -FilePath $childCer -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null
            }
        } finally {
            Remove-Item -LiteralPath $rootCer -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $childCer -Force -ErrorAction SilentlyContinue
        }
    }

    $files = @($AppPath)
    if ($SetupPath) {
        if (-not (Test-Path -LiteralPath $SetupPath)) {
            throw "SetupPath not found: $SetupPath"
        }
        $files += (Resolve-Path -LiteralPath $SetupPath).Path
    }

    $failed = $false
    foreach ($file in $files) {
        Write-Step "Signing $file ..."
        $signature = $null
        for ($i = 0; $i -lt 12; $i++) {
            try {
                $signature = Set-AuthenticodeSignature -FilePath $file -Certificate $child -HashAlgorithm SHA256
                if ($signature.Status -eq 'Valid') { break }
            } catch {
                $signature = $null
            }
            Start-Sleep -Milliseconds 500
        }
        if ($signature -and $signature.Status -eq 'Valid') {
            Write-Host "  OK: $($signature.StatusDescription)" -ForegroundColor Green
        } else {
            $failed = $true
            $status = if ($signature) { "$($signature.Status) — $($signature.StatusMessage)" } else { 'signing threw an exception' }
            Write-Warning "  Signature failed: $status"
        }
    }

    if ($failed) {
        throw "Code signing failed. See $logPath"
    }

    Write-Host ''
    Write-Host 'Done. Remove only this project child, or the root when unused:' -ForegroundColor Yellow
    Write-Host '  trust-sign.cmd -RemoveCert'
    Write-Host "  Root thumbprint:  $($root.Thumbprint)"
    Write-Host "  Child thumbprint: $($child.Thumbprint)"

    Start-AppIfRequested
    Stop-TranscriptIfNeeded
    if ($Pause) { Read-Host 'Press Enter to close' }
    exit 0
} catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $logPath" -ForegroundColor Yellow
    Start-AppIfRequested
    Stop-TranscriptIfNeeded
    if ($Pause) { Read-Host 'Press Enter to close' }
    exit 1
}
