#!/usr/bin/env python3
"""report_data.json -> 아티팩트용 HTML"""

from __future__ import annotations

import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BANDS = [("b10", "10억 전후", "8.5억 ~ 11.5억"),
         ("b15", "15억 전후", "13억 ~ 17억"),
         ("b20", "20억 전후", "18억 ~ 22억")]

CSS = """
:root{
  --paper:#F4F6F8; --surface:#FFFFFF; --surface-2:#FAFBFC;
  --ink:#131920; --ink-2:#3D4854; --muted:#6B7684; --line:#E2E7EC;
  --accent:#1F4A7A; --accent-soft:#EAF0F7;
  --up:#C8322D; --up-soft:#FBEDEC;
  --down:#1D5FB8; --down-soft:#EBF1FA;
  --flag:#8A5A00; --flag-soft:#FBF2E0; --flag-line:#E2C489;
  --shadow:0 1px 2px rgba(19,25,32,.05), 0 8px 24px -16px rgba(19,25,32,.25);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#0E1216; --surface:#161C22; --surface-2:#1B222A;
    --ink:#E9EDF2; --ink-2:#C2CBD5; --muted:#8B96A3; --line:#2A333D;
    --accent:#7FB0E4; --accent-soft:#1B2836;
    --up:#F2645C; --up-soft:#2E1D1C;
    --down:#6BA3F0; --down-soft:#182432;
    --flag:#E0AC58; --flag-soft:#2A2114; --flag-line:#5A4520;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  --paper:#0E1216; --surface:#161C22; --surface-2:#1B222A;
  --ink:#E9EDF2; --ink-2:#C2CBD5; --muted:#8B96A3; --line:#2A333D;
  --accent:#7FB0E4; --accent-soft:#1B2836;
  --up:#F2645C; --up-soft:#2E1D1C;
  --down:#6BA3F0; --down-soft:#182432;
  --flag:#E0AC58; --flag-soft:#2A2114; --flag-line:#5A4520;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Sans KR",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.6; -webkit-text-size-adjust:100%;
}
.wrap{max-width:1120px; margin:0 auto; padding:32px 20px 96px;
      display:flex; flex-direction:column; gap:36px}

/* ---- masthead ---- */
.masthead{display:flex; flex-direction:column; gap:18px;
  padding-bottom:22px; border-bottom:2px solid var(--ink)}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:11px;
  letter-spacing:.16em; text-transform:uppercase; color:var(--accent); font-weight:600}
h1{font-family:"Gothic A1","IBM Plex Sans KR",sans-serif; font-weight:800;
  font-size:clamp(28px,5vw,42px); line-height:1.15; margin:0; letter-spacing:-.02em;
  text-wrap:balance}
.sub{color:var(--muted); font-size:14px; margin:0; max-width:62ch}

.stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:10px; overflow:hidden}
.stat{background:var(--surface); padding:14px 16px; display:flex; flex-direction:column; gap:3px}
.stat dt{font-size:11px; color:var(--muted); letter-spacing:.06em; margin:0}
.stat dd{margin:0; font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; color:var(--ink)}
.stat dd small{font-size:12px; font-weight:400; color:var(--muted); margin-left:2px}

.notice{background:var(--accent-soft); border:1px solid var(--line);
  border-left:3px solid var(--accent); border-radius:0 8px 8px 0;
  padding:14px 16px; font-size:13.5px; color:var(--ink-2)}
.notice strong{color:var(--ink)}

/* ---- sections ---- */
section{display:flex; flex-direction:column; gap:16px}
.sec-head{display:flex; align-items:baseline; gap:12px; flex-wrap:wrap}
.sec-head h2{font-family:"Gothic A1","IBM Plex Sans KR",sans-serif; font-weight:700;
  font-size:22px; margin:0; letter-spacing:-.01em}
.sec-head .range{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:12px; color:var(--muted)}
.sec-head .count{margin-left:auto; font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:12px; font-weight:600; color:var(--accent);
  background:var(--accent-soft); padding:3px 9px; border-radius:999px}

.region{background:var(--surface); border:1px solid var(--line); border-radius:12px;
  box-shadow:var(--shadow); overflow:hidden}
.region > h3{margin:0; padding:11px 16px; font-size:13px; font-weight:600;
  letter-spacing:.03em; color:var(--ink-2); background:var(--surface-2);
  border-bottom:1px solid var(--line);
  display:flex; align-items:center; gap:8px}
.region > h3 .n{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11px; color:var(--muted); font-weight:400}

.scroll{overflow-x:auto}
table{border-collapse:collapse; width:100%; min-width:760px; font-size:13.5px}
th{font-size:11px; font-weight:600; letter-spacing:.05em; color:var(--muted);
  text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); white-space:nowrap}
td{padding:11px 12px; border-bottom:1px solid var(--line); vertical-align:top}
tr:last-child td{border-bottom:none}
.num{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums; white-space:nowrap}
.apt{font-weight:600; color:var(--ink)}
.dong{color:var(--muted); font-size:12px; display:block}
.amt{font-weight:600; font-size:14px}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--muted)}
.pill{display:inline-block; padding:2px 7px; border-radius:5px; font-size:11.5px;
  font-family:"IBM Plex Mono",ui-monospace,monospace; font-weight:600; white-space:nowrap}
.pill.up{background:var(--up-soft)} .pill.down{background:var(--down-soft)}
.pill.na{background:var(--surface-2); color:var(--muted); font-weight:400}
.prev{display:block; font-size:11px; color:var(--muted); margin-top:3px}
.chip{display:inline-block; margin-top:5px; padding:2px 8px; border-radius:999px;
  font-size:11px; background:var(--flag-soft); color:var(--flag);
  border:1px solid var(--flag-line); font-weight:500}
tr.has-redev td:first-child{box-shadow:inset 3px 0 0 var(--flag)}
.cancel{color:var(--muted); text-decoration:line-through}

.empty{padding:18px 16px; color:var(--muted); font-size:13.5px;
  background:var(--surface); border:1px dashed var(--line); border-radius:12px}
.empty b{color:var(--ink-2); font-weight:600}

footer{border-top:1px solid var(--line); padding-top:20px; font-size:12.5px;
  color:var(--muted); display:flex; flex-direction:column; gap:8px}
footer a{color:var(--accent)}
footer code{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:11.5px}

@media (max-width:640px){
  .wrap{padding:22px 14px 72px; gap:28px}
  table{min-width:660px}
}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def row_html(it: dict) -> str:
    redev = it.get("redev")
    cls = ' class="has-redev"' if redev else ""

    if it["diff"] is None:
        chg = '<span class="pill na">직전거래 확인 불가</span>'
    elif it["diff"] > 0:
        chg = (f'<span class="pill up">▲ {esc(it["diff_txt"][1:])} '
               f'({it["diff_pct"]:+.1f}%)</span>')
    elif it["diff"] < 0:
        chg = (f'<span class="pill down">▼ {esc(it["diff_txt"][1:])} '
               f'({it["diff_pct"]:+.1f}%)</span>')
    else:
        chg = '<span class="pill na">보합</span>'

    if it.get("prev_date"):
        chg += (f'<span class="prev">직전 {esc(it["prev_date"])} · '
                f'{esc(it["prev_amount_txt"])}</span>')

    amt_cls = "amt num cancel" if it["cancelled"] else "amt num"
    cancel_note = (f'<span class="prev">계약해제 {esc(it["cancel_day"])}</span>'
                   if it["cancelled"] else "")
    chip = f'<span class="chip">정비사업 · {esc(redev)}</span>' if redev else ""

    return f"""<tr{cls}>
