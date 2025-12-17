@echo off
setlocal

REM 프로젝트 루트이동
cd /d "%~dp0.."

REM 파이썬 확인
where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python Launcher (py.exe) not found.
  echo         Please install Python 3.11 (x64) and enable "py launcher".
  echo         Or provide a portable Python folder and update this script.
  pause
  exit /b 1
)

REM 파이썬 3.11 버전 확인
py -3.11 -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3.11 not available.
  echo         Install Python 3.11 (x64). Current installed Python versions may be different.
  echo         Tip: run "py -0p" to list installed Pythons.
  pause
  exit /b 1
)

REM 가상환경 venv 생성
if not exist venv (
  py -3.11 -m venv venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
)

call venv\Scripts\activate

REM wheelhouse에서만 설치
pip install --no-index --find-links ./wheelhouse  -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

REM py3dtilers 자체 설치
pip install -e . --no-deps --no-build-isolation
if errorlevel 1 (
  echo [ERROR] pip install -e . failed.
  pause
  exit /b 1
)

echo.
echo install done.
echo Try: (venv) ifc-tiler -i ".\test.ifc" -o ".\output" --crs_in EPSG:5186 --crs_out EPSG:4978
endlocal