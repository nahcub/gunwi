"""검증 로직이 실제로 살아 있는지 확인한다.

'통과하는지'가 아니라 '망가진 입력에 제대로 터지는지'를 본다.
검증이 죽어 있는데 초록불이 뜨는 상황을 막는 것이 목적이다.
"""
from __future__ import annotations

import json
from collections import Counter
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import prepare  # noqa: E402


# ------------------------------------------------------- 실제 데이터 기대값

def test_pipeline_runs_and_reproduces_known_counts():
    population, name_by_code = prepare.prepare_population()
    assert len(population) == 36          # 4시점 x (군 합계 + 읍면 8)
    assert len(name_by_code) == 8
    assert prepare.GUNWI_CODE not in name_by_code

    parks, _ = prepare.prepare_parks()
    assert len(parks) == 3                # 표준데이터 등록분. 전수가 아니다

    history = prepare.prepare_village_history()
    assert history["row_count"] == 2528
    assert history["sum_mismatch_count"] == 214   # 원본 그대로 보존된 오류
    assert history["duplicate_key_count"] == 56

    boundary = prepare.prepare_boundary(name_by_code)
    assert len(boundary["features"]) == 8


def test_boundary_carries_population_region_code():
    """경계와 인구가 같은 코드 체계로 붙는지. 런타임 이름 매칭을 없앤 부분."""
    _, name_by_code = prepare.prepare_population()
    boundary = prepare.prepare_boundary(name_by_code)
    codes = {f["properties"]["region_code"] for f in boundary["features"]}
    assert codes == set(name_by_code)
    for f in boundary["features"]:
        # 원본 ADM_CD 와는 다른 체계임을 보존해 둔다
        assert f["properties"]["source_adm_cd"] != f["properties"]["region_code"]


def test_every_raw_folder_has_provenance():
    for folder in sorted((ROOT / "data" / "raw").iterdir()):
        if not folder.is_dir():
            continue
        meta = json.loads((folder / "_meta.json").read_text(encoding="utf-8"))
        assert meta.get("provenance"), f"{folder.name}: provenance 없음"
        assert meta.get("files"), f"{folder.name}: files 해시 없음"


# ------------------------------------------------------------ 검증이 터지나

def _age_rows(period="2025-12"):
    path = ROOT / "data" / "raw" / f"mois-age-{period}" / "age.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_row_count_guard(tmp_path, monkeypatch):
    """9행이 아니면 멈춰야 한다."""
    _patch_age(tmp_path, monkeypatch, lambda rows: rows[:8])
    with pytest.raises(AssertionError, match="9행"):
        prepare.prepare_population()


def test_age_bucket_sum_guard(tmp_path, monkeypatch):
    """5세 구간 합계가 총계와 다르면 멈춰야 한다."""
    def corrupt(rows):
        rows[1] = list(rows[1])
        rows[1][4] = "999999"     # 첫 연령구간을 부풀린다
        return rows
    _patch_age(tmp_path, monkeypatch, corrupt)
    with pytest.raises(AssertionError, match="구간합"):
        prepare.prepare_population()


def test_eupmyeon_total_guard(tmp_path, monkeypatch):
    """읍면 합계와 군 합계가 안 맞으면 멈춰야 한다."""
    def corrupt(rows):
        head = list(rows[0])
        nums = [int(str(v).replace(",", "")) for v in head[2:]]
        nums[0] += 10
        nums[2] += 10
        head[2:] = [str(n) for n in nums]
        rows[0] = head
        return rows
    _patch_age(tmp_path, monkeypatch, corrupt)
    with pytest.raises(AssertionError):
        prepare.prepare_population()


def test_park_coordinate_guard(tmp_path, monkeypatch):
    """군위군 범위 밖 좌표는 통과하면 안 된다."""
    src = ROOT / "data" / "raw" / "datagokr-park-2026-03-05"
    dst = tmp_path / "data" / "raw" / "datagokr-park-2026-03-05"
    dst.mkdir(parents=True)
    for name in ("_meta.json", "header.json"):
        (dst / name).write_bytes((src / name).read_bytes())
    parks = json.loads((src / "parks.json").read_text(encoding="utf-8"))
    parks[0]["LATITUDE"] = "37.5665"      # 서울
    (dst / "parks.json").write_text(json.dumps(parks, ensure_ascii=False),
                                    encoding="utf-8")
    monkeypatch.setattr(prepare, "RAW", tmp_path / "data" / "raw")
    with pytest.raises(AssertionError, match="범위 밖"):
        prepare.prepare_parks()


