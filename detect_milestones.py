# ══════════════════════════════════════════════════════════════════════════════
# MILESTONE DETECTION — filing-confirmed only.
#
# RULE: a milestone gets status='confirmed' ONLY when an EDGAR filing proves it
# happened, and it carries the accession number as evidence. No date arithmetic.
# Anything unproven is status='pending' with NO date and NO checkmark.
# ══════════════════════════════════════════════════════════════════════════════
import re
import requests
from datetime import datetime

SEC_HEADERS = {"User-Agent": "Meridian Research contact@meridianarb.com"}

# ── the path a merger walks. order is the display order. ──
MILESTONE_PATH = [
    {"key": "announced",   "label": "Deal Announced",
     "desc": "Merger agreement announced via 8-K."},
    {"key": "proxy_filed", "label": "Proxy Filed",
     "desc": "Definitive merger proxy filed with the SEC, disclosing deal terms and the shareholder meeting."},
    {"key": "vote_scheduled", "label": "Shareholder Meeting",
     "desc": "Date the target's shareholders vote on the merger."},
    {"key": "vote_held",   "label": "Shareholder Vote Held",
     "desc": "Target shareholders voted on the merger agreement."},
    {"key": "reg_clearance", "label": "Regulatory Clearance",
     "desc": "Antitrust and sector reviews cleared or waiting periods expired."},
    {"key": "completed",   "label": "Deal Completed",
     "desc": "Merger closed; target deregistered and delisted."},
]


def _sub_url(cik):
    return f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"


def _accession_url(cik, accession, doc):
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{doc}"


# ── regex: shareholder meeting date out of proxy text ─────────────────────────
# Proxies phrase this a lot of ways. Patterns ordered most→least specific.
MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"

MEETING_PATTERNS = [
    # "special meeting ... will be held on May 14, 2026"
    re.compile(r"[Ss]pecial\s+[Mm]eeting[^.]{0,200}?will\s+be\s+held\s+on\s+(" + MONTHS + r"\s+\d{1,2},\s+20\d{2})", re.S),
    # "will be held on May 14, 2026, at 10:00 a.m."
    re.compile(r"will\s+be\s+held\s+(?:on\s+)?(" + MONTHS + r"\s+\d{1,2},\s+20\d{2})", re.S),
    # "The special meeting will be held virtually on May 14, 2026"
    re.compile(r"[Ss]pecial\s+[Mm]eeting[^.]{0,200}?on\s+(" + MONTHS + r"\s+\d{1,2},\s+20\d{2})", re.S),
    # "to be held on May 14, 2026"
    re.compile(r"to\s+be\s+held\s+(?:on\s+)?(" + MONTHS + r"\s+\d{1,2},\s+20\d{2})", re.S),
    # "meeting of stockholders ... May 14, 2026"
    re.compile(r"[Mm]eeting\s+of\s+(?:the\s+)?(?:stock|share)holders[^.]{0,160}?(" + MONTHS + r"\s+\d{1,2},\s+20\d{2})", re.S),
]

# Guard: proxies also mention the RECORD DATE, which is NOT the meeting date.
RECORD_DATE_NEAR = re.compile(r"record\s+date", re.I)


def extract_meeting_date(text, filed_date=None):
    """
    Pull the shareholder meeting date from proxy text.
    Returns (iso_date, matched_phrase) or (None, None).
    Rejects dates before the filing date (those are record dates / past events).
    """
    if not text:
        return None, None
    head = text[:120000]  # meeting date is near the top of a proxy

    for pat in MEETING_PATTERNS:
        for m in pat.finditer(head):
            raw = m.group(1)
            # reject if "record date" sits right before this match
            ctx_start = max(0, m.start() - 120)
            ctx = head[ctx_start:m.start()]
            if RECORD_DATE_NEAR.search(ctx):
                continue
            try:
                dt = datetime.strptime(raw, "%B %d, %Y")
            except ValueError:
                continue
            iso = dt.strftime("%Y-%m-%d")
            # a meeting can't be before the proxy was filed
            if filed_date and iso < filed_date:
                continue
            return iso, m.group(0)[:120].replace("\n", " ")
    return None, None


