"""
PATH B — resolve a merger proxy back to its announcement 8-K.

A DEFM14A tells us a deal exists but buries the terms in hundreds of pages.
The announcement 8-K states them plainly in a press release, which is the
document our extractor handles well.

This searches BACKWARD from the proxy date for the 8-K carrying merger
language. Different from _find_announcement_filing_for_validation, which
searches a tight window AROUND a known announcement date -- here the
announcement date is exactly what we don't have.

TWO CORRECTIONS after the 2022 dataset trial:

  1. ORDERING. This used to walk candidates newest-first and return the first
     match. For TEGNA that returned "Amendment No. 1 to Agreement and Plan of
     Merger" -- a document that modifies specific sections of the original and
     contains NO dollar amounts at all. The price lived in the original
     agreement filed weeks earlier. Announcements come first by definition, so
     candidates are now walked OLDEST-first within the window.

  2. AMENDMENT REJECTION. Amendments, extensions and supplements all carry
     merger language and are not announcements. They are skipped explicitly,
     which also protects against an amendment that happens to predate the
     announcement inside an odd window.

  3. WINDOW TIGHTENED. Oldest-first inside a 500-day window overcorrected: for
     a company with any prior deal activity it reached past the actual
     announcement into an older, unrelated transaction. iRobot resolved to
     2021-08-03 at $85.48 -- a full year before Amazon existed as a buyer.
     A merger proxy follows its announcement by roughly one to six months, so
     the window is now 240 days and, within it, the MOST RECENT
     announcement-shaped filing wins. Amendments and financing documents are
     still rejected outright, which is what oldest-first was working around.

  4. ITEM 1.01 IS READ DIRECTLY. Hand-verifying sixteen candidates found that
     seven were not merger filings at all -- a construction loan extension, a
     master repurchase agreement, a revolving credit amendment, an office lease
     amendment, a bylaw amendment. Every one of them names itself in the first
     line of Item 1.01:

         "entered into the Modification and Extension Agreement ... to extend
          the maturity date of the construction loan"
         "entered into the Third Amendment to Master Repurchase Agreement"
         "adopted and approved an amendment to the Bylaws"

     The earlier check only read the first 2,000 characters, which in an 8-K
     body is cover-page boilerplate -- the substance sits further in. Item 1.01
     is now located and its opening sentences are read on their own.

  5. FOLLOW-UP FILINGS REJECTED, AND THE REAL DATE READ OUT OF THEM. A second
     pass of hand verification found the remaining waste was not garbage but
     the WRONG FILING ABOUT A REAL DEAL -- bylaw amendments, merger-agreement
     amendments, termination notices. Each announces itself:

         "As previously disclosed in the Current Report on Form 8-K filed
          ... on October 25, 2021"                              (Dawson)
         "entered into an amendment to the Agreement and Plan of Merger,
          dated as of February 22, 2022"                        (TEGNA)
         "the Agreement and Plan of Merger, dated as of May 27, 2022"  (TXMD)

     A filing that points at an earlier agreement is not that agreement. These
     are now skipped, and the referenced date is returned as a hint so the
     caller can search near it instead.

  6. FINANCING DOCUMENTS REJECTED, AND MERGER LANGUAGE MUST APPEAR EARLY.
     Oldest-first surfaced a second problem: credit agreements. Spirit
     Airlines resolved to a March 2021 8-K carrying a confidential credit
     agreement; Southwest Gas to a TERM LOAN AGREEMENT; Centennial to a
     "Third Amendment" to a credit facility. All three are 300,000+ character
     financing documents that define "Merger" and cite "Agreement and Plan of
     Merger" in their definitions -- so a keyword search anywhere in the text
     matches them. An announcement states the deal in its opening lines; a
     loan document mentions it on page 180. Both facts are now checked.

Returns (filing_date, accession, form, primary_doc) or None.
"""
import re
import time
from datetime import datetime, timedelta

import requests


# A filing whose opening identifies it as an amendment is not the announcement.
# Checked against the first stretch of text, where the title sits.
AMENDMENT_MARKERS = [
    "amendment no.",
    "amendment to agreement and plan of merger",
    "amendment to the agreement and plan of merger",
    "first amendment to",
    "second amendment to",
    "amended and restated agreement and plan of merger",
    "supplement to",
]