def _patch_age(tmp_path, monkeypatch, corrupt):
    """age.json 한 시점만 망가뜨린 raw 트리를 만들어 RAW 를 가리키게 한다."""
    raw = tmp_path / "data" / "raw"
    for period in prepare.MOIS_PERIODS:
        src = ROOT / "data" / "raw" / f"mois-age-{period}"
        dst = raw / f"mois-age-{period}"
        dst.mkdir(parents=True)
        (dst / "_meta.json").write_bytes((src / "_meta.json").read_bytes())
        rows = json.loads((src / "age.json").read_text(encoding="utf-8"))
        if period == "2025-12":
            rows = corrupt(rows)
        (dst / "age.json").write_text(json.dumps(rows, ensure_ascii=False),
                                      encoding="utf-8")
    monkeypatch.setattr(prepare, "RAW", raw)


# ---------------------------------------------------------------- 포트홀

def _boundary():
    _, name_by_code = prepare.prepare_population()
    return prepare.prepare_boundary(name_by_code)


def test_pothole_known_counts():
    """원본이 바뀌면 알아채도록 숫자를 고정한다. 품질 문제는 교정하지 않는다."""
    out = prepare.prepare_potholes(_boundary())
    assert out["national_row_count"] == 57060
    assert out["exact_duplicate_count"] == 653
    assert out["unparsable_coord_count"] == 2       # 위도 '37,642'
    assert out["period"] == ["2025-01-01", "2026-10-13"]
    by_name = Counter(p["region_name"] for p in out["points"])
    assert by_name == {"우보면": 2, "효령면": 2}


def test_pothole_points_carry_population_region_code():
    _, name_by_code = prepare.prepare_population()
    out = prepare.prepare_potholes(prepare.prepare_boundary(name_by_code))
    for p in out["points"]:
        assert name_by_code[p["region_code"]] == p["region_name"]


def test_point_in_polygon_respects_holes():
    square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    geom = {"type": "Polygon", "coordinates": [square, hole]}
    assert prepare._in_geometry(2, 2, geom)
    assert not prepare._in_geometry(5, 5, geom)
    assert not prepare._in_geometry(11, 5, geom)


# ------------------------------------------------------- 경로당 / 배수시설

def test_senior_center_known_counts():
    """원본이 바뀌면 알아채도록 숫자를 고정한다."""
    _, name_by_code = prepare.prepare_population()
    out = prepare.prepare_senior_centers(name_by_code)
    assert len(out["centers"]) == 215
    assert out["provenance"] == "verified_import"   # 정부 원본 바이트가 아니다
    by_name = {name_by_code[c]: v for c, v in out["by_region"].items()}
    assert by_name["군위읍"] == {"count": 38, "old_count": 8}
    assert by_name["의흥면"] == {"count": 28, "old_count": 8}
    assert sum(v["old_count"] for v in out["by_region"].values()) == 41
    assert set(out["by_region"]) == set(name_by_code)   # 군 합계 코드 없음


def test_drainage_keeps_only_current_streams():
    _, name_by_code = prepare.prepare_population()
    out = prepare.prepare_drainage_risk(name_by_code)
    assert out["source_type_counts"]["세천"] == 28
    assert out["released_excluded"] == ["내량천"]    # 2018-06-05 해제
    assert len(out["sites"]) == 27
    by_name = {name_by_code[c]: v["count"] for c, v in out["by_region"].items()}
    assert by_name["부계면"] == 7


def test_address_must_resolve_to_one_eupmyeon():
    code_by_name = {"군위읍": "2772025000", "부계면": "2772033000"}
    assert prepare._region_code_from_address(
        code_by_name, "대구광역시 군위군 군위읍 동서길 27", "") == "2772025000"
    with pytest.raises(AssertionError, match="하나로 정할 수 없음"):
        prepare._region_code_from_address(code_by_name, "대구광역시 군위군", "")
    with pytest.raises(AssertionError, match="하나로 정할 수 없음"):
        prepare._region_code_from_address(
            code_by_name, "대구광역시 군위군 군위읍 X", "대구광역시 군위군 부계면 Y")


def test_senior_center_coordinate_guard(tmp_path, monkeypatch):
    """군위군 범위 밖 좌표는 통과하면 안 된다."""
    _, name_by_code = prepare.prepare_population()   # RAW 바꾸기 전에 읽는다
    folder = "datagokr-gunwi-senior-2025-12-19"
    src = ROOT / "data" / "raw" / folder
    dst = tmp_path / "data" / "raw" / folder
    dst.mkdir(parents=True)
    (dst / "_meta.json").write_bytes((src / "_meta.json").read_bytes())
    text = (src / "15114136_gunwi.csv").read_bytes().decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    lines[1] = lines[1].replace("36.2363029", "37.5665")   # 서울
    (dst / "15114136_gunwi.csv").write_text("".join(lines), encoding="utf-8-sig")
    monkeypatch.setattr(prepare, "RAW", tmp_path / "data" / "raw")
    with pytest.raises(AssertionError, match="범위 밖"):
        prepare.prepare_senior_centers(name_by_code)
