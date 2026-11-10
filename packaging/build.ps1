$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = (Get-Command python).Source
$node = (Get-Command node).Source
$version = '0.1.5'
$stage = Join-Path $PSScriptRoot 'stage'
$dist = Join-Path $root 'dist'

Write-Host '== clean =='
Remove-Item (Join-Path $root 'build') -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $dist -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage, $dist | Out-Null

Write-Host '== build GUI =='
& $python -m PyInstaller `
  --noconfirm --clean --onefile --windowed `
  --name CodexCallIdFix `
  --icon (Join-Path $root 'assets\app.ico') `
  --version-file (Join-Path $PSScriptRoot 'version_gui.txt') `
  --collect-data sv_ttk `
  --distpath $dist `
  --workpath (Join-Path $root 'build\gui') `
  --specpath (Join-Path $root 'build\spec') `
  (Join-Path $root 'gui\app.py')
if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }

Write-Host '== stage payload =='
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'backend'), (Join-Path $stage 'runtime'), (Join-Path $stage 'assets') | Out-Null
Copy-Item (Join-Path $root 'backend\manage.js') (Join-Path $stage 'backend\manage.js')
Copy-Item (Join-Path $root 'backend\server.js') (Join-Path $stage 'backend\server.js')
Copy-Item (Join-Path $root 'backend\rewrite.js') (Join-Path $stage 'backend\rewrite.js')
Copy-Item (Join-Path $root 'backend\start-hidden.vbs') (Join-Path $stage 'backend\start-hidden.vbs')
Copy-Item (Join-Path $root 'backend\callidfix.config.json') (Join-Path $stage 'backend\callidfix.config.json')
Copy-Item (Join-Path $root 'README.md') (Join-Path $stage 'README.md')
Copy-Item (Join-Path $root 'README.zh.md') (Join-Path $stage 'README.zh.md')
Copy-Item (Join-Path $root 'README.zh-Hant.md') (Join-Path $stage 'README.zh-Hant.md')
Copy-Item (Join-Path $root 'AUTHORS.md') (Join-Path $stage 'AUTHORS.md')
Copy-Item (Join-Path $root 'LICENSE') (Join-Path $stage 'LICENSE')
Copy-Item (Join-Path $root 'THIRD_PARTY_NOTICES.md') (Join-Path $stage 'THIRD_PARTY_NOTICES.md')
Copy-Item (Join-Path $root 'SECURITY.md') (Join-Path $stage 'SECURITY.md')
Copy-Item (Join-Path $root 'third_party') (Join-Path $stage 'third_party') -Recurse
Copy-Item (Join-Path $PSScriptRoot 'trust-sign.ps1') (Join-Path $stage 'trust-sign.ps1')
Copy-Item (Join-Path $PSScriptRoot 'trust-sign.cmd') (Join-Path $stage 'trust-sign.cmd')
Copy-Item (Join-Path $PSScriptRoot 'cleanup.ps1') (Join-Path $stage 'cleanup.ps1')
Copy-Item (Join-Path $PSScriptRoot 'cleanup.cmd') (Join-Path $stage 'cleanup.cmd')
Copy-Item (Join-Path $root 'assets\app.ico') (Join-Path $stage 'assets\app.ico')
Copy-Item (Join-Path $root 'assets\app.png') (Join-Path $stage 'assets\app.png')
Copy-Item (Join-Path $dist 'CodexCallIdFix.exe') (Join-Path $stage 'CodexCallIdFix.exe')
Copy-Item $node (Join-Path $stage 'runtime\node.exe')

Write-Host '== build installer =='
& $python -m PyInstaller `
  --noconfirm --clean --onefile --windowed `
  --name "CodexCallIdFix-Setup-$version" `
  --icon (Join-Path $root 'assets\app.ico') `
  --version-file (Join-Path $PSScriptRoot 'version_installer.txt') `
  --collect-data sv_ttk `
  --add-data "$stage;payload" `
  --distpath $dist `
  --workpath (Join-Path $root 'build\setup') `
  --specpath (Join-Path $root 'build\spec') `
  (Join-Path $PSScriptRoot 'installer.py')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }

Write-Host '== portable zip =='
$zip = Join-Path $dist "CodexCallIdFix-$version-portable.zip"
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal -Force

Write-Host '== checksums =='
$setup = Join-Path $dist "CodexCallIdFix-Setup-$version.exe"
Get-FileHash $setup, $zip -Algorithm SHA256 |
  ForEach-Object { "$($_.Hash)  $([System.IO.Path]::GetFileName($_.Path))" } |
  Set-Content -Path (Join-Path $dist 'SHA256SUMS.txt') -Encoding ASCII

Get-ChildItem $dist | Select-Object Name, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 2) } }
