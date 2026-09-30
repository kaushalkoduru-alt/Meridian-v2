"""Milestone extractor: hedged/forward-looking text must yield nothing; real
assertions must yield the right typed, dated event. Real-filing ground truth
(NATH, IMXI) is run by hand: see milestone_events.py docstring."""
from milestone_events import extract_events

def ev(t, fd="2026-01-10"):
    return [(e["type"], e["regulator"], e["date"]) for e in extract_events(t, fd)]

def test_positive():
    assert ev("CFIUS Clearance was obtained on September 17, 2026.") == [("cfius_clearance", "CFIUS", "2026-09-17")]
    assert ev("At 11:59 p.m. Eastern Time on October 6, 2025, the waiting period under the HSR Act with respect to the Merger expired.") == [("hsr_expired", "HSR (FTC/DOJ)", "2025-10-06")]
    assert ev("The parties made the filings required under the HSR Act on January 23, 2026, and the waiting period expired on February 23, 2026.") == [("hsr_expired", "HSR (FTC/DOJ)", "2026-02-23")]

def test_dfpi_uses_letter_date_not_context_date():
    r = ev("Also on August 13, 2026, the California Department of Financial Protection and Innovation (the \"DFPI\") sent a letter suspending the approval extension previously granted on July 31, 2026 for the pending acquisition of IMXI.")
    assert r == [("approval_suspended", "California DFPI", "2026-08-13")]

def test_hedged_or_conditional_yields_nothing():
    for t in ["The Merger cannot be completed until the waiting period under the HSR Act has expired or been terminated.",
              "We may receive a second request from the FTC, which could delay the Merger.",
              "If CFIUS Clearance was obtained after the outside date, either party may terminate.",
              "The parties expect the waiting period under the HSR Act to expire in the third quarter.",
              "“CFIUS Clearance” means the parties have received written notice from CFIUS that the Merger is not a covered transaction."]:
        assert ev(t) == [], t

def test_second_request_only_when_issued():
    assert ev("On March 3, 2026, the Company received a Second Request from the FTC in connection with the Merger.")[0][0] == "second_request"


# ── full-feed sweep regressions: every case below was a live false positive ──
def ev2(t, kind, fd="2026-08-10"):
    from milestone_events import extract_events
    return [(e["type"], e["date"]) for e in extract_events(t, fd, (), kind)]

def test_proxy_condition_sentences_are_not_events():
    for t in ["In order to complete the merger, we must obtain the required stockholder approval, the applicable waiting period under the HSR Act must have expired or been terminated.",
              "(i) The waiting periods applicable to the Transactions pursuant to the HSR Act will have expired or otherwise been terminated."]:
        assert ev2(t, "DEFM14A") == [], t

def test_proxy_negotiation_and_voting_agreement_text_is_not_an_outside_date_extension():
    for t in ["The Board discussed the length and extension mechanisms for the outside date and directed counsel to continue negotiating for a longer outside date.",
              "The Support Agreements will terminate upon the date on which the Merger Agreement is amended in a manner that extends the Termination Date without consent."]:
        assert ev2(t, "DEFM14A") == [] and ev2(t, "8-K") == [], t

def test_second_request_needs_a_stated_date():
    assert ev2("Prior to the expiration of the waiting period, PSKY received a Second Request from the Antitrust Division.", "DEFM14A") == []
    assert ev2("Neither the Civil Investigative Demand nor the Second Request issued to WBD impacted the HSR Act waiting period.", "DEFM14A") == []
    assert ev2("On June 11, 2026, each of Cintas and the Company received a Second Request from the FTC in connection with the Merger.", "8-K") == [("second_request", "2026-06-11")]

def test_early_termination_date_is_the_grant_date():
    assert ev2("Parent and the Company applied for early termination of the waiting period under the HSR Act, and the FTC granted such request on September 21, 2026.", "PREM14A") == [("hsr_expired", "2026-09-21")]

def test_unfinished_draft_text_is_skipped():
    assert ev2("The Company and Parent filed the required notifications on [August 10, 2026] and the waiting period under the HSR Act expired.", "PREM14A") == []

def test_real_outside_date_extension_is_detected():
    assert ev2("On August 1, 2026, the parties entered into an amendment to the Merger Agreement that extended the Outside Date to December 31, 2026.", "8-K") == [("outside_date_extended", "2026-08-01")]
