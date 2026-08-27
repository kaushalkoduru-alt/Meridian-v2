"""
The four §2 defects, tested against the values that exposed them.

Each case here is a live deal from the 2026-08-26 cache, not a synthetic one.
AES appears three times because a single bad close-date parse produced a
past-dated deal, an annualized figure computed against nothing, and — through a
break price above both current and deal price — a 99.9% probability of closing
printed beside a red "Distressed" label.
"""
from datetime import date
from main import (parse_close_date, days_to_close, annualized_spread,
                 two_state_applies, resolve_tx_value, VERIFIED_TX_VALUES)

ok = True
def check(label, got, want, detail=""):
    global ok
    good = got == want
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  {label}")
    print(f"        got {got}, wanted {want}" + (f" | {detail}" if detail else ""))

TODAY = date(2026, 8, 27)


print("CLOSE DATE — A YEAR NEVER BORROWS A MONTH FROM ANOTHER CLAUSE")
print("-" * 78)

# The defect. The old reader took the year from the first match in the whole
# string ("2026") and the month from a keyword chain scanning the whole string,
# which fired on "early" belonging to the SECOND clause -- 31 March 2026, a date
# matching neither reading and five months in the past on a live deal.
check("AES: two clauses do not merge into a third date",
      parse_close_date("late 2026 or early 2027"), date(2027, 3, 31),
      "was 2026-03-31 — year from clause one, month from clause two")
check("AES: the parsed close is no longer in the past",
      days_to_close("late 2026 or early 2027", now=TODAY) > 0, True,
      f"{days_to_close('late 2026 or early 2027', now=TODAY)} days")

# A range resolves to its LATER bound, consistently, at both scales: across
# clauses above and within one compound qualifier here.
check("CZR: a compound qualifier takes its later bound",
      parse_close_date("mid-to-late 2027"), date(2027, 12, 31),
      "was 2027-06-30 — 'mid' won because the chain tested it first")

# Every qualifier resolves to the last day it can mean.
check("Q3 ends in September", parse_close_date("Q3 2026"), date(2026, 9, 30))
check("H2 ends in December", parse_close_date("H2 2026"), date(2026, 12, 31))
check("a written-out half is read the same way",
      parse_close_date("second half 2026"), date(2026, 12, 31))
check("a bare year is a period too, and ends in December",
      parse_close_date("2027"), date(2027, 12, 31),
      "was 2027-06-30, the midpoint — not a bound at all")
check("early keeps its quarter", parse_close_date("early 2027"), date(2027, 3, 31))
check("a hyphenated mid still parses", parse_close_date("mid-2027"), date(2027, 6, 30))

# Nothing is invented where nothing is stated.
for empty in ("TBD", "", None, "nan", "not yet disclosed"):
    check(f"{empty!r} yields no date", parse_close_date(empty), None)
check("text with no year yields no date",
      parse_close_date("upon receipt of regulatory approval"), None)

# An exact date bypasses period logic entirely.
check("an exact date is taken as given",
      parse_close_date("2026-10-20"), date(2026, 10, 20))


print()
print("ANNUALIZED SPREAD — THE DEAL'S OWN CLOCK, OR NOTHING")
print("-" * 78)

# The defect: (sp_pct / 180) * 365 for every deal, which is the gross spread
# times 2.028 and carries no time information at all.
check("NATH: a near close annualizes UP",
      annualized_spread(4.24, 126), 12.28, "printed 8.60 under the 180 constant")
check("CZR: a distant close annualizes DOWN",
      annualized_spread(4.52, 491), 3.36, "printed 9.17 under the 180 constant")

# The ranking inversion the constant produced, in one assertion: under 180,
# CZR (9.17) outranked NATH (8.60). On real clocks NATH earns 3.7x more per
# unit of time.
check("the ranking the constant inverted is restored",
      annualized_spread(4.24, 126) > annualized_spread(4.52, 491), True,
      "NATH above CZR, where the constant put it below")

