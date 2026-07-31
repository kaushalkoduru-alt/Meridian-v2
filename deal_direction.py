"""
DEAL DIRECTION CHECK — is the filer the TARGET or the ACQUIRER?

The pipeline finds a filing with merger language and assumes the filer is being
acquired. That assumption was never checked, and it has been wrong twice:

  CLST  Catalyst Bancorp, buying Lakeside Bancshares
  RKLB  Rocket Lab, buying Iridium  (-7.85% spread; the "target" traded ABOVE
        its own offer price, which cannot happen)

Both were hand-patched into EXCLUDED_TICKERS after shipping. This module makes
the assumption explicit, checkable, and logged.

DESIGN — two layers, and deliberately no regex layer.

  Layer 1  STRUCTURAL. Arithmetic on numbers already on the deal. Deterministic,
           cannot regress, cannot be confused by legal phrasing. Catches RKLB by
           itself. This is the layer that carries the weight.

  Layer 2  MODEL. One question to Sonnet: is the filer being bought, or buying?
           Used only when layer 1 is inconclusive, which is most deals -- but
           enrichment is cached per deal, so it fires once per NEW deal, not
           hourly. Reading comprehension beats pattern matching on legal prose.

An earlier version had a regex layer between these. It was removed: across six
test cases it produced four wrong verdicts, and fixing one broke another. Legal
phrasing has too many forms ("will be acquired by", "each share shall be
converted into the right to receive", "will merge with and into a wholly owned
subsidiary of") for patterns to cover without constant tuning. What survives
from it is find_other_listed_ticker, which is a clean signal on its own.

A break-price-above-market check was also tried and removed. WBD is a genuine
target whose modeled break price ($28.80) sits above its market price ($25.64),
because the market is pricing real break risk. Normal for a wide-spread deal.
The check blocked good deals, which is worse than the bug it was meant to fix.

Verdicts: TARGET / ACQUIRER / UNCLEAR. Only TARGET may ship.
"""

import re

VERDICT_TARGET   = "TARGET"
VERDICT_ACQUIRER = "ACQUIRER"
VERDICT_UNCLEAR  = "UNCLEAR"

# Shadow mode. Flip only after several cycles of correct verdicts on real deals.
DIRECTION_ENFORCING = False

# A target CAN trade above its offer -- when the market expects a topping bid --
# but those spreads run 1-3%. Beyond this the filer's stock is not pinned to the
# offer at all, which means the filer is not the one being bought.
MAX_NEGATIVE_SPREAD = -3.0


def find_other_listed_ticker(text, filer_ticker):
    """
    An exchange-tagged ticker in the filing that isn't the filer's own. When a
    Rocket Lab filing names (NASDAQ: IRDM), that is the counterparty -- and very
    often the deal actually worth tracking.
    """
    pattern = r'\((?:NYSE|NASDAQ|NYSE\s*American|AMEX|NYSE\s*Arca)\s*:\s*([A-Z]{1,5})\)'
    for m in re.findall(pattern, text or '', re.IGNORECASE):
        if m.upper() != (filer_ticker or '').upper():
            return m.upper()
    return None


def _structural_verdict(spread_pct, deal_price, current_price):
    """
    Layer 1. Returns (verdict, reason) or (None, None) if inconclusive.
    Deterministic: no text, no model, no ambiguity.
    """
    if spread_pct is None and deal_price and current_price:
        try:
            spread_pct = ((float(deal_price) - float(current_price)) / float(current_price)) * 100
        except (TypeError, ValueError, ZeroDivisionError):
            return None, None

    if spread_pct is None:
        return None, None

    try:
        sp = float(spread_pct)
    except (TypeError, ValueError):
        return None, None

    if sp < MAX_NEGATIVE_SPREAD:
        return VERDICT_ACQUIRER, (
            f"spread {sp:.2f}% — the filer trades {abs(sp):.2f}% ABOVE the stated deal "
            f"price. A company being acquired trades near or below its offer; only a "
            f"buyer's stock floats free of it"
        )
    return None, None


