"""
DEAL STRUCTURE FLAGS — when the headline price is not what a holder receives

Hand-verifying 89 filings turned up the same structures over and over, and
every one of them breaks a naive screen that reads a dollar figure and calls it
the deal price:

  Steel Connect    $1.35 cash PLUS a contingent value right
  Paragon 28       $13.00 cash PLUS a CVR
  Enfusion         holders ELECT between mixed, stock, or cash consideration
  Emclaire         $40.00 cash OR 2.15 shares, capped 70/30 with proration
  Intevac          $4.00 plus a $0.052 special dividend at closing
  Revance          repriced from $3.10 to $3.65 mid-deal
  Vacasa           "$5.02 per share, subject to adjustment"
  Patterson        40-day go-shop, no competing bid emerged
  AspenTech        Emerson already held 57% before bidding for the rest

A screen showing "$1.35" for Steel Connect is not wrong about the cash. It is
wrong about what a holder gets, which is the only number that matters.

DESIGN
  Pure string matching on filing text. No API calls, no cost, deterministic.
  That last property matters: the direction check gave different answers on the
  same FSK filing across two runs, and a flag that flickers is worse than none.

  Every flag carries the phrase that triggered it, so a wrong flag is traceable
  rather than mysterious.

CONSERVATIVE BY DESIGN
  A missed flag leaves the product where it already is. A false flag tells a
  trader a clean deal is complicated, which is worse. So patterns require
  specific language rather than loose keywords, and anything ambiguous stays
  unflagged.
"""

import re

# ── flag identifiers ──────────────────────────────────────────────────────────
FLAG_CVR         = "CVR"
FLAG_ELECTION    = "ELECTION"
FLAG_ADJUSTMENT  = "ADJUSTMENT"
FLAG_GO_SHOP     = "GO_SHOP"
FLAG_CONTROLLING = "CONTROLLING_HOLDER"
FLAG_REPRICED    = "REPRICED"

# What each means to someone deciding whether to put money on a spread.
FLAG_MEANING = {
    FLAG_CVR: "Headline price is a floor. Holders also receive a contingent "
              "value right whose payout depends on future events and is often zero.",
    FLAG_ELECTION: "Holders choose between cash and stock, subject to proration. "
                   "What you actually receive depends on what everyone else elects.",
    FLAG_ADJUSTMENT: "Consideration is subject to adjustment before closing, so "
                     "the stated price is not final.",
    FLAG_GO_SHOP: "A go-shop window is open. A competing bid can still emerge, "
                  "and the break fee is usually reduced during it.",
    FLAG_CONTROLLING: "The buyer already holds a controlling stake. No competing "
                      "bid is realistic, but these deals draw fairness litigation.",
    FLAG_REPRICED: "The price has changed since announcement. Check which number "
                   "is current.",
}

# ── patterns ──────────────────────────────────────────────────────────────────
# Each entry: (compiled regex, flag, short label for the trigger phrase)
PATTERNS = [
    # CVR. Standard phrasing across every deal that used one.
    (r'contingent\s+value\s+right', FLAG_CVR, "contingent value right"),
    (r'\bCVR\s+Agreement\b', FLAG_CVR, "CVR Agreement"),
    (r'one\s+contractual\s+contingent', FLAG_CVR, "contractual contingent right"),

    # Election structures. Proration is the tell that an election is capped --
    # without a cap there is no allocation risk.
    (r'subject\s+to\s+proration', FLAG_ELECTION, "subject to proration"),
    (r'(?:may\s+)?elect\s+to\s+receive[^\n]{0,120}?(?:\bor\b|either)', FLAG_ELECTION, "elect to receive ... or"),
    (r'(?:cash|stock)\s+election\s+(?:consideration|amount)', FLAG_ELECTION, "cash/stock election"),
    (r'Per\s+Share\s+(?:Mixed|Cash|Stock)\s+Consideration', FLAG_ELECTION, "mixed/cash/stock consideration election"),

    # Adjustment. "Subject to adjustment" is boilerplate in some agreements, so
    # it is paired with a consideration term rather than matched alone.
    (r'(?:merger\s+consideration|per\s+share)[^\n]{0,80}?subject\s+to\s+adjustment',
     FLAG_ADJUSTMENT, "consideration subject to adjustment"),
    # Widened after Intevac was missed: its filing reads "payable to stockholders
    # of record immediately prior to the closing of the merger", which pushes the
    # closing reference past a tighter window. A special dividend tied to a merger
    # is a consideration modifier wherever the words land.
    (r'(?:one-?time\s+)?special\s+dividend[^\n]{0,220}?(?:clos|effective\s+time|merger)',
     FLAG_ADJUSTMENT, "special dividend tied to closing"),
    (r'pre-?closing\s+dividend', FLAG_ADJUSTMENT, "pre-closing dividend"),

    # Go-shop.
    (r'go-?shop\s+period', FLAG_GO_SHOP, "go-shop period"),
    (r'\bgo-?shop\b[^\n]{0,80}?(?:expire|solicit)', FLAG_GO_SHOP, "go-shop solicitation window"),

    # Controlling holder. A special committee alone is not enough -- those form
    # for other conflicts too -- so it is paired with evidence of an existing stake.
    (r'(?:already|currently)\s+owns?\s+approximately\s+\d+(?:\.\d+)?%',
     FLAG_CONTROLLING, "buyer already owns a stated stake"),
    (r'shares?\s+not\s+already\s+owned\s+by', FLAG_CONTROLLING, "shares not already owned by parent"),
    (r'remaining\s+(?:common\s+)?(?:stock|shares)\s+of', FLAG_CONTROLLING, "acquiring the remaining shares"),

    # Repriced.
    (r'amendment[^\n]{0,100}?(?:increase|decrease|revise)[^\n]{0,60}?(?:offer\s+price|merger\s+consideration|per\s+share)',
     FLAG_REPRICED, "amendment revising the price"),
    (r'(?:increased|reduced)\s+offer\s+price', FLAG_REPRICED, "increased/reduced offer price"),
    # Widened after Revance was missed: "representing $0.55 or 17% per share more
    # than the prior offer price" puts a percentage between the amount and the
    # comparison, which a stricter pattern walked straight past.
    (r'(?:more|less)\s+than\s+the\s+prior\s+offer', FLAG_REPRICED, "more/less than the prior offer"),
    (r'(?:Second|Third|First)\s+Amendment[^\n]{0,140}?(?:stockholders|shareholders)\s+will\s+receive',
     FLAG_REPRICED, "amendment restating what holders receive"),
]

