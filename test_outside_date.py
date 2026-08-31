"""
Outside date, tested against merger agreement language.

The hazard this module shares with deal_commitment: a hand-built fixture puts
things closer together than a filing does, and a proximity window will bridge
the gap. Every fixture here keeps the real distance where distance matters.
"""
import sys
from datetime import datetime, timedelta
sys.path.insert(0, '/home/claude/commit')
from outside_date import (extract_outside_date, extract_agreement_date,
                          _relative_deadline)

ok = True
def check(label, cond, detail=""):
    global ok
    ok &= cond
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if detail:
        print(f"        {detail}")

NOW = datetime(2026, 8, 24)
ANN = datetime(2026, 2, 27)

print("OUTSIDE DATE")
print("=" * 78)

# ── standard definition ──────────────────────────────────────────────────────
r = extract_outside_date(
    'Section 8.1. Termination. This Agreement may be terminated at any time '
    'prior to the Effective Time by either Parent or the Company if the Merger '
    'shall not have been consummated on or prior to March 15, 2027 (the "End '
    'Date"); provided that the right to terminate shall not be available to any '
    'party whose breach caused the failure.',
    announced_date=ANN, now=NOW)
check("reads a not-consummated-by deadline",
      r is not None and r['date'] == '2027-03-15',
      f"{r['date']} · {r['days_remaining']} days · via {r['source']}" if r else "nothing found")

# ── defined-term shape ───────────────────────────────────────────────────────
r = extract_outside_date(
    '"End Date" means September 30, 2027, or such later date as the parties may '
    'agree in writing.', announced_date=ANN, now=NOW)
check("reads a defined End Date",
      r is not None and r['date'] == '2027-09-30',
      f"{r['date']}" if r else "nothing found")

# ── automatic extension: the later date governs ──────────────────────────────
r = extract_outside_date(
    'if the Merger shall not have been consummated on or prior to June 30, 2027 '
    '(the "End Date"); provided, however, that if on such date the Regulatory '
    'Conditions have not been satisfied, the End Date shall be automatically '
    'extended to December 31, 2027.', announced_date=ANN, now=NOW)
check("with an automatic extension, the LATER date governs",
      r is not None and r['date'] == '2027-12-31' and r['extendable'],
      f"{r['date']}, extendable={r['extendable']}" if r else "nothing found")

# ── a passed deadline ────────────────────────────────────────────────────────
r = extract_outside_date(
    'if the Merger shall not have been consummated on or prior to April 1, 2026 '
    '(the "End Date")',
    announced_date=datetime(2025, 6, 1), now=NOW)
check("a passed deadline is flagged",
      r is not None and r['passed'],
      f"{r['date']}, {r['days_remaining']} days" if r else "nothing found")
if r:
    check("passed deadline explains the consequence",
          'walk away' in r['meaning'] and 'passed' in r['meaning'].lower(),
          r['meaning'][:100])

# ── implausible dates rejected ───────────────────────────────────────────────
r = extract_outside_date(
    'This Agreement, dated as of February 27, 2026, refers to the Prior '
    'Agreement dated January 3, 2019 and the fiscal year ending December 31, 2035.',
    announced_date=ANN, now=NOW)
check("a date before signing and one a decade out are both rejected",
      r is None, f"got {r['date']}" if r else "nothing found, correct")

# ── the quote is carried for verification ────────────────────────────────────
r = extract_outside_date(
    'if the Merger shall not have been consummated on or prior to March 15, 2027 '
    '(the "End Date")', announced_date=ANN, now=NOW)
check("carries the filing quote so the date is checkable",
      r is not None and 'March 15, 2027' in r['quote'],
      r['quote'][:90] if r else "")

# ── plain-language meaning ───────────────────────────────────────────────────
check("meaning avoids jargon and states the consequence",
      r is not None and 'break fee' in r['meaning'] and 'walk away' in r['meaning'],
      r['meaning'][:110] if r else "")

# ── near deadline warning ────────────────────────────────────────────────────
soon = NOW + timedelta(days=45)
r = extract_outside_date(
    f'if the Merger shall not have been consummated on or prior to '
    f'{soon.strftime("%B")} {soon.day}, {soon.year} (the "End Date")',
    announced_date=ANN, now=NOW)
