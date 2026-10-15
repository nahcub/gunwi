# 작업별 절차: "X 하려면 어디를 고치나"

규칙의 이유는 `CLAUDE.md`, 데이터 내용은 `docs/data-guide.md` 에 있다.
여기는 순서만 적는다.

## 0. 처음 받았을 때

```bash
git pull
pip install -r requirements.txt     # pytest, openpyxl
python tools/build.py               # public/data 는 git 에 없다. 이걸 안 하면 웹이 안 뜬다
python -m http.server 8787 --directory public    # 또는 npm run dev
```

http://127.0.0.1:8787 접속. "데이터를 불러오지 못했습니다" 가 뜨면 build.py 를 안 돌린 것이다.
`prepare.py` 는 원자료나 prepare.py 를 바꿨을 때만 돌리면 된다(derived 는 git 에 있다).

## 1. 화면(디자인·문구·동작)만 바꾸기

- 고칠 파일: `public/index.html`, `public/app.js`, `public/styles.css`
- 데이터는 `public/data/*.json` 을 fetch 해서 쓴다. 이 JSON 은 손으로 고치지 않는다
- 브라우저 새로고침으로 확인. 빌드 불필요

화면이 읽는 파일 (`app.js` 의 `main()`):

| 파일 | 내용 |
|---|---|
| `regions.json` | 읍면 8개 × 2시점 지표값 + 지표 정의(`indicators`) |
| `eupmyeon.geojson` | 읍면 경계(`region_code`) |
| `facilities.json` | 경로당·위험 세천 지점 |
| `parks.json` / `potholes.json` | 공원·포트홀 지점 |
| `sources.json` | 출처 패널 |
| `hypotheses.json` | 민원 가설 카드·사분면 (`data/hypotheses.json` 에서 생성) |

## 2. 이미 derived 에 있는 값을 화면에 새 지표로 올리기

예: SGIS `households`(가구수)를 코로플레스로 띄우고 싶다.

1. `tools/build.py` 의 `build_regions()` 에서 행 dict 에 값 추가
   (`"households": sgis[code]["households"]`)
2. 같은 파일 `INDICATORS` 에 정의 추가
   (`id` 는 위 키와 같게, `status: "available"`, `unit`, `higher_is_worse`, `reference`)
3. `python tools/build.py` → 새로고침. 지표 목록에 자동으로 생긴다
4. `python -m pytest tools/tests -q`
   (`test_every_available_indicator_has_values` 가 값 누락을 잡는다)

공개하면 안 되는 값(개인정보, 비공개 자료 파생물)은 build.py 에 적지 않는다.

## 3. 새 원자료 추가하기

1. 받은 파일을 그대로 등록 (raw 폴더를 손으로 만들지 말 것)
   ```bash
   python tools/add_source.py --id 새_ID --dir 출처-이름-기준일 --name "..." --provider "..." --url "..." --reference-date YYYY-MM-DD --license "..." --file 받은파일.csv
   ```
   - cp949 파일이면 `--encoding cp949`, 기준일 근거·행수·품질 문제는 `--notes "..."`
   - 원본 페이지를 `capture.html` 로 저장해 같이 `--file` 로 넣는다(URL 이 죽어도 증빙이 남는다)
2. 생성된 `data/raw/<폴더>/_meta.json` 을 열어 빠진 내용을 채운다
3. `data/sources.json` 에 항목 추가 (`id`, `name`, `provider`, `license`, `status` 필수)
4. `tools/prepare.py` 에 `prepare_xxx()` 추가 → `main()` 에서 `write("xxx.json", ...)`
   - 지역은 반드시 `region_code` 로 붙인다 (`_region_code_from_address()` 등 기존 함수 재사용)
   - 행수·합계·범위를 `assert` 로 검증한다
5. `python tools/prepare.py` → `data/derived/xxx.json` 확인
6. `tools/tests/test_prepare.py` 에 알려진 개수 테스트 추가
7. 화면에 올릴 거면 §2, 엑셀에 넣을 거면 §5
8. `docs/data-guide.md` 표에 한 줄 추가

## 4. 원자료를 새 시점으로 갱신하기

예: 2026-12 주민등록 인구.

1. 기존 폴더는 그대로 두고 **새 폴더**로 등록 (§3-1)
2. `prepare.py` 의 `MOIS_PERIODS` 에 `"2026-12"` 추가
3. `python tools/prepare.py`
4. 테스트 기대값(예: 18행 = 2시점×9)이 깨지면 새 값으로 고친다
5. 쓰지 않을 옛 시점은 `MOIS_PERIODS` 에서 빼고 raw 폴더를 지운다(git 기록에 남는다)

## 5. 제출용 엑셀 다시 만들기

```bash
python tools/export_excel.py
```

