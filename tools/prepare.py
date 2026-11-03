"""data/raw -> data/derived

원자료를 검증하고 정제해 derived/에 쓴다. raw/는 절대 수정하지 않는다.
검증에 실패하면 assert로 멈춘다 - 조용히 넘어가지 않는다.

  python tools/prepare.py
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"

# 주민등록 인구 파일이 제공하는 기준시점별 폴더
# 2023-12·2024-12 는 한때 삭제했다가 변화 추이 분석용으로 커밋 38c9139 에서 복원(sha256 일치)
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

def _read_age(folder: str) -> list[dict]:
    """mois-age 한 시점을 검증해 9행(군 합계 1 + 읍면 8)으로 돌려준다."""
    rows = json.loads((RAW / folder / "age.json").read_text(encoding="utf-8"))

    assert len(rows) == 9, f"{folder}: 9행이어야 하는데 {len(rows)}행"

    out = []
    gunwi_total = None
    eupmyeon_total = 0
    for row in rows:
        # 2023-07(편입 첫 달) 화면은 이름 앞에 '*' 가 붙어 있다
        code, name = row[0], row[1].lstrip("*")
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

        out.append({
            "region_code": code,
            "region_name": name,
            "level": "gun" if code == GUNWI_CODE else "eupmyeon",
            "population": block["total"],
            "male": block["male"],
            "female": block["female"],
            "elderly": sum(nums[2 + ELDERLY_FROM_BUCKET: 2 + 21]),
        })

        if code == GUNWI_CODE:
            gunwi_total = block["total"]
        else:
            eupmyeon_total += block["total"]

    assert gunwi_total is not None, f"{folder}: 군 합계 행이 없다"
    assert eupmyeon_total == gunwi_total, (
        f"{folder}: 읍면 합계 {eupmyeon_total} != 군 합계 {gunwi_total}")
    return out


def prepare_population():
    """행정안전부 연령별 인구. 4개 시점 x (군 합계 1 + 읍면 8) = 36행."""
    records = []
    name_by_code = {}

    for period in MOIS_PERIODS:
        folder = f"mois-age/{period}"
        meta = read_meta(folder)
        for row in _read_age(folder):
            records.append({"period": period,
                            "reference_date": meta["reference_date"], **row})
            if row["level"] == "eupmyeon":
                name_by_code[row["region_code"]] = row["region_name"]

    assert len(name_by_code) == 8, f"읍면이 8개가 아님: {len(name_by_code)}"
    assert len(records) == len(MOIS_PERIODS) * 9
    return records, name_by_code


MONTHLY_FIRST, MONTHLY_LAST = "2023-07", "2026-09"   # 대구 편입 첫 달 ~ 수집 마지막 달


def _months(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def prepare_population_monthly(population: list, name_by_code: dict) -> dict:
    """주민등록 연령별 인구 + 세대수, 매월. 39개월 x (군 합계 1 + 읍면 8) = 351행.

    세대 화면(mois-household)에는 행정기관코드가 없어 같은 달 mois-age 의
    이름·순서·총인구가 모두 맞을 때만 코드를 붙인다.
    """
    periods = _months(MONTHLY_FIRST, MONTHLY_LAST)
    for group in ("mois-age", "mois-household"):
        found = sorted(p.name for p in (RAW / group).iterdir() if p.is_dir())
        assert found == periods, f"{group}: 월 폴더가 {MONTHLY_FIRST}~{MONTHLY_LAST} 와 다르다"

    records = []
    for period in periods:
        age_meta = read_meta(f"mois-age/{period}")
        hh_meta = read_meta(f"mois-household/{period}")
        assert age_meta["reference_date"] == hh_meta["reference_date"], (
            f"{period}: 연령·세대 기준일이 다르다")
        ages = _read_age(f"mois-age/{period}")
        hh_rows = json.loads((RAW / "mois-household" / period / "household.json")
                             .read_text(encoding="utf-8"))
        assert len(hh_rows) == 9, f"mois-household/{period}: 9행이어야 하는데 {len(hh_rows)}행"

        hh_total = 0
        for age, hh in zip(ages, hh_rows):
            # 세대 화면 열: 이름, 총인구, 세대수, 세대당인구, 남, 여, 남여비율
            name = hh[0].lstrip("*")
            where = f"mois-household/{period}/{name}"
            assert name == age["region_name"], f"{where}: 연령 화면과 순서·이름이 다르다"
            if age["level"] == "eupmyeon":
                assert name == name_by_code[age["region_code"]], f"{where}: 코드-이름 대응이 다르다"
            pop, households, male, female = (_num(hh[i]) for i in (1, 2, 4, 5))
            assert (pop, male, female) == (age["population"], age["male"], age["female"]), (
                f"{where}: 연령 화면과 인구가 다르다")
            assert households > 0
            # 화면 값은 끝자리 0 을 뺀다(1.50 -> "1.5")
            assert round(pop / households, 2) == float(hh[3]), f"{where}: 세대당 인구 불일치"
            if age["level"] == "eupmyeon":
                hh_total += households
            else:
                gun_households = households

            records.append({
                "period": period,
                "reference_date": age_meta["reference_date"],
                **age,
                "households": households,
                "aging_rate": round(age["elderly"] / age["population"] * 100, 2),
                "persons_per_household": round(pop / households, 2),
            })
        assert hh_total == gun_households, (
            f"mois-household/{period}: 읍면 세대 합 {hh_total} != 군 {gun_households}")

    # 4개 분석 시점은 population.json 과 값이 같아야 한다 (같은 원자료)
    keys = ("population", "male", "female", "elderly")
    monthly = {(r["period"], r["region_code"]): r for r in records}
    for r in population:
        m = monthly[(r["period"], r["region_code"])]
        assert all(m[k] == r[k] for k in keys), (
            f"{r['period']}/{r['region_name']}: population.json 과 월별 값이 다르다")

    assert len(records) == len(periods) * 9
    return {"periods": periods, "records": records}


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
            "읍면 판정은 boundary_provenance 에 적힌 경계를 따른다."),
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

# 표준데이터(2026-07-15) 이후에 나온 지정해제 고시. 고시문 붙임 표의 세천 행을 현행에서 뺀다
RISK_RELEASE_NOTICE = "gunwi-small-risk-notice/2026-08-31"


def _read_release_notice(folder: str) -> dict:
    """해제 고시문(hwpx) 붙임 표에서 시설명 -> 행 정보.

    hwpx 는 zip 안의 XML 이라 표준 라이브러리로 읽는다. 표 행은
    연번 | 구분 | 명칭 | 위치 | 시점 | 종점 | 해제사유 | 지정일 의 8칸이다.
    """
    meta = read_meta(folder)
    name = next(n for n in meta["files"] if n.endswith(".hwpx"))
    with zipfile.ZipFile(RAW / folder / name) as z:
        xml = z.read("Contents/section0.xml").decode("utf-8")

    def text(s: str) -> str:
        return "".join(re.findall(r"<hp:t>([^<]*)</hp:t>", s)).strip()

    rows = {}
    for tr in re.findall(r"<hp:tr>.*?</hp:tr>", xml, flags=re.S):
        cells = [text(tc) for tc in re.findall(r"<hp:tc.*?</hp:tc>", tr, flags=re.S)]
        if len(cells) != 8 or not cells[0].isdigit():
            continue                      # 머리글 행
        no, kind, fac, loc, start, end, reason, designated = cells
        assert fac not in rows, f"{folder}: 시설명 중복 {fac}"
        rows[fac] = {"no": int(no), "type": kind, "location": loc,
                     "start": start, "end": end, "reason": reason}

    assert [r["no"] for r in rows.values()] == list(range(1, len(rows) + 1)), (
        f"{folder}: 연번이 1부터 이어지지 않는다")
    body = text(xml)
    m = re.search(r"총\s*(\d+)개소 중 (\d+)개소 해제", body)
    assert m and int(m.group(2)) == len(rows), (
        f"{folder}: 본문 해제 개소 수와 붙임 표 행 수({len(rows)})가 다르다")
    notice_no = re.search(r"고시 제\s*(\d{4})\s*[–-]\s*(\d+)\s*호", body)
    return {"notice": f"군위군 고시 제{notice_no.group(1)}-{notice_no.group(2)}호",
            "released_on": meta["reference_date"], "rows": rows}


def prepare_drainage_risk(name_by_code: dict) -> dict:
    """소규모공공시설 위험지정 중 현행 지정된 세천만 배수시설로 쓴다.

    표준데이터의 해제일자로 한 번, 그 뒤에 나온 해제 고시(RISK_RELEASE_NOTICE)로
    한 번 더 거른다.
    """
    folder = "datagokr-gunwi-small-facility-risk-2026-07-15"
    meta = read_meta(folder)
    rows = _read_csv(folder, meta)
    code_by_name = {v: k for k, v in name_by_code.items()}

    type_counts = Counter(r["시설유형"] for r in rows)
    streams = [(i, r) for i, r in enumerate(rows, start=1) if r["시설유형"] == "세천"]
    released = [(i, r) for i, r in streams if r["위험시설해제일자"].strip()]

    notice = _read_release_notice(RISK_RELEASE_NOTICE)
    notice_streams = {k: v for k, v in notice["rows"].items() if v["type"] == "세천"}
    current_by_name = {r["시설명"]: r for _, r in streams if not r["위험시설해제일자"].strip()}
    released_by_notice = []
    for fac, nr in notice_streams.items():
        assert fac in current_by_name, (
            f"{RISK_RELEASE_NOTICE}: 해제 세천 {fac} 이 표준데이터 현행 지정에 없다")
        # 이름만 같은 다른 시설이 아닌지 - 고시 구간 시점·종점 지번 중 하나가 주소 끝과 같아야 한다
        jibun = current_by_name[fac]["소재지지번주소"].split()[-1]
        assert jibun in (nr["start"], nr["end"]), (
            f"{RISK_RELEASE_NOTICE}: {fac} 지번 {jibun} 이 고시 구간({nr['start']}~{nr['end']})과 다르다")
        released_by_notice.append(fac)

    sites = []
    for i, r in streams:
        if r["위험시설해제일자"].strip() or r["시설명"] in notice_streams:
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
        "status_as_of": notice["released_on"],
        "_note": ("현행 위험지정 세천만 포함(표준데이터 2026-07-15 에 2026-08-31 해제 고시 반영). "
                  "빗물받이·맨홀 전수대장이 아니며 지정사유는 원본에서 전부 공란."),
        "source_type_counts": dict(type_counts),
        "released_excluded": [r["시설명"] for _, r in released],
        "released_by_notice": {
            "notice": notice["notice"],
            "released_on": notice["released_on"],
            "streams": released_by_notice,
            "other_type_count": len(notice["rows"]) - len(notice_streams),
        },
        "by_region": by_region,
        "sites": sites,
    }


# ---------------------------------------------------------------- 연도별 경로당 (통계연보)

YEARBOOK_XLSX_EDITIONS = ["62-2021", "63-2022", "64-2023"]   # zip 안 xlsx 로 받은 회차
YEARBOOK_SENIOR_SHEET = "25.노인여가복지시설"
YEARBOOK_SENIOR_COL = 6          # 표의 '경로당 시설수' 열 (0부터)


def _zip_name(info: zipfile.ZipInfo) -> str:
    # 한글 파일명이 UTF-8 플래그 없이 cp949 로 들어 있는 zip 이 섞여 있다
    return info.filename if info.flag_bits & 0x800 else info.filename.encode("cp437").decode("cp949")


def _read_yearbook_senior(edition: str, code_by_name: dict) -> tuple[int, dict, dict]:
    """연보 한 권의 12장 표 25 에서 (기준연도, 읍면별 경로당 수, 연도별 군 합계)."""
    import openpyxl

    folder = f"gunwi-yearbook/{edition}"
    meta = read_meta(folder)
    year = int(edition.split("-")[1])
    zip_file = next(n for n in meta["files"] if n.endswith(".zip"))
    with zipfile.ZipFile(RAW / folder / zip_file) as z:
        info = next(i for i in z.infolist()
                    if _zip_name(i).startswith("12") and "(19~" in _zip_name(i))
        wb = openpyxl.load_workbook(io.BytesIO(z.read(info)), read_only=True, data_only=True)
        rows = [r for r in wb[YEARBOOK_SENIOR_SHEET].iter_rows(values_only=True)]

    header = " ".join(str(c) for r in rows[:6] for c in r if c)
    assert "경로당" in header, f"{folder}: 표 25 머리글에 경로당이 없다"
    gun_totals, by_region = {}, {}
    for r in rows[6:]:                                  # 0~5행은 제목·머리글
        label = r[0]
        if isinstance(label, int):                      # 최근 5년 군 합계 행
            gun_totals[label] = int(r[YEARBOOK_SENIOR_COL])
        elif isinstance(label, str) and "\n" in label:  # 읍면 행: '군 위 읍\nGunwi-eup'
            name = label.split("\n")[0].replace(" ", "")
            assert name in code_by_name, f"{folder}: 모르는 읍면 {name}"
            by_region[code_by_name[name]] = int(r[YEARBOOK_SENIOR_COL])

    assert len(by_region) == 8, f"{folder}: 읍면 {len(by_region)}개"
    assert max(gun_totals) == year, f"{folder}: 마지막 군 합계 연도 {max(gun_totals)} != {year}"
    assert sum(by_region.values()) == gun_totals[year], (
        f"{folder}: 읍면 합 {sum(by_region.values())} != 군 합계 {gun_totals[year]}")
    return year, by_region, gun_totals


YEARBOOK_SENIOR_TRANSCRIBED = "gunwi-yearbook-senior-transcribed-2014-2020"
OLD_EUPMYEON_NAMES = {"고로면": "삼국유사면"}   # 2021-01 개칭. 경계는 같은 것으로 본다


def _read_transcribed_senior(code_by_name: dict) -> list[tuple]:
    """이미지형 PDF(제55~61회)에서 옮겨 적은 표 -> 회차별 (출처, True, 연도, 읍면값, 군합계)."""
    folder = YEARBOOK_SENIOR_TRANSCRIBED
    meta = read_meta(folder)
    assert meta["provenance"] == "transcribed", f"{folder}: 전사본 표시가 없다"
    by_edition = {}
    for r in _read_csv(folder, meta):
        source = r["원본폴더"]
        assert (RAW / source / r["원본파일"]).is_file(), f"{folder}: 원본 {source}/{r['원본파일']} 없음"
        year = int(r["기준연도"])
        ed = by_edition.setdefault(source, (year, {}, {}))
        assert ed[0] == year, f"{folder}: {source} 기준연도가 섞여 있다"
        value = int(r["경로당시설수"])
        if r["행구분"] == "군합계":
            ed[2][int(r["연도"])] = value
        else:
            assert r["행구분"] == "읍면" and int(r["연도"]) == year
            name = OLD_EUPMYEON_NAMES.get(r["지역명"], r["지역명"])
            assert name in code_by_name, f"{folder}: 모르는 읍면 {r['지역명']}"
            ed[1][code_by_name[name]] = value

    out = []
    for source, (year, by_region, totals) in sorted(by_edition.items()):
        assert len(by_region) == 8, f"{folder}/{source}: 읍면 {len(by_region)}개"
        assert max(totals) == year
        assert sum(by_region.values()) == totals[year], (
            f"{folder}/{source}: 읍면 합 {sum(by_region.values())} != 군 합계 {totals[year]}")
        out.append((source, True, year, by_region, totals))
    return out


def prepare_senior_centers_yearly(name_by_code: dict) -> dict:
    """군위통계연보 '노인여가복지시설' 표의 경로당 수, 읍면 x 연도.

    한 권에 그해 읍면별 값 + 최근 5년 군 합계가 실린다. 군 합계는 여러 권에
    겹쳐 나오므로 겹치는 해의 값이 같은지 검사한다. 2014~2020 판(이미지형 PDF)은
    사람이 옮겨 적은 표(YEARBOOK_SENIOR_TRANSCRIBED)로 읽는다.
    """
    code_by_name = {v: k for k, v in name_by_code.items()}
    records, gun = [], {}
    editions = _read_transcribed_senior(code_by_name) + [
        (f"gunwi-yearbook/{e}", False, *_read_yearbook_senior(e, code_by_name))
        for e in YEARBOOK_XLSX_EDITIONS]
    for source, transcribed, year, by_region, totals in editions:
        edition = source
        for code in name_by_code:
            records.append({"year": year, "region_code": code,
                            "region_name": name_by_code[code],
                            "senior_centers": by_region[code],
                            "source": source, "transcribed": transcribed})
        for y, v in totals.items():
            if y in gun:
                assert gun[y]["senior_centers"] == v, (
                    f"{edition}: {y}년 군 합계 {v} 가 앞 회차 {gun[y]['senior_centers']} 와 다르다")
            gun[y] = {"year": y, "senior_centers": v, "source": source}

    years = sorted({r["year"] for r in records})
    assert years == list(range(years[0], years[-1] + 1)), f"연도가 비어 있다: {years}"

    return {
        "_note": ("군위통계연보 12장 노인여가복지시설 표의 경로당 시설수. 표준데이터 "
                  "(senior_centers.json, 2025-12-19)와 출처가 달라 한 추이로 잇기 전 확인할 것."),
        "transcribed_years": sorted({r["year"] for r in records if r["transcribed"]}),
        "years": years,
        "records": records,
        "gun_totals": [gun[y] for y in sorted(gun)],
    }


# ---------------------------------------------------------------- 상수도

def prepare_water_supply(name_by_code: dict) -> dict:
    """읍면별 상수도보급률(%). 원본 8행, 군 합계 행 없음."""
    folder = "datagokr-gunwi-water-supply-rate-2025-12-31"
    meta = read_meta(folder)
    rows = _read_csv(folder, meta)
    code_by_name = {v: k for k, v in name_by_code.items()}

    rate_col = "상수도보급률(2025년 12월말 기준)"
    assert len(rows) == 8, f"{folder}: 8행이어야 하는데 {len(rows)}행"
    assert rate_col in rows[0], f"{folder}: 컬럼명이 바뀜 {list(rows[0])}"

    by_region = {}
    for r in rows:
        name = r["읍면명"].strip()
        assert name in code_by_name, f"{folder}: 인구 데이터에 없는 읍면 {name!r}"
        rate = float(r[rate_col])
        assert 0 <= rate <= 100, f"{folder}/{name}: 보급률 범위 밖 {rate}"
        by_region[code_by_name[name]] = {"supply_rate_pct": rate}
    assert set(by_region) == set(name_by_code), "상수도 읍면 집합이 인구와 다름"

    return {
        "reference_date": meta["reference_date"],
        "provenance": meta["provenance"],
        "_note": "읍면별 상수도보급률(%). 군 전체 값은 원본에 없고, 읍면 값을 평균하지 말 것(인구 가중 아님).",
        "by_region": by_region,
    }


# ---------------------------------------------------------------- SGIS 통계

SGIS_FOLDER = "sgis-admstat-2025-2q"
SGIS_GUN_CODE = "22520"           # SGIS 체계의 군 합계 코드
# 파일명이 의미를 정해 주는 총괄 항목만 쓴다. 건축년도·주택유형·연건평 등
# 주택 세부 항목은 사유 재산이라 공공시설 관리 분석 범위 밖이므로 쓰지 않는다.
SGIS_ITEMS = {
    # 항목코드: (파일명 접미, 출력 키, 단위, 읍면합 == 군합 검사 여부)
    "to_in_001": ("인구총괄(총인구)", "population", "명", True),
    "to_in_002": ("인구총괄(평균나이)", "avg_age", "세", False),
    "to_in_003": ("인구총괄(인구밀도)", "density_per_km2", "명/㎢", False),
    "to_in_004": ("인구총괄(노령화지수)", "aging_index", "유소년 100명당 고령인구", False),
    "to_in_005": ("인구총괄(노년부양비)", "old_dependency", "생산연령 100명당 고령인구", False),
    "to_in_006": ("인구총괄(유년부양비)", "young_dependency", "생산연령 100명당 유소년", False),
    "to_ga_001": ("가구총괄", "households", "가구", True),
    "to_ho_001": ("주택총괄_총주택(거처)수", "houses", "호", True),
    "to_fa_010": ("산업분류별(11차_대분류)_총괄사업체수", "businesses", "개", True),
    "to_em_020": ("산업분류별(11차_대분류)_총괄종사자수", "employees", "명", True),
}
# SGIS 인구(등록센서스)와 주민등록 인구는 정의가 달라 같지 않다. 매핑이
# 뒤바뀌면 수배 차이가 나므로 이 정도 허용 폭이면 뒤바뀜만 잡는다.
SGIS_POP_TOLERANCE = 0.15


def prepare_sgis_stats(boundary: dict, population: list) -> dict:
    """SGIS 행정구역 통계(2024년)를 읍면별로 정리한다.

    SGIS 코드(22520111 계열)는 경계 원본 ADM_CD 와 같은 체계다. prepare_boundary()
    가 심어 둔 source_adm_cd -> region_code 대응을 그대로 써서, 코드 변환을
    한 곳에만 둔다.
    """
    meta = read_meta(SGIS_FOLDER)
    region_by_sgis = {f["properties"]["source_adm_cd"]: f["properties"]["region_code"]
                      for f in boundary["features"]}
    assert len(region_by_sgis) == 8, "경계에서 SGIS 코드 8개를 얻지 못함"

    by_region = {code: {} for code in region_by_sgis.values()}
    gun = {}
    na_cells = []
    for item, (suffix, key, _unit, additive) in SGIS_ITEMS.items():
        name = f"2025년기준_2024년_{suffix}.csv"
        assert name in meta["files"], f"{SGIS_FOLDER}: _meta.json 에 없는 파일 {name}"
        text = (RAW / SGIS_FOLDER / name).read_bytes().decode(meta["encoding"])
        rows = [r for r in csv.DictReader(io.StringIO(text)) if r["통계항목"] == item]
        assert {r["기준연도"] for r in rows} == {"2024"}, f"{name}: 기준연도가 2024가 아님"
        codes = [r["행정구역코드"] for r in rows]
        assert sorted(codes) == sorted([SGIS_GUN_CODE, *region_by_sgis]), (
            f"{name}: 지역코드가 군 1 + 읍면 8 이 아님 {codes}")

        for r in rows:
            raw = r["통계값"].strip()
            # N/A 는 비공개(소수 셀) 표시다. 0 으로 바꾸지 않는다
            value = None if raw == "N/A" else (int(raw) if additive else float(raw))
            if value is None:
                na_cells.append(f"{r['행정구역코드']}/{item}")
            if r["행정구역코드"] == SGIS_GUN_CODE:
                gun[key] = value
            else:
                by_region[region_by_sgis[r["행정구역코드"]]][key] = value

        if additive:
            parts = [by_region[c][key] for c in by_region]
            if None not in parts and gun[key] is not None:
                assert sum(parts) == gun[key], (
                    f"{name}: 읍면 합 {sum(parts)} != 군 합계 {gun[key]}")

    # 매핑 검산: 분석 기준 시점(2025-12) 주민등록 인구와 크게 다르면 코드가 뒤바뀐 것
    mois = {r["region_code"]: r["population"] for r in population
            if r["period"] == "2025-12"}
    for code, v in by_region.items():
        gap = abs(v["population"] - mois[code]) / mois[code]
        assert gap <= SGIS_POP_TOLERANCE, (
            f"SGIS {code}: 인구 {v['population']:.0f} vs 주민등록 {mois[code]} "
            f"({gap:.0%} 차이) - 코드 매핑 확인")

    return {
        "reference_date": "2024-12-31",
        "provenance": meta["provenance"],
        "_note": ("SGIS 등록센서스 기반 2024년 통계. 인구는 주민등록 인구와 정의가 달라 "
                  "값이 다르다 - 섞어 쓰지 말 것. 주택 세부 항목(건축년도 등)은 "
                  "사유 재산이라 분석 범위 밖으로 제외."),
        "items": {key: {"sgis_code": item, "label": suffix, "unit": unit}
                  for item, (suffix, key, unit, _) in SGIS_ITEMS.items()},
        "na_cells": na_cells,
        "gun_total": gun,
        "by_region": by_region,
    }


# ---------------------------------------------------------------- 살피소 제보

SALPISO_FOLDER = "daegu-salpiso-reports-2024-11-27"
SALPISO_FIELDS = ["건축건설", "도로시설", "교통시설", "각종시설물", "환경청소",
                  "공원녹지", "광고물", "현수막", "도로적치물", "기타"]


def prepare_salpiso() -> dict:
    """대구 살피소 제보 처리현황. 처리기관 14행, 읍면 구분 없음 - 보고서 배경 수치용.

    읍면 비교 지표로 쓰지 않는다. 군위군 1행의 분야 구성과 대구 전체 구성을
    나란히 보여 주는 데만 쓴다. '대구광역시' 행은 시 합계가 아니라 본청 몫이다.
    """
    meta = read_meta(SALPISO_FOLDER)
    rows = _read_csv(SALPISO_FOLDER, meta)
    assert len(rows) == 14, f"{SALPISO_FOLDER}: 14행이어야 하는데 {len(rows)}행"
    assert list(rows[0])[5:] == SALPISO_FIELDS, f"{SALPISO_FOLDER}: 분야 컬럼이 바뀜"

    agencies = []
    for r in rows:
        n = {k: _num(v) for k, v in r.items() if k != "구분"}
        # 처리상태 합과 분야 합이 각각 제보 수와 같아야 한다
        assert n["제보"] == n["처리"] + n["미처리"] + n["반송"], f"{r['구분']}: 처리상태 합 != 제보"
        assert n["제보"] == sum(n[f] for f in SALPISO_FIELDS), f"{r['구분']}: 분야 합 != 제보"
        agencies.append({
            "agency": r["구분"],
            "reports": n["제보"],
            "status": {k: n[k] for k in ("처리", "미처리", "반송")},
            "by_field": {f: n[f] for f in SALPISO_FIELDS},
        })

    names = [a["agency"] for a in agencies]
    assert names.count("군위군") == 1, "군위군 행이 하나가 아님"
    all_fields = {f: sum(a["by_field"][f] for a in agencies) for f in SALPISO_FIELDS}

    return {
        "reference_date": meta["reference_date"],
        "provenance": meta["provenance"],
        "_note": ("처리기관 단위 집계. 읍면 구분·좌표 없음 - 읍면 비교 지표로 쓰지 않는다. "
                  "'대구광역시' 행은 본청 몫이며 대구 전체는 14행 합. 집계 연도 미확정."),
        "fields": SALPISO_FIELDS,
        "gunwi": next(a for a in agencies if a["agency"] == "군위군"),
        "daegu_all": {"reports": sum(a["reports"] for a in agencies), "by_field": all_fields},
        "agencies": agencies,
    }


# ---------------------------------------------------------------- main

def main() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)

    population, name_by_code = prepare_population()
    monthly = prepare_population_monthly(population, name_by_code)
    parks, park_labels = prepare_parks()
    boundary = prepare_boundary(name_by_code)
    potholes = prepare_potholes(boundary)
    seniors = prepare_senior_centers(name_by_code)
    seniors_yearly = prepare_senior_centers_yearly(name_by_code)
    drainage = prepare_drainage_risk(name_by_code)
    water = prepare_water_supply(name_by_code)
    sgis = prepare_sgis_stats(boundary, population)
    salpiso = prepare_salpiso()

    def write(name: str, obj) -> None:
        path = DERIVED / name
        # 좌표 덩어리는 사람이 읽을 게 아니므로 압축해서 쓴다
        indent = None if name.endswith(".geojson") else 2
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + "\n",
                        encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size:,} bytes)")

    print("PASS: 검증 통과. derived/ 생성:")
    # 실행 날짜를 넣지 않는다 - CI 가 derived 재생성 결과를 커밋과 바이트 비교하므로
    # 같은 raw 에서는 언제 돌려도 같은 파일이 나와야 한다
    write("population.json", {
        "periods": MOIS_PERIODS,
        "records": population,
    })
    write("population_monthly.json", monthly)
    write("parks.json", {"column_labels": park_labels, "parks": parks})
    write("eupmyeon.geojson", boundary)
    write("potholes.json", potholes)
    write("senior_centers.json", seniors)
    write("senior_centers_yearly.json", seniors_yearly)
    write("drainage_risk.json", drainage)
    write("water_supply.json", water)
    write("sgis_stats.json", sgis)
    write("salpiso.json", salpiso)

    print(f"\n  인구 {len(population)}행 / 월별 인구·세대 {len(monthly['records'])}행 "
          f"({monthly['periods'][0]}~{monthly['periods'][-1]}) / 공원 {len(parks)}건")
    print(f"  포트홀 전국 {potholes['national_row_count']}행 중 군위 "
          f"{len(potholes['points'])}건 "
          f"(완전중복 {potholes['exact_duplicate_count']}행, "
          f"좌표 파싱불가 {potholes['unparsable_coord_count']}행)")
    old = sum(v["old_count"] for v in seniors["by_region"].values())
    print(f"  경로당 {len(seniors['centers'])}곳 "
          f"(노후 {old}곳, {SENIOR_OLD_BEFORE_YEAR}년 이전 - 임시 기준) / "
          f"위험지정 세천 {len(drainage['sites'])}곳 "
          f"(해제 {len(drainage['released_excluded'])}건 + "
          f"{drainage['released_by_notice']['released_on']} 고시 해제 "
          f"{len(drainage['released_by_notice']['streams'])}건 제외)")
    print(f"  상수도보급률 읍면 {len(water['by_region'])}개 / "
          f"SGIS 2024 항목 {len(sgis['items'])}개 x 읍면 {len(sgis['by_region'])}개 "
          f"(N/A {len(sgis['na_cells'])}칸)")
    print(f"  살피소 제보 처리기관 {len(salpiso['agencies'])}행 "
          f"(군위군 {salpiso['gunwi']['reports']}건, 대구 전체 {salpiso['daegu_all']['reports']:,}건)")


if __name__ == "__main__":
    main()
