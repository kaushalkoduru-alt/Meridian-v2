"""
verify_deals.py — EDGAR-based deal verification for Meridian COMPS_DATA
Checks each deal against SEC EDGAR filings to confirm:
1. Continued-filings screen: company claimed CLOSED but still filing 10-K/10-Q → CONTRADICTED
2. Completion 8-K (Item 2.01) or Form 25/15 near claimed close date → VERIFIED CLOSED
3. Termination 8-K (Item 1.02) near claimed date → VERIFIED BROKEN
Anything that fails all checks → UNVERIFIABLE (dropped from published stats)

Usage: python verify_deals.py
Output: verified_deals.json with verification_source per row
"""

import json
import time
import requests
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Meridian Verification Script kaushal@meridian.dev",
    "Accept-Encoding": "gzip, deflate",
}

# Rate limit: max 10 req/sec per EDGAR fair-access policy
def edgar_get(url, pause=0.15):
    time.sleep(pause)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

# All 154 COMPS_DATA entries with their claimed outcome and approximate close date
# close_year is the year the deal was claimed to close/break — used for continued-filings screen
DEALS = [
    {"ticker":"ATVI","acquirer":"Microsoft","outcome":"Closed","close_year":2023,"spread":25.0},
    {"ticker":"VMW","acquirer":"Broadcom","outcome":"Closed","close_year":2023,"spread":18.0},
    {"ticker":"SIAL","acquirer":"Pfizer","outcome":"Closed","close_year":2020,"spread":8.0},
    {"ticker":"HES","acquirer":"Chevron","outcome":"Closed","close_year":2024,"spread":12.0},
    {"ticker":"SNPS","acquirer":"Cadence","outcome":"Closed","close_year":2024,"spread":6.0},
    {"ticker":"CACC","acquirer":"Stellantis","outcome":"Closed","close_year":2024,"spread":4.0},
    {"ticker":"ACI","acquirer":"Kroger","outcome":"Closed","close_year":2025,"spread":15.0},
    {"ticker":"NTCT","acquirer":"Broadcom","outcome":"Closed","close_year":2024,"spread":5.0},
    {"ticker":"GTES","acquirer":"Blackstone","outcome":"Closed","close_year":2024,"spread":3.0},
    {"ticker":"MTW","acquirer":"Titan Machinery","outcome":"Closed","close_year":2021,"spread":4.0},
    {"ticker":"AIN","acquirer":"Schweitzer-Mauduit","outcome":"Closed","close_year":2021,"spread":3.0},
    {"ticker":"CRAWA","acquirer":"Amphenol","outcome":"Closed","close_year":2021,"spread":2.0},
    {"ticker":"VSH","acquirer":"Maverick Capital","outcome":"Closed","close_year":2021,"spread":3.0},
    {"ticker":"NINE","acquirer":"Undisclosed","outcome":"Closed","close_year":2021,"spread":2.0},
    {"ticker":"RNST","acquirer":"First Horizon","outcome":"Closed","close_year":2022,"spread":5.0},
    {"ticker":"DAY","acquirer":"Carrier Global","outcome":"Closed","close_year":2023,"spread":4.0},
    {"ticker":"SNEX","acquirer":"StoneX Group","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"IPG","acquirer":"Omnicom","outcome":"Closed","close_year":2025,"spread":8.0},
    {"ticker":"CGC","acquirer":"Acreage Holdings","outcome":"Closed","close_year":2022,"spread":6.0},
    {"ticker":"KN","acquirer":"Solesis","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"RDW","acquirer":"ATA","outcome":"Closed","close_year":2022,"spread":5.0},
    {"ticker":"IRBT","acquirer":"Amazon","outcome":"Broken","close_year":2024,"spread":22.0},
    {"ticker":"TSEM","acquirer":"Intel","outcome":"Broken","close_year":2023,"spread":28.0},
    {"ticker":"CCXI","acquirer":"AstraZeneca","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"SGMS","acquirer":"Apollo","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"FORG","acquirer":"Thales","outcome":"Closed","close_year":2023,"spread":2.0},
    {"ticker":"PING","acquirer":"Thoma Bravo","outcome":"Closed","close_year":2023,"spread":3.0},
    {"ticker":"PCTY","acquirer":"Vista Equity","outcome":"Closed","close_year":2024,"spread":4.0},
    {"ticker":"GDRX","acquirer":"Francisco Partners","outcome":"Closed","close_year":2023,"spread":2.0},
    {"ticker":"MIME","acquirer":"Permira","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"SGEN","acquirer":"Pfizer","outcome":"Closed","close_year":2023,"spread":5.0},
    {"ticker":"PCOR","acquirer":"Trimble","outcome":"Closed","close_year":2023,"spread":3.0},
    {"ticker":"BLKB","acquirer":"Vista Equity","outcome":"Closed","close_year":2024,"spread":3.0},
    {"ticker":"INFIQ","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":15.0},
    {"ticker":"MMLP","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":8.0},
    {"ticker":"CRVO","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":20.0},
    {"ticker":"SAVE","acquirer":"JetBlue","outcome":"Broken","close_year":2024,"spread":35.0},
    {"ticker":"ATEX","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":18.0},
    {"ticker":"SGFY","acquirer":"CVS Health","outcome":"Broken","close_year":2023,"spread":12.0},
    {"ticker":"CHNG","acquirer":"UnitedHealth","outcome":"Broken","close_year":2023,"spread":22.0},
    {"ticker":"ATHA","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":25.0},
    {"ticker":"IIIN","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":10.0},
    {"ticker":"TIGR","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":18.0},
    {"ticker":"EBIX","acquirer":"Fidelity","outcome":"Broken","close_year":2022,"spread":25.0},
    {"ticker":"PNFP","acquirer":"Tennessee Bank","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"VRNT","acquirer":"Cognyte","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"SAIL","acquirer":"Broadcom","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"ATRC","acquirer":"Johnson & Johnson","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"XLNX","acquirer":"AMD","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"AJRD","acquirer":"L3Harris","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"CDAY","acquirer":"Ceridian","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"PLNT","acquirer":"TSG Consumer","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"AMED","acquirer":"UnitedHealth","outcome":"Closed","close_year":2024,"spread":5.0},
    {"ticker":"MGLN","acquirer":"Centene","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"MRTX","acquirer":"Pfizer","outcome":"Closed","close_year":2024,"spread":4.0},
    {"ticker":"SPWR","acquirer":"TotalEnergies","outcome":"Closed","close_year":2023,"spread":3.0},
    {"ticker":"PETQ","acquirer":"KKR","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"LMNX","acquirer":"DiaSorin","outcome":"Closed","close_year":2021,"spread":3.0},
    {"ticker":"RTLR","acquirer":"Equinor","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"MYOK","acquirer":"Bristol Myers","outcome":"Closed","close_year":2020,"spread":2.0},
    {"ticker":"ARNA","acquirer":"Pfizer","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"AFMD","acquirer":"Genmab","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"KRTX","acquirer":"Roche","outcome":"Closed","close_year":2024,"spread":3.0},
    {"ticker":"RGNX","acquirer":"Ultragenyx","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"HALO","acquirer":"Janssen","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"IMVT","acquirer":"Roche","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"AKBA","acquirer":"Akebia","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"MCRB","acquirer":"Nestle","outcome":"Closed","close_year":2022,"spread":7.0},
    {"ticker":"CTIC","acquirer":"Swedish Orphan","outcome":"Closed","close_year":2022,"spread":6.0},
    {"ticker":"PNTM","acquirer":"Merck","outcome":"Closed","close_year":2022,"spread":8.0},
    {"ticker":"ALDX","acquirer":"AbbVie","outcome":"Broken","close_year":2022,"spread":9.0},
    {"ticker":"ENTA","acquirer":"Roche","outcome":"Closed","close_year":2022,"spread":6.0},
    {"ticker":"YMAB","acquirer":"Jazz Pharma","outcome":"Closed","close_year":2022,"spread":7.0},
    {"ticker":"MDVN","acquirer":"Pfizer","outcome":"Closed","close_year":2020,"spread":5.0},
    {"ticker":"ACHN","acquirer":"Alexion","outcome":"Closed","close_year":2020,"spread":3.0},
    {"ticker":"PGNX","acquirer":"Servier","outcome":"Closed","close_year":2021,"spread":8.0},
    {"ticker":"PTLA","acquirer":"Pfizer","outcome":"Closed","close_year":2020,"spread":7.0},
    {"ticker":"AMAG","acquirer":"Covis Pharma","outcome":"Broken","close_year":2020,"spread":14.0},
    {"ticker":"SGBX","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":16.0},
    {"ticker":"TTGT","acquirer":"Informa","outcome":"Broken","close_year":2023,"spread":13.0},
    {"ticker":"PRSP","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":17.0},
    {"ticker":"DMTK","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":20.0},
    {"ticker":"PAHC","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":22.0},
    {"ticker":"COHN","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":20.0},
    {"ticker":"FWAA","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":15.0},
    {"ticker":"AZPN","acquirer":"Emerson Electric","outcome":"Closed","close_year":2023,"spread":3.0},
    {"ticker":"COUP","acquirer":"Vista Equity","outcome":"Closed","close_year":2023,"spread":2.0},
    {"ticker":"EVBG","acquirer":"Thoma Bravo","outcome":"Closed","close_year":2023,"spread":2.0},
    {"ticker":"DOMO","acquirer":"Thoma Bravo","outcome":"Closed","close_year":2023,"spread":3.0},
    {"ticker":"APPN","acquirer":"Vista Equity","outcome":"Closed","close_year":2023,"spread":2.0},
    {"ticker":"INST","acquirer":"KKR","outcome":"Closed","close_year":2020,"spread":2.0},
    {"ticker":"NLOK","acquirer":"Broadcom","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"AVEPO","acquirer":"Apollo","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"PRGS","acquirer":"KKR","outcome":"Closed","close_year":2023,"spread":2.0},
    {"ticker":"AMSF","acquirer":"Blackstone","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"TWTR","acquirer":"Elon Musk","outcome":"Closed","close_year":2022,"spread":10.0},
    {"ticker":"DISCA","acquirer":"AT&T","outcome":"Closed","close_year":2022,"spread":8.0},
    {"ticker":"MGM","acquirer":"Amazon","outcome":"Closed","close_year":2022,"spread":6.0},
    {"ticker":"ZNGA","acquirer":"Take-Two Interactive","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"MBWM","acquirer":"Old National","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"CLDR","acquirer":"KKR + CDP","outcome":"Closed","close_year":2021,"spread":2.0},
    {"ticker":"LHCG","acquirer":"UnitedHealth","outcome":"Closed","close_year":2023,"spread":5.0},
    {"ticker":"ATRS","acquirer":"Amneal","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"HRMY","acquirer":"Jazz Pharma","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"PRTO","acquirer":"Novo Nordisk","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"BMRN","acquirer":"Roche","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"ARWR","acquirer":"Roche","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"FATE","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":14.0},
    {"ticker":"ARCT","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":18.0},
    {"ticker":"LVGO","acquirer":"Teladoc","outcome":"Closed","close_year":2020,"spread":5.0},
    {"ticker":"PFPT","acquirer":"Thoma Bravo","outcome":"Closed","close_year":2021,"spread":2.0},
    {"ticker":"CDXS","acquirer":"Novo Nordisk","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"FMBI","acquirer":"Old National","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"QDEL","acquirer":"Ortho Clinical","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"CLGX","acquirer":"ICE","outcome":"Closed","close_year":2021,"spread":4.0},
    {"ticker":"ONCE","acquirer":"Roche","outcome":"Closed","close_year":2020,"spread":3.0},
    {"ticker":"MDCO","acquirer":"Medicines Company","outcome":"Closed","close_year":2020,"spread":2.0},
    {"ticker":"ESRX","acquirer":"Cigna","outcome":"Closed","close_year":2020,"spread":6.0},
    {"ticker":"CELG","acquirer":"Bristol Myers","outcome":"Closed","close_year":2020,"spread":8.0},
    {"ticker":"AKAO","acquirer":"Cipla","outcome":"Closed","close_year":2020,"spread":2.0},
    {"ticker":"NKTR","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":16.0},
    {"ticker":"SGMO","acquirer":"Pfizer","outcome":"Broken","close_year":2022,"spread":19.0},
    {"ticker":"ACAD","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":14.0},
    {"ticker":"NTRA","acquirer":"Roper Technologies","outcome":"Closed","close_year":2024,"spread":3.0},
    {"ticker":"SFLY","acquirer":"Shutterfly","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"MDLA","acquirer":"Veeva","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"SEMG","acquirer":"Sunoco","outcome":"Closed","close_year":2020,"spread":4.0},
    {"ticker":"EPAY","acquirer":"Bottomline Tech","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"NUAN","acquirer":"Microsoft","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"VRTU","acquirer":"KKR","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"TLND","acquirer":"Qlik","outcome":"Closed","close_year":2023,"spread":3.0},
    {"ticker":"TWLO","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":17.0},
    {"ticker":"INVA","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":13.0},
    {"ticker":"ARRY","acquirer":"Pfizer","outcome":"Closed","close_year":2020,"spread":3.0},
    {"ticker":"EIGI","acquirer":"Clearlake Capital","outcome":"Closed","close_year":2021,"spread":2.0},
    {"ticker":"RLAY","acquirer":"Roche","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"MYND","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":21.0},
    {"ticker":"KTCC","acquirer":"Undisclosed","outcome":"Closed","close_year":2021,"spread":3.0},
    {"ticker":"BNFT","acquirer":"Voya Financial","outcome":"Closed","close_year":2023,"spread":2.0},
    {"ticker":"EGRX","acquirer":"Undisclosed","outcome":"Closed","close_year":2022,"spread":5.0},
    {"ticker":"CVET","acquirer":"JAB Holdings","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"HMSY","acquirer":"UnitedHealth","outcome":"Closed","close_year":2021,"spread":2.0},
    {"ticker":"MDXG","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":15.0},
    {"ticker":"CSOD","acquirer":"Clearlake Capital","outcome":"Closed","close_year":2021,"spread":2.0},
    {"ticker":"ALXN","acquirer":"AstraZeneca","outcome":"Closed","close_year":2021,"spread":5.0},
    {"ticker":"ACBI","acquirer":"South State","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"TCBI","acquirer":"Undisclosed","outcome":"Broken","close_year":2022,"spread":9.0},
    {"ticker":"MFIN","acquirer":"Undisclosed","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"BPFH","acquirer":"Webster Financial","outcome":"Closed","close_year":2022,"spread":4.0},
    {"ticker":"CATY","acquirer":"Heartland Financial","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"HBMD","acquirer":"Shore Bankshares","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"UVSP","acquirer":"Fulton Financial","outcome":"Closed","close_year":2022,"spread":3.0},
    {"ticker":"STFC","acquirer":"Liberty Mutual","outcome":"Closed","close_year":2022,"spread":2.0},
    {"ticker":"NGHC","acquirer":"Allstate","outcome":"Closed","close_year":2021,"spread":3.0},
]

def get_cik(ticker):
    """Get CIK from EDGAR ticker-to-CIK mapping."""
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        data = edgar_get(url, pause=0.2)
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
    except Exception as e:
        print(f"  CIK lookup error for {ticker}: {e}")
    return None

def get_submissions(cik):
    """Get company submissions from EDGAR."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        return edgar_get(url, pause=0.15)
    except Exception as e:
        print(f"  Submissions error for CIK {cik}: {e}")
    return None

def check_continued_filings(submissions, close_year, ticker):
    """
    Screen 1: Check if company has 10-K/10-Q filings AFTER claimed close year.
    If yes → still public → claimed CLOSED outcome is likely fabricated.
    Returns: (is_still_filing, latest_annual_filing_date)
    """
    if not submissions:
        return False, None
    
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    
    annual_forms = {"10-K", "10-K/A", "20-F", "20-F/A"}
    quarterly_forms = {"10-Q", "10-Q/A"}
    
    latest_annual = None
    latest_filing = None
    
    for form, date, acc in zip(forms, dates, accessions):
        if form in annual_forms or form in quarterly_forms:
            if latest_filing is None or date > latest_filing:
                latest_filing = date
            if form in annual_forms:
                if latest_annual is None or date > latest_annual:
                    latest_annual = date
    
    if latest_filing:
        filing_year = int(latest_filing[:4])
        # If filing more than 1 year after claimed close → still active
        if filing_year > close_year + 1:
            return True, latest_filing
    
    return False, latest_filing

def find_completion_8k(submissions, close_year, ticker):
    """
    Screen 2: Look for Item 2.01 (completion of acquisition) 8-K near claimed close.
    Returns: (found, accession_number, filing_date) or (False, None, None)
    """
    if not submissions:
        return False, None, None
    
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    items = recent.get("items", [])
    
    for form, date, acc, item in zip(forms, dates, accessions, items):
        if form == "8-K":
            filing_year = int(date[:4])
            # Look within 2 years of claimed close
            if abs(filing_year - close_year) <= 2:
                item_str = str(item) if item else ""
                if "2.01" in item_str:
                    return True, acc, date
    
    return False, None, None

def find_form25_or_15(submissions, close_year):
    """
    Screen 2b: Look for Form 25 (delisting) or Form 15 (deregistration) near claimed close.
    Returns: (found, accession_number, filing_date) or (False, None, None)
    """
    if not submissions:
        return False, None, None
    
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    
    target_forms = {"25", "25-NSE", "15", "15-12B", "15-12G"}
    
    for form, date, acc in zip(forms, dates, accessions):
        if form in target_forms:
            filing_year = int(date[:4])
            if abs(filing_year - close_year) <= 2:
                return True, acc, date
    
    return False, None, None

def find_termination_8k(submissions, close_year, ticker):
    """
    Screen 3: Look for Item 1.02 (termination of agreement) 8-K for BROKEN deals.
    Returns: (found, accession_number, filing_date) or (False, None, None)
    """
    if not submissions:
        return False, None, None
    
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    items = recent.get("items", [])
    
    for form, date, acc, item in zip(forms, dates, accessions, items):
        if form == "8-K":
            filing_year = int(date[:4])
            if abs(filing_year - close_year) <= 2:
                item_str = str(item) if item else ""
                if "1.02" in item_str:
                    return True, acc, date
    
    return False, None, None

def verify_deal(deal):
    """
    Run the full verification pipeline for one deal.
    Returns dict with status and verification_source.
    """
    ticker = deal["ticker"]
    outcome = deal["outcome"]
    close_year = deal["close_year"]
    
    print(f"\nVerifying {ticker} ({outcome}, ~{close_year})...")
    
    # Get CIK
    cik = get_cik(ticker)
    if not cik:
        print(f"  {ticker}: No CIK found → UNVERIFIABLE")
        return {**deal, "status": "UNVERIFIABLE", "verification_source": "No EDGAR CIK found", "edgar_cik": None}
    
    print(f"  CIK: {cik}")
    
    # Get submissions
    submissions = get_submissions(cik)
    if not submissions:
        print(f"  {ticker}: No submissions data → UNVERIFIABLE")
        return {**deal, "status": "UNVERIFIABLE", "verification_source": "No EDGAR submissions data", "edgar_cik": cik}
    
    entity_name = submissions.get("name", "Unknown")
    print(f"  Entity: {entity_name}")
    
    if outcome == "Closed":
        # Screen 1: Check for continued filings
        still_filing, latest = check_continued_filings(submissions, close_year, ticker)
        if still_filing:
            print(f"  {ticker}: Still filing annual/quarterly reports after {close_year} (latest: {latest}) → CONTRADICTED")
            return {
                **deal,
                "status": "CONTRADICTED",
                "verification_source": f"EDGAR: Company still filing 10-K/10-Q as of {latest} — claimed closed {close_year}",
                "edgar_cik": cik,
                "edgar_entity": entity_name,
            }
        
        # Screen 2a: Look for completion 8-K (Item 2.01)
        found_8k, acc_8k, date_8k = find_completion_8k(submissions, close_year, ticker)
        if found_8k:
            print(f"  {ticker}: Found completion 8-K (2.01) filed {date_8k}, accession {acc_8k} → VERIFIED CLOSED")
            return {
                **deal,
                "status": "VERIFIED",
                "verification_source": f"EDGAR 8-K Item 2.01 filed {date_8k}, accession {acc_8k}",
                "edgar_cik": cik,
                "edgar_entity": entity_name,
            }
        
        # Screen 2b: Look for Form 25 or Form 15
        found_25, acc_25, date_25 = find_form25_or_15(submissions, close_year)
        if found_25:
            print(f"  {ticker}: Found Form 25/15 filed {date_25}, accession {acc_25} → VERIFIED CLOSED")
            return {
                **deal,
                "status": "VERIFIED",
                "verification_source": f"EDGAR Form 25/15 filed {date_25}, accession {acc_25}",
                "edgar_cik": cik,
                "edgar_entity": entity_name,
            }
        
        print(f"  {ticker}: No completion 8-K or Form 25/15 found → UNVERIFIABLE")
        return {
            **deal,
            "status": "UNVERIFIABLE",
            "verification_source": "No EDGAR completion filing found",
            "edgar_cik": cik,
            "edgar_entity": entity_name,
        }
    
    elif outcome == "Broken":
        # Screen 3: Look for termination 8-K (Item 1.02)
        found_term, acc_term, date_term = find_termination_8k(submissions, close_year, ticker)
        if found_term:
            print(f"  {ticker}: Found termination 8-K (1.02) filed {date_term}, accession {acc_term} → VERIFIED BROKEN")
            return {
                **deal,
                "status": "VERIFIED",
                "verification_source": f"EDGAR 8-K Item 1.02 filed {date_term}, accession {acc_term}",
                "edgar_cik": cik,
                "edgar_entity": entity_name,
            }
        
        # Fallback: check if still filing (if still public, BROKEN is more plausible)
        still_filing, latest = check_continued_filings(submissions, close_year, ticker)
        if still_filing:
            print(f"  {ticker}: Still public after {close_year}, consistent with BROKEN but no termination 8-K found → UNVERIFIABLE")
        
        print(f"  {ticker}: No termination 8-K found → UNVERIFIABLE")
        return {
            **deal,
            "status": "UNVERIFIABLE",
            "verification_source": "No EDGAR termination filing found",
            "edgar_cik": cik,
            "edgar_entity": entity_name,
        }
    
    return {**deal, "status": "UNVERIFIABLE", "verification_source": "Unknown outcome type", "edgar_cik": cik}


if __name__ == "__main__":
    results = []
    
    for i, deal in enumerate(DEALS):
        print(f"\n[{i+1}/{len(DEALS)}]", end="")
        result = verify_deal(deal)
        results.append(result)
        
        # Save progress incrementally
        with open("scripts/verified_deals_progress.json", "w") as f:
            json.dump(results, f, indent=2)
    
    # Final output
    verified = [r for r in results if r["status"] == "VERIFIED"]
    contradicted = [r for r in results if r["status"] == "CONTRADICTED"]
    unverifiable = [r for r in results if r["status"] == "UNVERIFIABLE"]
    
    print(f"\n\n=== FINAL RESULTS ===")
    print(f"VERIFIED: {len(verified)}")
    print(f"CONTRADICTED: {len(contradicted)}")
    print(f"UNVERIFIABLE: {len(unverifiable)}")
    
    with open("scripts/verified_deals.json", "w") as f:
        json.dump({
            "generated": datetime.utcnow().isoformat(),
            "total_input": len(DEALS),
            "verified_count": len(verified),
            "contradicted_count": len(contradicted),
            "unverifiable_count": len(unverifiable),
            "deals": results
        }, f, indent=2)
    
    print("\nOutput written to verified_deals.json")
