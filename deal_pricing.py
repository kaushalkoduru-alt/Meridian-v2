"""
BLENDED CONSIDERATION — what a holder actually receives

Every screen shows the headline price. For deals with an election, a collar, or
a cash-and-stock split, that number is not what anyone gets.

    Globalstar, announced April 2026, displayed everywhere as $90.00.
    Real terms: $90.00 cash OR 0.3210 Amazon shares, cash capped at 40% of
    outstanding, and the stock leg itself collared at $90.00. A holder electing
    all cash receives 40% at $90.00 and 60% converted to Amazon stock. At the
    time of writing that blends to $88.86, not $90.00.

The gap was small that day only because the two legs happened to sit near
parity. It is unbounded: Amazon falls 20% and the displayed spread stays
positive on a deal that is underwater.

WHY THIRTEEN BARRIERS

A wrong blended number is worse than no blended number. Showing $88.86 when the
truth is $72 is a bigger failure than showing $90.00 and flagging that it is
incomplete. So every computed value passes thirteen independent checks, and any
single failure falls back to the headline.

Every barrier records the values it compared, not just a verdict. Without the
numbers there is no way to tell whether a threshold is too tight or the
extraction was wrong -- and that distinction is the whole basis for loosening a
barrier later. Barriers get relaxed on evidence, the way the spread bounds were:
six deals flagged, all six checked by hand, all six correct, threshold widened
with a note saying why.
"""

from datetime import datetime, timedelta

# ── barrier identifiers ───────────────────────────────────────────────────────
B_EXTRACTION   = 1   # the model found the fields at all
B_FIELD_SANITY = 2   # values are within possible ranges
B_LEG_PARITY   = 3   # cash leg and stock leg are comparable at announcement
B_PLAUSIBLE    = 4   # blended value implies a believable spread
B_DIVERGENCE   = 5   # blended is near the headline, not wildly off
B_QUOTE_MATCH  = 6   # the cash figure appears in the filing quote
B_DETERMINISM  = 7   # the model gives the same answer twice
B_SHADOW       = 8   # handled by the caller, not here
B_PRICE_FRESH  = 9   # acquirer quote is current
B_COMPLETENESS = 10  # every field this structure needs is present
B_PREMIUM      = 11  # blended reproduces the premium the filing states
B_TICKER_IN_DOC = 12 # acquirer ticker appears in the filing text
B_MOVEMENT     = 13  # value did not jump without the acquirer moving

BARRIER_NAMES = {
    B_EXTRACTION:   "extraction produced the required fields",
    B_FIELD_SANITY: "field values are within possible ranges",
    B_LEG_PARITY:   "cash and stock legs are comparable at announcement",
    B_PLAUSIBLE:    "blended value implies a believable spread",
    B_DIVERGENCE:   "blended value is near the headline",
    B_QUOTE_MATCH:  "cash figure appears in the filing quote",
    B_DETERMINISM:  "model gave the same answer on both extractions",
    B_SHADOW:       "shadow mode",
    B_PRICE_FRESH:  "acquirer price is current",
    B_COMPLETENESS: "all fields required by this structure are present",
    B_PREMIUM:      "blended value reproduces the premium stated in the filing",
    B_TICKER_IN_DOC: "acquirer ticker appears in the filing",
    B_MOVEMENT:     "value did not jump without the acquirer moving",
}

# ── thresholds ────────────────────────────────────────────────────────────────
# Deliberately explicit. Each one is a number someone chose, and each should be
# revisited against logged failures rather than defended on principle.
LEG_PARITY_TOLERANCE   = 0.30   # legs within 30% of each other at announcement
PLAUSIBLE_SPREAD_MIN   = -15.0  # blended vs current price, percent
PLAUSIBLE_SPREAD_MAX   = 80.0
MAX_DIVERGENCE         = 0.45   # blended within 45% of headline
PREMIUM_TOLERANCE      = 0.12   # computed premium within 12 points of stated
PRICE_MAX_SESSIONS     = 1      # acquirer quote may be one closed session behind
PRICE_ABSOLUTE_MAX_DAYS = 10    # outer bound, catches a feed that stopped updating
MAX_JUMP_UNEXPLAINED   = 0.25   # blended move without a matching acquirer move

# Structures and the fields each one cannot be computed without.
REQUIRED_FIELDS = {
    'ELECTION_CAPPED': ('cash', 'ratio', 'acquirer_ticker', 'cash_cap'),
    'ELECTION_UNCAPPED': ('cash', 'ratio', 'acquirer_ticker'),
    'CASH_AND_STOCK': ('cash', 'ratio', 'acquirer_ticker'),
    'COLLAR': ('ratio', 'acquirer_ticker', 'collar_low', 'collar_high'),
    'CASH_ONLY': ('cash',),
}


