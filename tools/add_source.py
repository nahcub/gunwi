"""새 원자료를 data/raw/ 에 등록한다.

출처 기록을 깜빡할 수 없게 하는 것이 이 도구의 목적이다.
직접 다운로드해서 폴더에 던져넣으면 _meta.json 이 비고, 그게 이 프로젝트에서
실제로 벌어진 최대 구멍이었다(경계 GeoJSON 출처 불명).

  # 파일을 이미 받아둔 경우
  python tools/add_source.py --id MOIS_AGE_2026_12 --dir mois-age-2026-12 \
      --name "행정동별 연령별 주민등록인구" \
      --provider "행정안전부 주민등록 인구통계" \
      --url "https://jumin.mois.go.kr/ageStatMonth.do" \
      --reference-date 2026-12-31 --license "공식 통계 출처표시" \
      --file ~/Downloads/age.json

여러 --file 을 줄 수 있다. sha256 과 크기는 자동으로 기록된다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description="data/raw 에 원자료 등록")
    ap.add_argument("--id", required=True, help="레지스트리 source id")
    ap.add_argument("--dir", required=True, help="data/raw 아래 폴더 이름")
    ap.add_argument("--name", required=True)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--reference-date", required=True,
                    help="데이터의 기준시점 (파일 수정일이 아니다)")
    ap.add_argument("--license", required=True)
    ap.add_argument("--retrieved-at", default=date.today().isoformat())
    ap.add_argument("--retrieved-by", default="")
    ap.add_argument("--encoding", default=None, help="csv 등 비 utf-8 인 경우")
    ap.add_argument("--notes", default="")
    ap.add_argument("--provenance", choices=["verified", "verified_import"],
                    default="verified",
                    help="verified: 공식 원본 그대로 / verified_import: 출처는 확인됐지만 "
                         "팀원 등에게서 받은 가공본")
    ap.add_argument("--file", action="append", default=[], required=True,
                    help="복사해 넣을 파일 (여러 번 지정 가능)")
    args = ap.parse_args()

    dest = RAW / args.dir
    if dest.exists():
        raise SystemExit(f"이미 있는 폴더다: {dest.relative_to(ROOT)}\n"
                         "raw/ 는 동결 구역이므로 덮어쓰지 않는다. "
                         "새 기준시점이면 폴더 이름을 다르게 하라.")
    dest.mkdir(parents=True)

    files = {}
    for src in args.file:
        p = Path(src).expanduser()
        if not p.is_file():
            raise SystemExit(f"파일이 없다: {p}")
        shutil.copy2(p, dest / p.name)
        target = dest / p.name
        files[p.name] = {"sha256": sha256(target), "bytes": target.stat().st_size}

    meta = {
        "source_id": args.id,
        "name": args.name,
        "provider": args.provider,
        "url": args.url,
        "reference_date": args.reference_date,
        "retrieved_at": args.retrieved_at,
        "retrieved_by": args.retrieved_by or None,
        "license": args.license,
        "provenance": args.provenance,
        "notes": args.notes,
        "files": files,
    }
    if args.encoding:
        meta["encoding"] = args.encoding

    (dest / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"등록: {dest.relative_to(ROOT)}  (파일 {len(files)}개)")
    for n, f in files.items():
        print(f"  {n}  {f['bytes']:,} bytes  {f['sha256'][:16]}...")
    print("\n다음 할 일:")
    print(f"  1. data/sources.json 에 id={args.id} 항목 추가 "
          f"(raw_dir: data/raw/{args.dir})")
    print("  2. tools/prepare.py 에 읽는 코드 추가")
    print("  3. python tools/prepare.py && python tools/build.py")
    print("\n원본 페이지를 capture.html 로 같이 저장해두면 URL이 죽어도 출처가 남는다.")


if __name__ == "__main__":
    main()
