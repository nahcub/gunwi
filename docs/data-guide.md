# 데이터 설명서: `data/raw` → `data/derived`

`data/raw/` 에 무엇이 있고, `tools/prepare.py` 를 거치면 `data/derived/` 에서
무엇이 되는지 정리한 문서다. 숫자는 2026-10-14 실행 결과 기준.

```
data/raw/<폴더>/          받은 그대로. 동결. _meta.json = 출처 카드(출처·기준일·sha256)
      │  python tools/prepare.py   (assert 검증. 하나라도 틀리면 멈춘다)
      ▼
data/derived/*.json       정제·검증 통과분. 손으로 고치지 않는다
      │  python tools/build.py     (공개 여부 결정)
      ▼
public/data/*.json        웹 화면용
```

## 한눈에 보기

| raw 폴더 | 원자료 | 기준일 | → derived | 상태 |
|---|---|---|---|---|
| `mois-age-2025-12` | 행안부 연령별 주민등록인구 | 2025-12-31 | `population.json` | 사용 |
| `mois-age-2026-08` | 〃 | 2026-08-31 | `population.json` | 사용 |
| `boundary-eupmyeon-2025-06-30` | 읍면 경계 GeoJSON | 2025-06-30(추정) | `eupmyeon.geojson` | 사용 ⚠️ 출처 미확인 |
| `datagokr-park-2026-03-05` | 도시공원 표준데이터(군위 3건) | 2026-03-05 | `parks.json` | 사용 |
| `minwon-pothole-2026-10-13` | 권익위 포트홀 민원 좌표(전국) | 2025-01-01~2026-10-13 | `potholes.json` | 사용(지점 표시 전용) |
| `datagokr-gunwi-senior-2025-12-19` | 경로당 표준데이터(군위 215곳) | 2025-12-19 | `senior_centers.json` | 사용 |
| `datagokr-gunwi-small-facility-risk-2026-07-15` | 소규모공공시설 위험지정(39건) | 2026-07-15 | `drainage_risk.json` | 사용 |
| `datagokr-gunwi-water-supply-rate-2025-12-31` | 읍면별 상수도보급률 | 2025-12-31 | `water_supply.json` | 사용 |
| `sgis-admstat-2025-2q` | SGIS 행정구역 통계(2024년) | 2024-12-31 | `sgis_stats.json` | 19개 CSV 중 10개 사용 |
| `daegu-salpiso-reports-2024-11-27` | 대구 살피소 제보 처리현황 | 2024-11-27 | `salpiso.json` | 사용(군 단위 배경 수치, 웹 미공개) |

모든 폴더에 공통으로 있는 파일:

- `_meta.json` — 출처 카드. `prepare.py` 는 `provenance` 필드가 없으면 멈춘다.
- `capture.html` — 내려받은 페이지 화면 보존본(증빙용). 가공에 쓰지 않는다.

## 지역 코드: derived 의 공통 키

derived 의 모든 읍면 단위 값은 **`region_code`(주민등록 행정기관코드)** 로 묶인다.
원자료마다 지역 식별 방식이 달라서 `prepare.py` 가 한 번씩 맞춰 준다.

| 원자료 | 원래 지역 표기 | region_code 로 바꾸는 방법 |
|---|---|---|
| 주민등록 인구 | `2772025000` 등 | 그대로 (기준) |
| 경계 GeoJSON | `ADM_CD` `22520111` 등 | 읍면 **이름**으로 대응 (`prepare_boundary`) |
| SGIS 통계 | `22520111` 등 | 경계에 남긴 `source_adm_cd` 로 대응 |
| 경로당·위험시설 | 주소 문자열 | 주소 속 읍면 토큰으로 대응 |
| 상수도보급률 | `읍면명` 컬럼 | 이름으로 대응 |
| 포트홀 | 위경도 | 경계 다각형 안에 들어가는지 판정 |

| region_code | 읍면 | SGIS/경계 코드 |
|---|---|---|
| `2772000000` | 군위군 **합계** (읍면과 함께 더하지 말 것) | `22520` |
| `2772025000` | 군위읍 | `22520111` |
| `2772031000` | 소보면 | `22520311` |
| `2772032000` | 효령면 | `22520312` |
| `2772033000` | 부계면 | `22520313` |
| `2772034000` | 우보면 | `22520314` |
| `2772035000` | 의흥면 | `22520315` |
| `2772036000` | 산성면 | `22520316` |
| `2772037000` | 삼국유사면 | `22520317` |

---

## 1. 주민등록 인구 → `population.json`

