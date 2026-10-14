"""공개 산출물이 제대로 만들어지는지 확인한다.

핵심은 '누락 감지'다. 기존 저장소에서 레지스트리를 손으로 옮겨 적다가
license / join_key / update_date 필드가 웹 사본 15건 전부에서 증발했다.
공공데이터 출처표시는 의무이므로 그 사고를 테스트로 막는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402

REGISTRY = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))


def test_license_survives_to_public():
    """모든 출처가 웹 산출물에서도 라이선스를 갖고 있어야 한다."""
    out = build.build_sources()
    assert len(out["sources"]) == len(REGISTRY["sources"])
    for s in out["sources"]:
        assert s["license"], f"{s['id']}: license 누락"


def test_public_source_fields_match_registry():
    """웹 사본의 값이 레지스트리와 같아야 한다(손으로 고친 흔적 감지)."""
    out = build.build_sources()
    by_id = {s["id"]: s for s in REGISTRY["sources"]}
    for s in out["sources"]:
        src = by_id[s["id"]]
        for field in build.SOURCE_FIELDS:
            assert s[field] == src.get(field), f"{s['id']}.{field} 불일치"


def test_missing_required_field_is_caught(monkeypatch, tmp_path):
    bad = json.loads(json.dumps(REGISTRY))
    bad["sources"][0].pop("license")
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(build, "REGISTRY", path)
    with pytest.raises(AssertionError, match="필수 필드 누락"):
        build.build_sources()


def test_regions_exclude_gun_total():
    """군 합계 행이 공개 데이터에 섞이면 중복 합산 사고가 난다."""
    out = build.build_regions()
    for period, rows in out["regions"].items():
        assert len(rows) == 8, f"{period}: {len(rows)}개"
        codes = [r["region_code"] for r in rows]
        assert "2772000000" not in codes, f"{period}: 군 합계가 섞였다"
        assert len(set(codes)) == 8


def test_elderly_ratio_is_consistent():
    out = build.build_regions()
    for rows in out["regions"].values():
        for r in rows:
            expected = round(r["elderly"] / r["population"] * 100, 1)
            assert r["elderly_ratio"] == expected
            assert 0 < r["elderly_ratio"] < 100


def test_missing_indicators_have_no_values():
    """원자료가 없는 지표에 값이 채워져 있으면 안 된다."""
    out = build.build_regions()
    blocked = [i["id"] for i in out["indicators"] if i["status"] != "available"]
    assert "priority_score" in blocked
    assert "complaint_rate" in blocked
    for rows in out["regions"].values():
        for r in rows:
            for key in blocked:
                assert key not in r, f"{r['name']}: 미확보 지표 {key} 에 값이 있다"


def test_every_indicator_declares_why_it_is_unavailable():
    for ind in build.INDICATORS:
        if ind["status"] == "available":
            continue
        assert ind.get("blocked_by") or ind.get("reason"), \
            f"{ind['id']}: 왜 못 쓰는지 적혀 있지 않다"


def test_every_available_indicator_has_values():
    """화면에서 고를 수 있는 지표는 8개 읍면 모두 숫자가 있어야 한다."""
    out = build.build_regions()
    available = [i["id"] for i in out["indicators"] if i["status"] == "available"]
    for rows in out["regions"].values():
        for r in rows:
            for key in available:
                assert isinstance(r.get(key), (int, float)), f"{r['name']}.{key} 값 없음"


def test_facility_points_join_to_regions():
    fac = build.build_facilities()
    codes = {r["region_code"] for r in build.build_regions()["regions"]["2025-12"]}
    assert len(fac["senior_centers"]["points"]) == 215
    assert len(fac["drainage_risk"]["points"]) == 27
    for group in fac.values():
        for p in group["points"]:
            assert p["region_code"] in codes


def test_potholes_public_has_points_only():
    """전국 원자료 집계는 공개하지 않고 군위 지점만 내보낸다."""
    pot = build.load("potholes.json")
    assert {p["region_code"] for p in pot["points"]} <= {
        r["region_code"] for r in build.build_regions()["regions"]["2026-08"]}
