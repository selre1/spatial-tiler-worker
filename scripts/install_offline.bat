@echo off
setlocal

REM 프로젝트 루트이동
cd /d "%~dp0.."

REM 1) venv 생성
if not exist venv (
  py -3.11 -m venv venv
)

call venv\Scripts\activate

REM wheelhouse에서만 설치하도록 강제
pip install -r requirements-offline.txt

REM 3) py3dtilers 자체 설치
pip install -e .

echo.
echo install done.
echo Try: ifc-tiler -i ".\test.ifc" -o ".\output" --crs_in EPSG:5186 --crs_out EPSG:4978
endlocal