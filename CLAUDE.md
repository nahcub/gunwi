# CLAUDE.md

코드만 봐서는 알 수 없고, 모르면 반드시 틀리는 것들. 사람이 읽어도 그대로 유용하다.
(2026-10-15 인수인계 시점 최신화. 원작성자는 더 이상 이 저장소를 관리하지 않는다)

## 먼저 읽을 문서

| 알고 싶은 것 | 문서 |
|---|---|
| raw 원자료별 내용과 derived 에서 무엇이 되는지 | `docs/data-guide.md` |
| "X 하려면 어느 파일을 고치나" 작업별 절차 | `docs/how-to.md` |
| 지표 산식과 근거, 계산하지 않는 이유 | `docs/methodology.md` |
| 아직 못 구한 자료 조사 결과 | `docs/data-survey.md` |
| 군청 정보공개청구 초안(미발송) | `docs/requests/README.md` |

## 폴더 소유권

| 폴더 | 누가 쓰나 | 규칙 |
|---|---|---|
| `data/raw/` | 사람 (다운로드) | **동결.** 한 바이트도 고치지 않는다 |
| `data/derived/` | `tools/prepare.py` | 손대지 않는다. 고치려면 prepare.py 를 고친다. git 에 올라간다 |
| `public/*.html,js,css` | 사람 | 자유롭게 편집 |
| `public/data/` | `tools/build.py` | 손대지 않는다. `.gitignore` 에 있다 → **clone/pull 직후엔 비어 있다** |
| `outputs/` | `tools/export_excel.py` | 제출용 엑셀·CSV. 손으로 고치지 않는다 |

`public/` 에 들어간 것은 **인터넷에 공개된다.** `derived/` → `public/data/` 로
올릴 파일을 정하는 곳이 `tools/build.py` 이고, 그게 공개 여부를 결정하는 자리다.
비공개 자료의 파생물은 `derived/` 에서 멈춘다.

## 파이프라인과 도구

```
tools/add_source.py    새 원자료를 data/raw/<새 폴더>/ 에 등록 (_meta.json·sha256 자동)
tools/fetch_pothole.py 포트홀 민원 API 수집기 (인증키는 환경변수 DATA_GO_KR_KEY)
tools/prepare.py       data/raw     -> data/derived   (assert 검증 관문)
tools/build.py         data/derived -> public/data    (공개 결정 지점)
tools/export_excel.py  data/derived -> outputs/       (제출용 엑셀·CSV)
tools/tests/           pytest. 원자료 기준 "알려진 개수"를 고정해 둔 테스트가 많다
```

`npm run dev` 는 build.py 후 `python -m http.server 8787 --directory public`.

## 배포: main 에 push 하면 CI 가 돈다

`.github/workflows/deploy.yml` 이 main push 마다 실행된다.

1. `npm ci` — `package-lock.json` 이 있어야 한다. 지우지 말 것
2. `prepare.py` 를 다시 돌리고 `git diff --exit-code data/derived/`
   → **derived 를 재생성하지 않고 커밋했거나 손으로 고쳤으면 여기서 실패**.
   그래서 prepare.py 출력에 실행 날짜 같은 매번 바뀌는 값을 넣으면 안 된다
3. pytest
4. build.py → Cloudflare(wrangler) 배포. **단 GitHub Secrets 에
   `CLOUDFLARE_API_TOKEN`·`CLOUDFLARE_ACCOUNT_ID` 가 없으면 배포는 건너뛴다**
   (2026-10-15 현재 없음 → 검증만 하고 실제 공개 배포는 안 되는 상태)

그래서 raw 나 prepare.py 를 바꿨으면 반드시 `python tools/prepare.py` 를 돌리고
바뀐 `data/derived/` 를 **같이 커밋**한다. 실험은 브랜치에서 한다.

## 코드 체계가 셋이다

```
주민등록 행정기관코드 : 2772025000 (군위읍), 군 합계 2772000000   <- 프로젝트 표준 = region_code
경계 ADM_CD / SGIS    : 22520111   (군위읍), 군 합계 22520        <- 경계 원본·SGIS 통계가 같은 체계
통계청 최신 코드       : 27720 계열                               <- SGIS 파일에서 이걸로 찾으면 0행
```

세 체계는 **일치하지 않는다.** `prepare_boundary()` 가 지역명으로 한 번만 맞춰서
경계에 `region_code` 와 `source_adm_cd` 를 심는다. SGIS 통계는 그 `source_adm_cd`
로 붙인다(`prepare_sgis_stats()`). 경로당·위험시설은 주소의 읍면 토큰으로,
포트홀은 경계 다각형 포함 판정으로 region_code 를 얻는다. 전부 prepare.py 안에서
끝나고, 웹·엑셀은 `region_code` 만 쓴다. 이 변환을 다른 곳으로 옮기지 말 것 —
런타임 이름 매칭은 기존 저장소에서 실제로 문제를 만들었다.

## 절대 함께 더하지 말 것

- 군 합계 행(`2772000000`)과 읍면 8개 행
- 성별 `계` 와 `남`·`여`
- 주민등록 인구(`population.json`)와 SGIS 인구(`sgis_stats.json`) — 정의가 달라
  값이 다르다(2025-12 군 22,452 vs SGIS 2024 군 21,493). 한 산식 안에서 섞지 않는다
