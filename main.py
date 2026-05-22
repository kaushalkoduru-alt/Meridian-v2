from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
import pandas as pd
import os
import requests
import re
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime
import asyncio
import json
import math
from contextlib import asynccontextmanager

CACHE_FILE = "meridian_cache.csv"

COMPANY_NAMES = {
    'UNF': 'UniFirst Corporation', 'KDP': 'Keurig Dr Pepper',
    'OGN': 'Organon & Co.', 'IMXI': 'International Money Express',
    'AES': 'The AES Corporation', 'WBD': 'Warner Bros. Discovery',
    'HBT': 'Heartland BancCorp', 'PRA': 'ProAssurance Corporation',
    'GBTG': 'Global Business Travel Group', 'AVNS': 'Avanos Medical',
    'CPRX': 'Catalyst Biosciences', 'KALV': 'KalVista Pharmaceuticals',
    'MASI': 'Masimo Corporation', 'CWAN': 'Clearwater Analytics',
    'ASRT': 'Assertio Holdings', 'TPH': 'Tri Pointe Homes',
    'TERN': 'Terns Pharmaceuticals', 'CSGS': 'CSG Systems International',
    'EHAB': 'Enhabit Home Health', 'SLNO': 'Soleno Therapeutics',
    'APLS': 'Apellis Pharmaceuticals', 'EWCZ': 'European Wax Center',
    'JHG': 'Janus Henderson Group', 'KW': 'Kennedy-Wilson Holdings',
    'UAC': 'United Auto Credit', 'NATL': 'National Western Financial',
    'SKYT': 'SkyWater Technology', 'CVGW': 'Calavo Growers',
    'NBRG': 'Northbrook Bank & Trust', 'AFBI': 'Affinity Bancshares',
    'KTWO': 'K2 Pure Solutions', 'OIM': 'Oil States International',
    'HPE': 'Hewlett Packard Enterprise', 'OC': 'Owens Corning',
    'B': 'Barnes Group',
}

KNOWN_ACQUIRERS = {
    'UAC': 'Stellantis', 'NATL': 'NCR Voyix', 'WBD': 'Paramount Global',
    'AVNS': 'Becton Dickinson', 'HBT': 'Heartland Financial',
    'ASRT': 'Paratek Pharmaceuticals', 'EHAB': 'KKR',
    'NBRG': 'Glacier Bancorp', 'AFBI': 'Center Parc Credit Union',
    'KTWO': 'Roper Technologies', 'SKYT': 'IonQ',
    'CVGW': 'Mission Produce', 'EWCZ': 'General Atlantic',
    'PRA': 'The Doctors Company', 'GBTG': 'Long Lake Management',
    'TERN': 'Merck', 'CSGS': 'CSG Systems International',
    'HPE': 'Juniper Networks', 'OC': 'Saint-Gobain',
    'B': 'Apollo Global Management', 'MASI': 'Danaher',
    'IMXI': 'Western Union', 'CWAN': 'Advent International',
    'SLNO': 'Neurocrine Biosciences',
}

EXCLUDED_TICKERS = {
    'GIW', 'IEAG', 'FVAV', 'YCY', 'AIIA', 'LKSP', 'PACH', 'SPEGU'
}

