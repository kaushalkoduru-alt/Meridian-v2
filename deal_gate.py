"""
VERIFICATION GATE — a deal ships only when an EDGAR filing proves it exists.

This is the POSITIVE counterpart to validate_deal(). That function looks for
reasons a deal is WRONG (self-tender, same-entity, completed, aged out).
This one demands affirmative proof that the deal is REAL: a filing, in the
announcement window, whose text contains merger language, with an accession
number you can open.

Design:
  - Reuses _find_announcement_filing_for_validation (already windowed on the
    announced date, already searches 8-K / SC TO-T / SC TO-I / SC 13E-3 / SC 14D9)
  - Three verdicts: VERIFIED / WEAK / UNVERIFIED
  - SHADOW MODE by default: records the verdict, blocks nothing
  - Caches VERIFIED permanently (proof doesn't expire); re-checks WEAK and
    UNVERIFIED each cycle so a deal can graduate once its filing appears

Wire-in is two lines in the scan loop; see wire_in_notes at the bottom.
"""

VERDICT_VERIFIED   = "VERIFIED"     # filing found, merger language present
VERDICT_WEAK       = "WEAK"         # filing found in window, no merger language
VERDICT_UNVERIFIED = "UNVERIFIED"   # no filing found at all

# Flip to True only after reviewing several cycles of shadow output.
GATE_ENFORCING = False


def gate_deal(ticker, cik, announced_date_str, cached_verdict=None,
              finder=None, merger_signals=None, irrelevant_signals=None):
    """
    Returns dict:
        {verdict, accession, form, filing_date, reason, checked}

    cached_verdict: pass the deal's stored gate result. If it is already
    VERIFIED we trust it and make zero network calls -- a filing that proved
    a deal exists does not stop being proof.

    finder: the _find_announcement_filing_for_validation function, injected so
    this module stays testable without importing main.
    """
    # already proven -- do not spend an EDGAR call re-proving it
    if cached_verdict and cached_verdict.get("verdict") == VERDICT_VERIFIED:
        out = dict(cached_verdict)
        out["checked"] = False
        return out

    if not cik or not announced_date_str:
        return {"verdict": VERDICT_UNVERIFIED, "accession": None, "form": None,
                "filing_date": None, "checked": True,
                "reason": "missing cik or announced date -- cannot look up a filing"}

    result = finder(cik, announced_date_str)
    if not result:
        return {"verdict": VERDICT_UNVERIFIED, "accession": None, "form": None,
                "filing_date": None, "checked": True,
                "reason": f"no 8-K/tender filing found within the announcement window for CIK {cik}"}

    filing_date, accession, form, text = result
    low = (text or "").lower()

    has_merger = any(s in low for s in (merger_signals or []))
    hit_irrelevant = [s for s in (irrelevant_signals or []) if s in low]

    if has_merger:
        return {"verdict": VERDICT_VERIFIED, "accession": accession, "form": form,
                "filing_date": filing_date, "checked": True,
                "reason": f"{form} filed {filing_date} contains merger language"}

    reason = f"{form} filed {filing_date} found in window but contains no merger language"
    if hit_irrelevant:
        reason += f" (matched instead: {', '.join(hit_irrelevant[:2])})"
    return {"verdict": VERDICT_WEAK, "accession": accession, "form": form,
            "filing_date": filing_date, "checked": True, "reason": reason}


def gate_report(deals):
    """Summary line + per-deal detail for the shadow-mode log."""
    counts = {VERDICT_VERIFIED: 0, VERDICT_WEAK: 0, VERDICT_UNVERIFIED: 0}
    lines = []
    for d in deals:
        g = d.get("gate") or d.get("_gate") or {}
        v = g.get("verdict", VERDICT_UNVERIFIED)
        counts[v] = counts.get(v, 0) + 1
        mark = {"VERIFIED": "  ", "WEAK": " ~", "UNVERIFIED": " !"}.get(v, " ?")
        acc = g.get("accession") or "-"
        lines.append(f"{mark} {d.get('ticker','?'):<6} {v:<11} {acc:<22} {g.get('reason','')}")
    header = (f"[Gate] {counts[VERDICT_VERIFIED]} verified, "
              f"{counts[VERDICT_WEAK]} weak, {counts[VERDICT_UNVERIFIED]} unverified"
              f"{' (SHADOW -- nothing blocked)' if not GATE_ENFORCING else ' (ENFORCING)'}")
    return header, lines


wire_in_notes = """
WIRE-IN (two places, both in the scan path):

1. After deals are built, before save_cache:

    from deal_gate import gate_deal, gate_report, GATE_ENFORCING, VERDICT_VERIFIED
    for d in deals:
        d['_gate'] = gate_deal(
            d.get('ticker'), SEC_CIK_MAP.get(d.get('ticker','')),
            d.get('filed'), cached_verdict=d.get('_gate'),
            finder=_find_announcement_filing_for_validation,
            merger_signals=VALIDATION_MERGER_SIGNALS,
            irrelevant_signals=VALIDATION_IRRELEVANT_SIGNALS,
        )
    header, lines = gate_report(deals)
    print(header)
    for ln in lines: print(ln)

2. Only when you flip GATE_ENFORCING = True:

    if GATE_ENFORCING:
        deals = [d for d in deals if d['_gate']['verdict'] == VERDICT_VERIFIED]

NOTE: _gate must be persisted on the deal record so VERIFIED deals skip the
lookup next cycle. If your cache strips underscore-prefixed keys the way it
strips _filing_text, rename it to 'gate' before wiring in.
"""