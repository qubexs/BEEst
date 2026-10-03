#Requires -Version 5.1
<#
  BEEst one-shot setup. Idempotent - safe to re-run (pulls latest, refreshes deps).
  Single-line usage (fresh machine, PowerShell):
    powershell -ExecutionPolicy Bypass -c "iwr -useb https://raw.githubusercontent.com/qubexs/BEEst/master/setup.ps1 | iex"
#>
param(
  [string]$Dir = "$env:USERPROFILE\BEEst",
  [string]$Branch = "master",
  [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = 'qubexs/BEEst'

function Refresh-Path {
  $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $u = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = "$m;$u"
}

function Find-Python {
  foreach ($c in @('python', 'py -3')) {
    try { & cmd /c "$c --version 2>nul" | Out-Null; if ($LASTEXITCODE -eq 0) { return $c } }
    catch { }
  }
  return $null
}

function Ensure-Python {
  $py = Find-Python
  if ($py) { Write-Host "[setup] Python: $(& cmd /c "$py --version 2>nul")"; return $py }
  Write-Host '[setup] Python tiada - pasang automatik...'
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id Python.Python.3 --silent `
      --accept-package-agreements --accept-source-agreements
    Refresh-Path
    $py = Find-Python
    if ($py) { return $py }
  }
  Write-Host '[setup] winget gagal/tiada - muat turun pemasang python.org...'
  $ver = '3.12.10'
  $exe = "$env:TEMP\python-$ver-amd64.exe"
  Invoke-WebRequest -UseBasicParsing `
    -Uri "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe" `
    -OutFile $exe
  Start-Process -FilePath $exe -ArgumentList '/quiet', 'InstallAllUsers=0',
    'PrependPath=1', 'Include_pip=1', 'Include_tcltk=1' -Wait
  Refresh-Path
  $py = Find-Python
  if (-not $py) { throw 'Python masih tidak ditemui selepas pasang. Buka PowerShell baharu dan cuba lagi.' }
  return $py
}

function Ensure-Repo {
  if ((Test-Path "$Dir\.git") -and (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '[setup] Repo sedia ada - tarik terkini...'
    git -C $Dir pull --ff-only 2>$null
    return
  }
  if (Test-Path $Dir) {
    Write-Host "[setup] Guna folder sedia ada: $Dir"
    return
  }
  if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host '[setup] Clone repo...'
    git clone --depth 1 -b $Branch "https://github.com/$Repo.git" $Dir
    return
  }
  Write-Host '[setup] git tiada - muat turun ZIP...'
  $zip = "$env:TEMP\beest.zip"
  Invoke-WebRequest -UseBasicParsing `
    -Uri "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath "$env:TEMP\beest_zip" -Force
  Move-Item "$env:TEMP\beest_zip\BEEst-$Branch" $Dir
}

function Ensure-PathEntry([string]$p) {
  $u = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (($u -split ';') -notcontains $p) {
    [Environment]::SetEnvironmentVariable('Path', "$u;$p", 'User')
    $env:Path = "$env:Path;$p"
    Write-Host "[setup] PATH += $p"
  }
}

# ---------- run ----------
$py = Ensure-Python
try { & cmd /c "$py -c ""import tkinter"" 2>nul" | Out-Null; if ($LASTEXITCODE -ne 0) { throw 'no tkinter' } }
catch { throw 'Python ini tiada tkinter (UI). Pasang semula dari python.org.' }

Ensure-Repo
Set-Location $Dir

# PATH config: python dir + Scripts (covers fresh installs)
try {
  $pyDir = Split-Path (& cmd /c "$py -c ""import sys; print(sys.executable)"" 2>nul" | Select-Object -First 1).Trim()
  if ($pyDir) {
    Ensure-PathEntry $pyDir
    $scripts = Join-Path $pyDir 'Scripts'
    if (Test-Path $scripts) { Ensure-PathEntry $scripts }
  }
} catch { Write-Warning "[setup] PATH auto-config dilangkau: $_" }

Write-Host '[setup] pip install -r requirements.txt ...'
& cmd /c "$py -m pip install --disable-pip-version-check -r requirements.txt"
if ($LASTEXITCODE -ne 0) { throw 'pip install gagal.' }

Write-Host '[setup] SIAP.'
if (-not $NoLaunch) {
  Write-Host '[setup] Buka aplikasi...'
  if ($py -eq 'py -3') { $exe = 'py'; $appArgs = @('-3', 'kp205_viewer.py') }
  else { $exe = $py; $appArgs = @('kp205_viewer.py') }
  Start-Process -FilePath $exe -ArgumentList $appArgs -WorkingDirectory $Dir
}
