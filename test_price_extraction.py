"""Price extraction on real filing sentences: a stated cash price is found wherever
it sits, and a stock leg, a reference price or a contingent cap is never read as
the price. No network. Run:  python test_price_extraction.py

Every sentence below is quoted from the filing named beside it.
"""
import os
import sys

sys.path.insert(0, os.getcwd())
import main

fails = []


def check(name, cond):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


def html(text):
    return f"<html><body><p>{text}</p></body></html>"


FILLER = ("The transaction is expected to be accretive to adjusted earnings per share in the first "
          "full year after close and to fund $400 million per quarter of repurchases. ") * 40

# MKTX 8-K 0001193125-26-324933 EX-99.1: the price sentence sits far past the
# "consideration" header the window opens at, so the window sees an accretion
# paragraph and no price.
MKTX = ("Financing consideration comes from newly issued debt. " + FILLER +
        "Under the terms of the agreement, ICE will acquire all outstanding shares of MarketAxess "
        "for $167 per share in cash, representing a 33% premium to MarketAxess's closing price as "
        "of July 29, 2026.")
window = main.extract_price_from_text(main.extract_targeted_section(html(MKTX)))
check("MKTX: the targeted window alone misses a price sentence deep in the release", window is None)
check("MKTX: the document pass finds $167", main.extract_price_from_document(html(MKTX)) == 167.0)

# ROKU 8-K 0001140361-26-025115 EX-99.1: headline $160.00, stock leg restated as
# $64.00, valued off Fox's own $66.03 reference price.
ROKU = ("FOX will acquire Roku for $160.00 per share in a combination of cash and FOX Class A common "
        "stock. FOX is acquiring Roku in a cash-and-stock transaction valued at $160.00 per ROKU share. "
        "FOX will pay $96.00 in cash and 0.9693 shares of FOX Class A common stock for each Roku Class A "
        "and Class B share outstanding immediately prior to the effective time of the merger. The stock "
        "consideration represents $64.00 per ROKU share based on a reference price of $66.03 per share, "
        "the 10-day volume-weighted average price of FOX Class A common stock as of June 10, 2026.")
check("ROKU: headline $160.00, not the $66.03 reference price or the $64.00 stock leg",
      main.extract_price_from_text(ROKU) == 160.0)
_w = main.extract_price_from_text(main.extract_targeted_section(html(ROKU)))
check("ROKU: through the real window (which opens mid-sentence), never $64.00 or $66.03",
      _w in (None, 160.0))
check("ROKU: window then document pass ends at $160.00",
      (_w or main.extract_price_from_document(html(ROKU))) == 160.0)

# KVUE 8-K 0001104659-25-105216 EX-99.1: cash leg beside a stock leg, with the
# total stated afterwards.
KVUE = ("Kenvue shareholders will receive $3.50 per share in cash as well as 0.14625 Kimberly-Clark shares "
        "for each Kenvue share held at closing, for a total consideration to Kenvue shareholders of "
        "$21.01 per share, based on the closing price of Kimberly-Clark shares as of October 31, 2025.")
check("KVUE: the total $21.01, never the $3.50 cash leg", main.extract_price_from_text(KVUE) == 21.01)

# SMTI 8-K 0001493152-26-035196 EX-99.1
SMTI = ("MIMEDX will acquire all of the outstanding shares of Sanara in a cash and stock transaction "
        "valued at $35 per Sanara share. Sanara shareholders will receive $33.00 in cash and 0.4735 shares "
        "of MIMEDX common stock for each share of Sanara common stock they own, which represents a value "
        "of $2.00 per share, calculated based on the average closing price of MIMEDX common stock of $4.22.")
check("SMTI: headline $35 per Sanara share, not the $2.00 stock leg", main.extract_price_from_text(SMTI) == 35.0)

# GPRO 8-K 0001628280-26-060181 EX-2.1: a fixed mix with no stated total. The cash
# leg alone is not a price, and reading it would put $1.14 on a stock trading at $1.26.
GPRO = ("Each Eligible Share shall automatically convert into the right to receive (A) 0.1 shares of "
        "Surviving Corporation Common Stock (the “Per Share Stock Consideration”) and (B) $1.14 per "
        "share in cash, without interest.")
check("GPRO: a cash leg beside a stock leg with no stated total is blank, not $1.14",
      main.extract_price_from_text(GPRO) is None and main.extract_price_from_document(html(GPRO)) is None)

# LNTH 8-K 0001193125-26-331138: cash plus a CVR whose ceiling is not the price.
LNTH = ("Each share will be converted into the right to receive (x) $102.50 per share in cash, without "
        "interest and (y) one contractual contingent value right, which represents the right to receive "
        "up to $12.00 per share in cash upon achievement of a milestone.")
check("LNTH: the $102.50 cash price, never the CVR's $12.00 ceiling", main.extract_price_from_text(LNTH) == 102.5)

# UNF 8-K 0001193125-26-101128 EX-99.1: combined value stated after both legs.
UNF = ("Cintas will acquire UniFirst for $310.00 per share in cash and stock. UniFirst shareholders will "
       "receive $155.00 in cash and 0.7720 shares of Cintas stock for each UniFirst share they own. This "
       "represents a combined value of $310.00 per share based on Cintas' closing share price of $200.77 "
       "on March 9, 2026.")
check("UNF: $310.00, not the closing price $200.77", main.extract_price_from_text(UNF) == 310.0)

# Things that must keep working exactly as before.
check("plain all-cash still reads", main.extract_price_from_text(
    "Buyer will acquire the company for $25.00 per share in cash.") == 25.0)
check("par value is still not a price", main.extract_price_from_text(
    "common stock, par value $0.01 per share") is None)
check("a tie between two different prices is blank, not a guess", main.extract_price_from_document(html(
    "Buyer will acquire Target for $30.00 per share in cash. Buyer will also acquire Other for $12.00 "
    "per share in cash.")) is None)

print('\n%d failure(s)' % len(fails))
sys.exit(1 if fails else 0)
