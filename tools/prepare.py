"""data/raw -> data/derived

원자료를 검증하고 정제해 derived/에 쓴다. raw/는 절대 수정하지 않는다.
검증에 실패하면 assert로 멈춘다 - 조용히 넘어가지 않는다.

  python tools/prepare.py
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"

# 주민등록 인구 파일이 제공하는 기준시점별 폴더
MOIS_PERIODS = ["2023-12", "2024-12", "2025-12", "2026-08"]

GUNWI_CODE = "2772000000"        # 군 합계 행. 읍면과 절대 함께 더하지 않는다
ELDERLY_FROM_BUCKET = 13         # 5세 구간 인덱스 13 == 65세
SEX_BLOCKS = {"total": 0, "male": 23, "female": 46}
GUNWI_BBOX = (128.3, 35.9, 128.9, 36.5)   # lon_min, lat_min, lon_max, lat_max


def _num(value) -> int:
    return int(str(value).replace(",", "").strip())


def read_meta(folder: str) -> dict:
    meta = json.loads((RAW / folder / "_meta.json").read_text(encoding="utf-8"))
    assert meta.get("provenance"), f"{folder}: provenance 필드 없음"
    return meta


# ---------------------------------------------------------------- 인구

def prepare_population():
    """행정안전부 연령별 인구. 4개 시점 x (군 합계 1 + 읍면 8) = 36행."""
    records = []
    name_by_code = {}

    for period in MOIS_PERIODS:
        folder = f"mois-age-{period}"
        meta = read_meta(folder)
        rows = json.loads((RAW / folder / "age.json").read_text(encoding="utf-8"))

        assert len(rows) == 9, f"{folder}: 9행이어야 하는데 {len(rows)}행"

        gunwi_total = None
        eupmyeon_total = 0
        for row in rows:
            code, name = row[0], row[1]
            nums = [_num(v) for v in row[2:]]
            assert len(nums) == 69, f"{folder}/{name}: 69칸이어야 하는데 {len(nums)}칸"

            # 성별 블록마다 5세 구간 21개의 합이 그 블록 총계와 같아야 한다
            block = {}
            for label, off in SEX_BLOCKS.items():
                buckets = nums[off + 2: off + 23]
                assert len(buckets) == 21
                assert nums[off] == sum(buckets), (
                    f"{folder}/{name}/{label}: 구간합 != 총계")
                block[label] = nums[off]

            assert block["total"] == block["male"] + block["female"], (
                f"{folder}/{name}: 남+여 != 계")

            elderly = sum(nums[2 + ELDERLY_FROM_BUCKET: 2 + 21])
            is_gunwi = code == GUNWI_CODE

            records.append({
                "period": period,
                "reference_date": meta["reference_date"],
                "region_code": code,
                "region_name": name,
                "level": "gun" if is_gunwi else "eupmyeon",
                "population": block["total"],
                "male": block["male"],
                "female": block["female"],
                "elderly": elderly,
            })

            if is_gunwi:
                gunwi_total = block["total"]
            else:
                eupmyeon_total += block["total"]
                name_by_code[code] = name

        assert gunwi_total is not None, f"{folder}: 군 합계 행이 없다"
        assert eupmyeon_total == gunwi_total, (
            f"{folder}: 읍면 합계 {eupmyeon_total} != 군 합계 {gunwi_total}")

    assert len(name_by_code) == 8, f"읍면이 8개가 아님: {len(name_by_code)}"
    assert len(records) == len(MOIS_PERIODS) * 9
    return records, name_by_code


# ---------------------------------------------------------------- 공원

def prepare_parks():
    folder = "datagokr-park-2026-03-05"
    read_meta(folder)
    rows = json.loads((RAW / folder / "parks.json").read_text(encoding="utf-8"))
    header = json.loads((RAW / folder / "header.json").read_text(encoding="utf-8"))
    labels = {h["columCode"]: h["columNm"] for h in header["columList"]}

    assert len({r["MANAGE_NO"] for r in rows}) == len(rows), "관리번호 중복"

    lon_min, lat_min, lon_max, lat_max = GUNWI_BBOX
    parks = []
    for r in rows:
        lon, lat = float(r["LONGITUDE"]), float(r["LATITUDE"])
        assert lon_min <= lon <= lon_max and lat_min <= lat <= lat_max, (
            f"{r['PARK_NM']}: 군위군 범위 밖 좌표 ({lon}, {lat})")
        parks.append({
            "manage_no": r["MANAGE_NO"],
            "name": r["PARK_NM"],
            "category": r["PARK_SE"],
            "address": r["RDNMADR"],
            "lon": lon,
            "lat": lat,
            "area_sqm": float(r["PARK_AR"]) if r["PARK_AR"] else None,
            "reference_date": r["REFERENCE_DATE"],
        })
    return parks, labels


# ---------------------------------------------------------- 행정리 과거인구

def prepare_village_history() -> dict:
    """2008~2021 행정리 인구. 원본 품질 문제를 '보존한 채로' 기록한다."""
    folder = "gunwi-village-population-2008-2021"
    meta = read_meta(folder)
    text = (RAW / folder / "population.csv").read_bytes().decode(meta["encoding"])
    raw_rows = list(csv.reader(io.StringIO(text)))
    header, body = raw_rows[0], raw_rows[1:]

    rows = []
    for r in body:
        rows.append({
            "year": int(r[0]),
            "village": r[1].strip(),
            "male": _num(r[2]),
            "female": _num(r[3]),
            "total": _num(r[4]),
            "households": _num(r[5]),
        })

    sum_mismatch = [x for x in rows if x["male"] + x["female"] != x["total"]]
    dup_keys = Counter((x["year"], x["village"]) for x in rows)
    duplicates = {f"{y}/{v}": n for (y, v), n in dup_keys.items() if n > 1}

    return {
        "_warning": (
            "자동 교정하지 않은 원본이다. 최신 인구 분모로 사용 금지. "
            "읍면코드가 없어 리명만으로 결합 금지."),
        "header": header,
        "row_count": len(rows),
        "years": sorted({x["year"] for x in rows}),
        "sum_mismatch_count": len(sum_mismatch),
        "duplicate_key_count": len(duplicates),
        "duplicate_keys": duplicates,
        "rows": rows,
    }


# ---------------------------------------------------------------- 경계

def prepare_boundary(name_by_code: dict) -> dict:
    """읍면 경계에 region_code를 심는다.

    원본 피처는 ADM_CD(22520111 계열)를 갖는데 인구 데이터의 행정기관코드
    (2772025000 계열)와 다른 체계다. 지역명으로 여기서 한 번만 맞춰 코드를
    심고, 이후 웹에서는 코드만 쓴다 - 런타임 이름 매칭을 없앤다.
    """
    folder = "boundary-eupmyeon-2025-06-30"
    meta = read_meta(folder)
    gj = json.loads((RAW / folder / "eupmyeon.geojson").read_text(encoding="utf-8"))

    assert len(gj["features"]) == 8, (
        f"경계 피처가 8개가 아님: {len(gj['features'])}")

    code_by_name = {v: k for k, v in name_by_code.items()}
    assert len(code_by_name) == 8, "읍면 이름이 중복됨"

    seen = set()
    for feat in gj["features"]:
        props = feat["properties"]
        raw_name = str(props.get("ADM_NM") or props.get("adm_nm") or "")
        name = raw_name.split()[-1] if raw_name else ""
        assert name in code_by_name, f"인구 데이터에 없는 읍면: {raw_name!r}"
        code = code_by_name[name]
        assert code not in seen, f"경계 피처 중복: {name}"
        seen.add(code)
        feat["properties"] = {
            "region_code": code,
            "region_name": name,
            "source_adm_cd": props.get("ADM_CD"),
            "base_date": props.get("BASE_DATE"),
        }

    assert seen == set(name_by_code), "경계와 인구의 읍면 집합이 다름"

    gj["_provenance"] = meta["provenance"]
    if meta["provenance"] != "verified":
        print(f"  ! 경계 출처 미확인 ({meta['provenance']}) "
              "- 화면에 경고가 표시됩니다")
    return gj


# ---------------------------------------------------------------- 포트홀

POTHOLE_FOLDER = "minwon-pothole-2026-10-13"


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    for i in range(len(ring)):
        x1, y1 = ring[i][:2]
        x2, y2 = ring[i - 1][:2]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _in_geometry(lon: float, lat: float, geom: dict) -> bool:
    polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
             else [geom["coordinates"]])
    return any(_in_ring(lon, lat, p[0])
               and not any(_in_ring(lon, lat, hole) for hole in p[1:])
               for p in polys)


def prepare_potholes(boundary: dict) -> dict:
    """전국 포트홀 민원 좌표 중 군위 읍면 경계 안의 것만 남긴다.

    원본 품질 문제(완전중복 행, 쉼표 소수점 좌표)는 고치지 않고 개수만 센다.
    읍면 판정은 prepare_boundary() 가 region_code 를 심은 경계로 여기서 한 번만
    한다 - 웹에서는 region_code 만 쓴다.
    """
    meta = read_meta(POTHOLE_FOLDER)
    with (RAW / POTHOLE_FOLDER / "pothole_all.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    exact_dups = len(rows) - len({(r["create_dt"], r["event_lat"], r["event_lon"])
                                  for r in rows})
    # 전국 5만여 점을 전부 다각형 판정하면 수 분 걸린다 - 경계 외접사각형으로 먼저 거른다
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for sub in c:
                walk(sub)
    for feat in boundary["features"]:
        walk(feat["geometry"]["coordinates"])
    lon_min, lon_max, lat_min, lat_max = min(xs), max(xs), min(ys), max(ys)

    unparsable, points = 0, []
    for r in rows:
        try:
            lat, lon = float(r["event_lat"]), float(r["event_lon"])
        except ValueError:
            unparsable += 1
            continue
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            continue
        hits = [feat["properties"] for feat in boundary["features"]
                if _in_geometry(lon, lat, feat["geometry"])]
        assert len(hits) <= 1, f"두 읍면에 동시에 속하는 좌표: ({lon}, {lat})"
        if hits:
            d = r["create_dt"]
            points.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                "lat": lat,
                "lon": lon,
                "region_code": hits[0]["region_code"],
                "region_name": hits[0]["region_name"],
            })

    points.sort(key=lambda p: (p["date"], p["lat"], p["lon"]))
    dates = sorted(r["create_dt"] for r in rows)
    return {
        "_warning": (
            "표본이 너무 적어 읍면 비교 지표로 쓰지 않는다. 지점 표시 전용. "
            "읍면 판정은 출처 미확인 경계에 의존한다."),
        "source_id": meta["source_id"],
        "period": [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in (dates[0], dates[-1])],
        "boundary_provenance": boundary["_provenance"],
        "national_row_count": len(rows),
        "exact_duplicate_count": exact_dups,
        "unparsable_coord_count": unparsable,
        "points": points,
    }


# ------------------------------------------------------------ 시설 공통

def _read_csv(folder: str, meta: dict) -> list[dict]:
    """_meta.json 에 등록된 CSV 하나를 읽는다. 인코딩은 meta 를 따른다."""
    names = [n for n in meta["files"] if n.endswith(".csv")]
    assert len(names) == 1, f"{folder}: CSV가 하나가 아님 {names}"
    text = (RAW / folder / names[0]).read_bytes().decode(
        meta.get("encoding", "utf-8-sig"))
    return list(csv.DictReader(io.StringIO(text)))


def _region_code_from_address(code_by_name: dict, *addresses: str) -> str:
    """주소의 읍면 토큰으로 region_code 를 정한다 - 빌드 시점에 한 번만.

    도로명·지번 주소가 서로 다른 읍면을 가리키면 멈춘다.
    """
    found = {tok for addr in addresses for tok in (addr or "").split()
             if tok in code_by_name}
    assert len(found) == 1, f"주소에서 읍면을 하나로 정할 수 없음: {addresses} -> {found}"
    return code_by_name[found.pop()]


def _check_bbox(lon: float, lat: float, label: str) -> None:
    lon_min, lat_min, lon_max, lat_max = GUNWI_BBOX
    assert lon_min <= lon <= lon_max and lat_min <= lat <= lat_max, (
        f"{label}: 군위군 범위 밖 좌표 ({lon}, {lat})")


# ---------------------------------------------------------------- 경로당

# 노후 판정 기준 연도. 공식 기준이 아니라 프로젝트 임시값이다 - 확정되면 여기만 바꾼다
SENIOR_OLD_BEFORE_YEAR = 2000


def prepare_senior_centers(name_by_code: dict) -> dict:
    """경로당 215곳에 region_code 와 건립연도를 붙이고 읍면별로 센다."""
    folder = "datagokr-gunwi-senior-2025-12-19"
    meta = read_meta(folder)
    rows = _read_csv(folder, meta)
    code_by_name = {v: k for k, v in name_by_code.items()}

    centers = []
    for i, r in enumerate(rows, start=1):
        label = f"{folder}/{i}행 {r['시설명']}"
        assert r["시설유형"] == "경로당", f"{label}: 시설유형 {r['시설유형']!r}"
        built = r["건립일자"].strip()
        # 원본은 전 행 YYYY-01-01 - 월일은 의미가 없으므로 연도만 쓴다
        assert len(built) == 10 and built.endswith("-01-01"), (
            f"{label}: 건립일자 형식이 바뀜 {built!r}")
        lon, lat = float(r["경도"]), float(r["위도"])
        _check_bbox(lon, lat, label)
        centers.append({
            "name": r["시설명"],
            "region_code": _region_code_from_address(
                code_by_name, r["소재지도로명주소"], r["소재지지번주소"]),
            "address": r["소재지도로명주소"] or r["소재지지번주소"],
            "lon": lon,
            "lat": lat,
            "built_year": int(built[:4]),
            "floor_area_sqm": float(r["건물면적"]) if r["건물면적"] else None,
            "status": r["영업상태명"],
            "reference_date": r["데이터기준일자"],
            "source_row": i,
        })

    assert len({(c["name"], c["address"]) for c in centers}) == len(centers), (
        "경로당 이름+주소 중복")

    by_region = {}
    for code in name_by_code:
        mine = [c for c in centers if c["region_code"] == code]
        by_region[code] = {
            "count": len(mine),
            "old_count": sum(c["built_year"] < SENIOR_OLD_BEFORE_YEAR for c in mine),
        }
    assert sum(v["count"] for v in by_region.values()) == len(centers)

    return {
        "reference_date": meta["reference_date"],
        "provenance": meta["provenance"],
        "old_before_year": SENIOR_OLD_BEFORE_YEAR,
        "_note": "노후 기준 연도는 공식 기준이 아닌 프로젝트 임시값. 건립연도는 연도 정밀도.",
        "by_region": by_region,
        "centers": centers,
    }


# ---------------------------------------------------------------- 배수시설

def prepare_drainage_risk(name_by_code: dict) -> dict:
    """소규모공공시설 위험지정 중 현행 지정된 세천만 배수시설로 쓴다."""
    folder = "datagokr-gunwi-small-facility-risk-2026-07-15"
    meta = read_meta(folder)
    rows = _read_csv(folder, meta)
    code_by_name = {v: k for k, v in name_by_code.items()}

    type_counts = Counter(r["시설유형"] for r in rows)
    streams = [(i, r) for i, r in enumerate(rows, start=1) if r["시설유형"] == "세천"]
    released = [(i, r) for i, r in streams if r["위험시설해제일자"].strip()]

    sites = []
    for i, r in streams:
        if r["위험시설해제일자"].strip():
            continue
        label = f"{folder}/{i}행 {r['시설명']}"
        lon, lat = float(r["경도"]), float(r["위도"])
        _check_bbox(lon, lat, label)
        sites.append({
            "name": r["시설명"],
            "region_code": _region_code_from_address(
                code_by_name, r["소재지도로명주소"], r["소재지지번주소"]),
            "address": r["소재지지번주소"] or r["소재지도로명주소"],
            "lon": lon,
            "lat": lat,
            "designated_on": r["위험시설지정일자"],
            "notice_no": r["위험시설지정고시번호"],
            "length_m": float(r["연장"]) if r["연장"] else None,
            "width_m": float(r["폭"]) if r["폭"] else None,
            "reference_date": r["데이터기준일자"],
            "source_row": i,
        })

    by_region = {code: {"count": sum(s["region_code"] == code for s in sites)}
                 for code in name_by_code}
    assert sum(v["count"] for v in by_region.values()) == len(sites)

    return {
        "reference_date": meta["reference_date"],
        "provenance": meta["provenance"],
        "_note": ("현행 위험지정 세천만 포함. 빗물받이·맨홀 전수대장이 아니며 "
                  "지정사유는 원본에서 전부 공란."),
        "source_type_counts": dict(type_counts),
        "released_excluded": [r["시설명"] for _, r in released],
        "by_region": by_region,
        "sites": sites,
    }


# ---------------------------------------------------------------- main

def main() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)

    population, name_by_code = prepare_population()
    parks, park_labels = prepare_parks()
    history = prepare_village_history()
    boundary = prepare_boundary(name_by_code)
    potholes = prepare_potholes(boundary)
    seniors = prepare_senior_centers(name_by_code)
    drainage = prepare_drainage_risk(name_by_code)

    def write(name: str, obj) -> None:
        path = DERIVED / name
        # 좌표 덩어리는 사람이 읽을 게 아니므로 압축해서 쓴다
        indent = None if name.endswith(".geojson") else 2
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + "\n",
                        encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size:,} bytes)")

    print("PASS: 검증 통과. derived/ 생성:")
    write("population.json", {
        "generated_at": date.today().isoformat(),
        "periods": MOIS_PERIODS,
        "records": population,
    })
    write("parks.json", {"column_labels": park_labels, "parks": parks})
    write("village_history.json", history)
    write("eupmyeon.geojson", boundary)
    write("potholes.json", potholes)
    write("senior_centers.json", seniors)
    write("drainage_risk.json", drainage)

    print(f"\n  인구 {len(population)}행 / 공원 {len(parks)}건 / "
          f"행정리 {history['row_count']}행 "
          f"(합계불일치 {history['sum_mismatch_count']}행, "
          f"중복키 {history['duplicate_key_count']}개)")
    print(f"  포트홀 전국 {potholes['national_row_count']}행 중 군위 "
          f"{len(potholes['points'])}건 "
          f"(완전중복 {potholes['exact_duplicate_count']}행, "
          f"좌표 파싱불가 {potholes['unparsable_coord_count']}행)")
    old = sum(v["old_count"] for v in seniors["by_region"].values())
    print(f"  경로당 {len(seniors['centers'])}곳 "
          f"(노후 {old}곳, {SENIOR_OLD_BEFORE_YEAR}년 이전 - 임시 기준) / "
          f"위험지정 세천 {len(drainage['sites'])}곳 "
          f"(해제 {len(drainage['released_excluded'])}건 제외)")


if __name__ == "__main__":
    main()
