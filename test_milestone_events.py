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


# ── merger-vote extraction (real 5.07 wordings from the full-feed sweep) ─────
from milestone_events import _vote_events

def votes(t):
    return [(e["type"], e["adverse"]) for e in _vote_events("Item 5.07 Submission of Matters to a Vote of Security Holders. " + t + " Item 9.01 Financial Statements.", "2026-06-12")]

def test_merger_vote_wordings():
    assert votes("On June 11, 2026, the Company held a virtual special meeting of shareholders. Proposal 1 . Proposal to approve the Agreement and Plan of Merger, dated March 10, 2026 (the Merger Agreement Proposal). Set forth below are the voting results for the Merger Agreement Proposal, which was approved by the requisite vote of the Company's shareholders: For Against Abstain 47,458,203 10,251 17,219 Proposal 2 . Non-binding advisory proposal.") == [("vote_passed", False)]
    assert votes("On September 22, 2026, a special meeting was held. Proposal 1: Merger Proposal At the Special Meeting, the Company's stockholders voted upon and approved the Merger Proposal. Proposal 2: Advisory Compensation Proposal The stockholders approved it.") == [("vote_passed", False)]
    assert votes("On April 23, 2026, the Company held a special meeting. The proposal to adopt the Merger Agreement was approved by the requisite vote of the stockholders. The proposal to approve the advisory compensation was not approved.") == [("vote_passed", False)]

def test_annual_meeting_is_not_a_merger_vote():
    assert votes("On June 9, 2026, the Company held its 2026 Annual Meeting. Proposal 1: election of directors. The shareholders elected all nominees. Proposal 2: The shareholders approved, on an advisory basis, the compensation of the named executive officers. Proposal 3: The shareholders approved the amendment to the equity incentive plan.") == []

def test_compensation_approval_alone_is_not_a_merger_pass():
    assert votes("On May 1, 2026, the Company held a special meeting relating to the Merger Agreement. Proposal 1: Merger Agreement Proposal. Votes For Votes Against 10 90. Proposal 2: Advisory Proposal. The stockholders approved the advisory compensation proposal.")[:1] != [("vote_passed", False)]

def test_failed_merger_vote_is_adverse():
    assert votes("On May 1, 2026, the Company held a special meeting. Proposal 1: Merger Proposal. The Merger Proposal was not approved by the requisite vote of the stockholders.") == [("vote_failed", True)]

def test_vote_table_without_verdict_is_neutral():
    r = votes("On May 1, 2026, the Company held a special meeting. Merger Agreement Proposal: Votes For Votes Against Votes Abstaining 121,929,544 1,208,817 30,610")
    assert r == [("vote_held", False)]


def test_agency_closing_its_investigation_is_a_clearance_and_resolves_a_second_request():
    t = "In addition, on June 12, 2026, the Antitrust Division of the United States Department of Justice (the \"DOJ\") issued a statement in connection with closing its investigation into the Merger."
    assert ev2(t, "8-K") == [("agency_review_closed", "2026-06-12")]
    assert ev2("The Division is closing its investigation of an unrelated matter.", "8-K") == []
