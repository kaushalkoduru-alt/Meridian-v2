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
                 two_state_applies, resolve_tx_value, VERIFIED_TX_VALUES,
                 cap_expected_close, edgar_queries, get_break_price,
                 VERIFIED_UNAFFECTED_PRICES, DEAL_SEARCH_LOOKBACK_DAYS,
                 pricing_integrity_failures, DEAL_STRUCTURES,
                 blended_governs, apply_blended_to_spread,
                 validate_close_date, validate_enriched_acquirer,
                 ANNUALIZE_MIN_DAYS, CLOSE_DATE_SCAN_CHARS, extract_close_date,
                 tx_value_plausible, get_acquirer_type,
                 TX_VALUE_MIN_RATIO, TX_VALUE_MAX_RATIO,
                 PROXY_CLOSE_DATE_SCAN_CHARS, _pick_ex2, _EX2_NAME)

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
print("EDGAR SEARCH WINDOW ROLLS FORWARD")
print("-" * 78)

# The defect: every query carried a literal enddt, newest 2026-07-24, so by
# 2026-08-27 no deal announced in 34 days could be detected and the blind spot
# widened daily. Nothing failed and nothing logged.
_q = edgar_queries(now=date(2026, 8, 27))
check("every query is built, none dropped", len(_q), 6)
_ends = {u['url'].split('enddt=')[1].split('&')[0] for u in _q}
_starts = {u['url'].split('startdt=')[1].split('&')[0] for u in _q}
check("no query ends before today", _ends, {'2026-08-28'},
      "today plus one day, for the ET/UTC gap")
check("every query shares one rolling start", _starts, {'2025-02-25'},
      f"{DEAL_SEARCH_LOOKBACK_DAYS} days back, matching the age gate")
check("the window follows the clock rather than a constant",
      edgar_queries(now=date(2027, 1, 1))[0]['url'].split('enddt=')[1].split('&')[0],
      '2027-01-02')
check("no literal year survives in a built URL",
      any(y in _q[0]['url'] for y in ('2024-01-01', '2026-06-30', '2026-07-24')), False)

print()
print("EXPECTED CLOSE CAPPED AT A DEADLINE IT CANNOT PASS")
print("-" * 78)

# Four deals guided to a period whose END falls after their contractual
# deadline. The guidance is not wrong — each deadline sits INSIDE the guided
# period — the end-of-period point estimate is what made it look impossible.
for tk, cd, od, want in [
    ('NATH', 'H2 2026',          {'date': '2026-10-20', 'extension_type': 'automatic'}, date(2026, 10, 20)),
    ('CZR',  'mid-to-late 2027', {'date': '2027-11-27', 'extension_type': 'automatic'}, date(2027, 11, 27)),
    ('PAYO', 'mid-2027',         {'date': '2027-06-12', 'extension_type': 'automatic'}, date(2027, 6, 12)),
    ('GBCS', 'Q3 2026',          {'date': '2026-08-31', 'extension_type': None},        date(2026, 8, 31))]:
    got, capped = cap_expected_close(cd, od)
    check(f"{tk}: capped at its outside date", got, want, f"guidance {cd!r}")
    check(f"{tk}: the cap is recorded", capped, od['date'])

# An ELECTIVE deadline is not a wall — a party may push it out — so guidance
# landing past it is not impossible and must not be capped.
_got, _cap = cap_expected_close('early 2027',
                                {'date': '2027-01-26', 'extension_type': 'elective'})
check("OGN: an elective deadline does not cap", _got, date(2027, 3, 31),
      "base 2027-01-26 may be extended to 2027-04-26")
check("OGN: nothing recorded as capped", _cap, None)

