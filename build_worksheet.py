"""
CANDIDATE WORKSHEET BUILDER  —  Meridian historical dataset

Automated term extraction was tried and abandoned. Six rounds of fixes --
direction checking, target-only forms, full-document price search, Tiingo
pricing, amendment ordering, financing rejection -- moved the yield from 2%
to 4%. Every fix was correct; each one simply revealed another filing format.
Four years of SEC documents have more variety than a rules-based extractor
absorbs.

So the machine does what it is reliably good at, and you do the rest.

WHAT THIS DOES AUTOMATICALLY (all verified, all filing-sourced):
  - finds target-side filings only (DEFM14A / PREM14A / SC 14D9)
  - resolves each back to its announcement 8-K, skipping amendments and
    credit agreements
  - rejects SPAC shells and acquirer-side filings
  - determines the OUTCOME from a terminal filing, with its accession
  - pulls the announcement-day close from Tiingo

WHAT YOU DO BY HAND:
  - open the filing link
  - read the per-share price
  - type it in

That is the one step nothing automated did reliably, and it is the step where
a wrong number would silently poison every downstream result. Five minutes a
deal, roughly twelve hours for 150 -- which is what "weeks of unglamorous
verification" always meant.

The spread computes itself once the price is filled in; run --recompute.

USAGE
    python build_worksheet.py --year 2022
    python build_worksheet.py --year 2022 --limit 30
    python build_worksheet.py --recompute          # after filling prices in
"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.getcwd())

import requests
from bs4 import BeautifulSoup

WORKSHEET = "worksheet.csv"
REJECTED = "worksheet_rejected.csv"

FIELDS = [
    "ticker", "company", "cik",
    "announced_date", "announcement_url",
    "deal_price",            # <-- YOU FILL THIS IN
    "acquirer",              # <-- and this, if blank
    "consideration_notes",   # <-- anything odd: CVR, election, adjustment
    "price_at_announcement", "spread_at_announcement_pct",
    "outcome", "outcome_date", "outcome_url",
    "days_to_resolution",
    "verified_by_hand",      # <-- put y here when you have checked it
    "notes",
]

TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

DEREG_FORMS = {"25", "25-NSE"}
TERMINATION_SIGNALS = [
    "termination of the merger agreement", "terminated the merger agreement",
    "notice of termination", "merger agreement has been terminated",
    "mutually agreed to terminate", "terminate the agreement and plan of merger",
]
SPAC_NAME_SIGNALS = [
    "acquisition corp", "acquisition co.", "blank check",
    "investment corp.", "acquisition ii", "acquisition iii", "acquisition iv",
]


def log(m):
    print(m, flush=True)


def load_main():
    try:
        from main import (EDGAR_HEADERS, get_filing_links,
                          _get_text_for_validation,
                          VALIDATION_MERGER_SIGNALS, VALIDATION_IRRELEVANT_SIGNALS)
        from find_announcement import find_announcement_8k_backward
        from deal_direction import check_direction, VERDICT_TARGET, VERDICT_ACQUIRER
        return {
            "headers": EDGAR_HEADERS,
            "links": get_filing_links,
            "get_text": _get_text_for_validation,
            "merger_signals": VALIDATION_MERGER_SIGNALS,
            "irrelevant_signals": VALIDATION_IRRELEVANT_SIGNALS,
            "find_ann": find_announcement_8k_backward,
            "check_direction": check_direction,
            "V_TARGET": VERDICT_TARGET,
            "V_ACQUIRER": VERDICT_ACQUIRER,
        }
    except ImportError as e:
        log(f"import failed: {e}\nrun from meridian-v2.")
        raise SystemExit(1)


def target_side_queries(year):
    """Only a target files a merger proxy or a 14D9."""
    base = ("https://efts.sec.gov/LATEST/search-index?q={q}&forms={f}"
            "&dateRange=custom&startdt={y}-01-01&enddt={y}-12-31"
            "&from={{start}}&size=100")
    combos = [('%22per+share+in+cash%22', 'DEFM14A'),
              ('%22merger+consideration%22', 'DEFM14A'),
              ('%22per+share+in+cash%22', 'PREM14A'),
              ('%22per+share%22', 'SC+14D9')]
    return [base.format(q=q, f=f, y=year) for q, f in combos]


def collect(year, headers):
    seen_ids, seen_tk, out = set(), set(), []
    for tpl in target_side_queries(year):
        for start in range(0, 500, 100):
            try:
                r = requests.get(tpl.format(start=start), headers=headers, timeout=30)
                if r.status_code == 429:
                    time.sleep(20)
                    r = requests.get(tpl.format(start=start), headers=headers, timeout=30)
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
                s = h.get("_source", {})
                names = str(s.get("display_names", ""))
                m = re.search(r"\(([A-Z]{1,5})\)", names)
                tk = m.group(1) if m else None
                if not tk or tk in seen_tk:
                    continue
                seen_tk.add(tk)
                out.append({"ticker": tk, "cik": (s.get("ciks") or [""])[0],
                            "company": names.split("  (")[0].strip("[]'\" "),
                            "accession": s.get("adsh", ""),
                            "file_date": s.get("file_date", "")})
            if len(batch) < 100:
                break
            time.sleep(0.3)
    out.sort(key=lambda x: x["file_date"])
    return out


def tiingo_close(ticker, date_str, lookback=10, unaffected=True):
    """
    The UNAFFECTED close: the last trading day BEFORE the announcement.

    Pulling the announcement-day close was wrong. A deal is announced before
    the open or during the session, so that day's close already contains the
    news and the stock has jumped most of the way to the offer. PlayAGS closed
    at $11.34 the day of its announcement against a $12.50 offer -- a 10%
    spread -- when the press release plainly stated a 40% premium to the prior
    close of $8.96. The unaffected price is what a trader actually saw, and it
    is what the premium in every press release is quoted against.

    Pass unaffected=False to get the announcement day itself.
    """
    if not TIINGO_KEY:
        return None
    try:
        target = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    end = target - timedelta(days=1) if unaffected else target
    try:
        r = requests.get(f"https://api.tiingo.com/tiingo/daily/{ticker.lower()}/prices",
                         params={"startDate": (end - timedelta(days=lookback)).isoformat(),
                                 "endDate": end.isoformat(), "token": TIINGO_KEY},
                         headers={"Content-Type": "application/json"}, timeout=25)
        time.sleep(0.15)
        if r.status_code != 200:
            return None
        rows = r.json()
        return round(float(rows[-1]["close"]), 2) if rows else None
    except Exception:
        return None


def find_outcome(cik, announced, M, max_days=1100):
    """Rule 2 unchanged: a deal closed only if a filing says so."""
    try:
        ann = datetime.strptime(announced[:10], "%Y-%m-%d")
    except Exception:
        return "UNKNOWN", "", "", "unparseable announcement date"
    try:
        sub = requests.get(f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json",
                           headers=M["headers"], timeout=20).json()
        time.sleep(0.12)
    except Exception as e:
        return "UNKNOWN", "", "", f"submissions fetch failed: {e}"

    rec = sub.get("filings", {}).get("recent", {})
    forms, accs = rec.get("form", []), rec.get("accessionNumber", [])
    dates, items = rec.get("filingDate", []), rec.get("items", [])
    docs = rec.get("primaryDocument", [])

    cands = []
    for i, f in enumerate(forms):
        try:
            fd = datetime.strptime(dates[i], "%Y-%m-%d")
        except Exception:
            continue
        if ann < fd <= ann + timedelta(days=max_days):
            cands.append((fd, f, accs[i], items[i] if i < len(items) else "",
                          docs[i] if i < len(docs) else ""))
    cands.sort(key=lambda x: x[0])

    for fd, f, acc, item, doc in cands:
        if f in DEREG_FORMS:
            return "CLOSED", fd.strftime("%Y-%m-%d"), acc, f"Form {f}"
    for fd, f, acc, item, doc in cands:
        if f != "8-K":
            continue
        if "2.01" in str(item):
            return "CLOSED", fd.strftime("%Y-%m-%d"), acc, "8-K Item 2.01"
        if not doc:
            continue
        txt = (M["get_text"](f"https://www.sec.gov/Archives/edgar/data/"
                             f"{int(str(cik).lstrip('0'))}/{acc.replace('-','')}/{doc}") or "").lower()
        if any(s in txt for s in TERMINATION_SIGNALS):
            return "BROKEN", fd.strftime("%Y-%m-%d"), acc, "termination language"

    age = (datetime.utcnow() - ann).days
    return "PENDING", "", "", f"no terminal filing after {age} days"


def edgar_url(cik, accession):
    return (f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(str(cik).lstrip('0'))}/{accession.replace('-', '')}/")


def append(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def existing_tickers():
    done = set()
    for p in (WORKSHEET, REJECTED):
        if os.path.exists(p):
            with open(p, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    done.add(r.get("ticker"))
    return done


def recompute():
    """Fill in spreads for rows where you have typed a price."""
    if not os.path.exists(WORKSHEET):
        log("no worksheet yet")
        return
    with open(WORKSHEET, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    filled = 0
    for r in rows:
        try:
            dp = float(r.get("deal_price") or 0)
            px = float(r.get("price_at_announcement") or 0)
        except ValueError:
            continue
        if dp > 0 and px > 0:
            r["spread_at_announcement_pct"] = round(((dp - px) / px) * 100, 2)
            filled += 1
    tmp = WORKSHEET + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, WORKSHEET)
    done = sum(1 for r in rows if (r.get("verified_by_hand") or "").lower().startswith("y"))
    log(f"{filled} of {len(rows)} rows have a spread")
    log(f"{done} of {len(rows)} marked verified by hand")
    # Bounds widened after verification. The original -5%..+40% was a guess made
    # before any data existed, and it flagged six deals that all turned out to be
    # correct: Tapestry/Capri at +64.69% (the release stated 64.9%), Alaska/Hawaiian
    # at +270%, SP Plus at +52.50% (release stated 52%). Distressed and small-cap
    # targets routinely announce at premiums that large. These bounds now catch real
    # errors instead -- a negative spread means the filer is the acquirer, and past
    # +300% the price or the ticker is wrong.
    def _sp(r):
        try:
            return float(r.get("spread_at_announcement_pct"))
        except (TypeError, ValueError):
            return None
    flagged = [r for r in rows if _sp(r) is not None and not (-10 <= _sp(r) <= 300)]
    if flagged:
        log("")
        log("spreads outside -10%..+300% -- check these, the price or the side is wrong:")
        for r in flagged:
            log(f"   {r['ticker']:<6} {r['spread_at_announcement_pct']:>8}%   {r['announcement_url']}")


def repull():
    """
    Fetch announcement-day prices for rows that still lack one.

    Hand verification turned up two reasons a price is missing or wrong:

      WRONG TICKER   EDGAR's display name lists every registered security, so
                     the regex sometimes grabbed a preferred symbol -- CRLKP for
                     SP Plus, VIASP for Via Renewables, EQTNP for Equitrans,
                     TRXDW for Asensus. Tiingo then priced the wrong security
                     entirely and the spread came out nonsense.

      WRONG DATE     The lookback landed on a follow-up filing, so the date was
                     an amendment or a tender expiry rather than the
                     announcement. By then the stock had already converged and
                     the spread read near zero.

    Both are corrected by hand in the sheet. This re-pulls against whatever the
    ticker and announced_date columns now say, and leaves a row blank rather
    than guessing when Tiingo has nothing.
    """
    if not os.path.exists(WORKSHEET):
        log("no worksheet yet")
        return
    if not TIINGO_KEY:
        log("TIINGO_API_KEY not set -- nothing to pull with")
        return

    with open(WORKSHEET, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))

    todo = [r for r in rows
            if (r.get("deal_price") or "").strip()
            and not (r.get("price_at_announcement") or "").strip()
            and (r.get("announced_date") or "").strip()]

    if not todo:
        log("every row with a deal price already has an announcement price")
        return

    log(f"re-pulling {len(todo)} unaffected price(s) -- last close BEFORE announcement\n" + "=" * 74)
    filled = 0
    for r in todo:
        tk = (r.get("ticker") or "").strip().upper()
        d = (r.get("announced_date") or "").strip()
        px = tiingo_close(tk, d)
        if not tk:
            log(f"  (no ticker) {d}  cannot pull without a symbol -- fix the ticker column")
            continue
        if not px:
            log(f"  {tk:<7} {d}  no price from Tiingo -- left blank")
            continue
        r["price_at_announcement"] = px
        filled += 1
        try:
            dp = float(r["deal_price"])
            sp = round(((dp - px) / px) * 100, 2)
            r["spread_at_announcement_pct"] = sp
            flag = "" if -10 <= sp <= 300 else "   <-- outside -10%..+300%, check it"
            log(f"  {tk:<7} {d}  ${px:<9} deal ${dp:<9} spread {sp:+.2f}%{flag}")
        except (TypeError, ValueError):
            log(f"  {tk:<7} {d}  ${px:<9} (deal price unparseable, no spread)")

    # Write to a temp file and swap it in only once complete. An earlier version
    # wrote in place, hit a NameError partway through, and left a recovered
    # worksheet truncated to its header row.
    tmp = WORKSHEET + ".tmp"
    def _safe(v):
        if not isinstance(v, str):
            return v
        return (v.replace("\u2014", "-").replace("\u2013", "-")
                 .replace("\u2019", "'").replace("\u201c", '"')
                 .replace("\u201d", '"').replace("\u2026", "..."))
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: _safe(r.get(k, "")) for k in FIELDS})
    os.replace(tmp, WORKSHEET)

    log("=" * 74)
    log(f"filled {filled} of {len(todo)}")
    log("")
    log("Sanity-check each against the premium the press release stated. A price")
    log("that does not reconcile means the ticker or the date is still wrong --")
    log("that check caught SP Plus and PlayAGS when the spread math looked fine.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--recompute", action="store_true")
    ap.add_argument("--repull", action="store_true",
                    help="fetch announcement prices for rows that lack one")
    a = ap.parse_args()

    if a.repull:
        repull()
        return
    if a.recompute:
        recompute()
        return
    if not a.year or not (2022 <= a.year <= 2025):
        log("--year required, 2022-2025")
        raise SystemExit(1)
    if not TIINGO_KEY:
        log("TIINGO_API_KEY not set -- announcement prices will be blank\n")

    M = load_main()
    done = existing_tickers()
    if done:
        log(f"resuming -- {len(done)} tickers already on the worksheet")

    log(f"\ncollecting {a.year} target-side filings ...")
    hits = collect(a.year, M["headers"])
    log(f"{len(hits)} candidates\n" + "=" * 78)

    kept = rejected = 0
    for i, h in enumerate(hits, 1):
        tk = h["ticker"]
        if tk in done:
            continue
        if a.limit and (kept + rejected) >= a.limit:
            log(f"\nstopping at limit ({a.limit})")
            break

        base = {f: "" for f in FIELDS}
        base.update(ticker=tk, company=h["company"], cik=h["cik"])

        if any(s in (h["company"] or "").lower() for s in SPAC_NAME_SIGNALS):
            base["notes"] = "SPAC shell"
            append(REJECTED, base)
            rejected += 1
            log(f"[{i}/{len(hits)}] {tk:<6} rejected  SPAC shell")
            continue

        hints = []
        ann = M["find_ann"](str(h["cik"]).zfill(10), h["file_date"], M["headers"],
                            lookback_days=240,
                            merger_signals=M["merger_signals"],
                            irrelevant_signals=M["irrelevant_signals"],
                            text_fetcher=M["get_text"],
                            hint_out=hints)

        # A rejected follow-up filing usually names the date of the agreement it
        # is amending or terminating. Search again around that date rather than
        # abandoning a real deal -- TEGNA's amendment pointed straight at the
        # Feb 22 announcement carrying the $24.00 price.
        if not ann and hints:
            hint = sorted(hints)[-1]
            log(f"    [Hint] {tk}: follow-up cited an agreement dated {hint}, searching there")
            try:
                probe = (datetime.strptime(hint, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
            except Exception:
                probe = hint
            ann = M["find_ann"](str(h["cik"]).zfill(10), probe, M["headers"],
                                lookback_days=30,
                                merger_signals=M["merger_signals"],
                                irrelevant_signals=M["irrelevant_signals"],
                                text_fetcher=M["get_text"])

        if not ann:
            base["notes"] = ("no announcement 8-K found in lookback"
                             + (f"; a follow-up cited {sorted(hints)[-1]}" if hints else ""))
            append(REJECTED, base)
            rejected += 1
            log(f"[{i}/{len(hits)}] {tk:<6} rejected  no announcement found")
            continue
        adate, aacc, aform, adoc = ann

        # direction, on the announcement text -- the one automated judgement
        # that proved reliable (14/14 on live deals, and it caught Rocket Lab)
        text = ""
        try:
            links = M["links"](int(str(h["cik"]).lstrip("0")), aacc, M["headers"]) or []
            for lk in links[:4]:
                d = requests.get(lk, headers=M["headers"], timeout=20)
                time.sleep(0.15)
                t = BeautifulSoup(d.text, "html.parser").get_text()
                if len(t) > len(text):
                    text = t[:12000]
        except Exception:
            pass

        if text and ANTHROPIC_KEY:
            def _llm(p):
                r = requests.post("https://api.anthropic.com/v1/messages",
                                  headers={"x-api-key": ANTHROPIC_KEY,
                                           "anthropic-version": "2023-06-01",
                                           "Content-Type": "application/json"},
                                  json={"model": "claude-sonnet-5", "max_tokens": 20,
                                        "system": "You answer with exactly one word. No explanation.",
                                        "messages": [{"role": "user", "content": p}]},
                                  timeout=30)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                return r.json()["content"][0]["text"]
            try:
                dres = M["check_direction"](tk, h["company"], text, llm_fn=_llm)
                if dres["verdict"] == M["V_ACQUIRER"]:
                    base["notes"] = f"filer is the acquirer{' (target may be ' + dres['other_ticker'] + ')' if dres.get('other_ticker') else ''}"
                    append(REJECTED, base)
                    rejected += 1
                    log(f"[{i}/{len(hits)}] {tk:<6} rejected  acquirer-side")
                    continue
            except Exception:
                pass

        px = tiingo_close(tk, adate)
        outcome, odate, oacc, note = find_outcome(h["cik"], adate, M)
        days = ""
        if odate:
            try:
                days = (datetime.strptime(odate, "%Y-%m-%d")
                        - datetime.strptime(adate, "%Y-%m-%d")).days
            except Exception:
                pass

        row = dict(base)
        row.update(
            announced_date=adate,
            announcement_url=edgar_url(h["cik"], aacc),
            price_at_announcement=px if px else "",
            outcome=outcome, outcome_date=odate,
            outcome_url=edgar_url(h["cik"], oacc) if oacc else "",
            days_to_resolution=days, notes=note,
        )
        append(WORKSHEET, row)
        kept += 1
        log(f"[{i}/{len(hits)}] {tk:<6} -> worksheet   {outcome:<8} "
            f"px {px if px else 'n/a':<8} {adate}")

    log("\n" + "=" * 78)
    log(f"{kept} candidates on the worksheet, {rejected} rejected")
    log(f"worksheet -> {WORKSHEET}      rejected -> {REJECTED}")
    log("")
    log("Now open each announcement_url, read the per-share price, and type it")
    log("into deal_price. Mark verified_by_hand with y. Then:")
    log("    python build_worksheet.py --recompute")
    log("to fill in the spreads and flag anything implausible.")


if __name__ == "__main__":
    main()