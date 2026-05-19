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
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import threading

CACHE_FILE = "meridian_cache.csv"
progress_state = {"current": 0, "total": 0, "deals_found": 0}
progress_lock = threading.Lock()

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

def extract_transaction_value(clean_text):
    patterns = [
        r'transaction.*?valued.*?approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'aggregate.*?consideration.*?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'total.*?transaction.*?value.*?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'\$(\d+(?:\.\d+)?)\s*(billion|million).*?transaction',
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

def process_single_hit(hit, headers):
    src = hit['_source']
    name_str = str(src['display_names'])
    tm = re.search(r'\(([A-Z]{1,5})\)\s+\(CIK', name_str)
    ticker = tm.group(1) if tm else None
    cik = src['ciks'][0].lstrip('0') if src['ciks'] else None
    accession = src['adsh']
    if not ticker or not cik or not accession:
        return None
    try:
        h = yf.Ticker(ticker).history(period="5d")
        if h.empty: return None
        cp = h['Close'].iloc[-1]
        if cp < 1: return None
    except:
        return None
    try:
        and_ = accession.replace('-', '')
        ir = requests.get(
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{and_}/{accession}-index.htm",
            headers=headers, timeout=10)
        links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"', ir.text)
        dp = None
        acquirer = "Undisclosed"
        tx_value = None
        for lk in links:
            if 'ex99' in lk.lower():
                dr = requests.get(f"https://www.sec.gov{lk}", headers=headers, timeout=10)
                ct = BeautifulSoup(dr.text, 'html.parser').get_text()
                if 'definitive agreement' in ct.lower():
                    dp = extract_price_from_text(ct)
                    acquirer = extract_acquirer(ct)
                    tx_value = extract_transaction_value(ct)
                    if dp: break
        if not dp: return None
        sp = dp - cp
        sp_pct = (sp / cp) * 100
        if sp_pct < -10 or sp_pct > 20: return None
        days = (datetime.today() - datetime.strptime(src['file_date'], '%Y-%m-%d')).days
        sc = score_deal(sp_pct, days)
        risk = 'Very Low' if sc >= 80 else 'Low' if sc >= 65 else 'Medium' if sc >= 50 else 'High'
        ann = (sp_pct / 180) * 365
        return {
            'ticker':   ticker,
            'acquirer': acquirer,
            'cp':       round(cp, 2),
            'dp':       dp,
            'sp_pct':   round(sp_pct, 2),
            'ann':      round(ann, 2),
            'score':    sc,
            'risk':     risk,
            'filed':    src['file_date'],
            'days_old': days,
            'tx_value': tx_value,
            'fetched':  datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
        }
    except:
        return None

def fetch_deals_from_edgar(progress_callback=None):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Starting EDGAR fetch...")
    headers = {'User-Agent': 'Kaushal Koduru kaushalkoduru@gmail.com'}
    all_hits = []
    for start in range(0, 400, 100):
        url = (f"https://efts.sec.gov/LATEST/search-index?"
               f"q=%22definitive+agreement%22+%22per+share+in+cash%22"
               f"&forms=8-K&dateRange=custom&startdt=2025-01-01&enddt=2026-05-20"
               f"&from={start}&size=100")
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            hits = resp.json()['hits']['hits']
            all_hits.extend(hits)
            if len(hits) < 100:
                break
        except:
            break

    total = len(all_hits)
    results = []
    completed = 0
    results_lock = threading.Lock()

    def process_and_track(hit):
        nonlocal completed
        result = process_single_hit(hit, headers)
        with results_lock:
            completed += 1
            if result:
                results.append(result)
            if progress_callback:
                progress_callback(completed, total, len(results))
        return result

    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(process_and_track, all_hits)

    if results:
        df = pd.DataFrame(results).drop_duplicates(subset=['ticker'])
        df = df.sort_values('sp_pct', ascending=False).reset_index(drop=True)
        try:
            df.to_csv(CACHE_FILE, index=False)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Saved {len(df)} deals.")
        except Exception as e:
            print(f"Cache save error: {e}")
        return df.to_dict(orient='records')
    return []

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE)
            if not df.empty:
                return df.to_dict(orient='records')
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