def detect_milestones(ticker, cik, filed, acquirer=None, fetch_text=None):
    """
    Build the milestone path for a deal.
    - filed: announcement date 'YYYY-MM-DD' (already verified, from the scan)
    - fetch_text: callable(url) -> str, injected so we reuse the app's fetcher
    Returns list of milestone dicts.
    """
    confirmed = {}

    # Announced is real — it's the 8-K we detected the deal from.
    confirmed["announced"] = {
        "date": filed,
        "evidence": f"Merger 8-K filed {filed}",
    }

    if not cik:
        return _assemble(confirmed)

    try:
        r = requests.get(_sub_url(cik), headers=SEC_HEADERS, timeout=12)
        if r.status_code != 200:
            return _assemble(confirmed)
        recent = r.json().get("filings", {}).get("recent", {})
    except Exception:
        return _assemble(confirmed)

    candidates = []   # Item 2.01 8-Ks awaiting text verification
    forms   = recent.get("form", [])
    dates   = recent.get("filingDate", [])
    accs    = recent.get("accessionNumber", [])
    docs    = recent.get("primaryDocument", [])
    items   = recent.get("items", [])

    for i, form in enumerate(forms):
        fdate = dates[i] if i < len(dates) else ""
        if not fdate or fdate < filed:
            continue  # only filings after the announcement matter
        acc  = accs[i] if i < len(accs) else ""
        doc  = docs[i] if i < len(docs) else ""
        itm  = items[i] if i < len(items) else ""

        # ── PROXY FILED: DEFM14A (merger proxy) or DEF 14A ──
        if form in ("DEFM14A", "DEF 14A") and "proxy_filed" not in confirmed:
            confirmed["proxy_filed"] = {
                "date": fdate,
                "evidence": f"{form} filed {fdate}, accession {acc}",
                "_cik": cik, "_acc": acc, "_doc": doc,
            }

        # ── VOTE HELD: 8-K Item 5.07 = Submission of Matters to a Vote ──
        if form == "8-K" and "5.07" in str(itm) and "vote_held" not in confirmed:
            confirmed["vote_held"] = {
                "date": fdate,
                "evidence": f"8-K Item 5.07 (shareholder vote results) filed {fdate}, accession {acc}",
            }

        # ── COMPLETED ──
        # Form 25 = delisting/deregistration. Unambiguous.
        if "completed" not in confirmed and form.startswith("25"):
            confirmed["completed"] = {
                "date": fdate,
                "evidence": f"Form {form} (delisting/deregistration) filed {fdate}, accession {acc}",
            }
        # 8-K Item 2.01 = "Completion of Acquisition OR DISPOSITION of Assets".
        # A company selling a division files the same item. So the item number
        # alone proves nothing — the text must reference THIS merger.
        elif "completed" not in confirmed and form == "8-K" and "2.01" in str(itm):
            candidates.append({
                "date": fdate, "acc": acc, "doc": doc, "cik": cik,
            })

    # ── VOTE SCHEDULED: meeting date from the proxy text ──
    px = confirmed.get("proxy_filed")
    if px and fetch_text and px.get("_doc"):
        url = _accession_url(px["_cik"], px["_acc"], px["_doc"])
        try:
            text = fetch_text(url)
            mdate, phrase = extract_meeting_date(text, filed_date=px["date"])
            if mdate:
                confirmed["vote_scheduled"] = {
                    "date": mdate,
                    "evidence": f"Meeting date disclosed in {px['_acc']}: \"{phrase}\"",
                    "disclosed": True,   # company guidance, not a past event
                }
        except Exception:
            pass

    # ── VERIFY Item 2.01 candidates: text must reference the merger ──
    if candidates and "completed" not in confirmed and fetch_text:
        for c in candidates:
            if not c.get("doc"):
                continue
            try:
                text = fetch_text(_accession_url(c["cik"], c["acc"], c["doc"]))
            except Exception:
                continue
            if not text:
                continue
            low = text[:60000].lower()
            merger_ref = "merger" in low or "merger agreement" in low
            acq_ref = bool(acquirer) and acquirer.split()[0].lower() in low
            if merger_ref and (acq_ref or not acquirer):
                confirmed["completed"] = {
                    "date": c["date"],
                    "evidence": (f"8-K Item 2.01 filed {c['date']}, accession {c['acc']} "
                                 f"(text confirms merger completion)"),
                }
                break

    # ── REGULATORY CLEARANCE: only if vote held + completed both present is it
    #    safe to infer; otherwise we do NOT claim it. Left pending by design.
    #    (Item 8.01 clearance announcements are inconsistent across filers.)

    for v in confirmed.values():
        for k in ("_cik", "_acc", "_doc"):
            v.pop(k, None)
    return _assemble(confirmed)


def _assemble(confirmed):
    out = []
    for step in MILESTONE_PATH:
        k = step["key"]
        if k in confirmed:
            c = confirmed[k]
            # a scheduled-but-future meeting is disclosed, not confirmed-past
            if c.get("disclosed") and c["date"] > datetime.utcnow().strftime("%Y-%m-%d"):
                status = "scheduled"
            else:
                status = "confirmed"
            out.append({
                "key": k, "label": step["label"], "description": step["desc"],
                "status": status, "date": c["date"], "evidence": c["evidence"],
            })
        else:
            out.append({
                "key": k, "label": step["label"], "description": step["desc"],
                "status": "pending", "date": None, "evidence": None,
            })
    return out