**raw**: `mois-age-2025-12/age.json`, `mois-age-2026-08/age.json`
(행정안전부 jumin.mois.go.kr 조회 결과)

- 시점마다 9행(군 합계 1 + 읍면 8), 행마다 `[코드, 이름, 숫자 69칸]`.
- 69칸 = 성별 블록 3개(계·남·여) × 23칸(총계, 총계 중복, 5세 구간 21개: 0–4세 … 100세 이상).
- 숫자는 `"22,452"` 처럼 쉼표가 들어간 문자열.

**가공** (`prepare_population`)

1. 쉼표 제거 후 정수로 변환.
2. 검증: 블록마다 5세 구간 21개 합 = 총계 / 남 + 여 = 계 / 읍면 8개 합 = 군 합계.
3. 고령인구 `elderly` = 65세 이상 구간(인덱스 13~20) 합.

**derived**: 2시점 × 9행 = 18개 레코드

```json
{"period": "2025-12", "reference_date": "2025-12-31",
 "region_code": "2772025000", "region_name": "군위읍", "level": "eupmyeon",
 "population": 7852, "male": 4078, "female": 3774, "elderly": 2830}
```

- `level`: `gun`(군 합계) / `eupmyeon`.
- 고령화율은 저장하지 않는다. 화면에서 `elderly / population` 으로 계산한다.
- 2025-12 군 전체: 인구 22,452명, 65세 이상 10,992명(49.0%).

## 2. 읍면 경계 → `eupmyeon.geojson`

**raw**: `boundary-eupmyeon-2025-06-30/eupmyeon.geojson` (피처 8개)

- ⚠️ `provenance: UNVERIFIED`. 다운로드 이력이 없는 파일이다. 기준일 2025-06-30 도
  피처 속성 `BASE_DATE` 에서 읽었을 뿐 출처 문서로 확인되지 않았다.
- `boundary-alt.geojson` 은 속성 구조가 다른 대체본(역시 출처 미확인). **쓰지 않는다.**

**가공** (`prepare_boundary`)

1. 피처 `ADM_NM` 의 마지막 단어(읍면명)로 인구 데이터의 region_code 를 찾는다.
2. 검증: 피처 8개, 중복 없음, 인구의 읍면 8개와 집합이 같음.
3. 피처 속성을 아래 4개로 **교체**한다(원래 속성은 버린다). 도형은 그대로.

**derived**: 피처 8개 + 최상위 `_provenance: "UNVERIFIED"`

```json
{"region_code": "2772025000", "region_name": "군위읍",
 "source_adm_cd": "22520111", "base_date": "20250630"}
```

- `source_adm_cd` 는 SGIS 통계를 붙일 때 다리로 쓰인다(§7).
- `_provenance` 가 `verified` 가 아니면 웹 화면 상단에 경고 배너가 뜬다.

## 3. 도시공원 → `parks.json`

**raw**: `datagokr-park-2026-03-05/parks.json`(3행), `header.json`(컬럼 코드↔한글명)

- 공공데이터포털 전국도시공원정보 표준데이터 중 군위군 등록분 3건뿐.
  **군내 공원·녹지 전수가 아니다.**

**가공** (`prepare_parks`)

- 검증: 관리번호 중복 없음, 좌표가 군위 범위(경도 128.3~128.9, 위도 35.9~36.5) 안.
- 컬럼 8개만 골라 영문 키로 바꾼다.

**derived**: `column_labels`(header 매핑) + `parks` 3건

```json
{"manage_no": "27720-00003", "name": "서부제3어린이공원", "category": "어린이공원",
 "address": "대구광역시 군위군 군위읍 중앙4길 16-6",
 "lon": 128.5661865, "lat": 36.23..., "area_sqm": 1627.0, "reference_date": "2026-03-05"}
```

3건 모두 군위읍 어린이공원(서부제2·서부제3·동부제1). region_code 는 붙이지 않는다.

## 4. 포트홀 민원 → `potholes.json`

**raw**: `minwon-pothole-2026-10-13/`

| 파일 | 내용 | 가공에 사용 |
|---|---|---|
| `pothole_all.csv` | 전국 포트홀 민원 57,060행. 컬럼 `create_dt, event_lat, event_lon` 3개 | O |
| `progress.json` | `fetch_pothole.py` 가 완료한 15일 구간 44개 기록 | X |
| `test_response.txt` | 2025-01-01 하루치 API 원응답 표본(JSON) | X |

- `pothole_all.csv` 는 API 응답 그대로가 아니라 `tools/fetch_pothole.py` 가 3개 필드만 옮긴 것.
- 알려진 품질 문제: 완전중복 653행, 위도에 쉼표 소수점(`37,642`)이 들어간 2행.