# Guidance already inside the deadline is untouched — the headline number on
# these deals must not move.
for tk, cd, od, want in [
    ('WBD',  'Q3 2026',                 {'date': '2027-06-04', 'extension_type': 'automatic'}, date(2026, 9, 30)),
    ('GSAT', '2027',                    {'date': '2028-04-13', 'extension_type': 'automatic'}, date(2027, 12, 31)),
    ('AES',  'late 2026 or early 2027', {'date': '2027-06-01', 'extension_type': 'automatic'}, date(2027, 3, 31)),
    ('GBTG', 'second half 2026',        {'date': '2027-02-02', 'extension_type': 'automatic'}, date(2026, 12, 31))]:
    got, capped = cap_expected_close(cd, od)
    check(f"{tk}: guidance inside the deadline is untouched", (got, capped), (want, None))

check("no outside date, no cap",
      cap_expected_close('Q3 2026', None), (date(2026, 9, 30), None))
check("no guidance, no cap", cap_expected_close('TBD',
      {'date': '2026-10-20', 'extension_type': None}), (None, None))

print()
print("AES UNAFFECTED PRICE")
print("-" * 78)

# get_break_price takes the last close before the filing. AES traded a
# 13.28-14.39 range through January 2026, broke above it on 2026-02-03, closed
# at 16.87 the session before the 8-K, then fell 17.8% on the announcement.
check("AES uses its hand-verified unaffected price",
      get_break_price('AES', '2026-03-02'), 13.75,
      "was 16.87, the peak of the pre-announcement run-up")
check("the verified price sits below both current and deal price",
      13.75 < 14.73 and 13.75 < 15.00, True,
      "which is what un-gates the two-state model")
check("AES's probability becomes readable again",
      two_state_applies(14.73, 15.00, 13.75)[0], True)
check("only hand-read deals are overridden",
      list(VERIFIED_UNAFFECTED_PRICES), ['AES'],
      "a 150-day scan flags 7 of 12 as elevated; price alone cannot say which are leaks")

print()
print("BLENDED PRICE SURVIVES THE ROUND TRIP")
print("-" * 78)

# The barriers in deal_pricing protect against a WRONG blended number. Nothing
# protected against NO blended number. GSAT's pricing object vanished from the
# production feed for days while all thirteen barriers passed on every scan,
# because the cache write that carried it was rejected and nobody checked.
_GOOD = {'ticker': 'GSAT', 'pricing': {'blended': 85.36, 'all_passed': True}}

check("a healthy structured deal raises nothing",
      pricing_integrity_failures([_GOOD]), [])

# Shape 1: internally inconsistent. The barriers cannot certify a number that
# is not there.
_f = pricing_integrity_failures(
    [{'ticker': 'GSAT', 'pricing': {'blended': None, 'all_passed': True}}])
check("barriers passing with no blended number is caught", len(_f), 1)
check("and it is named a contradiction",
      'contradiction' in _f[0][1] if _f else False, True,
      _f[0][1] if _f else 'nothing raised')

# Shape 2: the one that actually shipped. No pricing object at all, which from
# outside the scan is indistinguishable from the pass never having run.
for label, deal in [
        ('no pricing key',   {'ticker': 'GSAT'}),
        ('pricing is None',  {'ticker': 'GSAT', 'pricing': None}),
        ('pricing is empty', {'ticker': 'GSAT', 'pricing': {}})]:
    _f = pricing_integrity_failures([deal])
    check(f"a structured deal with {label} is caught", len(_f), 1)
    check(f"  and it is named dropped ({label})",
          'dropped' in _f[0][1] if _f else False, True)

# The exact production feed that prompted this: GSAT present, priced, spreading
# off the $90 headline, with the pricing object gone.
_PROD = [{'ticker': 'GSAT', 'dp': 90.0, 'cp': 82.05, 'sp_pct': 9.69,
          'pricing': None, 'commitment': None, 'outside_date': None},
         {'ticker': 'WBD', 'dp': 31.0, 'cp': 28.9}]
_f = pricing_integrity_failures(_PROD)
check("the production feed that broke reproduces the failure",
      [t for t, _ in _f], ['GSAT'],
      "20 deals, 19 without enrichment, only GSAT is structured")

# Deals with no hand-verified structure are not this check's business — most of
# the feed is all-cash and has no blended price by design.
check("an unstructured deal with no pricing is not a failure",
      pricing_integrity_failures([{'ticker': 'WBD', 'dp': 31.0}]), [])