check("under three months out, the meaning says so",
      r is not None and 'three months' in r['meaning'],
      f"{r['days_remaining']} days remaining" if r else "nothing found")

# ── distance: a definition far from a passing mention ────────────────────────
# The real hazard. The operative date is defined once; the term is then
# referenced dozens of times with other dates nearby. Those references must not
# capture whatever date happens to sit near them.
far = ('"End Date" means March 15, 2027.' + (' filler clause.' * 400) +
       ' Notice under this Section shall be delivered no later than '
       'November 8, 2026 following the End Date provisions above.')
r = extract_outside_date(far, announced_date=ANN, now=NOW)
check("a later passing mention does not override the definition",
      r is not None and r['date'] == '2027-03-15',
      f"{r['date']} via {r['source']}" if r else "nothing found")

# ── automatic vs elective extension ──────────────────────────────────────────
# Both blocks are the verbatim clause from the filing. Which kind of extension
# governs decides which date a holder is actually trading against, so it is
# tested against the real language rather than a paraphrase.

print()
print("EXTENSION KIND")
print("=" * 78)

# WBD, accession 0001437107-26-000018. AUTOMATIC: the date moves on its own when
# the antitrust conditions are unsatisfied, so the OUTER date is the deadline.
WBD = ('(b) by either the Company or Buyer, if: (i) the Effective Time shall not '
       'have occurred on or before March 4, 2027, or such other date agreed in '
       'writing by Buyer and the Company (any such date, the “End '
       'Date”); provided, however, that (A) if, on March 4, 2027, any of '
       'the conditions set forth in Section 7.1(d) or Section 7.1(e) (solely in '
       'connection with an Antitrust Law or Foreign Regulatory Law) has not been '
       'satisfied or waived, then the End Date shall be automatically extended, '
       'without any further action on the part of any Party hereto, to June 4, 2027')
r = extract_outside_date(WBD, announced_date=datetime(2026, 2, 27), now=NOW)
check("automatic extension: the OUTER date governs",
      r is not None and r['date'] == '2027-06-04' and r['extension_type'] == 'automatic',
      f"{r['date']} via {r['source']}" if r else "nothing found")
if r:
    check("automatic: the base date is not the one reported",
          r['date'] != '2027-03-04', f"reported {r['date']}, base was 2027-03-04")

# OGN, accession 0001193125-26-178718. ELECTIVE: a party must give written
# notice, so the BASE date is the deadline and April 26 is only an option.
OGN = ('this Agreement may be terminated by either the Company or Parent if: '
       '(a) the transactions contemplated by this Agreement shall not have been '
       'consummated by 5:00 p.m. (New York time) on January 26, 2027 (the '
       '“Outside Date”), whether before or after the Requisite Company '
       'Vote has been obtained; provided, that, if on or prior to the Outside '
       'Date any of the conditions set forth in Section 8.1(b) shall not have '
       'been satisfied but all other conditions set forth in Article VIII shall '
       'have been satisfied or waived, then either Parent or the Company may, by '
       'written notice to the other Party prior to 5:00 p.m. (New York Time) on '
       'the Outside Date, elect to extend the Outside Date until April 26, 2027, '
       'and such date shall thereafter be deemed the Outside Date for all '
       'purposes of this Agreement')
r = extract_outside_date(OGN, announced_date=datetime(2026, 4, 27), now=NOW)
check("elective extension: the BASE date governs",
      r is not None and r['date'] == '2027-01-26' and r['extension_type'] == 'elective',
      f"{r['date']} via {r['source']}" if r else "nothing found")
if r:
    check("elective: the outer date is NOT reported as the deadline",
          r['date'] != '2027-04-26',
          f"reported {r['date']}, the option was 2027-04-26")
    check("elective: the option is named in the meaning text",
          'April 26, 2027' in r['meaning'] and 'unless one of them does' in r['meaning'],
          r['meaning'][-130:])
    check("elective: the option date is carried as its own field",
          r.get('extension_date') == '2027-04-26', str(r.get('extension_date')))

