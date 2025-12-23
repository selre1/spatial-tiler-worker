@echo off
setlocal

REM 프로젝트 루트이동
cd /d "%~dp0.."

REM 파이썬 3.11 버전 확인
py -3.11 -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 goto NO_PY311

REM 가상환경 venv 생성
if not exist venv (
  py -3.11 -m venv venv
)

call venv\Scripts\activate

REM requirements 의존성을 wheelhouse에서 찾고 설치
pip install --no-index --find-links ./wheelhouse  -r requirements.txt


REM py3dtilers 자체 설치
pip install -e . --no-deps --no-build-isolation

echo.
echo install done.
echo venv/Scripts/activate
echo Try: (venv) ifc-tiler -i ".\test.ifc" -o ".\output" --crs_in EPSG:5186 --crs_out EPSG:4978

endlocal
exit /b 0

:NO_PY311
echo [ERROR] Python 3.11 not available. Install Python 3.11 (x64).
echo         Tip: run "py -0p" to list installed versions.
pause
exit /b 1