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
import ast
import json
import math
import random
import time
from contextlib import asynccontextmanager
import stripe
from find_announcement import find_announcement_8k_backward
from deal_direction import (check_direction, direction_report,
                            DIRECTION_ENFORCING, VERDICT_TARGET)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID', '')
CLERK_SECRET_KEY = os.environ.get('CLERK_SECRET_KEY', '')
# Stripe sends the customer back here after checkout, so a stale host is a
# dead end on the paid path, not a cosmetic error. meridian-v2-production-cffa
# stopped resolving — Railway's edge answers it with "Application not found".
BASE_URL = os.environ.get('BASE_URL', 'https://meridianarb.up.railway.app')

# ─── DEAL STRUCTURES (TEMPORARY, HAND-VERIFIED) ──────────────────────────────
# Automatic extraction replaces this table later. It exists because the display
# and the thirteen barriers have to be proven against numbers already known to
# be correct — a barrier tuned against extracted values can only tell you the
# extractor and the barrier agree, not that either is right.
# Every entry carries the accession number it was read from. Nothing goes in
# here that a filing does not prove.
DEAL_STRUCTURES = {
    'GSAT': {
        'cash': 90.00,
        'ratio': 0.3210,
        'acquirer_ticker': 'AMZN',
        'cash_cap': 0.40,
        'collar_high': 90.00,
        'structure_hint': 'ELECTION_CAPPED',
        'source': 'hand-verified from 8-K 0001140361-26-014528',
    },
}

# Gates the display change only. False means the blended value is computed and
# logged but dp, sp_pct and everything the frontend reads stay untouched.
DEAL_PRICING_ENFORCING = True

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
    # The read and the write disagreed, and the disagreement was invisible: the
    # write posted {"value": ..., "ex": ...} as a JSON body, Upstash stored that
    # envelope verbatim, and the read did json.loads() on it and looked for
    # 'ticker_map' at the top level. It found the envelope's keys instead, so
    # every start fell through and re-fetched all 10,391 tickers from SEC while
    # the write went on reporting nothing at all.
    #
    # Same shape as redis_set: an operation that looks like it works, with no
    # check that it did. HIT and MISS are both logged now, so a silent
    # regression here has to say so.
    if not REDIS_URL or not REDIS_TOKEN:
        print("[SEC] Ticker map cache MISS — no Redis configured")
    else:
        try:
            r = requests.get(
                f"{REDIS_URL}/get/{cache_key}",
                headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
                timeout=10
            )
            result = r.json().get('result')
            if not result:
                print(f"[SEC] Ticker map cache MISS — key {cache_key} empty or expired")
            else:
                # Upstash returns the stored string. It is the payload itself,
                # not a wrapper around it.
                data = json.loads(result) if isinstance(result, str) else result
                if isinstance(data, dict) and data.get('ticker_map'):
                    SEC_TICKER_MAP = data['ticker_map']
                    SEC_CIK_MAP    = data.get('cik_map', {})
                    print(f"[SEC] Ticker map cache HIT: {len(SEC_TICKER_MAP)} tickers "
                          f"from Redis, SEC not called")
                    return
                print(f"[SEC] Ticker map cache MISS — stored value has no "
                      f"ticker_map (keys: {list(data)[:5] if isinstance(data, dict) else type(data).__name__})")
        except Exception as e:
            print(f"[SEC] Ticker map cache MISS — read error: {e}")

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

        # ── Write to Redis: RAW payload in the body ────────────────────────
        # The URL path cannot carry this — that part was always right. What was
        # wrong is the shape: json={"value": ..., "ex": ...} makes Upstash store
        # the envelope, which the reader above then cannot see through. The
        # payload goes in the body as-is, and the TTL is a query parameter,
        # which is where Upstash REST actually reads it from.
        if REDIS_URL and REDIS_TOKEN:
            try:
                payload = json.dumps({'ticker_map': ticker_map, 'cik_map': cik_map})
                w = requests.post(
                    f"{REDIS_URL}/set/{cache_key}?EX=86400",
                    headers={
                        "Authorization": f"Bearer {REDIS_TOKEN}",
                        "Content-Type": "text/plain",
                    },
                    data=payload.encode('utf-8'),
                    timeout=20
                )
                if w.status_code == 200:
                    print(f"[SEC] Ticker map cached: {len(payload):,} bytes, 24h TTL")
                else:
                    print(f"[SEC] Ticker map cache WRITE FAILED: HTTP "
                          f"{w.status_code} — {w.text[:200]}. Next start will "
                          f"re-fetch from SEC.")
            except Exception as e:
                print(f"[SEC] Ticker map cache WRITE FAILED (non-fatal): {e}")

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
    """
    Write the feed to Redis. The payload goes in the request BODY.

    It used to go in the URL path, percent-encoded. That works while the cache
    is small and fails silently once it is not: the enriched feed is 100,000+
    characters encoded, which no proxy will accept as a request line. The write
    returned a non-200, redis_set returned False, and save_cache ignored the
    return value and printed "Cache saved" anyway.

    What that produced in production was subtle. The pre-enrichment save
    (~47,000 chars) was small enough to land; the final save carrying pricing,
    commitment, outside_date, direction and gate (~93,000) was not. So every
    scan wrote a feed with correct prices and no enrichment, and the deals that
    still had readings were the ones rolling_merge carried over from the last
    write that fit. GSAT lost its blended pricing this way, along with 18 other
    deals' commitment and outside-date readings.

    fetch_sec_ticker_map already learned this — see the body POST there and its
    comment about URL-path length. This is the same fix on the write that
    matters more.
    """
    if not REDIS_URL or not REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(deals)
        # The RAW payload is the body. Upstash REST sets the key to the request
        # body verbatim, so what lands in Redis is byte-identical to what the
        # URL-path form used to store — redis_get needs no change and there is
        # nothing to migrate. Wrapping it as {"value": ...} would have stored
        # the wrapper too, and the reader would hand back the envelope.
        r = requests.post(
            f"{REDIS_URL}/set/{CACHE_KEY}",
            headers={
                "Authorization": f"Bearer {REDIS_TOKEN}",
                "Content-Type": "text/plain",
            },
            data=payload.encode('utf-8'),
            timeout=30
        )
        ok = r.status_code == 200
        print(f"Redis set: {r.status_code} — {len(deals)} deals, "
              f"{len(payload):,} bytes{'' if ok else ' — WRITE FAILED'}")
        if not ok:
            print(f"  Redis set body: {r.text[:300]}")
        return ok
    except Exception as e:
        print(f"Redis set error: {e}")
        return False

def append_snapshot(deal, sp_pct, score, risk):
    """
    Appends one timestamped snapshot to spread_history and score_history.
    FIFO cap of 365 entries. Index 0 (first-detection anchor) is ALWAYS preserved —
    never aged out. Called on pre-pandas source dicts so lists never enter the DataFrame.
    """
    now_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    CAP = 365

    sh = deal.get('spread_history')
    if not isinstance(sh, list):
        sh = []
    sh.append({'t': now_str, 'sp': round(sp_pct, 2), 'cp': deal.get('cp')})
    if len(sh) > CAP:
        sh = [sh[0]] + sh[-(CAP - 1):]  # preserve index 0, FIFO rest
    deal['spread_history'] = sh

    sch = deal.get('score_history')
    if not isinstance(sch, list):
        sch = []
    sch.append({'t': now_str, 'sc': score, 'risk': risk})
    if len(sch) > CAP:
        sch = [sch[0]] + sch[-(CAP - 1):]
    deal['score_history'] = sch


def save_cache(records):
    if not records:
        return
    try:
        # Fields that must never enter pandas — can't be round-tripped as lists.
        # Redis is the authoritative store for history arrays.
        LIST_FIELDS   = {'spread_history', 'score_history'}
        FROZEN_FIELDS = {'sp_pct_at_detection', 'score_at_detection', 'risk_at_detection'}

        # Build ticker-keyed lookup of pre-pandas source dicts (minus _filing_text).
        # append_snapshot runs here — before pandas — so the fresh entry is in
        # source_by_ticker and survives the merge back onto post-pandas dicts.
        source_by_ticker = {}
        for r in records:
            t = r.get('ticker')
            if t:
                source_by_ticker[t] = {k: v for k, v in r.items() if k != '_filing_text'}

        # Step 0: restore prior history BEFORE appending.
        #
        # source_by_ticker is built from the fresh scan records, which carry no
        # history at all. So append_snapshot was appending to an empty list every
        # hour and writing back a single entry -- months of snapshots overwritten,
        # one at a time. Redis holds the only accumulated copy.
        #
        # Third time this exact shape has appeared: the detection-value freeze
        # and the direction verdicts failed the same way. A record rebuilt from
        # scratch has none of the state the code assumes is there.
        try:
            _prior_hist = {}
            for _old in (redis_get() or []):
                _t = _old.get('ticker')
                if not _t:
                    continue
                _prior_hist[_t] = {
                    'spread_history': _old.get('spread_history'),
                    'score_history': _old.get('score_history'),
                }
            _restored = 0
            for ticker, d in source_by_ticker.items():
                old = _prior_hist.get(ticker)
                if not old:
                    continue
                for f in LIST_FIELDS:
                    if isinstance(old.get(f), list) and old[f]:
                        d[f] = list(old[f])
                        _restored += 1
            if _restored:
                print(f"[History] restored {_restored} prior history arrays before appending")
        except Exception as _he:
            print(f"[History] could not restore prior history: {_he}")

        # Step 1: append snapshots to pre-pandas source dicts.
        for ticker, d in source_by_ticker.items():
            sp = d.get('sp_pct')
            sc = d.get('score')
            ri = d.get('risk')
            if sp is not None and sc is not None and ri is not None:
                append_snapshot(d, sp, sc, ri)

        # Step 2: pandas handles flat scalars only — list fields excluded.
        scalar_records = [
            {k: v for k, v in d.items() if k not in LIST_FIELDS}
            for d in source_by_ticker.values()
        ]
        df = pd.DataFrame(scalar_records).drop_duplicates(subset=['ticker'])
        df = df[df['cp'].notna() & (df['cp'] > 0)]
        df['sp_pct'] = pd.to_numeric(df['sp_pct'], errors='coerce').fillna(0)
        df = df.sort_values('sp_pct', ascending=False).reset_index(drop=True)
        df = df.where(pd.notnull(df), None)
        clean = df.to_dict(orient='records')

        # Step 3: merge list fields and frozen fields back from source_by_ticker
        # onto the post-pandas scalar dicts, right before Redis.
        # append_snapshot already ran in Step 1 so source_by_ticker has the
        # fresh snapshot — this merge never clobbers it.
        for d in clean:
            ticker = d.get('ticker')
            src = source_by_ticker.get(ticker, {})
            for f in LIST_FIELDS:
                if isinstance(src.get(f), list):
                    d[f] = src[f]
            # Write-once belt-and-suspenders: if frozen field already set, preserve it.
            # Carried deals are protected by Redis persistence; this guard covers the
            # edge case of a re-detected deal whose old value is still in source_by_ticker.
            for f in FROZEN_FIELDS:
                if src.get(f) is not None:
                    d[f] = src[f]

        if len(clean) >= 3:
            merged = rolling_merge(clean)
            # The return value is checked. Ignoring it is what let a failed
            # Redis write print "Cache saved" for days while the enrichment
            # silently never persisted.
            _redis_ok = redis_set(merged)
            if REDIS_URL and REDIS_TOKEN and not _redis_ok:
                print(f"[Cache] REDIS WRITE FAILED — {len(merged)} deals were NOT "
                      f"persisted. The live feed is now stale and any enrichment "
                      f"in this scan is lost.")
            try:
                tmp = CACHE_FILE + '.tmp'
                # Exclude list fields from CSV — pd can't round-trip them.
                # Redis is the authoritative store for history arrays.
                _csv_exclude = {'spread_history', 'score_history'}
                _csv_rows = [{k: v for k, v in d.items() if k not in _csv_exclude} for d in merged]
                pd.DataFrame(_csv_rows).to_csv(tmp, index=False)
                os.replace(tmp, CACHE_FILE)
            except:
                pass
            _where = 'Redis + CSV' if _redis_ok else ('CSV only' if not (REDIS_URL and REDIS_TOKEN) else 'CSV ONLY — REDIS FAILED')
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Cache saved: {len(merged)} deals ({len(clean)} from scan, {len(merged)-len(clean)} carried over) [{_where}].")
    except Exception as e:
        print(f"save_cache error: {e}")


