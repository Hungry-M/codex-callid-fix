param(
    [string]$AppDir = $PSScriptRoot,
    [switch]$Yes,
    [switch]$KeepBackups,
    [switch]$RemoveFolder,
    [switch]$RemoveRoot,
    [switch]$Pause
)

$ErrorActionPreference = 'Stop'
$logDir = Join-Path $env:LOCALAPPDATA 'CodexCallIdFix'
$logPath = Join-Path $logDir 'cleanup.log'
$transcript = $false

function Write-Step([string]$message) {
    Write-Host "[cleanup] $message" -ForegroundColor Cyan
}

function Stop-TranscriptIfNeeded {
    if ($script:transcript) {
        try { Stop-Transcript | Out-Null } catch { }
        $script:transcript = $false
    }
}

function Remove-ShortcutIfTargets([string]$path, [string]$target) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($path)
        $actual = [IO.Path]::GetFullPath($shortcut.TargetPath).TrimEnd('\')
        if ($actual -ieq ([IO.Path]::GetFullPath($target).TrimEnd('\'))) {
            Remove-Item -LiteralPath $path -Force
            Write-Host "Removed shortcut $path"
        }
    } catch {
        Write-Warning "Could not inspect shortcut $path"
    }
}

try {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    try {
        Start-Transcript -Path $logPath -Append | Out-Null
        $transcript = $true
    } catch { }

    if (-not (Test-Path -LiteralPath $AppDir)) {
        throw "AppDir not found: $AppDir"
    }
    $AppDir = (Resolve-Path -LiteralPath $AppDir).Path
    $gui = Join-Path $AppDir 'CodexCallIdFix.exe'
    $node = Join-Path $AppDir 'runtime\node.exe'
    $manage = Join-Path $AppDir 'backend\manage.js'
    $trust = Join-Path $AppDir 'trust-sign.ps1'

    Write-Host 'Codex Call ID Fix cleanup' -ForegroundColor Green
    Write-Host "AppDir: $AppDir"
    Write-Host ''
    Write-Host 'This will:'
    Write-Host '  - restore tool-managed Codex config and turn autostart off'
    Write-Host '  - remove the codex-callid-fix child certificate'
    Write-Host '  - remove the Hungry-M root only if no other project child remains'
    if ($RemoveRoot) {
        Write-Host '  - REMOVE ROOT: remove Hungry-M root and ALL its child certificates' -ForegroundColor Yellow
    }
    Write-Host '  - remove the Run entry and matching uninstall entry'
    Write-Host '  - remove shortcuts whose target is this AppDir'
    Write-Host '  - remove logs and, unless -KeepBackups, this tool''s backups'
    Write-Host 'It does not scan or delete unrelated Programs folders.'
    Write-Host ''

    if (-not $Yes) {
        $answer = Read-Host 'Type CLEAN to continue'
        if ($answer -cne 'CLEAN') {
            Write-Host 'Cancelled.'
            Stop-TranscriptIfNeeded
            if ($Pause) { Read-Host 'Press Enter to close' }
            exit 1
        }
    }

    if ((Test-Path $node) -and (Test-Path $manage)) {
        Write-Step 'Restoring Codex config and disabling autostart...'
        & $node $manage off | Out-Host
        & $node $manage autostart off | Out-Host
    } else {
        Write-Warning 'node.exe/manage.js not found; skipping config restore.'
    }

    if (Test-Path $trust) {
        Write-Step 'Removing project certificate (root kept while other children exist)...'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $trust -RemoveCert | Out-Host
    } else {
        Write-Warning 'trust-sign.ps1 not found; skipping certificate cleanup.'
    }

    if ($RemoveRoot) {
        Write-Step 'Removing Hungry-M root and all certificates issued by it...'
        $rootSubject = 'CN=Hungry-M'
        $targets = @()
        foreach ($store in @('My', 'TrustedPublisher')) {
            $targets += Get-ChildItem "Cert:\CurrentUser\$store" -ErrorAction SilentlyContinue |
                Where-Object { $_.Issuer -eq $rootSubject -and $_.Subject -ne $rootSubject }
        }
        $targets = $targets | Sort-Object Thumbprint -Unique
        foreach ($cert in $targets) {
            foreach ($store in @('My', 'TrustedPublisher')) {
                certutil -user -delstore $store $cert.Thumbprint 2>$null | Out-Null
            }
            Write-Host "Removed child $($cert.Subject) $($cert.Thumbprint)"
        }
        foreach ($store in @('My', 'Root', 'TrustedPublisher')) {
            Get-ChildItem "Cert:\CurrentUser\$store" -ErrorAction SilentlyContinue |
                Where-Object { $_.Subject -eq $rootSubject } |
                ForEach-Object {
                    certutil -user -delstore $store $_.Thumbprint 2>$null | Out-Null
                    Write-Host "Removed root $store $($_.Thumbprint)"
                }
        }
    }

    Write-Step 'Removing matching Run entry...'
    Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
        -Name 'codex-callid-fix' -ErrorAction SilentlyContinue

    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexCallIdFix'
    if (Test-Path $uninstallKey) {
        $recorded = (Get-ItemProperty -Path $uninstallKey -ErrorAction SilentlyContinue).InstallLocation
        if ($recorded -and ([IO.Path]::GetFullPath($recorded).TrimEnd('\') -ieq $AppDir.TrimEnd('\'))) {
            Remove-Item -LiteralPath $uninstallKey -Recurse -Force
            Write-Host 'Removed matching uninstall entry.'
        } else {
            Write-Host 'Uninstall entry points elsewhere; kept it.'
        }
    }

    $desktop = [Environment]::GetFolderPath('Desktop')
    $programs = [Environment]::GetFolderPath('Programs')
    Remove-ShortcutIfTargets (Join-Path $desktop 'Codex Call ID Fix.lnk') $gui
    Remove-ShortcutIfTargets (Join-Path $programs 'Codex Call ID Fix.lnk') $gui
    Remove-ShortcutIfTargets (Join-Path $programs 'Trust & Sign Codex Call ID Fix.lnk') (Join-Path $AppDir 'trust-sign.cmd')

    if (-not $KeepBackups -and (Test-Path $logDir)) {
        Write-Step 'Removing this tool''s backups...'
        Remove-Item -LiteralPath (Join-Path $logDir 'backups') -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $logDir 'trust-sign.log') -Force -ErrorAction SilentlyContinue

    # Remove stale onefile extraction folders, but only inside this tool's data dir.
    Get-ChildItem -LiteralPath $logDir -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue |
        ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
            catch { Write-Warning "Could not remove $_" }
        }
    Remove-Item -LiteralPath (Join-Path $AppDir '.runtime') -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host ''
    Write-Host 'Cleanup complete.' -ForegroundColor Green
    if ($RemoveFolder) {
        Write-Step 'Scheduling AppDir removal...'
        Start-Process -FilePath 'cmd.exe' -ArgumentList @(
            '/c', "timeout /t 2 /nobreak >nul & rmdir /s /q `"$AppDir`""
        ) -WindowStyle Hidden
    } else {
        Write-Host "Delete the portable folder manually if desired: $AppDir"
    }

    Stop-TranscriptIfNeeded
    if ($Pause) { Read-Host 'Press Enter to close' }
    exit 0
} catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $logPath" -ForegroundColor Yellow
    Stop-TranscriptIfNeeded
    if ($Pause) { Read-Host 'Press Enter to close' }
    exit 1
}
