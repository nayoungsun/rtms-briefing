"""prev_snapshot.json.gz -> regions.json (실거래 흐름판용 시군구·월별 통계)

rtms.py 가 저장한 스냅샷(최근 diff_months 개월 전체 거래 키)을 읽어
시군구 x 월 x 평형대별로 평균가·중앙값·평당가·거래건수·최고가를 계산한다.
지난 실행의 regions.json 에 있던 더 오래된 달은 그대로 이어 붙여(최대 12개월)
시간이 지날수록 기간이 길어진다. 이 스크립트가 실패해도 브리핑에는 영향이 없다.
"""
from __future__ import annotations

import gzip
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
PY = 3.305785  # 1평 = 3.305785㎡
KEEP_MONTHS = 12

BANDS = {
    "all":  {"label": "전체 평형", "lo": 0.0, "hi": 9999.0,
             "cell": "전 평형 · 평당가는 전용면적 기준 · 국토부 원장 전수(해제 제외)"},
    "a59":  {"label": "전용 59㎡", "lo": 57.0, "hi": 62.0,
             "cell": "전용 57~62㎡ · 국토부 원장 전수(해제 제외)"},
    "a84":  {"label": "전용 84㎡", "lo": 82.0, "hi": 87.0,
             "cell": "전용 82~87㎡ · 국토부 원장 전수(해제 제외)"},
    "a114": {"label": "전용 114㎡", "lo": 110.0, "hi": 120.0,
             "cell": "전용 110~120㎡ · 국토부 원장 전수(해제 제외)"},
}


def short_name(region: dict) -> str:
    sido, sgg = region["sido"], region["sgg"]
    if sido == "서울" or sgg.endswith("시"):
        return sgg
    return f"{sido} {sgg}"


def parse_key(key: str):
    # sggCd|umdNm|aptNm|excluUseAr|floor|YYYY-MM-DD|dealAmount|X?
    p = key.split("|")
    if len(p) < 8:
        return None
    sgg, cancel = p[0], p[-1]
    try:
        area = float(p[-5])
        amount = int(str(p[-2]).replace(",", ""))
    except ValueError:
        return None
    ym = p[-3][:7]
    if len(ym) != 7:
        return None
    return {"sgg": sgg, "area": area, "ym": ym, "amount": amount, "cancel": bool(cancel.strip())}


def main() -> None:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with gzip.open(os.path.join(HERE, "prev_snapshot.json.gz"), "rt", encoding="utf-8") as f:
        snap = json.load(f)

    today = datetime.now(KST).date()
    as_of = (snap.get("meta") or {}).get("report_date") or today.isoformat()
    cur_ym = as_of[:7]
    y, m = int(cur_ym[:4]), int(cur_ym[5:7])
    latest_complete = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"

    regions = {r["code"]: r for r in cfg["regions"]}
    # bucket[(band, code, ym)] = [(amount, per_py), ...]
    bucket: dict[tuple, list] = {}
    n_ok = 0
    for key in snap.get("keys", []):
        rec = parse_key(key)
        if not rec or rec["cancel"] or rec["sgg"] not in regions or rec["area"] <= 0:
            continue
        n_ok += 1
        per_py = rec["amount"] / (rec["area"] / PY)
        for b, spec in BANDS.items():
            if spec["lo"] <= rec["area"] < spec["hi"]:
                bucket.setdefault((b, rec["sgg"], rec["ym"]), []).append((rec["amount"], per_py))

    fresh_months = sorted({k[2] for k in bucket})

    prev_path = os.path.join(HERE, "regions.json")
    prev = {}
    if os.path.exists(prev_path):
        try:
            with open(prev_path, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}

    out_bands = {}
    for b, spec in BANDS.items():
        out_regions = {}
        for code, r in regions.items():
            name = short_name(r)
            rows = {}
            for ym in fresh_months:
                deals = bucket.get((b, code, ym))
                if not deals:
                    continue
                amts = [a for a, _ in deals]
                pys = [p for _, p in deals]
                rows[ym] = [ym, round(sum(amts) / len(amts)), round(statistics.median(amts)),
                            round(sum(pys) / len(pys)), len(amts), max(amts),
                            1 if ym == cur_ym else 0]
            # 지난 파일에서 이번 창보다 오래된 달만 이어 붙인다
            old = (((prev.get("bands") or {}).get(b) or {}).get("regions") or {}).get(name) or {}
            for row in old.get("m", []):
                if fresh_months and row[0] < fresh_months[0] and row[0] not in rows:
                    row = list(row)
                    row[6] = 0
                    rows[row[0]] = row
            m_list = [rows[k] for k in sorted(rows)][-KEEP_MONTHS:]
            out_regions[name] = {"city": r["sido"], "error": None if m_list else "거래 없음",
                                 "chg": None, "m": m_list}
        out_bands[b] = {"band": b, "as_of": as_of, "latest_complete": latest_complete,
                        "band_meta": {"label": spec["label"], "cell": spec["cell"], "ok": True},
                        "regions": out_regions}

    out = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"),
           "as_of": as_of, "latest_complete": latest_complete,
           "source": "국토부 아파트 매매 실거래 원장(rtms.py 스냅샷, 계약해제 제외)",
           "records_used": n_ok, "fresh_months": fresh_months, "bands": out_bands}
    with open(prev_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[지역 통계] regions.json 저장 — 거래 {n_ok:,}건, 월 {fresh_months}", file=sys.stderr)


if __name__ == "__main__":
    main()