<td><span class="apt">{esc(it["apt"])}</span><span class="dong">{esc(it["umd"])}</span>{chip}</td>
<td class="num">{esc(it["area"])}㎡</td>
<td class="num">{esc(it["floor"])}층</td>
<td class="{amt_cls}">{esc(it["amount_txt"])}{cancel_note}</td>
<td class="num">{esc(it["deal_date"])}</td>
<td>{chg}</td>
<td class="num">{esc(it.get("dealing") or "—")}</td>
</tr>"""


THEAD = """<thead><tr>
<th>단지 / 동</th><th>전용면적</th><th>층</th><th>거래금액</th>
<th>계약일</th><th>직전거래 대비</th><th>거래유형</th>
</tr></thead>"""


def region_block(name: str, items: list[dict]) -> str:
    rows = "\n".join(row_html(i) for i in items)
    return f"""<div class="region">
<h3>{esc(name)} <span class="n">{len(items)}건</span></h3>
<div class="scroll"><table>{THEAD}<tbody>
{rows}
</tbody></table></div></div>"""


def build(data: dict) -> str:
    meta, res = data["meta"], data["result"]
    first = meta["first_run"]

    if first:
        notice = ('<div class="notice"><strong>오늘은 기준선(baseline)을 만든 첫 실행입니다.</strong> '
                  '이 리포트는 어제 스냅샷과 오늘 스냅샷을 비교해 <em>새로 등록된 건</em>만 뽑아냅니다. '
                  '비교 대상이 아직 없으므로 신규 0건으로 표시되며, 내일 아침부터 정상적으로 '
                  '전일 신규 등록분이 채워집니다.</div>')
    else:
        notice = (f'<div class="notice">국토교통부 실거래가 공개시스템 데이터를 매일 같은 범위로 내려받아 '
                  f'<strong>{esc(meta["prev_report_date"])}</strong> 스냅샷과 대조했습니다. '
                  f'아래는 그 사이에 <strong>새로 등록된 거래</strong>입니다. '
                  f'계약일은 등록일보다 이전일 수 있습니다.</div>')

    parts: list[str] = []

    # 재건축/재개발
    redev = res["redev"]
    if redev:
        body = region_block("정비사업 이슈 단지", redev)
    else:
        body = ('<div class="empty"><b>해당 없음</b> — 신규 등록분 중 재건축·재개발 '
                '이슈 단지에 해당하는 거래가 없습니다.</div>')
    parts.append(f"""<section>