# How long a deal can be absent from EDGAR scan results before rolling_merge drops it.
# 36 hours = survives transient upstream flakiness (EDGAR timeouts, Yahoo rate limits)
# without losing real open deals. Completion detection handles actual closed deals.
ROLLING_CARRY_MAX_AGE_HOURS = 36

def rolling_merge(new_deals):
    """
    Merges new scan results with existing cache.
    - New deals always included with fresh prices
    - Deals missing from this scan but in cache are kept IF:
      1. They were seen within the last ROLLING_CARRY_MAX_AGE_HOURS hours
      2. Their spread hasn't moved more than 15% in either direction
    - Deals missing for more than ROLLING_CARRY_MAX_AGE_HOURS are dropped
    - Deals whose stock has crashed more than 15% below deal price are dropped immediately
    """
    # Restore the true detection values FIRST, from the CSV rather than Redis.
    #
    # These were previously restored from redis_get() below, which meant the
    # freeze silently stopped working whenever Redis did -- and Redis fails
    # locally, so the bug survived every local test. The CSV is always present.
    #
    # Every scan rebuilds a deal from scratch and sets sp_pct_at_detection to
    # the CURRENT spread, so a deal detected in January was carrying July's
    # number. These three fields are the entire basis of the forward track
    # record: if they move, there is no record.
    _frozen = ('sp_pct_at_detection', 'score_at_detection', 'risk_at_detection')
    try:
        _prior_rows = load_cache() or []
        _prior = {r.get('ticker'): r for r in _prior_rows if r.get('ticker')}
        for d in new_deals:
            old = _prior.get(d.get('ticker'))
            if not old:
                continue  # genuinely new deal -- today's values ARE the detection values
            for f in _frozen:
                v = old.get(f)
                if v is not None and v != '':
                    d[f] = v
    except Exception as e:
        print(f"[Freeze] could not restore detection values: {e}")

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

            # Drop if missing for more than ROLLING_CARRY_MAX_AGE_HOURS
            if age_hours > ROLLING_CARRY_MAX_AGE_HOURS:
                print(f"  Rolling drop: {deal['ticker']} — missing for {age_hours:.1f}h (>{ROLLING_CARRY_MAX_AGE_HOURS}h threshold)")
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
    'AVNS': 'American Industrial Partners',  # confirmed 4/14/26 8-K — $25/share all-cash PE take-private
}

# Hand-verified unaffected prices, where the automatic lookback is provably
# reading deal speculation rather than the undisturbed price.
#
# get_break_price takes the last close before the filing date. For a deal that
# leaked, or one preceded by a public sale process, that is the most
# contaminated print available rather than the least. The pattern is already
# recorded by hand elsewhere in this project: worksheet.csv notes AMPS's premium
# as measured "to the Oct 15 2024 unaffected close, before the strategic review
# announcement", and VOXX entered at $8.00 — a NEGATIVE premium to a $7.50 deal
# — because four months of a public process had already lifted it off $2.85.
#
# These are overrides, not a detector. A 150-day scan across the twelve live
# deals flags seven as elevated into their announcement, and the price series
# alone cannot say which of those are leaks and which are ordinary business
# momentum — GSAT and WBD both roughly tripled in a year on their own news.
# Automating this would replace one wrong number with another in most cases, so
# each entry here is a deal whose series was read by hand.
VERIFIED_UNAFFECTED_PRICES = {
    # AES traded a 13.28-14.39 range through January 2026, broke above it on
    # 2026-02-03 and never returned, closing at 16.87 the session before the
    # 8-K. It then fell 17.8% on the announcement itself, which is what a
    # disappointing definitive agreement does to a speculative price. 13.75 is
    # the 2026-01-23 close, inside the quiet range and before the break.
    'AES': 13.75,
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
    'TBPH',  # temporary — CVR deal (Zymeworks, $17/share cash + contingent value right), model doesn't handle CVR spread/close-date correctly yet
    'JHG',   # Closed June 30 2026, cashed out at $52/share, delisted from NYSE
    'GHXI',  # Gores Holdings XI is a SPAC. The name filter missed it because it
             # reads "Holdings" rather than "Acquisition Corp". Gores runs a
             # numbered series, so the whole family will recur.
    'FSK',   # FS KKR Capital Corp is a BDC that ACQUIRES other BDCs (FSKR 2021,
             # CCT 2018), not a target. Enrichment reads its external manager KKR
             # as the "acquirer." The direction check returned UNCLEAR on one run
             # and TARGET on the next for the same filing, so the model is not
             # reliable here and this needs a hard exclusion.
    'RKLB',  # Rocket Lab is the ACQUIRER of Iridium (IRDM), not a target — ingested from
             # its own merger 8-K. Entered at -7.85% spread (target above offer, structurally
             # impossible) with break price 44% above market. IRDM is the deal worth tracking.
}
SECTOR_ETF_MAP = {
    'CACC':'XLF','NTCT':'XLK','NUAN':'XLK','SGEN':'XLV','CCXI':'XLV',
    'AZPN':'XLK','QDEL':'XLV','ONCE':'XLV','ARRY':'XLV','FMBI':'XLF',
    'NTRA':'XLV','EPAY':'XLF','GTES':'XLI','PING':'XLK','PCTY':'XLK',
    'COUP':'XLK','SAVE':'XTN','CHNG':'XLV','SGFY':'XLV','IRBT':'XLK',
    'ATVI':'XLK','ACI':'XLP',
}
# How far back a search reaches. 548 days is not arbitrary — it is the same
# horizon as the age gate below, which drops any deal whose announcement is more
# than 548 days old as "likely closed". A search window wider than the gate
# spends the 300-result budget on filings that are discarded on arrival.
DEAL_SEARCH_LOOKBACK_DAYS = 548

# Tomorrow, not today. EDGAR timestamps in Eastern time while the scan computes
# in UTC, so for several hours a day "today" excludes filings already public.
DEAL_SEARCH_FORWARD_BUFFER_DAYS = 1

# The search phrases. Dates are NOT baked in here — see edgar_queries().
#
# They used to be. Every one of these carried a literal enddt, the newest of
# which was 2026-07-24, so by 2026-08-27 no deal announced in the preceding 34
# days could be detected at all and the blind spot widened by a day per day.
# Nothing failed and nothing logged; the feed simply stopped seeing new deals.
# The startdt values were stale in the mirror-image way: fixed at 2024-01-01,
# 2025-06-01 and 2025-10-01, they widened forever, filling a fixed 300-result
# budget with filings the age gate discards.
EDGAR_QUERY_PHRASES = [
    {'type': 'All Cash',       'q': '%22definitive+agreement%22+%22per+share+in+cash%22',              'forms': '8-K'},
    {'type': 'All Cash',       'q': '%22merger+agreement%22+%22per+share+in+cash%22',                   'forms': '8-K'},
    {'type': 'Cash + Stock',   'q': '%22definitive+agreement%22+%22cash+and+stock%22',                  'forms': '8-K'},
    {'type': 'Private Equity', 'q': '%22definitive+agreement%22+%22per+share+in+cash%22+%22sponsor%22', 'forms': '8-K'},
    {'type': 'Tender Offer',   'q': '%22tender+offer%22+%22per+share%22+%22definitive+agreement%22',    'forms': '8-K'},
    # Merger proxies. The proxy itself is unparseable (300+ pages, terms buried),
    # so path B resolves each hit back to its announcement 8-K and parses that.
    # Catches cash deals whose announcement 8-K our phrase queries missed.
    {'type': 'All Cash',       'q': '%22per+share+in+cash%22+%22merger+agreement%22',                   'forms': 'DEFM14A'},
]


