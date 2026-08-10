"""
test_filer_role_check.py -- validates the filer-as-acquirer detection check.

Run locally: py test_filer_role_check.py
No network calls. Tests the check_filer_role() function that goes into validate_deal().

PRIMARY check (Option A): if extracted acquirer closely matches the filer's own
company name (Jaccard >= 0.6), the filer is the acquirer not the target -> FLAG.

BACKUP check (Option B): if acquirer is undisclosed/ambiguous AND
deal_price x filer_shares < 50% of filer_market_cap, the deal is too small
relative to filer to be the filer being acquired -> FLAG.

CASE 1 vs CASE 2 detection: when flagging filer-as-acquirer, search filing text
for a listed exchange ticker pattern that isn't the filer's own ticker.
If found: "filer is acquirer, real target may be trackable: [TICKER]"
If not found: "filer is acquirer, target appears non-listed -- skip"
"""
import re

def _name_overlap_score(name_a, name_b):
    """Jaccard similarity on word sets. >= 0.6 = same entity."""
    suffixes = {'inc','corp','ltd','llc','plc','co','company','corporation',
                'incorporated','limited','holdings','group'}
    def words(s):
        return set(w for w in re.sub(r'[^a-z0-9 ]','',s.lower()).split()
                   if w not in suffixes and len(w) > 1)
    a, b = words(name_a), words(name_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def find_listed_target_ticker(filing_text, filer_ticker):
    """
    Look for a listed exchange ticker in the filing text that isn't the filer.
    Pattern: (NYSE: XYZ) or (NASDAQ: XYZ) or (AMEX: XYZ)
    Returns ticker string if found, None otherwise.
    Used to distinguish Case 1 (OTC/private target) from Case 2 (listed target).
    """
    pattern = r'\((?:NYSE|NASDAQ|AMEX|NYSE\s*American):\s*([A-Z]{1,5})\)'
    matches = re.findall(pattern, filing_text, re.IGNORECASE)
    for m in matches:
        if m.upper() != filer_ticker.upper():
            return m.upper()
    return None

def check_filer_role(
    ticker,
    company_name,
    acquirer,
    filing_text,
    deal_price=None,
    filer_shares=None,
    filer_market_cap=None,
):
    """
    Checks whether the FILER of the merger 8-K is actually the ACQUIRER
    rather than the target. Returns (flagged: bool, reason: str, listed_target: str|None).

    PRIMARY (Option A): extracted acquirer matches filer company name -> flagged.
    BACKUP (Option B): deal implied value < 50% of filer market cap -> flagged.
    Both flag-first, never auto-remove.
    """
    # Option A: same-filer check
    if acquirer and acquirer != 'Undisclosed' and company_name:
        score = _name_overlap_score(acquirer, company_name)
        if score >= 0.6:
            listed_target = find_listed_target_ticker(filing_text or '', ticker)
            if listed_target:
                reason = (
                    f"Filer \"{company_name}\" appears to be the ACQUIRER "
                    f"(extracted acquirer \"{acquirer}\" matches filer name, "
                    f"overlap {score:.2f}). Real target may be trackable: "
                    f"{listed_target} -- verify before excluding."
                )
            else:
                reason = (
                    f"Filer \"{company_name}\" appears to be the ACQUIRER "
                    f"(extracted acquirer \"{acquirer}\" matches filer name, "
                    f"overlap {score:.2f}). Target appears non-listed -- skip."
                )
            return True, reason, listed_target

    # Option B: deal-size ratio backup (when A is inconclusive)
    if deal_price and filer_shares and filer_market_cap and filer_market_cap > 0:
        implied_value = deal_price * filer_shares
        ratio = implied_value / filer_market_cap
        if ratio < 0.5:
            listed_target = find_listed_target_ticker(filing_text or '', ticker)
            reason = (
                f"Deal implied value ${implied_value/1e6:.0f}M is "
                f"{ratio*100:.0f}% of filer market cap ${filer_market_cap/1e6:.0f}M "
                f"-- filer is likely the acquirer of a smaller company."
            )
            if listed_target:
                reason += f" Real target may be trackable: {listed_target}."
            else:
                reason += " Target appears non-listed -- skip."
            return True, reason, listed_target

    return False, '', None


tests = [
    # Case 1: CLST -- filer IS the acquirer (Catalyst buying Lakeside, OTC target)
    # Option A should catch this: extracted acquirer "Catalyst Bancorp" matches filer
    {
        "label": "CLST: filer is acquirer, OTC target (Option A catches it)",
        "ticker": "CLST",
        "company_name": "Catalyst Bancorp, Inc.",
        "acquirer": "Catalyst Bancorp",
        "filing_text": "Catalyst Bancorp, Inc. (NASDAQ: CLST) today announced that it has entered into a definitive agreement to acquire Lakeside Bancshares for $19.58 per share.",
        "deal_price": 19.58,
        "filer_shares": 2_100_000,
        "filer_market_cap": 82_000_000,
        "expect_flagged": True,
        "expect_listed_target": None,  # Lakeside is OTC, no listed ticker in text
    },
    # Case 2: hypothetical where filer acquires a listed target
    # Option A catches it AND reports the trackable target ticker
    {
        "label": "Filer is acquirer, listed target trackable (Case 2)",
        "ticker": "ACQR",
        "company_name": "Acquiring Corp",
        "acquirer": "Acquiring Corp",
        "filing_text": "Acquiring Corp (NYSE: ACQR) today announced a definitive agreement to acquire Target Inc (NASDAQ: TGTI) for $25.00 per share.",
        "deal_price": 25.0,
        "filer_shares": 5_000_000,
        "filer_market_cap": 500_000_000,
        "expect_flagged": True,
        "expect_listed_target": "TGTI",
    },
    # Normal deal: filer IS the target, acquirer is different -- should PASS
    {
        "label": "Normal deal: filer is target, acquirer is different",
        "ticker": "NATH",
        "company_name": "Nathan's Famous, Inc.",
        "acquirer": "Smithfield Foods",
        "filing_text": "Smithfield Foods to acquire Nathan's Famous for $102.00 per share.",
        "deal_price": 102.0,
        "filer_shares": 4_400_000,
        "filer_market_cap": 180_000_000,
        "expect_flagged": False,
        "expect_listed_target": None,
    },
    # Option B only: acquirer extraction failed (Undisclosed) but deal size ratio catches it
    {
        "label": "Option B: undisclosed acquirer but deal too small (filer is acquirer)",
        "ticker": "BIGCO",
        "company_name": "Big Company Inc",
        "acquirer": "Undisclosed",
        "filing_text": "Big Company Inc entered into a definitive agreement to acquire a smaller company for $10.00 per share.",
        "deal_price": 10.0,
        "filer_shares": 1_000_000,   # implied deal value: $10M
        "filer_market_cap": 500_000_000,  # filer worth $500M -- ratio = 2%
        "expect_flagged": True,
        "expect_listed_target": None,
    },
    # Option B: deal IS large relative to filer -- filer is probably the target
    {
        "label": "Option B: deal size >= 50% of filer cap -- filer is probably target",
        "ticker": "SMCO",
        "company_name": "Small Company Inc",
        "acquirer": "Undisclosed",
        "filing_text": "Small Company Inc entered into a definitive agreement to be acquired.",
        "deal_price": 20.0,
        "filer_shares": 10_000_000,  # implied deal value: $200M
        "filer_market_cap": 210_000_000,  # ratio = 95% -- filer IS the target
        "expect_flagged": False,
        "expect_listed_target": None,
    },
]

print(f"{'Test':<52} {'flagged':>8} {'listed_tgt':>12} {'expected_flag':>14} {'expected_tgt':>13}  result")
print("-" * 115)
all_pass = True
for t in tests:
    flagged, reason, listed_target = check_filer_role(
        ticker=t["ticker"],
        company_name=t["company_name"],
        acquirer=t["acquirer"],
        filing_text=t["filing_text"],
        deal_price=t["deal_price"],
        filer_shares=t["filer_shares"],
        filer_market_cap=t["filer_market_cap"],
    )
    flag_ok = flagged == t["expect_flagged"]
    target_ok = listed_target == t["expect_listed_target"]
    ok = flag_ok and target_ok
    if not ok:
        all_pass = False
    status = "OK" if ok else "FAIL"
    print(f"{t['label']:<52} {str(flagged):>8} {str(listed_target):>12} "
          f"{str(t['expect_flagged']):>14} {str(t['expect_listed_target']):>13}  {status}")
    if not ok:
        print(f"  reason: {reason[:100]}")

print()
print("All 5 passed." if all_pass else "FAILURES above -- do not push to main.py.")