check("180 days is the one case the constant got right",
      annualized_spread(10.0, 180), 20.28)

# No close date, no annualization. A constant fallback is what the defect was.
check("GBCS: no close date yields no figure", annualized_spread(6.09, None), None)
check("a passed close date yields no figure", annualized_spread(5.0, -149), None)
check("a zero-day close yields no figure", annualized_spread(5.0, 0), None)
check("an implausibly distant close yields no figure",
      annualized_spread(5.0, 1461), None, "beyond ANNUALIZE_MAX_DAYS")
check("no spread yields no figure", annualized_spread(None, 120), None)


print()
print("IMPLIED PROBABILITY — GATED, NOT CLAMPED")
print("-" * 78)

# The defect. AES's break price sits ABOVE both its current and its deal price,
# so both halves of the fraction go negative, the signs cancel, and 114.4% was
# clamped to 99.9% -- rendered as near-certain closing beside a red
# "Distressed" label, from one function, on one deal.
raw = ((14.73 - 16.87) / (15.00 - 16.87)) * 100
check("AES: the unclamped fraction really is over 100",
      round(raw, 1), 114.4, "cp 14.73, dp 15.00, bp 16.87")
applies, why = two_state_applies(14.73, 15.00, 16.87)
check("AES: the model is refused rather than clamped", applies, False)
check("AES: the refusal names the reason",
      "at or above the current price" in (why or ""), True, why)

# The deals where it does apply are untouched.
for tk, cp, dp, bp in [('WBD', 28.90, 31.00, 28.80), ('ALOT', 28.99, 29.00, 16.69),
                       ('GBCS', 5.42, 5.75, 3.20), ('CZR', 29.66, 31.00, 28.78)]:
    a, w = two_state_applies(cp, dp, bp)
    check(f"{tk}: the model still applies", a, True, w or "")

# WBD's numerator is $0.10 against a healthy $2.20 denominator. That is a real
# reading of a bad break price, not a model failure -- so it is NOT gated. §3
# and §4 own it.
check("WBD: a collapsing numerator is not what the gate catches",
      two_state_applies(28.90, 31.00, 28.80)[0], True,
      "4.5% is wrong because the break price is wrong, not because the model is")

check("break at the current price is refused",
      two_state_applies(10.00, 12.00, 10.00)[0], False)
check("break above the deal price is refused",
      two_state_applies(10.00, 12.00, 12.50)[0], False)
check("trading above the deal price is refused",
      two_state_applies(13.00, 12.00, 8.00)[0], False,
      "prices a topping bid, not this deal closing")
check("a missing break price is refused",
      two_state_applies(10.00, 12.00, None)[0], False)


print()
print("TRANSACTION VALUE — THE HAND-VERIFIED NUMBER WINS")
print("-" * 78)

# The defect: `if ticker in VERIFIED_TX_VALUES and not tx_value` applied the
# verified number ONLY where extraction had failed, so WBD's $77.72B equity
# approximation beat its verified $110B enterprise value.
check("WBD: the hardcode beats a successful extraction",
      resolve_tx_value('WBD', 77.72, 'equity_calc_approx'),
      (110.0, 'verified_hardcode'),
      "was (77.72, 'equity_calc_approx') — the guard was inverted")
check("GSAT: the hardcode still covers a failed extraction",
      resolve_tx_value('GSAT', None, None), (11.6, 'verified_hardcode'))
check("CZR: an unverified ticker keeps its extraction",
      resolve_tx_value('CZR', 17.6, 'regex_enterprise'), (17.6, 'regex_enterprise'))
check("an unverified ticker with no extraction stays empty",
      resolve_tx_value('ZZZZ', None, None), (None, None))
check("every verified ticker resolves to its verified value",
      all(resolve_tx_value(t, 999.0, 'x') == (v, 'verified_hardcode')
          for t, v in VERIFIED_TX_VALUES.items()), True,
      f"{len(VERIFIED_TX_VALUES)} entries")

print()
print("=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")