- 상수도보급률 읍면 값의 단순 평균 — 군 전체 보급률이 아니다(인구 가중 아님)

`build_regions()` 가 군 합계를 공개 데이터에서 걸러내고, 테스트가 그걸 검사한다.

## 프로젝트 임시값 (공식 기준 아님)

| 값 | 위치 | 의미 |
|---|---|---|
| `SENIOR_OLD_BEFORE_YEAR = 2000` | prepare.py | 이 해 이전 건립 경로당을 "노후"로 센다 |
| 세천만 사용 | `prepare_drainage_risk()` | 위험지정 39건 중 현행 지정 세천 27곳만. 소교량·농로 등은 개수만 |
| `SGIS_POP_TOLERANCE = 0.15` | prepare.py | SGIS·주민등록 인구 차이가 이보다 크면 코드 매핑이 뒤바뀐 것으로 보고 멈춤 |
| `ANALYSIS_PERIOD = "2025-12"` | export_excel.py | 엑셀 결과표의 인구 기준 시점 |

보고서에 쓸 때는 "프로젝트 임시 기준"이라고 명시한다.

## 미해결: 경계 GeoJSON 출처 불명

`data/raw/boundary-eupmyeon-2025-06-30/` 의 `provenance` 가 `UNVERIFIED` 다.
팀 저장소 첫 커밋에 이미 있었고 다운로드 이력이 없다. `reference_date`
2025-06-30 은 피처 속성 `BASE_DATE` 에서 읽은 값일 뿐 출처 문서로 확인된 게
아니다. 워크북 G01 은 경계를 "원본 미확보"로 적어놨는데 파일은 존재한다 —
문서와 실제가 모순된다.

**지도 전체와 포트홀 읍면 판정, SGIS 코드 대응이 이 파일 위에 서 있다.**
SGIS 전국 원본 zip(`sgis-admstat-2025-2q/_meta.json` 참고, 경계 shp 포함,
EPSG:5179)에서 2025 2Q 경계를 추출·대조하고, 새 raw 폴더로 등록한 뒤
`provenance` 를 `verified` 로 바꿀 것. 그때까지 화면 상단에 경고 배너가 뜬다
(`renderBanner()`). 보고서에도 "경계 출처 미확인"을 적는다.

## 종합 우선순위는 계산하지 않는다

문서에서 제안된 가중치는 `0.35 / 0.25 / 0.25 / 0.15` 인데 공식 기관 산식이
아니다. 네 지표의 척도가 서로 달라(건수 vs 비율) 표준화 없이 가중합하면 숫자가
의미를 잃는다. `priority_score` 는 `status: "blocked"` 로 두고 값을 만들지 않으며,
테스트가 그걸 검사한다. 엑셀의 `우선순위` 열도 비워 둔다. 근거는 `docs/methodology.md`.

## 없는 데이터는 만들지 않는다

민원 3지표와 시설관리 필요도는 원자료가 없다. 샘플값을 채우지 말고 지표를
`status: "missing"` 으로 두면 화면이 비활성으로 표시하고 이유까지 보여준다.
기존 저장소는 여기에 임의 숫자를 넣었고, 그 숫자가 모든 테스트를 통과했다.
통계 비공개 셀(`N/A`)도 0 으로 바꾸지 않고 `null` 로 둔다.

포트홀 민원은 군위 4건뿐이라 지표로 쓰지 않고 지점 표시만 한다.
살피소 제보 현황(`daegu-salpiso-reports-2024-11-27`)은 군 단위 1행이라 prepare.py
가 읽지 않는다 — 보고서 배경 수치용.

## 비밀값

- 이 저장소는 **공개(GitHub nahcub/gunwi)** 다. 인증키·토큰을 코드나 커밋에 넣지 않는다
- 공공데이터포털 키는 환경변수 `DATA_GO_KR_KEY` 로만 넣는다
- 과거 커밋(`tools/fetch_pothole.py`)에 키가 노출된 적이 있다 → 해당 키는 폐기·재발급 대상
- Cloudflare 토큰은 GitHub Secrets(`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`)에만 있다

## 테스트가 깨질 때

`tools/tests/` 는 현재 원자료의 개수·값(경로당 215, 세천 27, 포트홀 4 등)을
고정해 둔 테스트가 많다. **원자료를 새로 받아서** 숫자가 바뀐 거라면 테스트의
기대값을 새 값으로 고친다(이유를 커밋 메시지에). 원자료가 그대로인데 깨졌다면
코드가 틀린 것이다 — 테스트를 고치지 말고 코드를 고친다.

## 기타

- 군위군은 2023-07-01 경상북도 → 대구광역시 편입. 그 이전 자료는 옛 명칭·코드(47720 계열)를 쓴다
- UI 문구·데이터 레이블은 모두 한국어. 새로 추가하는 노출 문자열도 한국어로
- 프레임워크·번들러 없음. `public/` 의 파일을 직접 편집한다
- `public/index.html` 을 브라우저로 그냥 열어도 동작한다(빌드 후)
- raw CSV 인코딩이 섞여 있다(UTF-8 BOM / cp949). `_meta.json` 의 `encoding` 필드를 따른다
- `data/raw/` 는 `.gitattributes` 로 줄바꿈 변환을 막아 sha256 을 유지한다. 지우지 말 것
