from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
import pandas as pd
import os
import requests
import re
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import asyncio
import json
import math
import random
import time
from contextlib import asynccontextmanager
import stripe

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID', '')
CLERK_SECRET_KEY = os.environ.get('CLERK_SECRET_KEY', '')
BASE_URL = 'https://meridian-v2-production-cffa.up.railway.app'



# ─── REDIS CACHE ─────────────────────────────────────────────────────────────

REDIS_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '')
REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
CACHE_KEY   = 'meridian_deals_v1'
CACHE_FILE  = "meridian_cache.csv"
# ─── SEC COMPLIANCE ───────────────────────────────────────────────────────────
# No 'Host' header — requests manages this dynamically to avoid TLS mismatches
SEC_HEADERS = {
    'User-Agent': 'MeridianResearch/1.0 (kaushalkoduru@gmail.com)',
    'Accept-Encoding': 'gzip, deflate',
}
EDGAR_HEADERS = {
    'User-Agent': 'MeridianResearch/1.0 (kaushalkoduru@gmail.com)',
    'Accept-Encoding': 'gzip, deflate',
}
SEC_TICKER_MAP = {}  # ticker -> official SEC company name, populated at startup
SEC_CIK_MAP    = {}  # ticker -> zero-padded CIK string, populated at startup

def fetch_sec_ticker_map():
    """
    Fetches SEC's official company_tickers.json once at startup.
    Builds two lookup dicts: ticker->name and ticker->cik.
    Cached in Redis for 24 hours. Single request — no rate limit concern.
    Runs in run_in_executor thread pool, never blocks the event loop.
    """
    global SEC_TICKER_MAP, SEC_CIK_MAP
    cache_key = 'sec_ticker_map_v1'

    # ── Try Redis cache first ──────────────────────────────────────────────────
    try:
        r = requests.get(
            f"{REDIS_URL}/get/{cache_key}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=10
        )
        result = r.json().get('result')
        if result:
            raw = result if isinstance(result, str) else result.get('value', '')
            if raw:
                data = json.loads(raw)
                if data.get('ticker_map'):
                    SEC_TICKER_MAP = data['ticker_map']
                    SEC_CIK_MAP    = data.get('cik_map', {})
                    print(f"[SEC] Ticker map loaded from Redis: {len(SEC_TICKER_MAP)} tickers")
                    return
    except Exception as e:
        print(f"[SEC] Redis read error: {e}")

    # ── Fetch from SEC ─────────────────────────────────────────────────────────
    try:
        resp = requests.get(
            'https://www.sec.gov/files/company_tickers.json',
            headers=SEC_HEADERS,
            timeout=30
        )
        if resp.status_code != 200:
            print(f"[SEC] Ticker map fetch failed: HTTP {resp.status_code}")
            return
        raw_data = resp.json()
        ticker_map = {}
        cik_map    = {}
        for entry in raw_data.values():
            t    = entry.get('ticker', '').upper().strip()
            name = entry.get('title', '').strip()
            cik  = str(entry.get('cik_str', '')).zfill(10)
            if t and name:
                ticker_map[t] = name
                cik_map[t]    = cik
        SEC_TICKER_MAP = ticker_map
        SEC_CIK_MAP    = cik_map
        print(f"[SEC] Ticker map fetched fresh: {len(SEC_TICKER_MAP)} tickers")

        # ── Write to Redis using body POST (URL-path would exceed length limits) ─
        try:
            payload = json.dumps({'ticker_map': ticker_map, 'cik_map': cik_map})
            requests.post(
                f"{REDIS_URL}/set/{cache_key}",
                headers={
                    "Authorization": f"Bearer {REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"value": payload, "ex": 86400},
                timeout=20
            )
        except Exception as e:
            print(f"[SEC] Redis write error (non-fatal): {e}")

    except Exception as e:
        print(f"[SEC] Ticker map fetch error: {e}")


def resolve_company_name(ticker):
    """
    Returns the official company name for a ticker.
    Priority: SEC official name → yfinance shortName → honest placeholder.
    Never returns a fake 'TICKER Corp.' name.
    """
    if ticker in SEC_TICKER_MAP:
        return SEC_TICKER_MAP[ticker]
    try:
        info = yf.Ticker(ticker).info
        name = info.get('shortName') or info.get('longName', '')
        if name and len(name) > 2 and name.upper() != ticker:
            return name
    except:
        pass
    return f"{ticker} (name pending)"

def redis_get():
    if not REDIS_URL or not REDIS_TOKEN:
        return None
    try:
        r = requests.get(
            f"{REDIS_URL}/get/{CACHE_KEY}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=10
        )
        data = r.json()
        result = data.get('result')
        if not result:
            return None
        if isinstance(result, str):
            return json.loads(result)
        if isinstance(result, dict) and 'value' in result:
            return json.loads(result['value'])
        return None
    except Exception as e:
        print(f"Redis get error: {e}")
        return None

def redis_set(deals):
    if not REDIS_URL or not REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(deals)
        encoded = requests.utils.quote(payload, safe='')
        r = requests.post(
            f"{REDIS_URL}/set/{CACHE_KEY}/{encoded}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=15
        )
        print(f"Redis set: {r.status_code} — {len(deals)} deals saved")
        return r.status_code == 200
    except Exception as e:
        print(f"Redis set error: {e}")
        return False

def save_cache(records):
    if not records:
        return
    try:
        # Strip temp filing text before saving to Redis — work on copies not originals
        clean_records = [{k: v for k, v in r.items() if k != '_filing_text'} for r in records]
        df = pd.DataFrame(clean_records).drop_duplicates(subset=['ticker'])
        df = df[df['cp'].notna() & (df['cp'] > 0)]
        df['sp_pct'] = pd.to_numeric(df['sp_pct'], errors='coerce').fillna(0)
        df = df.sort_values('sp_pct', ascending=False).reset_index(drop=True)
        # Replace all NaN values with None so JSON serialization doesn't crash
        df = df.where(pd.notnull(df), None)
        clean = df.to_dict(orient='records')
        if len(clean) >= 3:
            merged = rolling_merge(clean)
            redis_set(merged)
            try:
                tmp = CACHE_FILE + '.tmp'
                pd.DataFrame(merged).to_csv(tmp, index=False)
                os.replace(tmp, CACHE_FILE)
            except:
                pass
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Cache saved: {len(merged)} deals ({len(clean)} from scan, {len(merged)-len(clean)} carried over).")
    except Exception as e:
        print(f"save_cache error: {e}")


def rolling_merge(new_deals):
    """
    Merges new scan results with existing cache.
    - New deals always included with fresh prices
    - Deals missing from this scan but in cache are kept IF:
      1. They were seen within the last 2 hours (one missed scan)
      2. Their spread hasn't moved more than 15% in either direction
    - Deals missing from two consecutive scans are dropped
    - Deals whose stock has crashed more than 15% below deal price are dropped immediately
    """
    existing = redis_get()
    if not existing:
        return new_deals

    now = datetime.utcnow()
    new_tickers = {d['ticker'] for d in new_deals}
    carried = []

    for deal in existing:
        if deal['ticker'] in new_tickers:
            continue  # Already in new scan with fresh data
        try:
            fetched_str = deal.get('fetched', '')
            if not fetched_str:
                continue
            fetched_time = datetime.strptime(fetched_str, '%Y-%m-%dT%H:%M')
            age_hours = (now - fetched_time).total_seconds() / 3600

            # Drop if missing for more than 2 hours (2 consecutive scans)
            if age_hours > 2:
                print(f"  Rolling drop: {deal['ticker']} — missing for {age_hours:.1f}h")
                continue

            # Drop deals with null current price — can't calculate spread
            if not deal.get('cp'):
                print(f"  Rolling drop: {deal['ticker']} — null current price")
                continue

            # Drop immediately if spread has gone very negative (deal broke/closed)
            sp = deal.get('sp_pct', 0)
            if sp < -15:
                print(f"  Rolling drop: {deal['ticker']} — spread crashed to {sp:.2f}%")
                continue

            # Validate carried deal using existing cached price — no new yfinance calls
            cp = deal.get('cp')
            dp = deal.get('dp', 0)
            if cp and dp and cp > 0:
                sp = round(((dp - cp) / cp) * 100, 2)
                if sp < -15:
                    print(f"  Rolling drop: {deal['ticker']} — spread {sp:.2f}%")
                    continue
                ratio = dp / cp
                if ratio < 0.70 or ratio > 3.00:
                    print(f"  Rolling drop: {deal['ticker']} — price ratio {ratio:.2f} invalid")
                    continue

            carried.append(deal)
            print(f"  Rolling carry: {deal['ticker']} — {age_hours:.1f}h old")
        except:
            continue

    merged = new_deals + carried
    merged.sort(key=lambda x: x.get('sp_pct', 0), reverse=True)
    return merged

def load_cache():
    deals = redis_get()
    if deals:
        print(f"Loaded {len(deals)} deals from Redis.")
        return deals
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE)
            if not df.empty:
                print(f"Loaded {len(df)} deals from local CSV.")
                return clean_records(df.to_dict(orient='records'))
        except:
            pass
    return None

def is_cache_fresh(max_age_minutes=50):
    deals = load_cache()
    if not deals:
        return False
    try:
        cache_time = datetime.strptime(deals[0].get('fetched', ''), '%Y-%m-%dT%H:%M')
        age = (datetime.utcnow() - cache_time).total_seconds() / 60
        return age < max_age_minutes
    except:
        return False

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

# COMPANY_NAMES and KNOWN_ACQUIRERS eliminated — replaced by dynamic SEC resolution.
# resolve_company_name() uses SEC's official company_tickers.json fetched at startup.
# VERIFIED_ACQUIRERS contains only manually confirmed overrides.
VERIFIED_ACQUIRERS = {
    'EA': 'Savvy Games Group (Saudi Arabia)',
    'CZR':  'Fertitta Entertainment',        # confirmed 5/28/26 8-K + press release
    'NATH': 'Smithfield Foods',              # confirmed 1/21/26 8-K
    'AES':  'GIP / EQT Consortium',          # confirmed 3/2/26 8-K — lead acquirers GIP (BlackRock) + EQT
}

VERIFIED_TX_VALUES = {
    'WBD': 110.0,   # Paramount-WBD — $110B enterprise value
    'GSAT': 11.6,   # Amazon-Globalstar — $11.6B
    'RGR': 0.7,     # Tender offer — ~$700M based on market cap
}

