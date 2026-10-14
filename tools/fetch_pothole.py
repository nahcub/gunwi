#!/usr/bin/env python3
"""포트홀 민원 위경도 수집기
(공공데이터포털 / 국민권익위원회 민원빅데이터 분석정보 API, minPotholeLatLonInfo)

사용법 (터미널):
  1) 인증키를 환경변수로 넣기 (코드에 직접 적지 않기)
       Mac/Linux : export DATA_GO_KR_KEY='발급받은 일반 인증키'
       Windows PS: $env:DATA_GO_KR_KEY='발급받은 일반 인증키'
  2) 하루치로 먼저 시험
       python3 fetch_pothole.py --test 20250101
  3) 전체 수집 (하루 호출 한도에 맞춰 --max-calls 조절, 다시 실행하면 이어서 받음)
       python3 fetch_pothole.py --start 20250101 --end 20261013 --max-calls 90

결과 파일 (프로젝트 루트 = tools/의 상위 폴더에 생성):
  pothole_all.csv        전국 포트홀 좌표 원본 (create_dt, event_lat, event_lon)
  gunwi_candidate.csv    군위군 대략 범위(bbox)로 거른 것 -> 정확한 행정경계로 다시 거를 것
  progress.json          완료한 구간 기록 (이어받기용)
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# 인증키는 환경변수 DATA_GO_KR_KEY 로만 넣는다. 이 저장소는 공개라서
# 여기에 키를 적고 커밋하면 그대로 인터넷에 노출된다.
API_KEY = ""

PATH = "apis.data.go.kr/1140100/minAnalsInfoView7/minPotholeLatLonInfo"
# 어느 폴더에서 실행하든 프로젝트 루트(tools/의 상위)에 저장한다
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_CSV = os.path.join(ROOT, "pothole_all.csv")
OUT_CSV = os.path.join(ROOT, "gunwi_candidate.csv")
PROGRESS = os.path.join(ROOT, "progress.json")
MAX_DAYS = 15  # API 조회 가능 기간 최대 15일


class QuotaExceeded(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class ServerError(Exception):
    """서버 쪽 일시 오류 (NullPointerException, 빈 body, 타임아웃 등)"""
    pass


class RateLimited(Exception):
    """같은 키로 연속 요청해 잠시 막힘 (요청 사이 약 1분 간격 필요)"""
    pass


def make_key(raw):
    # Decoding 키를 넣든 Encoding 키를 넣든 한 번만 인코딩되게 맞춘다
    if "%" in raw:
        raw = urllib.parse.unquote(raw)
    return urllib.parse.quote(raw, safe="")


def find_key(obj, name):
    """중첩된 JSON에서 name 키의 값을 찾는다."""
    if isinstance(obj, dict):
        if name in obj:
            return obj[name]
        for v in obj.values():
            r = find_key(v, name)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, name)
            if r is not None:
                return r
    return None


def to_items(items):
    if items is None or items == "":
        return []
    if isinstance(items, dict) and "item" in items:
        items = items["item"]
    if isinstance(items, dict):
        return [items]
    if isinstance(items, list):
        # [{"item": {...}}, ...] 처럼 한 겹씩 싸여 오는 경우도 푼다
        items = [i["item"] if isinstance(i, dict) and "item" in i else i
                 for i in items]
        return [i for i in items if isinstance(i, dict)]
    return []


def parse(text):
    """(totalCount, items) 반환. 오류 응답이면 예외."""
    if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in text:
        raise QuotaExceeded(text[:200])
    if "요청이연속" in text or "요청이 연속" in text or "잠시 제한" in text:
        raise RateLimited(text[:200])
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        obj = json.loads(text)
        total = find_key(obj, "totalCount")
        items = to_items(find_key(obj, "items"))
        if total is None:
            raise ServerError(text[:300])
        return int(total), items
    # XML
    root = ET.fromstring(text)
    total = root.findtext(".//totalCount")
    if total is None:
        raise RuntimeError("오류 응답: " + text[:300])
    items = []
    for it in root.iter("item"):
        items.append({c.tag: (c.text or "") for c in it})
    return int(total), items


def fetch(key, d1, d2, scheme):
    url = (f"{scheme}://{PATH}?serviceKey={key}"
           f"&dateFrom={d1}&dateTo={d2}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in body:
            raise QuotaExceeded(body[:200])
        if e.code >= 500:
            raise ServerError(f"HTTP {e.code}: {body[:300]}")
        raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ServerError(f"네트워크 오류: {e}")
    return text, *parse(text)


def d2s(d):
    return d.strftime("%Y%m%d")


def s2d(s):
    return datetime.strptime(s, "%Y%m%d")


class Collector:
    def __init__(self, key, scheme, max_calls, sleep):
        self.key, self.scheme = key, scheme
        self.max_calls, self.sleep = max_calls, sleep
        self.calls = 0
        self.last = None  # 마지막 호출 시각
        self.warnings = []

    def wait(self, sec):
        if self.last is not None:
            left = sec - (time.monotonic() - self.last)
            if left > 0:
                time.sleep(left)

    def call(self, d1, d2, retries=5, server_retries=2):
        if self.calls >= self.max_calls:
            raise BudgetExceeded()
        self.calls += 1
        i = j = 0
        while True:
            self.wait(self.sleep)
            self.last = time.monotonic()
            try:
                _, total, items = fetch(self.key, d1, d2, self.scheme)
                return total, items
            except RateLimited:
                i += 1
                if i > retries:
                    raise
                print(f"  {d1}~{d2}: 연속 요청 제한 -> 70초 뒤 재시도 ({i}/{retries})")
                self.wait(70)
            except ServerError as e:
                j += 1
                if j > server_retries:
                    raise
                print(f"  {d1}~{d2}: 서버 오류 -> 재시도 ({j}/{server_retries}): "
                      f"{str(e)[:80]!r}")

    def collect(self, d1, d2):
        """구간을 받고, totalCount보다 적게 왔으면 반으로 쪼개 다시 받는다."""
        a, b = s2d(d1), s2d(d2)
        try:
            total, items = self.call(d1, d2)
        except ServerError:
            if a == b:
                raise
            # 계속 실패하면 구간이 커서일 수 있으니 반으로 쪼개 본다
            print(f"  {d1}~{d2}: 계속 실패 -> 구간을 반으로 나눠 다시 받음")
            mid = a + (b - a) // 2
            return (self.collect(d1, d2s(mid)) +
                    self.collect(d2s(mid + timedelta(days=1)), d2))
        if len(items) >= total:
            return items
        if a == b:
            self.warnings.append(
                f"{d1}: totalCount={total}인데 {len(items)}건만 옴 (응답 크기 제한 가능성)")
            return items
        mid = a + (b - a) // 2
        return (self.collect(d1, d2s(mid)) +
                self.collect(d2s(mid + timedelta(days=1)), d2))


def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding="utf-8") as f:
            return json.load(f)
    return {"done": []}


def save_progress(p):
    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False)


def append_rows(items):
    new = not os.path.exists(RAW_CSV)
    with open(RAW_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["create_dt", "event_lat", "event_lon"])
        for it in items:
            w.writerow([it.get("create_dt", ""), it.get("event_lat", ""),
                        it.get("event_lon", "")])


def filter_bbox(lat_min, lat_max, lon_min, lon_max):
    if not os.path.exists(RAW_CSV):
        return 0
    n = 0
    with open(RAW_CSV, encoding="utf-8-sig") as f, \
            open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as g:
        r, w = csv.DictReader(f), csv.writer(g)
        w.writerow(["create_dt", "event_lat", "event_lon"])
        for row in r:
            try:
                la, lo = float(row["event_lat"]), float(row["event_lon"])
            except ValueError:
                continue
            if lat_min <= la <= lat_max and lon_min <= lo <= lon_max:
                w.writerow([row["create_dt"], row["event_lat"], row["event_lon"]])
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", metavar="YYYYMMDD", help="하루치만 호출해서 응답 확인")
    ap.add_argument("--start", default="20250101")
    ap.add_argument("--end", default=d2s(datetime.now() - timedelta(days=1)))
    ap.add_argument("--chunk-days", type=int, default=MAX_DAYS,
                    help="한 번에 요청할 일수 (잘려 오면 자동으로 반씩 쪼갬)")
    ap.add_argument("--max-calls", type=int, default=90,
                    help="이번 실행에서 최대 호출 수 (개발계정 한도 이하로)")
    ap.add_argument("--sleep", type=float, default=61,
                    help="호출 사이 최소 간격(초). 같은 키는 약 1분 간격 필요")
    ap.add_argument("--http", action="store_true", help="https가 안 되면 http로")
    # 군위군 대략 범위 (이웃 시군 일부가 섞임: 나중에 행정경계로 정밀 필터)
    ap.add_argument("--lat-min", type=float, default=36.05)
    ap.add_argument("--lat-max", type=float, default=36.40)
    ap.add_argument("--lon-min", type=float, default=128.40)
    ap.add_argument("--lon-max", type=float, default=128.95)
    a = ap.parse_args()
    a.chunk_days = max(1, min(a.chunk_days, MAX_DAYS))

    raw_key = (os.environ.get("DATA_GO_KR_KEY") or API_KEY).strip()
    if not raw_key:
        sys.exit("환경변수 DATA_GO_KR_KEY 에 인증키를 넣어 주세요 (파일 맨 위 사용법 참고).")
    key = make_key(raw_key)
    scheme = "http" if a.http else "https"

    if a.test:
        text, total, items = fetch(key, a.test, a.test, scheme)
        with open(os.path.join(ROOT, "test_response.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        print(f"totalCount={total}, 실제 받은 건수={len(items)}")
        for it in items[:3]:
            print(it)
        if len(items) < total:
            print("!! 받은 건수가 totalCount보다 적음 -> 응답 크기 제한 가능성. "
                  "test_response.txt를 확인하세요.")
        print("원본 응답은 test_response.txt에 저장됨")
        return

    col = Collector(key, scheme, a.max_calls, a.sleep)
    prog = load_progress()
    done = {tuple(x) for x in prog["done"]}
    cur, end = s2d(a.start), s2d(a.end)
    stopped = None
    done_spans = [(s2d(x), s2d(y)) for x, y in done]
    while cur <= end:
        # 이미 받은 구간(--chunk-days를 바꿨어도)에 걸리면 그 끝 다음 날로 건너뛴다
        hit = next((y for x, y in done_spans if x <= cur <= y), None)
        if hit:
            cur = hit + timedelta(days=1)
            continue
        c_end = min(cur + timedelta(days=a.chunk_days - 1), end)
        # 다음 받은 구간과 겹치지 않게 끊는다
        nxt = [x for x, _ in done_spans if cur < x <= c_end]
        if nxt:
            c_end = min(nxt) - timedelta(days=1)
        span = (d2s(cur), d2s(c_end))
        if span not in done:
            try:
                items = col.collect(*span)
            except BudgetExceeded:
                stopped = "이번 실행의 --max-calls에 도달"
                break
            except QuotaExceeded as e:
                stopped = f"일일 호출 한도 초과: {e}"
                break
            except (ServerError, RateLimited) as e:
                stopped = f"{span[0]}~{span[1]} 서버 오류가 계속됨: {str(e)[:150]}"
                break
            append_rows(items)
            prog["done"].append(list(span))
            save_progress(prog)
            print(f"{span[0]}~{span[1]}: {len(items)}건 (누적 호출 {col.calls})")
        cur = c_end + timedelta(days=1)

    n = filter_bbox(a.lat_min, a.lat_max, a.lon_min, a.lon_max)
    print(f"\n호출 {col.calls}회, 군위 후보 {n}건 -> {OUT_CSV}")
    for w in col.warnings:
        print("경고:", w)
    if stopped:
        print("중단:", stopped, "-> 같은 명령으로 다시 실행하면 이어서 받습니다.")
    else:
        print("지정한 기간 수집 완료")


if __name__ == "__main__":
    main()