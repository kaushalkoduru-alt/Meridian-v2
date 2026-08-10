"""
BACKFILL deal_type AND acquirer_type FROM THE VERIFICATION NOTES

Every row already records the structure -- "all cash", "all cash tender offer",
"all cash, PE take-private" -- because it was written down while reading each
filing. This turns that free text into two columns.

The split follows main.py's convention, which keeps these separate for good
reason:

    deal_type      what holders receive.  All Cash / Tender Offer / Cash + Stock
    acquirer_type  who is buying.         Private Equity / Strategic

A PE take-private structured as a plain cash merger is therefore All Cash with
a Private Equity acquirer -- not "Private Equity" as its deal type. Collapsing
the two would make it impossible to ask whether tender offers close more often
than one-step mergers, which is a claim V3 makes with its +10 / +8 weights.

Writes a new column pair and leaves everything else untouched. Prints every
classification so a wrong read is visible rather than silent.

Run from meridian-v2:
    python backfill_types.py           # show what it would do
    python backfill_types.py --write   # actually write
"""

import csv
import os
import re
import sys

WORKSHEET = "worksheet.csv"

# Ordered: the first match wins, so the most specific patterns come first.
DEAL_TYPE_RULES = [
    (r"cash\s*\+\s*stock|cash and stock|plus .* shares|in cash and .* in shares",
     "Cash + Stock"),
    (r"all[- ]stock|exchange ratio|shares of .* per .* share",
     "All Stock"),
    (r"election structure|elect .* or",
     "Election"),
    (r"tender offer",
     "Tender Offer"),
    (r"all cash",
     "All Cash"),
]

PE_MARKERS = [
    "take-private", "take private", "pe club", "private equity",
    "capital partners", "capital management", "partners llc", "holdings llc",
    "buyout", "sponsor",
]

# Acquirers known to be financial buyers from the verification pass. Name
# matching alone misreads plenty of these -- "Steel Partners Holdings" is an
# industrial holding company, not a fund -- so the list is explicit.
KNOWN_PE = {
    "blackstone", "searchlight", "eqt", "brightstar", "gtcr", "patient square",
    "warburg", "berkshire partners", "stonepeak", "deerfield", "tpg",
    "casago", "knox lane", "aya", "arcline", "american industrial",
    "titan bw", "metropolis", "velocity one", "retailco",
}
KNOWN_STRATEGIC = {
    "amazon", "stryker", "ibm", "hpe", "hewlett", "nippon", "j&j", "johnson",
    "novo", "emerson", "unitedhealth", "tapestry", "gentex", "globus",
    "alaska air", "hyatt", "seagate", "zimmer", "boston scientific",
    "roche", "immedica", "sega", "smithfield", "steel partners", "north american stainless",
    "acerinox", "ceco", "aptean", "clearwater", "omnicom", "capital one",
    "amcor", "chevron", "slb", "chesapeake", "eqt corporation", "mid penn",
    "cnb financial", "independent bank", "northwest bancshares",
}


def classify_deal_type(notes):
    low = notes.lower()
    for pattern, label in DEAL_TYPE_RULES:
        if re.search(pattern, low):
            return label
    return ""


def classify_acquirer_type(acquirer, notes):
    a = (acquirer or "").lower()
    low = notes.lower()
    for name in KNOWN_STRATEGIC:
        if name in a:
            return "Strategic"
    for name in KNOWN_PE:
        if name in a:
            return "Private Equity"
    if any(m in low for m in PE_MARKERS):
        return "Private Equity"
    return "Strategic" if a else ""


def main():
    write = "--write" in sys.argv
    if not os.path.exists(WORKSHEET):
        print("no worksheet.csv here")
        return

    with open(WORKSHEET, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else []

    for col in ("deal_type", "acquirer_type"):
        if col not in fields:
            fields.append(col)

    n_typed = 0
    print(f"{'ticker':<8}{'deal_type':<14}{'acquirer_type':<16}source note")
    print("-" * 92)
    for r in rows:
        notes = (r.get("consideration_notes") or "") + " " + (r.get("notes") or "")
        if not notes.strip():
            continue
        dt = classify_deal_type(notes)
        at = classify_acquirer_type(r.get("acquirer"), notes)
        r["deal_type"] = dt
        r["acquirer_type"] = at
        if dt or at:
            n_typed += 1
            tk = (r.get("ticker") or "?")[:7]
            snippet = re.sub(r"\s+", " ", notes).strip()[:44]
            print(f"{tk:<8}{dt or '-':<14}{at or '-':<16}{snippet}")

    print("-" * 92)
    print(f"classified {n_typed} rows")

    if not write:
        print("\ndry run. re-run with --write to save.")
        print("Read the columns above first: a wrong classification here quietly")
        print("becomes a wrong finding later.")
        return

    tmp = WORKSHEET + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    os.replace(tmp, WORKSHEET)
    print(f"\nwrote deal_type and acquirer_type to {WORKSHEET}")


if __name__ == "__main__":
    main()