VERIFIED_CLOSE_DATES = {
    'CZR':  'mid-to-late 2027',              # Fertitta Entertainment — confirmed 5/28/26 8-K
    'OGN':  'early 2027',
    'NATH': 'H2 2026',                       # updated: CFIUS delay shifted from H1 — confirmed updated 8-K
    'GSAT': '2027',
    'CLST': 'H2 2026',
    'CPRX': 'H2 2026',
    'PAYO': 'mid-2027',                      # Nuvei/Payoneer — confirmed 6/15/26 press release + 8-K
    'ALOT': 'Q3 2026',                       # AstroNova/Arcline
    'WBD':  'Q3 2026',                       # Paramount/WBD
    'AES':  'late 2026 or early 2027',       # GIP/EQT Consortium — confirmed 3/2/26 8-K
    'GBTG': 'second half 2026',              # Long Lake
    'AVNS': 'second half 2026',
}
EXCLUDED_TICKERS = {
    'GIW', 'IEAG', 'FVAV', 'YCY', 'AIIA', 'LKSP', 'PACH', 'SPEGU',
    'LEGO', 'LEG', 'LEGN', 'MNKD', 'NMP', 'OIM', 'NBIX', 'APAC', 'HBT', 'MCW', 'RGR',
    'KALV',  # Chiesi acquisition closed and became effective 6/11/2026
    'ASRT',  # Closed 6/16/2026
    'KROS',  # Keros Therapeutics issuer self-tender (buyback, $194M capital return, expired 11/18/2025) — never an acquisition
    'CLST',  # Catalyst Bancorp is the ACQUIRER of Lakeside Bancshares (OTC: LKSB), not a target — wrongly ingested from Catalyst's own merger 8-K
}
SECTOR_ETF_MAP = {
    'CACC':'XLF','NTCT':'XLK','NUAN':'XLK','SGEN':'XLV','CCXI':'XLV',
    'AZPN':'XLK','QDEL':'XLV','ONCE':'XLV','ARRY':'XLV','FMBI':'XLF',
    'NTRA':'XLV','EPAY':'XLF','GTES':'XLI','PING':'XLK','PCTY':'XLK',
    'COUP':'XLK','SAVE':'XTN','CHNG':'XLV','SGFY':'XLV','IRBT':'XLK',
    'ATVI':'XLK','ACI':'XLP',
}
EDGAR_QUERIES = [
    {'type': 'All Cash', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-06-30&from={start}&size=100'},
    {'type': 'All Cash', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22merger+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-06-30&from={start}&size=100'},
    {'type': 'Cash + Stock', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22cash+and+stock%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-06-30&from={start}&size=100'},
    {'type': 'Private Equity', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22+%22sponsor%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-06-30&from={start}&size=100'},
    {'type': 'Tender Offer', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22tender+offer%22+%22per+share%22+%22definitive+agreement%22&forms=8-K&dateRange=custom&startdt=2025-06-01&enddt=2026-06-30&from={start}&size=100'},
]

# FALLBACK_DEALS eliminated. No hardcoded deals. Zero real deals > fake deals.

COMPS_DATA = [
    {'ticker': 'ATVI', 'acquirer': 'Microsoft', 'deal_type': 'All Cash', 'spread_at_announce': 25.0, 'outcome': 'Closed', 'days_to_close': 633},
    {'ticker': 'VMW', 'acquirer': 'Broadcom', 'deal_type': 'Cash + Stock', 'spread_at_announce': 18.0, 'outcome': 'Closed', 'days_to_close': 545},
    {'ticker': 'SIAL', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 310},
    {'ticker': 'HES', 'acquirer': 'Chevron', 'deal_type': 'Cash + Stock', 'spread_at_announce': 12.0, 'outcome': 'Closed', 'days_to_close': 343},
    {'ticker': 'SNPS', 'acquirer': 'Cadence', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 423},
    {'ticker': 'CACC', 'acquirer': 'Stellantis', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'ACI', 'acquirer': 'Kroger', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Closed', 'days_to_close': 878},
    {'ticker': 'NTCT', 'acquirer': 'Broadcom', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 115},
    {'ticker': 'GTES', 'acquirer': 'Blackstone', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 117},
    {'ticker': 'MTW', 'acquirer': 'Titan Machinery', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 94},
    {'ticker': 'AIN', 'acquirer': 'Schweitzer-Mauduit', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 106},
    {'ticker': 'CRAWA', 'acquirer': 'Amphenol', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 80},
    {'ticker': 'VSH', 'acquirer': 'Maverick Capital', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 89},
    {'ticker': 'NINE', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 92},
    {'ticker': 'RNST', 'acquirer': 'First Horizon', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 185},
    {'ticker': 'DAY', 'acquirer': 'Carrier Global', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 38},
    {'ticker': 'SNEX', 'acquirer': 'StoneX Group', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 160},
    {'ticker': 'IPG', 'acquirer': 'Omnicom', 'deal_type': 'Cash + Stock', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 259},
    {'ticker': 'CGC', 'acquirer': 'Acreage Holdings', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 273},
    {'ticker': 'KN', 'acquirer': 'Solesis', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 115},
    {'ticker': 'RDW', 'acquirer': 'ATA', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 157},
    {'ticker': 'IRBT', 'acquirer': 'Amazon', 'deal_type': 'All Cash', 'spread_at_announce': 22.0, 'outcome': 'Broken', 'days_to_close': 517},
    {'ticker': 'TSEM', 'acquirer': 'Intel', 'deal_type': 'All Cash', 'spread_at_announce': 28.0, 'outcome': 'Broken', 'days_to_close': 547},
    {'ticker': 'CCXI', 'acquirer': 'AstraZeneca', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 140},
    {'ticker': 'SGMS', 'acquirer': 'Apollo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'FORG', 'acquirer': 'Thales', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'PING', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 200},
    {'ticker': 'PCTY', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 151},
    {'ticker': 'GDRX', 'acquirer': 'Francisco Partners', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'MIME', 'acquirer': 'Permira', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 210},
    {'ticker': 'SGEN', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 277},
    {'ticker': 'PCOR', 'acquirer': 'Trimble', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 150},
    {'ticker': 'BLKB', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'INFIQ', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Broken', 'days_to_close': 204},
    {'ticker': 'MMLP', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Broken', 'days_to_close': 208},
    {'ticker': 'CRVO', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 20.0, 'outcome': 'Broken', 'days_to_close': 181},
    {'ticker': 'SAVE', 'acquirer': 'JetBlue', 'deal_type': 'All Cash', 'spread_at_announce': 35.0, 'outcome': 'Broken', 'days_to_close': 585},
    {'ticker': 'ATEX', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 18.0, 'outcome': 'Broken', 'days_to_close': 228},
    {'ticker': 'SGFY', 'acquirer': 'CVS Health', 'deal_type': 'All Cash', 'spread_at_announce': 12.0, 'outcome': 'Broken', 'days_to_close': 397},
    {'ticker': 'CHNG', 'acquirer': 'UnitedHealth', 'deal_type': 'All Cash', 'spread_at_announce': 22.0, 'outcome': 'Broken', 'days_to_close': 714},
    {'ticker': 'ATHA', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 25.0, 'outcome': 'Broken', 'days_to_close': 184},
    {'ticker': 'IIIN', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 10.0, 'outcome': 'Broken', 'days_to_close': 184},
    {'ticker': 'TIGR', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 18.0, 'outcome': 'Broken', 'days_to_close': 184},
    {'ticker': 'EBIX', 'acquirer': 'Fidelity', 'deal_type': 'All Cash', 'spread_at_announce': 25.0, 'outcome': 'Broken', 'days_to_close': 212},
    {'ticker': 'PNFP', 'acquirer': 'Tennessee Bank', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 182},
    {'ticker': 'VRNT', 'acquirer': 'Cognyte', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 152},
    {'ticker': 'SAIL', 'acquirer': 'Broadcom', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'ATRC', 'acquirer': 'Johnson & Johnson', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'XLNX', 'acquirer': 'AMD', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 475},
    {'ticker': 'AJRD', 'acquirer': 'L3Harris', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 221},
    {'ticker': 'CDAY', 'acquirer': 'Ceridian', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 208},
    {'ticker': 'PLNT', 'acquirer': 'TSG Consumer', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 182},
    {'ticker': 'AMED', 'acquirer': 'UnitedHealth', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 341},
    {'ticker': 'MGLN', 'acquirer': 'Centene', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 365},
    {'ticker': 'MRTX', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 237},
    {'ticker': 'SPWR', 'acquirer': 'TotalEnergies', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'PETQ', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 152},
    {'ticker': 'LMNX', 'acquirer': 'DiaSorin', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 240},
    {'ticker': 'RTLR', 'acquirer': 'Equinor', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 161},
    {'ticker': 'MYOK', 'acquirer': 'Bristol Myers', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 50},
    {'ticker': 'ARNA', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 88},
    {'ticker': 'AFMD', 'acquirer': 'Genmab', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 182},
    {'ticker': 'KRTX', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 139},
    {'ticker': 'RGNX', 'acquirer': 'Ultragenyx', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'HALO', 'acquirer': 'Janssen', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 228},
    {'ticker': 'IMVT', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 153},
    {'ticker': 'AKBA', 'acquirer': 'Akebia', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 153},
    {'ticker': 'MCRB', 'acquirer': 'Nestle', 'deal_type': 'All Cash', 'spread_at_announce': 7.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'CTIC', 'acquirer': 'Swedish Orphan', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'PNTM', 'acquirer': 'Merck', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 181},
    {'ticker': 'ALDX', 'acquirer': 'AbbVie', 'deal_type': 'All Cash', 'spread_at_announce': 9.0, 'outcome': 'Broken', 'days_to_close': 184},
    {'ticker': 'ENTA', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'YMAB', 'acquirer': 'Jazz Pharma', 'deal_type': 'All Cash', 'spread_at_announce': 7.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'MDVN', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 181},
    {'ticker': 'ACHN', 'acquirer': 'Alexion', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 123},
    {'ticker': 'PGNX', 'acquirer': 'Servier', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'PTLA', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 7.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'AMAG', 'acquirer': 'Covis Pharma', 'deal_type': 'All Cash', 'spread_at_announce': 14.0, 'outcome': 'Broken', 'days_to_close': 100},
    {'ticker': 'SGBX', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 16.0, 'outcome': 'Broken', 'days_to_close': 212},
    {'ticker': 'TTGT', 'acquirer': 'Informa', 'deal_type': 'All Cash', 'spread_at_announce': 13.0, 'outcome': 'Broken', 'days_to_close': 275},
    {'ticker': 'PRSP', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 17.0, 'outcome': 'Broken', 'days_to_close': 182},
    {'ticker': 'DMTK', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 20.0, 'outcome': 'Broken', 'days_to_close': 214},
    {'ticker': 'PAHC', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 22.0, 'outcome': 'Broken', 'days_to_close': 212},
    {'ticker': 'COHN', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 19.0, 'outcome': 'Broken', 'days_to_close': 214},
    {'ticker': 'FWAA', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Broken', 'days_to_close': 213},
    {'ticker': 'AZPN', 'acquirer': 'Emerson Electric', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 223},
    {'ticker': 'COUP', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 77},
    {'ticker': 'EVBG', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 115},
    {'ticker': 'DOMO', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'APPN', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'INST', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 129},
    {'ticker': 'NLOK', 'acquirer': 'Broadcom', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 469},
    {'ticker': 'AVEPO', 'acquirer': 'Apollo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'PRGS', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 181},
    {'ticker': 'AMSF', 'acquirer': 'Blackstone', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'TWTR', 'acquirer': 'Elon Musk', 'deal_type': 'All Cash', 'spread_at_announce': 10.0, 'outcome': 'Closed', 'days_to_close': 185},
    {'ticker': 'DISCA', 'acquirer': 'AT&T', 'deal_type': 'Cash + Stock', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 326},
    {'ticker': 'MGM', 'acquirer': 'Amazon', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 295},
    {'ticker': 'ZNGA', 'acquirer': 'Take-Two Interactive', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 133},
    {'ticker': 'MBWM', 'acquirer': 'Old National', 'deal_type': 'Cash + Stock', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'CLDR', 'acquirer': 'KKR + CDP', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 221},
    {'ticker': 'LHCG', 'acquirer': 'UnitedHealth', 'deal_type': 'Tender Offer', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 315},
    {'ticker': 'ATRS', 'acquirer': 'Amneal', 'deal_type': 'Tender Offer', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 123},
    {'ticker': 'HRMY', 'acquirer': 'Jazz Pharma', 'deal_type': 'Tender Offer', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 122},
    {'ticker': 'PRTO', 'acquirer': 'Novo Nordisk', 'deal_type': 'Tender Offer', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 122},
    {'ticker': 'BMRN', 'acquirer': 'Roche', 'deal_type': 'Tender Offer', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'ARWR', 'acquirer': 'Roche', 'deal_type': 'Tender Offer', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 122},
    {'ticker': 'FATE', 'acquirer': 'Undisclosed', 'deal_type': 'Tender Offer', 'spread_at_announce': 14.0, 'outcome': 'Broken', 'days_to_close': 121},
    {'ticker': 'ARCT', 'acquirer': 'Undisclosed', 'deal_type': 'Tender Offer', 'spread_at_announce': 18.0, 'outcome': 'Broken', 'days_to_close': 182},
    {'ticker': 'LVGO', 'acquirer': 'Teladoc', 'deal_type': 'Cash + Stock', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 98},
    {'ticker': 'PFPT', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 105},
    {'ticker': 'CDXS', 'acquirer': 'Novo Nordisk', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 95},
    {'ticker': 'FMBI', 'acquirer': 'Old National', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 210},
    {'ticker': 'QDEL', 'acquirer': 'Ortho Clinical', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 142},
    {'ticker': 'CLGX', 'acquirer': 'ICE', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 335},
    {'ticker': 'ONCE', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 88},
    {'ticker': 'MDCO', 'acquirer': 'Medicines Company', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 112},
    {'ticker': 'ESRX', 'acquirer': 'Cigna', 'deal_type': 'Cash + Stock', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 289},
    {'ticker': 'CELG', 'acquirer': 'Bristol Myers', 'deal_type': 'Cash + Stock', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 342},
    {'ticker': 'AKAO', 'acquirer': 'Cipla', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 78},
    {'ticker': 'NKTR', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 16.0, 'outcome': 'Broken', 'days_to_close': 195},
    {'ticker': 'SGMO', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 19.0, 'outcome': 'Broken', 'days_to_close': 210},
    {'ticker': 'ACAD', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 14.0, 'outcome': 'Broken', 'days_to_close': 188},
    {'ticker': 'NTRA', 'acquirer': 'Roper Technologies', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'SFLY', 'acquirer': 'Shutterfly', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'MDLA', 'acquirer': 'Veeva', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 156},
    {'ticker': 'SEMG', 'acquirer': 'Sunoco', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 178},
    {'ticker': 'EPAY', 'acquirer': 'Bottomline Tech', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'NUAN', 'acquirer': 'Microsoft', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 365},
    {'ticker': 'VRTU', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'TLND', 'acquirer': 'Qlik', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'TWLO', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 17.0, 'outcome': 'Broken', 'days_to_close': 201},
    {'ticker': 'INVA', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 13.0, 'outcome': 'Broken', 'days_to_close': 178},
    {'ticker': 'ARRY', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'EIGI', 'acquirer': 'Clearlake Capital', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 112},
    {'ticker': 'RLAY', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'MYND', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 21.0, 'outcome': 'Broken', 'days_to_close': 167},
    {'ticker': 'KTCC', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 98},
    {'ticker': 'BNFT', 'acquirer': 'Voya Financial', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 156},
    {'ticker': 'EGRX', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 123},
    {'ticker': 'CVET', 'acquirer': 'JAB Holdings', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 201},
    {'ticker': 'HMSY', 'acquirer': 'UnitedHealth', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'MDXG', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Broken', 'days_to_close': 189},
    {'ticker': 'CSOD', 'acquirer': 'Clearlake Capital', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'ALXN', 'acquirer': 'AstraZeneca', 'deal_type': 'Cash + Stock', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 289},
    {'ticker': 'ACBI', 'acquirer': 'South State', 'deal_type': 'Cash + Stock', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 201},
    {'ticker': 'TCBI', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 9.0, 'outcome': 'Broken', 'days_to_close': 145},
    {'ticker': 'MFIN', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 112},
    {'ticker': 'BPFH', 'acquirer': 'Webster Financial', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 267},
    {'ticker': 'CATY', 'acquirer': 'Heartland Financial', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'HBMD', 'acquirer': 'Shore Bankshares', 'deal_type': 'Cash + Stock', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 189},
    {'ticker': 'UVSP', 'acquirer': 'Fulton Financial', 'deal_type': 'Cash + Stock', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 234},
    {'ticker': 'STFC', 'acquirer': 'Liberty Mutual', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'NGHC', 'acquirer': 'Allstate', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 201},
]

# ─── V3 SCORING MODEL ────────────────────────────────────────────────────────

def extract_financing_signal(text):
    if not text: return 'unknown'
    t = text.lower()
    if any(p in t for p in ['committed financing','fully committed','no financing condition','cash on hand','debt financing committed','all-cash consideration','sufficient cash']):
        return 'committed'
    if any(p in t for p in ['highly confident','highly confident letter']):
        return 'confident'
    if any(p in t for p in ['contingent on financing','subject to obtaining financing','financing condition','subject to financing']):
        return 'contingent'
    return 'unknown'

def score_financing_signal(signal):
    if signal == 'committed':  return 10
    if signal == 'confident':  return 2
    if signal == 'unknown':    return 0
    if signal == 'contingent': return -10
    return 0

def score_regulatory_complexity(reg_tags):
    if not reg_tags: return 5
    if len(reg_tags) == 1 and reg_tags[0].get('agency') == 'Standard Review': return 5
    score = 0
    for tag in reg_tags:
        agency = tag.get('agency', '')
        level  = tag.get('level', 'low')
        if agency == 'HSR Filing':             score -= 3
        elif agency == 'FTC Antitrust':        score -= 8 if level == 'medium' else 15
        elif agency == 'DOJ Antitrust':        score -= 8 if level == 'medium' else 15
        elif agency == 'CFIUS Review':         score -= 18
        elif agency == 'Market Concentration': score -= 10
    return max(-20, min(5, score))

def score_deal_premium(break_price, deal_price):
    if not break_price or not deal_price or break_price <= 0: return 0
    premium_pct = ((deal_price - break_price) / break_price) * 100
    if premium_pct >= 50:   return 8
    elif premium_pct >= 35: return 6
    elif premium_pct >= 25: return 4
    elif premium_pct >= 15: return 2
    elif premium_pct >= 5:  return 0
    else:                   return -5

def score_deal(spread_pct, days_since_filed, deal_type, reg_tags=None, break_price=None, deal_price=None, financing_signal='unknown'):
    score = 50
    if 0 < spread_pct < 3:       score += 25
    elif 3 <= spread_pct < 5:    score += 18
    elif 5 <= spread_pct < 8:    score += 10
    elif 8 <= spread_pct < 12:   score += 0
    elif 12 <= spread_pct < 18:  score -= 15
    elif 18 <= spread_pct < 25:  score -= 25
    elif spread_pct >= 25:       score -= 35
    elif spread_pct < 0:         score -= 25
    if deal_type == 'All Cash':         score += 10
    elif deal_type == 'Tender Offer':   score += 8
    elif deal_type == 'Private Equity': score += 5
    if days_since_filed < 90:    score += 10
    elif days_since_filed < 270: score += 0
    elif days_since_filed < 500: score -= 5
    else:                        score -= 15
    score += score_regulatory_complexity(reg_tags or [])
    score += score_deal_premium(break_price, deal_price)
    score += score_financing_signal(financing_signal)
    normalized = ((score - (-35)) / (118 - (-35))) * 100
    return min(100, max(0, round(normalized)))

def get_risk(spread_pct, score):
    if spread_pct >= 12:  return 'High'
    if spread_pct >= 8:   return 'High' if score < 60 else 'Medium'
    if score >= 75:       return 'Very Low'
    if score >= 55:       return 'Low'
    return 'Medium'

def get_acquirer_type(deal_type, acquirer):
    if deal_type == 'Private Equity': return 'Private Equity'
    pe_kw = ['capital','partners','equity','ventures','holdings','fund','blackstone','kkr','apollo','carlyle','vista','thoma','francisco','advent','permira','clearlake','general atlantic','arcline']
    if acquirer and any(kw in acquirer.lower() for kw in pe_kw): return 'Private Equity'
    return 'Strategic'

# VERIFIED_DEAL_TYPES — manual override for deals where the scanner's stale-filing
# classification stuck (e.g. an early tender-offer 8-K that the deal later moved past).
# Reclassification only fires on fresh EDGAR hits, not on deals carried forward in
# the rolling-carry path — see handoff doc for the structural gap.
VERIFIED_DEAL_TYPES = {
    'WBD': 'All Cash',   # was stuck on 'Tender Offer' from the dead Dec'25-Jan'26 hostile Paramount bid; live deal is a shareholder-approved $31/share all-cash merger
    'ALOT': 'All Cash',  # was stuck on 'Tender Offer'; live deal is a $29/share all-cash PE take-private by Arcline — acquirer_type now correctly derives to Private Equity via the Arcline keyword added above
}

# ─── EXTRACTION HELPERS ──────────────────────────────────────────────────────

def get_comparable_deals(deal_type, spread_pct, current_ticker, max_results=4):
    seed = sum(ord(c)*(i+1) for i,c in enumerate(current_ticker))
    rng  = random.Random(seed)
    comps      = [c for c in COMPS_DATA if c['ticker'] != current_ticker]
    type_match = sorted([c for c in comps if c['deal_type']==deal_type], key=lambda x: x['ticker'])
    tight = [c for c in type_match if abs(c['spread_at_announce']-spread_pct)<=2]
    if len(tight)>=3: return rng.sample(tight, min(max_results,len(tight)))
    loose = [c for c in type_match if abs(c['spread_at_announce']-spread_pct)<=5]
    if len(loose)>=2: return rng.sample(loose, min(max_results,len(loose)))
    return rng.sample(type_match, min(max_results,len(type_match))) if type_match else []

def get_regulatory_risk(ticker, acquirer, tx_value, deal_type):
    tags = []
    try:
        info     = yf.Ticker(ticker).info
        sector   = info.get('sector','')
        industry = info.get('industry','')
    except: sector=industry=''
    tx_billions = tx_value if tx_value else 0
    tx_millions = tx_billions*1000
    if tx_millions>=119.5 or tx_billions>=0.12:
        tags.append({'agency':'HSR Filing','level':'low','reason':'Transaction value triggers mandatory Hart-Scott-Rodino antitrust filing with DOJ and FTC'})
    foreign_kw=['china','chinese','japan','japanese','korea','korean','saudi','emirates','uae','russia','russian','huawei','alibaba','tencent','softbank','samsung']
    if acquirer and any(kw in acquirer.lower() for kw in foreign_kw):
        tags.append({'agency':'CFIUS Review','level':'high','reason':'Foreign acquirer may trigger Committee on Foreign Investment in the US national security review'})
    ftc_sectors=['Technology','Healthcare','Consumer Defensive','Consumer Cyclical','Communication Services']
    if sector in ftc_sectors and tx_billions>=1:
        tags.append({'agency':'FTC Antitrust','level':'medium' if tx_billions<5 else 'high','reason':f'{sector} sector deal of ${tx_billions:.1f}B subject to FTC antitrust review'})
    doj_sectors=['Industrials','Financial Services','Energy','Basic Materials','Utilities']
    if sector in doj_sectors and tx_billions>=1:
        tags.append({'agency':'DOJ Antitrust','level':'medium' if tx_billions<5 else 'high','reason':f'{sector} sector deal of ${tx_billions:.1f}B subject to DOJ antitrust review'})
    conc=['Software','Semiconductors','Biotechnology','Drug Manufacturers','Banks','Insurance','Airlines','Telecom']
    if any(c.lower() in industry.lower() for c in conc) and tx_billions>=2:
        tags.append({'agency':'Market Concentration','level':'high','reason':'Highly concentrated industry — enhanced regulatory scrutiny expected'})
    if not tags:
        tags.append({'agency':'Standard Review','level':'low','reason':'No elevated regulatory concerns identified based on deal size and sector'})
    return tags

def get_break_price(ticker, filed_date):
    try:
        filed = datetime.strptime(filed_date,'%Y-%m-%d')
        for days_back in [7,14,21,30]:
            start=(filed-timedelta(days=days_back)).strftime('%Y-%m-%d')
            end=filed.strftime('%Y-%m-%d')
            h=yf.Ticker(ticker).history(start=start,end=end)
            if not h.empty: return round(float(h['Close'].iloc[-1]),2)
        return None
    except: return None

def get_break_downside(current_price, break_price):
    if not break_price or not current_price: return None
    return round(((break_price-current_price)/current_price)*100,2)
def calculate_break_price(deal_price, premium_pct=None, current_price=None, spread_pct=None):
    # Method 1: deal premium reversal (most reliable)
    if premium_pct and premium_pct > 0:
        bp = round(deal_price / (1 + premium_pct/100), 2)
        return bp, 'premium_reversal'
    # Method 2: spread regression fallback
    if current_price and spread_pct and spread_pct > 0:
        bp = round(current_price - (deal_price - current_price) * (1/spread_pct), 2)
        return bp, 'spread_regression'
    return None, None
# ─── TARGETED SECTION PARSING (Step 2) ───────────────────────────────────────

MERGER_CONSIDERATION_HEADERS = [
    'the merger consideration',
    'summary term sheet',
    'terms of the merger',
    'consideration to be received',
    'per share merger consideration',
    'the offer price',
    'the offer and merger consideration',
    'merger price',
    'the proposed merger',
    'consideration',
]

def extract_targeted_section(html_text):
    """
    Parses filing HTML and extracts only the section immediately following a
    merger consideration header — typically 2500 chars. This prevents false
    positives from exec comp tables, historical price references, and fee schedules.
    Falls back to first 3000 chars if no targeted section is found.
    Runs synchronously inside fetch_deals_from_edgar thread — safe, no await needed.
    """
    try:
        soup = BeautifulSoup(html_text, 'html.parser')
        full_text = soup.get_text(separator=' ', strip=True)
        full_lower = full_text.lower()

        for header in MERGER_CONSIDERATION_HEADERS:
            idx = full_lower.find(header)
            if idx != -1:
                block = full_text[idx:idx + 2500]
                # Validate this block actually contains price language before returning
                if any(kw in block.lower() for kw in [
                    'per share', 'per common share', 'in cash', 'cash consideration'
                ]):
                    return block

        # No targeted section found — fall back to first 3000 chars
        return full_text[:3000]

    except Exception as e:
        print(f"[Parser] Section extract error: {e}")
        try:
            return BeautifulSoup(html_text, 'html.parser').get_text()[:3000]
        except:
            return html_text[:3000]


def validate_deal_price(deal_price, current_price, ticker):
    """
    Validates extracted deal price against live market price.
    Ratio must be between 0.70 and 3.00 for a legitimate active arb deal.
    Below 0.70: deal likely closed or broken (stock has crashed past deal price).
    Above 3.00: extraction error — picked up exec comp or fee table number.
    """
    if not deal_price or not current_price or deal_price <= 0 or current_price <= 0:
        return False
    ratio = deal_price / current_price
    if ratio < 0.70:
        print(f"  Reject {ticker}: deal ${deal_price} / current ${current_price:.2f} = {ratio:.2f} — too low, deal likely closed")
        return False
    if ratio > 3.00:
        print(f"  Reject {ticker}: deal ${deal_price} / current ${current_price:.2f} = {ratio:.2f} — too high, likely extraction error")
        return False
    return True
def extract_price_from_text(clean_text):
    patterns=[
        r'\$(\d+\.\d+)\s+per\s+share\s+in\s+cash',
        r'(\d+\.\d+)\s+USD\s+per\s+share\s+in\s+cash',
        r'\$(\d+\.\d+)\s+per\s+share',
        r'(\d+\.\d+)\s+USD\s+per\s+share',
        r'(\d+\.\d+)\s+per\s+share\s+in\s+cash',
    ]
    all_prices=[]
    for pat in patterns:
        matches=re.findall(pat,clean_text,re.IGNORECASE)
        all_prices.extend([float(p) for p in matches if 1<float(p)<1000])
    deal_prices=[p for p in all_prices if p>5]
    if not deal_prices: return None
    return max(set(deal_prices),key=deal_prices.count)

LEAD_JUNK = re.compile(
    r'^(?:'
    r'(?:under|pursuant to|as part of|in connection with|in accordance with)'
    r'\s+(?:the\s+)?(?:terms\s+of\s+)?(?:the\s+)?(?:agreement|merger agreement|transaction|deal)[,\s]+'
    r'|'
    r'(?:transaction highlights?|press release|news release|for immediate release)\s+'
    r'|'
    r'(?:(?:january|february|march|april|may|june|july|august|september|october|november|december)'
    r'\s+\d{1,2},?\s*\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4})\s*'
    r')',
    re.IGNORECASE
)

def clean_candidate(m):
    """Strip leading clause junk and date contamination from a raw regex match.
    Fixes: 'Under the terms of the agreement, Nuvei' -> 'Nuvei'
           'Transaction Highlights Paramount' -> 'Paramount'
           'As part of the agreement, Amazon' -> 'Amazon'
           'April 8, 2026Catalyst Bancorp' -> 'Catalyst Bancorp'
    """
    # Strip leading dates (handles run-together like "April 8, 2026Catalyst")
    m = re.sub(
        r'^(?:(?:january|february|march|april|may|june|july|august|september|'
        r'october|november|december)\s+\d{1,2},?\s*\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4})',
        '', m, flags=re.IGNORECASE).strip().lstrip(',. ')
    # Strip leading clause introductions
    m = LEAD_JUNK.sub('', m).strip().lstrip(',. ')
    return m

def extract_acquirer(clean_text, target_name=''):
    text = clean_text[:15000]
    for g in [
        r'News\s*Release\s*', r'Press\s*Release\s*', r'For\s*Immediate\s*Release\s*',
        r'Document\w*\s*(?:News\s*)?Release\w*\s*', r'\bDocument\b\s*',
        r'Announces\s+Definitive\s+Agreement\s+', r'Announces\s+Agreement\s+',
    ]:
        text = re.sub(g, ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    patterns = [
        r'to\s+be\s+acquired\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s+at|\s*,|\s*\.|\s+pursuant)',
        r'will\s+be\s+acquired\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s+at|\s*,|\s*\.)',
        r'(?:^|[\.\,]\s*)acquired\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s+at|\s*,|\s*\.)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:has\s+agreed\s+to\s+acquire|agreed\s+to\s+acquire|agrees\s+to\s+acquire)',
        r'(?:that|whereby)\s+([A-Z][A-Za-z0-9\s&\.\-\']{2,40}?)\s+will\s+acquire\b',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+to\s+acquire\s+(?:all\s+)?(?:of\s+)?(?:the\s+)?[A-Z][a-z]',
        r'(?:^|[\.]\s+)([A-Z][A-Za-z0-9\s&,\.\-\']{3,40}?)\s+will\s+acquire\b',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+today\s+announced\s+(?:it\s+has\s+agreed|a\s+definitive|an\s+agreement)',
        r'\bby\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:for\s+\$|in\s+a\s+|in\s+an\s+)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?(?:Inc|Corp|LLC|Ltd|Company|Group|Partners|Capital|Holdings|Management|Foods|Entertainment|Pharmaceuticals|Financial|Technologies|Solutions|Services|Systems))\s+(?:has\s+agreed|will\s+acquire|agreed|to\s+acquire|announced)',
    ]
    BAD_PHRASES = [
        'pursuant', 'stockholder', 'common stock', 'the company', 'which', 'upon',
        'each', 'document', 'exhibit', 'form 8', 'the board', 'the transaction',
        'forward', 'investor', 'this agreement', 'subject to', 'following', 'certain',
        'may not be', 'consummated', 'cannot be', 'will not be', 'is not', 'are not',
        'buyer', 'parent', 'merger sub', 'acquisition sub', 'bidder', 'offeror',
        'purchaser', 'wholly-owned', 'wholly owned', 'a subsidiary', 'subsidiary',
        'under the terms', 'as part of', 'in connection', 'transaction highlights',
    ]
    STOP_WORDS = {'inc', 'corp', 'ltd', 'llc', 'the', 'and', 'of', 'co', 'group',
                  'holdings', 'plc', 'company', 'famous', 'entertainment'}
    target_words = set(target_name.lower().split()) - STOP_WORDS if target_name else set()
    candidates = []
    for pat in patterns:
        for m in re.findall(pat, text, re.IGNORECASE):
            if not isinstance(m, str): continue
            m = m.strip().rstrip(',.')
            m = re.sub(r'\s+', ' ', m)
            m = re.sub(
                r'\s+(?:has|have|will|today|hereby|announces|announced|entered|'
                r'agrees|agreed|intends|to\s+acquire|to\s+be)\s*$',
                '', m, flags=re.IGNORECASE).strip()
            m = re.sub(r',?\s*(?:Inc|Corp|Ltd|LLC)\.?\s*$', '', m).strip()
            m = clean_candidate(m)
            if not (2 < len(m) < 60): continue
            if any(b in m.lower() for b in BAD_PHRASES): continue
            if not m[0].isupper(): continue
            if m.upper() == m and len(m) > 5: continue
            if len(m.split()) > 7: continue
            if target_words:
                cand_words = set(m.lower().split()) - STOP_WORDS
                overlap = len(target_words & cand_words)
                if overlap >= 2 or (overlap >= 1 and len(target_words) <= 2):
                    continue
            candidates.append(m)
    if not candidates:
        return 'Undisclosed'
    multi_word = [c for c in candidates if len(c.split()) > 1]
    if multi_word:
        return min(multi_word, key=len)
    return min(candidates, key=len)
def extract_acquirer_llm(text_block, ticker):
    """
    Fallback acquirer extraction using Groq (free tier) when regex returns Undisclosed.
    Sends a targeted 3000-char block to Llama3 with a strict JSON prompt.
    Groq free tier is generous enough for our scan volume — no cost.
    Runs synchronously inside fetch_deals_from_edgar thread — safe.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return 'Undisclosed'
    try:
        prompt = f"""You are an M&A data extractor analyzing an SEC 8-K filing.
Extract the name of the ACQUIRING company (the buyer) from this merger announcement text.
The target company ticker is {ticker} — do NOT return that company as the acquirer.
Return ONLY a JSON object with no other text: {{"acquirer": "Company Name"}}
If you cannot identify the acquirer with confidence, return: {{"acquirer": null}}

Filing text:
{text_block[:3000]}"""

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "max_tokens": 100,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": "You are an M&A data extractor. Return only valid JSON, no other text."},
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=15
        )
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content'].strip()
            content = content.replace('```json', '').replace('```', '').strip()
            data = json.loads(content)
            acquirer = data.get('acquirer')
            if acquirer and isinstance(acquirer, str) and len(acquirer) > 2:
                # Reject if LLM returned the target ticker's own company name or acquisition sub
                bad_llm = ['acquisition sub', 'merger sub', 'acquisition corp', 'merger corp']
                # Check ticker as whole word only to avoid substring matches like 'hbt' in 'HBT Financial'
                import re as _re
                if len(ticker) > 2:
                    if _re.search(r'\b' + ticker.lower() + r'\b', acquirer.lower()):
                        bad_llm.append(ticker.lower())
                if any(b in acquirer.lower() for b in bad_llm):
                    print(f"  [LLM] {ticker} rejected bad acquirer: {acquirer}")
                    return 'Undisclosed'
                print(f"  [LLM] {ticker} acquirer: {acquirer}")
                return acquirer
        else:
            print(f"  [LLM] Groq error {ticker}: {resp.status_code}")
    except Exception as e:
        print(f"  [LLM] Acquirer extraction error {ticker}: {e}")
    return 'Undisclosed' 
def extract_deal_metadata_llm(text_block, ticker):
    """
    Uses Groq to extract transaction value and expected close date when regex fails.
    Returns dict with 'tx_value' (float in billions or None) and 'close_date' (string or None).
    One call for both fields — minimal API usage.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return {'tx_value': None, 'close_date': None}
    try:
        prompt = f"""You are an M&A data extractor analyzing an SEC 8-K filing.
Extract two pieces of information from this merger announcement:
1. Total transaction value in billions of dollars (just the number, e.g. 2.5 for $2.5 billion)
2. Expected closing date or timeframe (e.g. "Q3 2025", "second half of 2025", "early 2026")

Return ONLY a JSON object with no other text:
{{"tx_value": 2.5, "close_date": "Q3 2025"}}

If you cannot find either value, use null for that field.
Do not include $ signs or the word billion in tx_value — just the number.

Filing text:
{text_block[:3000]}"""

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "max_tokens": 100,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": "You are an M&A data extractor. Return only valid JSON, no other text."},
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=15
        )
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content'].strip()
            content = content.replace('```json', '').replace('```', '').strip()
            data = json.loads(content)
            tx = data.get('tx_value')
            cd = data.get('close_date')
            # Validate tx_value is a reasonable number
            if tx and isinstance(tx, (int, float)) and 0.01 <= float(tx) <= 500:
                tx = round(float(tx), 2)
            else:
                tx = None
            # Validate close_date is a non-empty string
            if cd and isinstance(cd, str) and len(cd) > 2 and cd.lower() not in ['null','none','tbd','unknown']:
                cd = cd.strip()
            else:
                cd = None
            if tx or cd:
                print(f"  [LLM] {ticker} tx_value: {tx}, close_date: {cd}")
            return {'tx_value': tx, 'close_date': cd}
    except Exception as e:
        print(f"  [LLM] Metadata extraction error {ticker}: {e}")
    return {'tx_value': None, 'close_date': None}   
def extract_close_date(clean_text):
    # Patterns ordered specific-to-general: qualified phrases first, greedy catch-alls last.
    # [-\s]+ allows hyphenated forms like "mid-2027" as well as spaced "mid 2027".
    patterns=[
        # Specific: qualifier words anchored to close/complete/anticipated language
        r'(?:expected|anticipated|projected)\s+to\s+close.*?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:half[-\s]+of[-\s]+)?(?:of\s+)?20\d{2})',
        r'(?:expected|anticipated|projected)\s+to\s+be\s+completed.*?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:half[-\s]+of[-\s]+)?(?:of\s+)?20\d{2})',
        r'transaction.*?(?:expected|anticipated|projected).*?(?:close|complete|consummat).*?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late|second half|first half)[-\s]+(?:of\s+)?20\d{2})',
        r'(?:close|complete|consummat).*?(?:by|in|during)\s+((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:of\s+)?20\d{2})',
        r'anticipated\s+to\s+close.*?(?:in\s+)?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:of\s+)?20\d{2})',
        r'close.*?(?:by|in)\s+((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:of\s+)?20\d{2})',
        # Standalone qualifier patterns (no surrounding close language required)
        r'\b(Q[1-4]\s+20\d{2})\b',
        r'\b((?:first|second|third|fourth|early|mid|late)[-\s]+(?:half[-\s]+of[-\s]+)?20\d{2})\b',
        r'calendar\s+year\s+(20\d{2})',
        r'(?:fiscal|calendar)\s+(?:year\s+)?(20\d{2})',
        # Greedy catch-alls last — only fire if nothing above matched
        r'(?:expected|anticipated)\s+to\s+(?:close|complete).*?(?:in\s+(?:the\s+)?)?((?:first|second|third|fourth|early|mid-?|late)[-\s]+(?:half[-\s]+of[-\s]+)?20\d{2})',
        r'(?:expected|anticipated)\s+to\s+(?:close|complete).*?(\w+[-\s]+20\d{2})',
    ]

    QUALIFIER_WORDS = {
        'q1','q2','q3','q4','first','second','third','fourth',
        'early','mid','late','half','calendar','fiscal',
    }

    for pat in patterns:
        m=re.search(pat, clean_text[:5000], re.IGNORECASE)
        if m:
            result = m.group(1).strip()
            if not any(yr in result for yr in ['2025','2026','2027','2028']):
                continue
            # Abstention guard: reject bare "of 2026", "the 2026", "in 2026" fragments
            first_word = re.split(r'[-\s]', result)[0].lower()
            if first_word in ('of', 'the', 'in'):
                continue
            # Bare word+year with no qualifier context → abstain
            if len(re.split(r'[-\s]', result)) == 2 and first_word not in QUALIFIER_WORDS:
                continue
            return result

    return 'TBD'

def get_tender_offer_expiration(ticker, cik):
    """
    Queries EDGAR for SC TO-T filings to get the actual tender offer expiration date.
    SC TO-T is filed by the acquirer but contains the offer expiration date.
    Only runs for Tender Offer deal type.
    """
    try:
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=SC+TO-T&dateb=&owner=include&count=5&search_text=&output=atom"
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        # Parse the atom feed for filing links
        soup = BeautifulSoup(resp.text, 'html.parser')
        entries = soup.find_all('entry')
        if not entries:
            return None
        # Get the most recent SC TO-T filing
        filing_url = None
        for entry in entries[:3]:
            link = entry.find('filing-href')
            if link:
                filing_url = link.text.strip()
                break
        if not filing_url:
            return None
        # Fetch the filing index
        index_resp = requests.get(filing_url, headers=EDGAR_HEADERS, timeout=10)
        if index_resp.status_code != 200:
            return None
        # Look for expiration date in the filing text
        text = BeautifulSoup(index_resp.text, 'html.parser').get_text()
        patterns = [
            r'(?:offer|tender offer).*?(?:expir|expire).*?(\w+\s+\d{1,2},\s+20\d{2})',
            r'(?:expir|expire).*?(\w+\s+\d{1,2},\s+20\d{2})',
            r'(\w+\s+\d{1,2},\s+20\d{2}).*?(?:expir|expire)',
        ]
        for pat in patterns:
            m = re.search(pat, text[:10000], re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None
    except Exception as e:
        print(f"  TO scraper error {ticker}: {e}")
        return None

def extract_transaction_value(clean_text):
    text=re.sub(r'\s+',' ',clean_text[:25000].replace('\n',' ').replace('\r',' '))
    patterns=[
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
    for pat in patterns:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            value=float(m.group(1)); unit=m.group(2).lower()
            if unit=='billion' and 0.05<=value<=500: return round(value,2), 'regex_enterprise'
            if unit=='million' and 50<=value<=500000: return round(value/1000,2), 'regex_enterprise'
    return None, None

def compute_equity_tx_fallback(dp, ticker):
    """
    Fallback only: equity value = deal_price x shares_outstanding from yfinance.
    Returns (value_in_billions, 'equity_calc_approx') or (None, None).
    Convention: EQUITY value (understates enterprise value for leveraged deals).
    Only fires for per-share all-cash deals when regex fails.
    Labeled 'equity_calc_approx' so regulatory threshold logic can treat it as approximate.
    """
    try:
        info = yf.Ticker(ticker).info
        shares = info.get('sharesOutstanding')
        if not shares or shares <= 0:
            return None, None
        equity_b = round(dp * shares / 1e9, 2)
        if 0.01 <= equity_b <= 1000:
            return equity_b, 'equity_calc_approx'
    except Exception as e:
        print(f"  [TxFallback] {ticker}: equity calc error — {e}")
    return None, None

def clean_records(records):
    cleaned=[]
    for r in records:
        clean={}
        for k,v in r.items():
            clean[k]=None if isinstance(v,float) and math.isnan(v) else v
        cleaned.append(clean)
    return cleaned

def get_filing_links(cik, accession, headers):
    acc_clean=accession.replace('-','')
    try:
        ir=requests.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{accession}-index.html",headers=headers,timeout=10)
        soup=BeautifulSoup(ir.text,'html.parser')
        ex99,other=[],[]
        for a in soup.find_all('a',href=True):
            href=a['href']
            if '.htm' in href.lower() and '/Archives/' in href:
                full=f"https://www.sec.gov{href}" if href.startswith('/') else href
                if any(x in href.lower() for x in ['ex99','ex-99','exhibit99','press','ex9901','ex9902']): ex99.append(full)
                elif 'index' not in href.lower(): other.append(full)
        return ex99+other
    except: return []

# ─── CORE PIPELINE ───────────────────────────────────────────────────────────

def fetch_deals_from_edgar():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Background EDGAR scan started.")
    headers={'User-Agent':'Kaushal Koduru kaushalkoduru@gmail.com'}
    all_hits=[]
    seen_ids=set()

    for q in EDGAR_QUERIES:
        for start in range(0,300,100):
            url=q['url'].format(start=start)
            try:
                resp=requests.get(url,headers=headers,timeout=25)
                if resp.status_code==429:
                    print(f"Rate limited — waiting 20s")
                    time.sleep(20)
                    resp=requests.get(url,headers=headers,timeout=25)
                hits=resp.json()['hits']['hits']
                for h in hits:
                    if h['_id'] not in seen_ids:
                        h['_deal_type']=q['type']
                        all_hits.append(h)
                        seen_ids.add(h['_id'])
                if len(hits)<100: break
            except Exception as e:
                print(f"Query error: {e}")
                break

    print(f"EDGAR scan got {len(all_hits)} total hits. Processing...")
    results=[]
    seen_tickers=set()

    # Pre-deduplicate hits by ticker to avoid processing same company multiple times
    seen_pre = set()
    deduped_hits = []
    for hit in all_hits:
        src = hit['_source']
        name_str = str(src.get('display_names',''))
        tm = (re.search(r'\(([A-Z]{1,5})\)\s+\(CIK', name_str) or
              re.search(r'\(([A-Z]{1,5})\)', name_str) or
              re.search(r'([A-Z]{1,5})\s+\(CIK', name_str))
        t = tm.group(1) if tm else None
        key = t if t else src.get('adsh', str(len(deduped_hits)))
        if key not in seen_pre:
            seen_pre.add(key)
            deduped_hits.append(hit)
    all_hits = deduped_hits
    print(f"After deduplication: {len(all_hits)} unique hits")

    for i,hit in enumerate(all_hits):
        src=hit['_source']
        deal_type=hit.get('_deal_type','All Cash')
        form_type=src.get('form_type','')
        # SC 14D9 filings are always tender offers
        if 'SC 14D9' in form_type or 'SC14D9' in form_type:
            deal_type='Tender Offer'
        name_str=str(src['display_names'])
        tm=re.search(r'\(([A-Z]{1,5})\)\s+\(CIK',name_str)
        ticker=tm.group(1) if tm else None
        cik=src['ciks'][0].lstrip('0') if src['ciks'] else None
        accession=src['adsh']
        if not ticker or not cik or not accession: continue
        if ticker in seen_tickers: continue
        if ticker in EXCLUDED_TICKERS: continue

        # ── SPAC filter ───────────────────────────────────────────────────────
        # SPACs have no real merger target yet — exclude them entirely
        spac_keywords = ['acquisition corp', 'acquisition co', 'blank check', 
                        'special purpose acquisition', 'spac', 'business combination corp',
                        'acquisition ii', 'acquisition iii', 'acquisition iv', 'acquisition v',
                        'stonebridge acquisition']
        company_name_lower = str(src.get('display_names', '')).lower()
        if any(kw in company_name_lower for kw in spac_keywords):
            print(f"  Skip {ticker}: SPAC detected in display name")
            continue

        # ── 8-K Item filter ───────────────────────────────────────────────────
        # Only process filings that include Item 1.01 (Entry into Material Definitive Agreement)
        src = hit.get('_source', {})
        items = src.get('items', [])
        if items:  
            item_strs = [str(i) for i in items]
            has_101 = any('1.01' in i for i in item_strs)
            if not has_101:
                print(f"  Skip {ticker}: 8-K items {items} — no Item 1.01")
                continue
        try:
            h=yf.Ticker(ticker).history(period='5d')
            if h.empty:
                time.sleep(2)
                h=yf.Ticker(ticker).history(period='5d')
            if h.empty:
                print(f"${ticker}: possibly delisted; no price data found  (period=5d)")
                seen_tickers.add(ticker)
                continue
            cp=float(h['Close'].iloc[-1])
            if cp<1:
                seen_tickers.add(ticker)
                continue
        except Exception as e:
            print(f"${ticker}: possibly delisted; no price data found  (period=5d) (Yahoo error = \"{e}\")")
            seen_tickers.add(ticker)
            continue
        try:
            dp=None; acquirer='Undisclosed'; close_date='TBD'; tx_value=None; financing_signal='unknown'
            links=get_filing_links(cik,accession,headers)
            if not links:
                acc_clean=accession.replace('-','')
                try:
                    ir=requests.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{accession}-index.htm",headers=headers,timeout=10)
                    raw_links=re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"',ir.text)
                    links=[f"https://www.sec.gov{l}" for l in raw_links if 'ex99' in l.lower()]
                except: pass
            for lk in links[:8]:
                try:
                    dr=requests.get(lk,headers=EDGAR_HEADERS,timeout=10)
                    time.sleep(0.12)  # SEC rate limit: 10 req/sec max — safe: in thread pool
                    # Full text for keyword gate — cheap check before deeper parsing
                    full_ct=BeautifulSoup(dr.text,'html.parser').get_text()
                    # Gate check: must have merger language to proceed
                    if not (any(kw in full_ct.lower() for kw in ['definitive agreement','merger agreement','tender offer','per share in cash']) and
                            any(kw in full_ct.lower() for kw in ['acquir','merger','tender offer']) and
                            ('per share' in full_ct.lower() or 'per common share' in full_ct.lower())):
                        continue
                    # Step 2: extract only the merger consideration section
                    ct=extract_targeted_section(dr.text)
                    dp_try=extract_price_from_text(ct)
                    if not dp_try:
                        continue
                    # Price validation runs FIRST before anything else
                    if not validate_deal_price(dp_try, cp, ticker):
                        continue
                    dp=dp_try
                    # Acquirer extraction — regex only, no LLM
                    acquirer=extract_acquirer(full_ct, target_name=resolve_company_name(ticker))
                    # Reject if filing company is the acquirer not target
                    if acquirer != 'Undisclosed':
                        ticker_company = resolve_company_name(ticker).lower()
                        stop_words = {'inc', 'corp', 'ltd', 'llc', 'the', 'and', 'of', 'co', 'group', 'holdings'}
                        ticker_words = set(ticker_company.split()) - stop_words
                        acquirer_words = set(acquirer.lower().split()) - stop_words
                        overlap_count = len(ticker_words & acquirer_words)
                        if overlap_count >= 2 or (overlap_count >= 1 and len(ticker_words) <= 2):
                            print(f"  Reject {ticker}: acquirer matches own company — filing company is the acquirer")
                            dp = None
                    if not dp: continue
                    # Regex extraction only — no Groq calls
                    close_date=extract_close_date(full_ct)
                    # For tender offers, try to get actual expiration date from SC TO-T filing
                    if deal_type == 'Tender Offer' and close_date == 'TBD':
                        to_date = get_tender_offer_expiration(ticker, cik)
                        if to_date:
                            close_date = to_date
                            print(f"  [TO] {ticker} expiration: {to_date}")
                    tx_value, tx_value_source = extract_transaction_value(full_ct)
                    # Equity calc fallback — only for cash deals when regex failed
                    if tx_value is None and deal_type in ('All Cash', 'Tender Offer') and dp:
                        tx_value, tx_value_source = compute_equity_tx_fallback(dp, ticker)
                    if tx_value is None:
                        tx_value_source = None
                    financing_signal=extract_financing_signal(full_ct)
                    # Reclassify deal type from filing text — overrides query-assigned type
                    full_ct_lower = full_ct.lower()
                    has_cash = 'per share in cash' in full_ct_lower or 'per common share in cash' in full_ct_lower
                    has_stock = any(kw in full_ct_lower for kw in ['stock consideration','equity consideration','per share in a combination of cash and','per share in cash and stock'])
                    has_tender = 'tender offer' in full_ct_lower
                    has_pe = any(kw in full_ct_lower for kw in ['equity sponsor','private equity sponsor','portfolio company of','backed by']) and not has_cash
                    if has_tender:
                        deal_type = 'Tender Offer'
                    elif has_pe:
                        deal_type = 'Private Equity'
                    elif has_cash and has_stock:
                        deal_type = 'Cash + Stock'
                    elif has_cash:
                        deal_type = 'All Cash'
                    break
                except Exception as e:
                    print(f"  Filing parse error {ticker}: {e}")
                    continue
            if not dp: continue
            sp_pct=((dp-cp)/cp)*100
            if sp_pct<-10 or sp_pct>60: continue
            days=(datetime.today()-datetime.strptime(src['file_date'],'%Y-%m-%d')).days
            if days > 548:
                print(f"  Rolling drop: {ticker} — deal is {days} days old, likely closed")
                continue
            acquirer=VERIFIED_ACQUIRERS.get(ticker, acquirer)
            if ticker in VERIFIED_TX_VALUES and not tx_value:
                tx_value=VERIFIED_TX_VALUES[ticker]
                tx_value_source='verified_hardcode'
            if ticker in VERIFIED_CLOSE_DATES:
                close_date=VERIFIED_CLOSE_DATES[ticker]
            if ticker in VERIFIED_DEAL_TYPES:
                deal_type=VERIFIED_DEAL_TYPES[ticker]
            # Log missing fields to REVIEW_QUEUE for hand-fill via VERIFIED_* dicts
            missing_fields = []
            if not acquirer or acquirer == 'Undisclosed':
                missing_fields.append('acquirer')
            if not close_date or close_date == 'TBD':
                missing_fields.append('close_date')
            if not tx_value:
                missing_fields.append('tx_value')
            if missing_fields:
                REVIEW_QUEUE.append({
                    'ticker': ticker,
                    'accession': accession,
                    'missing_fields': missing_fields,
                    'detected_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'note': 'Add verified values to VERIFIED_ACQUIRERS / VERIFIED_CLOSE_DATES / VERIFIED_TX_VALUES',
                })
                print(f"  [Review] {ticker}: missing {missing_fields} — logged to /api/admin/close-date-review-queue")
            break_price=get_break_price(ticker,src['file_date'])
            break_price_method='historical'
            if not break_price:
                premium_pct=None
                pass
                bp_calc,method=calculate_break_price(dp,premium_pct,round(cp,2),round(sp_pct,2))
                if bp_calc and bp_calc>0 and bp_calc<dp:
                    break_price=bp_calc
                    break_price_method=method or 'calculated'
            break_downside=get_break_downside(round(cp,2),break_price)
            reg_tags=get_regulatory_risk(ticker,acquirer,tx_value,deal_type)
            sc=score_deal(sp_pct,days,deal_type,reg_tags,break_price,dp,financing_signal)
            risk=get_risk(sp_pct,sc)
            ann=(sp_pct/180)*365
            acq_type=get_acquirer_type(deal_type,acquirer)
            seen_tickers.add(ticker)
            results.append({
                'ticker':ticker,'acquirer':acquirer,'acquirer_type':acq_type,
                'company':resolve_company_name(ticker),'deal_type':deal_type,
                'cp':round(cp,2),'dp':dp,'sp_pct':round(sp_pct,2),'ann':round(ann,2),
                'score':sc,'risk':risk,'filed':src['file_date'],'days_old':days,
                'close_date':close_date,'tx_value':tx_value,'tx_value_source':tx_value_source,'break_price':break_price,
                'break_downside':break_downside,'break_price_method':break_price_method,
                'financing_signal':financing_signal,
                'reg_tags':json.dumps(reg_tags),'fetched':datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
                '_filing_text':full_ct[:10000],  # Temp field for enrichment, stripped before Redis save
            })
            # At-detection: cheap checks only (no extra EDGAR calls).
            # Completion check and age-out run in daily_validation_loop instead.
            try:
                cheap_flags = []
                # Check 1: SC TO-I form type
                if form_type and 'TO-I' in form_type.upper():
                    cheap_flags.append({
                        'check': 'SELF_TENDER_FORM',
                        'reason': f'Form type is {form_type} (issuer self-tender/buyback by SEC definition)',
                    })
                # Check 2: same-entity name match (Jaccard >= 0.6)
                company_name = resolve_company_name(ticker)
                if acquirer and company_name:
                    score = _name_overlap_score(acquirer, company_name)
                    if score >= 0.6:
                        cheap_flags.append({
                            'check': 'SAME_ENTITY',
                            'reason': (f'Acquirer "{acquirer}" closely matches company name '
                                       f'"{company_name}" (overlap {score:.2f} >= 0.6)'),
                        })
                if cheap_flags:
                    VALIDATION_FLAGS.append({
                        'ticker': ticker,
                        'detected_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'source': 'at_detection',
                        'flags': cheap_flags,
                    })
                    print(f'  [Validate] {ticker}: {len(cheap_flags)} flag(s) at detection — see /api/admin/validation-flags')
                else:
                    print(f'  [Validate] {ticker}: clean at detection')
            except Exception as ve:
                print(f'  [Validate] {ticker}: detection check error — {ve}')

            if len(results) % 10 == 0:
                save_cache(results)
        except: continue

    

    if results:
        save_cache(results)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Scan complete.")
        # Background enrichment — fill missing tx_value and close_date via Groq
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Starting background enrichment...")
            enriched = False
            for deal in results:
                needs_acquirer = deal.get('acquirer') == 'Undisclosed'
                needs_tx = not deal.get('tx_value')
                needs_cd = deal.get('close_date') == 'TBD'
                if not needs_acquirer and not needs_tx and not needs_cd:
                    continue
                # Prioritize acquirer first — only do tx/cd if acquirer already known
                if needs_acquirer:
                    needs_tx = False
                    needs_cd = False
                ticker = deal.get('ticker')
                filing_text = deal.get('_filing_text', '')
                print(f"  [Enrich] {ticker} — acquirer: {deal.get('acquirer')}, tx_value: {deal.get('tx_value')}, close_date: {deal.get('close_date')}")

                # Acquirer enrichment
                if needs_acquirer and filing_text:
                    try:
                        time.sleep(3.0)
                        resp = requests.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                            json={
                                "model": "llama-3.1-8b-instant",
                                "max_tokens": 100,
                                "temperature": 0,
                                "messages": [
                                    {"role": "system", "content": "You are an M&A data extractor. Return only valid JSON, no other text."},
                                    {"role": "user", "content": f"""Extract the acquiring company name from this SEC 8-K merger filing.
The TARGET company ticker is {ticker} and company name is {deal.get('company')} — do NOT return this as the acquirer.
The acquirer is the company BUYING the target.

Filing text:
{filing_text[:3000]}

Return JSON only: {{"acquirer": "Company Name"}}
If you cannot identify the acquirer with confidence, return: {{"acquirer": null}}"""}
                                ]
                            },
                            timeout=15
                        )
                        if resp.status_code == 200:
                            content = resp.json()['choices'][0]['message']['content'].strip()
                            content = content.replace('```json','').replace('```','').strip()
                            data = json.loads(content)
                            acq = data.get('acquirer')
                            if acq and isinstance(acq, str) and len(acq) > 2 and acq.lower() not in ['null','none','unknown']:
                                # Reject if acquirer matches target company name
                                stop_words = {'inc','corp','ltd','llc','the','and','of','co','group','holdings'}
                                ticker_words = set(deal.get('company','').lower().split()) - stop_words
                                acq_words = set(acq.lower().split()) - stop_words
                                if len(ticker_words & acq_words) < 2:
                                    deal['acquirer'] = acq
                                    enriched = True
                                    print(f"  [Enrich] {ticker} acquirer: {acq}")
                        elif resp.status_code == 429:
                            print(f"  [Enrich] Rate limited on acquirer, stopping")
                            break
                    except Exception as e:
                        print(f"  [Enrich] Acquirer error {ticker}: {e}")
                try:
                    time.sleep(3.0)
                    resp = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                        json={
                            "model": "llama-3.1-8b-instant",
                            "max_tokens": 150,
                            "temperature": 0,
                            "messages": [
                                {"role": "system", "content": "You are an M&A data extractor. Return only valid JSON, no other text."},
                                {"role": "user", "content": f"""Extract from this SEC 8-K merger filing text:
1. Total transaction value in billions (number only, e.g. 2.5 for $2.5 billion, 0.45 for $450 million)
2. Expected closing timeframe (e.g. 'Q3 2026', 'second half of 2026', 'early 2027')

Filing text:
{deal.get('_filing_text', '')[:2000]}

Return JSON only: {{"tx_value": 2.5, "close_date": "Q3 2026"}}
IMPORTANT: tx_value is the TOTAL deal value in billions, NOT the per-share price. 
Total deal values are typically described as "$X billion" or "$X million" in the aggregate.
Per-share prices like "$31.00 per share" are NOT the transaction value.
If you cannot find the total deal value clearly stated, use null. Do not guess."""}
                            ]
                        },
                        timeout=15
                    )
                    if resp.status_code == 200:
                        content = resp.json()['choices'][0]['message']['content'].strip()
                        content = content.replace('```json','').replace('```','').strip()
                        data = json.loads(content)
                        tx = data.get('tx_value')
                        cd = data.get('close_date')
                        if tx and isinstance(tx, (int, float)) and 0.01 <= float(tx) <= 500:
                            if not deal.get('tx_value'):
                                deal['tx_value'] = round(float(tx), 2)
                                deal['tx_value_source'] = 'regex_enterprise'
                                enriched = True
                                print(f"  [Enrich] {ticker} tx_value: {deal['tx_value']}B")
                        if cd and isinstance(cd, str) and len(cd) > 2 and cd.lower() not in ['null','none','tbd','unknown']:
                            if deal.get('close_date') == 'TBD':
                                deal['close_date'] = cd.strip()
                                enriched = True
                                print(f"  [Enrich] {ticker} close_date: {cd}")
                    elif resp.status_code == 429:
                        print(f"  [Enrich] Rate limited, stopping enrichment")
                        break
                except Exception as e:
                    print(f"  [Enrich] Error {ticker}: {e}")
                    continue
            if enriched:
                clean = [{k: v for k, v in r.items() if k != '_filing_text'} for r in results]
                save_cache(clean)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Enrichment complete — cache updated.")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Scan returned no results — Redis unchanged.")

# ─── BACKGROUND TASK MANAGEMENT ──────────────────────────────────────────────

_scan_running = False

async def run_background_scan():
    global _scan_running
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, fetch_deals_from_edgar)
        await asyncio.sleep(3)
    except Exception as e:
        print(f"Background scan error: {e}")
    finally:
        _scan_running = False
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Background scan finished.")

async def daily_validation_loop():
    """
    Runs all four validation checks (including the EDGAR-call-heavy completion
    check) against every deal in the feed, once per day. Starts 1 hour after
    startup to avoid competing with the initial scan.
    Flags go to VALIDATION_FLAGS for review — nothing is auto-removed.
    """
    await asyncio.sleep(3600)
    while True:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Daily validation starting...")
        deals = load_cache() or []
        for deal in deals:
            ticker   = deal.get('ticker', '')
            acquirer = deal.get('acquirer', '')
            filed    = deal.get('filed', '')
            cik      = SEC_CIK_MAP.get(ticker, '')
            company  = resolve_company_name(ticker)
            if not ticker or not filed or not cik:
                continue
            try:
                v_flags = validate_deal(ticker, acquirer, cik, company, filed)
                if v_flags:
                    already = any(f['ticker'] == ticker for f in VALIDATION_FLAGS)
                    if not already:
                        VALIDATION_FLAGS.append({
                            'ticker': ticker,
                            'detected_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                            'source': 'daily_check',
                            'flags': v_flags,
                        })
                        print(f'  [Validate-daily] {ticker}: {len(v_flags)} flag(s)')
                    else:
                        print(f'  [Validate-daily] {ticker}: already flagged, skipping')
                else:
                    print(f'  [Validate-daily] {ticker}: clean')
                await asyncio.sleep(2)
            except Exception as e:
                print(f'  [Validate-daily] {ticker}: error — {e}')
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Daily validation complete. "
              f"{len(VALIDATION_FLAGS)} total flag(s) in queue.")
        await asyncio.sleep(86400)

async def auto_refresh_loop():
    while True:
        await asyncio.sleep(3600)
        global _scan_running
        if _scan_running:
            print("Auto-refresh skipped — scan already running.")
            continue
        if is_cache_fresh(50):
            print("Auto-refresh skipped — cache fresh.")
            continue
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auto-refresh triggered.")
        _scan_running = True
        asyncio.create_task(run_background_scan())

async def preload_track_record_charts():
    TRACK_TICKERS = [
        ('CACC','2024-01-15','2024-07-01'),
        ('NTCT','2024-02-20','2024-06-15'),
        ('NUAN','2021-04-12','2022-04-04'),
        ('SGEN','2023-03-13','2023-12-14'),
        ('CCXI','2022-08-08','2022-12-26'),
        ('AZPN','2022-10-11','2023-05-22'),
        ('QDEL','2022-05-27','2022-10-16'),
        ('ONCE','2019-12-17','2020-12-17'),
        ('ARRY','2019-06-17','2019-07-30'),
        ('FMBI','2021-06-01','2022-02-15'),
        ('NTRA','2023-09-11','2024-03-01'),
        ('EPAY','2022-01-12','2022-06-06'),
        ('GTES','2024-01-22','2024-05-18'),
        ('PING','2022-08-03','2023-02-19'),
        ('PCTY','2024-03-05','2024-08-03'),
        ('COUP','2022-12-12','2023-02-27'),
        ('SAVE','2022-07-28','2025-01-01'),
        ('CHNG','2022-01-06','2025-01-01'),
        ('SGFY','2022-09-05','2025-01-01'),
        ('IRBT','2022-08-05','2025-01-01'),
        ('ATVI','2022-01-18','2023-10-13'),
        ('ACI','2022-10-14','2025-01-15'),
    ]
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Preloading track record charts...")
    for ticker, start, end in TRACK_TICKERS:
        cache_key = f"tr_chart_{ticker}"
        try:
            existing = requests.get(
                f"{REDIS_URL}/get/{cache_key}",
                headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
                timeout=5
            ).json()
            if existing.get('result'):
                print(f"  Already cached: {ticker}")
                continue
        except:
            pass
        try:
            etf = SECTOR_ETF_MAP.get(ticker, 'SPY')
            h = yf.Ticker(etf).history(start=start, end=end)
            spy = yf.Ticker("SPY").history(start=start, end=end)
            if not h.empty:
                prices = [{"date": d.strftime('%Y-%m-%d'), "close": round(float(r['Close']), 2)} for d, r in h.iterrows()]
                spy_prices = [{"date": d.strftime('%Y-%m-%d'), "close": round(float(r['Close']), 2)} for d, r in spy.iterrows()]
                payload = json.dumps({"prices": prices, "spy": spy_prices})
                requests.post(
                    f"{REDIS_URL}/set/{cache_key}",
                    headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
                    json={"value": payload},
                    timeout=10
                )
                print(f"  Cached: {ticker}")
        except Exception as e:
            print(f"  Failed {ticker}: {e}")
        time.sleep(0.5)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Track record charts done.")

async def startup_scan():
    global _scan_running
    await asyncio.sleep(3)
    if is_cache_fresh(90):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Redis cache fresh — skipping startup scan.")
        return
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Redis cache empty/stale — starting startup scan.")
    _scan_running = True
    await run_background_scan()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fetch SEC ticker map first — runs in thread pool, never blocks event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, fetch_sec_ticker_map)
    asyncio.create_task(auto_refresh_loop())
    asyncio.create_task(startup_scan())
    asyncio.create_task(daily_validation_loop())
    yield

# ─── APP & ROUTES ─────────────────────────────────────────────────────────────

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

def read_html():
    with open("templates/index.html","r",encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/")
async def home(): return read_html()

@app.get("/dashboard")
async def dashboard(): return read_html()

@app.get("/methodology")
async def methodology(): return read_html()

@app.get("/compare")
async def compare(): return read_html()

@app.get("/api/deals")
async def get_deals():
    deals = load_cache()
    # Sanitize NaN values before JSON serialization
    import math
    def sanitize(obj):
        if isinstance(obj, float) and math.isnan(obj):
            return None
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(i) for i in obj]
        return obj
    deals = sanitize(deals or [])
    return JSONResponse(content={"deals": deals})

@app.get("/api/scan-status")
async def scan_status():
    return JSONResponse(content={"running": _scan_running})

# ─── ADMIN + VALIDATION ───────────────────────────────────────────────────────

ADMIN_TOKEN     = os.environ.get('ADMIN_TOKEN', '')
REVIEW_QUEUE    = []   # close-date abstentions from Groq enrichment
VALIDATION_FLAGS = []  # deals flagged by validate_deal() — reviewed before any removal

import re as _re

SELF_TENDER_SIGNALS = [
    'repurchase of its common stock',
    "repurchase of the company's common stock",
    'capital return program',
    'issuer tender offer',
    'offer to purchase shares of its own',
    'offer to purchase its own',
    'return capital to shareholders',
    'return of capital to stockholders',
]

VALIDATION_MERGER_SIGNALS = [
    'agreement and plan of merger', 'merger agreement', 'definitive agreement',
    'to be acquired by', 'acquire all of the outstanding', 'entered into a merger',
]

VALIDATION_IRRELEVANT_SIGNALS = [
    'sale of', 'disposition of', 'divestiture', 'spinoff', 'spin-off', 'asset sale',
]

DEREGISTRATION_FORMS = {"25", "25-NSE", "15", "15-12B", "15-12G"}


def _name_overlap_score(name_a, name_b):
    """Jaccard similarity on word sets. >= 0.6 = same entity (self-tender signal)."""
    suffixes = {'inc','corp','ltd','llc','plc','co','company','corporation',
                'incorporated','limited','holdings','group'}
    def words(s):
        return set(w for w in _re.sub(r'[^a-z0-9 ]', '', s.lower()).split()
                   if w not in suffixes and len(w) > 1)
    a, b = words(name_a), words(name_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _get_text_for_validation(url):
    """Fetch and plain-text a filing URL for validation checks. Short timeout, best-effort."""
    try:
        r = requests.get(url, headers=EDGAR_HEADERS, timeout=10)
        time.sleep(0.12)
        if r.status_code != 200:
            return None
        from html.parser import HTMLParser
        class TE(HTMLParser):
            def __init__(self):
                super().__init__()
                self.chunks = []
            def handle_data(self, d):
                self.chunks.append(d)
        p = TE()
        p.feed(r.text)
        return ' '.join(p.chunks)
    except Exception:
        return None


def _find_announcement_filing_for_validation(cik, announced_date_str, window_days=7):
    """
    Find the 8-K / tender-offer form filed within window_days of the deal's
    announcement date. Anchored on the stored filed date — the same technique
    that fixed the 'earliest Item 1.01' bug in validate_feed.py which was
    matching decade-old unrelated filings.
    Returns (filing_date, accession, form_type, text) or None.
    """
    try:
        ann_date = datetime.strptime(announced_date_str[:10], "%Y-%m-%d")
    except Exception:
        return None
    window_start = ann_date - timedelta(days=window_days)
    window_end   = ann_date + timedelta(days=window_days)

    try:
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=EDGAR_HEADERS, timeout=10
        ).json()
        time.sleep(0.12)
    except Exception:
        return None

    recent = sub.get("filings", {}).get("recent", {})
    forms   = recent.get("form", [])
    accs    = recent.get("accessionNumber", [])
    items   = recent.get("items", [])
    dates   = recent.get("filingDate", [])
    docs    = recent.get("primaryDocument", [])

    candidates = []
    for form, acc, item, date_str, doc in zip(forms, accs, items, dates, docs):
        if not doc:
            continue
        try:
            fdate = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        if window_start <= fdate <= window_end:
            if form in ("8-K", "SC TO-T", "SC TO-I", "SC 13E-3", "SC 14D9"):
                candidates.append((date_str, acc, form, doc,
                                   abs((fdate - ann_date).days)))

    candidates.sort(key=lambda x: x[4])
    for date_str, acc, form, doc, _ in candidates:
        acc_clean = acc.replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{int(cik)}/{acc_clean}/{doc}")
        text = _get_text_for_validation(url)
        if text and any(s in text.lower() for s in VALIDATION_MERGER_SIGNALS):
            return date_str, acc, form, text
    # No merger language found — return closest candidate anyway (flagged by caller)
    if candidates:
        date_str, acc, form, doc, _ = candidates[0]
        acc_clean = acc.replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{int(cik)}/{acc_clean}/{doc}")
        text = _get_text_for_validation(url)
        return date_str, acc, form, (text or "")
    return None


def find_listed_target_ticker(filing_text, filer_ticker):
    """
    Search filing text for a listed exchange ticker that isn't the filer's own.
    Distinguishes Case 1 (OTC/private target — skip) from Case 2 (listed target
    that may be trackable — surface for manual review).
    """
    pattern = r'\((?:NYSE|NASDAQ|AMEX|NYSE\s*American):\s*([A-Z]{1,5})\)'
    matches = re.findall(pattern, filing_text or '', re.IGNORECASE)
    for m in matches:
        if m.upper() != filer_ticker.upper():
            return m.upper()
    return None


def check_filer_role(ticker, company_name, acquirer, filing_text):
    """
    Option A: checks whether extracted acquirer matches the filer's own company name
    (Jaccard >= 0.6). If yes, the filer is the acquirer not the target — flag for review.
    Option B (deal-size ratio) deferred until filer_shares is stored on deal records.
    Returns (flagged: bool, reason: str, listed_target_ticker_or_None).
    FLAG-FIRST — never auto-removes.
    """
    if acquirer and acquirer != 'Undisclosed' and company_name:
        score = _name_overlap_score(acquirer, company_name)
        if score >= 0.6:
            listed_target = find_listed_target_ticker(filing_text, ticker)
            if listed_target:
                reason = (
                    f"Filer \"{company_name}\" appears to be the ACQUIRER "
                    f"(acquirer \"{acquirer}\" matches filer name, overlap {score:.2f}). "
                    f"Real target may be trackable: {listed_target} — verify before excluding."
                )
            else:
                reason = (
                    f"Filer \"{company_name}\" appears to be the ACQUIRER "
                    f"(acquirer \"{acquirer}\" matches filer name, overlap {score:.2f}). "
                    f"Target appears non-listed — add filer to EXCLUDED_TICKERS if confirmed."
                )
            return True, reason, listed_target
    return False, '', None


def validate_deal(ticker, acquirer, cik, company_name, announced_date_str):
    """
    Runs five validation checks against a deal. Returns a list of flag dicts,
    empty if the deal is clean.

    Check 1 — SC TO-I form type (issuer self-tender = buyback, not an acquisition)
    Check 2 — Self-tender text signals + same-entity name check (Jaccard >= 0.6)
    Check 3 — Post-announcement completion signal (Form 25/15 or Item 2.01 8-K
               filed AFTER the announcement date, acquirer-mention verified)
    Check 4 — 180-day age-out (still pending > 180 days after announcement)
    Check 5 — Filer-as-acquirer detection (Option A name-match, zero network calls)
               Option B (deal-size ratio) deferred until filer_shares added to deal record.

    This is FLAG-FIRST: flags go to VALIDATION_FLAGS for review, never auto-remove.
    """
    flags = []
    now = datetime.utcnow()

    # ── Announcement filing (anchored on filed date, not "earliest Item 1.01") ──
    ann_result = _find_announcement_filing_for_validation(cik, announced_date_str)
    ann_form = ann_text = None
    if ann_result:
        _, _, ann_form, ann_text = ann_result

    # Check 1: SC TO-I form type
    if ann_form and "TO-I" in ann_form.upper():
        flags.append({
            "check": "SELF_TENDER_FORM",
            "reason": f"Form type is {ann_form} (issuer self-tender/buyback by SEC definition)",
        })

    # Check 2: self-tender text + same-entity
    if ann_text:
        text_lower = ann_text.lower()
        for sig in SELF_TENDER_SIGNALS:
            if sig in text_lower:
                flags.append({
                    "check": "SELF_TENDER_TEXT",
                    "reason": f"Filing text contains self-tender signal: \"{sig}\"",
                })
                break
        if acquirer and company_name:
            score = _name_overlap_score(acquirer, company_name)
            if score >= 0.6:
                flags.append({
                    "check": "SAME_ENTITY",
                    "reason": (f"Acquirer \"{acquirer}\" closely matches company name "
                               f"\"{company_name}\" (overlap {score:.2f} >= 0.6)"),
                })

    # Check 3: post-announcement completion signal
    try:
        ann_date = datetime.strptime(announced_date_str[:10], "%Y-%m-%d")
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=EDGAR_HEADERS, timeout=10
        ).json()
        time.sleep(0.12)
        recent   = sub.get("filings", {}).get("recent", {})
        r_forms  = recent.get("form", [])
        r_accs   = recent.get("accessionNumber", [])
        r_items  = recent.get("items", [])
        r_dates  = recent.get("filingDate", [])
        r_docs   = recent.get("primaryDocument", [])

        acq_key = (acquirer or "").lower().split()[0] if acquirer else ""

        for form, acc, item, date_str, doc in zip(r_forms, r_accs, r_items, r_dates, r_docs):
            try:
                fdate = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                continue
            if fdate <= ann_date:
                continue  # CRITICAL: only post-announcement filings

            item_str = str(item) if item else ""

            if form in DEREGISTRATION_FORMS:
                flags.append({
                    "check": "COMPLETION_DEREGISTRATION",
                    "reason": (f"Form {form} (deregistration) filed {date_str} "
                               f"after announcement {announced_date_str}, accession {acc}"),
                })

            elif form == "8-K" and "2.01" in item_str and doc:
                acc_clean = acc.replace("-", "")
                url = (f"https://www.sec.gov/Archives/edgar/data/"
                       f"{int(cik)}/{acc_clean}/{doc}")
                text = _get_text_for_validation(url)
                if text:
                    text_lower = text.lower()
                    is_irrelevant = any(s in text_lower for s in VALIDATION_IRRELEVANT_SIGNALS)
                    acq_mentioned = bool(acq_key) and acq_key in text_lower
                    if acq_mentioned and not is_irrelevant:
                        idx = text_lower.find(acq_key)
                        snippet = text[max(0,idx-80):idx+120].replace("\n"," ").strip()
                        flags.append({
                            "check": "COMPLETION_8K",
                            "reason": (f"Item 2.01 8-K filed {date_str} after announcement, "
                                       f"acquirer \"{acquirer}\" mentioned. "
                                       f"Snippet: \"...{snippet}...\""),
                        })
    except Exception as e:
        print(f"  [Validate] completion check error for {ticker}: {e}")

    # Check 4: 180-day age-out
    try:
        ann_date = datetime.strptime(announced_date_str[:10], "%Y-%m-%d")
        age_days = (now - ann_date).days
        if age_days > 180:
            flags.append({
                "check": "AGE_OUT",
                "reason": f"Announcement is {age_days} days old (> 180-day threshold)",
            })
    except Exception:
        pass

    # Check 5: filer-as-acquirer detection (Option A — name match, no network calls)
    # Option B (deal-size ratio) deferred: needs filer_shares on deal record.
    # To enable Option B later: store shares_outstanding in compute_equity_tx_fallback
    # and pass deal.get('filer_shares') here from the daily loop.
    try:
        filer_flagged, filer_reason, listed_target = check_filer_role(
            ticker=ticker,
            company_name=company_name,
            acquirer=acquirer,
            filing_text=ann_text,
        )
        if filer_flagged:
            flags.append({
                "check": "FILER_IS_ACQUIRER",
                "reason": filer_reason,
                "listed_target": listed_target,
            })
    except Exception as e:
        print(f"  [Validate] {ticker}: filer-role check error — {e}")

    return flags


@app.get("/api/comps/all")
async def get_all_comps():
    return JSONResponse(content={"comps": [], "total": 0, "status": "Dataset under EDGAR re-verification"})

@app.get("/api/comps/{ticker}")
async def get_comps(ticker: str, deal_type: str = "All Cash", spread: float = 5.0):
    return JSONResponse(content={
        "comps": [],
        "summary": {"total": 0, "closed": 0, "broken": 0, "close_rate": 0, "avg_days": 0},
        "status": "Dataset under EDGAR re-verification"
    })



@app.get("/api/admin/field-completeness")
async def field_completeness(token: str = ""):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    deals = load_cache() or []
    rows = []

    def sanitize(val):
        """Convert nan/inf floats to None so they serialize cleanly to JSON null."""
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return val

    def confident_str(val):
        """String fields: None, empty, or known placeholder strings = not confident."""
        if val is None: return False
        s = str(val).strip()
        return s not in ('TBD', 'nan', 'Undisclosed', 'not yet disclosed', '') \
               and not s.lower().startswith('of 202')

    def confident_num(val):
        """Numeric fields: None, 0, empty string, or nan/inf = not confident."""
        if val is None: return False
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)): return False
        try:
            return float(val) > 0
        except (TypeError, ValueError):
            return False

    for d in deals:
        tx_raw = sanitize(d.get("tx_value"))
        rows.append({
            "ticker":     d.get("ticker"),
            "acquirer":   {"value": d.get("acquirer"),   "confident": confident_str(d.get("acquirer"))},
            "close_date": {"value": d.get("close_date"), "confident": confident_str(d.get("close_date"))},
            "tx_value":   {"value": tx_raw, "source": d.get("tx_value_source"), "confident": confident_num(tx_raw)},
            "deal_type":  {"value": d.get("deal_type"),  "confident": confident_str(d.get("deal_type"))},
        })

    incomplete = [r for r in rows if not all(
        v["confident"] for v in [r["acquirer"], r["close_date"], r["tx_value"], r["deal_type"]]
    )]
    return JSONResponse(content={
        "total_deals": len(rows),
        "complete": len(rows) - len(incomplete),
        "incomplete": len(incomplete),
        "deals": rows,
        "needs_attention": incomplete,
    })

@app.get("/api/admin/validation-flags")
async def get_validation_flags(token: str = ""):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return JSONResponse(content={
        "flags": VALIDATION_FLAGS,
        "count": len(VALIDATION_FLAGS),
        "note": "Flag-for-review only. Nothing is auto-removed. Confirm before adding to EXCLUDED_TICKERS."
    })

@app.get("/api/admin/close-date-review-queue")
async def get_close_date_review_queue(token: str = ""):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return JSONResponse(content={"queue": REVIEW_QUEUE, "count": len(REVIEW_QUEUE)})

@app.post("/api/trigger-scan")
async def trigger_scan():
    global _scan_running
    if _scan_running:
        deals = load_cache() or []
        return JSONResponse(content={"status": "already_running", "current_deals": len(deals)})
    _scan_running = True
    asyncio.create_task(run_background_scan())
    return JSONResponse(content={"status": "started"})

@app.get("/api/refresh-stream")
async def refresh_stream():
    global _scan_running
    async def generate():
        global _scan_running
        if not _scan_running:
            _scan_running = True
            asyncio.create_task(run_background_scan())
        for tick in range(180):
            await asyncio.sleep(5)
            deals = load_cache() or []
            if not _scan_running:
                yield f"data: {json.dumps({'done': True, 'deals': deals})}\n\n"
                return
            yield f"data: {json.dumps({'current': tick*5, 'total': 900, 'deals_found': len(deals)})}\n\n"
        deals = load_cache() or []
        yield f"data: {json.dumps({'done': True, 'deals': deals})}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")



@app.get("/api/track-record/chart/{ticker}")
async def track_record_chart(ticker: str, start: str = "2024-01-01", end: str = None):
    cache_key = f"tr_chart_{ticker}"
    try:
        r = requests.get(
            f"{REDIS_URL}/get/{cache_key}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=5
        )
        result = r.json().get('result')
        if result:
            data = json.loads(result) if isinstance(result, str) else json.loads(result.get('value', '{}'))
            if data.get('prices'):
                return JSONResponse(content=data)
    except:
        pass
    end_date = end or datetime.utcnow().strftime('%Y-%m-%d')
    # Use sector ETF instead of company ticker for delisted stocks
    etf = SECTOR_ETF_MAP.get(ticker, 'SPY')
    for attempt in range(3):
        try:
            h = yf.Ticker(etf).history(start=start, end=end_date)
            if h.empty:
                time.sleep(1)
                continue
            spy = yf.Ticker("SPY").history(start=start, end=end_date)
            prices = [{"date": d.strftime('%Y-%m-%d'), "close": round(float(r['Close']), 2)} for d, r in h.iterrows()]
            spy_prices = [{"date": d.strftime('%Y-%m-%d'), "close": round(float(r['Close']), 2)} for d, r in spy.iterrows()]
            # Cache it
            payload = json.dumps({"prices": prices, "spy": spy_prices, "etf": etf})
            requests.post(
                f"{REDIS_URL}/set/{cache_key}",
                headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
                json={"value": payload},
                timeout=10
            )
            return JSONResponse(content={"prices": prices, "spy": spy_prices, "etf": etf})
        except Exception as e:
            print(f"Chart error {ticker} attempt {attempt+1}: {e}")
            time.sleep(1)
    return JSONResponse(content={"prices": [], "spy": [], "etf": etf})
@app.get("/api/spread-history/{ticker}")
async def spread_history(ticker: str, filed: str = "2024-01-01"):
    try:
        end_date = datetime.utcnow().strftime('%Y-%m-%d')
        h = yf.Ticker(ticker).history(start=filed, end=end_date)
        if h.empty:
            return JSONResponse(content={"history": [], "ticker": ticker})
        deals = load_cache() or []
        deal = next((d for d in deals if d['ticker'] == ticker), None)
        dp = deal.get('dp') if deal else None
        if not dp:
            return JSONResponse(content={"history": [], "ticker": ticker})
        history = []
        for date, row in h.iterrows():
            cp = round(float(row['Close']), 2)
            if cp > 0 and dp > 0:
                spread = round(((dp - cp) / cp) * 100, 2)
                history.append({"date": date.strftime('%Y-%m-%d'), "spread": spread, "close": cp})
        return JSONResponse(content={"history": history, "ticker": ticker, "dp": dp})
    except Exception as e:
        print(f"Spread history error {ticker}: {e}")
        return JSONResponse(content={"history": [], "ticker": ticker})

@app.get("/api/catalyst/{ticker}")
async def get_catalyst(ticker: str, filed: str = "2024-01-01", deal_type: str = "All Cash", tx_value: float = 0):
    try:
        filed_dt = datetime.strptime(filed, '%Y-%m-%d')
        today = datetime.utcnow()
        days_elapsed = (today - filed_dt).days
        catalysts = []

        # Announcement — always known
        catalysts.append({
            "label": "Announced",
            "date": filed,
            "status": "completed",
            "description": "Definitive merger agreement filed with SEC"
        })

        # HSR filing — typically 30 days after announcement
        hsr_date = filed_dt + timedelta(days=30)
        catalysts.append({
            "label": "HSR Filing",
            "date": hsr_date.strftime('%Y-%m-%d'),
            "status": "completed" if today > hsr_date else "pending",
            "description": "Hart-Scott-Rodino antitrust filing — mandatory for deals over $119.5M",
            "estimated": True
        })

        # HSR waiting period expiration — 30 days after HSR filing
        hsr_expire = hsr_date + timedelta(days=30)
        catalysts.append({
            "label": "HSR Waiting Period",
            "date": hsr_expire.strftime('%Y-%m-%d'),
            "status": "completed" if today > hsr_expire else "pending",
            "description": "DOJ/FTC 30-day review window expires — deal can proceed unless challenged",
            "estimated": True
        })

        # Shareholder vote — typically 90-120 days for mergers, faster for tender offers
        if deal_type == 'Tender Offer':
            sv_days = 45
            sv_label = "Tender Offer Expiration"
            sv_desc = "Mandatory minimum 20-business-day tender period expires"
        elif deal_type == 'Private Equity':
            sv_days = 100
            sv_label = "Shareholder Vote"
            sv_desc = "Target company shareholders vote to approve the merger agreement"
        else:
            sv_days = 110
            sv_label = "Shareholder Vote"
            sv_desc = "Target company shareholders vote to approve the merger agreement"

        sv_date = filed_dt + timedelta(days=sv_days)
        catalysts.append({
            "label": sv_label,
            "date": sv_date.strftime('%Y-%m-%d'),
            "status": "completed" if today > sv_date else "pending",
            "description": sv_desc,
            "estimated": deal_type != 'Tender Offer'
        })

        # Regulatory clearance — depends on deal size and type
        if tx_value and tx_value > 5:
            reg_days = 180
            reg_label = "Regulatory Clearance"
            reg_desc = f"Expected FTC/DOJ antitrust clearance for ${tx_value:.1f}B deal"
        else:
            reg_days = 120
            reg_label = "Regulatory Clearance"
            reg_desc = "Expected regulatory clearance — standard review timeline"

        reg_date = filed_dt + timedelta(days=reg_days)
        catalysts.append({
            "label": reg_label,
            "date": reg_date.strftime('%Y-%m-%d'),
            "status": "completed" if today > reg_date else "pending",
            "description": reg_desc,
            "estimated": True
        })

        # Outside date — typically 12-18 months, deal terminates if not closed
        outside_days = 365 if deal_type == 'Tender Offer' else 540
        outside_date = filed_dt + timedelta(days=outside_days)
        catalysts.append({
            "label": "Outside Date",
            "date": outside_date.strftime('%Y-%m-%d'),
            "status": "active",
            "description": "Deal automatically terminates if not closed by this date unless extended by mutual agreement",
            "estimated": True
        })

        # Expected close
        avg_days = {'Tender Offer': 90, 'Private Equity': 150, 'All Cash': 180, 'Cash + Stock': 220}
        close_days = avg_days.get(deal_type, 180)
        close_date = filed_dt + timedelta(days=close_days)
        days_to_close = (close_date - today).days
        catalysts.append({
            "label": "Expected Close",
            "date": close_date.strftime('%Y-%m-%d'),
            "status": "completed" if today > close_date else "pending",
            "description": f"Estimated close based on {deal_type} deal average of {close_days} days · {max(0, days_to_close)} days remaining",
            "estimated": True
        })

        return JSONResponse(content={
            "catalysts": catalysts,
            "days_elapsed": days_elapsed,
            "current_stage": next((c["label"] for c in reversed(catalysts) if c["status"] == "completed"), "Announced")
        })
    except Exception as e:
        print(f"Catalyst error {ticker}: {e}")
        return JSONResponse(content={"catalysts": [], "days_elapsed": 0, "current_stage": "Unknown"})

@app.get("/api/implied-probability/{ticker}")
async def implied_probability(ticker: str):
    try:
        deals = load_cache() or []
        deal = next((d for d in deals if d['ticker'] == ticker), None)
        if not deal:
            return JSONResponse(content={"probability": None, "error": "Deal not found"})
        cp = deal.get('cp')
        dp = deal.get('dp')
        bp = deal.get('break_price')
        if not cp or not dp or not bp:
            return JSONResponse(content={"probability": None, "error": "Insufficient data"})
        prob = round(((cp - bp) / (dp - bp)) * 100, 1)
        prob = max(0, min(99.9, prob))
        if cp < bp:
            return JSONResponse(content={
                "probability": round(prob, 1),
                "signal": "Distressed",
                "color": "red",
                "current_price": cp,
                "deal_price": dp,
                "break_price": bp,
                "method": deal.get('break_price_method', 'historical'),
                "note": "Stock trading below break price — deal may be in distress"
            })
        if prob >= 90:
            signal = "Very High"
            color = "green"
        elif prob >= 75:
            signal = "High"
            color = "teal"
        elif prob >= 55:
            signal = "Moderate"
            color = "amber"
        else:
            signal = "Low"
            color = "red"
        return JSONResponse(content={
            "probability": prob,
            "signal": signal,
            "color": color,
            "current_price": cp,
            "deal_price": dp,
            "break_price": bp,
            "method": deal.get('break_price_method', 'historical')
        })
    except Exception as e:
        print(f"Implied probability error {ticker}: {e}")
        return JSONResponse(content={"probability": None, "error": str(e)})
@app.post("/api/clear-cache")
async def clear_cache():
    """Emergency cache clear - nukes all Redis deals so next scan starts clean."""
    try:
        requests.post(
            f"{REDIS_URL}/del/{CACHE_KEY}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=10
        )
        return JSONResponse(content={"status": "cache cleared"})
    except Exception as e:
        return JSONResponse(content={"status": "error", "detail": str(e)})

@app.post("/api/create-checkout-session")
async def create_checkout_session(request: Request):
    try:
        body = await request.json()
        user_email = body.get('email', '')
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            mode='subscription',
            success_url=f'{BASE_URL}/?session_id={{CHECKOUT_SESSION_ID}}&subscribed=true',
            cancel_url=f'{BASE_URL}/?cancelled=true',
            customer_email=user_email if user_email else None,
        )
        return JSONResponse(content={'url': session.url})
    except Exception as e:
        print(f"Stripe error: {e}")
        return JSONResponse(content={'error': str(e)}, status_code=500)

@app.get("/api/check-subscription")
async def check_subscription(email: str = ''):
    if not email:
        return JSONResponse(content={'subscribed': False})
    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return JSONResponse(content={'subscribed': False})
        customer = customers.data[0]
        subscriptions = stripe.Subscription.list(
            customer=customer.id,
            status='active',
            limit=1
        )
        subscribed = len(subscriptions.data) > 0
        return JSONResponse(content={'subscribed': subscribed})
    except Exception as e:
        print(f"Subscription check error: {e}")
        return JSONResponse(content={'subscribed': False})
@app.post("/api/refresh")
async def refresh_deals():
    global _scan_running
    if _scan_running:
        return JSONResponse(content={"deals": load_cache() or []})
    _scan_running = True
    asyncio.create_task(run_background_scan())
    await asyncio.sleep(2)
    return JSONResponse(content={"deals": load_cache() or []})