check("every ticker checked is one with a hand-verified structure",
      all(t in DEAL_STRUCTURES for t, _ in pricing_integrity_failures(
          [{'ticker': k} for k in list(DEAL_STRUCTURES) + ['WBD', 'AES']])), True)

# A barrier legitimately failing is the system working. Only the pairing of a
# passing verdict with a missing number is a defect.
check("blended None with barriers FAILING is allowed through",
      pricing_integrity_failures(
          [{'ticker': 'GSAT', 'pricing': {'blended': None, 'all_passed': False}}]), [],
      "the barriers refused the number, which is what they are for")

# The feed reaches this check as repr strings off the CSV whenever Redis is
# down, so the parse has to be the same on both paths.
check("a cached repr string is read like a live dict",
      pricing_integrity_failures(
          [{'ticker': 'GSAT', 'pricing': "{'blended': 85.36, 'all_passed': True}"}]), [])
check("a cached repr string still catches the contradiction",
      len(pricing_integrity_failures(
          [{'ticker': 'GSAT', 'pricing': "{'blended': None, 'all_passed': True}"}])), 1)

check("an empty feed raises nothing", pricing_integrity_failures([]), [])
check("a null feed raises nothing", pricing_integrity_failures(None), [])

print()
print("TICKER MAP CACHE ROUND-TRIPS")
print("-" * 78)

# The write posted {"value": ..., "ex": ...} as a JSON body. Upstash stores a
# request body verbatim, so what landed in Redis was the ENVELOPE -- and the
# reader json.loads()'d it and looked for 'ticker_map' at the top level, where
# it found 'value' and 'ex' instead. Every start missed and re-fetched all
# 10,391 tickers, and neither end reported anything.
import json as _json
_MAP = {'ticker_map': {'AES': 'The AES Corporation'}, 'cik_map': {'AES': '0000874761'}}

# What the old write stored, and why the reader could not see through it.
_envelope = _json.dumps({'value': _json.dumps(_MAP), 'ex': 86400})
check("the old write stored an envelope, not the payload",
      sorted(_json.loads(_envelope)), ['ex', 'value'],
      "the reader looked for 'ticker_map' among these")
check("so the old read found no ticker_map",
      _json.loads(_envelope).get('ticker_map'), None)

# What the fixed write stores: the payload itself, readable in one hop.
_raw = _json.dumps(_MAP)
check("the fixed write stores the payload itself",
      _json.loads(_raw).get('ticker_map'), {'AES': 'The AES Corporation'})
check("and the cik_map rides along with it",
      _json.loads(_raw).get('cik_map'), {'AES': '0000874761'})

print()
print("BLENDED VALUE GOVERNS THE SPREAD")
print("-" * 78)

# GSAT in production: blended 87.32, all thirteen barriers passing, and sp_pct
# still 9.30 -- ((90.00 - 82.34) / 82.34), measured off a headline nobody
# receives. The deal card recomputed it to 6.05% for display; the ticker, the
# annualized figure, the position-size table and /api/deals did not, and the
# dashboard sorted GSAT to the top of the feed on the wrong number.
_GSAT = {'ticker': 'GSAT', 'cp': 82.34, 'dp': 90.00, 'sp_pct': 9.3, 'ann': 6.93,
         'days_to_close': 490, 'score': 47, 'risk': 'High',
         'pricing': {'blended': 87.32, 'all_passed': True}}

_f = pricing_integrity_failures([dict(_GSAT)])
check("a passing deal with a headline-derived spread is caught", len(_f), 1)
check("  and the failure names the spread source",
      'spread source' in _f[0][1] if _f else False, True)
check("  and identifies it as the headline",
      'headline' in _f[0][1] if _f else False, True,
      _f[0][1][:110] if _f else '')

_d = dict(_GSAT); _ch = apply_blended_to_spread(_d)
check("sp_pct is re-derived from the blended value", _d['sp_pct'], 6.05,
      "(87.32 - 82.34) / 82.34, not (90.00 - 82.34) / 82.34")
