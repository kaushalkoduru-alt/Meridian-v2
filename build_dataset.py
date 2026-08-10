"""
HISTORICAL DEAL DATASET BUILDER  —  Meridian

Builds a verified set of US merger deals announced 2022-2025, each with its
outcome traced to a real SEC filing. This is the dataset that unblocks the
backtest, comparable deals, close-probability estimates, and V3 weight
calibration.

THE THREE RULES, fixed before any data was seen:

  Rule 1 — UNIVERSE  (revised after the 2022 trial)
      TARGET-SIDE FORMS ONLY: DEFM14A and PREM14A (merger proxies) and
      SC 14D9 (target's response to a tender offer). Only a target files these.

      The first version searched 8-K full text for merger language, which
      returns BOTH sides of every deal. Of the first 60 announcements, 22 were
      acquirers -- Intel, Pfizer, Broadcom, UnitedHealth, Take-Two, Stryker --
      and 18 more were large caps whose filings matched the phrases without
      being deals at all. One usable target in sixty. The direction check
      caught every acquirer correctly, but filtering after the fact is the
      wrong place to solve it: the universe was wrong to begin with.

      Selection still happens on the deal's existence, never on its outcome.

      KNOWN LIMITATION, to be reported with the results: a deal that collapses
      before any proxy or 14D9 is filed never enters this universe. Broken
      deals are therefore somewhat underrepresented, which biases the observed
      close rate UPWARD. The size of that gap is not knowable from this data.

  Rule 1a — DIRECTION (added after the first trial run)
      A full-text search for merger language catches ACQUIRER-side filings too.
      In the first ten 2022 announcements, six were companies doing the buying
      (Take-Two/Zynga, Planet Fitness/Sunshine, Stryker/Vocera) and one was a
      SPAC. Worse, FMNB was recorded as a deal at a +91.91% spread -- Farmers
      National Banc was the BUYER of Emclaire, so every field on that row was
      meaningless. Direction is now checked BEFORE terms are extracted, and
      acquirer-side filings are categorised rather than silently dropped.

  Rule 1b — PRICEABLE CONSIDERATION
      Some deals have no single per-share cash price. Emclaire holders could
      elect $40.00 cash OR 2.15 acquirer shares, capped 70/30. There is no
      fixed deal price there, so there is no spread, so there is nothing to
      backtest. These are excluded by reason, never by a guessed number.

  Rule 2 — OUTCOME PROOF
      CLOSED    Form 25 / 25-NSE, or an 8-K carrying Item 2.01
      BROKEN    an 8-K announcing termination of the merger agreement
      PENDING   no terminal filing found and the deal is recent enough to be live
      EXCLUDED  cannot be proven either way. Logged with a reason and COUNTED.
                Exclusions are part of the result, not swept aside.

  Rule 3 — FIELDS
      ticker, cik, announced date + accession, acquirer, deal price,
      consideration type, PRICE AND SPREAD ON THE ANNOUNCEMENT DATE,
      outcome, outcome date + accession, days to resolution.

      Spread at announcement is the load-bearing field: without it there is
      nothing to backtest, because you cannot know what the screen would have
      seen at the time.

USAGE (run from meridian-v2):

    python build_dataset.py --year 2022
    python build_dataset.py --year 2023
    ...

  One year at a time. Each run appends to historical_deals.csv and can be
  resumed -- tickers already recorded for that year are skipped. Runs are slow
  by design: EDGAR rate limits are respected, and every claim costs a fetch.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.getcwd())

import requests
from bs4 import BeautifulSoup

OUTFILE = "historical_deals.csv"
EXCLUDED_LOG = "historical_excluded.csv"

FIELDS = [
    "ticker", "cik", "company", "announced_date", "announced_accession",
    "acquirer", "deal_price", "consideration_type",
    "price_at_announcement", "spread_at_announcement_pct",
    "outcome", "outcome_date", "outcome_accession", "days_to_resolution",
    "price_source", "notes",
]

# ── Rule 2: what proves an outcome ───────────────────────────────────────────
DEREGISTRATION_FORMS = {"25", "25-NSE"}
TERMINATION_SIGNALS = [
    "termination of the merger agreement",
    "terminated the merger agreement",
    "notice of termination",
    "merger agreement has been terminated",
    "mutually agreed to terminate",
    "terminate the agreement and plan of merger",
]
COMPLETION_ITEM = "2.01"   # Completion of Acquisition or Disposition of Assets

# ── Rule 1a / 1b guards ──────────────────────────────────────────────────────
# Real merger spreads at announcement sit in a narrow band. Anything outside it
# is a directional error or a mis-extracted price, not an opportunity. FMNB came
# through the first trial at +91.91% (wrong side of the deal); RKLB reached
# production at -7.85% for the same reason. Arithmetic caught both.
SPREAD_FLOOR = -5.0
SPREAD_CEIL  = 40.0

# Phrases that mean the consideration has no single cash-per-share figure.
ELECTION_SIGNALS = [
    "may elect to receive", "election to receive", "stock election",
    "cash election", "or shares of", "exchange ratio of",
    "subject to proration", "election period",
]
STOCK_ONLY_SIGNALS = [
    "all-stock transaction", "all stock transaction",
    "in an all-stock", "stock-for-stock",
]

# SPAC shells are not merger-arb targets and their filings match the same
# phrases. SVF Investment Corp. 3 surfaced in the first ten.
SPAC_NAME_SIGNALS = [
    "acquisition corp", "acquisition co.", "blank check", "capital corp iii",
    "investment corp.", "acquisition ii", "acquisition iii", "acquisition iv",
]


def log(msg):
    print(msg, flush=True)


def load_main():
    """Import the pipeline's own extractors so the dataset is built the same
    way live deals are. If extraction differs between the two, the backtest
    measures the wrong thing."""
    try:
        from main import (
            EDGAR_HEADERS, get_filing_links, extract_targeted_section,
            extract_price_from_text, extract_acquirer, _get_text_for_validation,
            fetch_sec_ticker_map,
        )
        from deal_direction import check_direction, VERDICT_TARGET, VERDICT_ACQUIRER
        from find_announcement import find_announcement_8k_backward
        from extract_merger_price import extract_merger_price_fulltext
        from main import VALIDATION_MERGER_SIGNALS, VALIDATION_IRRELEVANT_SIGNALS
        import main as _main
        if not getattr(_main, "SEC_CIK_MAP", None):
            log("building SEC CIK map ...")
            fetch_sec_ticker_map()
        return {
            "headers": EDGAR_HEADERS,
            "get_filing_links": get_filing_links,
            "extract_targeted_section": extract_targeted_section,
            "extract_price_from_text": extract_price_from_text,
            "extract_acquirer": extract_acquirer,
            "get_text": _get_text_for_validation,
            "cik_map": getattr(_main, "SEC_CIK_MAP", {}) or {},
            "check_direction": check_direction,
            "V_TARGET": VERDICT_TARGET,
            "V_ACQUIRER": VERDICT_ACQUIRER,
            "anthropic_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "find_announcement": find_announcement_8k_backward,
            "fulltext_price": extract_merger_price_fulltext,
            "merger_signals": VALIDATION_MERGER_SIGNALS,
            "irrelevant_signals": VALIDATION_IRRELEVANT_SIGNALS,
        }
    except ImportError as e:
        log(f"could not import from main.py: {e}")
        log("run this from inside your meridian-v2 folder.")
        raise SystemExit(1)


# ── Rule 1: the universe ─────────────────────────────────────────────────────
def announcement_queries(year):
    """
    Rule 1: target-side forms only. Only the company being acquired files a
    merger proxy or a 14D9, so the universe contains no acquirers by
    construction rather than by filtering.
    """
    base = ("https://efts.sec.gov/LATEST/search-index?q={q}&forms={f}"
            "&dateRange=custom&startdt={y}-01-01&enddt={y}-12-31"
            "&from={{start}}&size=100")
    combos = [
        ('%22per+share+in+cash%22', 'DEFM14A'),
        ('%22merger+consideration%22', 'DEFM14A'),
        ('%22per+share+in+cash%22', 'PREM14A'),
        ('%22per+share%22', 'SC+14D9'),
    ]
    return [base.format(q=q, f=f, y=year) for q, f in combos]


def collect_announcements(year, headers):
    """Every qualifying 8-K for the year, deduped by ticker, in filing order."""
    seen_ids, seen_tickers, hits = set(), set(), []
    for url_tpl in announcement_queries(year):
        for start in range(0, 500, 100):
            url = url_tpl.format(start=start)
            try:
                r = requests.get(url, headers=headers, timeout=30)
                if r.status_code == 429:
                    log("  rate limited, waiting 20s")
                    time.sleep(20)
                    r = requests.get(url, headers=headers, timeout=30)
                batch = r.json().get("hits", {}).get("hits", [])
            except Exception as e:
                log(f"  query error: {e}")
                break
            if not batch:
                break
            for h in batch:
                if h.get("_id") in seen_ids:
                    continue
                seen_ids.add(h["_id"])
                src = h.get("_source", {})
                names = str(src.get("display_names", ""))
                m = re.search(r"\(([A-Z]{1,5})\)\s*\(CIK", names) or re.search(r"\(([A-Z]{1,5})\)", names)
                tk = m.group(1) if m else None
                if not tk or tk in seen_tickers:
                    continue
                seen_tickers.add(tk)
                hits.append({
                    "ticker": tk,
                    "cik": (src.get("ciks") or [""])[0],
                    "company": names.split("  (")[0].strip("[]'\" "),
                    "accession": src.get("adsh", ""),
                    "file_date": src.get("file_date", ""),
                })
            if len(batch) < 100:
                break
            time.sleep(0.3)
    hits.sort(key=lambda x: x["file_date"])
    return hits


# ── Rule 3: terms from the announcement filing ───────────────────────────────
def consideration_is_priceable(low):
    """
    Rule 1b. Returns (ok, reason). A deal is priceable only when there is a
    single per-share cash figure. Election structures and all-stock deals have
    no fixed price, so no spread, so nothing to backtest -- they are excluded
    by reason rather than recorded with a number that was never real.
    """
    for sig in STOCK_ONLY_SIGNALS:
        if sig in low:
            return False, f"all-stock consideration ('{sig}') — no fixed cash price"
    hits = [s for s in ELECTION_SIGNALS if s in low]
    if len(hits) >= 2:
        return False, f"election structure ({', '.join(hits[:2])}) — no single per-share price"
    return True, ""


def extract_terms(hit, M):
    """Deal price, acquirer, consideration type -- from the announcement itself.
    Also returns the filing text, which the direction check needs."""
    cik = hit["cik"].lstrip("0")
    out = {"deal_price": None, "acquirer": None, "consideration_type": None,
           "filing_text": "", "priceable": True, "price_note": "", "price_source": ""}
    try:
        links = M["get_filing_links"](int(cik), hit["accession"], M["headers"])
    except Exception:
        return out
    for lk in (links or [])[:6]:
        try:
            dr = requests.get(lk, headers=M["headers"], timeout=20)
            time.sleep(0.15)
        except Exception:
            continue
        full = BeautifulSoup(dr.text, "html.parser").get_text()
        low = full.lower()

        # Gate loosened after the 2022 trial. The old version demanded the
        # literal string "per share" AND one of three phrases; TEGNA's merger
        # agreement carried "agreement and plan of merger" and merger verbs but
        # was cut for phrasing, and its 8-K had no press release at all. Wider
        # here is safe because price extraction below is the real filter -- a
        # document that passes but yields no price costs nothing.
        has_agreement = any(k in low for k in (
            "definitive agreement", "merger agreement", "tender offer",
            "agreement and plan of merger", "plan of merger"))
        has_verb = any(k in low for k in ("acquir", "merger", "merge with", "tender offer"))
        has_share = any(k in low for k in ("per share", "per common share", "per share in cash"))
        if not (has_agreement and has_verb and has_share):
            continue

        if len(full) > len(out["filing_text"]):
            out["filing_text"] = full[:12000]

        ok, why = consideration_is_priceable(low)
        if not ok:
            out["priceable"] = False
            out["price_note"] = why
            return out

        # targeted section first -- higher precision when its window lands right
        ct = M["extract_targeted_section"](dr.text)
        price = M["extract_price_from_text"](ct)
        source = "targeted-section"

        # ...then the whole document. Amazon/iRobot stated "$61 per share in an
        # all-cash transaction" in the press release and "$61.00 per Share in
        # cash, without interest" in the merger agreement. Both sat outside the
        # window, so a deal with the price twice in plain sight was dropped.
        if not price:
            price, label = M["fulltext_price"](full)
            source = f"fulltext:{label}" if price else source
        if not price:
            continue
        out["deal_price"] = price
        out["price_source"] = source
        try:
            acq = M["extract_acquirer"](ct)
            out["acquirer"] = acq if acq and acq != "Undisclosed" else None
        except Exception:
            pass
        has_cash = "cash" in low
        has_stock = any(s in low for s in ("stock consideration", "shares of common stock of parent",
                                           "cash and stock", "stock election"))
        out["consideration_type"] = ("Cash + Stock" if has_cash and has_stock
                                     else "All Cash" if has_cash else "Other")
        return out
    return out


# ── Rule 3: the load-bearing field ───────────────────────────────────────────
TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "")


def price_on_date(ticker, date_str, lookback_days=7):
    """
    Close on the announcement date, or the nearest prior trading day. This is
    what a screen would have seen at the time; without it there is no spread
    and nothing to backtest.

    Tiingo, not yfinance. Every completed merger ends in delisting, and
    yfinance answers "Quote not found for symbol: IRBT" for anything
    deregistered -- which is precisely the population this dataset is about.
    Stooq retains delisted history but now sits behind a JavaScript
    proof-of-work challenge. Tiingo priced 7 of 7 test names including IRBT,
    TGNA, ATVI and two small caps.
    """
    if not TIINGO_KEY:
        return None
    try:
        target = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    start = target - timedelta(days=lookback_days)
    try:
        r = requests.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker.lower()}/prices",
            params={"startDate": start.isoformat(),
                    "endDate": target.isoformat(),
                    "token": TIINGO_KEY},
            headers={"Content-Type": "application/json"}, timeout=25)
        time.sleep(0.15)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        rows = r.json()
    except Exception:
        return None
    if not rows:
        return None
    px = rows[-1].get("close")
    return round(float(px), 2) if px is not None else None


# ── Rule 2: what actually happened ───────────────────────────────────────────
def find_outcome(cik, announced_date, M, max_days=900):
    """
    Walk forward from the announcement for a terminal filing.

    Returns (outcome, date, accession, note). PENDING means no terminal filing
    was found -- which is a real answer for recent deals, and a reason for
    exclusion on old ones. Nothing here is inferred: a deal is closed only if a
    filing says so.
    """
    cik_p = str(cik).zfill(10)
    try:
        ann = datetime.strptime(announced_date[:10], "%Y-%m-%d")
    except Exception:
        return "EXCLUDED", "", "", "unparseable announcement date"
    try:
        sub = requests.get(f"https://data.sec.gov/submissions/CIK{cik_p}.json",
                           headers=M["headers"], timeout=20).json()
        time.sleep(0.12)
    except Exception as e:
        return "EXCLUDED", "", "", f"submissions fetch failed: {e}"

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs  = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [])
    docs  = recent.get("primaryDocument", [])

    window_end = ann + timedelta(days=max_days)
    cands = []
    for i, form in enumerate(forms):
        try:
            fd = datetime.strptime(dates[i], "%Y-%m-%d")
        except Exception:
            continue
        if not (ann < fd <= window_end):
            continue
        cands.append((fd, form, accs[i], (items[i] if i < len(items) else ""),
                      (docs[i] if i < len(docs) else "")))
    cands.sort(key=lambda x: x[0])

    # deregistration is the cleanest proof a deal closed
    for fd, form, acc, item, doc in cands:
        if form in DEREGISTRATION_FORMS:
            return "CLOSED", fd.strftime("%Y-%m-%d"), acc, f"Form {form} filed"

    # then an 8-K carrying Item 2.01, or one whose text announces termination
    for fd, form, acc, item, doc in cands:
        if form != "8-K":
            continue
        if COMPLETION_ITEM in str(item):
            return "CLOSED", fd.strftime("%Y-%m-%d"), acc, "8-K Item 2.01"
        if not doc:
            continue
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{int(str(cik).lstrip('0'))}/{acc.replace('-', '')}/{doc}")
        txt = M["get_text"](url) or ""
        low = txt.lower()
        if any(s in low for s in TERMINATION_SIGNALS):
            return "BROKEN", fd.strftime("%Y-%m-%d"), acc, "termination language in 8-K"

    age = (datetime.utcnow() - ann).days
    if age < 550:
        return "PENDING", "", "", f"no terminal filing; {age} days since announcement"
    return "EXCLUDED", "", "", f"no terminal filing after {age} days — outcome unprovable"


def already_done(year):
    """Resume support: tickers already recorded for this year."""
    done = set()
    for path in (OUTFILE, EXCLUDED_LOG):
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("announced_date") or "").startswith(str(year)):
                    done.add(row.get("ticker"))
    return done


def append_row(path, row, fields):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, help="calendar year, 2022-2025")
    ap.add_argument("--limit", type=int, default=0, help="stop after N deals (for a quick trial run)")
    args = ap.parse_args()

    if not os.environ.get("TIINGO_API_KEY"):
        log("TIINGO_API_KEY not set — announcement prices and spreads will be blank.")
        log("  export TIINGO_API_KEY=your_key   (free at tiingo.com)")
        log("")

    if args.year < 2022 or args.year > 2025:
        log("Rule 1 fixes the range at 2022-2025.")
        raise SystemExit(1)

    M = load_main()
    done = already_done(args.year)
    if done:
        log(f"resuming — {len(done)} tickers already recorded for {args.year}")

    log(f"\ncollecting {args.year} announcements ...")
    hits = collect_announcements(args.year, M["headers"])
    log(f"{len(hits)} announcements found\n" + "=" * 74)

    counts = {"CLOSED": 0, "BROKEN": 0, "PENDING": 0, "EXCLUDED": 0,
              "SPAC": 0, "ACQUIRER_SIDE": 0, "UNCLEAR_SIDE": 0, "SPREAD_FLAG": 0,
              "NO_ANNOUNCEMENT": 0}
    processed = 0

    for i, hit in enumerate(hits, 1):
        tk = hit["ticker"]
        if tk in done:
            continue
        if args.limit and processed >= args.limit:
            log(f"\nstopping at limit ({args.limit})")
            break

        def drop(reason, tag="EXCLUDED"):
            row = {f: "" for f in FIELDS}
            row.update(ticker=tk, cik=hit["cik"], company=hit["company"],
                       announced_date=hit["file_date"],
                       announced_accession=hit["accession"],
                       outcome=tag, notes=reason)
            append_row(EXCLUDED_LOG, row, FIELDS)
            counts[tag] = counts.get(tag, 0) + 1
            log(f"[{i}/{len(hits)}] {tk:<6} {tag:<10} {reason[:52]}")

        # ── SPAC shells match the same phrases and are not merger-arb targets ──
        cname = (hit["company"] or "").lower()
        if any(s in cname for s in SPAC_NAME_SIGNALS):
            drop("SPAC shell — not a merger-arb target", "SPAC")
            processed += 1
            continue

        # ── resolve the proxy back to the announcement 8-K ────────────────────
        # The proxy proves a deal exists but is filed weeks or months later and
        # buries the terms in hundreds of pages. Everything the backtest needs
        # -- terms, the announcement date, the price the screen would have seen
        # -- comes from the announcement itself.
        ann = M["find_announcement"](
            str(hit["cik"]).zfill(10), hit["file_date"], M["headers"],
            lookback_days=500,
            merger_signals=M["merger_signals"],
            irrelevant_signals=M["irrelevant_signals"],
            text_fetcher=M["get_text"],
        )
        if not ann:
            drop("no announcement 8-K found within 500 days before the proxy",
                 "NO_ANNOUNCEMENT")
            processed += 1
            continue
        ann_date, ann_acc, ann_form, _ann_doc = ann
        # from here the deal is dated and accessioned from its ANNOUNCEMENT
        hit = dict(hit, file_date=ann_date, accession=ann_acc)

        terms = extract_terms(hit, M)

        # ── Rule 1a: which side of the deal is the filer on? ──────────────────
        # Checked BEFORE terms are trusted. FMNB was recorded at a +91.91%
        # spread because it was the buyer, not the target -- every field on that
        # row described the wrong company.
        if terms["filing_text"]:
            def _llm(prompt):
                r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": M["anthropic_key"],
                             "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                    json={"model": "claude-sonnet-5", "max_tokens": 20,
                          "system": "You answer with exactly one word. No explanation.",
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=30)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                return r.json()["content"][0]["text"]

            try:
                dr_res = M["check_direction"](
                    tk, hit["company"], terms["filing_text"],
                    deal_price=terms["deal_price"],
                    llm_fn=_llm if M["anthropic_key"] else None)
            except Exception as _dex:
                drop(f"direction check raised {type(_dex).__name__}: {_dex}", "UNCLEAR_SIDE")
                processed += 1
                continue
            if dr_res["verdict"] == M["V_ACQUIRER"]:
                note = f"filer is the ACQUIRER — {dr_res['reason'][:60]}"
                if dr_res.get("other_ticker"):
                    note += f" (target may be {dr_res['other_ticker']})"
                drop(note, "ACQUIRER_SIDE")
                processed += 1
                continue
            if dr_res["verdict"] != M["V_TARGET"]:
                drop(f"direction unconfirmed — {dr_res['reason'][:60]}", "UNCLEAR_SIDE")
                processed += 1
                continue

        # ── Rule 1b: is there a single per-share cash price at all? ────────────
        if not terms["priceable"]:
            drop(terms["price_note"] or "consideration not priceable")
            processed += 1
            continue

        if not terms["deal_price"]:
            drop("no deal price extractable from announcement")
            processed += 1
            continue

        px = price_on_date(tk, hit["file_date"])
        if not px or px <= 0:
            drop("no market price on the announcement date — spread uncomputable")
            processed += 1
            continue

        spread = round(((terms["deal_price"] - px) / px) * 100, 2)

        # ── spread sanity: arithmetic catches what reading misses ─────────────
        if spread < SPREAD_FLOOR or spread > SPREAD_CEIL:
            drop(f"spread {spread:+.2f}% outside {SPREAD_FLOOR:+.0f}%..{SPREAD_CEIL:+.0f}% "
                 f"— price or direction is wrong, not an opportunity", "SPREAD_FLAG")
            processed += 1
            continue

        outcome, odate, oacc, note = find_outcome(hit["cik"], hit["file_date"], M)
        days = ""
        if odate:
            try:
                days = (datetime.strptime(odate, "%Y-%m-%d")
                        - datetime.strptime(hit["file_date"][:10], "%Y-%m-%d")).days
            except Exception:
                pass

        row = {
            "ticker": tk, "cik": hit["cik"], "company": hit["company"],
            "announced_date": hit["file_date"], "announced_accession": hit["accession"],
            "acquirer": terms["acquirer"] or "", "deal_price": terms["deal_price"],
            "consideration_type": terms["consideration_type"] or "",
            "price_at_announcement": px if px else "",
            "spread_at_announcement_pct": spread if spread is not None else "",
            "outcome": outcome, "outcome_date": odate, "outcome_accession": oacc,
            "days_to_resolution": days, "price_source": terms.get("price_source", ""),
            "notes": note,
        }
        append_row(EXCLUDED_LOG if outcome == "EXCLUDED" else OUTFILE, row, FIELDS)
        counts[outcome] = counts.get(outcome, 0) + 1
        processed += 1

        sp = f"{spread:+.2f}%" if spread is not None else "  n/a "
        log(f"[{i}/{len(hits)}] {tk:<6} {outcome:<8} ${terms['deal_price']:<8} "
            f"spread {sp:<8} {note[:40]}")

    log("\n" + "=" * 74)
    log(f"{args.year}: " + "  ".join(f"{k} {v}" for k, v in counts.items()))
    log(f"kept -> {OUTFILE}    excluded -> {EXCLUDED_LOG}")
    kept = counts["CLOSED"] + counts["BROKEN"] + counts["PENDING"]
    total = sum(counts.values())
    if total:
        log(f"kept {kept} of {total} announcements ({kept/total*100:.0f}%)")
    log("")
    log("Every rejection above is categorised, not silently dropped. Report these")
    log("counts alongside the kept deals: a dataset that hides what it could not")
    log("verify has the same problem as a backtest that hides its losing trades.")


if __name__ == "__main__":
    main()