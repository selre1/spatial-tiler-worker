# 공간분할 변환도구

## 요약

- 웹 환경에서 대용량 3D BIM 데이터를 효율적으로 렌더링하기 위한 변환 도구입니다.
- OBJ, GeoJSON, IFC 등 다양한 기하학 포맷을 3D Tiles로 생성하여 스트리밍/LOD 기반 시각화를 지원합니다.
---


## Installation from sources

### 윈도우 사용

설치 및 실행

```bash
git clone <repository>
cd spatial-tiler-worker
scripts\install_offline.bat
ifc-tiler -i ".\test.ifc" -o ".\output" --crs_in EPSG:5186 --crs_out EPSG:4978
```