**가공** (`prepare_potholes`)

1. 품질 문제는 **고치지 않고 개수만 센다.** 좌표 파싱이 안 되는 행은 버린다.
2. 경계 전체 외접사각형으로 먼저 거른 뒤, 남은 점을 읍면 다각형마다 포함 판정.
3. 읍면 안에 들어간 점에 region_code 를 붙인다(두 읍면에 동시에 속하면 멈춘다).

**derived**: 전국 57,060행 중 **군위 4건** (우보면 2, 효령면 2)

```json
{"source_id": "MINWON_POTHOLE_LATLON", "period": ["2025-01-01", "2026-10-13"],
 "boundary_provenance": "UNVERIFIED",
 "national_row_count": 57060, "exact_duplicate_count": 653, "unparsable_coord_count": 2,
 "points": [{"date": "2025-03-12", "lat": 36.19..., "lon": 128.66...,
             "region_code": "2772034000", "region_name": "우보면"}, ...]}
```

- 표본이 너무 적어 **읍면 비교 지표로 쓰지 않는다.** 지도에 지점으로만 표시.
- 읍면 판정이 출처 미확인 경계(§2)에 의존한다.

## 5. 경로당 → `senior_centers.json`

**raw**: `datagokr-gunwi-senior-2025-12-19/15114136_gunwi.csv` (215행, UTF-8 BOM)

- 전국 마을회관·경로당 표준데이터에서 팀원이 군위군만 추출한 파일
  (`provenance: verified_import`, 정부 원본 바이트 아님).
- 컬럼: 시설명, 시설유형, 소재지도로명주소, 소재지지번주소, 위도, 경도, 영업상태명,
  전화번호, 건립일자, 건물면적, 관리기관명, 데이터기준일자.
- 건립일자가 전 행 `YYYY-01-01` 이라 **연도 정밀도**로만 쓸 수 있다.

**가공** (`prepare_senior_centers`)

1. 검증: 시설유형이 모두 `경로당`, 건립일자 형식 유지, 좌표가 군위 범위 안, 이름+주소 중복 없음.
2. 도로명·지번 주소에서 읍면명을 찾아 region_code 부여(두 주소가 다른 읍면이면 멈춤).
3. 건립일자 → `built_year`(연도만).
4. 읍면별 개수와 **노후 경로당 수**(2000년 이전 건립) 집계.

**derived**

```json
{"reference_date": "2025-12-19", "provenance": "verified_import", "old_before_year": 2000,
 "by_region": {"2772025000": {"count": 38, "old_count": 8}, ...},
 "centers": [{"name": "동부1리 경로당", "region_code": "2772025000",
              "address": "대구광역시 군위군 군위읍 동서길 27", "lon": 128.565, "lat": 36.236,
              "built_year": 2009, "floor_area_sqm": 157.56, "status": "영업",
              "reference_date": "2025-12-19", "source_row": 1}, ...]}
```

| 읍면 | 군위읍 | 소보면 | 효령면 | 부계면 | 우보면 | 의흥면 | 산성면 | 삼국유사면 | 계 |
|---|---|---|---|---|---|---|---|---|---|
| 경로당 | 38 | 33 | 36 | 17 | 28 | 28 | 15 | 20 | 215 |
| 2000년 이전 건립 | 8 | 4 | 4 | 5 | 4 | 8 | 4 | 4 | 41 |

- **2000년 기준은 공식 기준이 아니라 프로젝트 임시값**이다(`SENIOR_OLD_BEFORE_YEAR`).
- `source_row` 로 원본 CSV 몇 번째 행인지 추적할 수 있다.

## 6. 소규모공공시설 위험지정 → `drainage_risk.json`

**raw**: `datagokr-gunwi-small-facility-risk-2026-07-15/대구광역시_군위군_소규모공공시설위험지정정보_20260715.csv`
(39행 16컬럼, UTF-8 BOM). `capture-file-detail.html` 은 파일 상세 페이지 증빙.

- 시설유형: 세천 28 · 소교량 7 · 농로 3 · 마을진입로 1.
- 위험시설해제일자가 있는 행 1건(내량천, 2018-06-05 해제).
- 지정사유·도로명주소·시설부속물 컬럼은 전부 공란, 폭은 13행만 있음.

**가공** (`prepare_drainage_risk`)

1. 시설유형 **`세천`만** 남긴다(배수시설 관점).
2. 해제일자가 있는 행은 제외 → 현행 지정 세천 **27곳**.
3. 좌표 범위 검증, 주소로 region_code 부여.

**derived**

