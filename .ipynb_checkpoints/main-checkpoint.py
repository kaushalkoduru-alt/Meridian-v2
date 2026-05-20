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
}

KNOWN_ACQUIRERS = {
    'UAC': 'Stellantis', 'NATL': 'NCR Voyix', 'WBD': 'Paramount Global',
    'AVNS': 'Becton Dickinson', 'HBT': 'Heartland Financial',
    'ASRT': 'Paratek Pharmaceuticals', 'EHAB': 'KKR',
    'NBRG': 'Glacier Bancorp', 'AFBI': 'Center Parc Credit Union',
    'KTWO': 'Roper Technologies', 'SKYT': 'IonQ',
    'CVGW': 'Mission Produce',
}

EDGAR_QUERIES = [
    {
        'type': 'All Cash',
        'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'
    },
    {
        'type': 'All Cash',
        'url': 'https://efts.sec.gov/LATEST/search-index?q=%22merger+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'
    },
    {
        'type': 'Cash + Stock',
        'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22cash+and+stock%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'
    },
    {
        'type': 'Private Equity',
        'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22+%22sponsor%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'
    },
    {
        'type': 'Tender Offer',
        'url': 'https://efts.sec.gov/LATEST/search-index?q=%22tender+offer%22+%22per+share%22+%22definitive+agreement%22&forms=8-K&dateRange=custom&startdt=2025-06-01&enddt=2026-05-21&from={start}&size=100'
    },
]

FALLBACK_DEALS = [
    {
        'ticker': 'CWAN', 'acquirer': 'Advent International',
        'company': 'Clearwater Analytics', 'deal_type': 'Private Equity',
        'dp': 27.52, 'filed': '2025-02-18', 'close_date': 'Q3 2026', 'tx_value': 6.50,
    },
    {
        'ticker': 'MASI', 'acquirer': 'Danaher',
        'company': 'Masimo Corporation', 'deal_type': 'All Cash',
        'dp': 180.00, 'filed': '2023-02-14', 'close_date': 'TBD', 'tx_value': 7.65,
    },
    {
        'ticker': 'IMXI', 'acquirer': 'Western Union',
        'company': 'International Money Express', 'deal_type': 'All Cash',
        'dp': 16.00, 'filed': '2025-03-10', 'close_date': 'TBD', 'tx_value': None,
    },
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
    patterns = [
        r'([A-Z][A-Za-z\s&,\.\-]+?)\s+(?:has agreed to acquire|will acquire|agreed to acquire)',
        r'([A-Z][A-Za-z\s&,\.\-]+?)\s+today announced.*?(?:acquire|merger|combination)',
        r'([A-Z][A-Za-z\s&,\.\-]+?)\s+(?:Funds?|LLC|Inc|Corp|Ltd).*?(?:agreed to acquire|will acquire|to acquire)',
        r'(?:acquisition of|merger with)\s+.+?\s+by\s+([A-Z][A-Za-z\s&,\.\-]+?)(?:\s+for|\s+in|\s*,|\s*\.)',
        r'([A-Z][A-Za-z\s&,\.\-]+?)\s+(?:to Acquire|to acquire)\s+[A-Z]',
    ]
    candidates = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            m = m.strip()
            m = re.sub(r'\s+', ' ', m)
            m = re.sub(r'\s+(Funds?|LLC|managed|affiliated|sponsored).*$', '', m, flags=re.IGNORECASE)
            if 3 < len(m) < 60 and not any(x in m.lower() for x in [
                'pursuant', 'stockholder', 'common', 'share', 'the company',
                'today', 'this', 'which', 'that', 'upon', 'each'
            ]):
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
    patterns = [
        r'transaction.*?valued.*?approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'aggregate.*?consideration.*?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'total.*?transaction.*?value.*?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million).*?(?:transaction|deal|acquisition)',
        r'valued at approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
    ]
    for pattern in patterns:
        match = re.search(pattern, clean_text[:5000], re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()
            if unit == 'billion':
                return round(value, 2)
            else:
                return round(value / 1000, 2)
    return None

def score_deal(spread_pct, days_since_filed):
    score = 70
    if 0 < spread_pct < 5:      score += 20
    elif spread_pct >= 5:        score += 5
    elif spread_pct < 0:         score -= 20
    if days_since_filed < 30:    score += 10
    elif days_since_filed > 180: score -= 10
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
        if not ticker or not cik or not accession:
            continue
        if ticker in seen_tickers:
            continue
        try:
            h = yf.Ticker(ticker).history(period="5d")
            if h.empty: continue
            cp = h['Close'].iloc[-1]
            if cp < 1: continue
        except:
            continue
        try:
            and_ = accession.replace('-', '')
            ir = requests.get(
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{and_}/{accession}-index.htm",
                headers=headers, timeout=10)
            links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"', ir.text)
            dp = None
            acquirer = "Undisclosed"
            close_date = "TBD"
            tx_value = None
            for lk in links:
                if 'ex99' in lk.lower():
                    dr = requests.get(f"https://www.sec.gov{lk}", headers=headers, timeout=10)
                    ct = BeautifulSoup(dr.text, 'html.parser').get_text()
                    if 'definitive agreement' in ct.lower():
                        dp = extract_price_from_text(ct)
                        acquirer = extract_acquirer(ct)
                        close_date = extract_close_date(ct)
                        tx_value = extract_transaction_value(ct)
                        if dp: break
            if not dp: continue
            sp = dp - cp
            sp_pct = (sp / cp) * 100
            if sp_pct < -10 or sp_pct > 20: continue
            days = (datetime.today() - datetime.strptime(src['file_date'], '%Y-%m-%d')).days
            sc = score_deal(sp_pct, days)
            risk = 'Very Low' if sc >= 80 else 'Low' if sc >= 65 else 'Medium' if sc >= 50 else 'High'
            ann = (sp_pct / 180) * 365
            acquirer = KNOWN_ACQUIRERS.get(ticker, acquirer)
            seen_tickers.add(ticker)
            results.append({
                'ticker':     ticker,
                'acquirer':   acquirer,
                'company':    COMPANY_NAMES.get(ticker, ticker + ' Corp.'),
                'deal_type':  deal_type,
                'cp':         round(cp, 2),
                'dp':         dp,
                'sp_pct':     round(sp_pct, 2),
                'ann':        round(ann, 2),
                'score':      sc,
                'risk':       risk,
                'filed':      src['file_date'],
                'days_old':   days,
                'close_date': close_date,
                'tx_value':   tx_value,
                'fetched':    datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
            })
        except:
            continue

    # Fallback deals EDGAR misses
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
                sc = score_deal(sp_pct, days)
                risk = 'Very Low' if sc >= 80 else 'Low' if sc >= 65 else 'Medium' if sc >= 50 else 'High'
                ann = round((sp_pct / 180) * 365, 2)
                results.append({
                    'ticker':     fd['ticker'],
                    'acquirer':   fd['acquirer'],
                    'company':    fd['company'],
                    'deal_type':  fd['deal_type'],
                    'cp':         cp,
                    'dp':         dp,
                    'sp_pct':     sp_pct,
                    'ann':        ann,
                    'score':      sc,
                    'risk':       risk,
                    'filed':      fd['filed'],
                    'days_old':   days,
                    'close_date': fd['close_date'],
                    'tx_value':   fd['tx_value'],
                    'fetched':    datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
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