# The hazard this replaces. OGN's agreement ALSO contains "shall automatically
# be extended" -- in a litigation-stay clause that names no calendar date. A
# document-level marker test reads that as automatic and reports April 26:
# three months of runway the holder does not have.
OGN_BOTH = OGN + (' The Outside Date shall automatically be extended to (i) '
                  'the twentieth Business Day following the resolution of such '
                  'Proceeding, or (ii) such other time period established by the '
                  'court presiding over such Proceeding.')
r = extract_outside_date(OGN_BOTH, announced_date=datetime(2026, 4, 27), now=NOW)
check("an unrelated automatic clause elsewhere does not flip the verdict",
      r is not None and r['date'] == '2027-01-26' and r['extension_type'] == 'elective',
      f"{r['date']}, {r['extension_type']}" if r else "nothing found")

# ── EXTENSIONS STATED AS A PERIOD ────────────────────────────────────────────
# APGE's agreement never names a second date. It extends automatically "by six
# (6) months" and leaves the arithmetic to the reader, so a reader that only
# looks for dates concluded the deadline was FIXED -- on an agreement that moves
# its own deadline half a year without anyone lifting a finger.
print()
print("PERIOD-STATED EXTENSIONS")
print("=" * 78)

APGE = ('by either the Company or Parent if the Effective Time has not occurred '
        'on or before December 18, 2026 (the "End Date"); provided that if on '
        'the End Date all of the conditions to Closing other than those relating '
        'to Antitrust Laws shall have been satisfied or waived, the End Date '
        'shall be automatically extended by six (6) months (and in the case of '
        'such extension, any reference to the End Date in any other provision of '
        'this Agreement shall be a reference to the End Date as so extended).')
r = extract_outside_date(APGE, announced_date=datetime(2026, 6, 22), now=NOW)
check("a period-stated automatic extension is found at all",
      r is not None and r['extension_type'] == 'automatic',
      f"{r['date']}, {r['extension_type']}" if r else "nothing found")
if r:
    check("the period is added as CALENDAR months, not 30.44-day approximations",
          r['date'] == '2027-06-18',
          f"{r['date']} (base was 2026-12-18, + six months)")
    check("the base date is not the one reported",
          r['date'] != '2026-12-18',
          f"reported {r['date']}, base was 2026-12-18")
    check("the quote shows the clause that computes the date",
          'six (6) months' in r['quote'],
          r['quote'][-120:])

# Consecutive automatic periods compound: the deadline that arrives without
# anyone acting is the last one in the chain, not the first.
APGE_CHAIN = APGE[:-1] + (' provided, further, that if on such extended End Date '
                          'those conditions shall have been satisfied, the End '
                          'Date shall be automatically extended by three (3) '
                          'months.')
r = extract_outside_date(APGE_CHAIN, announced_date=datetime(2026, 6, 22), now=NOW)
check("consecutive automatic periods compound",
      r is not None and r['date'] == '2027-09-18',
      f"{r['date']} (6 months then 3 more off 2026-12-18)" if r else "nothing found")

# An ELECTIVE period must not move the reported deadline, for the same reason an
# elective DATE does not: it arrives only if somebody acts.
APGE_ELEC = ('by either the Company or Parent if the Effective Time has not '
             'occurred on or before December 18, 2026 (the "End Date"); provided '
             'that the End Date may be extended by a period of six (6) months in '
             "Parent's sole discretion by written notice to the Company.")
r = extract_outside_date(APGE_ELEC, announced_date=datetime(2026, 6, 22), now=NOW)
check("an elective period leaves the BASE date as the deadline",
      r is not None and r['date'] == '2026-12-18' and r['extension_type'] == 'elective',
      f"{r['date']}, {r['extension_type']}" if r else "nothing found")
if r:
    check("the elective period is carried as the option date",
          r.get('extension_date') == '2027-06-18', str(r.get('extension_date')))

# The litigation stay NATH and OGN both carry. It extends "by the amount of time
# during which such Proceeding is pending" -- automatic, but tied to no period
# anyone can compute. Reading a number out of it would invent a deadline.
NATH_STAY = ('by either party if the Merger shall not have been consummated on '
             'or before April 20, 2026 (the "End Date"). Notwithstanding anything '
             'to the contrary, if prior to the End Date any party initiates a '
             'Proceeding to enforce specifically the terms of this Agreement, '
             'then the End Date shall be automatically extended by (i) the amount '
             'of time during which such Proceeding is pending plus twenty (20) '
             'Business Days.')
