"""data/derived -> outputs/ 시계열 지표 엑셀 (시트 여러 개) + 시트별 CSV

피드백("읍면 × 시점으로 변화 추이")용. derived 만 읽고 raw 는 읽지 않는다.
기존 결과표(export_excel.py, 2025 한 시점)는 건드리지 않는다.

  python tools/export_timeseries.py
"""
from __future__ import annotations

import csv
import json

from openpyxl import Workbook
from openpyxl.styles import Alignment

from export_excel import DERIVED, OUT, ROOT, SECTION_FONT, _sheet

BASENAME = "군위군_시계열지표"
CSV_DIR = OUT / "시계열"

FIRST_MONTH, LAST_MONTH = "2023-07", "2026-09"     # 월별 인구 전체 기간
YEAR_END = ["2023-12", "2024-12", "2025-12"]       # 연간 증감률은 같은 달(12월)끼리
SENIOR_STD_YEAR = 2025                             # 경로당 표준데이터(2025-12-19)
SUPPLY = [  # (연도, 경로당 출처, 인구 시점) - 경로당과 인구 시점이 맞는 해만
    (2023, "연보", "2023-12"),
    (2025, "표준데이터", "2025-12"),
]
GUN = "군위군 합계"


def load(name: str):
    return json.loads((DERIVED / name).read_text(encoding="utf-8"))


def pct(a: float, b: float) -> float:
    return round((b - a) / a * 100, 2)


def per_1k(count: int, elderly: int) -> float:
    return round(count / elderly * 1000, 2)


def collect() -> dict:
    monthly = load("population_monthly.json")
    pop = {(r["period"], r["region_code"]): r for r in monthly["records"]}
    regions = sorted({(r["region_code"], r["region_name"], r["level"])
                      for r in monthly["records"]},
                     key=lambda x: (x[2] == "gun", x[0]))   # 읍면 8 -> 군 합계 1
    assert [x[2] for x in regions].count("eupmyeon") == 8 and regions[-1][2] == "gun"

    yearly = load("senior_centers_yearly.json")
    senior = {(r["year"], r["region_code"]): r["senior_centers"] for r in yearly["records"]}
    gun_code = regions[-1][0]
    for g in yearly["gun_totals"]:
        senior[(g["year"], gun_code)] = g["senior_centers"]
    std = load("senior_centers.json")["by_region"]
    for code, v in std.items():
        senior[(SENIOR_STD_YEAR, code)] = v["count"]
    senior[(SENIOR_STD_YEAR, gun_code)] = sum(v["count"] for v in std.values())

    drainage = load("drainage_risk.json")
    streams = {code: v["count"] for code, v in drainage["by_region"].items()}
    streams[gun_code] = len(drainage["sites"])

    return {"periods": monthly["periods"], "pop": pop, "regions": regions,
            "years": yearly["years"], "transcribed": yearly["transcribed_years"],
            "senior": senior, "streams": streams, "stream_date": drainage["status_as_of"]}


def _label(region) -> str:
    return GUN if region[2] == "gun" else region[1]


def summary(d: dict) -> tuple[list[str], list[list]]:
    y0, y1 = d["years"][0], d["years"][-1]
    s = SENIOR_STD_YEAR
    header = ["행정구역코드", "읍면명",
              f"총인구_{FIRST_MONTH}", f"총인구_{LAST_MONTH}", "총인구_증감률(%)",
              f"고령화율_{FIRST_MONTH}(%)", f"고령화율_{LAST_MONTH}(%)", "고령화율_변화(%p)",
              f"경로당_{y0}", f"경로당_{y1}", f"경로당_{s}", f"경로당_증감({y0}→{s})",
              f"노인1천명당경로당_{SUPPLY[0][0]}", f"노인1천명당경로당_{SUPPLY[1][0]}",
              "노인1천명당경로당_변화",
              f"위험지정세천_{d['stream_date']}"]
    body = []
    for reg in d["regions"]:
        code = reg[0]
        a, b = d["pop"][(FIRST_MONTH, code)], d["pop"][(LAST_MONTH, code)]
        sup = [per_1k(d["senior"][(y, code)], d["pop"][(p, code)]["elderly"])
               for y, _, p in SUPPLY]
        body.append([code, _label(reg),
                     a["population"], b["population"], pct(a["population"], b["population"]),
                     a["aging_rate"], b["aging_rate"], round(b["aging_rate"] - a["aging_rate"], 2),
                     d["senior"][(y0, code)], d["senior"][(y1, code)], d["senior"][(s, code)],
                     d["senior"][(s, code)] - d["senior"][(y0, code)],
                     sup[0], sup[1], round(sup[1] - sup[0], 2),
                     d["streams"][code]])
    return header, body


