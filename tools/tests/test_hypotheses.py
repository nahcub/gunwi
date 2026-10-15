"""가설 레지스트리(data/hypotheses.json)가 정직하게 유지되는지 확인한다.

가설은 검증 전 주장이다. 민원 원자료 없이 '지지'로 바뀌거나, 없는 지표에
붙거나, 사분면이 몰래 점수·가중치를 갖게 되는 것을 막는다.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402

HYP = json.loads((ROOT / "data" / "hypotheses.json").read_text(encoding="utf-8"))
REG = {s["id"]: s for s in json.loads(
    (ROOT / "data" / "sources.json").read_text(encoding="utf-8"))["sources"]}


def test_registry_builds():
    out = build.build_hypotheses()
    assert len(out["hypotheses"]) == len(HYP["hypotheses"])


def test_no_hypothesis_is_verified_without_complaint_data():
    """민원 원자료가 미확보인 동안에는 어떤 가설도 '지지'·'기각'일 수 없다."""
    if REG["COMPLAINT_INTERNAL"]["status"] != "미확보":
        pytest.skip("민원 원자료가 들어왔다 - 이 테스트를 새 상태에 맞게 고칠 것")
    for h in HYP["hypotheses"]:
        assert h["status"] == "가설(미검증)", f"{h['id']}: 검증 자료 없이 {h['status']}"


def test_every_hypothesis_says_how_to_verify_and_its_limits():
    for h in HYP["hypotheses"]:
        for key in ("statement", "mechanism", "caveat", "verify_method"):
            assert h[key].strip(), f"{h['id']}: {key} 비어 있음"
        assert h["verify_with"], f"{h['id']}: 검증 자료 없음"


def test_unknown_indicator_is_caught(tmp_path, monkeypatch):
    bad = json.loads(json.dumps(HYP))
    bad["hypotheses"][0]["indicator"] = "complaint_rate"     # 미확보 지표
    path = tmp_path / "hypotheses.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(build, "HYPOTHESES", path)
    with pytest.raises(AssertionError, match="화면에 없는 지표"):
        build.build_hypotheses()


def test_views_carry_no_scores_or_weights():
    """사분면은 위치 표시다. 종합 우선순위(priority_score)를 우회하지 않는다.

    허용된 키 밖의 필드(가중치·점수 등)가 생기면 실패한다.
    """
    allowed = {"id", "kind", "x", "y", "split", "title", "hypotheses",
               "high_high_label", "_note"}
    for v in HYP["views"]:
        extra = set(v) - allowed
        assert not extra, f"{v['id']}: 허용되지 않은 필드 {extra}"
        assert v["kind"] == "quadrant" and v["split"] == "median"


def test_quadrant_high_high_known_regions():
    """원자료가 바뀌면 알아채도록 2025-12 기준 '둘 다 높음' 읍면을 고정한다."""
    v = HYP["views"][0]
    rows = build.build_regions()["regions"]["2025-12"]
    mx = statistics.median(r[v["x"]] for r in rows)
    my = statistics.median(r[v["y"]] for r in rows)
    hh = {r["name"] for r in rows if r[v["x"]] > mx and r[v["y"]] > my}
    assert hh == {"의흥면", "산성면"}


def test_old_ratio_matches_counts():
    for rows in build.build_regions()["regions"].values():
        for r in rows:
            expected = round(r["senior_center_old_count"] / r["senior_center_count"] * 100, 1)
            assert r["senior_center_old_ratio"] == expected