check("ann follows the corrected spread", _d['ann'], 4.51, "was 6.93")
check("the risk band follows too", _d['risk'], 'Medium',
      "9.30 banded it High; 6.05 does not")
check("the headline is preserved, not destroyed", _d['sp_pct_headline'], 9.3)
check("dp is untouched — it stays 'offer in the filing'", _d['dp'], 90.00)
check("the frozen detection anchor is not rewritten",
      'sp_pct_at_detection' in _d, False, "history is not re-derived")
check("the corrected record passes the integrity check",
      pricing_integrity_failures([_d]), [])

# The sort reads sp_pct, so correcting it is what moves the deal.
_FEED = [dict(_GSAT), {'ticker': 'WBD', 'cp': 28.9, 'dp': 31.0, 'sp_pct': 7.27},
         {'ticker': 'GBCS', 'cp': 5.42, 'dp': 5.75, 'sp_pct': 6.09}]
check("GSAT ranks first on the headline spread",
      sorted(_FEED, key=lambda z: z.get('sp_pct') or 0, reverse=True)[0]['ticker'],
      'GSAT')
for _x in _FEED: apply_blended_to_spread(_x)
check("and third once the blended value governs",
      [z['ticker'] for z in sorted(_FEED, key=lambda z: z.get('sp_pct') or 0,
                                   reverse=True)], ['WBD', 'GBCS', 'GSAT'])

# blended_governs is the single gate. A failing barrier set, a missing blended
# value or an unstructured deal all mean the headline still stands.
check("a failing barrier set does not govern",
      blended_governs({'pricing': {'blended': 87.32, 'all_passed': False}}), None,
      "the barriers refused the number, so it cannot drive the spread")
check("a missing blended value does not govern",
      blended_governs({'pricing': {'blended': None, 'all_passed': True}}), None)
check("a deal with no pricing does not govern",
      blended_governs({'ticker': 'WBD', 'dp': 31.0}), None)
check("and such a deal's spread is left alone",
      apply_blended_to_spread({'ticker': 'WBD', 'cp': 28.9, 'sp_pct': 7.27}), None)
check("a cached repr string still governs",
      blended_governs({'pricing': "{'blended': 87.32, 'all_passed': True}"}), 87.32)

print()
print("THE ENRICHMENT PASS IS NO LONGER TAKEN ON TRUST")
print("-" * 78)

# BWMN carried close_date "Q2 2026" on a deal announced 2026-08-10 -- six weeks
# after that quarter ended. It did not come from the filing; extract_close_date
# returns TBD for that 8-K. A model produced it and nothing objected.
_v, _why = validate_close_date('Q2 2026', '2026-08-10')
check("BWMN: a close date before the announcement is refused", _v, None)
check("  and the refusal says why",
      'backwards' in (_why or ''), True, _why)
check("APGE: a plausible one is kept",
      validate_close_date('Q3 2026', '2026-06-22'), ('Q3 2026', None))
check("a date beyond any merger horizon is refused",
      validate_close_date('2035', '2026-01-01')[0], None,
      "3,651 days past announcement")
check("an unreadable phrase is refused",
      validate_close_date('sometime soon', '2026-01-01')[0], None)
for _empty in (None, '', 'null', 'TBD', 'unknown'):
    check(f"{_empty!r} is refused", validate_close_date(_empty, '2026-01-01')[0], None)
check("with no announcement date to judge against, it stands",
      validate_close_date('Q3 2026', None), ('Q3 2026', None),
      "nothing to compare to is not grounds to discard")

# The acquirer had a guard, but it only compared against the TARGET's name. It
# never asked whether the name appears in the filing at all.
_FILING = ('Atkore Inc. today announced a definitive agreement under which '
           'Prysmian S.p.A. will acquire all outstanding shares for $95.00 per '
           'share in cash.')
check("an acquirer named in the filing is kept",
      validate_enriched_acquirer('Prysmian', _FILING, 'Atkore Inc.')[0], 'Prysmian')