def year_end(d: dict) -> tuple[list[str], list[list]]:
    header = ["행정구역코드", "읍면명"]
    for p in YEAR_END:
        header += [f"총인구_{p}", f"65세이상_{p}", f"고령화율_{p}(%)"]
    for prev, cur in zip(YEAR_END, YEAR_END[1:]):
        header += [f"총인구_증감률_{prev[:4]}→{cur[:4]}(%)",
                   f"65세이상_증감률_{prev[:4]}→{cur[:4]}(%)"]
    body = []
    for reg in d["regions"]:
        code = reg[0]
        rows = [d["pop"][(p, code)] for p in YEAR_END]
        row = [code, _label(reg)]
        for r in rows:
            row += [r["population"], r["elderly"], r["aging_rate"]]
        for r0, r1 in zip(rows, rows[1:]):
            row += [pct(r0["population"], r1["population"]), pct(r0["elderly"], r1["elderly"])]
        body.append(row)
    return header, body


def wide(d: dict, key: str) -> tuple[list[str], list[list]]:
    header = ["행정구역코드", "읍면명"] + d["periods"]
    body = [[reg[0], _label(reg)] + [d["pop"][(p, reg[0])][key] for p in d["periods"]]
            for reg in d["regions"]]
    return header, body


def long_rows(d: dict) -> tuple[list[str], list[list]]:
    header = ["시점", "기준일", "행정구역코드", "읍면명", "구분", "총인구", "남", "여",
              "65세이상", "고령화율(%)", "세대수", "세대당인구"]
    body = []
    for p in d["periods"]:
        for reg in d["regions"]:
            r = d["pop"][(p, reg[0])]
            body.append([p, r["reference_date"], reg[0], r["region_name"],
                         "군 합계" if reg[2] == "gun" else "읍면",
                         r["population"], r["male"], r["female"], r["elderly"],
                         r["aging_rate"], r["households"], r["persons_per_household"]])
    return header, body


def senior_years(d: dict) -> tuple[list[str], list[list]]:
    years = d["years"]
    gap = list(range(years[-1] + 1, SENIOR_STD_YEAR))           # 2024: 연보 미발간
    header = (["행정구역코드", "읍면명"]
              + [f"{y}(연보{'·전사' if y in d['transcribed'] else ''})" for y in years]
              + [f"{y}(자료없음)" for y in gap]
              + [f"{SENIOR_STD_YEAR}(표준데이터)"])
    body = [[reg[0], _label(reg)]
            + [d["senior"][(y, reg[0])] for y in years]
            + [None for _ in gap]
            + [d["senior"][(SENIOR_STD_YEAR, reg[0])]]
            for reg in d["regions"]]
    return header, body


def supply(d: dict) -> tuple[list[str], list[list]]:
    header = ["행정구역코드", "읍면명"]
    for y, src, p in SUPPLY:
        header += [f"경로당_{y}({src})", f"65세이상_{p}", f"노인1천명당경로당_{y}"]
    header += ["노인1천명당경로당_변화"]
    body = []
    for reg in d["regions"]:
        code = reg[0]
        row, vals = [code, _label(reg)], []
        for y, _, p in SUPPLY:
            n, e = d["senior"][(y, code)], d["pop"][(p, code)]["elderly"]
            vals.append(per_1k(n, e))
            row += [n, e, vals[-1]]
        body.append(row + [round(vals[1] - vals[0], 2)])
    return header, body


