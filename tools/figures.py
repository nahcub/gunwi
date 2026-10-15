"""data/derived + data/hypotheses.json -> outputs/figures/ 보고서 삽화

값은 tools/build.py 의 build_regions() 를 그대로 쓴다 - 웹과 같은 숫자다.
raw 는 읽지 않는다. 기준 시점은 export_excel.py 의 ANALYSIS_PERIOD 와 같다.

  python tools/figures.py

출력 (모두 PNG + 근거표 CSV)
  그림1_읍면별_지표지도.png        가설에 쓰는 지표 6개 읍면 지도
  그림2_사분면_노후경로당_고령화율.png  data/hypotheses.json views[Q1]
  그림3_지표간_순위상관.png  (+ csv)  지표끼리의 Spearman 순위상관 (민원과의 상관이 아니다)
  그림4_살피소_분야구성.png  (+ csv)  군위군 vs 대구 전체 제보 분야 비율
  그림5_가설구조도.png               지표 -> 민원 분야 가설 연결
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.collections import PatchCollection  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402
from export_excel import ANALYSIS_PERIOD  # noqa: E402

DERIVED = ROOT / "data" / "derived"
OUT = ROOT / "outputs" / "figures"
HYP = json.loads((ROOT / "data" / "hypotheses.json").read_text(encoding="utf-8"))

# 그림1 에 그릴 지표 - 가설(H1~H7)이 붙은 지표 중 읍면 비교가 의미 있는 것
MAP_INDICATORS = ["elderly_ratio", "aging_index", "senior_center_old_ratio",
                  "senior_center_per_1k_elderly", "drainage_risk_count", "water_supply_rate"]
CRITICAL_RHO_N8 = 0.738   # n=8, 양측 5% Spearman 임계값. 이보다 작으면 우연과 구분되지 않는다


def _font() -> None:
    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Malgun Gothic", "AppleGothic", "NanumGothic",
                 "Noto Sans CJK KR", "Noto Sans CJK JP"):
        if cand in names:
            plt.rcParams["font.family"] = cand
            break
    else:
        print("  ! 한글 글꼴을 찾지 못했다 - 그림의 한글이 깨질 수 있다")
    plt.rcParams["axes.unicode_minus"] = False


def _save(fig, name: str) -> None:
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  {path.relative_to(ROOT)}")


def _rows() -> list[dict]:
    rows = build.build_regions()["regions"][ANALYSIS_PERIOD]
    assert len(rows) == 8
    return rows


def _ind(iid: str) -> dict:
    return next(i for i in build.INDICATORS if i["id"] == iid)


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1     # 동순위는 평균 순위
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _rank(a), _rank(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den


# ---------------------------------------------------------------- 그림1

def fig_maps(rows: list[dict]) -> None:
    gj = json.loads((DERIVED / "eupmyeon.geojson").read_text(encoding="utf-8"))
    by_code = {r["region_code"]: r for r in rows}
    lat0 = 36.18
    fig, axes = plt.subplots(2, 3, figsize=(16, 11.5))
    for ax, iid in zip(axes.flat, MAP_INDICATORS):
        ind = _ind(iid)
        vals = [r[iid] for r in rows]
        lo, hi = min(vals), max(vals)
        cmap = plt.get_cmap("OrRd" if ind["higher_is_worse"] else "OrRd_r")
        patches, colors = [], []
        for f in gj["features"]:
            code = f["properties"]["region_code"]
            v = by_code[code][iid]
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for poly in polys:
                patches.append(Polygon(poly[0], closed=True))
                colors.append(cmap((v - lo) / (hi - lo) if hi > lo else 0.5))
            # 라벨은 가장 큰 고리의 평균점 근처에
            ring = max((p[0] for p in polys), key=len)
            cx = statistics.mean(x for x, _ in ring)
            cy = statistics.mean(y for _, y in ring)
            ax.text(cx, cy, f"{by_code[code]['name']}\n{v:g}", ha="center", va="center",
                    fontsize=6.8, bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.7))
        ax.add_collection(PatchCollection(patches, facecolor=colors, edgecolor="#555", linewidth=0.6))
        ax.autoscale_view()
        ax.set_aspect(1 / math.cos(math.radians(lat0)))
        ax.set_axis_off()
        ref = f" · {ind['reference']}" if ind.get("reference") else ""
        ax.set_title(f"{ind['label']} ({ind['unit'] or '지수'})", fontsize=11)
        ax.text(0.5, -0.02, f"{'높을수록 취약' if ind['higher_is_worse'] else '낮을수록 취약'}{ref}",
                transform=ax.transAxes, ha="center", va="top", fontsize=7, color="#666")
    fig.suptitle(f"군위군 읍면별 가설 지표 (인구 기준 {ANALYSIS_PERIOD}, 진할수록 취약 방향)", fontsize=14)
    fig.text(0.5, 0.01, "색 구간은 8개 읍면 안에서의 상대 척도다. 읍면 경계 출처 미확인(UNVERIFIED).",
             ha="center", fontsize=8, color="#666")
    _save(fig, "그림1_읍면별_지표지도.png")


# ---------------------------------------------------------------- 그림2

def fig_quadrant(rows: list[dict]) -> None:
    v = next(x for x in HYP["views"] if x["id"] == "Q1")
    ix, iy = _ind(v["x"]), _ind(v["y"])
    xs = [r[v["x"]] for r in rows]
    ys = [r[v["y"]] for r in rows]
    mx, my = statistics.median(xs), statistics.median(ys)
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    ax.fill_between([mx, max(xs) + 3], my, max(ys) + 3, color="#fdecec", zorder=0)
    ax.axvline(mx, color="#999", ls="--", lw=1)
    ax.axhline(my, color="#999", ls="--", lw=1)
    for r in rows:
        hh = r[v["x"]] > mx and r[v["y"]] > my
        ax.scatter(r[v["x"]], r[v["y"]], s=90, color="#e57373" if hh else "#8fb9dc",
                   edgecolor="#9b2c2c" if hh else "#2f6fb0", zorder=3)
        ax.annotate(r["name"], (r[v["x"]], r[v["y"]]), xytext=(6, 5), textcoords="offset points", fontsize=9)
    ax.set_xlim(min(xs) - 3, max(xs) + 3)
    ax.set_ylim(min(ys) - 3, max(ys) + 3)
    ax.set_xlabel(f"{ix['label']} ({ix['unit']})")
    ax.set_ylabel(f"{iy['label']} ({iy['unit']})")
    ax.set_title(f"{v['title']} — 빨간 영역: 두 지표 모두 중앙값 초과({v['high_high_label']})", fontsize=11)
    fig.text(0.5, -0.03, f"점선 = 8개 읍면 중앙값 ({ix['label']} {mx:.1f}{ix['unit']}, {iy['label']} {my:.1f}{iy['unit']}). "
            f"위치 표시일 뿐 종합 우선순위가 아니다. 관련 가설 {', '.join(v['hypotheses'])}",
            ha="center", fontsize=8, color="#666")
    ax.spines[["top", "right"]].set_visible(False)
    _save(fig, "그림2_사분면_노후경로당_고령화율.png")


# ---------------------------------------------------------------- 그림3

def fig_correlation(rows: list[dict]) -> None:
    ids = [i["id"] for i in build.INDICATORS if i["status"] == "available"]
    labels = [_ind(i)["label"] for i in ids]
    cols = {i: [r[i] for r in rows] for i in ids}
    n = len(ids)
    m = [[spearman(cols[a], cols[b]) for b in ids] for a in ids]

    with open(OUT / "그림3_지표간_순위상관.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["지표"] + labels)
        for lab, row in zip(labels, m):
            w.writerow([lab] + [round(x, 2) for x in row])

    fig, ax = plt.subplots(figsize=(9, 7.5))
    im = ax.imshow(m, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(n), labels, rotation=45, ha="right", fontsize=8.5)
    ax.set_yticks(range(n), labels, fontsize=8.5)
    for i in range(n):
        for j in range(n):
            strong = abs(m[i][j]) >= CRITICAL_RHO_N8 and i != j
            ax.text(j, i, f"{m[i][j]:.2f}", ha="center", va="center", fontsize=7.5,
                    fontweight="bold" if strong else "normal",
                    color="white" if abs(m[i][j]) > 0.6 else "#222")
    fig.colorbar(im, ax=ax, shrink=0.75, label="Spearman ρ")
    ax.set_title("지표끼리의 순위상관 (읍면 8개, 인구 기준 " + ANALYSIS_PERIOD + ")", fontsize=12)
    fig.text(0.5, -0.02, f"굵은 글씨 = |ρ| ≥ {CRITICAL_RHO_N8} (n=8 양측 5% 임계값). 민원과의 상관이 아니라 "
             "지표끼리 같이 움직이는지 본 것이다 - 같이 움직이는 지표는 한 가설의 증거로 두 번 세지 않는다.",
             ha="center", fontsize=8, color="#666", wrap=True)
    _save(fig, "그림3_지표간_순위상관.png")


# ---------------------------------------------------------------- 그림4

def fig_salpiso() -> None:
    sp = json.loads((DERIVED / "salpiso.json").read_text(encoding="utf-8"))
    fields = sp["fields"]
    g, a = sp["gunwi"], sp["daegu_all"]
    gs = [g["by_field"][f] / g["reports"] * 100 for f in fields]
    as_ = [a["by_field"][f] / a["reports"] * 100 for f in fields]
    order = sorted(range(len(fields)), key=lambda i: gs[i])

    with open(OUT / "그림4_살피소_분야구성.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["분야", "군위군_건수", "군위군_비율_pct", "대구전체_건수", "대구전체_비율_pct"])
        for i in reversed(order):
            w.writerow([fields[i], g["by_field"][fields[i]], round(gs[i], 1),
                        a["by_field"][fields[i]], round(as_[i], 1)])

    fig, ax = plt.subplots(figsize=(8, 5.5))
    y = range(len(fields))
    ax.barh([k + 0.2 for k in y], [gs[i] for i in order], height=0.4, color="#c0504d",
            label=f"군위군 ({g['reports']}건)")
    ax.barh([k - 0.2 for k in y], [as_[i] for i in order], height=0.4, color="#9ca3af",
            label=f"대구 전체 ({a['reports']:,}건)")
    for k, i in enumerate(order):
        ax.text(gs[i] + 0.6, k + 0.2, f"{g['by_field'][fields[i]]}건", va="center", fontsize=8)
    ax.set_yticks(list(y), [fields[i] for i in order])
    ax.set_xlabel("제보 중 비율 (%)")
    ax.set_title("살피소 제보 분야 구성: 군위군 vs 대구 전체", fontsize=12)
    ax.legend(loc="lower right", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, -0.02, f"처리기관 단위 집계(기준 {sp['reference_date']}, 집계 연도 미확정). 읍면 구분이 없어 "
             "군 단위 배경 근거로만 쓴다.", ha="center", fontsize=8, color="#666")
    _save(fig, "그림4_살피소_분야구성.png")


# ---------------------------------------------------------------- 그림5

def fig_structure() -> None:
    from matplotlib.lines import Line2D

    hyps = HYP["hypotheses"]
    inds = list(dict.fromkeys(h["indicator"] for h in hyps))
    fields = HYP["complaint_fields"]
    type_color = {"수요형": "#5b95c6", "부족형": "#e0a35c", "노후형": "#c0504d"}
    n = max(len(inds), len(fields))
    fig, ax = plt.subplots(figsize=(10.5, 7))
    ax.set_xlim(0, 10)
    ax.set_ylim(n - 0.4, -1.3)
    ax.set_axis_off()
    yi = {iid: k * (n - 1) / max(len(inds) - 1, 1) for k, iid in enumerate(inds)}
    yf = {f: k * (n - 1) / max(len(fields) - 1, 1) for k, f in enumerate(fields)}
    for h in hyps:
        for f in h["complaint_fields"]:
            ax.plot([3.25, 6.75], [yi[h["indicator"]], yf[f]], color=type_color[h["type"]], lw=2, alpha=0.7)
    for h in hyps:   # 가설 번호는 지표 상자 바로 오른쪽에 한 번만
        ax.text(3.45, yi[h["indicator"]], h["id"], fontsize=8, ha="left", va="center",
                color=type_color[h["type"]], fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=type_color[h["type"]], lw=0.8))
    for iid, y in yi.items():
        h = next(x for x in hyps if x["indicator"] == iid)
        ax.text(3.15, y, f"{_ind(iid)['label']}  ({h['direction']})", ha="right", va="center", fontsize=10,
                bbox=dict(boxstyle="round,pad=0.3", fc="#f6f7f9", ec="#bbb"))
    for f, y in yf.items():
        ax.text(6.85, y, f, ha="left", va="center", fontsize=10,
                bbox=dict(boxstyle="round,pad=0.3", fc="#fff4e5", ec="#e0a35c"))
    ax.text(1.7, -0.9, "지표 (가설 방향)", ha="center", fontsize=10, color="#555", fontweight="bold")
    ax.text(8.0, -0.9, "민원 분야 (요청 6개)", ha="center", fontsize=10, color="#555", fontweight="bold")
    handles = [Line2D([0], [0], color=c, lw=3, label=t) for t, c in type_color.items()]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.08), ncol=3, frameon=False)
    ax.set_title("지표–민원 가설 구조 (전부 미검증 · data/hypotheses.json)", fontsize=12, pad=4)
    _save(fig, "그림5_가설구조도.png")


def main() -> None:
    _font()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _rows()
    print("outputs/figures 생성:")
    fig_maps(rows)
    fig_quadrant(rows)
    fig_correlation(rows)
    fig_salpiso()
    fig_structure()


if __name__ == "__main__":
    main()
