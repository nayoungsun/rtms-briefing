"""ledger/ -> focus_<group>.json (매수 지도 등 '관심 후보 단지' 체결 장부) — 2026-10-05 추가

config.json 의 focus_complexes 에 적힌 단지의 거래를 원장 보관함(ledger/<코드>/<YYYYMM>.json)에서
모아, 예약 작업이 WebFetch 한두 번으로 받을 수 있는 작은 파일로 만든다.
(시군구 원장을 통째로 받으면 매주 30회 넘게, 파일당 최대 47KB를 받아야 해서 무겁다.)

- 그룹(group)마다 파일 하나: focus_maesu.json 등
- 단지마다: 보관 달 / 없는 달, 평형(정수 ㎡)별 최근 4개 계약월(이번 달 포함)·보관 전체 건수, 4개월 중앙값·최고·최저,
  마지막 체결, 그리고 최근 4개 계약월 거래 행(해제 표시 포함)
- '해제 짝': 면적·층·계약일·금액이 같은 정상 행과 해제 행이 함께 있는 경우. 원장만으로는
  '해제된 계약'인지 '해제 후 같은 조건으로 정정 재신고된 유효 계약'인지 알 수 없다.
  행에는 해제짝=1 로 표시하고, 통계(median 등)는 보수적으로 짝 두 행을 모두 뺀 값과
  짝의 정상 행을 넣은 값(median_4m_incl_pair)을 둘 다 남긴다.
- check: 예약 작업이 받은 숫자로 다시 계산해 대조하는 검산값
ledger_export.py 다음에 실행한다. 실패해도 브리핑에는 영향 없음(워크플로에서 continue-on-error).
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger")
ROW = ["월", "전용㎡", "층", "계약일", "금액", "해제", "직거래", "해제짝"]


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def months_back(n: int, today: date) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def collect(c: dict, keep: list[str]) -> tuple[list, list, list]:
    rows, have, missing = [], [], []
    names = set(c["apt_names"])
    for ym in keep:
        d = jload(os.path.join(LEDGER, c["lawd"], f"{ym}.json"))
        if d is None:
            missing.append(f"{ym[:4]}-{ym[4:]}")
            continue
        have.append(f"{ym[:4]}-{ym[4:]}")
        for r in d["rows"]:
            if r[0] == c["umd"] and r[1] in names:
                rows.append([f"{ym[:4]}-{ym[4:]}", r[2], r[3], r[4], r[5],
                             int(r[6] or 0), int(r[8] or 0), 0])
    # 해제 짝 표시
    key = lambda x: (x[0], x[1], x[2], x[3], x[4])
    cancelled = {key(x) for x in rows if x[5]}
    for x in rows:
        if key(x) in cancelled:
            x[7] = 1
    rows.sort(key=lambda x: (x[0], x[3], x[4]), reverse=True)
    return rows, sorted(have), sorted(missing)


def area_stats(rows: list, recent3: set) -> dict:
    out: dict[str, dict] = {}
    for x in rows:
        out.setdefault(str(int(float(x[1]))), []).append(x)
    res = {}
    for a, xs in sorted(out.items(), key=lambda kv: int(kv[0])):
        ok = [x for x in xs if not x[7]]
        r3 = [x[4] for x in ok if x[0] in recent3]
        r3i = [x[4] for x in xs if not x[5] and x[0] in recent3]   # 짝의 정상 행 포함
        last = ok[0] if ok else None
        res[a] = {
            "n_12m": len(ok), "n_4m": len(r3), "n_cancel_pair": sum(1 for x in xs if x[7]),
            "median_4m": round(statistics.median(r3)) if r3 else None,
            "median_4m_incl_pair": round(statistics.median(r3i)) if r3i else None,
            "max_4m": max(r3) if r3 else None, "min_4m": min(r3) if r3 else None,
            "last": ({"date": f"{last[0]}-{last[3]}", "floor": last[2], "amount": last[4],
                      "area": last[1]} if last else None),
        }
    return res


BANDS = {"all": (0.0, 9999.0), "a59": (57.0, 62.0), "a84": (82.0, 87.0)}
PY = 3.305785


def dong_stats(c: dict, keep: list[str]) -> dict:
    """법정동(여러 개 가능) 묶음의 월별 통계. 해제 행 제외(stats/ 와 같은 기준) + 해제 짝 수 표시."""
    umds = set(c["umd"] if isinstance(c["umd"], list) else [c["umd"]])
    bands = {b: [] for b in BANDS}
    have, missing, pairs = [], [], 0
    for ym in sorted(keep):
        d = jload(os.path.join(LEDGER, c["lawd"], f"{ym}.json"))
        mm = f"{ym[:4]}-{ym[4:]}"
        if d is None:
            missing.append(mm)
            continue
        have.append(mm)
        rows = [r for r in d["rows"] if r[0] in umds and r[2]]
        canc = {(r[1], r[2], r[3], r[4], r[5]) for r in rows if r[6]}
        pairs += sum(1 for r in rows if not r[6] and (r[1], r[2], r[3], r[4], r[5]) in canc)
        for b, (lo, hi) in BANDS.items():
            amts = [(r[5], r[5] / (r[2] / PY)) for r in rows if not r[6] and lo <= r[2] < hi]
            if amts:
                a = [x for x, _ in amts]
                bands[b].append([mm, len(a), round(statistics.median(a)),
                                 round(sum(p for _, p in amts) / len(amts)), max(a)])
    return {"label": c["label"], "lawd": c["lawd"], "umd": sorted(umds), "note": c.get("note"),
            "months_covered": have, "months_missing": missing, "n_cancel_pair": pairs,
            "fields": ["월", "건수", "중앙값", "평당가(전용)", "최고가"], "bands": bands}


def main() -> None:
    cfg = jload(os.path.join(HERE, "config.json"), {})
    focus = cfg.get("focus_complexes") or []
    fdongs = cfg.get("focus_dongs") or []
    if not focus and not fdongs:
        print("[관심 후보] config.focus_complexes / focus_dongs 없음 — 건너뜀")
        return
    idx = jload(os.path.join(LEDGER, "index.json"), {}) or {}
    as_of = idx.get("as_of") or datetime.now(KST).date().isoformat()
    today = date.fromisoformat(as_of)
    keep = months_back(int((cfg.get("ledger") or {}).get("keep_months", 12)), today)
    recent3 = {f"{m[:4]}-{m[4:]}" for m in months_back(4, today)}  # 이번 달 포함 최근 4개 계약월

    groups: dict[str, list] = {}
    for c in focus:
        groups.setdefault(c.get("group", "main"), []).append(c)
    dgroups: dict[str, list] = {}
    for c in fdongs:
        dgroups.setdefault(c.get("group", "main"), []).append(c)
        groups.setdefault(c.get("group", "main"), [])

    for g, items in groups.items():
        complexes, chk_rows, chk_sum = {}, 0, 0
        dongs = {c["id"]: dong_stats(c, keep) for c in dgroups.get(g, [])}
        chk_drows = sum(len(v) for x in dongs.values() for v in x["bands"].values())
        chk_dn = sum(r[1] for x in dongs.values() for v in x["bands"].values() for r in v)
        chk_dmed = sum(r[2] for x in dongs.values() for v in x["bands"].values() for r in v)
        for c in items:
            rows, have, missing = collect(c, keep)
            shown = [x for x in rows if x[0] in recent3]
            complexes[c["id"]] = {
                "label": c["label"], "lawd": c["lawd"], "umd": c["umd"], "apt_names": c["apt_names"],
                "note": c.get("note"), "months_covered": have, "months_missing": missing,
                "by_area": area_stats(rows, recent3), "rows_4m": shown,
            }
            chk_rows += len(shown)
            chk_sum += sum(x[4] for x in shown)
        out = {
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"), "as_of": as_of,
            "group": g, "unit": "만원", "row_fields": ROW,
            "note": "국토부 원장 전수(ledger/) · 평형 키 = 전용㎡ 정수부 · 통계는 해제 행과 그 짝 정상 행을 모두 제외(_incl_pair는 짝 정상 행 포함) · "
                    "최근 2개월은 신고기한(30일) 전이라 늘 수 있음",
            "complexes": complexes,
            "dongs": dongs,
            "check": {"complexes": len(complexes), "rows_4m": chk_rows, "sum_amount_4m": chk_sum,
                      "dongs": len(dongs), "dong_rows": chk_drows, "dong_sum_n": chk_dn,
                      "dong_sum_median": chk_dmed},
        }
        path = os.path.join(HERE, f"focus_{g}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        print(f"[관심 후보] {path} — 단지 {len(complexes)} · 4개월 행 {chk_rows} · 동 묶음 {len(dongs)}")


if __name__ == "__main__":
    main()
