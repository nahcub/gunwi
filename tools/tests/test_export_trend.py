"""읍면별 변화추이 엑셀: 기초지표 파일과 같은 구성(메인·컬럼설명·산출방법 + 부록)인지 고정한다."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import export_timeseries as ts  # noqa: E402
import export_trend as tr  # noqa: E402


def _by_name():
    return {name: (header, body) for name, header, body in tr.sheets()}


def test_sheet_names_and_shapes():
    sheets = _by_name()
    assert list(sheets) == ["시계열지표", "컬럼설명", "산출방법", "부록_인구_연말비교",
                            "부록_총인구_월별", "부록_고령화율_월별", "부록_인구세대_월별",
                            "부록_경로당_연도별", "부록_경로당_공급수준"]
    for name, (header, body) in sheets.items():
        assert all(len(row) == len(header) for row in body), name
        assert len(name) <= 31                         # 엑셀 시트 이름 제한
    assert len(sheets["부록_인구세대_월별"][1]) == 351      # 39개월 x 9


def test_main_table_has_eupmyeon_only_and_every_column_described():
    sheets = _by_name()
    header, body = sheets["시계열지표"]
    assert len(body) == 8 and ts.GUN not in [r[1] for r in body]
    assert [r[0] for r in sheets["컬럼설명"][1]] == header
    assert not any("순위" in h or "등급" in h for h in header)   # 다음 단계에서 정한다


def test_same_numbers_as_timeseries_workbook():
    """구성만 다르고 숫자는 군위군_시계열지표.xlsx 와 같아야 한다."""
    old = {name: (h, b) for name, h, b in ts.sheets()}
    new = _by_name()
    assert old["경로당_연도별"] == new["부록_경로당_연도별"]
    assert old["인구_연말비교"] == new["부록_인구_연말비교"]
    oh, ob = old["요약_읍면별"]
    nh, nb = new["시계열지표"]
    for col in ("총인구_2023-07", "경로당_2014", "경로당_2025", "노인1천명당경로당_2023",
                "위험지정세천_2026-08-31"):
        assert [r[oh.index(col)] for r in ob[:8]] == [r[nh.index(col)] for r in nb], col