<div class="sec-head"><h2>재건축 · 재개발 이슈 단지</h2>
<span class="range">워치리스트 + 준공 30년 경과 자동 판정</span>
<span class="count">{len(redev)}건</span></div>
{body}</section>""")

    # 가격대별
    for bid, label, rng in BANDS:
        groups = res["bands"].get(bid, {})
        total = sum(len(v) for v in groups.values())
        if groups:
            body = "\n".join(region_block(k, v) for k, v in groups.items())
        else:
            body = ('<div class="empty"><b>해당 없음</b> — 이 가격대에서 새로 등록된 '
                    '거래가 확인되지 않았습니다.</div>')
        parts.append(f"""<section>
<div class="sec-head"><h2>{esc(label)}</h2><span class="range">{esc(rng)}</span>
<span class="count">{total}건</span></div>
{body}</section>""")

    return f"""<title>실거래 등록 브리핑</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Gothic+A1:wght@700;800&family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>{CSS}</style>

<div class="wrap">
<header class="masthead">
  <div class="eyebrow">{esc(meta["report_date"])} · 전일 신규 등록분</div>
  <h1>실거래 등록 브리핑</h1>
  <p class="sub">서울 25개 구와 용인 · 수원 · 성남 · 과천 · 광명의 아파트 매매 실거래 중,
  국토교통부 공개시스템에 어제 새로 올라온 건을 가격대별로 정리했습니다.</p>
  <dl class="stats">
    <div class="stat"><dt>신규 등록</dt><dd>{meta["new_records"]:,}<small>건</small></dd></div>
    <div class="stat"><dt>정비사업 단지</dt><dd>{len(res["redev"]):,}<small>건</small></dd></div>
    <div class="stat"><dt>대조 대상</dt><dd>{meta["window_records"]:,}<small>건</small></dd></div>
    <div class="stat"><dt>조사 시군구</dt><dd>{meta["regions"]}<small>곳</small></dd></div>
    <div class="stat"><dt>생성 시각</dt><dd style="font-size:14px">{esc(meta["generated_at"][11:16])}<small>KST</small></dd></div>
  </dl>
  {notice}
</header>

{"".join(parts)}

<footer>
<div>출처 · <a href="https://www.data.go.kr/data/15126468/openapi.do">국토교통부 아파트 매매 실거래가 상세 자료 (공공데이터포털 오픈API)</a>
— 원본 공개시스템 <a href="https://rt.molit.go.kr/">rt.molit.go.kr</a></div>
<div>‘신규 등록’은 국토부가 신고일 필드를 제공하지 않기 때문에, 매일 같은 범위를 조회해 저장한
전일 스냅샷과 대조하는 방식으로 판정합니다. 계약 해제분은 <code>계약해제</code>로 표시됩니다.</div>
<div>금액은 신고서 기준이며 등기 완료 여부와는 다릅니다. 투자 판단의 근거로 쓰기 전에 원본을 확인하세요.</div>
</footer>
</div>

<script type="application/json" id="rtms-snapshot">{data["snapshot_blob"]}</script>"""


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "report_data.json")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "report.html")
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(build(data))
    print(f"wrote {dst}", file=sys.stderr)