check("a full legal name still matches the filing's short form",
      validate_enriched_acquirer('Prysmian S.p.A.', _FILING, 'Atkore Inc.')[0],
      'Prysmian S.p.A.')
_a, _w = validate_enriched_acquirer('Berkshire Hathaway', _FILING, 'Atkore Inc.')
check("an acquirer absent from the filing is refused", _a, None,
      "the check the old guard never made")
check("  and the refusal says why",
      'does not appear' in (_w or ''), True, _w)
check("the target's own name is still refused",
      validate_enriched_acquirer('Atkore Inc.', _FILING, 'Atkore Inc.')[0], None)
for _bad in (None, '', 'null', 'x'):
    check(f"{_bad!r} is refused",
          validate_enriched_acquirer(_bad, _FILING, 'Atkore Inc.')[0], None)

print()
print("SHORT WINDOWS ARE NOT ANNUALIZED")
print("-" * 78)

# GBCS, one day from its outside date on a 6.09% spread, annualized to 2,222%.
check("GBCS: a one-day window yields no annualized figure",
      annualized_spread(6.09, 1), None, "was 2222.85")
check("the floor is one month", ANNUALIZE_MIN_DAYS, 30)
check("one day below the floor is suppressed", annualized_spread(6.09, 29), None)
check("the floor itself annualizes", annualized_spread(6.09, 30), 74.09)
check("ALOT at 31 days is unaffected", annualized_spread(0.03, 31), 0.35)

# A floor, not a cap. A real 78% on a 34-day close is a real number.
check("a large but genuine figure is NOT clamped",
      annualized_spread(7.27, 34), 78.05,
      "clamping is what the probability endpoint did before it was deleted")
check("nothing above the floor is altered", annualized_spread(4.24, 126), 12.28)

print()
print("THE CLOSE-DATE READER SEES THE WHOLE FILING")
print("-" * 78)

# SLAB states its close date twice, at offsets 12,483 and 5,517. The old cap
# was 5,000, so the press release missed by 517 characters.
_SENT = ('The transaction is expected to close in the first half of 2027, '
         'subject to receipt of regulatory approvals.')
check("the cap matches extract_transaction_value's", CLOSE_DATE_SCAN_CHARS, 25000,
      "was 5,000 — the tightest in the file by 5x, on the same text")
check("SLAB's phrase at its real offset is now read",
      extract_close_date(('x' * 12483) + ' ' + _SENT), 'first half of 2027',
      "the 8-K offset; returned TBD under the old cap")
check("and at the press release offset",
      extract_close_date(('x' * 5517) + ' ' + _SENT), 'first half of 2027',
      "missed the old 5,000 window by 517 characters")
check("beyond the new cap it still abstains rather than guessing",
      extract_close_date(('x' * 26000) + ' ' + _SENT), 'TBD')

print()
print("A TRANSACTION VALUE IS CHECKED AGAINST ITS OWN COMPANY")
print("-" * 78)

# CBZ reached production with tx_value 60.0 -- sixty billion -- on a company
# with 54,263,879 shares at $55.00, an implied equity value of $2.98B. The only
# guard was 0.01 <= tx <= 500, which asks whether the number could belong to
# SOME deal rather than to THIS one.
_ok, _why = tx_value_plausible(60.0, 55.00, 'CBZ', shares=54_263_879)
check("CBZ: a 20x overstatement is rejected", _ok, False)
check("  and the reason names the comparison",
      ('20.1x' in (_why or '') and 'equity value' in (_why or '')), True, _why)
check("the true value for the same deal passes",
      tx_value_plausible(2.98, 55.00, 'CBZ', shares=54_263_879)[0], True)

# The band was set from the live feed, not from intuition. Both genuinely
# leveraged targets have to survive it.
check("CZR at 2.79x survives — a leveraged target's EV exceeds its equity",
      tx_value_plausible(17.6, 31.00, 'CZR', shares=203_777_357)[0], True)
