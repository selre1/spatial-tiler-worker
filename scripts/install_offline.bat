@echo off
setlocal

REM 1) venv 생성
if not exist venv (
  py -3.11 -m venv venv
)

call venv\Scripts\activate

REM 2) 오프라인 설치
python -m pip install -U pip

REM wheelhouse에서만 설치하도록 강제
pip install --no-index --find-links=wheelhouse -r requirements-offline.txt

REM git deps도 wheelhouse에 있으니 여기서 같이 설치
pip install --no-index --find-links=wheelhouse py3dtiles py3dtiles_temporal_extension earclip

REM 3) py3dtilers 자체 설치
pip install -e . --no-deps

echo.
echo install done.
echo Try: ifc-tiler -i ".\test.ifc" -o ".\output" --crs_in EPSG:5186 --crs_out EPSG:4978
endlocal