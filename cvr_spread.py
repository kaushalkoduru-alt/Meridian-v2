"""
Contingent value rights and the spread.

A CVR deal pays cash plus a right whose value the filing does not price. When the
stock trades ABOVE the cash price the arithmetic spread (cash - price) / price is
negative, but that negative number is the market valuing the CVR, not a deal
that is mispriced, broken or about to be topped. SSTI: $8.00 cash plus a
non-transferable CVR of up to $3.00, trading at $8.43. Scoring it as "negative
spread" and showing "-5.04%, -20% annualized" misstates what the holder faces.

So for a CVR deal trading above its cash price the spread is NOT MEANINGFUL: it
is shown as n/m, the annualized figure is withheld, the score gives the spread
factor 0 (neither the tight-spread bonus nor the negative penalty) and the
spread cap in get_risk does not apply. What the filing does state is shown
instead: the cash price and the maximum CVR, taken from the filing's own words.

Display/scoring only; nothing is estimated. Where the filing does not state a
maximum, none is shown.
"""
import ast
import re

_MAX_RE = re.compile(
    r"(?:up\s+to|of\s+up\s+to|maximum\s+(?:aggregate\s+)?(?:payment|amount)\s+(?:of|will\s+not\s+exceed))"
    r"\s+(?:an\s+additional\s+)?\$\s?(\d+(?:\.\d+)?)\s+per\s+(?:share|CVR)", re.I)


def _flags(deal):
    f = (deal or {}).get("flags")
    if isinstance(f, str):
        try:
            f = ast.literal_eval(f)
        except (ValueError, SyntaxError):
            return []
    return [x for x in f if isinstance(x, dict)] if isinstance(f, list) else []


def cvr_flag(deal):
    return next((f for f in _flags(deal) if f.get("flag") == "CVR"), None)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def spread_not_meaningful(deal):
    """True for a CVR deal trading above its cash price."""
    if not cvr_flag(deal):
        return False
    cp, dp = _num((deal or {}).get("cp")), _num((deal or {}).get("dp"))
    return bool(cp and dp and cp > dp)


def cvr_terms(deal):
    """What the filing states about the CVR, or None. The maximum is parsed from
    the flag's own filing excerpt and quoted; no maximum is ever assumed."""
    flag = cvr_flag(deal)
    if not flag:
        return None
    dp, cp = _num(deal.get("dp")), _num(deal.get("cp"))
    out = {"cash": dp, "max_per_share": None, "total_max": None, "spread_to_max_pct": None,
           "quote": None, "excerpt_of": "the filing's CVR flag"}
    m = _MAX_RE.search(str(flag.get("context") or ""))
    if m and dp:
        mx = float(m.group(1))
        s = max(0, m.start() - 120)
        out["max_per_share"] = mx
        out["total_max"] = round(dp + mx, 2)
        q = " ".join(str(flag.get("context"))[s:m.end() + 40].split())
        out["quote"] = q.split(" ", 1)[1] if s > 0 and " " in q else q   # drop a clipped first word
        if cp:
            out["spread_to_max_pct"] = round((dp + mx - cp) / cp * 100, 2)
    return out