```json
{"reference_date": "2026-07-15", "provenance": "verified",
 "source_type_counts": {"세천": 28, "소교량": 7, "마을진입로": 1, "농로": 3},
 "released_excluded": ["내량천"],
 "by_region": {"2772033000": {"count": 7}, ...},
 "sites": [{"name": "새터천", "region_code": "2772033000",
            "address": "대구광역시 군위군 부계면 춘산리 957", "lon": 128.658, "lat": 36.093,
            "designated_on": "2017-02-28", "notice_no": "군위군 고시 제2017-14호(2017.2.28)",
            "length_m": 300.0, "width_m": 4.0, "reference_date": "2026-07-15", "source_row": 2}, ...]}
```

| 읍면 | 군위읍 | 소보면 | 효령면 | 부계면 | 우보면 | 의흥면 | 산성면 | 삼국유사면 | 계 |
|---|---|---|---|---|---|---|---|---|---|
| 위험지정 세천 | 3 | 2 | 3 | 7 | 3 | 2 | 4 | 3 | 27 |

- **빗물받이·맨홀 전수대장이 아니다.** 군이 위험시설로 지정한 세천 목록일 뿐이다.
- 소교량·농로·마을진입로는 derived 에 개수(`source_type_counts`)만 남는다.

## 7. 상수도보급률 → `water_supply.json`

**raw**: `datagokr-gunwi-water-supply-rate-2025-12-31/대구광역시 군위군_상수도보급률 현황_20260622.csv`
(8행, **cp949 인코딩**). 컬럼: 시도명, 시군구명, 읍면명, `상수도보급률(2025년 12월말 기준)`.

- 파일명의 `20260622` 는 포털 갱신일이다. 기준일은 컬럼명에 적힌 2025년 12월말.
- 군 합계 행은 없다.

**가공** (`prepare_water_supply`): 읍면명 → region_code, 값이 0~100 범위인지 검증.

**derived**

| 읍면 | 군위읍 | 소보면 | 효령면 | 부계면 | 우보면 | 의흥면 | 산성면 | 삼국유사면 |
|---|---|---|---|---|---|---|---|---|
| `supply_rate_pct` | 95 | 92 | 96 | 86 | 98 | 99 | 99 | **65** |

- 읍면 값을 단순 평균해 군 전체 보급률로 쓰지 말 것(인구 가중이 아니다).

## 8. SGIS 행정구역 통계 → `sgis_stats.json`

**raw**: `sgis-admstat-2025-2q/` CSV 19개 (**cp949**). 전국 파일(269MB zip, 저장소 밖 보관)에서
군위군(SGIS 코드 `22520`) 행만 걸러낸 것. 형식은 모두 같다:

```
기준연도,행정구역코드,통계항목,통계값
2024,22520,to_in_001,21493
```

⚠️ SGIS 제공용 코드는 `22520` 계열이다. 행정구역코드 `27720` 으로 찾으면 0행이 나온다.

**사용하는 10개 파일** (항목코드 1개씩, 군 1 + 읍면 8 = 9행)

| 파일 접미 | 항목코드 | derived 키 | 단위 | 읍면합=군합 검사 |
|---|---|---|---|---|
| 인구총괄(총인구) | `to_in_001` | `population` | 명 | O |
| 인구총괄(평균나이) | `to_in_002` | `avg_age` | 세 | |
| 인구총괄(인구밀도) | `to_in_003` | `density_per_km2` | 명/㎢ | |
| 인구총괄(노령화지수) | `to_in_004` | `aging_index` | 유소년 100명당 고령인구 | |
| 인구총괄(노년부양비) | `to_in_005` | `old_dependency` | 생산연령 100명당 고령인구 | |
| 인구총괄(유년부양비) | `to_in_006` | `young_dependency` | 생산연령 100명당 유소년 | |
| 가구총괄 | `to_ga_001` | `households` | 가구 | O |
| 주택총괄_총주택(거처)수 | `to_ho_001` | `houses` | 호 | O |
| 산업분류별(11차_대분류)_총괄사업체수 | `to_fa_010` | `businesses` | 개 | O |
| 산업분류별(11차_대분류)_총괄종사자수 | `to_em_020` | `employees` | 명 | O |

**쓰지 않는 9개 파일**: 건축년도별주택, 주택유형별주택, 연건평별주택, 세대구성별가구,
성연령별인구, 산업분류별 대분류 사업체수·종사자수, 중분류 사업체수·종사자수.
주택 세부 항목은 사유 재산이라 공공시설 관리 분석 범위 밖으로 뺐다.

**가공** (`prepare_sgis_stats`)

