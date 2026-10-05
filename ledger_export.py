"""원장 보관함(ledger/) + 동·평형별 월 통계(stats/) — 2026-10-05 추가

예약 작업·일회성 작업이 PlayMCP AptInfo(시군구·월당 10건만 돌려줌) 대신
국토부 원장 전수를 쓰도록, 시군구 × 계약월 단위로 거래 전부를 파일로 남긴다.

산출물 (모두 GitHub Pages로 공개 — https://nayoungsun.github.io/rtms-briefing/...)
- ledger/index.json                 : 보관 중인 시군구·월 목록과 건수 (먼저 이것을 본다)
- ledger/<시군구코드>/<YYYYMM>.json  : 그 달의 거래 전부(해제 포함, 해제 표시)
- stats/<시군구코드>_<band>.json     : 시군구 전체 + 법정동별 월 통계(최근 12개월, 해제 제외)
                                      band = all · a59(57~62㎡) · a84(82~87㎡) · a114(110~120㎡)
모든 파일에 check(검산값)가 있다. WebFetch로 받은 뒤 같은 값을 다시 계산해 대조한다.

데이터 출처
- 브리핑 대상 37개 시군구의 최근 diff_months(3개월): rtms.py 스냅샷(원장 전수) — API 호출 없음
- 그보다 오래된 달과 config.ledger.extra_regions(브리핑 밖 지역): 국토부 API
  · 한 번 받은 '지난 달'은 다시 받지 않는다(보관함에 있으면 건너뜀)
  · extra 지역의 최근 3개월은 extra_refresh_days 마다 다시 받는다(신고 30일·해제 반영)
  · 한 번 실행에 API는 api_budget 회까지만 — 첫 보충은 며칠에 나눠 채워진다
이 스크립트가 실패해도 브리핑에는 영향이 없다(워크플로에서 continue-on-error).
"""
from __future__ import annotations

import gzip
import json
import os
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger")
STATS = os.path.join(HERE, "stats")
PY = 3.305785
BANDS = {"all": (0.0, 9999.0), "a59": (57.0, 62.0), "a84": (82.0, 87.0), "a114": (110.0, 120.0)}
ROW_FIELDS = ["법정동", "단지", "전용㎡", "층", "계약일", "금액(만원)", "해제(1)", "건축년도", "직거래(1)"]


def months_back(n: int, today: date) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jdump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def month_check(rows: list) -> dict:
    return {"n": len(rows), "sum_amount": sum(r[5] for r in rows),
            "n_cancel": sum(1 for r in rows if r[6])}


def rows_from_snapshot(snap: dict, codes: set) -> dict:
    """{(code, YYYYMM): [row, ...]} — 스냅샷 키에는 건축년도·직거래 정보가 없다(None)."""
    got: dict[tuple, list] = {}
    for key in snap.get("keys", []):
        p = key.split("|")
        if len(p) < 8 or p[0] not in codes:
            continue
        sgg, umd, cancel = p[0], p[1], p[-1]
        apt = "|".join(p[2:-5])
        area, floor, dd, amt = p[-5], p[-4], p[-3], p[-2]
        try:
            row = [umd, apt, float(area), floor, dd[8:10], int(str(amt).replace(",", "")),
                   1 if cancel.strip() else 0, None, None]
        except ValueError:
            continue
        got.setdefault((sgg, dd[:4] + dd[5:7]), []).append(row)
    return got


def rows_from_api(api_rows: list) -> list:
    out = []
    for r in api_rows:
        try:
            area = float(r["excluUseAr"])
        except (TypeError, ValueError):
            continue
        by = r.get("buildYear") or ""
        out.append([r["umdNm"], r["aptNm"], area, r["floor"], f'{int(r["dealDay"]):02d}',
                    int(r["dealAmount"]), 1 if r.get("cdealType") else 0,
                    int(by) if str(by).isdigit() else None,
                    1 if (r.get("dealingGbn") or "").strip() == "직거래" else 0])
    return out


def write_month(code: str, ym: str, rows: list, src: str, as_of: str) -> None:
    rows = sorted(rows, key=lambda r: (r[0], r[1], r[4], r[5]))
    jdump(os.path.join(LEDGER, code, f"{ym}.json"), {
        "lawd": code, "ym": ym, "as_of": as_of, "src": src, "unit": "만원",
        "fields": ROW_FIELDS, "rows": rows, "check": month_check(rows)})


