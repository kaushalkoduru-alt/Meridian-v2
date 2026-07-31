"""
PATH B — resolve a merger proxy back to its announcement 8-K.

A DEFM14A tells us a deal exists but buries the terms in a thousand pages of
legalese. The announcement 8-K states them plainly in a press release, which
is the document our extractor already handles well.

This searches BACKWARD from the proxy date for the most recent 8-K carrying
merger language. Different from _find_announcement_filing_for_validation,
which searches a tight window AROUND a known announcement date -- here the
announcement date is exactly what we don't have.

Returns (filing_date, accession, form, primary_doc) or None.
"""
import re
import time
from datetime import datetime, timedelta

import requests


def find_announcement_8k_backward(cik, from_date_str, headers,
                                  lookback_days=400,
                                  merger_signals=None,
                                  text_fetcher=None,
                                  irrelevant_signals=None):
    """
    cik            zero-padded CIK string
    from_date_str  the proxy's filing date, 'YYYY-MM-DD' -- search back from here
    lookback_days  how far back to look. Deals typically announce 3-12 months
                   before the proxy; 400 days covers the slow ones.
    text_fetcher   function(url) -> text. Pass main._get_text_for_validation.

    Walks candidate 8-Ks newest-first and returns the first one whose text
    contains merger language. Newest-first matters: a company may have older
    unrelated merger filings, and the most recent one before the proxy is
    almost always this deal's announcement.
    """
    merger_signals = merger_signals or []
    irrelevant_signals = irrelevant_signals or []

    try:
        from_date = datetime.strptime(from_date_str[:10], "%Y-%m-%d")
    except Exception:
        return None
    window_start = from_date - timedelta(days=lookback_days)

    try:
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=headers, timeout=15
        ).json()
        time.sleep(0.12)
    except Exception:
        return None

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs  = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    docs  = recent.get("primaryDocument", [])

    candidates = []
    for form, acc, date_str, doc in zip(forms, accs, dates, docs):
        if not doc or form not in ("8-K", "SC TO-T", "SC TO-C"):
            continue
        try:
            fdate = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        if window_start <= fdate <= from_date:
            candidates.append((date_str, acc, form, doc, fdate))

    # newest first -- the announcement is the most recent merger 8-K before the proxy
    candidates.sort(key=lambda x: x[4], reverse=True)

    if candidates:
        print(f"    [Lookback] CIK {cik}: checking up to {min(len(candidates), 25)} filings for the announcement")
    for date_str, acc, form, doc, _ in candidates[:25]:
        acc_clean = acc.replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{int(cik)}/{acc_clean}/{doc}")
        text = text_fetcher(url) if text_fetcher else None
        if not text:
            continue
        low = text.lower()
        if any(s in low for s in merger_signals):
            # reject filings that are about a different transaction type
            if any(s in low for s in irrelevant_signals) and not any(
                s in low for s in ('agreement and plan of merger', 'merger agreement')
            ):
                continue
            return date_str, acc, form, doc
    return None