def sessions_since(bar_date, now=None):
    """
    How many trading sessions have CLOSED since a daily bar's date.

    Barrier 9 asks whether the acquirer price is the most recent one available.
    Measuring that in elapsed hours gets it wrong in a specific and predictable
    way: yfinance stamps a daily bar at midnight ET, so Friday's close reads as
    16 hours old the instant it exists and 70 hours old by Sunday. A 30-hour
    limit therefore blocks every weekend scan and every Monday pre-market scan
    -- while Friday's close is, on a Sunday, simply the correct current price.
    Nothing newer exists.

    Counting sessions instead answers the question that matters. Weekends do not
    age a quote. Two weekdays do.

    Known limitation: this counts weekdays, not exchange holidays, so a bar from
    the day before a market holiday reads one session older than it truly is.
    That errs toward blocking, which is the safe direction, and affects roughly
    nine days a year.
    """
    now = now or datetime.utcnow()
    if bar_date is None:
        return None
    d = bar_date.date() if hasattr(bar_date, 'date') else bar_date
    today = now.date()
    if d > today:
        return 0
    sessions = 0
    cur = d
    while cur < today:
        cur += timedelta(days=1)
        if cur.weekday() < 5:          # Mon-Fri
            sessions += 1
    # The session that closes today has not closed yet if it is still early;
    # treat today as not-yet-a-closed-session before 21:00 UTC (16:00 ET).
    if today.weekday() < 5 and now.hour < 21 and sessions > 0:
        sessions -= 1
    return sessions


class BarrierResult:
    """One barrier's verdict plus the numbers it compared."""

    def __init__(self, barrier, passed, detail):
        self.barrier = barrier
        self.passed = passed
        self.detail = detail

    def __repr__(self):
        mark = "pass" if self.passed else "FAIL"
        return f"[{self.barrier:>2}] {mark}  {BARRIER_NAMES[self.barrier]}: {self.detail}"


