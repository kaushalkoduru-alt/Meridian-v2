"""
When a deal's detection record is allowed to freeze.

sp_pct_at_detection, score_at_detection and risk_at_detection are the whole
basis of the forward track record. They freeze at the first scan, and the first
scan of a deal announced before the open prices it off the PREVIOUS close: SSTI
was first scanned at 8:14 ET on announcement day with cp = 5.47 (the 28 Sept
close), so its record says "46.25% spread, High risk" -- the offer premium, not a
spread anyone could trade. An hour after the open the stock was at 8.22.

A detection record is only valid once a price that can reflect the announcement
has been observed. We define that as the first regular-session close at or after
the moment EDGAR accepted the announcement filing, and re-derive the three fields
from the first snapshot in spread_history/score_history taken at or after it.
Until such a snapshot exists the record is provisional and simply tracks the
current values. Snapshots taken before it are tagged prov=True, not deleted.

Pure functions plus one EDGAR lookup (cached by accession); the caller injects
the lookup so tests need no network.
"""
import ast
import json
import os
import time
from datetime import datetime, timedelta

import requests

HEADERS = {"User-Agent": "MeridianResearch/1.0 (kaushalkoduru@gmail.com)",
           "Accept-Encoding": "gzip, deflate"}
ACC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "acceptance_cache.json")
_acc = {}                   # accession -> ISO UTC string, '' when EDGAR could not say
FRESH_DAYS = 7              # only recent deals can still be pre-close; older records are left alone
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _load():
    if _acc:
        return
    try:
        with open(ACC_FILE, encoding="utf-8") as f:
            _acc.update(json.load(f))
    except Exception:
        pass


def accepted_utc(cik, accession):
    """EDGAR's acceptance time (UTC) for a filing, or None. Cached per accession;
    a failed lookup is not cached, so it is retried next scan."""
    if not cik or not accession:
        return None
    _load()
    hit = _acc.get(accession)
    if hit:
        return datetime.strptime(hit, TS_FMT)
    try:
        time.sleep(0.15)
        r = requests.get(f"https://data.sec.gov/submissions/CIK{int(str(cik)):010d}.json",
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        rec = r.json()["filings"]["recent"]
        i = rec["accessionNumber"].index(accession)
        dt = datetime.strptime(rec["acceptanceDateTime"][i][:19], "%Y-%m-%dT%H:%M:%S")
    except Exception as e:
        print(f"[Baseline] acceptance lookup failed for {accession}: {e}")
        return None
    _acc[accession] = dt.strftime(TS_FMT)
    try:
        with open(ACC_FILE, "w", encoding="utf-8") as f:
            json.dump(_acc, f)
    except Exception:
        pass
    return dt


def _ny_offset(dt_utc):
    """Hours New York is behind UTC at that instant (4 in DST, else 5)."""
    def nth_sunday(y, m, n):
        d = datetime(y, m, 1)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    y = dt_utc.year
    start = nth_sunday(y, 3, 2).replace(hour=7)      # 02:00 EST
    end = nth_sunday(y, 11, 1).replace(hour=6)       # 02:00 EDT
    return 4 if start <= dt_utc < end else 5


def session_close_after(accepted):
    """UTC time of the first 16:00 New York close at or after `accepted`.
    Weekends roll to Monday; exchange holidays are not modelled (a holiday only
    keeps a record provisional one day longer, never the wrong way)."""
    local = accepted - timedelta(hours=_ny_offset(accepted))
    day = local.date()
    if not (local.hour < 16 and local.weekday() < 5):
        day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    probe = datetime(day.year, day.month, day.day, 16, 0)
    return probe + timedelta(hours=_ny_offset(probe + timedelta(hours=5)))


def _parse(t):
    try:
        return datetime.strptime(t, TS_FMT)
    except (TypeError, ValueError):
        return None


def _last_pre(deal):
    b = deal.get("break_price_band")
    if isinstance(b, str):
        try:
            b = ast.literal_eval(b)
        except (ValueError, SyntaxError):
            return None
    v = b.get("last_pre") if isinstance(b, dict) else None
    return float(v) if isinstance(v, (int, float)) else None


def rebaseline_detection(deal, accept_fn, now=None):
    """Re-derive the three detection fields for a recently announced deal.
    Returns a one-line description when it changed something, else None.

    accept_fn(deal) -> datetime (UTC) | None : when EDGAR accepted the
    announcement filing."""
    now = now or datetime.utcnow()
    sh, sch = deal.get("spread_history"), deal.get("score_history")
    if not (isinstance(sh, list) and isinstance(sch, list) and sh and len(sh) == len(sch)):
        return None
    try:
        filed = datetime.strptime(str(deal.get("filed"))[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if (now - filed).days > FRESH_DAYS:
        return None
    first = _parse(sh[0].get("t"))
    if first is None:
        return None
    # Certain to be post-close without asking EDGAR: skip the lookup.
    if first >= filed + timedelta(days=2, hours=21):
        return None
    accepted = None
    try:
        accepted = accept_fn(deal)
    except Exception as e:
        print(f"[Baseline] {deal.get('ticker')}: acceptance lookup error {e}")
    # Unknown acceptance: assume it landed before the filing date's close.
    confirm = session_close_after(accepted) if accepted else session_close_after(filed + timedelta(hours=12))
    if first >= confirm:
        return None

    # A snapshot taken after the close only counts if its PRICE is post-announcement.
    # LFCR: the scanner's price stayed at the 25 Sept close (4.20) for a day and a
    # half after the 28 Sept announcement (stock 6.52), so snapshots after the close
    # still carried the pre-announcement price. A price equal to the pre-announcement
    # price (the first scan's, or the stored last pre-announcement close) is stale.
    pre = [x for x in (sh[0].get("cp"), _last_pre(deal)) if isinstance(x, (int, float)) and x > 0]

    def stale(snap):
        cp = snap.get("cp")
        return not isinstance(cp, (int, float)) or any(abs(cp - x) / x <= 0.001 for x in pre)

    idx = next((i for i, s in enumerate(sh)
                if (_parse(s.get("t")) or datetime.min) >= confirm and not stale(s)), None)
    for j in range(idx if idx is not None else len(sh)):
        sh[j]["prov"] = True
        sch[j]["prov"] = True
    before = (deal.get("sp_pct_at_detection"), deal.get("score_at_detection"), deal.get("risk_at_detection"))
    if idx is None:
        deal["sp_pct_at_detection"] = deal.get("sp_pct")
        deal["score_at_detection"] = deal.get("score")
        deal["risk_at_detection"] = deal.get("risk")
        deal["detection_basis"] = "provisional: first close after the announcement not yet observed"
    else:
        deal["sp_pct_at_detection"] = sh[idx].get("sp")
        deal["score_at_detection"] = sch[idx].get("sc")
        deal["risk_at_detection"] = sch[idx].get("risk")
        deal["detection_basis"] = "first close after the announcement (" + sh[idx]["t"] + ")"
    after = (deal.get("sp_pct_at_detection"), deal.get("score_at_detection"), deal.get("risk_at_detection"))
    if after != before:
        return f"{deal.get('ticker')}: detection {before} -> {after} [{deal['detection_basis']}]"
    return None
