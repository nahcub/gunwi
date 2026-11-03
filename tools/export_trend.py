"""data/derived -> outputs/ 읍면별 변화추이 엑셀 (기초지표 파일과 같은 구성)

메인 표(읍면 8행 한 장) · 컬럼설명 · 산출방법 + 부록 6개. 숫자는
export_timeseries.py(군위군_시계열지표.xlsx)와 같고 구성만 다르다. 그 파일은 그대로 둔다.
지표별 순위·등급·종합점수는 넣지 않는다(다음 단계에서 정한다).

  python tools/export_trend.py
"""
from __future__ import annotations

import csv

from openpyxl import Workbook
from openpyxl.styles import Alignment

from export_excel import OUT, ROOT, SECTION_FONT, _sheet
from export_timeseries import (FIRST_MONTH, LAST_MONTH, SENIOR_STD_YEAR, SUPPLY, YEAR_END,
                               _widths, _wrap_header, collect, long_rows, pct, per_1k,
                               senior_years, supply, wide, year_end)

BASENAME = "군위군_읍면별_변화추이"
CSV_DIR = OUT / "변화추이"


def main_table(d: dict) -> tuple[list[tuple], list[list]]:
    """메인 시트: 읍면 8행 x 지표. 열 정의(컬럼명, 자료형, 단위, 설명)와 값을 함께 만든다.

    군 합계 행은 넣지 않는다(읍면과 함께 더하는 실수 방지) - 부록 시트 맨 아래에 있다.
    지표별 순위·등급·종합점수는 넣지 않는다.
    """
    y0, y1, s = d["years"][0], d["years"][-1], SENIOR_STD_YEAR
    pts = [FIRST_MONTH] + YEAR_END + [LAST_MONTH]
    cols = [
        ("행정구역코드", "문자열", "", "행정안전부 행정기관코드 10자리. 조인키. 정수로 바꾸면 조인이 깨진다",
         lambda c, p: c),
        ("읍면명", "문자열", "", "읍·면 이름", None),
    ]
    for p in pts:
        cols.append((f"총인구_{p}", "정수", "명", f"{p} 말 주민등록 인구 (행정안전부)",
                     lambda c, p_, k=p: d["pop"][(k, c)]["population"]))
    cols.append((f"총인구_증감률_{FIRST_MONTH}→{LAST_MONTH}", "실수", "%",
                 "(나중 − 처음) ÷ 처음 × 100. 전체 기간",
                 lambda c, p: pct(p[FIRST_MONTH]["population"], p[LAST_MONTH]["population"])))
    for a, b in zip(YEAR_END, YEAR_END[1:]):
        cols.append((f"총인구_증감률_{a[:4]}→{b[:4]}", "실수", "%", f"{a}→{b}, 같은 달(12월)끼리 비교",
                     lambda c, p, a=a, b=b: pct(p[a]["population"], p[b]["population"])))
    for k in (FIRST_MONTH, LAST_MONTH):
        cols.append((f"65세이상_{k}", "정수", "명", f"{k} 말 주민등록 65세 이상 인구",
                     lambda c, p, k=k: p[k]["elderly"]))
    cols.append((f"65세이상_증감률_{FIRST_MONTH}→{LAST_MONTH}", "실수", "%", "(나중 − 처음) ÷ 처음 × 100",
                 lambda c, p: pct(p[FIRST_MONTH]["elderly"], p[LAST_MONTH]["elderly"])))
    for k in pts:
        cols.append((f"고령화율_{k}", "실수", "%", f"{k} 65세 이상 ÷ 총인구 × 100",
                     lambda c, p, k=k: p[k]["aging_rate"]))
    cols.append((f"고령화율_변화_{FIRST_MONTH}→{LAST_MONTH}", "실수", "%p", "고령화율 차이(나중 − 처음)",
                 lambda c, p: round(p[LAST_MONTH]["aging_rate"] - p[FIRST_MONTH]["aging_rate"], 2)))
    for k in (FIRST_MONTH, LAST_MONTH):
        cols.append((f"세대수_{k}", "정수", "세대", f"{k} 말 주민등록 세대수",
                     lambda c, p, k=k: p[k]["households"]))
    cols.append((f"세대당인구_{LAST_MONTH}", "실수", "명", "총인구 ÷ 세대수",
                 lambda c, p: p[LAST_MONTH]["persons_per_household"]))
    for y, src in ((y0, "통계연보(전사)"), (y1, "통계연보"), (s, "경로당 표준데이터 2025-12-19")):
        cols.append((f"경로당_{y}", "정수", "개소", f"{y}년 읍면별 경로당 수. 출처 {src}",
                     lambda c, p, y=y: d["senior"][(y, c)]))
    cols.append((f"경로당_증감_{y0}→{s}", "정수", "개소",
                 f"{s} − {y0}. 출처가 다르다({y0} 연보, {s} 표준데이터)",
                 lambda c, p: d["senior"][(s, c)] - d["senior"][(y0, c)]))
    for y, src, k in SUPPLY:
        cols.append((f"노인1천명당경로당_{y}", "실수", "개소",
                     f"경로당({src}) ÷ {k} 65세 이상 × 1,000",
                     lambda c, p, y=y, k=k: per_1k(d["senior"][(y, c)], p[k]["elderly"])))
    cols.append((f"노인1천명당경로당_변화_{SUPPLY[0][0]}→{SUPPLY[1][0]}", "실수", "개소",
                 "나중 − 처음. 음수면 노인 증가가 경로당 증가보다 빠르다",
                 lambda c, p: round(per_1k(d["senior"][(SUPPLY[1][0], c)], p[SUPPLY[1][2]]["elderly"])
                                    - per_1k(d["senior"][(SUPPLY[0][0], c)], p[SUPPLY[0][2]]["elderly"]), 2)))
    cols.append((f"위험지정세천_{d['stream_date']}", "정수", "개소",
                 f"현행 위험지정 세천(표준데이터 2026-07-15 + {d['stream_date']} 해제 고시). 한 시점. "
                 "새터천 1곳은 2017 지정분으로 현행 여부 미확인",
                 lambda c, p: d["streams"][c]))

    body = []
    for reg in d["regions"]:
        if reg[2] == "gun":
            continue
        code = reg[0]
        p = {k: d["pop"][(k, code)] for k in d["periods"]}
        body.append([reg[1] if fn is None else fn(code, p) for *_, fn in cols])
    assert len(body) == 8
    return [c[:4] for c in cols], body