r = extract_outside_date(NATH_STAY, announced_date=datetime(2026, 1, 21), now=NOW)
check("an uncomputable litigation stay does not fabricate a period",
      r is not None and r['date'] == '2026-04-20',
      f"{r['date']} via {r['source']}" if r else "nothing found")

print()
print("DEADLINES DEFINED AS A PERIOD FROM SIGNING")
print("=" * 78)

# Four live agreements never state a calendar date. Every PATTERNS entry ends in
# one, so the module read nothing -- correctly, but four deals short.
_ATKR = ('the Effective Time shall not have occurred on or before the first '
         'Business Day that is twelve (12) months after the date of this Agreement')
_ALOT = ('if the Merger has not been consummated on or before the date that is '
         'one hundred and fifty (150) days after the date of this Agreement')
_RAMP = ('the Effective Time has not occurred on or before the date that is '
         'twelve (12) months after the date hereof')
_HZO = ('the Effective Time shall not have occurred on or prior to the date '
        'which is nine months following the date of this Agreement')

for _lbl, _txt, _agd, _want, _why in [
    ("ATKR: twelve (12) months, past a 'first Business Day that is'",
     _ATKR, datetime(2026, 8, 2), datetime(2027, 8, 2), ''),
    ("ALOT: one hundred and fifty (150) DAYS, not months",
     _ALOT, datetime(2026, 6, 16), datetime(2026, 11, 13),
     'the 120 bound was written for months and refused this'),
    ("RAMP: 'the date hereof' reads like 'of this Agreement'",
     _RAMP, datetime(2026, 5, 16), datetime(2027, 5, 16), ''),
    ("HZO: 'nine months' spelled out, with no numeral at all",
     _HZO, datetime(2026, 8, 9), datetime(2027, 5, 9), '')]:
    _r = _relative_deadline(_txt, _agd)
    check(_lbl, bool(_r) and _r[0] == _want,
          _why or f"{_agd.date()} -> {_r[0].date() if _r else 'nothing'}")

# The anchor is the agreement's own date. All four differ from their filing
# date, so falling back to it would move every one of these deadlines.
check("the agreement's stated date is read off the cover",
      extract_agreement_date('AGREEMENT AND PLAN OF MERGER By and Among X, Y '
                             'and Z Dated as of August 2, 2026 TABLE OF CONTENTS')
      == datetime(2026, 8, 2))
check("no agreement date means no deadline, not a guessed one",
      _relative_deadline(_ATKR, None) is None,
      'an anchor off by two days is a deadline off by two days')
check("the filing date would have moved ATKR by a day",
      _relative_deadline(_ATKR, datetime(2026, 8, 3))[0] == datetime(2027, 8, 3),
      'which is why the filing date is not the anchor')

# The bound is per unit now, or 150 days is refused while 150 months would pass.
check("an implausible month count is still refused",
      _relative_deadline('the Effective Time shall not have occurred on or '
                         'before the date that is (900) months after the date '
                         'of this Agreement', datetime(2026, 1, 1)) is None)
check("a plausible day count is allowed",
      _relative_deadline('the Merger has not been consummated on or before the '
                         'date that is (180) days after the date of this '
                         'Agreement', datetime(2026, 1, 1))[0] == datetime(2026, 6, 30))

# End to end: a relative base still runs through the extension classifier.
_FULL = _ALOT + (' (the "Outside Date"); provided that either party may elect to '
                 'extend the Outside Date by three (3) months.')
_r = extract_outside_date(_FULL, announced_date=datetime(2026, 6, 17),
                          agreement_date=datetime(2026, 6, 16), now=NOW)
check("a period-defined base is still classified for extensions",
      _r is not None and _r['source'] == 'period from the agreement date',
      _r['source'] if _r else 'nothing found')
check("and an elective extension leaves the base as the deadline",
      bool(_r) and _r['date'] == '2026-11-13',
      'elective moves nothing without someone acting')

print("=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")
