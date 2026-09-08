"""
test_extract_acquirer.py -- validates extract_acquirer against string fixtures.
Imports the real function from main.py so the test cannot drift from what ships.
Run locally: py test_extract_acquirer.py   (no network calls)
"""
from main import extract_acquirer

tests = [
    # Original 7
    ("Smithfield to acquire Nathan's (present infinitive)",
     "Smithfield Foods to acquire all of Nathan's Famous' issued and outstanding shares for $102.00 per share.",
     "Nathan's Famous", "Smithfield Foods"),
    ("Caesars to be acquired by Fertitta (passive)",
     "Caesars Entertainment, Inc. has entered into a definitive agreement to be acquired by Fertitta Entertainment for $31.00 per share in cash.",
     "Caesars Entertainment", "Fertitta Entertainment"),
    ("Generic 'will be acquired by'",
     "The Company entered into an Agreement and Plan of Merger pursuant to which it will be acquired by Blackstone Capital Partners in an all-cash transaction.",
     "The Company", "Blackstone Capital Partners"),
    ("Target name first, acquirer second",
     "Nathan's Famous, Inc. announced today that Smithfield Foods will acquire all of Nathan's Famous' outstanding shares for $102.00 per share.",
     "Nathan's Famous", "Smithfield Foods"),
    ("Active past: acquirer has agreed to acquire",
     "Long Lake Management has agreed to acquire Global Business Travel Group for $9.50 per share.",
     "Global Business Travel Group", "Long Lake Management"),
    ("No acquirer -- returns Undisclosed",
     "The Company has entered into a definitive merger agreement. The transaction is subject to customary closing conditions.",
     "The Company", "Undisclosed"),
    ("Consortium: will be acquired by",
     "The AES Corporation announced that it will be acquired by Global Infrastructure Partners and EQT for $15.00 per share.",
     "AES Corporation", "Global Infrastructure Partners"),
    # New failure cases from production
    ("WBD: section header before name",
     "Transaction Highlights Paramount will acquire Warner Bros. Discovery for $31.00 per share.",
     "Warner Bros. Discovery", "Paramount"),
    ("PAYO: lead-in clause before name",
     "Under the terms of the agreement, Nuvei will acquire Payoneer for $7.40 per share.",
     "Payoneer", "Nuvei"),
    ("GSAT: lead-in clause before name",
     "As part of the agreement, Amazon will acquire Globalstar for $1.20 per share.",
     "Globalstar", "Amazon"),
    ("CLST: date run-together, target should be rejected",
     "April 8, 2026Catalyst Bancorp, Inc. entered into a definitive agreement to be acquired by Siemens for $14.00 per share.",
     "Catalyst Bancorp", "Siemens"),
    ("AVNS: full multi-word name must not be truncated",
     "American Industrial Partners to acquire Avanos Medical for $14.50 per share in an all-cash deal.",
     "Avanos Medical", "American Industrial Partners"),
    # Parenthetical defined term between the legal name and the verb (BOW)
    ("BOW: name, entity suffix, parenthetical, then verb",
     'American Family Mutual Insurance Company, S.I. (together with its affiliates, "American Family") has agreed to acquire all of the issued and outstanding shares of common stock of Bowhead Specialty Holdings Inc. for $34.00 per share.',
     "Bowhead Specialty Holdings", "American Family"),
    # All-caps headline verb + all-caps acquirer name (CBZ)
    ("CBZ: ALL-CAPS 'TO ACQUIRE' headline",
     "GRANT THORNTON ADVISORS TO ACQUIRE CBIZ FOR $5 BILLION IN TRANSACTION SUPPORTED BY NEW MOUNTAIN CAPITAL. CBIZ shareholders to receive $55.00 per share in cash.",
     "CBIZ, Inc.", "Grant Thornton Advisors"),
    # Sponsor take-private: named only in the headline, agreement caption is shells (DSGR)
    ("DSGR: 'taken private by affiliates of X'",
     'DISTRIBUTION SOLUTIONS GROUP TO BE TAKEN PRIVATE BY AFFILIATES OF LKCM HEADWATER INVESTMENTS FOR $35.00 PER COMMON SHARE IN CASH. Newly formed entities controlled by LKCM Headwater Investments, LLC (collectively, "LKCM Headwater") will acquire all of the outstanding shares of common stock of DSG.',
     "Distribution Solutions Group", "LKCM Headwater"),
    # Shell names in an agreement caption must never win (guards BAD_PHRASES stays)
    ("Shell caption alone yields Undisclosed, not a shell",
     "AGREEMENT AND PLAN OF MERGER by and among ECLIPSE PARENT ACQUISITIONS, LLC, ECLIPSE ACQUISITIONS MERGER SUB, INC. and DISTRIBUTION SOLUTIONS GROUP, INC. Dated as of July 15, 2026.",
     "Distribution Solutions Group", "Undisclosed"),
]

print(f"{'Test':<48} {'got':<32} {'expected':<32} result")
print("-" * 120)
all_pass = True
for label, text, target, expected in tests:
    got = extract_acquirer(text, target_name=target)
    if expected == 'Undisclosed':
        ok = got == 'Undisclosed'
    else:
        ok = got != 'Undisclosed' and expected.lower() in got.lower()
    if not ok:
        all_pass = False
    print(f"{label:<48} {got:<32} {expected:<32} {'OK' if ok else 'FAIL'}")

print()
print("All %d passed." % len(tests) if all_pass else "FAILURES above -- do not push to main.py.")