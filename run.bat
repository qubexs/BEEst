@echo off
setlocal
cd /d "%~dp0"
title BEEst setup + launch

:: ---------- 1. cari Python ----------
where python >nul 2>nul
if %errorlevel%==0 ( set "PY=python" & goto :havepy )
where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" & goto :havepy )

echo [BEEst] Python tidak ditemui. Cuba pasang automatik...
where winget >nul 2>nul
if not %errorlevel%==0 (
  echo [BEEst] Tiada winget. Sila pasang Python 3.11+ dari:
  echo         https://www.python.org/downloads/
  echo         ^(tandakan "Add python.exe to PATH"^)
  pause
  exit /b 1
)
winget install -e --id Python.Python.3 --silent ^
  --accept-package-agreements --accept-source-agreements
:: PATH baharu: cari semula
where python >nul 2>nul
if %errorlevel%==0 ( set "PY=python" & goto :havepy )
where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" & goto :havepy )
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "C:\Python3*" "C:\Program Files\Python3*") do (
  if exist "%%~D\python.exe" ( set "PY=%%~D\python.exe" & goto :havepy )
)
echo [BEEst] Pemasangan Python gagal dikesan. Tutup tetingkap ini,
echo         buka semula selepas pasang, atau set PATH manual.
pause
exit /b 1

:havepy
:: ---------- 2. semak tkinter (UI) ----------
%PY% -c "import tkinter" >nul 2>nul
if not %errorlevel%==0 (
  echo [BEEst] AMARAN: Python ini tiada tkinter ^(UI tidak boleh dibuka^).
  echo         Pasang semula dari python.org ^(bukan Store minimal^).
  pause
  exit /b 1
)

:: ---------- 3. dependencies ----------
echo [BEEst] Pasang dependencies...
%PY% -m pip install --disable-pip-version-check -r requirements.txt
if not %errorlevel%==0 (
  echo [BEEst] GAGAL: pip install gagal. Semak internet / ralat di atas.
  pause
  exit /b 1
)

:: ---------- 4. launch (login: admin / 7717) ----------
echo [BEEst] Sedia. Buka aplikasi...
%PY% kp205_viewer.py
pause