EDGAR_QUERIES = [
    {'type': 'All Cash', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'All Cash', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22merger+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'Cash + Stock', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22cash+and+stock%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'Private Equity', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22+%22sponsor%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'Tender Offer', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22tender+offer%22+%22per+share%22+%22definitive+agreement%22&forms=8-K&dateRange=custom&startdt=2025-06-01&enddt=2026-05-21&from={start}&size=100'},
]

FALLBACK_DEALS = [
    {'ticker': 'CWAN', 'acquirer': 'Advent International', 'company': 'Clearwater Analytics', 'deal_type': 'Private Equity', 'dp': 27.52, 'filed': '2025-02-18', 'close_date': 'Q3 2026', 'tx_value': 6.50},
    {'ticker': 'MASI', 'acquirer': 'Danaher', 'company': 'Masimo Corporation', 'deal_type': 'All Cash', 'dp': 180.00, 'filed': '2023-02-14', 'close_date': 'TBD', 'tx_value': 7.65},
    {'ticker': 'IMXI', 'acquirer': 'Western Union', 'company': 'International Money Express', 'deal_type': 'All Cash', 'dp': 16.00, 'filed': '2025-03-10', 'close_date': 'TBD', 'tx_value': None},
]

def extract_price_from_text(clean_text):
    patterns = [
        r'\$(\d+\.\d+)\s+per\s+share\s+in\s+cash',
        r'(\d+\.\d+)\s+USD\s+per\s+share\s+in\s+cash',
        r'\$(\d+\.\d+)\s+per\s+share',
        r'(\d+\.\d+)\s+USD\s+per\s+share',
        r'(\d+\.\d+)\s+per\s+share\s+in\s+cash',
    ]
    all_prices = []
    for pattern in patterns:
        matches = re.findall(pattern, clean_text, re.IGNORECASE)
        all_prices.extend([float(p) for p in matches if 1 < float(p) < 1000])
    deal_prices = [p for p in all_prices if p > 5]
    if not deal_prices:
        return None
    return max(set(deal_prices), key=deal_prices.count)

def extract_acquirer(clean_text):
    text = clean_text[:5000]
    garbage = [
        r'News\s*Release\s*', r'Press\s*Release\s*',
        r'For\s*Immediate\s*Release\s*',
        r'Document\w*\s*(?:News\s*)?Release\w*\s*',
        r'\bDocument\b\s*',
        r'Under\s*the\s*terms\s*of\s*the\s*(?:proposed\s*)?(?:merger\s*)?agreement[,\s]*',
        r'Pursuant\s*to\s*the\s*(?:terms\s*of\s*the\s*)?agreement[,\s]*',
        r'In\s*connection\s*with\s*the\s*(?:proposed\s*)?(?:merger|transaction)[,\s]*',
        r'Announces\s+Definitive\s+Agreement\s+',
    ]
    for g in garbage:
        text = re.sub(g, ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()

    patterns = [
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:has agreed to acquire|will acquire|agreed to acquire|agrees to acquire)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+today announced\s+(?:it has agreed|a definitive|an agreement)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:to Acquire|to acquire)\s+[A-Z][a-z]',
        r'(?:acquisition of|merger with)\s+.+?\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s*,|\s*\.)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?(?:Inc|Corp|LLC|Ltd|Company|Group|Partners|Capital|Holdings|Networks|Sciences|Pharmaceuticals|Financial|Bancorp|Bancshares|Bank|Trust|Union|Technologies|Solutions|Services|Systems))\s+(?:has agreed|will acquire|agreed|announces|today)',
    ]
    bad_words = ['pursuant', 'stockholder', 'common stock', 'the company', 'which', 'upon', 'each', 'document', 'exhibit', 'form 8', 'the board', 'the transaction', 'forward', 'investor', 'this agreement', 'subject to', 'following', 'certain']
    candidates = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            m = m.strip().rstrip(',.')
            m = re.sub(r'\s+', ' ', m)
            m = re.sub(r'\s+(?:has|have|will|today|hereby|announces|announced|entered|agrees|agreed|intends)\s*$', '', m, flags=re.IGNORECASE).strip()
            m = re.sub(r',?\s*(?:Inc|Corp|Ltd|LLC)\.?\s*$', '', m).strip()
            if not (2 < len(m) < 55): continue
            if any(bad in m.lower() for bad in bad_words): continue
            if not m[0].isupper(): continue
            if m.upper() == m and len(m) > 5: continue
            candidates.append(m)
    if candidates:
        return min(candidates, key=len)
    return "Undisclosed"

