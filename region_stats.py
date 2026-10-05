"""ledger/ (원장 보관함) -> regions.json · regions_<band>.json (실거래 흐름판용 시군구·월별 통계)

2026-10-05 개정: 스냅샷(최근 3개월)만 보던 방식을 원장 보관함 ledger/<코드>/<YYYYMM>.json 전체
(최대 12개월)로 바꿨다. 그래서 흐름판의 3·6개월 창과 급지 분류(최근 6개 완결월)가 바로 계산된다.
ledger_export.py 다음에 실행해야 한다(ledger/ 가 먼저 갱신돼야 하므로).
ledger/ 가 아직 없으면 예전처럼 스냅샷으로 계산한다.

- 계약해제 행 제외(원장 해제 표시 기준). 금액 단위 만원, 평당가는 전용면적 기준.
- 부분월(행 마지막 칸 1): 신고기한(계약 후 30일)이 아직 안 끝난 달 = 그 달 말일 + 30일이 as_of 이후인 달.
  latest_complete = 부분월이 아닌 가장 최근 달. (예: as_of 10-05 → 9월·10월 부분월, 완결월 8월)
- 2026-10-06 추가: regions_rs.json — 시군구×평형과 후보·목적지 동 묶음의 '같은 단지 지수'(반복거래) 월 변화율.
이 스크립트가 실패해도 브리핑에는 영향이 없다.
"""
from __future__ import annotations

import gzip
import json
import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

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


def band_check(doc: dict) -> dict:
    """검산값: 지역 수·행 수·거래건수 합·평균가 합·최고가 합."""
    regions_with_data = rows = sum_count = sum_avg = sum_max = 0
    for r in doc["regions"].values():
        if r["m"]:
            regions_with_data += 1
        for row in r["m"]:
            rows += 1
            sum_avg += row[1]
            sum_count += row[4]
            sum_max += row[5]
    return {"regions": len(doc["regions"]), "regions_with_data": regions_with_data,
            "rows": rows, "sum_count": sum_count, "sum_avg": sum_avg, "sum_max": sum_max}