check("BZH at 2.46x survives",
      tx_value_plausible(2.2, 33.50, 'BZH', shares=26_679_623)[0], True)
check("the ceiling leaves room beyond the feed's worst real case",
      TX_VALUE_MAX_RATIO > 2.79, True, f"ceiling {TX_VALUE_MAX_RATIO}x vs CZR 2.79x")

# A net-cash target's enterprise value sits BELOW its equity, so the floor has
# to be under 1 -- but not so far under that a decimal slip survives.
check("a net-cash target below parity survives",
      tx_value_plausible(0.9, 10.00, 'X', shares=100_000_000)[0], True, "0.90x")
check("a value an order of magnitude too small is rejected",
      tx_value_plausible(0.1, 10.00, 'X', shares=100_000_000)[0], False, "0.10x")

# Unknowable inputs pass. Refusing on absence would discard good values every
# time yfinance is down.
for _lbl, _args in [('no share count', (60.0, 55.0, 'CBZ', 0)),
                    ('no deal price',  (60.0, None, 'CBZ', 54_263_879)),
                    ('no tx_value',    (None, 55.0, 'CBZ', 54_263_879))]:
    check(f"{_lbl} passes rather than rejecting", tx_value_plausible(*_args)[0], True)

print()
print("ACQUIRER TYPE IS READ FROM THE ACQUIRER")
print("-" * 78)

# GSAT reached production as acquirer_type 'Private Equity' with AMAZON as the
# acquirer, because get_acquirer_type returned PE unconditionally whenever
# deal_type already said so. One unvalidated field propagating into a second.
check("GSAT: Amazon is not private equity, whatever deal_type says",
      get_acquirer_type('Private Equity', 'Amazon'), 'Strategic',
      "was 'Private Equity', inherited from deal_type")
check("the same acquirer reads the same under any deal_type",
      get_acquirer_type('All Cash', 'Amazon'), get_acquirer_type('Private Equity', 'Amazon'),
      "deal_type no longer changes the answer")

# A real PE buyer is still caught, and now by its own name rather than by a
# deal_type that may itself be wrong.
check("a PE firm is still typed PE on an All Cash deal",
      get_acquirer_type('All Cash', 'Bernhard Capital Partners'), 'Private Equity')
check("and on a Private Equity deal", 
      get_acquirer_type('Private Equity', 'Arcline Investment Management'), 'Private Equity')
check("a strategic buyer stays strategic",
      get_acquirer_type('All Cash', 'Smithfield Foods'), 'Strategic')

# No buyer named is not grounds to claim one type over the other. 'Strategic'
# was the old default and it is a claim, not an absence.
for _none in ('Undisclosed', '', None, 'none'):
    check(f"{_none!r} yields Unknown, not a default",
          get_acquirer_type('Private Equity', _none), 'Unknown')

print()
print("CLOSE DATE IS VALIDATED ON EVERY PATH, NOT JUST THE MODEL'S")
print("-" * 78)

# BWMN's "Q2 2026" never went near the model. extract_close_date found it in
# EX-99.2, in a cross-reference to that morning's separate earnings release --
# "Bowman's Q2 2026 Earnings Results" -- because the standalone Q-pattern needs
# no close language nearby. The validator existed and guarded only the
# enrichment path, so it never saw the value.
check("BWMN: the construction path is now checked too",
      validate_close_date('Q2 2026', '2026-08-10')[0], None,
      "regex-sourced, six weeks before the announcement")

# A bad regex hit also SUPPRESSED the guarded path: enrichment only runs when
# close_date == 'TBD'. Rejecting to TBD is what lets the validated reader run.
check("rejection returns the field to TBD so enrichment can try",
      validate_close_date('Q2 2026', '2026-08-10')[0] is None, True)

check("SLAB's recovered date is unaffected",
      validate_close_date('first half of 2027', '2026-02-04'),
      ('first half of 2027', None))
check("a tender expiry after announcement passes",
      validate_close_date('2026-10-20', '2026-06-24')[0], '2026-10-20')
