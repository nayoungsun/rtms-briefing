#!/usr/bin/env python3
"""
국토교통부 아파트 매매 실거래가 상세자료(RTMSDataSvcAptTradeDev)를 이용해
'어제 새로 공개시스템에 등록된 실거래'를 추출한다.

핵심 아이디어
-------------
국토부 API/공개시스템은 '신고일(공개 등록일)' 필드를 제공하지 않는다.
대신 데이터가 매일 갱신되므로, 매일 같은 범위를 조회해 스냅샷을 저장하고
어제 스냅샷에 없던 레코드 = '어제 새로 등록된 건' 으로 판정한다.
(아실·호갱노노·리치고의 '오늘 실거래' 도 동일한 방식이다.)

스냅샷은 발행된 아티팩트 HTML 안에 gzip+base64 로 임베드해 보관하므로
세션이 매번 새로 시작되어도 상태가 이어진다.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

KST = timezone(timedelta(hours=9))
BASE = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_MARKER = "rtms-snapshot"


# --------------------------------------------------------------------------
# 수집
# --------------------------------------------------------------------------

def _text(node: ET.Element, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


_throttle = __import__("threading").Semaphore(1)
_last_call = [0.0]
MIN_GAP = 0.25   # 요청 사이 최소 간격(초). 429 방지용.


def _pace() -> None:
    with _throttle:
        gap = time.monotonic() - _last_call[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last_call[0] = time.monotonic()


def fetch_month(service_key: str, lawd_cd: str, deal_ymd: str,
                retries: int = 7) -> list[dict[str, Any]]:
    """한 시군구 × 한 계약년월의 전체 거래를 가져온다.

    공공데이터포털은 동시 요청이 몰리면 429(Too Many Requests)를 돌려준다.
    429는 '키가 잘못됐다'가 아니라 '천천히 보내라'는 뜻이므로 지수 백오프로 기다렸다 재시도한다.
    """
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        qs = urlencode({
            "serviceKey": service_key,
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": deal_ymd,
            "pageNo": page,
            "numOfRows": 1000,
        }, safe="%")
        url = f"{BASE}?{qs}"

        body = None
        last_exc: Exception | None = None
        for attempt in range(retries):
            _pace()
            try:
                with urlopen(url, timeout=45) as resp:
                    body = resp.read().decode("utf-8", "replace")
                break
            except HTTPError as exc:
                last_exc = exc
                if exc.code in (429, 500, 502, 503, 504):
                    wait = min(60.0, 2.0 * (2 ** attempt))   # 2,4,8,16,32,60,60
                    ra = exc.headers.get("Retry-After") if exc.headers else None
                    if ra and str(ra).strip().isdigit():
                        wait = max(wait, float(ra))
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"{lawd_cd}/{deal_ymd} 조회 실패: {exc}") from exc
            except (URLError, TimeoutError) as exc:
                last_exc = exc
                time.sleep(min(30.0, 2.0 * (attempt + 1)))
        if body is None:
            raise RuntimeError(f"{lawd_cd}/{deal_ymd} 조회 실패({retries}회 재시도): {last_exc}")

        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise RuntimeError(f"{lawd_cd}/{deal_ymd} XML 파싱 실패: {body[:300]}") from exc

        code = _text(root, ".//resultCode") or _text(root, ".//returnReasonCode")
        if code and code not in ("00", "000"):
            msg = _text(root, ".//resultMsg") or _text(root, ".//returnAuthMsg")
            raise RuntimeError(f"API 오류 [{code}] {msg} ({lawd_cd}/{deal_ymd})")

        items = root.findall(".//item")
        for it in items:
            amount_raw = _text(it, "dealAmount").replace(",", "").strip()
            if not amount_raw.isdigit():
                continue
            rows.append({
                "sggCd": _text(it, "sggCd") or lawd_cd,
                "umdNm": _text(it, "umdNm"),
                "aptNm": _text(it, "aptNm"),
                "jibun": _text(it, "jibun"),
                "excluUseAr": _text(it, "excluUseAr"),
                "floor": _text(it, "floor"),
                "dealYear": _text(it, "dealYear"),
                "dealMonth": _text(it, "dealMonth"),
                "dealDay": _text(it, "dealDay"),
                "dealAmount": int(amount_raw),          # 만원
                "buildYear": _text(it, "buildYear"),
                "dealingGbn": _text(it, "dealingGbn"),   # 중개거래 / 직거래
                "cdealDay": _text(it, "cdealDay"),       # 해제사유발생일
                "cdealType": _text(it, "cdealType"),     # 해제여부 O
                "rgstDate": _text(it, "rgstDate"),       # 등기일자
                "estateAgentSggNm": _text(it, "estateAgentSggNm"),
            })

        total = _text(root, ".//totalCount")
        if not total.isdigit() or page * 1000 >= int(total):
            break
        page += 1

    return rows


def months_back(n: int, today: date) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def collect(service_key: str, regions: list[dict], months: list[str],
            workers: int = 3) -> tuple[list[dict], list[str]]:
    """전 구간을 수집한다. (결과, 실패목록) 을 돌려준다."""
    jobs = [(r, ym) for r in regions for ym in months]
    total = len(jobs)
    results: list[dict] = []
    errors: list[str] = []
    done = [0]
    lock = __import__("threading").Lock()

    def run(job):
        region, ym = job
        try:
            rows = fetch_month(service_key, region["code"], ym)
        except RuntimeError as exc:
            errors.append(str(exc))
            rows = []
        else:
            for row in rows:
                row["sido"] = region["sido"]
                row["sgg"] = region["sgg"]
        with lock:
            done[0] += 1
            n = done[0]
        if n % 10 == 0 or n == total:
            print(f"      {n}/{total} ({n * 100 // total}%)"
                  + (f"  실패 {len(errors)}" if errors else ""),
                  file=sys.stderr, flush=True)
        return rows

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in pool.map(run, jobs):
            results.extend(chunk)

    if errors and len(errors) == total:
        raise SystemExit(
            "모든 요청이 실패했습니다. 인증키 또는 활용신청 상태를 확인하세요.\n" + errors[0])

    return results, errors


# --------------------------------------------------------------------------
# 키 / 스냅샷
# --------------------------------------------------------------------------

def deal_date(row: dict) -> str:
    return f"{row['dealYear']}-{int(row['dealMonth']):02d}-{int(row['dealDay']):02d}"


def record_key(row: dict) -> str:
    """한 거래를 유일하게 식별하는 키 (해제건은 별도 표시)."""
    return "|".join([
        row["sggCd"], row["umdNm"], row["aptNm"], row["excluUseAr"],
        row["floor"], deal_date(row), str(row["dealAmount"]),
        "X" if row.get("cdealType") else "",
    ])


def pack_snapshot(keys: set[str], meta: dict) -> str:
    payload = json.dumps({"meta": meta, "keys": sorted(keys)},
                         ensure_ascii=False, separators=(",", ":")).encode()
    return base64.b64encode(gzip.compress(payload, 9)).decode()


def unpack_snapshot(blob: str) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(blob)).decode())


def snapshot_from_html(html: str) -> dict | None:
    """이전에 발행한 아티팩트 HTML에서 스냅샷을 추출한다."""
    m = re.search(
        rf'<script[^>]*id="{SNAPSHOT_MARKER}"[^>]*>\s*([A-Za-z0-9+/=\s]+?)\s*</script>',
        html, re.S)
    if not m:
        return None
    try:
        return unpack_snapshot(re.sub(r"\s+", "", m.group(1)))
    except Exception:
        return None


# --------------------------------------------------------------------------
# 분석
# --------------------------------------------------------------------------

def won(man: int) -> str:
    """만원 정수 -> '12억 3,450만원'"""
    eok, rest = divmod(man, 10000)
    if eok and rest:
        return f"{eok}억 {rest:,}만원"
    if eok:
        return f"{eok}억원"
    return f"{rest:,}만원"


def delta_str(man: int) -> str:
    sign = "+" if man > 0 else "−" if man < 0 else "±"
    return f"{sign}{won(abs(man))}" if man else "보합"


def unit_key(row: dict) -> tuple:
    """직전거래 비교 단위: 같은 단지 + 같은 전용면적."""
    return (row["sggCd"], row["umdNm"], row["aptNm"], row["excluUseAr"])


def find_previous(row: dict, history: list[dict]) -> dict | None:
    """같은 단지·같은 평형의 직전 거래(계약일 기준 이전, 해제건 제외)."""
    d = deal_date(row)
    cands = [h for h in history
             if deal_date(h) < d and not h.get("cdealType")]
    if not cands:
        return None
    return max(cands, key=lambda h: (deal_date(h), h["dealAmount"]))


def redevelopment_note(row: dict, watchlist: list[dict], this_year: int) -> str | None:
    for w in watchlist:
        if w["sgg"] == row["sgg"] and w["name_contains"] in row["aptNm"]:
            return w["stage"]
    by = row.get("buildYear", "")
    if by.isdigit() and this_year - int(by) >= 30:
        return f"준공 {by}년 · {this_year - int(by)}년차 (재건축 연한 30년 경과)"
    return None


def band_of(amount: int, bands: list[dict]) -> dict | None:
    for b in bands:
        if b["min"] <= amount <= b["max"]:
            return b
    return None


def analyse(new_rows: list[dict], all_rows: list[dict], cfg: dict,
            today: date) -> dict:
    by_unit: dict[tuple, list[dict]] = defaultdict(list)
    for r in all_rows:
        by_unit[unit_key(r)].append(r)

    bands = cfg["bands"]
    watch = cfg["redevelopment_watchlist"]

    out: dict[str, Any] = {b["id"]: defaultdict(list) for b in bands}
    redev: list[dict] = []

    for r in new_rows:
        prev = find_previous(r, by_unit[unit_key(r)])
        item = {
            "sido": r["sido"],
            "sgg": r["sgg"],
            "umd": r["umdNm"],
            "apt": r["aptNm"],
            "area": r["excluUseAr"],
            "floor": r["floor"],
            "amount": r["dealAmount"],
            "amount_txt": won(r["dealAmount"]),
            "deal_date": deal_date(r),
            "build_year": r["buildYear"],
            "dealing": r["dealingGbn"],
            "cancelled": bool(r.get("cdealType")),
            "cancel_day": r.get("cdealDay", ""),
            "redev": redevelopment_note(r, watch, today.year),
        }
        if prev:
            diff = r["dealAmount"] - prev["dealAmount"]
            item["prev_amount_txt"] = won(prev["dealAmount"])
            item["prev_date"] = deal_date(prev)
            item["diff"] = diff
            item["diff_txt"] = delta_str(diff)
            item["diff_pct"] = round(diff / prev["dealAmount"] * 100, 1)
        else:
            item["diff"] = None
            item["diff_txt"] = "직전거래 확인 불가"

        b = band_of(r["dealAmount"], bands)
        if b:
            out[b["id"]][f'{r["sido"]} {r["sgg"]}'].append(item)
        if item["redev"]:
            redev.append(item)

    for bid in out:
        for k in out[bid]:
            out[bid][k].sort(key=lambda i: -i["amount"])
        out[bid] = dict(sorted(out[bid].items()))

    redev.sort(key=lambda i: -i["amount"])
    return {"bands": out, "redev": redev}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> None:
    key = os.environ.get("MOLIT_SERVICE_KEY", "").strip()
    if not key:
        raise SystemExit("환경변수 MOLIT_SERVICE_KEY 가 필요합니다 (공공데이터포털 일반 인증키).")

    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    today = datetime.now(KST).date()
    hist_months = months_back(cfg["history_months"], today)
    diff_months = set(months_back(cfg["diff_months"], today))

    print(f"[1/4] 수집: {len(cfg['regions'])}개 시군구 × {len(hist_months)}개월"
          f" = {len(cfg['regions']) * len(hist_months)}회 호출", file=sys.stderr)
    rows, errors = collect(key, cfg["regions"], hist_months)
    print(f"      총 {len(rows):,}건", file=sys.stderr)

    if errors:
        print(f"\n[중단] {len(errors)}개 구간을 끝내 가져오지 못했습니다.", file=sys.stderr)
        for e in errors[:5]:
            print("       " + e, file=sys.stderr)
        raise SystemExit(
            "\n일부 구간이 빠진 채로 스냅샷을 저장하면, 다음 실행 때 그 거래들이\n"
            "전부 '신규 등록'으로 잘못 잡힙니다. 그래서 저장하지 않고 멈춥니다.\n"
            "잠시 후 다시 실행해 주세요. 계속 실패하면 config.json 의\n"
            "history_months 를 6 정도로 줄이면 호출량이 줄어 통과할 수 있습니다.")

    # 스냅샷 창(최근 diff_months)에 해당하는 레코드만 diff 대상
    window = [r for r in rows if f'{r["dealYear"]}{int(r["dealMonth"]):02d}' in diff_months]
    today_keys = {record_key(r) for r in window}

    # 스냅샷은 gzip 으로 보관한다(git 저장소에 매일 커밋되므로 용량이 중요).
    # 예전 비압축 파일이 있으면 그것도 읽어준다.
    snap_path = os.path.join(HERE, "prev_snapshot.json.gz")
    legacy_path = os.path.join(HERE, "prev_snapshot.json")

    prev_snapshot = None
    if os.path.exists(snap_path):
        with gzip.open(snap_path, "rt", encoding="utf-8") as f:
            prev_snapshot = json.load(f)
    elif os.path.exists(legacy_path):
        with open(legacy_path, encoding="utf-8") as f:
            prev_snapshot = json.load(f)

    print(f"[2/4] 스냅샷 비교", file=sys.stderr)
    if prev_snapshot is None:
        new_keys: set[str] = set()
        first_run = True
        print("      이전 스냅샷 없음 → 오늘은 기준선만 저장(신규 0건)", file=sys.stderr)
    else:
        first_run = False
        new_keys = today_keys - set(prev_snapshot["keys"])
        print(f"      신규 {len(new_keys):,}건", file=sys.stderr)

    new_rows = [r for r in window if record_key(r) in new_keys]

    print(f"[3/4] 분석", file=sys.stderr)
    result = analyse(new_rows, rows, cfg, today)

    meta = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "report_date": today.isoformat(),
        "prev_report_date": (prev_snapshot or {}).get("meta", {}).get("report_date"),
        "total_records": len(rows),
        "window_records": len(window),
        "new_records": len(new_rows),
        "first_run": first_run,
        "regions": len(cfg["regions"]),
        "history_months": cfg["history_months"],
    }

    out = {
        "meta": meta,
        "result": result,
        "snapshot_blob": pack_snapshot(today_keys, {"report_date": today.isoformat()}),
    }
    with open(os.path.join(HERE, "report_data.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    with gzip.open(snap_path, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump({"meta": {"report_date": today.isoformat()},
                   "keys": sorted(today_keys)}, f, ensure_ascii=False)
    if os.path.exists(legacy_path):
        os.remove(legacy_path)      # 압축본으로 승격되었으므로 중복 제거

    size_kb = os.path.getsize(snap_path) / 1024
    print(f"[4/4] 완료 → report_data.json (신규 {len(new_rows)}건, "
          f"스냅샷 {len(today_keys):,}키 / {size_kb:,.0f}KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