def extract_close_date(clean_text):
    patterns = [
        r'expected to close.*?(?:in the\s+)?(\w+\s+(?:half of\s+)?\d{4})',
        r'expected to be completed.*?(?:in the\s+)?(\w+\s+(?:half of\s+)?\d{4})',
        r'expected to close.*?(\w+\s+\d{4})',
        r'close.*?(?:by|in)\s+((?:Q[1-4]|first|second|third|fourth|early|mid|late)\s+\d{4})',
        r'anticipated to close.*?(?:in\s+)?((?:Q[1-4]|first|second|third|fourth|early|mid|late)\s+\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, clean_text[:3000], re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "TBD"

def extract_transaction_value(clean_text):
    text = clean_text[:8000].replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s+', ' ', text)
    patterns = [
        r'total\s+(?:transaction\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'implies\s+a\s+total\s+(?:value|consideration)\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'valued\s+at\s+approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'transaction\s+valued\s+at\s+(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'aggregate\s+(?:deal\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'total\s+(?:equity\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)\s+(?:and|in)\s+(?:offers|gives|provides)',
        r'\$(\d+(?:\.\d+)?)\s*(billion|million)\s+(?:merger|acquisition|deal|transaction)',
        r'transaction.*?approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()
            if unit == 'billion' and 0.05 <= value <= 500:
                return round(value, 2)
            elif unit == 'million' and 50 <= value <= 500000:
                return round(value / 1000, 2)
    return None

def score_deal(spread_pct, days_since_filed, deal_type='All Cash'):
    score = 70

    if deal_type == 'All Cash':         score += 10
    elif deal_type == 'Tender Offer':   score += 8
    elif deal_type == 'Private Equity': score += 5
    elif deal_type == 'Cash + Stock':   score += 0

    if 0 < spread_pct < 3:       score += 25
    elif 3 <= spread_pct < 5:    score += 18
    elif 5 <= spread_pct < 8:    score += 10
    elif 8 <= spread_pct < 12:   score += 0
    elif 12 <= spread_pct < 18:  score -= 15
    elif 18 <= spread_pct < 25:  score -= 25
    elif spread_pct >= 25:       score -= 35
    elif spread_pct < 0:         score -= 25

    if days_since_filed < 90:    score += 10
    elif days_since_filed < 270: score += 0
    elif days_since_filed < 500: score -= 5
    else:                        score -= 15

    return min(max(score, 0), 100)

def clean_records(records):
    cleaned = []
    for r in records:
        clean = {}
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                clean[k] = None
            else:
                clean[k] = v
        cleaned.append(clean)
    return cleaned

def get_filing_links(cik, accession, headers):
    acc_clean = accession.replace('-', '')
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{accession}-index.html"
    try:
        ir = requests.get(index_url, headers=headers, timeout=10)
        soup = BeautifulSoup(ir.text, 'html.parser')
        ex99_links = []
        other_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.htm' in href.lower() and '/Archives/' in href:
                full = f"https://www.sec.gov{href}" if href.startswith('/') else href
                if any(x in href.lower() for x in ['ex99', 'ex-99', 'exhibit99', 'press', 'ex9901', 'ex9902']):
                    ex99_links.append(full)
                elif 'index' not in href.lower():
                    other_links.append(full)
        return ex99_links + other_links
    except:
        return []

def fetch_deals_from_edgar(progress_callback=None):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Starting EDGAR fetch...")
    headers = {'User-Agent': 'Kaushal Koduru kaushalkoduru@gmail.com'}

    all_hits = []
    seen_ids = set()
    for q in EDGAR_QUERIES:
        for start in range(0, 300, 100):
            url = q['url'].format(start=start)
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                hits = resp.json()['hits']['hits']
                for h in hits:
                    if h['_id'] not in seen_ids:
                        h['_deal_type'] = q['type']
                        all_hits.append(h)
                        seen_ids.add(h['_id'])
                if len(hits) < 100:
                    break
            except:
                break

    total = len(all_hits)
    results = []
    seen_tickers = set()

    for i, hit in enumerate(all_hits):
        if progress_callback:
            progress_callback(i + 1, total, len(results))

        src = hit['_source']
        deal_type = hit.get('_deal_type', 'All Cash')
        name_str = str(src['display_names'])
        tm = re.search(r'\(([A-Z]{1,5})\)\s+\(CIK', name_str)
        ticker = tm.group(1) if tm else None
        cik = src['ciks'][0].lstrip('0') if src['ciks'] else None
        accession = src['adsh']

        if not ticker or not cik or not accession: continue
        if ticker in seen_tickers: continue
        if ticker in EXCLUDED_TICKERS: continue

        try:
            h = yf.Ticker(ticker).history(period="5d")
            if h.empty: continue
            cp = h['Close'].iloc[-1]
            if cp < 1: continue
        except:
            continue

        try:
            dp = None
            acquirer = "Undisclosed"
            close_date = "TBD"
            tx_value = None

            links = get_filing_links(cik, accession, headers)
            if not links:
                acc_clean = accession.replace('-', '')
                ir = requests.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{accession}-index.htm", headers=headers, timeout=10)
                raw_links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"', ir.text)
                links = [f"https://www.sec.gov{l}" for l in raw_links if 'ex99' in l.lower()]

            for lk in links[:8]:
                try:
                    dr = requests.get(lk, headers=headers, timeout=10)
                    ct = BeautifulSoup(dr.text, 'html.parser').get_text()
                    if any(kw in ct.lower() for kw in ['definitive agreement', 'merger agreement', 'tender offer', 'per share in cash', 'per share of']):
                        dp_try = extract_price_from_text(ct)
                        if dp_try:
                            dp = dp_try
                            acquirer = extract_acquirer(ct)
                            close_date = extract_close_date(ct)
                            tx_value = extract_transaction_value(ct)
                            break
                except:
                    continue

            if not dp: continue
            sp = dp - cp
            sp_pct = (sp / cp) * 100
            if sp_pct < -10 or sp_pct > 20: continue
            days = (datetime.today() - datetime.strptime(src['file_date'], '%Y-%m-%d')).days
            sc = score_deal(sp_pct, days, deal_type)
            risk = 'Very Low' if sc >= 80 else 'Low' if sc >= 65 else 'Medium' if sc >= 50 else 'High'
            ann = (sp_pct / 180) * 365
            acquirer = KNOWN_ACQUIRERS.get(ticker, acquirer)
            seen_tickers.add(ticker)
            results.append({
                'ticker': ticker, 'acquirer': acquirer,
                'company': COMPANY_NAMES.get(ticker, ticker + ' Corp.'),
                'deal_type': deal_type, 'cp': round(cp, 2), 'dp': dp,
                'sp_pct': round(sp_pct, 2), 'ann': round(ann, 2),
                'score': sc, 'risk': risk, 'filed': src['file_date'],
                'days_old': days, 'close_date': close_date,
                'tx_value': tx_value,
                'fetched': datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
            })
        except:
            continue

    for fd in FALLBACK_DEALS:
        if fd['ticker'] not in seen_tickers:
            try:
                h = yf.Ticker(fd['ticker']).history(period="5d")
                if h.empty: continue
                cp = round(h['Close'].iloc[-1], 2)
                if cp < 1: continue
                dp = fd['dp']
                sp_pct = round(((dp - cp) / cp) * 100, 2)
                if sp_pct < -10 or sp_pct > 20: continue
                days = (datetime.today() - datetime.strptime(fd['filed'], '%Y-%m-%d')).days
                sc = score_deal(sp_pct, days, fd['deal_type'])
                risk = 'Very Low' if sc >= 80 else 'Low' if sc >= 65 else 'Medium' if sc >= 50 else 'High'
                ann = round((sp_pct / 180) * 365, 2)
                results.append({
                    'ticker': fd['ticker'], 'acquirer': fd['acquirer'],
                    'company': fd['company'], 'deal_type': fd['deal_type'],
                    'cp': cp, 'dp': dp, 'sp_pct': sp_pct, 'ann': ann,
                    'score': sc, 'risk': risk, 'filed': fd['filed'],
                    'days_old': days, 'close_date': fd['close_date'],
                    'tx_value': fd['tx_value'],
                    'fetched': datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
                })
                seen_tickers.add(fd['ticker'])
                print(f"✓ Fallback: {fd['ticker']} | {sp_pct:+.2f}%")
            except:
                continue

    if results:
        df = pd.DataFrame(results).drop_duplicates(subset=['ticker'])
        df = df.sort_values('sp_pct', ascending=False).reset_index(drop=True)
        try:
            df.to_csv(CACHE_FILE, index=False)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Saved {len(df)} deals.")
        except Exception as e:
            print(f"Cache save error: {e}")
        return clean_records(df.to_dict(orient='records'))
    return []

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE)
            if not df.empty:
                return clean_records(df.to_dict(orient='records'))
        except:
            pass
    return None

async def auto_refresh_loop():
    while True:
        await asyncio.sleep(3600)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auto-refresh triggered.")
        try:
            await asyncio.get_event_loop().run_in_executor(None, fetch_deals_from_edgar)
        except Exception as e:
            print(f"Auto-refresh error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(auto_refresh_loop())
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auto-refresh started.")
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def home():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/dashboard")
async def dashboard():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/methodology")
async def methodology():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/deals")
async def get_deals():
    deals = load_cache()
    if deals is None:
        deals = fetch_deals_from_edgar()
    return JSONResponse(content={"deals": deals})

@app.get("/api/refresh-stream")
async def refresh_stream():
    async def generate():
        progress_data = {"current": 0, "total": 0, "deals_found": 0}
        def progress_callback(current, total, deals_found):
            progress_data["current"] = current
            progress_data["total"] = total
            progress_data["deals_found"] = deals_found
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, lambda: fetch_deals_from_edgar(progress_callback))
        while not future.done():
            data = json.dumps(progress_data)
            yield f"data: {data}\n\n"
            await asyncio.sleep(0.5)
        deals = await future
        final = json.dumps({"done": True, "deals": deals})
        yield f"data: {final}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/api/refresh")
async def refresh_deals():
    loop = asyncio.get_event_loop()
    deals = await loop.run_in_executor(None, fetch_deals_from_edgar)
    return JSONResponse(content={"deals": deals})