def edgar_queries(now=None):
    """
    The search URLs with their window computed from today.

    Built per scan rather than at import, so a process that stays up for weeks
    does not drift back into the same blind spot a shorter interval at a time.
    """
    now = now or datetime.utcnow().date()
    startdt = (now - timedelta(days=DEAL_SEARCH_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    enddt = (now + timedelta(days=DEAL_SEARCH_FORWARD_BUFFER_DAYS)).strftime('%Y-%m-%d')
    return [
        {'type': p['type'],
         'url': ('https://efts.sec.gov/LATEST/search-index?q=' + p['q'] +
                 '&forms=' + p['forms'] +
                 '&dateRange=custom&startdt=' + startdt + '&enddt=' + enddt +
                 '&from={start}&size=100')}
        for p in EDGAR_QUERY_PHRASES
    ]

# FALLBACK_DEALS eliminated. No hardcoded deals. Zero real deals > fake deals.



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
    """
    What kind of buyer this is, read from the BUYER.

    `deal_type` is accepted and deliberately not consulted. It used to short
    -circuit the whole function -- `if deal_type == 'Private Equity': return
    'Private Equity'` -- which made this field inherit a verdict from a field
    that is itself unvalidated and unlabelled. GSAT reached production as
    `acquirer_type: Private Equity` with **Amazon** as the acquirer, because its
    deal_type had been set to Private Equity by whichever EDGAR query matched
    first. One unchecked field propagated into a second, and the second looked
    like an independent judgement.

    The parameter stays so call sites do not move, and because removing it would
    hide that this dependency was once here.
    """
    if not acquirer or str(acquirer).strip().lower() in ('', 'undisclosed', 'none'):
        # No buyer named, so no honest verdict. 'Strategic' was the old default
        # and it is a claim, not an absence.
        return 'Unknown'
    pe_kw = ['capital','partners','equity','ventures','holdings','fund','blackstone','kkr','apollo','carlyle','vista','thoma','francisco','advent','permira','clearlake','general atlantic','arcline']
    if any(kw in acquirer.lower() for kw in pe_kw): return 'Private Equity'
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
    # A hand-verified unaffected price always wins, the way VERIFIED_ACQUIRERS
    # and VERIFIED_TX_VALUES do. The lookback below cannot see a leak.
    if ticker in VERIFIED_UNAFFECTED_PRICES:
        return VERIFIED_UNAFFECTED_PRICES[ticker]
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
# ─── TIME TO CLOSE, AND WHAT DEPENDS ON IT ───────────────────────────────────
# Filings state the expected close as a period, not a day: "Q3 2026",
# "second half 2026", "mid-to-late 2027". Every qualifier below resolves to the
# LAST day it can mean, so a period never resolves earlier than the period
# allows. A bare year is a period too, and ends in December.
_CLOSE_PERIOD_END = {
    'first quarter': (3, 31),  'q1': (3, 31),
    'second quarter': (6, 30), 'q2': (6, 30),
    'third quarter': (9, 30),  'q3': (9, 30),
    'fourth quarter': (12, 31),'q4': (12, 31),
    'first half': (6, 30),     'h1': (6, 30),
    'second half': (12, 31),   'h2': (12, 31),
    'early': (3, 31),
    'mid': (6, 30),
    'late': (12, 31),
}


def parse_close_date(close_date):
    """
    The expected-close text as a date, or None.

    The rule that matters: a year is only ever combined with a qualifier from
    ITS OWN clause. The previous reader took the year from the first match in
    the string and the month from a keyword chain scanning the whole string, so
    AES's "late 2026 or early 2027" produced the year of the first clause and
    the month of the second — 31 March 2026, a date matching neither reading and
    five months in the past on a live deal.

    Each year token here sees only the text between the previous year token and
    itself, which makes that combination impossible to express. Where a string
    names several periods, the LATEST resulting date wins: "late 2026 or early
    2027" is a range, and the later bound is what a deadline-conscious reader
    should be shown. Nothing is ever synthesised between two stated periods.
    """
    if close_date is None:
        return None
    s = str(close_date).lower().strip()
    if s in ('', 'tbd', 'nan', 'none', 'not yet disclosed', 'not disclosed'):
        return None

    # An exact date, where a tender-offer expiration or a hand-verified entry
    # supplied one. No period logic applies.
    m = re.search(r'(20\d{2})-(\d{1,2})-(\d{1,2})', s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            return None

    years = list(re.finditer(r'20\d{2}', s))
    if not years:
        return None

    best, clause_start = None, 0
    for ym in years:
        clause = s[clause_start:ym.start()]   # this year's clause, and only this one
        clause_start = ym.end()
        # Within one clause a compound like "mid-to-late" names both bounds.
        # The later one governs, for the same reason the later clause does.
        end = None
        for kw, md in _CLOSE_PERIOD_END.items():
            if kw in clause and (end is None or md > end):
                end = md
        month, day = end if end else (12, 31)
        try:
            d = datetime(int(ym.group(0)), month, day).date()
        except ValueError:
            continue
        if best is None or d > best:
            best = d
    return best


def days_to_close(close_date, now=None):
    """Days from today to the expected close. Negative when it has passed."""
    d = parse_close_date(close_date)
    if not d:
        return None
    return (d - (now or datetime.utcnow().date())).days


# Beyond this the stated period is not a close estimate any more, it is a parse
# artifact, and annualizing against it manufactures a number.
ANNUALIZE_MAX_DAYS = 1460

# Below this, do not annualize at all.
#
# Annualizing assumes the capital can be redeployed into a comparable position
# when the deal closes and keep earning at that rate. Inside a month that
# assumption stops holding: there is no reliable supply of merger-arb positions
# to roll into on a weekly cadence, so the figure describes a return nobody can
# actually compound. The arithmetic also turns brittle — at 30 days the
# multiplier is 12x, at 5 days it is 73x, and at 1 day it is 365x, so a spread
# that is mostly bid-ask noise becomes the largest number on the page. GBCS,
# one day from its outside date on a 6.09% spread, annualized to 2,222%.
#
# 30 rather than 20: one month is where the redeployment story stops being
# arguable, and the round boundary is easier to explain to a reader than a
# threshold tuned to make a particular deal look sensible.
#
# This is a FLOOR, not a cap. Nothing is clamped to a maximum — a genuine 80%
# annualized return on a 34-day close is real and gets printed. Clamping is what
# the probability endpoint used to do, and it converted a sign error into a
# confident-looking 99.9%; the lesson was to refuse the number, not to bend it.
ANNUALIZE_MIN_DAYS = 30


def annualized_spread(spread_pct, days):
    """
    The spread scaled to a year by the deal's OWN time to close, or None.

    This previously divided by a hardcoded 180 for every deal, which made the
    result the gross spread times 2.028 and carried no time information at all —
    the one thing an annualized figure exists to carry. It inverted the ranking
    of the live feed: NATH printed below CZR while actually earning more than
    twice as much per unit time.

    None rather than a fallback constant. A deal whose close date is unknown
    (GBCS, APGE both carry TBD) or already passed has no honest annualization,
    and printing one anyway is what the old constant did.
    """
    if spread_pct is None or days is None:
        return None
    if days <= 0 or days > ANNUALIZE_MAX_DAYS:
        return None
    if days < ANNUALIZE_MIN_DAYS:
        # Too close to annualize honestly. The caller shows the raw spread and
        # the days remaining, which is the whole of what is known.
        return None
    return round(spread_pct * 365 / days, 2)


def resolve_tx_value(ticker, extracted, extracted_source):
    """
    The transaction value to use, and where it came from.

    A hand-verified entry always wins, which is how VERIFIED_ACQUIRERS already
    behaves and what its documentation states. The previous guard read
    `if ticker in VERIFIED_TX_VALUES and not tx_value`, applying the verified
    number ONLY where extraction had failed — so WBD's $77.72B equity
    approximation beat its verified $110B enterprise value. That is a 29% error
    on a field that feeds the reverse-fee percentage and three regulatory
    thresholds, and it inverted the intended precedence exactly.
    """
    if ticker in VERIFIED_TX_VALUES:
        return VERIFIED_TX_VALUES[ticker], 'verified_hardcode'
    return extracted, extracted_source


def cap_expected_close(close_date, outside):
    """
    The expected close, bounded by the contractual deadline.

    Returns (date, capped_to) where capped_to is the outside date if the cap
    bound and None otherwise. A deal cannot close after a deadline it cannot
    pass, so where management guidance resolves past one, the deadline is the
    later of the two dates that can actually happen.

    NOT applied to an ELECTIVE extension. There the reported date is the BASE
    deadline and a party may push it out by electing, so guidance landing after
    it is not impossible — OGN guides to early 2027 against a 2027-01-26 base
    that can be extended to 2027-04-26, and capping would invent a constraint
    the agreement does not impose.

    Applied to AUTOMATIC extensions because the date reported for those is
    already the outermost the extension machinery reaches, and to agreements
    with no extension clause at all, where the date is simply fixed.

    Four deals reached this state through no fault of their guidance: the
    end-of-period convention in parse_close_date resolves "H2 2026" to 31
    December, while NATH's deadline is 20 October, which is inside H2. The
    guidance and the contract agree; only the point estimate disagreed.
    """
    expected = parse_close_date(close_date)
    if not expected or not isinstance(outside, dict):
        return expected, None
    od = parse_close_date(outside.get('date'))
    if not od or outside.get('extension_type') == 'elective':
        return expected, None
    if expected <= od:
        return expected, None
    return od, od.isoformat()


# A close date the model produced must still be a possible close date. BWMN
# carried "Q2 2026" on a deal announced 2026-08-10 — six weeks after that
# quarter ended — and nothing in the pipeline objected.
ENRICHED_CLOSE_MAX_DAYS = 1260          # ~3.5 years past announcement


def validate_close_date(cd, announced, now=None):
    """
    A model-produced close date, or None with the reason it was refused.

    Three ways to fail, and all three were reachable:
      unreadable  -- the phrase does not resolve to a date at all
      backwards   -- it resolves BEFORE the deal was announced
      implausible -- it resolves further out than any merger horizon

    A blank close date is honest. A fabricated one is not, and the whole
    positioning of this project rests on that difference — "nothing ships unless
    a real EDGAR filing proves it" cannot coexist with an unchecked model output
    written straight to the cache.
    """
    if not cd or not isinstance(cd, str):
        return None, 'empty'
    cd = cd.strip()
    if cd.lower() in ('null', 'none', 'tbd', 'unknown', 'not disclosed'):
        return None, 'no date offered'
    resolved = parse_close_date(cd)
    if not resolved:
        return None, f'unreadable: {cd!r} resolves to no date'
    try:
        ann = datetime.strptime(str(announced)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return cd, None                  # no anchor to judge against; let it stand
    if resolved < ann:
        return None, (f'backwards: {cd!r} resolves to {resolved}, before the '
                      f'{ann} announcement')
    if (resolved - ann).days > ENRICHED_CLOSE_MAX_DAYS:
        return None, (f'implausible: {cd!r} resolves to {resolved}, '
                      f'{(resolved - ann).days} days past announcement')
    return cd, None


def validate_enriched_acquirer(name, filing_text, target_name):
    """
    A model-produced acquirer name, or None with the reason it was refused.

    The existing guard only compared the name against the TARGET's name, which
    catches the model returning the target and nothing else. It never asked
    whether the name appears in the filing at all — so a plausible-sounding
    company the model supplied from its own knowledge would have been stored
    with no filing behind it.

    Matching on the first significant word rather than the whole string: filings
    write "Prysmian S.p.A." where the model returns "Prysmian", and demanding an
    exact match would refuse correct answers.
    """
    if not name or not isinstance(name, str) or len(name.strip()) < 3:
        return None, 'empty'
    name = name.strip()
    if name.lower() in ('null', 'none', 'unknown'):
        return None, 'no acquirer offered'
    stop = {'inc', 'corp', 'ltd', 'llc', 'the', 'and', 'of', 'co', 'group',
            'holdings', 'company', 'plc', 'sa', 'nv', 'ag'}
    tgt = set((target_name or '').lower().split()) - stop
    got = set(re.sub(r'[^a-z0-9 ]', ' ', name.lower()).split()) - stop
    if not got:
        return None, 'name is all stop words'
    # Two guards, because the inherited one only fired on a two-word overlap and
    # a single-word target slipped straight through: "Atkore Inc." offered as the
    # acquirer of Atkore Inc. reduces to {'atkore'} on both sides, an overlap of
    # one, and was accepted.
    if got <= tgt or len(tgt & got) >= 2:
        return None, f'{name!r} matches the target company name'
    # The decisive check: does it appear in the document?
    hay = (filing_text or '').lower()
    if hay and not any(w in hay for w in got if len(w) > 3):
        return None, f'{name!r} does not appear anywhere in the filing text'
    return name, None


def blended_governs(deal):
    """
    The blended value where one exists and its barriers passed, else None.

    A holder of a cash-and-stock deal receives the blended value. The headline
    in the filing is what the acquirer announced, and for GSAT that is $90.00
    against $87.32 actually received — so a spread measured off the headline is
    measured against a price nobody is paid.

    One function decides this for sp_pct, ann, the risk band and the dashboard
    sort, so they cannot disagree the way they did: the deal card recomputed the
    spread off blended and showed 6.05%, while the ticker, the annualized
    figure, the position-size table and /api/deals all still read 9.30% off the
    headline, and the dashboard sorted GSAT to the top on it.
    """
    p = parse_structured((deal or {}).get('pricing', {}))
    if not isinstance(p, dict) or not p.get('all_passed'):
        return None
    b = p.get('blended')
    try:
        b = float(b)
    except (TypeError, ValueError):
        return None
    return b if b > 0 else None


def apply_blended_to_spread(deal):
    """
    Rewrite sp_pct, ann and risk off the blended value. Returns what changed.

    dp is left alone on purpose. The filing's offer stays visible as "offer in
    the filing" — it is a fact about the agreement. It just stops driving any
    computed figure.

    sp_pct_at_detection is also left alone: it is the frozen forward-record
    anchor, and re-deriving it now would rewrite history.
    """
    b = blended_governs(deal)
    cp = deal.get('cp')
    if b is None or not cp or cp <= 0:
        return None
    old_sp, old_ann, old_risk = deal.get('sp_pct'), deal.get('ann'), deal.get('risk')
    new_sp = round(((b - cp) / cp) * 100, 2)
    deal['sp_pct_headline'] = old_sp          # kept so the gap stays auditable
    deal['sp_pct'] = new_sp
    deal['ann'] = annualized_spread(new_sp, deal.get('days_to_close'))
    # get_risk takes the spread as its first argument, so leaving it would band
    # the deal on a price nobody receives -- the same defect one field over.
    if deal.get('score') is not None:
        deal['risk'] = get_risk(new_sp, deal['score'])
    return {'ticker': deal.get('ticker'), 'blended': b,
            'sp_pct': (old_sp, new_sp), 'ann': (old_ann, deal['ann']),
            'risk': (old_risk, deal.get('risk'))}


def pricing_integrity_failures(deals):
    """
    Deals that should carry a blended price and do not. Empty means healthy.

    The barriers in deal_pricing protect against a WRONG blended number. Nothing
    protected against NO blended number, and that is the failure that actually
    shipped: GSAT's pricing object vanished from production for days while every
    barrier passed on every scan, because the write that carried it was rejected
    and the failure was never checked.

    Two shapes, and the second is the one that bit:

      contradiction -- all_passed is true but blended is None. Internally
      inconsistent: the barriers cannot certify a number that is not there.

      dropped -- a DEAL_STRUCTURES deal is in the feed with no pricing object at
      all. From inside the scan this looks like nothing; from outside it is
      indistinguishable from the pricing pass never having run.

    Takes the feed as the frontend receives it, so a cached repr string counts
    the same as a live dict.
    """
    failures = []
    for d in deals or []:
        tk = d.get('ticker')
        if tk not in DEAL_STRUCTURES:
            continue
        p = parse_structured(d.get('pricing', {}))
        if not isinstance(p, dict) or not p:
            failures.append((tk, 'dropped: in DEAL_STRUCTURES but carries no '
                                 'pricing object'))
            continue
        if p.get('blended') is None and p.get('all_passed'):
            failures.append((tk, 'contradiction: every barrier passed but '
                                 'blended is None'))
            continue
        # The barriers passing means the blended value governs. If sp_pct is
        # still the headline spread, the number that ranks this deal and sizes
        # a position against it is measured off a price nobody receives.
        b, cp, sp = blended_governs(d), d.get('cp'), d.get('sp_pct')
        if b is not None and cp and sp is not None:
            want = round(((b - cp) / cp) * 100, 2)
            if abs(float(sp) - want) > 0.05:
                failures.append((tk, f'spread source: barriers passed and the '
                                     f'blended value is {b:.2f}, so sp_pct should '
                                     f'be {want:.2f} but is {sp} '
                                     f'({"headline" if d.get("dp") and abs(float(sp) - round(((float(d["dp"])-cp)/cp)*100, 2)) <= 0.05 else "neither"})'))
    return failures


def two_state_applies(cp, dp, bp):
    """
    Whether the close-or-break model can produce a probability at all.

    Returns (True, None) or (False, reason). The model solves
    `cp = p*dp + (1-p)*bp`, which only has a meaning in [0, 1] when the current
    price sits between the break price and the deal price. Outside that range
    the arithmetic still returns a number, and it is not a probability.

    This replaces a `max(0, min(99.9, prob))` clamp. The clamp did not prevent
    the error, it concealed it: AES's break price sits ABOVE both its current
    and its deal price, both halves of the fraction go negative, the signs
    cancel, and 114.4% was clamped to 99.9% — rendered as near-certain closing
    beside a red "Distressed" label, from one function, on one deal.
    """
    if not cp or not dp or not bp:
        return False, "a current price, deal price and break price are all needed"
    if bp >= cp:
        return False, ("the modeled break price is at or above the current price, "
                       "so there is no downside left for the model to price")
    if bp >= dp:
        return False, ("the modeled break price is at or above the deal price, "
                       "so closing and breaking are not distinguishable outcomes")
    if cp > dp:
        return False, ("the stock trades above the deal price, which prices a "
                       "topping bid rather than this deal closing")
    return True, None


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
    """Strip leading clause junk, date contamination, trailing appositives,
    and foreign corporate suffixes from a raw regex match."""
    m = re.sub(
        r'^(?:(?:january|february|march|april|may|june|july|august|september|'
        r'october|november|december)\s+\d{1,2},?\s*\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4})',
        '', m, flags=re.IGNORECASE).strip().lstrip(',. ')
    m = LEAD_JUNK.sub('', m).strip().lstrip(',. ')
    m = re.sub(r',\s+(?:a|an|the)\s+\w+.*$', '', m, flags=re.IGNORECASE).strip()
    m = re.sub(
        r',?\s*(?:S\.p\.A\.|S\.A\.|N\.V\.|GmbH|S\.r\.l\.|B\.V\.|A\.S\.|AG|Oyj|AB|PLC|Plc)\.?\s*$',
        '', m, flags=re.IGNORECASE).strip().rstrip(',.')
    return m

# CAPWORD/CAPRUN: bounds the acquirer capture to a short run of capitalized
# tokens instead of unbounded lazy matching. This is the real CPRX fix — the
# old unbounded \s+ let the match span entire run-on sentences (e.g. greedily
# capturing the target's whole descriptive clause before reaching "has agreed
# to acquire"). Case-sensitive by design: capitalization is what stops the
# match at lowercase connector words ("to", "which", "a", "the").
_CAPWORD = r"[A-Z][A-Za-z0-9&\.\-']*"
_CAPRUN = rf"({_CAPWORD}(?:\s+{_CAPWORD}){{0,4}})"

def _flex(phrase):
    """Make only the first letter of a trigger phrase case-flexible; rest stays literal.
    Needed because patterns below are case-sensitive (for CAPRUN to work), but trigger
    phrases like 'has agreed to acquire' normally appear lowercase mid-sentence."""
    return f'[{phrase[0].upper()}{phrase[0].lower()}]{re.escape(phrase[1:])}'

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
        rf'{_flex("pursuant to which")} {_CAPRUN}\s+{_flex("has agreed to acquire")}',
        rf'{_flex("pursuant to which")} {_CAPRUN}\s+{_flex("will acquire")}',
        rf'{_CAPRUN}\s+{_flex("has agreed to acquire")}',
        rf'{_CAPRUN}\s+{_flex("agreed to acquire")}',
        rf'{_CAPRUN}\s+{_flex("agrees to acquire")}',
        rf'{_CAPRUN}\s+{_flex("will acquire")}',
        rf'{_CAPRUN}\s+{_flex("to acquire")}\s+(?:all\s+)?(?:of\s+)?(?:the\s+)?{_CAPWORD}',
        rf'{_flex("to be acquired by")}\s+{_CAPRUN}',
        rf'{_flex("will be acquired by")}\s+{_CAPRUN}',
        rf'{_flex("acquired by")}\s+{_CAPRUN}',
        rf'{_CAPRUN}\s+{_flex("today announced")}',
        # Extended: catches "for $X" AND "for Approximately $X" (e.g. AVNS headline)
        rf'{_flex("by")}\s+{_CAPRUN}\s+{_flex("for")}\s+(?:\$|[Aa]pproximately)',
        # New: catches "advised by [Acquirer]" when acquirer manages funds/affiliates
        rf'[Aa]dvised\s+by\s+{_CAPRUN}',
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
        for m in re.findall(pat, text):  # case-sensitive — required for CAPRUN bounding
            if not isinstance(m, str): continue
            m = m.strip().rstrip(',.')
            m = re.sub(r'\s+', ' ', m)
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


# How far into the filing the close-date reader looks. It was 5,000, which was
# the tightest cap in the file by a factor of five: extract_acquirer reads
# 15,000 of the same text, get_tender_offer_expiration 10,000, and
# extract_transaction_value 25,000. Nothing justified close_date being the
# outlier, and SLAB's guidance sits at offset 12,483 in its 8-K and 5,517 in its
# press release -- the second missing the old window by 517 characters.
#
# Matched to extract_transaction_value rather than to a new number, because both
# read the same full_ct and there is no reason for them to disagree about how
# much of it is worth reading.
CLOSE_DATE_SCAN_CHARS = 25000


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
        m=re.search(pat, clean_text[:CLOSE_DATE_SCAN_CHARS], re.IGNORECASE)
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

# A transaction value is checked against the company it belongs to, not against
# a range of numbers that are large in the abstract.
#
# CBZ reached production carrying tx_value 60.0 — sixty billion dollars — on a
# company with 54,263,879 shares at $55.00, an implied equity value of $2.98B.
# A 20x overstatement. The only guard was `0.01 <= tx <= 500`, and 60 sits
# comfortably inside it, because that range asks whether the number could belong
# to SOME deal rather than to THIS one.
#
# The band comes from the live feed rather than from intuition. Nineteen deals:
#
#     0.97 0.99 1.00 1.00 1.00 1.07 1.08 1.09 1.13 1.18
#     1.19 1.20 1.27 1.28 1.30 1.34        <- sixteen deals, all near parity
#     2.46 (BZH)  2.79 (CZR)               <- genuinely leveraged targets
#     20.10 (CBZ)                          <- 7x beyond the next-highest
#
# The ratio is enterprise-to-equity in all but name, so it is legitimately above
# 1 for a target carrying debt (Caesars at 2.79x) and legitimately below 1 for
# one carrying net cash. 5.0 leaves room for an LBO target more leveraged than
# anything in the feed today; 0.4 leaves room for a cash-rich one. CBZ is
# rejected with four times the margin of the nearest real value.
TX_VALUE_MIN_RATIO = 0.4
TX_VALUE_MAX_RATIO = 5.0


def tx_value_plausible(tx_value, dp, ticker, shares=None):
    """
    Whether a transaction value is consistent with this deal's own equity value.

    Returns (True, None) or (False, reason). Unknowable inputs pass: a missing
    share count is not evidence against the number, and refusing on absence
    would discard good values whenever yfinance is down.
    """
    if tx_value is None or not dp or dp <= 0:
        return True, None
    if shares is None:
        try:
            shares = yf.Ticker(ticker).info.get('sharesOutstanding')
        except Exception:
            return True, None
    if not shares or shares <= 0:
        return True, None
    equity_b = dp * shares / 1e9
    if equity_b <= 0:
        return True, None
    ratio = float(tx_value) / equity_b
    if ratio > TX_VALUE_MAX_RATIO:
        return False, (f'${tx_value}B is {ratio:.1f}x this deal\'s equity value '
                       f'(${equity_b:.2f}B = {shares:,} shares x ${dp}), above the '
                       f'{TX_VALUE_MAX_RATIO}x ceiling')
    if ratio < TX_VALUE_MIN_RATIO:
        return False, (f'${tx_value}B is {ratio:.2f}x this deal\'s equity value '
                       f'(${equity_b:.2f}B), below the {TX_VALUE_MIN_RATIO}x floor')
    return True, None


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

def parse_structured(value):
    """
    Undoes the CSV repr() round-trip for a structured (list/dict) field.

    pandas.to_csv() has no concept of nested types, so any list-of-dicts or
    dict field gets written as its Python repr() (single-quoted) rather than
    JSON. Redis round-trips these fields correctly via json.dumps/loads; this
    only bites on the CSV fallback path, when Redis is unavailable.

    Four fields have hit this so far: direction verdicts, the gate dict,
    spread_history, and flags. Reuse this helper for the next one instead of
    writing another one-off parse.
    """
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.startswith('[') or s.startswith('{'):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, dict)):
                    return parsed
            except Exception:
                pass
            return [] if s.startswith('[') else {}
    return {}

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
    # Capture prior direction verdicts BEFORE anything writes to the cache.
    # The direction block near the end of this function runs after save_cache()
    # has already overwritten the CSV with fresh results carrying no verdict,
    # so reading there finds nothing and every deal gets re-checked -- roughly
    # 3,500 API calls a month to re-answer a settled question.
    _prior_directions = {}
    try:
        for _row in (load_cache() or []):
            _tk, _dv = _row.get('ticker'), _row.get('direction')
            if _tk and _dv:
                # The CSV stores this dict as its repr, so it comes back a
                # string. Parse it once here rather than making every
                # downstream .get() defend itself.
                if isinstance(_dv, str) and _dv.strip().startswith('{'):
                    try:
                        import ast as _ast
                        _dv = _ast.literal_eval(_dv)
                    except Exception:
                        continue
                if isinstance(_dv, dict):
                    _prior_directions[_tk] = _dv
    except Exception as _pe:
        print(f"[Direction] could not capture prior verdicts: {_pe}")

    # Same capture, same reason, for the two readings taken off the merger
    # agreement. This is the fourth time this shape has appeared: the deal dict
    # built below carries neither field, and save_cache() writes those fresh
    # rows to the CSV before the agreement pass runs — so a read down there
    # found nothing and every scan re-fetched all twelve exhibits, 300-500k
    # characters each, for data that cannot change.
    #
    # Keyed on ACCESSION, not ticker. An amended merger agreement is filed under
    # a new accession and genuinely changes both readings — a new outside date
    # is the whole point of most amendments. When the accession moves, the
    # cached readings are stale and must be dropped rather than carried.
    _prior_agreements = {}
    try:
        for _row in (load_cache() or []):
            _tk, _acc = _row.get('ticker'), _row.get('accession')
            if not _tk or not _acc:
                continue
            _entry = {'accession': _acc}
            for _f in ('commitment', 'outside_date'):
                _pv = parse_structured(_row.get(_f, {}))
                if _pv:
                    _entry[_f] = _pv
            # Marks that this accession's exhibit was fetched and read. Without
            # it there is no way to tell "not yet read" from "read, and the
            # agreement states no outside date" — and the second kind would
            # re-download a 500k exhibit every hour to find the same nothing.
            _ra = _row.get('agreement_read')
            if isinstance(_ra, str) and _ra:
                _entry['agreement_read'] = _ra
            elif _entry.get('commitment'):
                # Rows written before this field existed. A commitment reading
                # only exists if the exhibit was read, so the read is implied.
                _entry['agreement_read'] = _acc
            _prior_agreements[_tk] = _entry
    except Exception as _pae:
        print(f"[Commitment] could not capture prior agreement readings: {_pae}")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Background EDGAR scan started.")
    headers={'User-Agent':'Kaushal Koduru kaushalkoduru@gmail.com'}
    all_hits=[]
    seen_ids=set()

    _queries = edgar_queries()
    print(f"[Scan] EDGAR window {_queries[0]['url'].split('startdt=')[1].split('&')[0]}"
          f" -> {_queries[0]['url'].split('enddt=')[1].split('&')[0]}"
          f" ({DEAL_SEARCH_LOOKBACK_DAYS}d lookback, matching the age gate)")
    for q in _queries:
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
        form_type=src.get('form','') or (src.get('root_forms') or [''])[0]
        # SC 14D9 filings are always tender offers
        if 'SC 14D9' in form_type or 'SC14D9' in form_type:
            deal_type='Tender Offer'
        name_str=str(src['display_names'])
        tm=re.search(r'\(([A-Z]{1,5})\)\s+\(CIK',name_str)
        ticker=tm.group(1) if tm else None
        cik=src['ciks'][0].lstrip('0') if src['ciks'] else None
        accession=src['adsh']
        if not ticker or not cik or not accession: continue
        print(f"  [Loop] processing {ticker} ({form_type}) {accession}")
        # ── PATH B: proxy hits resolve back to their announcement 8-K ─────────
        # A DEFM14A proves a deal exists but buries the terms. The announcement
        # 8-K states them in a press release, which our extractor handles well.
        # If no announcement is found, the deal is skipped rather than guessed at.
        
        if 'DEFM14A' in form_type.upper() or 'PREM14A' in form_type.upper():
            _proxy_date = src.get('file_date') or src.get('filing_date') or ''
            _ann = find_announcement_8k_backward(
                str(cik).zfill(10), _proxy_date or datetime.utcnow().strftime('%Y-%m-%d'),
                EDGAR_HEADERS, lookback_days=400,
                merger_signals=VALIDATION_MERGER_SIGNALS,
                irrelevant_signals=VALIDATION_IRRELEVANT_SIGNALS,
                text_fetcher=_get_text_for_validation,
            )
            if not _ann:
                print(f"  [PathB] {ticker}: proxy found but no announcement 8-K in lookback — skipping")
                continue
            _adate, _aacc, _aform, _adoc = _ann
            print(f"  [PathB] {ticker}: proxy resolved to {_aform} {_adate} ({_aacc})")
            accession = _aacc
            src = dict(src)
            src['file_date'] = _adate
        if ticker in seen_tickers: continue
        if ticker in EXCLUDED_TICKERS: continue
        # ── Age gate (moved up) ───────────────────────────────────────────────
        # Age was checked ~100 lines below, after a Yahoo price lookup. Path B
        # surfaces many old proxies whose targets have already delisted, so that
        # ordering meant a slow failing price fetch for deals we then discarded.
        # Checking the date first skips them before any network call.
        try:
            _age_days = (datetime.utcnow().date()
                         - datetime.strptime(src['file_date'], '%Y-%m-%d').date()).days
            if _age_days > 548:
                print(f"  [AgeSkip] {ticker}: announced {_age_days} days ago — skipping before price fetch")
                seen_tickers.add(ticker)
                continue
        except Exception:
            pass
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
        items = src.get('items', [])
        if items:  
            item_strs = [str(i) for i in items]
            has_101 = any('1.01' in i for i in item_strs)
            if not has_101:
                print(f"  Skip {ticker}: 8-K items {items} — no Item 1.01")
                continue
        try:
            # yfinance 1.5.1 wraps history() as (*args, **kwargs) and swallows a
            # timeout kwarg, so a delisted ticker can hang the scan indefinitely.
            # Path B surfaces many already-closed deals whose targets have stopped
            # trading, so this went from rare to routine. Enforce the deadline
            # ourselves: run the fetch in a worker thread and abandon it if it
            # overruns. The thread is left to die on its own; we just stop waiting.
            import concurrent.futures as _cf
            def _fetch_hist(tk):
                return yf.Ticker(tk).history(period='5d')
            h = None
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(_fetch_hist, ticker)
                try:
                    h = _fut.result(timeout=10)
                except _cf.TimeoutError:
                    print(f"${ticker}: price fetch exceeded 10s — abandoning, skipping")
                    seen_tickers.add(ticker)
                    continue
                except Exception as _pe:
                    print(f"${ticker}: price fetch failed ({_pe}) — skipping")
                    seen_tickers.add(ticker)
                    continue
            if h is None or h.empty:
                print(f"${ticker}: no price data (period=5d) — likely delisted, skipping")
                seen_tickers.add(ticker)
                continue
            cp=float(h['Close'].iloc[-1])
            if cp<1:
                print(f"  [PriceSkip] {ticker}: price ${cp:.2f} below $1 threshold — skipping")
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
                    # Validated HERE too, not only after enrichment. BWMN's
                    # "Q2 2026" never went near the model: the regex found it in
                    # EX-99.2, in a cross-reference to that morning's separate
                    # earnings release — "Bowman's Q2 2026 Earnings Results" —
                    # because the standalone Q-pattern requires no close
                    # language nearby. The deal was announced 2026-08-10, six
                    # weeks after that quarter ended.
                    #
                    # Worse, a bad value here SUPPRESSES the guarded path: the
                    # enrichment pass only runs when close_date == 'TBD', so an
                    # unvalidated regex hit stops the validated reader from ever
                    # being asked.
                    if close_date and close_date != 'TBD':
                        _cdok, _cdwhy = validate_close_date(close_date, src['file_date'])
                        if not _cdok:
                            print(f"  [CloseDate] {ticker}: REJECTED — {_cdwhy}")
                            close_date = 'TBD'
                    # For tender offers, try to get actual expiration date from SC TO-T filing
                    if deal_type == 'Tender Offer' and close_date == 'TBD':
                        to_date = get_tender_offer_expiration(ticker, cik)
                        if to_date:
                            _tok, _twhy = validate_close_date(to_date, src['file_date'])
                            if _tok:
                                close_date = to_date
                            else:
                                print(f"  [CloseDate] {ticker}: tender expiry "
                                      f"REJECTED — {_twhy}")
                            print(f"  [TO] {ticker} expiration: {to_date}")
                    tx_value, tx_value_source = extract_transaction_value(full_ct)
                    # Checked against this company before anything downstream
                    # sees it. Nulling it here rather than later lets the equity
                    # fallback below produce a defensible number in its place.
                    if tx_value is not None:
                        _txok, _txwhy = tx_value_plausible(tx_value, dp, ticker)
                        if not _txok:
                            print(f"  [TxValue] {ticker}: REJECTED — {_txwhy}")
                            tx_value, tx_value_source = None, None
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
            if not dp:
                print(f"  [NoPrice] {ticker}: no deal price extracted from {accession} — skipped")
                continue
            sp_pct=((dp-cp)/cp)*100
            # A target trading ABOVE its offer price is nearly always a sign the
            # filer is the acquirer, not the target. Genuine negative spreads happen
            # when the market expects a topping bid, but those run 1-3%, not 8%.
            # RKLB (acquiring Iridium) entered the feed at -7.85% under the old -10 gate.
            if sp_pct < -3 or sp_pct > 60:
                print(f"  [SpreadGate] {ticker}: spread {sp_pct:.2f}% out of range — skipping")
                continue
            days=(datetime.utcnow().date()-datetime.strptime(src['file_date'],'%Y-%m-%d').date()).days
            if days > 548:
                print(f"  Rolling drop: {ticker} — deal is {days} days old, likely closed")
                continue
            acquirer=VERIFIED_ACQUIRERS.get(ticker, acquirer)
            tx_value, tx_value_source = resolve_tx_value(
                ticker, tx_value, tx_value_source)
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
            # 'historical' is the pre-filing close. A hand-verified unaffected
            # price is a different provenance and must not be labelled as one.
            break_price_method=('verified_unaffected'
                                if ticker in VERIFIED_UNAFFECTED_PRICES else 'historical')
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
            # Annualized against THIS deal's time to close, not a constant.
            # None where the close date is unknown or has passed — see
            # annualized_spread. The UI already renders null as an em-dash.
            _dtc = days_to_close(close_date)
            ann=annualized_spread(round(sp_pct,2), _dtc)
            acq_type=get_acquirer_type(deal_type,acquirer)
            seen_tickers.add(ticker)
            results.append({
                'ticker':ticker,'acquirer':acquirer,'acquirer_type':acq_type,
                'company':resolve_company_name(ticker),'deal_type':deal_type,
                'cp':round(cp,2),'dp':dp,'sp_pct':round(sp_pct,2),'sp_pct_at_detection':round(sp_pct,2),'ann':ann,'days_to_close':_dtc,
                'score':sc,'risk':risk,'score_at_detection':sc,'risk_at_detection':risk,'filed':src['file_date'],'days_old':days,
                'close_date':close_date,'tx_value':tx_value,'tx_value_source':tx_value_source,'break_price':break_price,
                'break_downside':break_downside,'break_price_method':break_price_method,
                'financing_signal':financing_signal,
                'accession':accession,'reg_tags':json.dumps(reg_tags),'fetched':datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
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
        except Exception as _deal_ex:
            print(f"  [ScanError] {ticker}: inner processing failed — {_deal_ex}")
            continue

    

    if results:
        save_cache(results)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Scan complete.")
        # Background enrichment — fill missing tx_value and close_date via Groq
        groq_key = os.environ.get("GROQ_API_KEY", "")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
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
                            "https://api.anthropic.com/v1/messages",
                            headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                            json={
                                "model": "claude-sonnet-5",
                                "max_tokens": 100,
                                
                                "system": "You are an M&A data extractor. Return only valid JSON, no other text.",
                                "messages": [
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
                            content = resp.json()['content'][0]['text'].strip()
                            content = content.replace('```json','').replace('```','').strip()
                            data = json.loads(content)
                            acq = data.get('acquirer')
                            _ok, _why = validate_enriched_acquirer(
                                acq, filing_text, deal.get('company', ''))
                            if _ok:
                                deal['acquirer'] = _ok
                                deal['acquirer_source'] = 'llm_enriched'
                                enriched = True
                                print(f"  [Enrich] {ticker} acquirer: {_ok}")
                            else:
                                print(f"  [Enrich] {ticker} acquirer REFUSED — {_why}")
                        elif resp.status_code == 429:
                            print(f"  [Enrich] Rate limited on acquirer, stopping")
                            break
                    except Exception as e:
                        print(f"  [Enrich] Acquirer error {ticker}: {e}")
                try:
                    time.sleep(3.0)
                    resp = requests.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                        json={
                            "model": "claude-sonnet-5",
                            "max_tokens": 150,
                            "system": "You are an M&A data extractor. Return only valid JSON, no other text.",
                            "messages": [
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
                        content = resp.json()['content'][0]['text'].strip()
                        content = content.replace('```json','').replace('```','').strip()
                        data = json.loads(content)
                        tx = data.get('tx_value')
                        cd = data.get('close_date')
                        _txok, _txwhy = (tx_value_plausible(
                            float(tx), deal.get('dp'), ticker)
                            if isinstance(tx, (int, float)) else (False, 'not a number'))
                        if not _txok and tx is not None:
                            print(f"  [Enrich] {ticker} tx_value REFUSED — {_txwhy}")
                        if (_txok and tx and isinstance(tx, (int, float))
                                and 0.01 <= float(tx) <= 500):
                            if not deal.get('tx_value'):
                                deal['tx_value'] = round(float(tx), 2)
                                # 'regex_enterprise' was a lie: this number came
                                # from a model, not from a regex over the filing.
                                # The provenance field is the whole audit trail,
                                # so it has to say which one produced the value.
                                deal['tx_value_source'] = 'llm_enriched'
                                enriched = True
                                print(f"  [Enrich] {ticker} tx_value: {deal['tx_value']}B "
                                      f"(model estimate, not filing-extracted)")
                        if deal.get('close_date') == 'TBD':
                            _cd, _why = validate_close_date(cd, deal.get('filed'))
                            if _cd:
                                deal['close_date'] = _cd
                                deal['close_date_source'] = 'llm_enriched'
                                # Everything measured from the close date was
                                # computed hundreds of lines ago, off the 'TBD'
                                # that was here then. Recompute, or the date sits
                                # in the record parseable and unused -- which is
                                # what left APGE showing Q3 2026 beside a null
                                # days_to_close and no annualized figure.
                                _d2 = days_to_close(_cd)
                                deal['days_to_close'] = _d2
                                deal['ann'] = annualized_spread(deal.get('sp_pct'), _d2)
                                enriched = True
                                print(f"  [Enrich] {ticker} close_date: {_cd} "
                                      f"(days_to_close {_d2}, ann {deal['ann']})")
                            elif _why not in ('empty', 'no date offered'):
                                print(f"  [Enrich] {ticker} close_date REFUSED — {_why}")
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
        # ── VERIFICATION GATE (shadow mode) ──────────────────────────────────
        # Every deal must be provable by a real EDGAR filing. Records a verdict
        # and an accession number; blocks nothing until GATE_ENFORCING is True.
        # ── DEAL DIRECTION (shadow) ───────────────────────────────────────────
        # The pipeline assumes the filer is the target. That was wrong twice
        # (CLST, RKLB). Layer 1 is arithmetic; layer 2 asks Sonnet. UNCLEAR is
        # not a pass -- with enforcing on, only TARGET ships.
        try:
            def _direction_llm(prompt):
                _r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key,
                             "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                    json={"model": "claude-sonnet-5", "max_tokens": 20,
                          "system": "You answer with exactly one word. No explanation.",
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=25)
                if _r.status_code != 200:
                    raise RuntimeError(f"HTTP {_r.status_code}")
                return _r.json()["content"][0]["text"]

            print(f"[DirDebug] _prior_directions has {len(_prior_directions)} entries; "
                  f"tickers: {sorted(list(_prior_directions))[:5]}")
            for _d in results:
                _cached = _d.get('direction') or _prior_directions.get(_d.get('ticker'))
                if isinstance(_cached, dict):
                    _v = _cached.get('verdict')
                elif isinstance(_cached, str):
                    _v = VERDICT_TARGET if ('TARGET' in _cached and 'ACQUIRER' not in _cached) else None
                else:
                    _v = None
                if _d.get('ticker') == 'NATH':
                    print(f"[DirDebug] NATH cached={type(_cached).__name__} "
                          f"_v={_v!r} VERDICT_TARGET={VERDICT_TARGET!r} match={_v == VERDICT_TARGET}")
                if _v == VERDICT_TARGET:
                    # Already established as a target on a previous scan. Keep
                    # the verdict and skip the model call -- re-asking a settled
                    # question every hour is what turned this into ~3,500 API
                    # calls a month.
                    _d['direction'] = _cached
                    continue
                    
                _d['direction'] = check_direction(
                    _d.get('ticker'), _d.get('company'), _d.get('_filing_text', ''),
                    deal_price=_d.get('dp'), current_price=_d.get('cp'),
                    spread_pct=_d.get('sp_pct'),
                    llm_fn=_direction_llm if anthropic_key else None,
                )
            _dhdr, _dlines = direction_report(results)
            print(_dhdr)
            for _ln in _dlines:
                print(_ln)
            # A missing API key makes every deal UNCLEAR, which enforcing would
            # treat as a rejection and wipe the feed. Never enforce blind.
            if DIRECTION_ENFORCING and anthropic_key:
                _pre = len(results)
                def _verdict_of(r):
                    """A cached verdict arrives as a string from the CSV, so a
                    bare .get('verdict') raises. This crashed the whole
                    direction block once, and the handler swallowed it."""
                    v = r.get('direction')
                    if isinstance(v, dict):
                        return v.get('verdict')
                    if isinstance(v, str):
                        return VERDICT_TARGET if ('TARGET' in v and 'ACQUIRER' not in v) else None
                    return None
                results = [r for r in results if _verdict_of(r) == VERDICT_TARGET]
                if len(results) != _pre:
                    print(f"[Direction] blocked {_pre - len(results)} deal(s) not confirmed as targets")
        except Exception as _de:
            print(f"[Direction] error (non-fatal, nothing blocked): {_de}")

        # ── DEAL FLAGS ─────────────────────────────────────────────────────────
        # Pure string matching against filing text, no API calls. Display-only —
        # must never take down a scan.
        try:
            from deal_flags import detect_flags, flags_summary
            for _d in results:
                if not _d.get('flags'):
                    _d['flags'] = detect_flags(_d.get('_filing_text', ''))
            _flagged = [_d for _d in results if _d.get('flags')]
            print(f"[Flags] {len(_flagged)} flagged deal(s)")
            for _d in _flagged:
                print(f"  [Flags] {_d.get('ticker')}: {flags_summary(_d['flags'])}")
        except Exception as _fe:
            print(f"[Flags] error (non-fatal): {_fe}")

        # ── BLENDED CONSIDERATION — SHADOW MODE ────────────────────────────────
        # What a holder actually receives on an election or collar, run against
        # the thirteen barriers and logged. Computed only: dp, sp_pct and every
        # field the frontend reads are left exactly as they were. Turning the
        # display on is DEAL_PRICING_ENFORCING, and that stays False until the
        # barrier failures have been watched on live scans and checked by hand.
        try:
            from deal_pricing import (run_barriers, barrier_report,
                                      classify_structure, stock_leg_value)

            def _num(v):
                """dp and cp arrive as floats on a fresh scan and as strings off
                the CSV. The barriers do arithmetic on both."""
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            _acq_quotes = {}  # acquirer ticker -> (price, naive UTC timestamp)

            def _acquirer_quote(tk):
                """Last close and the timestamp of the bar it came from.

                The timestamp is the bar's own, not the time of the fetch —
                barrier 9 measures how stale the quote is, and stamping now()
                onto a three-day-old close would make it pass every time.
                Same abandon-on-timeout pattern as the target price fetch:
                yfinance swallows a timeout kwarg and can hang a scan.
                """
                if tk in _acq_quotes:
                    return _acq_quotes[tk]
                _px = _ts = None
                try:
                    import concurrent.futures as _cf
                    with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                        _h = _ex.submit(
                            lambda: yf.Ticker(tk).history(period='5d')
                        ).result(timeout=10)
                    if _h is not None and not _h.empty:
                        _px = float(_h['Close'].iloc[-1])
                        _bar = _h.index[-1]
                        if _bar.tzinfo is not None:
                            _bar = _bar.tz_convert('UTC').tz_localize(None)
                        _ts = _bar.to_pydatetime()
                    else:
                        print(f"  [Pricing] acquirer {tk}: no price data")
                except Exception as _qe:
                    print(f"  [Pricing] acquirer {tk}: price fetch failed ({_qe})")
                _acq_quotes[tk] = (_px, _ts)
                return _acq_quotes[tk]

            for _d in results:
                _terms = DEAL_STRUCTURES.get(_d.get('ticker'))
                if not _terms:
                    continue
                _px, _ts = _acquirer_quote(_terms.get('acquirer_ticker', ''))
                # Barrier 6 checks the cash figure against the sentence the
                # filing states it in — that is what the ELECTION flag already
                # captured, so reuse it rather than re-matching the document.
                _quote = ''
                for _fl in (_d.get('flags') or []):
                    if isinstance(_fl, dict) and _fl.get('flag') == 'ELECTION':
                        _quote = _fl.get('context', '') or ''
                        break
                _headline = _num(_d.get('dp'))
                _blended, _why, _bars = run_barriers(
                    _terms,
                    headline_price=_headline,
                    target_price=_num(_d.get('cp')),
                    acquirer_price=_px,
                    acquirer_price_time=_ts,
                    filing_text=_d.get('_filing_text', '') or '',
                    filing_quote=_quote,
                )
                _d['pricing'] = {
                    'blended': _blended,
                    'explanation': _why,
                    'barriers': [{'barrier': _b.barrier, 'passed': _b.passed,
                                  'detail': _b.detail} for _b in _bars],
                    'all_passed': all(_b.passed for _b in _bars),
                    # The legs the blended value was built from. The card writes
                    # its own sentence out of these -- a reader who has never
                    # heard of proration needs "40% at $90.00, the rest in stock
                    # worth $84.31", not a one-line summary of the result.
                    'structure': classify_structure(_terms),
                    'cash': _terms.get('cash'),
                    'ratio': _terms.get('ratio'),
                    'cash_cap': _terms.get('cash_cap'),
                    'collar_low': _terms.get('collar_low'),
                    'collar_high': _terms.get('collar_high'),
                    'acquirer_ticker': _terms.get('acquirer_ticker'),
                    'stock_leg': stock_leg_value(_terms, _px),
                    'acquirer_price': _px,
                    # ISO string, never a datetime: this dict round-trips
                    # through repr() into the CSV when Redis is down, and
                    # ast.literal_eval cannot rebuild a datetime from that.
                    'acquirer_price_at': _ts.isoformat() if _ts else None,
                }
                if _headline is None:
                    # barrier_report formats the headline, so it cannot be
                    # called without one. Report the barriers anyway.
                    print(f"[Pricing] {_d.get('ticker')}: no headline price — "
                          f"{sum(1 for _b in _bars if not _b.passed)} barrier(s) failed")
                    _lines = [f"    {_b}" for _b in _bars]
                else:
                    _hdr, _lines = barrier_report(_d.get('ticker'), _blended,
                                                  _headline, _bars)
                    print(_hdr)
                for _ln in _lines:
                    print(_ln)
            # Everything downstream reads sp_pct. Rewrite it here, once, so the
            # ticker, the annualized figure, the position-size table, the risk
            # band, the dashboard sort and /api/deals all measure against what a
            # holder receives rather than against the headline.
            for _d in results:
                _ch = apply_blended_to_spread(_d)
                if _ch:
                    print(f"  [Pricing] {_ch['ticker']}: spread now measured off "
                          f"the blended ${_ch['blended']:.2f} — "
                          f"sp_pct {_ch['sp_pct'][0]} -> {_ch['sp_pct'][1]}, "
                          f"ann {_ch['ann'][0]} -> {_ch['ann'][1]}, "
                          f"risk {_ch['risk'][0]} -> {_ch['risk'][1]}")
        except Exception as _pce:
            print(f"[Pricing] error (non-fatal, nothing changed): {_pce}")

        # ── COMMITMENT TERMS + OUTSIDE DATE ────────────────────────────────────
        # How hard the buyer is contractually bound to close, and the deadline it
        # is bound by. Both live in the merger agreement filed as EX-2.1, not in
        # the 8-K body or the press release, so _filing_text is the wrong
        # document and this pass fetches the exhibit separately off the deal's
        # accession. One fetch feeds both readings.
        #
        # Cached on the accession once read: a signed merger agreement does not
        # change, so the same document is never read twice. An AMENDED agreement
        # does change both readings — Vacasa pushed its outside date back twice
        # inside three weeks — and is filed under a new accession, which drops
        # the cached readings and forces a fresh read.
        try:
            from deal_commitment import assess_commitment
            from outside_date import extract_outside_date

            # Restore the prior readings captured before the scan's first write.
            # results dicts are built from scratch and carry neither field, so
            # without this every deal looks unread and every exhibit is
            # re-downloaded. Accession must match: a new accession means an
            # amended agreement, and the old readings describe a document that
            # is no longer operative.
            _restored = _amended = 0
            for _d in results:
                _p = _prior_agreements.get(_d.get('ticker'))
                if not _p:
                    continue
                if _p.get('accession') != _d.get('accession'):
                    print(f"  [Commitment] {_d.get('ticker')}: accession moved "
                          f"{_p.get('accession')} -> {_d.get('accession')} — "
                          f"agreement amended, cached readings discarded")
                    _amended += 1
                    continue
                for _f in ('commitment', 'outside_date', 'agreement_read'):
                    if _p.get(_f):
                        _d[_f] = _p[_f]
                _restored += 1
            print(f"[Commitment] {_restored} deal(s) restored from cache, "
                  f"{_amended} discarded on a changed accession")

            _read = 0
            for _d in results:
                # agreement_read holds the accession whose exhibit was read.
                # When it matches, both readings are settled for this document
                # — including a deal where the agreement simply states no
                # outside date, which must not be re-read to find the same
                # nothing. A signed agreement does not change; an amended one
                # arrives under a new accession and was dropped above.
                if _d.get('agreement_read') and _d.get('agreement_read') == _d.get('accession'):
                    continue
                _need_commit = not _d.get('commitment')
                _need_od     = not _d.get('outside_date')
                _tk = _d.get('ticker')
                _cik = SEC_CIK_MAP.get(_tk or '', '')
                _acc = _d.get('accession')
                if not _cik or not _acc:
                    continue
                _accn = _acc.replace('-', '')
                try:
                    _ix = requests.get(
                        f"https://www.sec.gov/Archives/edgar/data/{_cik}/{_accn}/index.json",
                        headers=EDGAR_HEADERS, timeout=10)
                    time.sleep(0.12)  # SEC rate limit: 10 req/sec max
                    if _ix.status_code != 200:
                        print(f"  [Commitment] {_tk}: document list HTTP {_ix.status_code}")
                        continue
                    # Naming shapes and the filter live on _EX2_NAME.
                    _ex2 = _pick_ex2(
                        _it.get('name') for _it in
                        _ix.json().get('directory', {}).get('item', []))
                    if not _ex2:
                        # index.json is not always populated with the filing's
                        # documents. CZR's accession lists only the index pages,
                        # the complete-submission .txt and the XBRL zip — while
                        # d143382dex21.htm, the merger agreement, sits in the
                        # same directory and serves fine. The human index page
                        # lists it. Without this fallback CZR's outside date is
                        # unreachable: it appears in no other filing.
                        _ex2 = _ex2_from_index_page(_cik, _accn, _acc)
                        if _ex2:
                            print(f"  [Commitment] {_tk}: {_ex2} found via index "
                                  f"page — absent from index.json")
                    if not _ex2:
                        # Plenty of 8-Ks announce a deal without attaching the
                        # agreement. Nothing to read, so nothing is claimed.
                        print(f"  [Commitment] {_tk}: no EX-2 exhibit in {_acc} — skipped")
                        continue
                    _txt = _get_text_for_validation(
                        f"https://www.sec.gov/Archives/edgar/data/{_cik}/{_accn}/{_ex2}")
                    if not _txt:
                        print(f"  [Commitment] {_tk}: {_ex2} unreadable — skipped")
                        continue
                    # Merger agreements run past 300,000 characters, and the
                    # termination fees sit in Article VIII near the end, so a tight
                    # cap drops the most valuable field first. GSAT's EX-2.1 is
                    # 500,072 characters and its $592M reverse fee falls past
                    # 400,000; 600,000 reaches it.
                    _txt = _txt[:600000]
                    _read += 1
                    # The exhibit is in hand; whatever the two readings return
                    # is this accession's final answer, including nothing.
                    _d['agreement_read'] = _acc
                    if _need_commit:
                        # tx_value is carried in billions. assess_commitment sizes
                        # the reverse fee against deal value in dollars.
                        try:
                            _dv = float(_d.get('tx_value')) * 1e9 if _d.get('tx_value') else None
                        except (TypeError, ValueError):
                            _dv = None
                        _d['commitment'] = assess_commitment(_txt, deal_value=_dv)
                    if _need_od:
                        # filed anchors plausibility: a deadline sits after
                        # signing. It arrives as NaN on some cached rows, and
                        # only a string is usable as an anchor.
                        _filed = _d.get('filed')
                        _d['outside_date'] = extract_outside_date(
                            _txt,
                            announced_date=_filed if isinstance(_filed, str) else None)
                except Exception as _ce:
                    print(f"  [Commitment] {_tk}: {_ce}")

            _committed = [_d for _d in results if _d.get('commitment')]
            print(f"[Commitment] {_read} agreement(s) read this scan, "
                  f"{len(_committed)} deal(s) with a commitment reading")
            for _d in _committed:
                _c = _d.get('commitment')
                if not isinstance(_c, dict):
                    continue
                _verdicts = ", ".join(f"{_t.get('term')}: {_t.get('verdict')}"
                                      for _t in _c.get('terms', []))
                print(f"  [Commitment] {_d.get('ticker')}: {_c.get('summary')} — {_verdicts}")

            # Outside dates read out of the same agreements. parse_structured
            # because a cached reading arrives as a repr string off the CSV
            # while a fresh one is still a dict.
            _dated = []
            for _d in results:
                _od = parse_structured(_d.get('outside_date', {}))
                if isinstance(_od, dict) and _od.get('date'):
                    _dated.append((_d.get('ticker'), _od))
            print(f"[OutsideDate] {len(_dated)} of {len(results)} deal(s) "
                  f"carry an outside date")

            # Cap the expected close at a deadline it cannot pass, and recompute
            # what depends on it. This runs here and not at deal construction
            # because the outside date is read from the agreement, which happens
            # in this pass — the deal dict was built hundreds of lines earlier
            # with no deadline to bound anything against.
            _capped = 0
            for _d in results:
                _od = parse_structured(_d.get('outside_date', {}))
                if not isinstance(_od, dict) or not _od.get('date'):
                    continue
                _ec, _cap_to = cap_expected_close(_d.get('close_date'), _od)
                _d['close_date_capped_to'] = _cap_to
                if not _cap_to:
                    continue
                _capped += 1
                _dtc2 = (_ec - datetime.utcnow().date()).days
                _d['days_to_close'] = _dtc2
                _d['ann'] = annualized_spread(_d.get('sp_pct'), _dtc2)
                print(f"  [CloseDate] {_d.get('ticker')}: guidance "
                      f"'{_d.get('close_date')}' resolves past the "
                      f"{_od.get('extension_type') or 'fixed'} outside date "
                      f"{_cap_to} — capped, {_dtc2}d to close")
            print(f"[CloseDate] {_capped} deal(s) capped at their outside date")
            for _tk, _od in _dated:
                _days = _od.get('days_remaining')
                _when = ("PASSED " + str(abs(_days)) + " days ago") if _od.get('passed')                         else (str(_days) + " days remaining")
                print(f"  [OutsideDate] {_tk}: {_od.get('date')} — {_when}, "
                      f"{'extendable' if _od.get('extendable') else 'fixed'}")
        except Exception as _cme:
            print(f"[Commitment] error (non-fatal, nothing changed): {_cme}")

        try:
            from deal_gate import gate_deal, gate_report, GATE_ENFORCING, VERDICT_VERIFIED
            
            for _d in results:
                _d['gate'] = gate_deal(
                    _d.get('ticker'),
                    SEC_CIK_MAP.get(_d.get('ticker', ''), ''),
                    _d.get('filed'),
                    cached_verdict=_d.get('gate'),
                    finder=_find_announcement_filing_for_validation,
                    merger_signals=VALIDATION_MERGER_SIGNALS,
                    irrelevant_signals=VALIDATION_IRRELEVANT_SIGNALS,
                )
            _hdr, _lines = gate_report(results)
            print(_hdr)
            for _ln in _lines:
                print(_ln)
            if GATE_ENFORCING:
                _before = len(results)
                results = [r for r in results if r.get('gate', {}).get('verdict') == VERDICT_VERIFIED]
                if len(results) != _before:
                    print(f"[Gate] blocked {_before - len(results)} unverified deal(s)")
            _clean = [{k: v for k, v in r.items() if k != '_filing_text'} for r in results]
            save_cache(_clean)

            # Read the feed back and check the blended prices survived the write.
            # This is the check that did not exist when GSAT's pricing silently
            # stopped reaching production: the barriers all passed, the scan
            # logged success, and the number was gone.
            try:
                _pf = pricing_integrity_failures(load_cache() or [])
                if _pf:
                    for _tk, _why in _pf:
                        print(f"[PricingIntegrity] {_tk}: {_why}")
                    print(f"[PricingIntegrity] {len(_pf)} deal(s) lost their "
                          f"blended price between computing it and reading it "
                          f"back — the cache write did not carry it")
                else:
                    print(f"[PricingIntegrity] all {len(DEAL_STRUCTURES)} "
                          f"structured deal(s) round-tripped with a blended price")
            except Exception as _pie:
                print(f"[PricingIntegrity] check failed (non-fatal): {_pie}")
        except Exception as _ge:
            print(f"[Gate] error (non-fatal, nothing blocked): {_ge}")
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
                # ── COMPLETION DETECTION (shadow mode) ───────────────────────
                # Heuristic pre-filter: skip EDGAR completion check for deals
                # that are clearly still early/open (saves EDGAR calls).
                # Only run Check 3 if at least one heuristic suggests possible completion.
                sp       = deal.get('sp_pct', 999)
                days_old = deal.get('days_old', 0)
                close_dt = deal.get('close_date', '')
                close_passed = False
                if close_dt and close_dt not in ('TBD', 'Not yet disclosed', ''):
                    try:
                        # Parse approximate close date to check if passed
                        import calendar
                        yr_match = re.search(r'(20\d{2})', close_dt)
                        if yr_match:
                            yr = int(yr_match.group(1))
                            if 'first half' in close_dt.lower() or 'h1' in close_dt.lower() or 'q1' in close_dt.lower() or 'q2' in close_dt.lower():
                                close_passed = datetime.utcnow() > datetime(yr, 7, 1)
                            elif 'second half' in close_dt.lower() or 'h2' in close_dt.lower() or 'q3' in close_dt.lower() or 'q4' in close_dt.lower():
                                close_passed = datetime.utcnow() > datetime(yr, 12, 31)
                            elif 'early' in close_dt.lower():
                                close_passed = datetime.utcnow() > datetime(yr, 4, 1)
                            elif 'mid' in close_dt.lower():
                                close_passed = datetime.utcnow() > datetime(yr, 8, 1)
                            elif 'late' in close_dt.lower():
                                close_passed = datetime.utcnow() > datetime(yr, 12, 1)
                            else:
                                close_passed = datetime.utcnow().year > yr
                    except Exception:
                        pass

                run_completion_check = (
                    abs(sp) < 1.0       # near-zero spread (deal nearly closed or already closed)
                    or close_passed      # close date has passed
                    or days_old > 400    # very old deal
                )

                if run_completion_check:
                    # Re-run validate_deal Check 3 explicitly for this deal
                    # validate_deal already has Check 3 built in — run it and
                    # look for COMPLETION flags specifically
                    v_flags_completion = validate_deal(ticker, acquirer, cik, company, filed)
                    completion_flags = [f for f in v_flags_completion
                                       if f.get('check') in ('COMPLETION_DEREGISTRATION', 'COMPLETION_8K')]

                    if completion_flags:
                        # Filing-confirmed completion — highest confidence
                        deal_key = f"{ticker}:{deal.get('accession') or filed}"
                        evidence = completion_flags[0].get('reason', '')
                        already_pending = any(p['deal_key'] == deal_key for p in PENDING_EXCLUSIONS)
                        if not already_pending:
                            PENDING_EXCLUSIONS.append({
                                'deal_key': deal_key,
                                'ticker': ticker,
                                'acquirer': acquirer,
                                'evidence': evidence,
                                'identified_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'heuristics': {
                                    'sp_pct': sp,
                                    'days_old': days_old,
                                    'close_passed': close_passed,
                                },
                                'auto_exclude_enabled': COMPLETION_AUTO_EXCLUDE,
                            })
                            print(f'  [Shadow] Would auto-exclude {ticker} ({deal_key}): {evidence[:80]}')
                    elif any(f.get('check') == 'AGE_OUT' for f in v_flags_completion) or close_passed:
                        # Heuristics only — flag for review, never auto-exclude
                        already = any(f['ticker'] == ticker for f in VALIDATION_FLAGS)
                        if not already:
                            VALIDATION_FLAGS.append({
                                'ticker': ticker,
                                'detected_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'source': 'daily_check_heuristic',
                                'flags': [{'check': 'POSSIBLE_COMPLETION_NO_FILING',
                                           'reason': f'sp_pct={sp:.2f}%, days_old={days_old}, close_passed={close_passed} — no completion filing found'}],
                            })
                            print(f'  [Validate-daily] {ticker}: possible completion (heuristics only, no filing) — flagged for review')

                # ── STANDARD VALIDATION (other checks) ──────────────────────
                v_flags = validate_deal(ticker, acquirer, cik, company, filed)
                # Filter out completion flags — handled above; avoid double-flagging
                other_flags = [f for f in v_flags
                               if f.get('check') not in ('COMPLETION_DEREGISTRATION', 'COMPLETION_8K')]
                if other_flags:
                    already = any(f['ticker'] == ticker for f in VALIDATION_FLAGS)
                    if not already:
                        VALIDATION_FLAGS.append({
                            'ticker': ticker,
                            'detected_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                            'source': 'daily_check',
                            'flags': other_flags,
                        })
                        print(f'  [Validate-daily] {ticker}: {len(other_flags)} flag(s)')
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

@app.get("/primer")
async def primer(): return read_html()

@app.get("/deal/{ticker}")
async def deal_page(ticker: str): return read_html()

def get_clean_deals():
    """
    Single source of truth for what the frontend sees.
    1. Filter out EXCLUDED_TICKERS — deals gone from feed immediately on deploy,
       no cache purge needed.
    2. Apply VERIFIED_ACQUIRERS overlay — hardcodes always win over cache.
    3. Parse structured fields (flags, direction) back from the CSV repr()
       string they round-trip as when Redis is unavailable — see
       parse_structured().
    Admin endpoints bypass this and read load_cache() directly so they can
    still see the full raw cache state.
    """
    import math
    def sanitize(obj):
        if isinstance(obj, float) and math.isnan(obj):
            return None
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(i) for i in obj]
        return obj
    deals = sanitize(load_cache() or [])
    # Step 1: filter excluded tickers
    deals = [d for d in deals if d.get('ticker') not in EXCLUDED_TICKERS]
    # Step 2: apply verified acquirer overrides
    for d in deals:
        t = d.get('ticker')
        if t and t in VERIFIED_ACQUIRERS:
            d['acquirer'] = VERIFIED_ACQUIRERS[t]
    # Step 3: undo the CSV repr() round-trip on structured fields before they
    # reach the frontend.
    for d in deals:
        d['flags'] = parse_structured(d.get('flags', []))
        d['direction'] = parse_structured(d.get('direction', {}))
        # Parsed so it is a dict rather than a repr string. The card reads it
        # only when DEAL_PRICING_ENFORCING is True; until then it rides along.
        if 'pricing' in d:
            d['pricing'] = parse_structured(d.get('pricing', {}))
        # Same round-trip: the commitment reading is a dict on a fresh scan and
        # a repr string once it has been through the CSV.
        if 'commitment' in d:
            d['commitment'] = parse_structured(d.get('commitment', {}))
        # Same round-trip again for the outside date read off the agreement.
        if 'outside_date' in d:
            d['outside_date'] = parse_structured(d.get('outside_date', {}))
    return deals

@app.get("/api/deals")
async def get_deals():
    # pricing_display is the one gate on the blended-consideration display.
    # While DEAL_PRICING_ENFORCING is False the frontend renders every card
    # exactly as it did before, and the pricing dict rides along unread.
    return JSONResponse(content={"deals": get_clean_deals(),
                                 "pricing_display": DEAL_PRICING_ENFORCING})

@app.get("/api/scan-status")
async def scan_status():
    return JSONResponse(content={"running": _scan_running})

# ─── ADMIN + VALIDATION ───────────────────────────────────────────────────────

ADMIN_TOKEN      = os.environ.get('ADMIN_TOKEN', '')
REVIEW_QUEUE     = []   # close-date abstentions from Groq enrichment
VALIDATION_FLAGS = []   # deals flagged by validate_deal() — reviewed before any removal
PENDING_EXCLUSIONS = []  # deals shadow-mode would auto-exclude — inspect at /api/admin/pending-exclusions
# When true, completion-confirmed deals are written to completed_deals in Redis and filtered from feed.
# Default false (shadow mode) — flip to true only after verifying PENDING_EXCLUSIONS for 1+ week.
COMPLETION_AUTO_EXCLUDE = os.environ.get('COMPLETION_AUTO_EXCLUDE', 'false').lower() == 'true'

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


# Filer agents name the merger agreement four ways: d62897dex21.htm,
# ef20070409_ex2-1.htm, exhibit21.htm, and ZERO-PADDED dp248400_ex0201.htm
# (EX-2.01). The padded form matched none of the plain substrings, which cost
# PAYO both its commitment reading and its outside date off a 662KB exhibit
# sitting right there in the filing.
#
# The 0* is what admits the padding. The trailing class stops 'ex1002' and
# similar from matching on a stray 2. Documents only -- '...index2.htm' would
# otherwise match on the 'ex2' in 'index', and the .jpg pages of a scanned
# exhibit carry the exhibit's own name.
_EX2_NAME = re.compile(r'ex(?:hibit)?[\-_]?0*2(?:[.\-_]|\d|$)')


def _pick_ex2(names):
    """First filename in the sequence that looks like the EX-2 merger agreement."""
    for _n in names:
        _nm = (_n or '').lower()
        if not _nm.endswith(('.htm', '.html', '.txt')) or 'index' in _nm:
            continue
        if _EX2_NAME.search(_nm):
            return _n
    return None


def _ex2_from_index_page(cik, accn, acc):
    """
    The EX-2 exhibit as listed on the filing's human index page.

    index.json is the fast path and is usually complete, but not always: CZR's
    8-K lists only its index pages, the complete-submission .txt and the XBRL
    zip there, while the index PAGE links d143382dex21.htm in the same
    directory. Falling back to the page is the difference between reading that
    agreement and reporting the deal has none.

    Returns a bare filename, or None. Best-effort — a failure here is the same
    outcome as no exhibit.
    """
    try:
        r = requests.get(
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{acc}-index.html",
            headers=EDGAR_HEADERS, timeout=10)
        time.sleep(0.12)  # SEC rate limit: 10 req/sec max
        if r.status_code != 200:
            return None
        # Same-directory document links only. The page also carries links out to
        # company search and to other accessions, and neither is this filing.
        _links = re.findall(rf'/Archives/edgar/data/\d+/{accn}/([^"\'>\s]+)', r.text)
        return _pick_ex2(_links)
    except Exception:
        return None


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
    # An 'Undisclosed' acquirer is itself a filer-as-acquirer signal: extract_acquirer
    # found the filer's own name, the same-entity check rejected it, and the field fell
    # back to blank. Requiring a non-blank acquirer meant this check never fired on the
    # exact case it exists to catch (see RKLB / Iridium).
    if (not acquirer or acquirer == 'Undisclosed') and company_name:
        listed_target = find_listed_target_ticker(filing_text, ticker)
        if listed_target:
            return True, (
                f"Filer \"{company_name}\" has no extractable acquirer, and the filing "
                f"names another listed company ({listed_target}). Filer is likely the "
                f"ACQUIRER. Real target may be trackable: {listed_target}."
            ), listed_target
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

@app.get("/api/admin/pending-exclusions")
async def get_pending_exclusions(token: str = ""):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return JSONResponse(content={
        "pending": PENDING_EXCLUSIONS,
        "count": len(PENDING_EXCLUSIONS),
        "auto_exclude_enabled": COMPLETION_AUTO_EXCLUDE,
        "note": (
            "Shadow mode — these deals WOULD be auto-excluded when COMPLETION_AUTO_EXCLUDE=true. "
            "Verify every entry is a real completed deal before flipping that env var. "
            "Each entry shows the EDGAR filing evidence that confirmed completion."
        ) if not COMPLETION_AUTO_EXCLUDE else (
            "Auto-exclude is LIVE. These deals have been excluded from the feed via completed_deals in Redis."
        ),
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

@app.post("/api/admin/reextract-acquirers")
async def reextract_acquirers(token: str = ""):
    """
    One-time re-extraction pass: re-runs the FIXED extract_acquirer against every
    cached deal's stored filing text and updates the acquirer field where it changes.
    Skips any ticker in VERIFIED_ACQUIRERS — those hardcodes always win and are
    never overwritten by this pass. Flag-first in spirit: reports every change made
    so you can review the diff, rather than silently mutating the cache.
    """
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    deals = load_cache() or []
    changes = []
    skipped_verified = []

    for d in deals:
        ticker = d.get('ticker', '')
        if not ticker:
            continue
        if ticker in VERIFIED_ACQUIRERS:
            skipped_verified.append(ticker)
            continue

        old_acquirer = d.get('acquirer', 'Undisclosed')
        accession = d.get('accession', '')
        cik = SEC_CIK_MAP.get(ticker, '')
        if not cik:
            continue

        # Re-fetch the same filing text the original extraction used
        filing_text = None
        try:
            sub = requests.get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers=EDGAR_HEADERS, timeout=10
            ).json()
            time.sleep(0.12)
            recent = sub.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            accs = recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])
            items = recent.get("items", [])
            for form, acc, doc, item in zip(forms, accs, docs, items):
                if form == "8-K" and doc and item and "1.01" in str(item):
                    links = get_filing_links(cik, acc, EDGAR_HEADERS)
                    if links:
                        for lk in links:
                            try:
                                dr = requests.get(lk, headers=EDGAR_HEADERS, timeout=10)
                                time.sleep(0.12)
                                ct = extract_targeted_section(dr.text)
                                if ct and len(ct) > 200:
                                    filing_text = ct
                                    break
                            except Exception:
                                continue
                    if filing_text:
                        break
        except Exception as e:
            print(f"  [Reextract] {ticker}: fetch error — {e}")
            continue

        if not filing_text:
            continue

        new_acquirer = extract_acquirer(filing_text, target_name=resolve_company_name(ticker))

        if new_acquirer != old_acquirer and new_acquirer != 'Undisclosed':
            d['acquirer'] = new_acquirer
            d['acquirer_type'] = get_acquirer_type(d.get('deal_type', 'All Cash'), new_acquirer)
            changes.append({
                "ticker": ticker,
                "old_acquirer": old_acquirer,
                "new_acquirer": new_acquirer,
            })
        time.sleep(0.3)

    if changes:
        clean = clean_records(deals)
        save_cache(clean)

    return JSONResponse(content={
        "changes_made": changes,
        "changes_count": len(changes),
        "skipped_verified_hardcodes": skipped_verified,
        "note": "Cache updated for changed tickers. VERIFIED_ACQUIRERS entries were never touched.",
    })

@app.post("/api/admin/clear-agreement-markers")
async def clear_agreement_markers(tickers: str = "", token: str = ""):
    """
    Drop the cached agreement readings for the named tickers so the next scan
    re-reads their EX-2 exhibits.

    The marker caches the DOCUMENT, not the reading — agreement_read holds the
    accession whose exhibit was read, and a signed agreement never changes, so
    the scan is right to skip it. The cost is that every improvement to the
    extractors is invisible on deals already read: the elective/automatic split
    could not reach SLAB, CZR, NATH or APGE, whose readings predate it, because
    their accessions had not moved. This is the release valve for that, and the
    only way to apply an extractor fix without waiting for an amendment.

    Takes a comma-separated ticker list. Refuses an empty one rather than
    treating it as "all" — re-reading twelve 400KB exhibits should be something
    you asked for on purpose.
    """
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    wanted = {t.strip().upper() for t in tickers.split(',') if t.strip()}
    if not wanted:
        return JSONResponse(status_code=400, content={
            "error": "Pass ?tickers=SLAB,CZR — an empty list is not taken to mean all."})

    deals = load_cache() or []
    cleared, missing = [], sorted(wanted - {d.get('ticker') for d in deals})

    for d in deals:
        if d.get('ticker') not in wanted:
            continue
        # Both readings go with the marker. Clearing the marker alone leaves the
        # stale dicts in place and the scan re-reads to no effect, because it
        # only fills a field that is empty.
        had = {f: d.get(f) for f in ('agreement_read', 'commitment', 'outside_date')
               if d.get(f)}
        for f in had:
            d[f] = None
        cleared.append({"ticker": d.get('ticker'), "fields_cleared": sorted(had)})

    if cleared:
        save_cache(clean_records(deals))

    return JSONResponse(content={
        "cleared": cleared,
        "cleared_count": len(cleared),
        "not_in_cache": missing,
        "note": "Next scan re-fetches the EX-2 exhibit for each of these and "
                "re-runs both the commitment and outside-date readings.",
    })


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
        # Gate before computing, not clamp after. The clamp that stood here
        # turned AES's sign error into 99.9% — printed beside a red
        # "Distressed" label from this same function, on the same deal. Where
        # the model does not apply there is no probability to publish, and
        # saying why is more useful than any number would be.
        applies, why = two_state_applies(cp, dp, bp)
        if not applies:
            return JSONResponse(content={
                "probability": None,
                "model_applies": False,
                "signal": "Model does not apply",
                "color": "grey",
                "current_price": cp,
                "deal_price": dp,
                "break_price": bp,
                "method": deal.get('break_price_method', 'historical'),
                "note": ("A close-or-break probability cannot be read from these "
                         "prices: " + why + ". The break price is a model estimate, "
                         "not an observed floor."),
            })
        prob = round(((cp - bp) / (dp - bp)) * 100, 1)
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
            "model_applies": True,
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

@app.get("/api/paywall-status")
async def paywall_status():
    """No-auth-required check for the global paywall bypass flag. The frontend
    calls this BEFORE checking Clerk login state, so a fully logged-out visitor
    can also see the bypass take effect — check-subscription alone can't do this
    since it's only ever called after a Clerk user is detected."""
    disabled = os.environ.get('PAYWALL_DISABLED', '').lower() == 'true'
    return JSONResponse(content={'paywall_disabled': disabled})

@app.get("/api/check-subscription")
async def check_subscription(email: str = ''):
    # Temporary full-product bypass — does not touch Stripe or auth code.
    # Set PAYWALL_DISABLED=true in Railway env vars to show full product to everyone.
    # Set back to false (or remove the var) to restore normal paywall behavior.
    if os.environ.get('PAYWALL_DISABLED', '').lower() == 'true':
        return JSONResponse(content={'subscribed': True})
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
        return JSONResponse(content={"deals": get_clean_deals()})
    _scan_running = True
    asyncio.create_task(run_background_scan())
    await asyncio.sleep(2)
    return JSONResponse(content={"deals": get_clean_deals()})