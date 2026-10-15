"""data/derived + data/sources.json -> public/data

public/에 넣는 것은 인터넷에 공개된다. 이 파일에 적은 것만 공개되고,
적지 않은 것은 derived/에 남는다 - 이 스크립트가 공개 여부를 결정하는 자리다.

정적 파일(html/js/css)은 복사하지 않는다. public/에 이미 있다.

  python tools/build.py
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
REGISTRY = ROOT / "data" / "sources.json"
HYPOTHESES = ROOT / "data" / "hypotheses.json"
OUT = ROOT / "public" / "data"

# 웹 화면에 내보내는 출처 필드. 여기서 뺀 필드는 화면에 안 뜬다.
# license는 공공데이터 출처표시 의무가 있어 반드시 포함한다.
SOURCE_FIELDS = [
    "id", "name", "provider", "url", "reference_date",
    "license", "status", "request_status", "used_for", "notes",
]

# 지표 정의. status가 missing이면 화면에서 비활성으로 표시된다.
# 원자료가 없는 지표에 값을 채우지 않는다 - 비활성이 정직한 상태다.
INDICATORS = [
    {"id": "population", "label": "총인구", "unit": "명",
     "status": "available", "higher_is_worse": False},
    {"id": "elderly_ratio", "label": "고령화율", "unit": "%",
     "status": "available", "higher_is_worse": True},
    # 아래 시설·SGIS 지표는 시점 전환과 무관한 값이다. 기준일은 reference 에 적는다
    {"id": "aging_index", "label": "노령화지수", "unit": "",
     "status": "available", "higher_is_worse": True, "reference": "SGIS 2024"},
    {"id": "density_per_km2", "label": "인구밀도", "unit": "명/㎢",
     "status": "available", "higher_is_worse": False, "reference": "SGIS 2024"},
    {"id": "senior_center_count", "label": "경로당 수", "unit": "개소",
     "status": "available", "higher_is_worse": False, "reference": "2025-12-19"},
    {"id": "senior_center_per_1k_elderly", "label": "고령인구 1천명당 경로당", "unit": "개소",
     "status": "available", "higher_is_worse": False,
     "reference": "경로당 2025-12-19 / 고령인구는 선택 시점"},
    {"id": "senior_center_old_ratio", "label": "노후 경로당 비율", "unit": "%",
     "status": "available", "higher_is_worse": True,
     "reference": "2025-12-19 · 2000년 이전 건립(프로젝트 임시 기준)"},
    {"id": "drainage_risk_count", "label": "위험지정 세천", "unit": "개소",
     "status": "available", "higher_is_worse": True, "reference": "2026-07-15"},
    {"id": "water_supply_rate", "label": "상수도보급률", "unit": "%",
     "status": "available", "higher_is_worse": False, "reference": "2025-12-31"},
    {"id": "complaint_rate", "label": "민원발생률", "unit": "건/천명",
     "status": "missing", "blocked_by": "COMPLAINT_INTERNAL"},
    {"id": "repeat_rate", "label": "반복민원율", "unit": "%",
     "status": "missing", "blocked_by": "COMPLAINT_INTERNAL"},
    {"id": "delay_rate", "label": "처리지연율", "unit": "%",
     "status": "missing", "blocked_by": "COMPLAINT_INTERNAL"},
    {"id": "facility_need", "label": "시설관리 필요도", "unit": "점",
     "status": "missing", "blocked_by": "FACILITY_MAINT_HISTORY"},
    {"id": "priority_score", "label": "종합 우선순위", "unit": "점",
     "status": "blocked",
     "reason": "검증된 가중치 모형이 없다. docs/methodology.md 참고"},
]


def load(name: str):
    return json.loads((DERIVED / name).read_text(encoding="utf-8"))


def build_regions() -> dict:
    """읍면 8개 x 2시점. 군 합계 행은 내보내지 않는다(중복 합산 방지).

    시설·SGIS 값은 시점과 무관하므로 두 시점 행에 같은 값을 붙인다.
    고령인구 1천명당 경로당만 분모가 시점마다 달라진다.
    """
    pop = load("population.json")
    sgis = load("sgis_stats.json")["by_region"]
    seniors = load("senior_centers.json")["by_region"]
    drainage = load("drainage_risk.json")["by_region"]
    water = load("water_supply.json")["by_region"]
    by_period: dict[str, list] = {}

    for rec in pop["records"]:
        if rec["level"] != "eupmyeon":
            continue
        code = rec["region_code"]
        ratio = round(rec["elderly"] / rec["population"] * 100, 1)
        by_period.setdefault(rec["period"], []).append({
            "region_code": code,
            "name": rec["region_name"],
            "population": rec["population"],
            "elderly": rec["elderly"],
            "elderly_ratio": ratio,
            "aging_index": sgis[code]["aging_index"],
            "density_per_km2": sgis[code]["density_per_km2"],
            "senior_center_count": seniors[code]["count"],
            "senior_center_old_count": seniors[code]["old_count"],
            "senior_center_old_ratio": round(
                seniors[code]["old_count"] / seniors[code]["count"] * 100, 1),
            "senior_center_per_1k_elderly": round(
                seniors[code]["count"] / rec["elderly"] * 1000, 1),
            "drainage_risk_count": drainage[code]["count"],
            "water_supply_rate": water[code]["supply_rate_pct"],
        })

    for period, rows in by_period.items():
        assert len(rows) == 8, f"{period}: 읍면이 8개가 아님 ({len(rows)})"
        rows.sort(key=lambda r: r["region_code"])

    periods = pop["periods"]
    return {
        "meta": {
            "generated_at": date.today().isoformat(),
            "periods": periods,
            "default_period": periods[-1],
            "reference_dates": {
                r["period"]: r["reference_date"] for r in pop["records"]
            },
        },
        "indicators": INDICATORS,
        "regions": by_period,
    }


def build_facilities() -> dict:
    """지도 마커용 시설 지점. 화면에 필요한 필드만 골라 내보낸다."""
    seniors = load("senior_centers.json")
    drainage = load("drainage_risk.json")
    return {
        "senior_centers": {
            "reference_date": seniors["reference_date"],
            "old_before_year": seniors["old_before_year"],
            "points": [
                {k: c[k] for k in ("name", "region_code", "lat", "lon", "built_year")}
                for c in seniors["centers"]],
        },
        "drainage_risk": {
            "reference_date": drainage["reference_date"],
            "points": [
                {k: s[k] for k in ("name", "region_code", "lat", "lon", "designated_on")}
                for s in drainage["sites"]],
        },
    }


def build_hypotheses() -> dict:
    """data/hypotheses.json -> 공개용 가설 목록.

    가설은 '지표가 민원과 이렇게 엮일 것이다'라는 미검증 주장이다. 여기서
    지표·출처 id 가 실제로 있는지 검사해, 없는 지표에 가설이 붙는 것을 막는다.
    점수·가중치는 만들지 않는다 - views 의 사분면도 중앙값 위치 표시뿐이다.
    """
    hyp = json.loads(HYPOTHESES.read_text(encoding="utf-8"))
    available = {i["id"] for i in INDICATORS if i["status"] == "available"}
    sources = {s["id"] for s in json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]}
    statuses = set(hyp["status_values"])
    fields = set(hyp["complaint_fields"])

    ids = [h["id"] for h in hyp["hypotheses"]]
    assert len(ids) == len(set(ids)), "가설 id 중복"
    for h in hyp["hypotheses"]:
        assert h["indicator"] in available, f"{h['id']}: 화면에 없는 지표 {h['indicator']}"
        assert h["status"] in statuses, f"{h['id']}: 허용되지 않은 상태 {h['status']}"
        assert h["direction"] in {"+", "-", "±"}, f"{h['id']}: 방향 표기 {h['direction']}"
        assert set(h["complaint_fields"]) <= fields, f"{h['id']}: 없는 민원 분야"
        missing = set(h["verify_with"]) - sources
        assert not missing, f"{h['id']}: sources.json 에 없는 검증 자료 {missing}"
    for e in hyp["evidence"]:
        assert e["source"] in sources, f"{e['id']}: sources.json 에 없는 자료 {e['source']}"
    for v in hyp["views"]:
        assert {v["x"], v["y"]} <= available, f"{v['id']}: 화면에 없는 지표"
        assert set(v["hypotheses"]) <= set(ids), f"{v['id']}: 없는 가설 참조"
        assert v["split"] == "median", f"{v['id']}: 사분면은 중앙값 분할만 쓴다"
    return {k: hyp[k] for k in ("schema_version", "updated_at", "status_values",
                                "complaint_fields", "hypotheses", "evidence", "views")}


def build_sources() -> dict:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    out = []
    for s in reg["sources"]:
        missing = [f for f in ("id", "name", "provider", "license", "status")
                   if not s.get(f)]
        assert not missing, f"{s.get('id')}: 필수 필드 누락 {missing}"
        out.append({f: s.get(f) for f in SOURCE_FIELDS})
    return {
        "schema_version": reg["schema_version"],
        "verified_at": reg["verified_at"],
        "sources": out,
    }


def main() -> None:
    # stale 파일이 배포될 수 없게 매번 비우고 다시 쓴다
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)

    def write(name: str, obj) -> None:
        path = OUT / name
        indent = None if name.endswith(".geojson") else 2
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + "\n",
                        encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size:,} bytes)")

    boundary = load("eupmyeon.geojson")
    parks = load("parks.json")
    potholes = load("potholes.json")

    print("public/data 생성:")
    write("regions.json", build_regions())
    write("eupmyeon.geojson", boundary)
    write("parks.json", {"parks": parks["parks"]})
    # 지점만 공개한다. 전국 원자료와 품질 집계는 derived/에 남는다
    write("potholes.json", {
        "source_id": potholes["source_id"],
        "period": potholes["period"],
        "points": potholes["points"],
    })
    write("facilities.json", build_facilities())
    write("hypotheses.json", build_hypotheses())
    write("sources.json", build_sources())

    if boundary.get("_provenance") != "verified":
        print(f"  ! 경계 출처 {boundary['_provenance']} "
              "- 화면 상단에 경고 배너가 뜹니다")


if __name__ == "__main__":
    main()
