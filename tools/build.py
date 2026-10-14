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
    """읍면 8개 x 2시점. 군 합계 행은 내보내지 않는다(중복 합산 방지)."""
    pop = load("population.json")
    by_period: dict[str, list] = {}

    for rec in pop["records"]:
        if rec["level"] != "eupmyeon":
            continue
        ratio = round(rec["elderly"] / rec["population"] * 100, 1)
        by_period.setdefault(rec["period"], []).append({
            "region_code": rec["region_code"],
            "name": rec["region_name"],
            "population": rec["population"],
            "elderly": rec["elderly"],
            "elderly_ratio": ratio,
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
    write("sources.json", build_sources())

    if boundary.get("_provenance") != "verified":
        print(f"  ! 경계 출처 {boundary['_provenance']} "
              "- 화면 상단에 경고 배너가 뜹니다")


if __name__ == "__main__":
    main()