def main() -> None:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with gzip.open(os.path.join(HERE, "prev_snapshot.json.gz"), "rt", encoding="utf-8") as f:
        snap = json.load(f)

    today = datetime.now(KST).date()
    as_of = (snap.get("meta") or {}).get("report_date") or today.isoformat()
    as_of_d = date.fromisoformat(as_of)

    def is_partial(ym: str) -> bool:
        y, m = int(ym[:4]), int(ym[5:7])
        last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        return last + timedelta(days=30) >= as_of_d

    regions = {r["code"]: r for r in cfg["regions"]}
    # bucket[(band, code, ym)] = [(amount, per_py), ...]
    bucket: dict[tuple, list] = {}
    n_ok = 0

    def add(code: str, ym: str, area: float, amount: int) -> None:
        nonlocal n_ok
        if area <= 0:
            return
        n_ok += 1
        per_py = amount / (area / PY)
        for b, spec in BANDS.items():
            if spec["lo"] <= area < spec["hi"]:
                bucket.setdefault((b, code, ym), []).append((amount, per_py))

    ledger_dir = os.path.join(HERE, "ledger")
    source = "국토부 아파트 매매 실거래 원장 — ledger/ 원장 보관함(계약해제 제외)"
    if os.path.isdir(ledger_dir):
        for code in regions:
            d = os.path.join(ledger_dir, code)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        doc = json.load(f)
                except Exception:
                    continue
                ym = f"{fn[:4]}-{fn[4:6]}"
                for r in doc.get("rows", []):
                    if r[6] or not r[2]:
                        continue
                    add(code, ym, float(r[2]), int(r[5]))
    else:
        source = "국토부 아파트 매매 실거래 원장(rtms.py 스냅샷, 계약해제 제외)"
        for key in snap.get("keys", []):
            rec = parse_key(key)
            if not rec or rec["cancel"] or rec["sgg"] not in regions:
                continue
            add(rec["sgg"], rec["ym"], rec["area"], rec["amount"])

    fresh_months = sorted({k[2] for k in bucket})
    done = [ym for ym in fresh_months if not is_partial(ym)]
    latest_complete = done[-1] if done else None

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
                            1 if is_partial(ym) else 0]
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
           "source": source,
           "records_used": n_ok, "fresh_months": fresh_months, "bands": out_bands}
    with open(prev_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # 2026-10-04 추가: 밴드별 작은 파일 + 검산값(check).
    # 예약 작업은 curl 대신 WebFetch로 이 파일을 받고, 받은 숫자로 check를 다시 계산해
    # 일치할 때만 흐름판에 쓴다(숫자가 요약·변형되면 불일치로 걸러진다).
    for b, doc in out_bands.items():
        doc = dict(doc)
        doc["check"] = band_check(doc)
        with open(os.path.join(HERE, f"regions_{b}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[지역 통계] regions.json 저장 — 거래 {n_ok:,}건, 월 {fresh_months}", file=sys.stderr)
    try:
        build_rs(cfg, regions, as_of, is_partial)
    except Exception as exc:  # 같은 단지 지수 실패는 지역 통계에 영향 없음
        print(f"[같은 단지 지수] 실패: {exc}", file=sys.stderr)


# ---- 2026-10-06 추가: 같은 단지 지수(반복거래 지수) ------------------------------------
# 두 달 연속 거래된 '같은 단지·같은 평형(전용㎡ 정수부)' 셀의 월 중앙값 변화율(로그)을 구해,
# 두 달 거래 수 중 작은 값을 가중치로 한 가중 중앙값을 그 달의 변화율로 쓴다.
# 평당가 평균과 달리 '어떤 집이 팔렸나(구성)'의 영향을 덜 받는다. 해제 행 제외.
RS_GROUPS_DEFAULT = [
    {"id": "hwanghak_sindang", "label": "황학·신당(중구)", "lawd": "11140", "umd": ["황학동", "신당동"]},
    {"id": "wangsimni", "label": "왕십리·행당·마장(성동)", "lawd": "11200", "umd": ["하왕십리동", "상왕십리동", "행당동", "마장동", "도선동", "홍익동"]},
    {"id": "jeonnong", "label": "전농·답십리·휘경·이문(동대문)", "lawd": "11230", "umd": ["전농동", "답십리동", "휘경동", "이문동"]},
    {"id": "gireum", "label": "길음·보문·종암(성북)", "lawd": "11290", "umd": ["길음동", "보문동1가", "보문동3가", "종암동", "돈암동", "안암동3가"]},
    {"id": "jangwi", "label": "장위·석관(성북)", "lawd": "11290", "umd": ["장위동", "석관동"]},
    {"id": "junggye", "label": "중계·하계(노원)", "lawd": "11350", "umd": ["중계동", "하계동"]},
    {"id": "cheolsan", "label": "철산·하안(광명)", "lawd": "41210", "umd": ["철산동", "하안동"]},
    {"id": "suji", "label": "풍덕천·동천(수지)", "lawd": "41465", "umd": ["풍덕천동", "동천동"]},
    {"id": "gwanggyo", "label": "광교 이의·하동(영통)", "lawd": "41117", "umd": ["이의동", "하동"]},
    {"id": "dest_geumho", "label": "[목적지] 금호·옥수(성동)", "lawd": "11200", "umd": ["금호동1가", "금호동2가", "금호동3가", "금호동4가", "옥수동"]},
    {"id": "dest_gongdeok", "label": "[목적지] 공덕·아현(마포)", "lawd": "11440", "umd": ["공덕동", "신공덕동", "아현동", "염리동", "대흥동"]},
    {"id": "dest_heukseok", "label": "[목적지] 흑석·상도(동작)", "lawd": "11590", "umd": ["흑석동", "상도동", "본동"]},
    {"id": "dest_godeok", "label": "[목적지] 고덕·상일(강동)", "lawd": "11740", "umd": ["고덕동", "상일동", "강일동"]},
    {"id": "dest_jamsil", "label": "[목적지] 잠실·신천(송파)", "lawd": "11710", "umd": ["잠실동", "신천동"]},
    {"id": "dest_daechi", "label": "[목적지] 대치·도곡·역삼(강남)", "lawd": "11680", "umd": ["대치동", "도곡동", "역삼동"]},
]


def _rs_links(cells_by_month: dict, months: list) -> list:
    """[[월, 전월 대비 %, 비교 셀 수], ...] — 셀이 5개 미만이면 %는 None"""
    import math
    out = []
    for a, b in zip(months, months[1:]):
        ca, cb = cells_by_month.get(a, {}), cells_by_month.get(b, {})
        common = [k for k in ca if k in cb]
        if len(common) < 5:
            out.append([b, None, len(common)])
            continue
        pairs = sorted((math.log(statistics.median(cb[k]) / statistics.median(ca[k])),
                        min(len(ca[k]), len(cb[k]))) for k in common)
        tot = sum(w for _, w in pairs)
        acc, med = 0, 0.0
        for x, w in pairs:
            acc += w
            if acc >= tot / 2:
                med = x
                break
        out.append([b, round((math.exp(med) - 1) * 100, 2), len(common)])
    return out


def build_rs(cfg: dict, regions: dict, as_of: str, is_partial) -> None:
    ledger_dir = os.path.join(HERE, "ledger")
    if not os.path.isdir(ledger_dir):
        return
    groups = cfg.get("rs_groups") or RS_GROUPS_DEFAULT
    # cells[(scope, band)][ym][(code, dong, apt, int area)] = [amount...]
    cells: dict = {}
    months: set = set()

    def put(scope, b, ym, key, amt):
        cells.setdefault((scope, b), {}).setdefault(ym, {}).setdefault(key, []).append(amt)

    for code in regions:
        d = os.path.join(ledger_dir, code)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    doc = json.load(f)
            except Exception:
                continue
            ym = f"{fn[:4]}-{fn[4:6]}"
            months.add(ym)
            for r in doc.get("rows", []):
                if r[6] or not r[2]:
                    continue
                area = float(r[2])
                key = (code, r[0], r[1], int(area))
                for b, spec in BANDS.items():
                    if spec["lo"] <= area < spec["hi"]:
                        put(("sgg", code), b, ym, key, int(r[5]))
                for g in groups:
                    if g["lawd"] == code and r[0] in g["umd"]:
                        put(("grp", g["id"]), "all", ym, key, int(r[5]))
    ms = sorted(months)
    out_sgg, out_grp = {}, {}
    rows = sum_n = 0
    for code, r in regions.items():
        name = short_name(r)
        out_sgg[name] = {}
        for b in BANDS:
            links = _rs_links(cells.get((("sgg", code), b), {}), ms)
            out_sgg[name][b] = links
            rows += len(links)
            sum_n += sum(x[2] for x in links)
    for g in groups:
        links = _rs_links(cells.get((("grp", g["id"]), "all"), {}), ms)
        out_grp[g["id"]] = {"label": g["label"], "lawd": g["lawd"], "umd": g["umd"], "links": links}
        rows += len(links)
        sum_n += sum(x[2] for x in links)
    doc = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"), "as_of": as_of,
           "months": ms, "partial": [m for m in ms if is_partial(m)],
           "method": "같은 단지·같은 평형(전용㎡ 정수부) 셀의 월 중앙값 로그 변화율을 두 달 거래 수 중 작은 값으로 가중한 중앙값 · 셀 5개 미만은 None · 해제 제외",
           "fields": ["월", "전월 대비 %", "비교 셀 수"], "sgg": out_sgg, "groups": out_grp,
           "check": {"rows": rows, "sum_n": sum_n}}
    with open(os.path.join(HERE, "regions_rs.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[같은 단지 지수] regions_rs.json 저장 — 링크 {rows}개", file=sys.stderr)


if __name__ == "__main__":
    main()