def method_rows(d: dict) -> list[list]:
    t0, t1 = d["transcribed"][0], d["transcribed"][-1]
    return [
        ["■ 개요", ""],
        ["데이터셋", "대구광역시 군위군 읍면별 시계열 지표 (인구·고령화·경로당 공급)"],
        ["공간 단위", "읍·면 8곳 (군위읍, 소보·효령·부계·우보·의흥·산성·삼국유사면)"],
        ["기준 시점", f"인구·세대 {FIRST_MONTH}~{LAST_MONTH} 매월 / 경로당 {d['years'][0]}~{d['years'][-1]} 매년 + "
                     f"{SENIOR_STD_YEAR} / 위험지정 세천 {d['stream_date']}"],
        ["다른 파일과의 관계", "기초지표_2025.xlsx(2025 한 시점), 군위군_시계열지표.xlsx(같은 숫자를 주제별 표로)와 별개. 이 파일은 같은 숫자를 기초지표 파일처럼 메인 표·컬럼설명·산출방법 구성으로 다시 묶은 것"],
        ["", ""],
        ["■ 산출식", ""],
        ["증감률", "(나중 값 − 처음 값) ÷ 처음 값 × 100. 연간 증감률은 계절 영향을 피하려고 12월끼리 비교"],
        ["고령화율", "65세 이상 ÷ 총인구 × 100. 변화는 %p(차이)"],
        ["노인 1천명당 경로당", "경로당 수 ÷ 65세 이상 인구 × 1,000. 경로당과 인구 시점이 맞는 해(2023, 2025)만"],
        ["순위·등급·종합점수", "넣지 않았다(다음 단계에서 정한다)"],
        ["", ""],
        ["■ 시트", ""],
        ["시계열지표", "읍면 8행 한 장짜리 표. 열 설명은 '컬럼설명' 시트"],
        ["부록_인구_연말비교", "2023·2024·2025 12월 비교와 전년 대비 증감률"],
        ["부록_총인구_월별 / 부록_고령화율_월별", f"{FIRST_MONTH}~{LAST_MONTH} 매월. 추이 그래프용 가로 표"],
        ["부록_인구세대_월별", "derived/population_monthly.json 그대로 (읍면 8 + 군 합계 1) × 39개월"],
        ["부록_경로당_연도별", f"{d['years'][0]}~{d['years'][-1]} 통계연보, {SENIOR_STD_YEAR} 표준데이터. "
                            "2024 는 연보 미발간(2026-12 예정)이라 빈칸"],
        ["부록_경로당_공급수준", "노인 1천명당 경로당 계산 과정(경로당 수, 65세 이상)"],
        ["", ""],
        ["■ 자료 출처", ""],
        ["인구·세대", "행정안전부 주민등록 인구통계 (월말 기준) — jumin.mois.go.kr"],
        ["경로당 2014~2023", f"군위통계연보 제55~64회 12장 노인여가복지시설 표의 경로당 시설수 — gunwi.go.kr. "
                           f"{t0}~{t1} 은 이미지형 PDF 를 옮겨 적은 전사본(합계 검사·재판독 확인)"],
        ["경로당 2025", "공공데이터포털 경로당 표준데이터 (2025-12-19, 215곳)"],
        ["위험지정 세천", f"소규모공공시설 위험지정 표준데이터(2026-07-15)에 {d['stream_date']} 군위군 고시 "
                        "제2026-107호(해제) 반영"],
        ["", ""],
        ["■ 알아둘 점", ""],
        ["군 합계", "메인 표에는 군 합계 행이 없다. 부록 시트 맨 아래 '군위군 합계' 행은 읍면 행과 함께 더하지 말 것"],
        ["경로당 출처 차이", "2014~2023(연보)과 2025(표준데이터)는 출처가 다르다. 2023 연보 213곳 vs "
                          "2025 표준데이터 215곳(효령·우보 각 1곳 차이)"],
        ["인구 정의", "모두 주민등록 인구. SGIS 인구와 섞지 말 것"],
        ["표본 수", "읍면이 8곳뿐이라 비교·상관은 탐색적 수준이다"],
        ["", ""],
        ["■ 재현", ""],
        ["코드", "tools/prepare.py (raw → derived) · tools/export_trend.py (derived → 이 파일)"],
        ["CSV", "outputs/변화추이/ 에 시트마다 CSV 1개 (UTF-8 BOM)"],
    ]