def notes(d: dict) -> list[list]:
    t0, t1 = d["transcribed"][0], d["transcribed"][-1]
    return [
        ["■ 이 파일", ""],
        ["목적", "읍면 × 시점 변화 추이 (인구 증감률, 고령화율 변화, 인구 대비 경로당 공급 수준)"],
        ["기존 결과표와의 관계", "군위군_시설관리우선지역_기초지표_2025.xlsx(2025 한 시점)와 별개. 그 파일은 바꾸지 않았다"],
        ["", ""],
        ["■ 시트", ""],
        ["요약_읍면별", f"핵심표. 인구·고령화율은 {FIRST_MONTH}→{LAST_MONTH}, 경로당은 "
                     f"{d['years'][0]}→{SENIOR_STD_YEAR}, 공급 수준은 2023·2025"],
        ["인구_연말비교", "12월 말끼리 비교한 연간 증감률 (계절 영향 제외)"],
        ["총인구_월별 / 고령화율_월별", f"{FIRST_MONTH}~{LAST_MONTH} 매월. 추이 그래프용 가로 표"],
        ["인구세대_월별(원자료)", "derived/population_monthly.json 그대로 (읍면 8 + 군 합계 1) × 39개월"],
        ["경로당_연도별", f"{d['years'][0]}~{d['years'][-1]} 통계연보, {SENIOR_STD_YEAR} 표준데이터. "
                       "2024 는 연보 미발간(2026-12 예정)이라 빈칸"],
        ["경로당_공급수준", "노인 1천명당 경로당 = 경로당 수 ÷ 65세 이상 인구 × 1,000. "
                         "경로당과 인구 시점이 맞는 해(2023, 2025)만"],
        ["", ""],
        ["■ 출처", ""],
        ["인구·세대", "행정안전부 주민등록 인구통계 (월말 기준)"],
        ["경로당 2014~2023", f"군위통계연보 12장 노인여가복지시설 표의 경로당 시설수. {t0}~{t1} 은 이미지형 "
                           "PDF 를 옮겨 적은 전사본(합계 검사·재판독 확인)"],
        ["경로당 2025", "공공데이터포털 경로당 표준데이터 (2025-12-19, 215곳)"],
        ["위험지정 세천", f"소규모공공시설 위험지정 표준데이터에 {d['stream_date']} 해제 고시 반영 "
                        "(새터천 1곳은 2017 지정분으로 현행 여부 미확인)"],
        ["", ""],
        ["■ 주의", ""],
        ["군 합계 행", "각 표 맨 아래 '군위군 합계' 행을 읍면 8행과 함께 더하지 말 것"],
        ["경로당 출처 차이", "2014~2023(연보)과 2025(표준데이터)는 출처가 다르다. 2023 연보 213곳 vs "
                          "2025 표준데이터 215곳(효령·우보 각 1곳 차이)"],
        ["인구 정의", "모두 주민등록 인구. SGIS 인구와 섞지 말 것"],
        ["증감률", "(나중 값 − 처음 값) ÷ 처음 값 × 100. 고령화율 변화는 %p(차이)"],
        ["", ""],
        ["■ 재현", ""],
        ["코드", "tools/prepare.py (raw → derived) · tools/export_timeseries.py (derived → 이 파일)"],
        ["CSV", f"outputs/시계열/ 에 시트마다 CSV 1개 (UTF-8 BOM)"],
    ]


def sheets() -> list[tuple[str, list[str], list[list]]]:
    d = collect()
    return [
        ("설명", ["구분", "내용"], notes(d)),
        ("요약_읍면별", *summary(d)),
        ("인구_연말비교", *year_end(d)),
        ("총인구_월별", *wide(d, "population")),
        ("고령화율_월별", *wide(d, "aging_rate")),
        ("인구세대_월별(원자료)", *long_rows(d)),
        ("경로당_연도별", *senior_years(d)),
        ("경로당_공급수준", *supply(d)),
    ]


def _text_width(value) -> float:
    # 한글은 영문·숫자의 약 2배 폭
    return sum(2 if ord(ch) > 0x2E80 else 1.1 for ch in str(value))


def _widths(header: list[str], body: list[list]) -> list[float]:
    """열마다 (줄바꿈한 머리글 가장 긴 줄, 값) 중 넓은 쪽에 맞춘다."""
    out = []
    for i, h in enumerate(header):
        longest = max([_text_width(line) for line in h.split("_")]
                      + [_text_width(r[i]) for r in body if r[i] is not None])
        out.append(max(8, longest + 2))
    return out


def _wrap_header(ws, header: list[str]) -> None:
    """엑셀 머리글만 '_' 자리에서 줄을 바꾼다 (CSV 머리글은 그대로)."""
    for cell, h in zip(ws[1], header):
        cell.value = h.replace("_", "\n")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 15 * max(h.count("_") + 1 for h in header) + 4


def main() -> None:
    OUT.mkdir(exist_ok=True)
    CSV_DIR.mkdir(exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    for name, header, body in sheets():
        ws = wb.create_sheet(name)
        if name == "설명":
            _sheet(ws, header, body, [26, 110])
            for row in ws.iter_rows(min_row=2):
                if str(row[0].value or "").startswith("■"):
                    row[0].font = SECTION_FONT
                row[1].alignment = Alignment(wrap_text=True, vertical="top")
        else:
            _sheet(ws, header, body, _widths(header, body))
            _wrap_header(ws, header)
            code_col = header.index("행정구역코드") + 1
            for row in ws.iter_rows(min_row=2, min_col=code_col, max_col=code_col):
                row[0].number_format = "@"          # 코드는 문자열로 둔다
        with open(CSV_DIR / f"{name}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(body)
        print(f"  {name}: {len(body)}행 x {len(header)}열")

    xlsx = OUT / f"{BASENAME}.xlsx"
    wb.save(xlsx)
    print(f"  {xlsx.relative_to(ROOT)}  /  {CSV_DIR.relative_to(ROOT)}/*.csv")


if __name__ == "__main__":
    main()
