import re

QUALIFIER_WORDS = {
    'q1','q2','q3','q4','first','second','third','fourth',
    'early','mid','late','half','calendar','fiscal',
}

def extract_close_date(clean_text):
    patterns=[
        r'(?:expected|anticipated|projected)\s+to\s+close.*?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:half[-\s]+of[-\s]+)?(?:of\s+)?20\d{2})',
        r'(?:expected|anticipated|projected)\s+to\s+be\s+completed.*?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:half[-\s]+of[-\s]+)?(?:of\s+)?20\d{2})',
        r'transaction.*?(?:expected|anticipated|projected).*?(?:close|complete|consummat).*?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late|second half|first half)[-\s]+(?:of\s+)?20\d{2})',
        r'(?:close|complete|consummat).*?(?:by|in|during)\s+((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:of\s+)?20\d{2})',
        r'anticipated\s+to\s+close.*?(?:in\s+)?((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:of\s+)?20\d{2})',
        r'close.*?(?:by|in)\s+((?:Q[1-4]|first|second|third|fourth|early|mid-?|late)[-\s]+(?:of\s+)?20\d{2})',
        r'\b(Q[1-4]\s+20\d{2})\b',
        r'\b((?:first|second|third|fourth|early|mid|late)[-\s]+(?:half[-\s]+of[-\s]+)?20\d{2})\b',
        r'calendar\s+year\s+(20\d{2})',
        r'(?:fiscal|calendar)\s+(?:year\s+)?(20\d{2})',
        r'(?:expected|anticipated)\s+to\s+(?:close|complete).*?(?:in\s+(?:the\s+)?)?((?:first|second|third|fourth|early|mid-?|late)[-\s]+(?:half[-\s]+of[-\s]+)?20\d{2})',
        r'(?:expected|anticipated)\s+to\s+(?:close|complete).*?(\w+[-\s]+20\d{2})',
    ]
    for pat in patterns:
        m=re.search(pat, clean_text[:5000], re.IGNORECASE)
        if m:
            result = m.group(1).strip()
            if not any(yr in result for yr in ['2025','2026','2027','2028']):
                continue
            first_word = re.split(r'[-\s]', result)[0].lower()
            if first_word in ('of', 'the', 'in'):
                continue
            if len(re.split(r'[-\s]', result)) == 2 and first_word not in QUALIFIER_WORDS:
                continue
            return result
    return 'TBD'

tests = [
    ("expected to close in the second half of 2026",                       "second half of 2026"),
    ("The transaction is expected to close in the first half of 2027",      "first half of 2027"),
    ("expected to close in Q3 2026",                                        "Q3 2026"),
    ("anticipated to close in early 2027",                                  "early 2027"),
    ("expected to close in late 2026 or early 2027",                        "late 2026"),
    ("transaction expected to be completed in mid-2027",                    "mid-2027"),
    ("expected to close by calendar year 2026",                             "2026"),
    ("expected to close in 2027, subject to",                               "TBD"),
    ("expected to close in the second half of 2026 subject to regulatory",  "second half of 2026"),
]

all_pass = True
for text, expected in tests:
    got = extract_close_date(text)
    status = "OK" if got == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"{status}: '{text[:65]}' -> got '{got}', expected '{expected}'")

print()
print("All 9 passed." if all_pass else "FAILURES above — do not implement into main.py.")