def sheets() -> list[tuple[str, list[str], list[list]]]:
    d = collect()
    cols, body = main_table(d)
    return [
        ("시계열지표", [c[0] for c in cols], body),
        ("컬럼설명", ["컬럼명", "자료형", "단위", "설명"], [list(c) for c in cols]),
        ("산출방법", ["구분", "내용"], method_rows(d)),
        ("부록_인구_연말비교", *year_end(d)),
        ("부록_총인구_월별", *wide(d, "population")),
        ("부록_고령화율_월별", *wide(d, "aging_rate")),
        ("부록_인구세대_월별", *long_rows(d)),
        ("부록_경로당_연도별", *senior_years(d)),
        ("부록_경로당_공급수준", *supply(d)),
    ]


TEXT_SHEETS = {"컬럼설명": [34, 9, 7, 100], "산출방법": [30, 120]}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    CSV_DIR.mkdir(exist_ok=True)
    for old in CSV_DIR.glob("*.csv"):           # 시트 이름이 바뀌면 옛 CSV 가 남지 않게
        old.unlink()
    wb = Workbook()
    wb.remove(wb.active)
    for name, header, body in sheets():
        ws = wb.create_sheet(name)
        if name in TEXT_SHEETS:
            _sheet(ws, header, body, TEXT_SHEETS[name])
            for row in ws.iter_rows(min_row=2):
                if str(row[0].value or "").startswith("■"):
                    row[0].font = SECTION_FONT
                row[-1].alignment = Alignment(wrap_text=True, vertical="top")
        else:
            _sheet(ws, header, body, _widths(header, body))
            _wrap_header(ws, header)
            code_col = header.index("행정구역코드") + 1
            for row in ws.iter_rows(min_row=2, min_col=code_col, max_col=code_col):
                row[0].number_format = "@"          # 코드는 문자열로 둔다
            if name == "시계열지표":
                ws.freeze_panes = "C2"              # 코드·읍면명 고정
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