def fill_build_year(code: str, months: list[str]) -> None:
    """스냅샷 달 행의 건축년도 빈칸을 같은 단지의 API 달 값으로 채운다."""
    by: dict[tuple, int] = {}
    docs = {}
    for ym in months:
        d = jload(os.path.join(LEDGER, code, f"{ym}.json"))
        if not d:
            continue
        docs[ym] = d
        for r in d["rows"]:
            if r[7]:
                by[(r[0], r[1])] = r[7]
    for ym, d in docs.items():
        changed = False
        for r in d["rows"]:
            if r[7] is None and (r[0], r[1]) in by:
                r[7] = by[(r[0], r[1])]
                changed = True
        if changed:
            jdump(os.path.join(LEDGER, code, f"{ym}.json"), d)


def stat_row(ym: str, deals: list) -> list:
    amts = [a for a, _ in deals]
    pys = [p for _, p in deals]
    return [f"{ym[:4]}-{ym[4:]}", len(amts), round(statistics.median(amts)),
            round(sum(amts) / len(amts)), round(sum(pys) / len(pys)), max(amts)]


def build_stats(code: str, name: str, months: list[str], as_of: str) -> dict:
    """band별 {sgg: [[YYYY-MM, 건수, 중앙값, 평균, 평당가, 최고가]...], dong: {법정동: [...]}}"""
    out = {b: {"sgg": [], "dong": {}} for b in BANDS}
    for ym in sorted(months):
        d = jload(os.path.join(LEDGER, code, f"{ym}.json"))
        if not d:
            continue
        buckets: dict[tuple, list] = {}
        for r in d["rows"]:
            if r[6] or not r[2]:
                continue
            per_py = r[5] / (r[2] / PY)
            for b, (lo, hi) in BANDS.items():
                if lo <= r[2] < hi:
                    buckets.setdefault((b, None), []).append((r[5], per_py))
                    buckets.setdefault((b, r[0]), []).append((r[5], per_py))
        for (b, umd), deals in buckets.items():
            row = stat_row(ym, deals)
            if umd is None:
                out[b]["sgg"].append(row)
            else:
                out[b]["dong"].setdefault(umd, []).append(row)
    for b in BANDS:
        rows = out[b]["sgg"] + [r for v in out[b]["dong"].values() for r in v]
        doc = {"lawd": code, "name": name, "band": b, "band_area": list(BANDS[b]), "as_of": as_of,
               "unit": "만원", "fields": ["월", "건수", "중앙값", "평균", "평당가(전용)", "최고가"],
               "note": "국토부 원장 전수 · 계약해제 제외 · 최근 월은 신고기한(30일) 전이라 늘 수 있음",
               "sgg": out[b]["sgg"], "dong": dict(sorted(out[b]["dong"].items())),
               "check": {"rows": len(rows), "sum_n": sum(r[1] for r in rows),
                         "sum_median": sum(r[2] for r in rows), "sum_max": sum(r[5] for r in rows)}}
        jdump(os.path.join(STATS, f"{code}_{b}.json"), doc)
    return out


