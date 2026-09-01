"""
The integrity sweep, tested against the shapes of the nine defects it exists to
catch. Every case here is a real one from this week's feed.
"""
import sys
import main
import integrity

ok = True
def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if detail:
        print(f"        {detail}")


def flags(deal, extra=None):
    """Findings for one deal, padded so ubiquity has a feed to compare against."""
    feed = [dict(deal)] + [dict(extra or {}, ticker=f'PAD{i}') for i in range(9)]
    return [f for f in integrity.sweep(feed, main) if f.ticker == deal['ticker']]


def checks_of(deal, name, extra=None):
    return [f for f in flags(deal, extra) if f.check == name]


BASE = {'ticker': 'X', 'cp': 10.0, 'dp': 12.0, 'sp_pct': 20.0,
        'filed': '2026-01-05', 'break_price': 8.0}

print("THE SWEEP FINDS THE SHAPES THAT GOT THROUGH THIS WEEK")
print("-" * 78)

check("a clean deal raises nothing", not flags(BASE, BASE),
      "the report has to be quiet to be worth reading")

# CBZ: tx_value 60.0 on a company worth $2.98B, labelled regex_enterprise.
check("a transaction value wildly off its own company is flagged",
      checks_of(dict(BASE, ticker='CBZ', cp=54.67, dp=55.0, sp_pct=0.6,
                     tx_value=60.0, break_price=40.0), 'tx_value'),
      "CBZ, 20x its equity value")

# AES, then BZH: a break price at or above the current price.
_bp = checks_of(dict(BASE, ticker='BZH', cp=33.18, dp=33.5, sp_pct=0.96,
                     break_price=33.46), 'break_price')
check("a break price above the current price is flagged", _bp,
      _bp[0].detail[:88] if _bp else '')

# BWMN: a close date six weeks before the deal was announced.
check("a close date preceding the announcement is flagged",
      checks_of(dict(BASE, ticker='BWMN', filed='2026-08-10',
                     close_date='Q2 2026'), 'close_date'))
# ATKR and GSAT: a bare year, which names a 365-day window.
check("a bare-year close date is flagged",
      checks_of(dict(BASE, ticker='GSAT', close_date='2027'), 'close_date'))
check("a properly granular close date is not",
      not checks_of(dict(BASE, close_date='Q3 2026'), 'close_date'))

# GSAT: acquirer_type Private Equity with Amazon as the acquirer. CBZ and DSGR:
# the type left at Unknown after enrichment filled the acquirer in.
check("an acquirer_type that disagrees with its acquirer is flagged",
      checks_of(dict(BASE, ticker='GSAT', acquirer='Amazon',
                     acquirer_type='Private Equity', deal_type='Private Equity'),
                'acquirer_type'),
      "Amazon is not private equity")
check("a stale Unknown after enrichment is flagged",
      checks_of(dict(BASE, ticker='CBZ', acquirer='Grant Thornton Advisors LLC',
                     acquirer_type='Unknown'), 'acquirer_type'))

# GSAT: barriers passed, blended never persisted.
check("barriers passing with no blended price is flagged",
      checks_of(dict(BASE, ticker='GSAT',
                     pricing={'all_passed': True, 'blended': None}), 'pricing'))

# GBCS: the deadline arrived. Not an error -- the single most important state
# the field holds, and the report says so rather than staying silent.
_od = checks_of(dict(BASE, ticker='GBCS', outside_date={
    'date': '2026-08-31', 'passed': True, 'days_remaining': -1}), 'outside_date')
check("a passed outside date is surfaced", _od,
      _od[0].detail[:96] if _od else '')
check("  and named as walkable",
      _od and 'walk without a break fee' in _od[0].detail)
check("an outside date before the announcement is flagged",
      checks_of(dict(BASE, ticker='Y', filed='2026-06-01',
                     outside_date={'date': '2026-01-15'}), 'outside_date'))

# A spread that does not follow from its own inputs -- the shape that would
# have caught sp_pct computed off the headline while a blended value governed.
check("a spread that disagrees with cp and dp is flagged",
      checks_of(dict(BASE, sp_pct=9.3), 'spread'),
      "cp 10.00 and dp 12.00 give 20%, not 9.3%")
check("a spread measured off a governing blended value is accepted",
      not checks_of(dict(BASE, sp_pct=6.05, cp=82.34, dp=90.0,
                         break_price=70.0,
                         pricing={'all_passed': True, 'blended': 87.32}), 'spread'),
      "the blended value governs, so 6.05% is correct")

# Provenance labels that disagree with the record.
check("a verified_hardcode label with no verified entry is flagged",
      checks_of(dict(BASE, ticker='ZZZZ', tx_value=1.0,
                     tx_value_source='verified_hardcode'), 'tx_value_source'))
