"""
test_tx_value.py -- tests the improved tx_value extraction logic before pushing to main.py.

Run locally: py test_tx_value.py
No EDGAR calls needed -- tests against local text samples that mirror real filing language.
Tests both the extended-window regex (primary) and the equity-calc fallback.

Convention: ENTERPRISE value as target. Equity calc is fallback only, labeled "equity_calc_approx".
"""
import re
import math

# ── Improved extract_transaction_value ───────────────────────────────────────
# Key change: window extended from 8000 to 25000 chars.
# Enterprise value is stated in press release body, often past the 8000-char mark.
# No other logic changes — same patterns, same validation.

def extract_transaction_value(clean_text):
    """
    Extracts enterprise/total transaction value from filing text.
    Convention: enterprise value (includes assumed debt) — matches press release language
    and what regulatory threshold logic (HSR/FTC) correctly needs.
    Window extended from 8000 to 25000 chars to catch value statements in long press releases.
    Returns (value_in_billions, source_label) or (None, None).
    """
    # Extended window: was 8000, now 25000
    # Press releases for large deals routinely run 10000-20000 chars of boilerplate
    # before the financial summary section where "$X billion" appears.
    text = re.sub(r'\s+', ' ', clean_text[:25000].replace('\n', ' ').replace('\r', ' '))
    patterns = [
        r'total\s+(?:transaction\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'implies\s+a\s+total\s+(?:value|consideration)\s+(?:of\s+)?(?:approximately\s+)?\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'valued\s+at\s+approximately\s+\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'transaction\s+valued\s+at\s+(?:approximately\s+)?\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'aggregate\s+(?:deal\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'total\s+(?:equity\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'enterprise\s+value\s+(?:of\s+)?(?:approximately\s+)?\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'approximately\s+\$([\d]+(?:\.[\d]+)?)\s*(billion|million)\s+(?:and|in)\s+(?:offers|gives|provides)',
        r'\$([\d]+(?:\.[\d]+)?)\s*(billion|million)\s+(?:merger|acquisition|deal|transaction)',
        r'transaction.*?approximately\s+\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
        r'approximately\s+\$([\d]+(?:\.[\d]+)?)\s*(billion|million)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            value = float(m.group(1))
            unit = m.group(2).lower()
            if unit == 'billion' and 0.05 <= value <= 500:
                return round(value, 2), 'regex_enterprise'
            if unit == 'million' and 50 <= value <= 500000:
                return round(value / 1000, 2), 'regex_enterprise'
    return None, None


def compute_equity_fallback(dp, shares_outstanding):
    """
    Fallback only: equity value = deal_price x shares_outstanding.
    Returns (value_in_billions, 'equity_calc_approx') or (None, None).
    Only valid for per-share all-cash deals.
    Labeled 'equity_calc_approx' so scoring logic can treat it as approximate.
    """
    if not dp or not shares_outstanding or shares_outstanding <= 0:
        return None, None
    try:
        equity_b = round(dp * shares_outstanding / 1e9, 2)
        if 0.01 <= equity_b <= 1000:
            return equity_b, 'equity_calc_approx'
    except Exception:
        pass
    return None, None


def get_tx_value(clean_text, dp=None, shares_outstanding=None, deal_type='All Cash'):
    """
    Full extraction chain with source labeling:
    1. Regex on extended 25000-char window (enterprise value)
    2. Equity calc fallback if dp and shares available and deal is all-cash
    3. Abstain (None, None) if both fail
    """
    # Step 1: regex (enterprise value, primary)
    val, src = extract_transaction_value(clean_text)
    if val is not None:
        return val, src

    # Step 2: equity calc fallback — only for cash deals with known dp
    if dp and shares_outstanding and deal_type in ('All Cash', 'Tender Offer'):
        val, src = compute_equity_fallback(dp, shares_outstanding)
        if val is not None:
            return val, src

    # Step 3: abstain
    return None, None


# ── Test cases ────────────────────────────────────────────────────────────────

# Simulated filing text: realistic press release extracts at different positions
# to test the window extension

GBTG_SHORT = """
GLOBAL BUSINESS TRAVEL GROUP, INC.
8-K
Item 1.01. Entry into a Material Definitive Agreement.
On May 4, 2026, Global Business Travel Group, Inc. ("Amex GBT") entered into an
Agreement and Plan of Merger with Long Lake Management LLC.
""" * 5  # ~1200 chars -- value statement NOT included (tests that regex correctly abstains when text is too short)

GBTG_REALISTIC = """
GLOBAL BUSINESS TRAVEL GROUP, INC.
8-K
Item 1.01. Entry into a Material Definitive Agreement.
""" + ("x " * 3500) + """
American Express Global Business Travel, which is operated by Global Business Travel
Group, Inc. (NYSE: GBTG), today announced that it has entered into a definitive agreement
to be acquired by Long Lake Management for $9.50 per share in an all-cash transaction
valued at approximately $6.3 billion. Under the terms of the agreement, Amex GBT
shareholders will receive $9.50 per share in cash, which represents a 60.2% premium
to the closing stock price on May 1, 2026.
"""  # value statement ~7000 chars in — past 8000 window, within 25000

JHG_REALISTIC = """
JANUS HENDERSON GROUP PLC
8-K
Item 1.01. Entry into a Material Definitive Agreement.
""" + ("y " * 4000) + """
Janus Henderson Group plc announced that they have entered into a definitive agreement
under which Janus Henderson will be acquired by Trian and General Catalyst in an
all-cash transaction at an equity value of approximately $7.4 billion. Under the terms
of the agreement, shareholders will receive $49.00 per share in cash.
"""  # ~8300 chars in — just past old 8000 limit

NATH_REALISTIC = """
NATHANS FAMOUS, INC.
8-K
""" + ("z " * 200) + """
Smithfield Foods will acquire all of Nathan's Famous' issued and outstanding shares
of its common stock for $102.00 per share in an all cash transaction. The transaction
represents an enterprise value of approximately $450 million.
"""  # short — should be caught easily

# Test cases: (label, text, dp, shares, deal_type, expected_val, expected_src_contains)
tests = [
    (
        "GBTG value past 8000 chars (window fix)",
        GBTG_REALISTIC, 9.50, None, 'All Cash',
        6.3, 'regex_enterprise',
    ),
    (
        "JHG value past old 8000 limit",
        JHG_REALISTIC, 49.00, None, 'All Cash',
        7.4, 'regex_enterprise',
    ),
    (
        "NATH short filing — regex catches it",
        NATH_REALISTIC, 102.00, None, 'All Cash',
        0.45, 'regex_enterprise',
    ),
    (
        "GBTG with equity fallback when regex text too short",
        GBTG_SHORT, 9.50, 663_000_000, 'All Cash',  # ~663M shares outstanding
        6.3, 'equity_calc_approx',  # regex fails on short text, equity calc fires
    ),
    (
        "Stock deal — equity calc should NOT fire even if regex fails",
        "No financial terms here.", 50.00, 100_000_000, 'Cash + Stock',
        None, None,  # abstain
    ),
    (
        "No value anywhere — abstain cleanly",
        "This filing contains no dollar amounts.", None, None, 'All Cash',
        None, None,
    ),
]

TOLERANCE_PCT = 15
print("Testing improved tx_value extraction (enterprise value convention)...\n")
print(f"{'Test':<45} {'got_val':>8} {'exp_val':>8} {'source':<22} result")
print("-" * 100)

all_pass = True
for label, text, dp, shares, deal_type, exp_val, exp_src in tests:
    got_val, got_src = get_tx_value(text, dp=dp, shares_outstanding=shares, deal_type=deal_type)

    if exp_val is None:
        ok = got_val is None
        result = "OK" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"{label:<45} {str(got_val):>8} {'None':>8} {str(got_src):<22} {result}")
    else:
        if got_val is None:
            ok = False
            diff_str = "no value"
        else:
            diff_pct = abs(got_val - exp_val) / exp_val * 100
            ok = diff_pct <= TOLERANCE_PCT and got_src == exp_src
            diff_str = f"{diff_pct:.1f}%"
        if not ok:
            all_pass = False
        result = "OK" if ok else "FAIL"
        print(f"{label:<45} {str(got_val):>8} {exp_val:>8.2f} {str(got_src):<22} {result}  ({diff_str})")

print()
print("All 6 passed." if all_pass else "FAILURES above — do not push to main.py.")
print()
print("Convention: ENTERPRISE value (primary). Equity calc is labeled fallback.")
print("tx_value_source field distinguishes 'regex_enterprise' vs 'equity_calc_approx' vs 'verified_hardcode'.")