# NOTE ON [^\n] vs [^.]
# These patterns originally used [^.]{0,N} to keep a match inside one sentence.
# That silently failed on any filing where a dollar amount sat between the two
# halves of the pattern, because "$0.052" contains a period. Intevac's special
# dividend went undetected for exactly that reason. detect_flags flattens
# whitespace before matching, so [^\n] bounds the distance without tripping on
# decimals.
COMPILED = [(re.compile(p, re.IGNORECASE), f, label) for p, f, label in PATTERNS]


def _snap_context_start(text, match_start, reach):
    """
    Finds a clean opening boundary for the quote, no more than `reach` chars
    before match_start.

    A raw match_start - reach cut lands mid-word as often as not (GSAT's
    quote used to open "ction Terms Under the terms of..." -- the tail of
    "Transaction Terms"). A first pass that only looked within a tight 100-char
    window and fell back to the nearest space still landed mid-phrase ("Terms
    Under the terms of...", dropping "Transaction"), because the real sentence
    boundary was a bit further back than that window reached. So the period
    search gets the full `reach` to work with -- real sentence breaks are
    almost always found well inside it -- and the word-boundary fallback is
    the last resort, not the common case.
    """
    anchor = max(0, match_start - reach)
    if anchor == 0:
        return 0
    segment = text[anchor:match_start]
    period_idx = segment.rfind('. ')
    if period_idx != -1:
        return anchor + period_idx + 2
    space_idx = segment.find(' ')
    if space_idx != -1:
        return anchor + space_idx + 1
    return anchor  # one unbroken run of non-space chars spanning the reach


def _snap_context_end(text, match_end, reach):
    """
    Finds a clean closing boundary for the quote, up to `reach` chars past
    match_end -- but greedily, consuming every complete sentence that fits
    rather than stopping at the first one.

    Stopping at the first sentence end cut GSAT's quote right after the
    election language and before the sentence that actually matters: the
    proration cap capping cash elections at 40%. That sentence is why the
    ELECTION flag exists -- without it the quote reads as a free cash/stock
    choice. So keep appending whole sentences for as long as the next one
    still fits within reach; only fall back to trimming at a word boundary if
    not even one complete sentence fits.
    """
    n = len(text)
    limit = min(n, match_end + reach)
    pos = match_end
    end = None
    while pos < limit:
        segment = text[pos:limit]
        idx = segment.find('. ')
        if idx == -1:
            break
        end = pos + idx + 1  # include the period, drop the trailing space
        pos = pos + idx + 2  # look for the next sentence after this one
    if end is not None:
        return end
    if limit == n:
        return n  # ran out of text -- the end of the document is a clean stop too
    segment = text[match_end:limit]
    space_idx = segment.rfind(' ')
    if space_idx != -1:
        return match_end + space_idx
    return limit  # one unbroken run of non-space chars spanning the reach


def detect_flags(filing_text, max_chars=40000):
    """
    Returns a list of {flag, trigger, meaning}, one per distinct flag.

    max_chars bounds the scan: merger agreements run past 300,000 characters and
    the structural terms always appear early. Reading the whole document mostly
    adds boilerplate that produces false positives.
    """
    if not filing_text:
        return []

    text = re.sub(r'\s+', ' ', filing_text[:max_chars])
    seen = {}
    for rx, flag, label in COMPILED:
        if flag in seen:
            continue  # one entry per flag; the first trigger is enough
        m = rx.search(text)
        if m:
            # 150 chars before, 500 after, as a maximum reach -- not a hard
            # cut. _snap_context_start pulls the opening in to the nearest
            # real sentence start within that reach (falling back to a word
            # break only if none exists). _snap_context_end pushes the close
            # out to include every complete sentence that fits, not just the
            # first one -- the trigger phrase is often not the operative
            # sentence. Together these land the quote around 500-600 chars
            # of complete sentences for a typical multi-clause match.
            start = _snap_context_start(text, m.start(), 150)
            end = _snap_context_end(text, m.end(), 500)
            seen[flag] = {
                "flag": flag,
                "trigger": label,
                "meaning": FLAG_MEANING[flag],
                "context": text[start:end].strip(),
            }
    order = [FLAG_CVR, FLAG_ELECTION, FLAG_ADJUSTMENT, FLAG_REPRICED,
             FLAG_GO_SHOP, FLAG_CONTROLLING]
    return [seen[f] for f in order if f in seen]


def flags_summary(flags):
    """One-line summary for logs and compact display."""
    if not flags:
        return ""
    return " · ".join(f["flag"] for f in flags)


def price_is_complete(flags):
    """
    True when the stated deal price is the whole story.

    CVR, election and adjustment all mean a holder receives something other than
    the headline number. Go-shop and controlling-holder are risk context, not
    price modifiers, so they do not affect this.
    """
    modifiers = {FLAG_CVR, FLAG_ELECTION, FLAG_ADJUSTMENT}
    return not any(f["flag"] in modifiers for f in flags)