def main() -> None:
    cfg = jload(os.path.join(HERE, "config.json"), {})
    lcfg = cfg.get("ledger") or {}
    keep = int(lcfg.get("keep_months", 12))
    budget = int(lcfg.get("api_budget", 120))
    refresh_days = int(lcfg.get("extra_refresh_days", 2))
    time_limit = float(lcfg.get("time_limit_sec", 600))
    diff_n = int(cfg.get("diff_months", 3))

    snap_path = os.path.join(HERE, "prev_snapshot.json.gz")
    with gzip.open(snap_path, "rt", encoding="utf-8") as f:
        snap = json.load(f)
    as_of = (snap.get("meta") or {}).get("report_date") or datetime.now(KST).date().isoformat()
    today = date.fromisoformat(as_of)
    keep_months = months_back(keep, today)                 # 최신 → 과거
    recent = set(months_back(diff_n, today))

    core = [dict(r, kind="core") for r in cfg.get("regions", [])]
    extra = [dict(r, kind="extra") for r in lcfg.get("extra_regions", [])]
    regions = {r["code"]: r for r in core + extra}

    # 1) 브리핑 지역의 최근 달 — 스냅샷에서 매일 덮어쓰기
    snap_rows = rows_from_snapshot(snap, {r["code"] for r in core})
    for r in core:
        for ym in recent:
            write_month(r["code"], ym, snap_rows.get((r["code"], ym), []), "snapshot", as_of)

    # 2) API가 필요한 (지역, 달) 목록 — 최근 달 갱신(extra) 먼저, 그다음 빠진 달(최신부터)
    old_index = jload(os.path.join(LEDGER, "index.json"), {}) or {}
    fetched_at = old_index.get("fetched_at") or {}
    need: list[tuple] = []
    for r in extra:
        for ym in sorted(recent, reverse=True):
            last = fetched_at.get(f'{r["code"]}/{ym}')
            stale = (not last) or (today - date.fromisoformat(last)).days >= refresh_days
            if stale:
                need.append((r["code"], ym))
    for ym in keep_months:
        for r in core + extra:
            if r["kind"] == "core" and ym in recent:
                continue
            if (r["code"], ym) in need:
                continue
            if not os.path.exists(os.path.join(LEDGER, r["code"], f"{ym}.json")):
                need.append((r["code"], ym))

    key = os.environ.get("MOLIT_SERVICE_KEY", "").strip()
    done, failed, skipped = [], [], max(0, len(need) - budget)
    if key and need:
        sys.path.insert(0, HERE)
        import rtms  # noqa: E402
        t0 = time.monotonic()
        for code, ym in need[:budget]:
            if time.monotonic() - t0 > time_limit:
                skipped += 1
                continue
            try:
                api_rows = rtms.fetch_month(key, code, ym, retries=4)
            except Exception as exc:
                failed.append(f"{code}/{ym}: {exc}")
                continue
            write_month(code, ym, rows_from_api(api_rows), "api", as_of)
            fetched_at[f"{code}/{ym}"] = as_of
            done.append(f"{code}/{ym}")
    elif need:
        skipped = len(need)

    # 3) 12개월 밖 파일 정리 · 건축년도 보충 · 통계 · 색인
    index_regions = {}
    for code, r in regions.items():
        d = os.path.join(LEDGER, code)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith(".json") and fn[:6] not in keep_months:
                    os.remove(os.path.join(d, fn))
        have = sorted(ym for ym in keep_months if os.path.exists(os.path.join(d, f"{ym}.json")))
        fill_build_year(code, have)
        name = r["sgg"] if (r.get("sido") == "서울" or r["sgg"].endswith("시")) else f'{r.get("sido", "")} {r["sgg"]}'.strip()
        build_stats(code, name, have, as_of)
        counts = {}
        for ym in have:
            doc = jload(os.path.join(d, f"{ym}.json"), {})
            counts[f"{ym[:4]}-{ym[4:]}"] = (doc.get("check") or {}).get("n", 0)
        index_regions[code] = {"name": name, "kind": r["kind"], "months": counts,
                               "missing": [f"{m[:4]}-{m[4:]}" for m in keep_months if m not in have],
                               "warn": ("최근 3개월 거래 0건 — 시군구 코드 확인 필요"
                                        if have and sum(counts.get(f"{m[:4]}-{m[4:]}", 0) for m in recent) == 0
                                        else None)}
    fetched_at = {k: v for k, v in fetched_at.items() if k.split("/")[-1] in keep_months}
    jdump(os.path.join(LEDGER, "index.json"), {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"), "as_of": as_of,
        "base": "https://nayoungsun.github.io/rtms-briefing/",
        "how": "ledger/<코드>/<YYYYMM>.json = 그 달 거래 전부 · stats/<코드>_<all|a59|a84|a114>.json = 시군구·법정동 월 통계",
        "keep_months": keep, "regions": index_regions, "fetched_at": fetched_at,
        "last_run": {"api_done": len(done), "api_failed": failed[:10], "api_pending": skipped},
        "check": {"regions": len(index_regions),
                  "month_files": sum(len(v["months"]) for v in index_regions.values()),
                  "sum_n": sum(sum(v["months"].values()) for v in index_regions.values())}})
    print(f"[원장 보관함] 지역 {len(index_regions)} · API {len(done)}회 성공 · 실패 {len(failed)} · "
          f"남은 보충 {skipped}", file=sys.stderr)


if __name__ == "__main__":
    main()
