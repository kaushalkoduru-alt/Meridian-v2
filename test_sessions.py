"""
Barrier 9 counts trading sessions, so the cases that matter are the ones where
elapsed hours and elapsed sessions disagree. Those are exactly the cases the
hours-based version got wrong.
"""
import sys
from datetime import datetime, timedelta
sys.path.insert(0, '/home/claude/pricing')
from deal_pricing import sessions_since

# Anchor on known weekdays so the tests do not drift with the calendar.
# 2026-08-07 is a Friday, 08-08 Sat, 08-09 Sun, 08-10 Mon, 08-12 Wed.
FRI = datetime(2026, 8, 7, 4, 0)     # a daily bar, stamped midnight ET
SAT = datetime(2026, 8, 8, 12, 0)
SUN = datetime(2026, 8, 9, 22, 0)
MON_PRE = datetime(2026, 8, 10, 12, 0)   # Monday before the close
MON_POST = datetime(2026, 8, 10, 22, 0)  # Monday after the close
WED = datetime(2026, 8, 12, 22, 0)
NEXT_MON = datetime(2026, 8, 17, 22, 0)

CASES = [
    ("Friday's bar, checked Saturday", FRI, SAT, 0,
     "nothing newer exists on a Saturday"),
    ("Friday's bar, checked Sunday", FRI, SUN, 0,
     "the case that broke the hours version -- read as 70h old, actually current"),
    ("Friday's bar, Monday before the close", FRI, MON_PRE, 0,
     "Monday has not closed yet, so Friday is still the latest close"),
    ("Friday's bar, Monday after the close", FRI, MON_POST, 1,
     "one session has now closed without a new bar"),
    ("Friday's bar, checked Wednesday", FRI, WED, 3,
     "genuinely stale -- three sessions have closed"),
    ("Friday's bar, checked the following Monday", FRI, NEXT_MON, 6,
     "very stale"),
    ("same-day bar", datetime(2026, 8, 12, 4, 0), WED, 0, "today's close"),
]

print("barrier 9 — trading-session staleness")
print("=" * 78)
ok = True
for label, bar, now, expected, why in CASES:
    got = sessions_since(bar, now)
    good = got == expected
    ok &= good
    hours = (now - bar).total_seconds() / 3600
    print(f"  {'PASS' if good else 'FAIL'}  {label}")
    print(f"        {got} session(s), {hours:.0f}h elapsed  (expected {expected})")
    print(f"        {why}")

print("=" * 78)
print("ALL PASS" if ok else "FAILED")
print()
print("The point: on a Sunday, Friday's close is 70 hours old and zero sessions")
print("behind. It is not stale. It is the only price that exists.")