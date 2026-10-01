"""Re-read every live deal's merger agreement through the CURRENT efforts ladder
and compare with the label production shows today.

Usage: python breaks/recheck_efforts.py <deals.json from /api/deals> <out.json> [text_cache_dir]
With a cache dir, exhibit texts are saved/reused so the extractor can be iterated offline.
Read-only: fetches the feed file you give it and EDGAR exhibits; writes only <out.json>.
"""
import contextlib
import io
import json
import re
import sys
import os
import time

import requests

sys.path.insert(0, '.')
with contextlib.redirect_stdout(io.StringIO()):
    import main
from deal_commitment import check_antitrust_efforts

feed = json.load(open(sys.argv[1], encoding='utf-8'))['deals']
H = main.EDGAR_HEADERS
tickers = requests.get('https://www.sec.gov/files/company_tickers.json', headers=H, timeout=30).json()
cik_of = {r['ticker']: str(r['cik_str']) for r in tickers.values()}

out = {}
for d in feed:
    t, acc = d['ticker'], d.get('accession')
    old = next((x for x in (d.get('commitment') or {}).get('terms', [])
                if x['term'] == 'Antitrust obligation'), None)
    rec = {'old_verdict': (old or {}).get('verdict'), 'old_meaning': (old or {}).get('meaning')}
    cik = cik_of.get(t) or main.SEC_CIK_MAP.get(t, '')
    try:
        if not cik or not acc:
            raise RuntimeError('no cik/accession')
        accn = acc.replace('-', '')
        ex2 = main._ex2_by_document_type(cik, accn, acc)
        if not ex2:
            ix = requests.get(f'https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/index.json',
                              headers=H, timeout=15)
            time.sleep(0.12)
            if ix.status_code == 200:
                ex2 = main._pick_ex2(i.get('name') for i in ix.json().get('directory', {}).get('item', []))
        if not ex2:
            ex2 = main._ex2_from_index_page(cik, accn, acc)
        if not ex2:
            raise RuntimeError('no EX-2 exhibit')
        cf = os.path.join(sys.argv[3], t + '.txt') if len(sys.argv) > 3 else None
        if cf and os.path.exists(cf):
            txt = open(cf, encoding='utf-8').read()
        else:
            txt = main._get_text_for_validation(f'https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{ex2}')
            if txt and cf:
                open(cf, 'w', encoding='utf-8').write(txt[:600000])
        if not txt:
            raise RuntimeError('exhibit unreadable')
        v, why, q = check_antitrust_efforts(txt[:600000])
        rec.update(new_verdict=v, new_meaning=why, quote=q, exhibit=ex2)
    except Exception as e:
        rec['error'] = str(e)
    out[t] = rec
    print(t, rec.get('old_verdict'), '->', rec.get('new_verdict', 'ERR ' + rec.get('error', '')), flush=True)
json.dump(out, open(sys.argv[2], 'w'), indent=1)
