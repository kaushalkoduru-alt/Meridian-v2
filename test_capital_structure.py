"""
Capital-structure extractor, run against the three hand-verified targets.

    python test_capital_structure.py            # uses ANTHROPIC_API_KEY from env
    python test_capital_structure.py sk-ant-... # or pass the key as arg 1

Ground truth the run must reproduce (hand-read from the filings named):

  CBZ  — CBIZ, Inc., 10-K/A accession 0000944148-26-000094, Note 10 "Debt and
         Financing Arrangements", as of 2025-12-31.
         2024 Credit Facilities, one agreement, two tranches:
           Term Loan   face $1,330,000  (current $70,000 + long-term $1,260,000),
                       net $1,319,647 shown in the table
           Revolver    drawn $142,400 on a $600,000 commitment
         Rate: base rate or Term SOFR + applicable margin; blended 6.56% in 2025,
               range 3.54%-6.84%.  Maturity Nov 1, 2029.
         Change of control: "in the event of a defined change in control, the
               2024 Credit Facilities may be terminated" — likely refinanced.
         Reconciles to: gross $1,472,400 outstanding under the 2024 Credit
               Facilities; net $1,455,924 (short-term $66,372 + long-term
               $1,389,552).

  BZH  — Beazer Homes USA, Inc., 10-K accession 0000915840-25-000075, Note 7
         "Borrowings", as of 2025-09-30. Five tranches:
           5.875% Senior Notes (2027 Notes)  face $357,255   Oct 2027   fixed
           7.250% Senior Notes (2029 Notes)  face $350,000   Oct 2029   fixed
           7.500% Senior Notes (2031 Notes)  face $250,000   Mar 2031   fixed
             (less $6,611 unamortized issuance costs -> Total Senior Notes, net $950,644)
           Junior Subordinated Notes  face $100,773 / net $78,470  Jul 2036
             floating, wtd-avg 7.02%; $25.8M at 3-mo SOFR + 2.71%, $75M restructured
             (SOFR-based, 4.25% floor / 9.25% cap). Subordinated to the Unsecured
             Facility and the Senior Notes.
           Senior Unsecured Revolving Credit Facility  $0 drawn on $365,000
             capacity ($41.4M letters of credit outstanding)   Mar 2028
         Senior Notes rank senior to subordinated indebtedness, effectively
         subordinated to future secured debt.
         Change of control: not in the 10-K debt footnote. The extractor follows
         each senior note's indenture reference (EX-4.1 of the 8-Ks filed
         2017-10-10 / 2019-09-24 / 2024-03-18) and should report a
         change-of-control put at 101% of principal on all three, holder's
         option, notes survive. Junior subs / revolver stay null.
         Reconciles to: "Total debt, net $1,029,114".

  NATH — Nathan's Famous, Inc., 10-K accession 0001437749-26-019923, Note J
         "Long-Term Debt", as of 2026-03-29. One tranche:
           SOFR Term Loan  face $48,400  effective rate 5.175%  matures FY2030
         Change of control: "the Buyer at the Effective Time shall pay all
           outstanding obligations under the Credit Facility" — gone at close.
         Reconciles to: "Total debt, net of debt issuance costs 48,143"
           (face $48,400 less $257 issuance costs); face total also stated $48,400.
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from capital_structure import (assess_capital_structure, anthropic_llm_fn,
                               OK, INCOMPLETE, NOT_DISCLOSED, UNAVAILABLE)

TARGETS = [
    ("CBZ", "CBIZ, Inc."),
    ("BZH", "Beazer Homes USA, Inc."),
    ("NATH", "Nathan's Famous, Inc."),
]


def _fmt_amt(x, unit):
    if x is None:
        return "—"
    try:
        return f"{float(x):,.0f} ({unit})"
    except (TypeError, ValueError):
        return str(x)


def report(res):
    t = res["ticker"]
    print("=" * 78)
    print(f"{t}   status: {res['status'].upper()}")
    if res.get("source"):
        s = res["source"]
        print(f"   source: {s.get('form')} {s.get('accession')} filed {s.get('filed')}")
        print(f"           {s.get('url')}")
        print(f"           footnote heading: {s.get('heading')!r}")
    if res["status"] in (NOT_DISCLOSED, UNAVAILABLE):
        print(f"   reason: {res.get('reason')}")
        return
    print(f"   as of: {res.get('as_of')}   unit: {res.get('currency_unit')}")
    st = res.get("stated_net_total") or {}
    ft = res.get("stated_face_total") or {}
    print(f"   stated net total: {st.get('label')!r} = {st.get('amount'):,}"
          + (f"  (derived: {st.get('note')})" if st.get("note") else ""))
    if ft.get("amount"):
        print(f"   stated face total: {ft.get('label')!r} = {ft.get('amount'):,}")
    unit = res.get("currency_unit")
    print(f"\n   TRANCHES ({len(res['tranches'])}):")
    for tr in res["tranches"]:
        print(f"     - [{tr.get('instrument_type')}] {tr.get('name')}")
        if tr.get("instrument_type") == "revolver":
            print(f"         drawn {_fmt_amt(tr.get('drawn'), unit)} "
                  f"/ capacity {_fmt_amt(tr.get('capacity'), unit)}")
        else:
            print(f"         face {_fmt_amt(tr.get('face_amount'), unit)}"
                  + (f"   net {_fmt_amt(tr.get('net_amount'), unit)}"
                     if tr.get('net_amount') is not None else ""))
        rate = tr.get("rate") or {}
        print(f"         rate: [{rate.get('kind')}] {rate.get('text')}")
        print(f"         maturity: {tr.get('maturity')}")
        if tr.get("seniority"):
            print(f"         seniority: {tr.get('seniority')}")
        print(f"         change of control: {tr.get('change_of_control') or '— (not stated)'}")
        if tr.get("change_of_control_quote"):
            print(f'           "{tr["change_of_control_quote"]}"')
        if tr.get("change_of_control_source"):
            print(f"           source: {tr['change_of_control_source']}")

    undrawn = res.get("undrawn_facilities") or []
    if undrawn:
        print(f"\n   UNDRAWN CAPACITY (not debt — {len(undrawn)}):")
        for u in undrawn:
            print(f"     · {u.get('name')} — capacity {_fmt_amt(u.get('capacity'), unit)}, "
                  f"$0 drawn  [{u.get('status')}]")

    ilog = res.get("indenture_log") or []
    if ilog:
        print("\n   INDENTURE CHANGE-OF-CONTROL PASS:")
        for e in ilog:
            print(f"     {e}")

    rc = res["reconciliation"]
    print(f"\n   RECONCILIATION: {'PASS' if rc['ok'] else 'FAIL'}")
    print(f"     {rc['method']}")
    if rc.get("computed") is not None:
        print(f"     net total {rc['net_total']:,}  computed {rc['computed']:,}  "
              f"delta {rc['delta']:,}  tolerance +/-{rc['tolerance']:,.1f}")
    if rc.get("missing_amounts"):
        print(f"     tranches with no amount: {rc['missing_amounts']}")
    if rc.get("face_check"):
        fc = rc["face_check"]
        print(f"     face cross-check: sum {fc['sum_of_tranche_face']:,} vs "
              f"stated {fc['stated']:,}  delta {fc['delta']:,}  "
              f"{'ok' if fc['ok'] else 'MISMATCH'}")
    if res.get("model_notes"):
        print(f"   model notes: {res['model_notes']}")


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("No ANTHROPIC_API_KEY. Pass it as arg 1 or set the env var.")
        sys.exit(2)
    llm = anthropic_llm_fn(key)

    results = []
    for ticker, company in TARGETS:
        print(f"\n>>> {ticker} ({company}) — fetching 10-K and reading debt footnote...")
        res = assess_capital_structure(ticker, company=company, llm_fn=llm)
        results.append(res)
        report(res)

    print("\n" + "=" * 78)
    print("SUMMARY")
    for res in results:
        rc = res.get("reconciliation") or {}
        print(f"  {res['ticker']:5} {res['status']:13} "
              f"tranches={len(res.get('tranches', []))} "
              f"reconciles={rc.get('ok')}")


if __name__ == "__main__":
    main()
