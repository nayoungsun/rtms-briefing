"""prev_snapshot.json.gz (+ 1회 과거분 보충) -> watch.json (고정 관심 단지 체결 장부)

예약 작업이 AptInfo(시군구·월당 10건만 돌려주는 MCP) 대신 쓰도록,
config.json 의 watch_complexes 에 적힌 단지의 거래를 국토부 원장에서 빠짐없이 모은다.

- 최근 diff_months 개월: rtms.py 가 저장한 스냅샷(원장 전수)에서 매일 새로 뽑아 덮어쓴다.
  계약해제 표시(X)도 그대로 따라온다.
- 그보다 오래된 달: watch.json 에 이미 있으면 그대로 두고, 없으면(첫 실행 등)
  MOLIT_SERVICE_KEY 가 있을 때만 그 달을 한 번 API로 받아 채운다(단지 2곳 기준 최대 18회).
- 평형별로 6개월 체결 건수·마지막 체결·최고·최저·저층(1~3층)/고층(10층 이상) 평균을 계산한다.
- check: 예약 작업이 WebFetch 로 받은 숫자를 다시 계산해 대조하는 검산값.

이 스크립트가 실패해도 브리핑에는 영향이 없다(워크플로에서 continue-on-error).
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
KEEP_MONTHS = 12
WINDOW_DAYS = 183           # '최근 6개월' 통계 창
OUT = os.path.join(HERE, "watch.json")


def months_back(n: int, today: date) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def floor_band(floor) -> str | None:
    try:
        f = int(str(floor).strip())
    except ValueError:
        return None
    return "저층" if f <= 3 else ("중층" if f <= 9 else "고층")


def matches(w: dict, sgg: str, umd: str, apt: str) -> bool:
    return sgg == w["lawd"] and umd == w["umd"] and apt.strip() in w["apt_names"]


def from_snapshot(snap: dict, watch: list[dict]) -> tuple[dict, set]:
    """{(id, ym): [trade, ...]}, 스냅샷이 덮는 달 집합"""
    got: dict[tuple, list] = {}
    months: set[str] = set()
    for key in snap.get("keys", []):
        p = key.split("|")
        if len(p) < 8:
            continue
        sgg, umd, apt, area, floor, dd, amt, cancel = p[0], p[1], p[2], p[-5], p[-4], p[-3], p[-2], p[-1]
        months.add(dd[:7])
        for w in watch:
            if matches(w, sgg, umd, apt):
                got.setdefault((w["id"], dd[:7]), []).append({
                    "date": dd, "area": area, "floor": floor,
                    "amount": int(str(amt).replace(",", "")),
                    "cancel": bool(cancel.strip()), "src": "snapshot"})
    return got, months


def backfill(watch: list[dict], need: list[tuple]) -> dict:
    """need = [(lawd, 'YYYY-MM'), ...] → {(id, ym): [trade...]}. 키가 없으면 빈 dict."""
    key = os.environ.get("MOLIT_SERVICE_KEY", "").strip()
    if not key or not need:
        return {}
    sys.path.insert(0, HERE)
    import rtms  # noqa: E402
    got: dict[tuple, list] = {}
    for lawd, ym in need:
        try:
            rows = rtms.fetch_month(key, lawd, ym.replace("-", ""), retries=5)
        except Exception as exc:   # 한 달 실패는 다음 실행에 다시 시도
            print(f"[관심 단지] {lawd}/{ym} 보충 실패: {exc}", file=sys.stderr)
            continue
        for w in watch:
            if w["lawd"] != lawd:
                continue
            got[(w["id"], ym)] = [{
                "date": rtms.deal_date(r), "area": r["excluUseAr"], "floor": r["floor"],
                "amount": int(r["dealAmount"]), "cancel": bool(r.get("cdealType")),
                "dealing": r.get("dealingGbn") or None, "src": "api"}
                for r in rows if matches(w, r.get("sggCd") or lawd, r["umdNm"], r["aptNm"])]
    return got


def area_stats(trades: list[dict], as_of: date) -> dict:
    lo = (as_of - timedelta(days=WINDOW_DAYS)).isoformat()
    by_area: dict[str, list] = {}
    for t in trades:
        by_area.setdefault(t["area"], []).append(t)
    out = {}
    for area, ts in sorted(by_area.items(), key=lambda kv: float(kv[0] or 0)):
        ok = sorted([t for t in ts if not t["cancel"]], key=lambda t: (t["date"], t["amount"]))
        win = [t for t in ok if t["date"] >= lo]
        last = ok[-1] if ok else None
        low = [t["amount"] for t in win if floor_band(t["floor"]) == "저층"]
        high = [t["amount"] for t in win if floor_band(t["floor"]) == "고층"]
        low_avg = round(sum(low) / len(low)) if low else None
        high_avg = round(sum(high) / len(high)) if high else None
        gap = (round((high_avg / low_avg - 1) * 100, 1)
               if (low_avg and high_avg and len(win) >= 2) else None)
        out[area] = {
            "n_all": len(ok), "n_cancel": len(ts) - len(ok), "n_6m": len(win),
            "last": ({"date": last["date"], "floor": last["floor"], "amount": last["amount"],
                      "days_ago": (as_of - date.fromisoformat(last["date"])).days} if last else None),
            "max_6m": max((t["amount"] for t in win), default=None),
            "min_6m": min((t["amount"] for t in win), default=None),
            "low_n": len(low), "low_avg": low_avg, "high_n": len(high), "high_avg": high_avg,
            "high_vs_low_pct": gap,
        }
    return out


def main() -> None:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    watch = cfg.get("watch_complexes") or []
    if not watch:
        print("[관심 단지] config.watch_complexes 없음 — 건너뜀", file=sys.stderr)
        return
    with gzip.open(os.path.join(HERE, "prev_snapshot.json.gz"), "rt", encoding="utf-8") as f:
        snap = json.load(f)

    as_of_s = (snap.get("meta") or {}).get("report_date") or datetime.now(KST).date().isoformat()
    as_of = date.fromisoformat(as_of_s)
    keep = months_back(KEEP_MONTHS, as_of)          # 최신 → 과거

    prev = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}

    snap_got, snap_months = from_snapshot(snap, watch)
    # 스냅샷 창(diff_months)에 드는 달은 거래가 0건이어도 '스냅샷이 덮는 달'로 본다
    snap_months |= set(months_back(int(cfg.get("diff_months", 3)), as_of))

    # 달별 저장소: {id: {ym: [trades]}} — 스냅샷 달은 매일 덮어쓰고, 나머지는 이전 값을 유지
    store: dict[str, dict] = {}
    for w in watch:
        old = (((prev.get("complexes") or {}).get(w["id"]) or {}).get("months") or {})
        store[w["id"]] = {ym: v for ym, v in old.items() if ym in keep and ym not in snap_months}
        for ym in snap_months:
            if ym in keep:
                store[w["id"]][ym] = snap_got.get((w["id"], ym), [])

    need = sorted({(w["lawd"], ym) for w in watch for ym in keep
                   if ym not in store[w["id"]]})
    for (wid, ym), trades in backfill(watch, need).items():
        store[wid][ym] = trades

    complexes = {}
    chk_n = chk_sum = chk_months = 0
    for w in watch:
        months = {ym: store[w["id"]][ym] for ym in sorted(store[w["id"]])}
        trades = sorted((t for ts in months.values() for t in ts),
                        key=lambda t: (t["date"], t["amount"]), reverse=True)
        missing = [ym for ym in keep if ym not in months]
        complexes[w["id"]] = {
            "label": w["label"], "lawd": w["lawd"], "umd": w["umd"], "apt_names": w["apt_names"],
            "note": w.get("note"),
            "months_covered": sorted(months), "months_missing": sorted(missing),
            "by_area": area_stats(trades, as_of),
            "trades": trades,
            "months": months,
        }
        chk_n += len(trades)
        chk_sum += sum(t["amount"] for t in trades)
        chk_months += len(months)

    out = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "as_of": as_of_s,
        "source": "국토부 아파트 매매 실거래 원장 — 최근 월은 rtms.py 스냅샷, 과거 월은 API 1회 보충",
        "window_days": WINDOW_DAYS,
        "floor_bands": "저층 1~3층 · 중층 4~9층 · 고층 10층 이상",
        "unit": "만원",
        "complexes": complexes,
        "check": {"complexes": len(complexes), "trades": chk_n,
                  "sum_amount": chk_sum, "months": chk_months},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[관심 단지] watch.json 저장 — 거래 {chk_n}건, 월 {chk_months}개 "
          f"(보충 요청 {len(need)}건)", file=sys.stderr)


if __name__ == "__main__":
    main()
