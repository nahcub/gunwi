"""시계열 지표 엑셀: 시트 구성과 알려진 값, 군 합계 행 위치를 고정한다."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import export_timeseries as ts  # noqa: E402


def _by_name():
    return {name: (header, body) for name, header, body in ts.sheets()}


def test_sheet_names_and_shapes():
    sheets = _by_name()
    assert list(sheets) == ["설명", "요약_읍면별", "인구_연말비교", "총인구_월별",
                            "고령화율_월별", "인구세대_월별(원자료)", "경로당_연도별",
                            "경로당_공급수준"]
    for name, (header, body) in sheets.items():
        assert all(len(row) == len(header) for row in body), name
        assert len(name) <= 31                         # 엑셀 시트 이름 제한
    assert len(sheets["인구세대_월별(원자료)"][1]) == 351   # 39개월 x 9
    assert len(sheets["총인구_월별"][0]) == 2 + 39


def test_gun_row_is_last_and_separate():
    """군 합계 행은 맨 아래 한 줄. 읍면 8행 합과 같아야 하고 함께 더하면 안 된다."""
    header, body = _by_name()["경로당_연도별"]
    assert [r[1] for r in body][-1] == ts.GUN and len(body) == 9
    for col in range(2, len(header)):
        if body[0][col] is None:                       # 2024 자료없음
            continue
        assert sum(r[col] for r in body[:8]) == body[8][col], header[col]


def test_summary_known_values():
    header, body = _by_name()["요약_읍면별"]
    row = dict(zip(header, next(r for r in body if r[1] == ts.GUN)))
    assert row["총인구_2023-07"] == 23165
    assert row["경로당_2014"] == 203 and row["경로당_2023"] == 213 and row["경로당_2025"] == 215
    assert row["위험지정세천_2026-08-31"] == 6
    assert row["노인1천명당경로당_2023"] == round(213 / 10311 * 1000, 2)
