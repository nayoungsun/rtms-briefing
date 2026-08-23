#!/usr/bin/env python3
"""
report_data.json  ->  index.html (GitHub Pages 용) + summary.md (Claude 가 읽을 요약)

index.html : 브라우저로 보는 리포트 본체
summary.md : 예약 작업이 WebFetch 로 읽어 채팅 요약을 만들 때 쓰는 압축 텍스트
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import render  # noqa: E402

# summary.md 가 지나치게 길어지지 않도록 그룹별 상한. 잘린 건수는 반드시 표기한다.
MAX_PER_GROUP = 12


def summary_md(data: dict) -> str:
    m, res = data["meta"], data["result"]
    out: list[str] = []
    out.append(f"# 실거래 등록 브리핑 {m['report_date']}")
    out.append("")
    if m["first_run"]:
        out.append("**첫 실행 — 기준선만 저장했습니다. 신규 판정은 다음 실행부터 시작됩니다.**")
        out.append("")
    out.append(f"- 기준일: {m['report_date']}"
               + (f" (직전 대조일 {m['prev_report_date']})" if m.get("prev_report_date") else ""))
    out.append(f"- 새로 등록된 거래: **{m['new_records']:,}건**")
    out.append(f"- 그 중 재건축·재개발 이슈 단지: **{len(res['redev']):,}건**")
    out.append(f"- 조사 범위: {m['regions']}개 시군구, 최근 {m['history_months']}개월 계약분")
    out.append(f"- 생성 시각: {m['generated_at']}")
    out.append("")

    def rows(items: list[dict]) -> list[str]:
        lines = []
        for it in items[:MAX_PER_GROUP]:
            bits = [f"- **{it['apt']}** ({it['umd']}) {it['area']}㎡ {it['floor']}층",
                    f"{it['amount_txt']}", f"계약 {it['deal_date']}"]
            if it["diff"] is None:
                bits.append("직전거래 확인 불가")
            else:
                arrow = "상승" if it["diff"] > 0 else "하락" if it["diff"] < 0 else "보합"
                bits.append(f"직전 {it['prev_date']} {it['prev_amount_txt']} 대비 "
                            f"{it['diff_txt']} ({it['diff_pct']:+.1f}%) {arrow}")
            if it["cancelled"]:
                bits.append(f"⚠ 계약해제({it['cancel_day']})")
            if it.get("redev"):
                bits.append(f"[정비사업: {it['redev']}]")
            lines.append(" · ".join(bits))
        if len(items) > MAX_PER_GROUP:
            lines.append(f"- …외 {len(items) - MAX_PER_GROUP}건 (전체는 리포트 페이지 참조)")
        return lines

    out.append("## 재건축 · 재개발 이슈 단지")
    out.append("")
    out.extend(rows(res["redev"]) if res["redev"]
               else ["해당 없음 — 신규 등록분 중 정비사업 단지 거래가 없습니다."])
    out.append("")

    for bid, label, rng in render.BANDS:
        groups = res["bands"].get(bid, {})
        total = sum(len(v) for v in groups.values())
        out.append(f"## {label} ({rng}) — {total}건")
        out.append("")
        if not groups:
            out.append("해당 없음 — 이 가격대에서 새로 등록된 거래가 확인되지 않았습니다.")
            out.append("")
            continue
        for region, items in groups.items():
            out.append(f"### {region} ({len(items)}건)")
            out.extend(rows(items))
            out.append("")

    out.append("---")
    out.append("출처: 국토교통부 아파트 매매 실거래가 상세 자료 (공공데이터포털 오픈API).")
    out.append("'새로 등록'은 국토부가 신고일 필드를 제공하지 않으므로, 매일 같은 범위를 조회해")
    out.append("전일 스냅샷과 대조하는 방식으로 판정합니다.")
    return "\n".join(out)


def main() -> None:
    with open(os.path.join(HERE, "report_data.json"), encoding="utf-8") as f:
        data = json.load(f)

    body = render.build(data)
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(
            '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'</head><body style="margin:0">{body}</body></html>')

    with open(os.path.join(HERE, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary_md(data))

    m = data["meta"]
    print(f"index.html / summary.md 생성 완료 — 신규 {m['new_records']}건, "
          f"정비사업 {len(data['result']['redev'])}건", file=sys.stderr)


if __name__ == "__main__":
    main()
