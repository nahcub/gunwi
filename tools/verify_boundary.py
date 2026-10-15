"""읍면 경계 raw 파일이 SGIS 공식 원본과 같은 도형인지 대조한다.

data/raw/boundary-eupmyeon-2025-06-30/eupmyeon.geojson 은 다운로드 이력 없이
들어온 파일이었다. 이 스크립트로 SGIS 행정구역 경계 원본(공공데이터포털 15129688,
전국 zip 안의 bnd_dong_00_2025_2Q.shp, EPSG:5179)에서 군위군 8개 읍면을 직접 뽑아
위경도로 바꾼 뒤 raw 파일과 읍면별로 비교한다. raw 파일은 읽기만 한다.

  pip install geopandas            # requirements.txt 밖. 이 검증에만 필요
  python tools/verify_boundary.py --shp 경로/bnd_dong_00_2025_2Q.shp

전국 원본 zip(269MB)·shp(135MB)는 저장소에 넣지 않는다. 보관 위치와 해시는
data/raw/sgis-admstat-2025-2q/_meta.json · boundary-eupmyeon-2025-06-30/_meta.json 참고.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "boundary-eupmyeon-2025-06-30" / "eupmyeon.geojson"
SGIS_GUN_PREFIX = "22520"      # SGIS 제공용 코드의 군위군
MIN_IOU = 0.9999               # 이보다 작으면 다른 도형으로 본다


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="읍면 경계 raw 와 SGIS 원본 대조")
    ap.add_argument("--shp", required=True, help="bnd_dong_00_2025_2Q.shp 경로")
    args = ap.parse_args()
    shp = Path(args.shp)

    official = gpd.read_file(shp)
    assert str(official.crs).upper().endswith("5179"), f"좌표계가 EPSG:5179 가 아님: {official.crs}"
    gun = official[official["ADM_CD"].astype(str).str.startswith(SGIS_GUN_PREFIX)]
    assert len(gun) == 8, f"SGIS 원본에서 군위군 읍면이 8개가 아님: {len(gun)}"

    raw = gpd.read_file(RAW).to_crs(4326)
    gun_wgs = gun.to_crs(4326)
    rows, ok = [], True
    for _, r in gun_wgs.iterrows():
        match = raw[raw["ADM_CD"].astype(str) == str(r["ADM_CD"])]
        assert len(match) == 1, f"{r['ADM_NM']}: raw 에서 ADM_CD {r['ADM_CD']} 를 하나로 찾지 못함"
        a, b = r.geometry, match.geometry.iloc[0]
        iou = a.intersection(b).area / a.union(b).area
        gap_m = (gpd.GeoSeries([a], crs=4326).to_crs(5179).iloc[0]
                 .hausdorff_distance(gpd.GeoSeries([b], crs=4326).to_crs(5179).iloc[0]))
        same_attr = (str(match["ADM_NM"].iloc[0]) == str(r["ADM_NM"])
                     and str(match["BASE_DATE"].iloc[0]) == str(r["BASE_DATE"]))
        ok &= iou >= MIN_IOU and same_attr
        rows.append({"adm_cd": str(r["ADM_CD"]), "name": r["ADM_NM"], "iou": round(iou, 6),
                     "max_gap_m": round(gap_m, 2), "same_attributes": same_attr})

    report = {
        "official_shp": shp.name,
        "official_shp_sha256": sha256(shp),
        "official_crs": "EPSG:5179",
        "raw_file": str(RAW.relative_to(ROOT)),
        "raw_sha256": sha256(RAW),
        "min_iou_required": MIN_IOU,
        "result": "PASS" if ok else "FAIL",
        "features": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
