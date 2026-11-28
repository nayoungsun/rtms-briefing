# KB부동산 주간 원자료(매매지수 서울·경기, 매수우위지수, 매매거래지수)를 kb/ 에 원문 그대로 저장한다.
# 실거래 흐름판 주간 예약 작업이 raw.githubusercontent.com 에서 이 파일을 읽어 검산한다.
# 받기에 실패하면 기존 파일을 그대로 두고 kb/meta.json 에 실패 사유만 적는다.
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BASE = 'https://data-api.kbland.kr/bfmstat/weekMnthlyHuseTrnd/'
JOBS = {
    'priceIndex_11': ('priceIndex', {'월간주간구분코드': '02', '매물종별구분': '01', '매매전세코드': '01', '지역코드': '11', '기간': '1'}),
    'priceIndex_41': ('priceIndex', {'월간주간구분코드': '02', '매물종별구분': '01', '매매전세코드': '01', '지역코드': '41', '기간': '1'}),
    'makt_01': ('maktTrnd', {'메뉴코드': '01', '월간주간구분코드': '02', '지역코드': '', '기간': '1'}),
    'makt_02': ('maktTrnd', {'메뉴코드': '02', '월간주간구분코드': '02', '지역코드': '', '기간': '1'}),
}
HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://kbland.kr/',
    'Origin': 'https://kbland.kr',
}
os.makedirs('kb', exist_ok=True)
meta_path = 'kb/meta.json'
try:
    meta = json.load(open(meta_path, encoding='utf-8'))
except Exception:
    meta = {}
now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
ok_all = True
for name, (ep, params) in JOBS.items():
    url = BASE + ep + '?' + urllib.parse.urlencode(params)
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=60) as r:
                raw = r.read().decode('utf-8')
            d = json.loads(raw)
            body = d['dataBody']
            if body.get('resultCode') not in (None, 11000, '11000') and not body.get('data'):
                raise ValueError('resultCode %s' % body.get('resultCode'))
            data = body['data']
            if ep == 'priceIndex':
                info = {'업데이트일자': data.get('업데이트일자'), 'last_date': data['날짜리스트'][-1], 'n_regions': len(data['데이터리스트'])}
            else:
                info = {'n_regions': len(data) if isinstance(data, list) else None}
            with open('kb/%s.json' % name, 'w', encoding='utf-8') as f:
                f.write(raw)  # 원문 그대로
            meta[name] = dict(info, fetched_at=now, bytes=len(raw), ok=True)
            err = None
            break
        except Exception as e:
            err = repr(e)[:300]
            time.sleep(10 * (attempt + 1))
    if err:
        ok_all = False
        prev = meta.get(name, {})
        meta[name] = dict(prev, ok=False, last_error=err, failed_at=now)
    print(name, meta[name])
meta['run_at'] = now
json.dump(meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('ALL_OK' if ok_all else 'SOME_FAILED')