def _model_prompt(ticker, company_name, filing_text):
    return (
        "You are reading an SEC filing about a merger or acquisition.\n\n"
        f"The company that FILED this document is: {company_name} (ticker: {ticker}).\n\n"
        "Question: in this transaction, is the FILING COMPANY being acquired, or is the "
        "FILING COMPANY the one doing the acquiring?\n\n"
        "Answer with exactly one word:\n"
        "  TARGET   — the filing company is being acquired by someone else\n"
        "  ACQUIRER — the filing company is buying another company\n"
        "  UNCLEAR  — the filing does not make this determinable\n\n"
        "Do not explain. One word only.\n\n"
        "--- FILING TEXT ---\n"
        f"{(filing_text or '')[:6000]}\n"
        "--- END ---\n\n"
        "One word:"
    )


def check_direction(ticker, company_name, filing_text,
                    deal_price=None, current_price=None, spread_pct=None,
                    llm_fn=None):
    """
    Returns:
        {verdict, layer, reason, other_ticker, checked_llm}

    llm_fn: callable(prompt) -> str. Omit to run layer 1 only, in which case
    anything layer 1 doesn't catch comes back UNCLEAR.

    Note on UNCLEAR: it is NOT a pass. With DIRECTION_ENFORCING on, only TARGET
    ships. UNCLEAR deals are held and logged for review -- the whole point is to
    stop assuming, so an unanswered question must not default to yes.
    """
    result = {
        "verdict": VERDICT_UNCLEAR,
        "layer": None,
        "reason": "",
        "other_ticker": find_other_listed_ticker(filing_text, ticker),
        "checked_llm": False,
    }

    # ── Layer 1: structural ──────────────────────────────────────────────────
    verdict, reason = _structural_verdict(spread_pct, deal_price, current_price)
    if verdict:
        result.update(verdict=verdict, layer="structural", reason=reason)
        return result

    # ── Layer 2: model ───────────────────────────────────────────────────────
    if llm_fn and filing_text:
        try:
            raw = (llm_fn(_model_prompt(ticker, company_name, filing_text)) or "")
            result["checked_llm"] = True
            token = raw.strip().upper()
            # Match on a leading token rather than substring: a verbose reply like
            # "ACQUIRER is wrong, this is TARGET" must not be read by whichever
            # word appears first in our own if-chain.
            first = re.split(r'[^A-Z]+', token)
            first = next((w for w in first if w in
                          (VERDICT_TARGET, VERDICT_ACQUIRER, VERDICT_UNCLEAR)), None)
            if first == VERDICT_ACQUIRER:
                result.update(verdict=VERDICT_ACQUIRER, layer="model",
                              reason="model read the filer as the buyer, not the acquired party")
                return result
            if first == VERDICT_TARGET:
                result.update(verdict=VERDICT_TARGET, layer="model",
                              reason="model read the filer as the company being acquired")
                return result
            result.update(layer="model",
                          reason=f"model gave no usable verdict (returned {token[:40]!r})")
            return result
        except Exception as e:
            result["reason"] = f"model check failed: {e}"

    # ── Inconclusive ─────────────────────────────────────────────────────────
    hint = ""
    if result["other_ticker"]:
        hint = (f"; filing names {result['other_ticker']}, which may be the real "
                f"counterparty")
    if not result["reason"]:
        result["reason"] = ("no structural signal and no model check available" + hint)
    result["layer"] = result["layer"] or "none"
    return result


def direction_report(deals):
    """Header line plus one line per deal, for the shadow-mode log."""
    counts = {VERDICT_TARGET: 0, VERDICT_ACQUIRER: 0, VERDICT_UNCLEAR: 0}
    lines = []
    for d in deals:
        r = d.get("direction") or {}
        v = r.get("verdict", VERDICT_UNCLEAR)
        counts[v] = counts.get(v, 0) + 1
        mark = {VERDICT_TARGET: "  ", VERDICT_ACQUIRER: " !", VERDICT_UNCLEAR: " ?"}.get(v, " ?")
        lines.append(f"{mark} {d.get('ticker','?'):<6} {v:<9} "
                     f"[{r.get('layer') or '-':<10}] {r.get('reason','')[:76]}")
    header = (f"[Direction] {counts[VERDICT_TARGET]} target, "
              f"{counts[VERDICT_ACQUIRER]} acquirer, {counts[VERDICT_UNCLEAR]} unclear"
              + (" (ENFORCING)" if DIRECTION_ENFORCING else " (SHADOW — nothing blocked)"))
    return header, lines