def _f(v):
    """Float or None. Strings arrive from JSON and from the CSV round trip."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_structure(terms):
    """
    Which structure is this, based on the fields present.
    Returns a key into REQUIRED_FIELDS, or None when nothing fits.

    A NOTE ON THE DANGEROUS CASE
    Classifying from present fields alone means a capped election whose cap was
    dropped in extraction looks identical to an uncapped one -- and uncapped
    computes a different, higher number without complaint. That is worse than a
    block: it is a confident wrong answer.

    So when the filing says the consideration is capped or prorated, the caller
    passes structure_hint='ELECTION_CAPPED' (deal_flags already knows this from
    the ELECTION flag). A hint that cannot be satisfied classifies AS the hinted
    structure anyway, so the completeness barrier sees the missing field and
    blocks, rather than the deal quietly becoming something else.
    """
    hint = terms.get('structure_hint')
    cash = _f(terms.get('cash'))
    ratio = _f(terms.get('ratio'))
    cap = _f(terms.get('cash_cap'))
    lo, hi = _f(terms.get('collar_low')), _f(terms.get('collar_high'))

    # An unsatisfiable hint still wins, so completeness can catch the gap.
    if hint in REQUIRED_FIELDS:
        return hint

    if ratio and (lo is not None or hi is not None) and not cash:
        return 'COLLAR'
    if cash and ratio and cap is not None:
        return 'ELECTION_CAPPED'
    if cash and ratio:
        # An election without a cap and a fixed cash+stock split compute the
        # same way from here; the distinction matters for wording, not math.
        return 'ELECTION_UNCAPPED' if terms.get('is_election') else 'CASH_AND_STOCK'
    if cash and not ratio:
        return 'CASH_ONLY'
    return None


def stock_leg_value(terms, acquirer_price):
    """
    What the stock half of the consideration is worth right now.

    Split out of compute_blended because the display needs it as its own
    number -- "0.3210 Amazon shares, worth $84.31 today" is the sentence that
    makes a blended value legible, and a second copy of the collar rules
    written for the frontend would be a second place for them to go wrong.

    Returns None when this deal has no stock leg or no acquirer price.
    """
    ratio = _f(terms.get('ratio'))
    if ratio is None or acquirer_price is None:
        return None
    lo, hi = _f(terms.get('collar_low')), _f(terms.get('collar_high'))
    # A collar fixes value inside the band and fixes the share count outside it.
    if lo is not None and hi is not None:
        if acquirer_price < lo:
            return ratio * lo
        if acquirer_price > hi:
            return ratio * hi
        return ratio * acquirer_price
    if hi is not None:
        # A one-sided cap: the stock leg cannot be worth more than hi.
        return min(ratio * acquirer_price, hi)
    return ratio * acquirer_price


def compute_blended(terms, acquirer_price):
    """
    The value a holder actually receives, at the acquirer's current price.
    Returns (value, explanation) or (None, reason).
    """
    structure = classify_structure(terms)
    if not structure:
        return None, "structure could not be classified from the extracted fields"

    # Refuse before computing. A structure hint deliberately classifies a deal
    # as capped even when the cap is missing, so completeness can block it --
    # which means the math must never assume the field arrived.
    missing = [f for f in REQUIRED_FIELDS[structure] if terms.get(f) in (None, "")]
    if missing:
        return None, f"{structure} is missing {', '.join(missing)}"

    cash = _f(terms.get('cash'))
    ratio = _f(terms.get('ratio'))
    cap = _f(terms.get('cash_cap'))

    if structure == 'CASH_ONLY':
        return cash, f"${cash:.2f} in cash"

    if acquirer_price is None:
        return None, "no acquirer price available"

    stock_leg = stock_leg_value(terms, acquirer_price)

    if structure == 'COLLAR':
        return round(stock_leg, 2), f"{ratio} shares, collared, currently ${stock_leg:.2f}"

    if structure == 'ELECTION_CAPPED':
        blended = round(cap * cash + (1 - cap) * stock_leg, 2)
        return blended, (
            f"${cash:.2f} cash for up to {cap*100:.0f}% of shares, the rest "
            f"converting to {ratio} acquirer shares currently worth "
            f"${stock_leg:.2f}"
        )

    # Uncapped election: a holder can take all cash, so cash is the floor and
    # the rational choice is whichever leg is worth more.
    if structure == 'ELECTION_UNCAPPED':
        blended = round(max(cash, stock_leg), 2)
        return blended, (
            f"holders elect ${cash:.2f} cash or {ratio} shares worth "
            f"${stock_leg:.2f}; uncapped, so the better leg applies"
        )

    # Fixed cash-and-stock: both, not either.
    blended = round(cash + stock_leg, 2)
    return blended, (
        f"${cash:.2f} cash plus {ratio} acquirer shares worth ${stock_leg:.2f}"
    )


def run_barriers(terms, headline_price, target_price, acquirer_price,
                 acquirer_price_time=None, filing_text="", filing_quote="",
                 stated_premium=None, unaffected_price=None,
                 second_extraction=None, previous_blended=None,
                 previous_acquirer_price=None):
    """
    Every barrier runs, always. Nothing short-circuits.

    A first-failure-and-stop design would hide the fact that a deal failed four
    checks rather than one, and the failure distribution across many deals is
    what tells you whether a threshold is too tight.

    Returns (blended_or_None, explanation, [BarrierResult]).
    """
    results = []
    structure = classify_structure(terms)

    # ── 1 · extraction produced something ────────────────────────────────────
    got = [k for k in ('cash', 'ratio', 'acquirer_ticker', 'cash_cap',
                       'collar_low', 'collar_high') if terms.get(k) not in (None, "")]
    ok = bool(structure)
    results.append(BarrierResult(B_EXTRACTION, ok,
        f"fields present: {got or 'none'}; structure: {structure or 'unclassifiable'}"))

    # ── 10 · completeness for this structure ─────────────────────────────────
    if structure:
        need = REQUIRED_FIELDS[structure]
        missing = [f for f in need if terms.get(f) in (None, "")]
        ok = not missing
        results.append(BarrierResult(B_COMPLETENESS, ok,
            f"{structure} requires {need}; missing: {missing or 'nothing'}"))
    else:
        results.append(BarrierResult(B_COMPLETENESS, False,
            "no structure, so required fields cannot be determined"))

    # ── 2 · field sanity ─────────────────────────────────────────────────────
    problems = []
    ratio, cap = _f(terms.get('ratio')), _f(terms.get('cash_cap'))
    cash = _f(terms.get('cash'))
    lo, hi = _f(terms.get('collar_low')), _f(terms.get('collar_high'))
    if ratio is not None and not (0 < ratio < 100):
        problems.append(f"ratio {ratio} outside (0, 100)")
    if cap is not None and not (0 <= cap <= 1):
        problems.append(f"cash_cap {cap} outside [0, 1]")
    if cash is not None and not (0 < cash < 10000):
        problems.append(f"cash {cash} outside (0, 10000)")
    if lo is not None and hi is not None and lo >= hi:
        problems.append(f"collar_low {lo} >= collar_high {hi}")
    results.append(BarrierResult(B_FIELD_SANITY, not problems,
        "; ".join(problems) if problems else "all values within possible ranges"))

    # ── 9 · acquirer price freshness ─────────────────────────────────────────
    if structure in (None, 'CASH_ONLY'):
        results.append(BarrierResult(B_PRICE_FRESH, True,
            "no acquirer price needed for this structure"))
    elif acquirer_price is None:
        results.append(BarrierResult(B_PRICE_FRESH, False, "no acquirer price"))
    elif acquirer_price_time is None:
        results.append(BarrierResult(B_PRICE_FRESH, False,
            f"price ${acquirer_price:.2f} has no timestamp, so staleness is unknowable"))
    else:
        sessions = sessions_since(acquirer_price_time)
        days = (datetime.utcnow() - acquirer_price_time).days
        if days > PRICE_ABSOLUTE_MAX_DAYS:
            results.append(BarrierResult(B_PRICE_FRESH, False,
                f"acquirer price ${acquirer_price:.2f} is {days}d old, past the "
                f"{PRICE_ABSOLUTE_MAX_DAYS}d outer bound -- the feed has stopped updating"))
        else:
            ok = sessions is not None and sessions <= PRICE_MAX_SESSIONS
            when = acquirer_price_time.strftime('%Y-%m-%d')
            results.append(BarrierResult(B_PRICE_FRESH, ok,
                f"acquirer price ${acquirer_price:.2f} from {when} is {sessions} "
                f"closed session(s) behind (limit {PRICE_MAX_SESSIONS}); "
                f"{days}d elapsed, which weekends inflate"))

    # ── 12 · acquirer ticker appears in the filing ───────────────────────────
    tk = (terms.get('acquirer_ticker') or "").strip().upper()
    if not tk:
        results.append(BarrierResult(B_TICKER_IN_DOC, structure == 'CASH_ONLY',
            "no acquirer ticker extracted"))
    else:
        found = tk in (filing_text or "").upper()
        results.append(BarrierResult(B_TICKER_IN_DOC, found,
            f"'{tk}' {'appears' if found else 'does NOT appear'} in the filing text"))

    # ── 6 · cash figure appears in the filing quote ──────────────────────────
    if cash is None:
        results.append(BarrierResult(B_QUOTE_MATCH, structure == 'COLLAR',
            "no cash figure to check"))
    else:
        q = filing_quote or filing_text or ""
        variants = [f"{cash:.2f}", f"{cash:.0f}" if cash == int(cash) else f"{cash:.2f}",
                    f"{cash:g}"]
        found = any(v in q for v in variants)
        results.append(BarrierResult(B_QUOTE_MATCH, found,
            f"${cash} {'appears' if found else 'does NOT appear'} in the filing quote"))

    # ── 3 · leg parity at announcement ───────────────────────────────────────
    if cash and ratio and acquirer_price:
        stock_leg = ratio * acquirer_price
        if stock_leg > 0:
            drift = abs(cash - stock_leg) / max(cash, stock_leg)
            ok = drift <= LEG_PARITY_TOLERANCE
            results.append(BarrierResult(B_LEG_PARITY, ok,
                f"cash ${cash:.2f} vs stock leg ${stock_leg:.2f} "
                f"({drift*100:.1f}% apart, tolerance {LEG_PARITY_TOLERANCE*100:.0f}%)"))
        else:
            results.append(BarrierResult(B_LEG_PARITY, False, "stock leg computed to zero"))
    else:
        results.append(BarrierResult(B_LEG_PARITY, structure in ('CASH_ONLY', 'COLLAR'),
            "not a two-leg structure, parity does not apply"))

    # ── the computation itself ───────────────────────────────────────────────
    blended, explanation = compute_blended(terms, acquirer_price)

    # ── 4 · blended implies a believable spread ──────────────────────────────
    if blended is None or not target_price:
        results.append(BarrierResult(B_PLAUSIBLE, False,
            "no blended value or no target price to compare against"))
    else:
        sp = ((blended - target_price) / target_price) * 100
        ok = PLAUSIBLE_SPREAD_MIN <= sp <= PLAUSIBLE_SPREAD_MAX
        results.append(BarrierResult(B_PLAUSIBLE, ok,
            f"blended ${blended:.2f} vs target ${target_price:.2f} = {sp:+.2f}% "
            f"(band {PLAUSIBLE_SPREAD_MIN:+.0f}%..{PLAUSIBLE_SPREAD_MAX:+.0f}%)"))

    # ── 5 · blended is near the headline ─────────────────────────────────────
    if blended is None or not headline_price:
        results.append(BarrierResult(B_DIVERGENCE, False,
            "no blended value or no headline to compare against"))
    else:
        div = abs(blended - headline_price) / headline_price
        ok = div <= MAX_DIVERGENCE
        results.append(BarrierResult(B_DIVERGENCE, ok,
            f"blended ${blended:.2f} vs headline ${headline_price:.2f} "
            f"({div*100:.1f}% apart, limit {MAX_DIVERGENCE*100:.0f}%)"))

    # ── 11 · blended reproduces the stated premium ───────────────────────────
    # The strongest check available: an independent number the company published.
    if stated_premium is None or unaffected_price in (None, 0):
        results.append(BarrierResult(B_PREMIUM, True,
            "filing states no premium, or no unaffected price to measure from"))
    elif blended is None:
        results.append(BarrierResult(B_PREMIUM, False, "no blended value to check"))
    else:
        computed = (blended - unaffected_price) / unaffected_price
        gap = abs(computed - stated_premium)
        ok = gap <= PREMIUM_TOLERANCE
        results.append(BarrierResult(B_PREMIUM, ok,
            f"filing states {stated_premium*100:.1f}% premium; blended ${blended:.2f} "
            f"over unaffected ${unaffected_price:.2f} gives {computed*100:.1f}% "
            f"({gap*100:.1f} points apart, tolerance {PREMIUM_TOLERANCE*100:.0f})"))

    # ── 7 · determinism across two extractions ───────────────────────────────
    if second_extraction is None:
        results.append(BarrierResult(B_DETERMINISM, True,
            "single extraction, determinism not tested"))
    else:
        diffs = []
        for k in ('cash', 'ratio', 'cash_cap', 'collar_low', 'collar_high'):
            a, b = _f(terms.get(k)), _f(second_extraction.get(k))
            if a != b:
                diffs.append(f"{k}: {a} vs {b}")
        a_tk = (terms.get('acquirer_ticker') or '').upper()
        b_tk = (second_extraction.get('acquirer_ticker') or '').upper()
        if a_tk != b_tk:
            diffs.append(f"acquirer_ticker: {a_tk} vs {b_tk}")
        results.append(BarrierResult(B_DETERMINISM, not diffs,
            "; ".join(diffs) if diffs else "both extractions agreed"))

    # ── 13 · movement without a matching acquirer move ───────────────────────
    if blended is None or previous_blended in (None, 0):
        results.append(BarrierResult(B_MOVEMENT, True,
            "no previous value to compare against"))
    else:
        moved = abs(blended - previous_blended) / previous_blended
        if previous_acquirer_price and acquirer_price:
            acq_moved = abs(acquirer_price - previous_acquirer_price) / previous_acquirer_price
        else:
            acq_moved = None
        if moved <= MAX_JUMP_UNEXPLAINED:
            ok, why = True, f"blended moved {moved*100:.1f}%, within {MAX_JUMP_UNEXPLAINED*100:.0f}%"
        elif acq_moved is not None and acq_moved >= moved * 0.5:
            ok, why = True, (f"blended moved {moved*100:.1f}% but the acquirer moved "
                             f"{acq_moved*100:.1f}%, which explains it")
        else:
            ok, why = False, (f"blended moved {moved*100:.1f}% while the acquirer moved "
                              f"{(acq_moved*100 if acq_moved is not None else 0):.1f}%")
        results.append(BarrierResult(B_MOVEMENT, ok, why))

    passed_all = all(r.passed for r in results)
    return (blended if passed_all else None), explanation, results


def barrier_report(ticker, blended, headline, results):
    """Multi-line log block. Shows every barrier, not only the failures."""
    failed = [r for r in results if not r.passed]
    head = (f"[Pricing] {ticker}: " +
            (f"blended ${blended:.2f} vs headline ${headline:.2f} — all barriers passed"
             if blended is not None
             else f"headline ${headline:.2f} retained — {len(failed)} barrier(s) failed"))
    lines = [f"    {r}" for r in results]
    return head, lines


def failure_tally(all_results):
    """
    How often each barrier blocks, across many deals.

    This is the number that decides whether a threshold is too tight. A barrier
    that fires constantly is either catching a real recurring problem or is set
    wrong, and the only way to tell is to check the blocked deals by hand --
    the same way the spread bounds were widened after six flagged deals all
    turned out to be correct.
    """
    tally = {}
    for results in all_results:
        for r in results:
            if not r.passed:
                tally[r.barrier] = tally.get(r.barrier, 0) + 1
    return dict(sorted(tally.items(), key=lambda kv: -kv[1]))