# Financing paperwork carries merger vocabulary in its definitions and dwarfs a
# press release in length, so it wins any keyword race. Identified by its own
# opening lines, which is where these documents name themselves.
FINANCING_MARKERS = [
    "credit agreement", "term loan agreement", "loan agreement",
    "indenture", "revolving credit", "note purchase agreement",
    "security agreement", "pledge agreement", "guaranty agreement",
    "confidential information contain",
]

# What Item 1.01 says the agreement IS. Taken verbatim from the filings that
# wasted verification time: a construction loan extension, a repurchase
# agreement amendment, a revolving credit amendment, a lease amendment, a
# bylaw amendment. All real 8-Ks, none of them mergers.
NON_MERGER_AGREEMENTS = [
    "credit agreement", "revolving credit", "term loan", "loan agreement",
    "construction loan", "repurchase agreement", "master repurchase",
    "indenture", "note purchase agreement", "security agreement",
    "amendment to lease", "lease agreement", "amendment to the bylaws",
    "amendment to bylaws", "modification and extension agreement",
    "employment agreement", "underwriting agreement", "at-the-market",
    "equity distribution agreement", "registration rights agreement",
    "forbearance agreement", "waiver and amendment",
]

# Phrases that mean "this filing is about an agreement signed earlier". The
# announcement never says these -- it IS the earlier agreement.
BACKREFERENCE_MARKERS = [
    "as previously disclosed",
    "as previously announced",
    "previously reported",
    "entered into an amendment to the agreement and plan of merger",
    "amendment to the merger agreement",
    "announces termination",
    "terminated the merger agreement",
    "termination of the merger agreement",
]

# "the Agreement and Plan of Merger, dated as of February 22, 2022" -- when a
# filing cites an agreement date earlier than its own, it is a follow-up and
# the cited date is where the announcement actually lives.
AGREEMENT_DATE_RE = re.compile(
    r'(?:agreement\s+and\s+plan\s+of\s+merger|merger\s+agreement)[^.]{0,60}?'
    r'dated\s+as\s+of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})',
    re.IGNORECASE)

# How far into a document merger language may appear and still count. An
# announcement leads with the deal. A credit agreement mentions it deep in
# definitions. TEGNA's real announcement said "TEGNA to be Acquired" in the
# first hundred characters.
EARLY_WINDOW = 4000

# Announcement language proper. A filing must look like a NEW deal being
# struck, not an existing one being adjusted.
ANNOUNCEMENT_HINTS = [
    "entered into an agreement and plan of merger",
    "entered into a definitive",
    "have entered into",
    "announced today",
    "announced that it has entered",
    "definitive agreement",
    "agreement and plan of merger",
]


def _looks_like_amendment(text):
    head = (text or "")[:1500].lower()
    return any(m in head for m in AMENDMENT_MARKERS)


def _looks_like_financing(text):
    """Credit agreements, term loans and indentures name themselves up front."""
    head = (text or "")[:2000].lower()
    return any(m in head for m in FINANCING_MARKERS)


def _referenced_agreement_date(text, own_date):
    """
    The agreement date a filing cites, when it is earlier than the filing's own
    date. Returns 'YYYY-MM-DD' or None.
    """
    m = AGREEMENT_DATE_RE.search(text or "")
    if not m:
        return None
    try:
        cited = datetime.strptime(m.group(1).replace(",", ""), "%B %d %Y")
    except Exception:
        return None
    try:
        own = datetime.strptime(own_date[:10], "%Y-%m-%d")
    except Exception:
        return None
    # a few days' slack: an announcement 8-K is filed within days of signing
    if cited < own - timedelta(days=5):
        return cited.strftime("%Y-%m-%d")
    return None


def _is_followup(text):
    """A filing that points back at an earlier agreement is not the announcement."""
    head = (text or "")[:4000].lower()
    return any(m in head for m in BACKREFERENCE_MARKERS)