1. 경계 derived 의 `source_adm_cd` → `region_code` 대응표로 SGIS 코드를 바꾼다.
2. 검증: 기준연도 2024, 지역코드가 군 1 + 읍면 8.
3. 더할 수 있는 항목(O)은 읍면 8개 합 = 군 합계인지 검산.
4. `N/A`(비공개 소수 셀)는 0 이 아니라 `null` 로 두고 `na_cells` 에 기록 (현재 0칸).
5. 코드 매핑 검산: SGIS 인구가 2025-12 주민등록 인구와 15% 넘게 다르면 멈춘다.

**derived**

```json
{"reference_date": "2024-12-31", "provenance": "verified",
 "items": {"population": {"sgis_code": "to_in_001", "label": "인구총괄(총인구)", "unit": "명"}, ...},
 "na_cells": [],
 "gun_total": {"population": 21493, "avg_age": 59.2, "density_per_km2": 35.1,
               "aging_index": 1188.7, "old_dependency": 89.6, "young_dependency": 7.5,
               "households": 10883, "houses": 9735, "businesses": 3372, "employees": 9893},
 "by_region": {"2772025000": {"population": 7606, "avg_age": 52.7, ...}, ...}}
```

- SGIS 인구(등록센서스, 2024)와 주민등록 인구(§1)는 **정의가 달라 값이 다르다**
  (군 전체 21,493 vs 22,452). 한 표에서 섞어 쓰지 말 것.

## 9. 살피소 제보 처리현황 → `salpiso.json`

**raw**: `daegu-salpiso-reports-2024-11-27/대구광역시_살피소처리현황.csv` (14행 × 15열, UTF-8 BOM)

- 컬럼: 구분, 제보, 처리, 미처리, 반송 + 분야 10개(건축건설·도로시설·교통시설·각종시설물·
  환경청소·공원녹지·광고물·현수막·도로적치물·기타).
- 행은 **처리기관 단위**(본청·사업본부 5개 + 구군 9개). 읍면 구분이 없다.
- 주의: `대구광역시` 행은 시 합계가 아니라 본청 몫이다. 전체는 14행 합(253,043).
- 집계 연도가 확정되지 않았다(파일명 기준 2023년분, 등록일 기준 2024년분 추정).

**가공** (`prepare_salpiso`)

1. 검증: 14행, 분야 컬럼 10개 순서 유지, 행마다 처리+미처리+반송 = 제보, 분야 합 = 제보.
2. 군위군 1행과 14행 합계(대구 전체)를 따로 남긴다.

**derived**

```json
{"reference_date": "2024-11-27", "fields": ["건축건설", ...],
 "gunwi": {"agency": "군위군", "reports": 87,
           "status": {"처리": 68, "미처리": 10, "반송": 9},
           "by_field": {"현수막": 37, "도로시설": 13, "교통시설": 13, ...}},
 "daegu_all": {"reports": 253043, "by_field": {...}},
 "agencies": [...]}
```

- 군 단위 1행이라 **읍면 비교 지표로 쓰지 않는다.** `build.py` 는 이 파일을 공개하지 않는다.
- 쓰는 곳: 가설 레지스트리의 배경 근거 E1, 그림4(군위군 vs 대구 전체 분야 구성).

---

## derived 다음 단계

| derived | `build.py` → `public/data/` | `export_excel.py` → `outputs/` |
|---|---|---|
| `population.json` | `regions.json` 에 합쳐짐(군 합계 행 제거) | 결과표 |
| `sgis_stats.json` | `regions.json` 에 합쳐짐 | 결과표 |
| `senior_centers.json` | `regions.json`(읍면 집계·노후 비율) + `facilities.json`(지점) | 결과표 |
| `drainage_risk.json` | `regions.json`(읍면 집계) + `facilities.json`(지점) | 결과표 |
| `water_supply.json` | `regions.json` | 결과표 |
| `eupmyeon.geojson` | 그대로 복사 | — |
| `parks.json` | `parks` 배열만 | — |
| `potholes.json` | 지점만 공개(전국 행수·품질 집계는 derived 에 남음) | — |
| `salpiso.json` | 공개하지 않음 | — (그림4 · 가설 E1 에만) |

## 원자료를 바꿀 때

1. 새 자료는 **새 폴더**로 받는다(`tools/add_source.py`). 기존 raw 파일은 고치지 않는다.
2. `python tools/prepare.py` — 구조가 바뀌었으면 assert 에서 멈추고 이유를 출력한다.
3. derived 가 이상하면 derived 를 고치지 말고 `prepare.py` 를 고친다.