check("a tx_value with no provenance label at all is flagged",
      checks_of(dict(BASE, tx_value=1.0), 'tx_value_source'))
check("a close_date_source with no close date is flagged",
      checks_of(dict(BASE, close_date_source='llm_enriched'), 'close_date_source'))

# Missing what almost every other deal has.
_miss = flags(dict(BASE, ticker='M'), dict(BASE, outside_date={'date': '2027-01-01'}))
check("a field 9 of 10 deals carry is flagged when absent",
      any(f.check == 'outside_date' and 'absent' in f.detail for f in _miss),
      next((f.detail for f in _miss if 'absent' in f.detail), ''))

# An empty dict is absence, not a dropped write. /api/deals turns every missing
# structured field into {}, so treating that as a finding drowns the report --
# it produced 20 false alarms on the first run.
check("an empty structured field is not itself a finding",
      not [f for f in flags(dict(BASE, pricing={}, direction={}), BASE)
           if f.check in ('pricing', 'direction')],
      "parse_structured turns absence into {} for the whole feed")

print()
print("ACQUIRER TYPE FOLLOWS THE ACQUIRER WHEN ENRICHMENT CHANGES IT")
print("-" * 78)

# CBZ and DSGR carried acquirer_type 'Unknown' while naming Grant Thornton and
# LKCM Headwater. Both were 'Undisclosed' at detection -- which correctly yields
# 'Unknown' -- and the enrichment pass filled the acquirer in without
# recomputing the type. The sweep found it; this is the rule it should follow.
check("an undisclosed acquirer types as Unknown at detection",
      main.get_acquirer_type('All Cash', 'Undisclosed') == 'Unknown')
for _tk, _acq, _want in [('CBZ', 'Grant Thornton Advisors LLC', 'Strategic'),
                         ('DSGR', 'LKCM Headwater Investments, LLC', 'Strategic'),
                         ('BWMN', 'Bernhard Capital Partners', 'Private Equity')]:
    check(f"{_tk}: once enriched, it types as {_want}",
          main.get_acquirer_type('All Cash', _acq) == _want,
          f"{_acq!r}")
check("and the sweep no longer questions the recomputed value",
      not checks_of(dict(BASE, ticker='CBZ', acquirer='Grant Thornton Advisors LLC',
                         acquirer_type='Strategic'), 'acquirer_type'))

print()
print("PREMIUM — SURFACED, AND NOT MISTAKEN FOR SAFETY")
print("-" * 78)

# BZH: $33.50 against a $33.46 pre-announcement close, at 0.8x book, with the
# press release stating no premium anywhere. Nothing else in the sweep catches
# it -- its spread, close date and tx_value are all unremarkable.
_bz = checks_of(dict(BASE, ticker='BZH', cp=33.18, dp=33.5, sp_pct=0.96,
                     break_price=33.46), 'premium')
check("a deal priced at market is flagged", _bz, _bz[0].detail[:92] if _bz else '')
check("  and all three explanations are named",
      _bz and all(w in _bz[0].detail for w in
                  ('no-premium deal', 'wrong deal price', 'absorbed')))
check("a healthy premium is not flagged",
      not checks_of(dict(BASE, ticker='GBTG', cp=9.46, dp=9.5, sp_pct=0.42,
                         break_price=5.93), 'premium'),
      '60.2% — the next-lowest real deal is CZR at 7.7%, clear of the 5% bar')

# A stated premium is a filing fact and outranks our own break-price estimate,
# which AUDIT #8 shows is a price lookup rather than a model.
_st = main.deal_premium({'dp': 14.0, 'break_price': 11.23},
                        'representing a premium of approximately 42% to the '
                        'closing price on March 3, 2026.')
check("a stated premium wins over the computed one", _st['basis'] == 'stated',
      f"{_st['value']}% {_st['basis']}")
check("  and carries the filing's own reference",
      'March 3, 2026' in _st['reference'], _st['reference'])
_cp = main.deal_premium({'dp': 33.5, 'break_price': 33.46,
                         'break_price_method': 'historical'}, 'no premium language')
check("with no stated premium it computes and says so",
      _cp['basis'] == 'computed' and 'states no premium' in _cp['reference'])
check("and marks a thin one", _cp['thin'] is True, f"{_cp['value']}%")

# §30C, carried with the number rather than left to the reader.
check("the caveat says what a premium measures",
      'standalone downside' in _cp['caveat'] and 'vote yes' in _cp['caveat'])
check("and what it does not",
      'not evidence the deal will close' in _cp['caveat'] and
      'regulatory risk' in _cp['caveat'])

# A premium that cannot be read is not invented.
for _bad in ({'dp': None}, {'dp': 14.0}, {'dp': 14.0, 'break_price': 0}):
    check(f"no premium invented from {_bad}", main.deal_premium(_bad, '') is None)

print()
print("=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")