def _item_101_text(text, span=1200):
    """
    The opening of Item 1.01, where an 8-K states what agreement was signed.

    In an 8-K body the first 2,000 characters are cover-page boilerplate --
    company name, address, check-boxes -- so a check anchored to the start of
    the document reads none of the substance. Item 1.01 is where the filing
    says what it actually is.
    """
    if not text:
        return ""
    m = re.search(r'item\s*1\.01[^a-z]{0,40}(entry\s+into\s+a\s+material\s+definitive\s+agreement)?',
                  text, re.IGNORECASE)
    if not m:
        return ""
    start = m.end()
    return text[start:start + span].lower()


def _item_101_is_not_a_merger(text):
    """
    True when Item 1.01 describes something other than a merger.

    Returns False when no Item 1.01 is found -- absence of the heading is not
    evidence either way, and press releases filed as exhibits have no item
    headings at all.
    """
    body = _item_101_text(text)
    if not body:
        return False
    # a merger named in the same breath outranks any other agreement mentioned
    if any(s in body for s in ("agreement and plan of merger", "merger agreement",
                               "definitive merger", "plan of merger")):
        return False
    return any(k in body for k in NON_MERGER_AGREEMENTS)


def _merger_language_is_early(text, merger_signals):
    """
    True when merger language appears in the opening stretch. A deal
    announcement leads with the deal; a 300,000-character loan document
    mentions "Agreement and Plan of Merger" in a definitions section far in.
    """
    head = (text or "")[:EARLY_WINDOW].lower()
    return any(s in head for s in merger_signals)


def find_announcement_8k_backward(cik, from_date_str, headers,
                                  lookback_days=240,
                                  merger_signals=None,
                                  text_fetcher=None,
                                  irrelevant_signals=None,
                                  hint_out=None):
    """
    cik            zero-padded CIK string
    from_date_str  the proxy's filing date, 'YYYY-MM-DD' -- search back from here
    lookback_days  a proxy follows its announcement by roughly 1-6 months.
                   240 days covers the slow ones. Wider reaches into whatever
                   the company did the year before -- which is exactly how
                   iRobot came back dated a year early at the wrong price.
    text_fetcher   function(url) -> text. Pass main._get_text_for_validation.
    hint_out       optional list. Agreement dates cited by rejected follow-up
                   filings are appended here, so a caller that finds nothing
                   knows where the announcement actually is.
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

    # NEWEST first, inside a tight window. Oldest-first was a workaround for
    # amendments outranking originals; amendments are now rejected by name, so
    # the ordering can go back to what is actually true -- the announcement
    # nearest the proxy is the one the proxy is about.
    candidates.sort(key=lambda x: x[4], reverse=True)

    if candidates:
        print(f"    [Lookback] CIK {cik}: checking up to {min(len(candidates), 25)} filings within {lookback_days}d, newest first")

    fallback = None
    for date_str, acc, form, doc, _ in candidates[:25]:
        acc_clean = acc.replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{int(cik)}/{acc_clean}/{doc}")
        text = text_fetcher(url) if text_fetcher else None
        if not text:
            continue
        low = text.lower()

        if not any(s in low for s in merger_signals):
            continue

        # a term loan is not a merger announcement, however often it says "Merger"
        if _looks_like_financing(text):
            continue

        # ...and neither is a lease, a repurchase agreement or a bylaw change,
        # each of which says so plainly in Item 1.01
        if _item_101_is_not_a_merger(text):
            continue

        # an amendment, a termination notice or a bylaw change that references
        # an earlier agreement -- the announcement is that earlier filing
        if _is_followup(text):
            hint = _referenced_agreement_date(text, date_str)
            if hint and hint_out is not None:
                hint_out.append(hint)
            continue

        # ...and the deal must be the subject, not a definition on page 180
        if not _merger_language_is_early(text, merger_signals):
            continue

        # a different transaction type wearing merger words
        if any(s in low for s in irrelevant_signals) and not any(
            s in low for s in ('agreement and plan of merger', 'merger agreement')
        ):
            continue

        if _looks_like_amendment(text):
            # remember it in case nothing better turns up, but keep looking
            if fallback is None:
                fallback = (date_str, acc, form, doc)
            continue

        # prefer a filing that reads like a new deal rather than a procedural one
        if any(h in low for h in ANNOUNCEMENT_HINTS):
            return date_str, acc, form, doc
        if fallback is None:
            fallback = (date_str, acc, form, doc)

    return fallback