check("a tender expiry before announcement is refused",
      validate_close_date('2026-05-01', '2026-06-24')[0], None)

print()
print("THE QUARTER FORM, AND A CAP SIZED TO THE DOCUMENT")
print("-" * 78)

# CBZ's PREM14A states "the Merger will be completed during the fourth quarter
# of 2026". The patterns carried an explicit (?:half of)? accommodation and no
# quarter twin, so "second half of 2026" read and "fourth quarter of 2026" did
# not -- while parse_close_date resolved it fine either way.
_CBZ = ('We currently anticipate that the Merger will be completed during the '
        'fourth quarter of 2026, but we cannot be certain when.')
check("CBZ's phrasing is now extracted",
      extract_close_date(_CBZ), 'fourth quarter of 2026', "returned 'TBD'")
check("and resolves to the quarter's end",
      parse_close_date('fourth quarter of 2026'), date(2026, 12, 31))
for _q, _want in [('first quarter of 2027', 'first quarter of 2027'),
                  ('third quarter of 2026', 'third quarter of 2026')]:
    check(f"'{_q}' reads", extract_close_date(f'expected to close in the {_q}'), _want)
check("the half form still reads",
      extract_close_date('expected to close in the second half of 2026'),
      'second half of 2026', "the accommodation this was modelled on")
check("the Q-abbreviation still reads",
      extract_close_date('expected to close in Q4 2026'), 'Q4 2026')

# A proxy is an order of magnitude longer than an 8-K. CBZ's is 884,167 chars
# and states its close at offset 102,755 -- under 3% of the way in.
check("a proxy cap exists and is far larger than the 8-K one",
      PROXY_CLOSE_DATE_SCAN_CHARS > CLOSE_DATE_SCAN_CHARS * 10, True,
      f"{PROXY_CLOSE_DATE_SCAN_CHARS:,} vs {CLOSE_DATE_SCAN_CHARS:,}")
check("at CBZ's real offset the 8-K cap sees nothing",
      extract_close_date(('x' * 102755) + ' ' + _CBZ), 'TBD')
check("and the proxy cap reads it",
      extract_close_date(('x' * 102755) + ' ' + _CBZ,
                         scan_chars=PROXY_CLOSE_DATE_SCAN_CHARS),
      'fourth quarter of 2026')
check("it validates against CBZ's announcement",
      validate_close_date('fourth quarter of 2026', '2026-07-29')[0],
      'fourth quarter of 2026')
check("the proxy cap is bounded, not unlimited",
      extract_close_date(('x' * 500000) + ' ' + _CBZ,
                         scan_chars=PROXY_CLOSE_DATE_SCAN_CHARS), 'TBD',
      "a proxy holds hundreds of dates that are not guidance")

print()
print("THE EXHIBIT IS FOUND BY ITS TYPE, NOT ITS FILENAME")
print("-" * 78)

# BOW filed its merger agreement as triplecrown-mergeragreemen.htm -- the deal's
# project codename. ATKR filed atkr_mergerk.htm. Neither carries an ex2 token,
# so _pick_ex2 returned None on both and two 8-Ks went unread while every
# sibling deal had a commitment reading and an outside date.
for _nm in ('triplecrown-mergeragreemen.htm', 'atkr_mergerk.htm'):
    check(f"filename matching cannot see {_nm}", _pick_ex2([_nm]), None,
          "which is why document TYPE is now the primary test")
check("conventionally named exhibits still match by filename",
      [_pick_ex2([n]) for n in ('d143382dex21.htm', 'tm2622398d1_ex2-1.htm',
                                'dp248400_ex0201.htm', 'ex2-1.htm')],
      ['d143382dex21.htm', 'tm2622398d1_ex2-1.htm',
       'dp248400_ex0201.htm', 'ex2-1.htm'],
      "the fallback still carries 17 of 19 deals")
check("the filename filter still rejects near-misses",
      [_pick_ex2([n]) for n in ('index2.htm', 'ex1002.htm', 'd1ex21.jpg')],
      [None, None, None])

print()
print("=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")