- 출력: `outputs/군위군_시설관리우선지역_기초지표_2025.xlsx` (+ 같은 이름 `.csv`)
- 시트 3개: `기초지표`(읍면 8행) · `컬럼설명` · `산출방법`
- 열을 추가·변경하려면 `export_excel.py` 의 `COLUMNS`(열 정의)와 `build_rows()`(값)를 같이 고친다
- 엑셀을 열어 둔 채로 실행하면 저장이 실패한다. 닫고 실행

## 6. 배포

- main 에 push 하면 GitHub Actions 가 검증 → Cloudflare 배포까지 자동으로 한다
- 단 Cloudflare 키가 GitHub Secrets 에 없으면 배포 단계는 건너뛴다(현재 그 상태).
  실제로 공개하려면 레포 Settings → Secrets 에 `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` 등록
- 실패 원인 1순위: raw/prepare.py 를 바꾸고 `data/derived/` 를 재생성·커밋하지 않음
  → `python tools/prepare.py` 후 derived 변경분까지 커밋
- 커밋 전 로컬 점검:
  ```bash
  python tools/prepare.py
  python -m pytest tools/tests -q
  python tools/build.py
  ```

## 7. 포트홀 민원 다시 수집하기

```bash
$env:DATA_GO_KR_KEY='발급받은 일반 인증키'      # PowerShell. Mac/Linux 는 export
python tools/fetch_pothole.py --test 20250101
python tools/fetch_pothole.py --start 20250101 --end YYYYMMDD --max-calls 90
```

- 키는 **코드에 적지 않는다**(공개 저장소)
- 결과는 프로젝트 루트에 생긴다 → `pothole_all.csv`·`progress.json` 을 새 raw 폴더로 등록(§3).
  `gunwi_candidate.csv` 는 bbox 가 실제 경계보다 좁아 쓰지 않는다
- prepare.py 의 `POTHOLE_FOLDER` 를 새 폴더명으로 바꾼다

## 8. 민원 원자료(군청)가 들어오면

이 프로젝트의 본래 목표. 들어오면 민원발생률·반복민원율·처리지연율이 풀린다.

1. 개인정보가 섞여 있으면 **공개 저장소에 올리지 않는다** — 비식별 집계만 raw 에
2. §3 절차로 등록, 산식은 `docs/methodology.md` §2 를 따른다
3. `build.py` `INDICATORS` 에서 해당 지표 `status` 를 `"available"` 로 바꾸고 값 추가
4. `test_missing_indicators_have_no_values` 등 테스트를 새 상태에 맞게 고친다
5. `data/sources.json` 의 `COMPLAINT_INTERNAL` 상태 갱신

청구서 초안: `docs/requests/README.md` (아직 발송 안 됨)

## 9. 민원 가설 고치기·추가하기

가설 문구·방향·검증 방법은 **`data/hypotheses.json` 한 곳만** 고친다.
웹 카드, 엑셀 '가설' 시트, 그림5 가 모두 여기서 나온다.

1. `data/hypotheses.json` 의 `hypotheses` 에 항목 추가 (`id`, `indicator`, `type`,
   `direction`, `complaint_fields`, `statement`, `mechanism`, `caveat`,
   `verify_with`, `verify_method`, `status`)
   - `indicator` 는 `build.py` `INDICATORS` 에서 `available` 인 id 여야 한다
   - `verify_with` 는 `data/sources.json` 의 id 여야 한다
   - `status` 는 `가설(미검증)` 으로 시작한다. 민원 원자료 없이 바꾸지 않는다
2. `python tools/build.py` — 위 조건이 틀리면 assert 로 멈춘다
3. `python -m pytest tools/tests -q`
4. `python tools/export_excel.py` · `python tools/figures.py` 로 엑셀·그림 갱신

민원 원자료가 들어와 가설을 검증하면: `status` 를 `검증 중` → `지지`/`기각` 으로
바꾸고, 근거(순위상관 값, 기간)를 `verify_method` 아래가 아니라 `docs/hypotheses.md`
에 기록한다. `test_no_hypothesis_is_verified_without_complaint_data` 는 그때 고친다.

## 10. 보고서 그림 다시 만들기

```bash
pip install -r requirements.txt      # matplotlib 포함
python tools/figures.py              # 또는 npm run figures
```

- 출력: `outputs/figures/그림1~5_*.png` (+ 그림3·4 근거 CSV)
- 값은 `build.py` `build_regions()` 를 그대로 쓴다 — 웹과 같은 숫자
- 기준 시점은 `export_excel.py` 의 `ANALYSIS_PERIOD`(2025-12)
- 한글 글꼴(맑은 고딕·AppleGothic·나눔고딕·Noto CJK) 중 하나가 있어야 한글이 안 깨진다
- CI 는 그림을 만들지 않는다. 그림을 바꿨으면 직접 돌려서 커밋한다
