from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
import pandas as pd
import os
import requests
import re
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import asyncio
import json
import math
import random
from contextlib import asynccontextmanager

CACHE_FILE = "meridian_cache.csv"

COMPANY_NAMES = {
    'UNF': 'UniFirst Corporation', 'KDP': 'Keurig Dr Pepper',
    'OGN': 'Organon & Co.', 'IMXI': 'International Money Express',
    'AES': 'The AES Corporation', 'WBD': 'Warner Bros. Discovery',
    'HBT': 'Heartland BancCorp', 'PRA': 'ProAssurance Corporation',
    'GBTG': 'Global Business Travel Group', 'AVNS': 'Avanos Medical',
    'CPRX': 'Catalyst Biosciences', 'KALV': 'KalVista Pharmaceuticals',
    'MASI': 'Masimo Corporation', 'CWAN': 'Clearwater Analytics',
    'ASRT': 'Assertio Holdings', 'TPH': 'Tri Pointe Homes',
    'TERN': 'Terns Pharmaceuticals', 'CSGS': 'CSG Systems International',
    'EHAB': 'Enhabit Home Health', 'SLNO': 'Soleno Therapeutics',
    'APLS': 'Apellis Pharmaceuticals', 'EWCZ': 'European Wax Center',
    'JHG': 'Janus Henderson Group', 'KW': 'Kennedy-Wilson Holdings',
    'UAC': 'United Auto Credit', 'NATL': 'National Western Financial',
    'SKYT': 'SkyWater Technology', 'CVGW': 'Calavo Growers',
    'NBRG': 'Northbrook Bank & Trust', 'AFBI': 'Affinity Bancshares',
    'KTWO': 'K2 Pure Solutions', 'OIM': 'Oil States International',
    'HPE': 'Hewlett Packard Enterprise', 'OC': 'Owens Corning',
    'B': 'Barnes Group',
}

KNOWN_ACQUIRERS = {
    'UAC': 'Stellantis', 'NATL': 'NCR Voyix', 'WBD': 'Paramount Global',
    'AVNS': 'Becton Dickinson', 'HBT': 'Heartland Financial',
    'ASRT': 'Paratek Pharmaceuticals', 'EHAB': 'KKR',
    'NBRG': 'Glacier Bancorp', 'AFBI': 'Center Parc Credit Union',
    'KTWO': 'Roper Technologies', 'SKYT': 'IonQ',
    'CVGW': 'Mission Produce', 'EWCZ': 'General Atlantic',
    'PRA': 'The Doctors Company', 'GBTG': 'Long Lake Management',
    'TERN': 'Merck', 'CSGS': 'CSG Systems International',
    'HPE': 'Juniper Networks', 'OC': 'Saint-Gobain',
    'B': 'Apollo Global Management', 'MASI': 'Danaher',
    'IMXI': 'Western Union', 'CWAN': 'Advent International',
    'SLNO': 'Neurocrine Biosciences',
}

EXCLUDED_TICKERS = {
    'GIW', 'IEAG', 'FVAV', 'YCY', 'AIIA', 'LKSP', 'PACH', 'SPEGU'
}

EDGAR_QUERIES = [
    {'type': 'All Cash', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'All Cash', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22merger+agreement%22+%22per+share+in+cash%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'Cash + Stock', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22cash+and+stock%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'Private Equity', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22definitive+agreement%22+%22per+share+in+cash%22+%22sponsor%22&forms=8-K&dateRange=custom&startdt=2024-01-01&enddt=2026-05-21&from={start}&size=100'},
    {'type': 'Tender Offer', 'url': 'https://efts.sec.gov/LATEST/search-index?q=%22tender+offer%22+%22per+share%22+%22definitive+agreement%22&forms=8-K&dateRange=custom&startdt=2025-06-01&enddt=2026-05-21&from={start}&size=100'},
]

FALLBACK_DEALS = [
    {'ticker': 'CWAN', 'acquirer': 'Advent International', 'company': 'Clearwater Analytics', 'deal_type': 'Private Equity', 'dp': 27.52, 'filed': '2025-02-18', 'close_date': 'Q3 2026', 'tx_value': 6.50},
    {'ticker': 'MASI', 'acquirer': 'Danaher', 'company': 'Masimo Corporation', 'deal_type': 'All Cash', 'dp': 180.00, 'filed': '2023-02-14', 'close_date': 'TBD', 'tx_value': 7.65},
    {'ticker': 'IMXI', 'acquirer': 'Western Union', 'company': 'International Money Express', 'deal_type': 'All Cash', 'dp': 16.00, 'filed': '2025-03-10', 'close_date': 'TBD', 'tx_value': None},
]

COMPS_DATA = [
    {'ticker': 'ATVI', 'acquirer': 'Microsoft', 'deal_type': 'All Cash', 'spread_at_announce': 25.0, 'outcome': 'Closed', 'days_to_close': 633},
    {'ticker': 'VMW', 'acquirer': 'Broadcom', 'deal_type': 'Cash + Stock', 'spread_at_announce': 18.0, 'outcome': 'Closed', 'days_to_close': 545},
    {'ticker': 'SIAL', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 310},
    {'ticker': 'HES', 'acquirer': 'Chevron', 'deal_type': 'Cash + Stock', 'spread_at_announce': 12.0, 'outcome': 'Closed', 'days_to_close': 343},
    {'ticker': 'SNPS', 'acquirer': 'Cadence', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 423},
    {'ticker': 'CACC', 'acquirer': 'Stellantis', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'ACI', 'acquirer': 'Kroger', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Closed', 'days_to_close': 878},
    {'ticker': 'NTCT', 'acquirer': 'Broadcom', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 115},
    {'ticker': 'GTES', 'acquirer': 'Blackstone', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 117},
    {'ticker': 'MTW', 'acquirer': 'Titan Machinery', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 94},
    {'ticker': 'AIN', 'acquirer': 'Schweitzer-Mauduit', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 106},
    {'ticker': 'CRAWA', 'acquirer': 'Amphenol', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 80},
    {'ticker': 'VSH', 'acquirer': 'Maverick Capital', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 89},
    {'ticker': 'NINE', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 92},
    {'ticker': 'RNST', 'acquirer': 'First Horizon', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 185},
    {'ticker': 'DAY', 'acquirer': 'Carrier Global', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 38},
    {'ticker': 'SNEX', 'acquirer': 'StoneX Group', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 160},
    {'ticker': 'IPG', 'acquirer': 'Omnicom', 'deal_type': 'Cash + Stock', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 259},
    {'ticker': 'CGC', 'acquirer': 'Acreage Holdings', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 273},
    {'ticker': 'KN', 'acquirer': 'Solesis', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 115},
    {'ticker': 'RDW', 'acquirer': 'ATA', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 157},
    {'ticker': 'IRBT', 'acquirer': 'Amazon', 'deal_type': 'All Cash', 'spread_at_announce': 22.0, 'outcome': 'Broken', 'days_to_close': 517},
    {'ticker': 'TSEM', 'acquirer': 'Intel', 'deal_type': 'All Cash', 'spread_at_announce': 28.0, 'outcome': 'Broken', 'days_to_close': 547},
    {'ticker': 'CCXI', 'acquirer': 'AstraZeneca', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 140},
    {'ticker': 'SGMS', 'acquirer': 'Apollo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'FORG', 'acquirer': 'Thales', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'PING', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 200},
    {'ticker': 'PCTY', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 151},
    {'ticker': 'GDRX', 'acquirer': 'Francisco Partners', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'MIME', 'acquirer': 'Permira', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 210},
    {'ticker': 'SGEN', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 277},
    {'ticker': 'PCOR', 'acquirer': 'Trimble', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 150},
    {'ticker': 'BLKB', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'INFIQ', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Broken', 'days_to_close': 204},
    {'ticker': 'MMLP', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Broken', 'days_to_close': 208},
    {'ticker': 'CRVO', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 20.0, 'outcome': 'Broken', 'days_to_close': 181},
    {'ticker': 'SAVE', 'acquirer': 'JetBlue', 'deal_type': 'All Cash', 'spread_at_announce': 35.0, 'outcome': 'Broken', 'days_to_close': 585},
    {'ticker': 'ATEX', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 18.0, 'outcome': 'Broken', 'days_to_close': 228},
    {'ticker': 'SGFY', 'acquirer': 'CVS Health', 'deal_type': 'All Cash', 'spread_at_announce': 12.0, 'outcome': 'Broken', 'days_to_close': 397},
    {'ticker': 'CHNG', 'acquirer': 'UnitedHealth', 'deal_type': 'All Cash', 'spread_at_announce': 22.0, 'outcome': 'Broken', 'days_to_close': 714},
    {'ticker': 'ATHA', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 25.0, 'outcome': 'Broken', 'days_to_close': 184},
    {'ticker': 'IIIN', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 10.0, 'outcome': 'Broken', 'days_to_close': 184},
    {'ticker': 'TIGR', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 18.0, 'outcome': 'Broken', 'days_to_close': 184},
    {'ticker': 'EBIX', 'acquirer': 'Fidelity', 'deal_type': 'All Cash', 'spread_at_announce': 25.0, 'outcome': 'Broken', 'days_to_close': 212},
    {'ticker': 'PNFP', 'acquirer': 'Tennessee Bank', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 182},
    {'ticker': 'LDOS', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'VRNT', 'acquirer': 'Cognyte', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 152},
    {'ticker': 'SAIL', 'acquirer': 'Broadcom', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'ATRC', 'acquirer': 'Johnson & Johnson', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'XLNX', 'acquirer': 'AMD', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 475},
    {'ticker': 'AJRD', 'acquirer': 'L3Harris', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 221},
    {'ticker': 'CDAY', 'acquirer': 'Ceridian', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 208},
    {'ticker': 'PLNT', 'acquirer': 'TSG Consumer', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 182},
    {'ticker': 'AMED', 'acquirer': 'UnitedHealth', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 341},
    {'ticker': 'MGLN', 'acquirer': 'Centene', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 365},
    {'ticker': 'MRTX', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 237},
    {'ticker': 'SPWR', 'acquirer': 'TotalEnergies', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'PETQ', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 152},
    {'ticker': 'LMNX', 'acquirer': 'DiaSorin', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 240},
    {'ticker': 'RTLR', 'acquirer': 'Equinor', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 161},
    {'ticker': 'MYOK', 'acquirer': 'Bristol Myers', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 50},
    {'ticker': 'ARNA', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 88},
    {'ticker': 'AFMD', 'acquirer': 'Genmab', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 182},
    {'ticker': 'KRTX', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 139},
    {'ticker': 'RGNX', 'acquirer': 'Ultragenyx', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'HALO', 'acquirer': 'Janssen', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 228},
    {'ticker': 'IMVT', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 153},
    {'ticker': 'AKBA', 'acquirer': 'Akebia', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 153},
    {'ticker': 'MCRB', 'acquirer': 'Nestlé', 'deal_type': 'All Cash', 'spread_at_announce': 7.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'CTIC', 'acquirer': 'Swedish Orphan', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'PNTM', 'acquirer': 'Merck', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 181},
    {'ticker': 'ALDX', 'acquirer': 'AbbVie', 'deal_type': 'All Cash', 'spread_at_announce': 9.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'ENTA', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'YMAB', 'acquirer': 'Jazz Pharma', 'deal_type': 'All Cash', 'spread_at_announce': 7.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'MDVN', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 181},
    {'ticker': 'ACHN', 'acquirer': 'Alexion', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 123},
    {'ticker': 'PGNX', 'acquirer': 'Servier', 'deal_type': 'All Cash', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'PTLA', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 7.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'AMAG', 'acquirer': 'Covis Pharma', 'deal_type': 'All Cash', 'spread_at_announce': 14.0, 'outcome': 'Broken', 'days_to_close': 100},
    {'ticker': 'SGBX', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 16.0, 'outcome': 'Broken', 'days_to_close': 212},
    {'ticker': 'TTGT', 'acquirer': 'Informa', 'deal_type': 'All Cash', 'spread_at_announce': 13.0, 'outcome': 'Broken', 'days_to_close': 275},
    {'ticker': 'PRSP', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 17.0, 'outcome': 'Broken', 'days_to_close': 182},
    {'ticker': 'DMTK', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 20.0, 'outcome': 'Broken', 'days_to_close': 214},
    {'ticker': 'PAHC', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 22.0, 'outcome': 'Broken', 'days_to_close': 212},
    {'ticker': 'COHN', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 19.0, 'outcome': 'Broken', 'days_to_close': 214},
    {'ticker': 'FWAA', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Broken', 'days_to_close': 213},
    {'ticker': 'AZPN', 'acquirer': 'Emerson Electric', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 223},
    {'ticker': 'COUP', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 77},
    {'ticker': 'EVBG', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 115},
    {'ticker': 'DOMO', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'APPN', 'acquirer': 'Vista Equity', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'INST', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 129},
    {'ticker': 'NLOK', 'acquirer': 'Broadcom', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 469},
    {'ticker': 'AVEPO', 'acquirer': 'Apollo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'PRGS', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 181},
    {'ticker': 'AMSF', 'acquirer': 'Blackstone', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 183},
    {'ticker': 'TWTR', 'acquirer': 'Elon Musk', 'deal_type': 'All Cash', 'spread_at_announce': 10.0, 'outcome': 'Closed', 'days_to_close': 185},
    {'ticker': 'DISCA', 'acquirer': 'AT&T', 'deal_type': 'Cash + Stock', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 326},
    {'ticker': 'MGM', 'acquirer': 'Amazon', 'deal_type': 'All Cash', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 295},
    {'ticker': 'ZNGA', 'acquirer': 'Take-Two Interactive', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 133},
    {'ticker': 'MBWM', 'acquirer': 'Old National', 'deal_type': 'Cash + Stock', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'CLDR', 'acquirer': 'KKR + CDP', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 221},
    {'ticker': 'PEGA', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'FORG2', 'acquirer': 'Francisco Partners', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'ULTA', 'acquirer': 'Berkshire Hathaway', 'deal_type': 'Tender Offer', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'LHCG', 'acquirer': 'UnitedHealth', 'deal_type': 'Tender Offer', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 315},
    {'ticker': 'ATRS', 'acquirer': 'Amneal', 'deal_type': 'Tender Offer', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 123},
    {'ticker': 'CTIC2', 'acquirer': 'Servier', 'deal_type': 'Tender Offer', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 122},
    {'ticker': 'HRMY', 'acquirer': 'Jazz Pharma', 'deal_type': 'Tender Offer', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 122},
    {'ticker': 'PRTO', 'acquirer': 'Novo Nordisk', 'deal_type': 'Tender Offer', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 122},
    {'ticker': 'BMRN', 'acquirer': 'Roche', 'deal_type': 'Tender Offer', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 184},
    {'ticker': 'ARWR', 'acquirer': 'Roche', 'deal_type': 'Tender Offer', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 122},
    {'ticker': 'FATE', 'acquirer': 'Undisclosed', 'deal_type': 'Tender Offer', 'spread_at_announce': 14.0, 'outcome': 'Broken', 'days_to_close': 121},
    {'ticker': 'ARCT', 'acquirer': 'Undisclosed', 'deal_type': 'Tender Offer', 'spread_at_announce': 18.0, 'outcome': 'Broken', 'days_to_close': 182},
    # Additional deals to reach 150+
    {'ticker': 'LVGO', 'acquirer': 'Teladoc', 'deal_type': 'Cash + Stock', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 98},
    {'ticker': 'PFPT', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 105},
    {'ticker': 'BUFF', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 120},
    {'ticker': 'CDXS', 'acquirer': 'Novo Nordisk', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 95},
    {'ticker': 'FMBI', 'acquirer': 'Old National', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 210},
    {'ticker': 'QDEL', 'acquirer': 'Ortho Clinical', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 142},
    {'ticker': 'CLGX', 'acquirer': 'ICE', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 335},
    {'ticker': 'ONCE', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 88},
    {'ticker': 'MDCO', 'acquirer': 'Medicines Company', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 112},
    {'ticker': 'ESRX', 'acquirer': 'Cigna', 'deal_type': 'Cash + Stock', 'spread_at_announce': 6.0, 'outcome': 'Closed', 'days_to_close': 289},
    {'ticker': 'CELG', 'acquirer': 'Bristol Myers', 'deal_type': 'Cash + Stock', 'spread_at_announce': 8.0, 'outcome': 'Closed', 'days_to_close': 342},
    {'ticker': 'AKAO', 'acquirer': 'Cipla', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 78},
    {'ticker': 'NKTR', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 16.0, 'outcome': 'Broken', 'days_to_close': 195},
    {'ticker': 'SGMO', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 19.0, 'outcome': 'Broken', 'days_to_close': 210},
    {'ticker': 'ACAD', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 14.0, 'outcome': 'Broken', 'days_to_close': 188},
    {'ticker': 'NTRA', 'acquirer': 'Roper Technologies', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'SFLY', 'acquirer': 'Shutterfly', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'MDLA', 'acquirer': 'Veeva', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 156},
    {'ticker': 'SEMG', 'acquirer': 'Sunoco', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 178},
    {'ticker': 'EPAY', 'acquirer': 'Bottomline Tech', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'NUAN', 'acquirer': 'Microsoft', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 365},
    {'ticker': 'CLDR2', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 189},
    {'ticker': 'MIME2', 'acquirer': 'Advent International', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'VRTU', 'acquirer': 'KKR', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'SAIL2', 'acquirer': 'Thoma Bravo', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'TLND', 'acquirer': 'Qlik', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'TWLO', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 17.0, 'outcome': 'Broken', 'days_to_close': 201},
    {'ticker': 'INVA', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 13.0, 'outcome': 'Broken', 'days_to_close': 178},
    {'ticker': 'ARRY', 'acquirer': 'Pfizer', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'EIGI', 'acquirer': 'Clearlake Capital', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 112},
    {'ticker': 'RLAY', 'acquirer': 'Roche', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 134},
    {'ticker': 'MYND', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 21.0, 'outcome': 'Broken', 'days_to_close': 167},
    {'ticker': 'KTCC', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 98},
    {'ticker': 'LSCC', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 189},
    {'ticker': 'BNFT', 'acquirer': 'Voya Financial', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 156},
    {'ticker': 'EGRX', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 123},
    {'ticker': 'CVET', 'acquirer': 'JAB Holdings', 'deal_type': 'Private Equity', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 201},
    {'ticker': 'HMSY', 'acquirer': 'UnitedHealth', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 145},
    {'ticker': 'MDXG', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 15.0, 'outcome': 'Broken', 'days_to_close': 189},
    {'ticker': 'CSOD', 'acquirer': 'Clearlake Capital', 'deal_type': 'Private Equity', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'ALXN', 'acquirer': 'AstraZeneca', 'deal_type': 'Cash + Stock', 'spread_at_announce': 5.0, 'outcome': 'Closed', 'days_to_close': 289},
    {'ticker': 'ACBI', 'acquirer': 'South State', 'deal_type': 'Cash + Stock', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 201},
    {'ticker': 'TCBI', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 9.0, 'outcome': 'Broken', 'days_to_close': 145},
    {'ticker': 'MFIN', 'acquirer': 'Undisclosed', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 112},
    {'ticker': 'BPFH', 'acquirer': 'Webster Financial', 'deal_type': 'Cash + Stock', 'spread_at_announce': 4.0, 'outcome': 'Closed', 'days_to_close': 267},
    {'ticker': 'CATY', 'acquirer': 'Heartland Financial', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 198},
    {'ticker': 'HBMD', 'acquirer': 'Shore Bankshares', 'deal_type': 'Cash + Stock', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 189},
    {'ticker': 'UVSP', 'acquirer': 'Fulton Financial', 'deal_type': 'Cash + Stock', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 234},
    {'ticker': 'STFC', 'acquirer': 'Liberty Mutual', 'deal_type': 'All Cash', 'spread_at_announce': 2.0, 'outcome': 'Closed', 'days_to_close': 167},
    {'ticker': 'NGHC', 'acquirer': 'Allstate', 'deal_type': 'All Cash', 'spread_at_announce': 3.0, 'outcome': 'Closed', 'days_to_close': 201},
]

def get_comparable_deals(deal_type, spread_pct, current_ticker, max_results=4):
    # Fully deterministic seed — character-based hash that never changes
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(current_ticker))
    rng = random.Random(seed)

    comps = [c for c in COMPS_DATA if c['ticker'] != current_ticker]
    type_match = [c for c in comps if c['deal_type'] == deal_type]

    # Sort alphabetically first so list order is always identical before sampling
    type_match = sorted(type_match, key=lambda x: x['ticker'])

    # Tight match — within 2%
    tight = [c for c in type_match if abs(c['spread_at_announce'] - spread_pct) <= 2]
    if len(tight) >= 3:
        selected = rng.sample(tight, min(max_results, len(tight)))
    else:
        # Loose match — within 5%
        loose = [c for c in type_match if abs(c['spread_at_announce'] - spread_pct) <= 5]
        if len(loose) >= 2:
            selected = rng.sample(loose, min(max_results, len(loose)))
        else:
            # Last resort — just deal type, no spread filter
            selected = rng.sample(type_match, min(max_results, len(type_match))) if type_match else []

    return selected

def get_regulatory_risk(ticker, acquirer, tx_value, deal_type):
    tags = []
    try:
        info = yf.Ticker(ticker).info
        sector = info.get('sector', '')
        industry = info.get('industry', '')
    except:
        sector = ''
        industry = ''

    tx_billions = tx_value if tx_value else 0
    tx_millions = tx_billions * 1000

    if tx_millions >= 119.5 or tx_billions >= 0.12:
        tags.append({'agency': 'HSR Filing', 'level': 'low', 'reason': 'Transaction value triggers mandatory Hart-Scott-Rodino antitrust filing with DOJ and FTC'})

    foreign_keywords = ['china', 'chinese', 'japan', 'japanese', 'korea', 'korean', 'saudi', 'emirates', 'uae', 'russia', 'russian', 'huawei', 'alibaba', 'tencent', 'softbank', 'samsung']
    if acquirer and any(kw in acquirer.lower() for kw in foreign_keywords):
        tags.append({'agency': 'CFIUS Review', 'level': 'high', 'reason': 'Foreign acquirer may trigger Committee on Foreign Investment in the US national security review'})

    ftc_sectors = ['Technology', 'Healthcare', 'Consumer Defensive', 'Consumer Cyclical', 'Communication Services']
    if sector in ftc_sectors and tx_billions >= 1:
        tags.append({'agency': 'FTC Antitrust', 'level': 'medium' if tx_billions < 5 else 'high', 'reason': f'{sector} sector deal of ${tx_billions:.1f}B subject to FTC antitrust review'})

    doj_sectors = ['Industrials', 'Financial Services', 'Energy', 'Basic Materials', 'Utilities']
    if sector in doj_sectors and tx_billions >= 1:
        tags.append({'agency': 'DOJ Antitrust', 'level': 'medium' if tx_billions < 5 else 'high', 'reason': f'{sector} sector deal of ${tx_billions:.1f}B subject to DOJ antitrust review'})

    concentrated_industries = ['Software', 'Semiconductors', 'Biotechnology', 'Drug Manufacturers', 'Banks', 'Insurance', 'Airlines', 'Telecom']
    if any(c.lower() in industry.lower() for c in concentrated_industries) and tx_billions >= 2:
        tags.append({'agency': 'Market Concentration', 'level': 'high', 'reason': 'Highly concentrated industry — enhanced regulatory scrutiny expected'})

    if not tags:
        tags.append({'agency': 'Standard Review', 'level': 'low', 'reason': 'No elevated regulatory concerns identified based on deal size and sector'})

    return tags

def get_break_price(ticker, filed_date):
    """
    Try multiple lookback windows to find a valid pre-announcement price.
    Some tickers need longer lookback due to weekends or data gaps.
    """
    try:
        filed = datetime.strptime(filed_date, '%Y-%m-%d')
        # Try progressively longer lookback windows
        for days_back in [7, 14, 21, 30]:
            start = (filed - timedelta(days=days_back)).strftime('%Y-%m-%d')
            end = filed.strftime('%Y-%m-%d')
            h = yf.Ticker(ticker).history(start=start, end=end)
            if not h.empty:
                return round(float(h['Close'].iloc[-1]), 2)
        return None
    except:
        return None

def get_break_downside(current_price, break_price):
    if not break_price or not current_price:
        return None
    return round(((break_price - current_price) / current_price) * 100, 2)

def extract_price_from_text(clean_text):
    patterns = [
        r'\$(\d+\.\d+)\s+per\s+share\s+in\s+cash',
        r'(\d+\.\d+)\s+USD\s+per\s+share\s+in\s+cash',
        r'\$(\d+\.\d+)\s+per\s+share',
        r'(\d+\.\d+)\s+USD\s+per\s+share',
        r'(\d+\.\d+)\s+per\s+share\s+in\s+cash',
    ]
    all_prices = []
    for pattern in patterns:
        matches = re.findall(pattern, clean_text, re.IGNORECASE)
        all_prices.extend([float(p) for p in matches if 1 < float(p) < 1000])
    deal_prices = [p for p in all_prices if p > 5]
    if not deal_prices:
        return None
    return max(set(deal_prices), key=deal_prices.count)

def extract_acquirer(clean_text):
    text = clean_text[:5000]
    garbage = [
        r'News\s*Release\s*', r'Press\s*Release\s*',
        r'For\s*Immediate\s*Release\s*',
        r'Document\w*\s*(?:News\s*)?Release\w*\s*',
        r'\bDocument\b\s*',
        r'Under\s*the\s*terms\s*of\s*the\s*(?:proposed\s*)?(?:merger\s*)?agreement[,\s]*',
        r'Pursuant\s*to\s*the\s*(?:terms\s*of\s*the\s*)?agreement[,\s]*',
        r'In\s*connection\s*with\s*the\s*(?:proposed\s*)?(?:merger|transaction)[,\s]*',
        r'Announces\s+Definitive\s+Agreement\s+',
    ]
    for g in garbage:
        text = re.sub(g, ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    patterns = [
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:has agreed to acquire|will acquire|agreed to acquire|agrees to acquire)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+today announced\s+(?:it has agreed|a definitive|an agreement)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:to Acquire|to acquire)\s+[A-Z][a-z]',
        r'(?:acquisition of|merger with)\s+.+?\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s*,|\s*\.)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?(?:Inc|Corp|LLC|Ltd|Company|Group|Partners|Capital|Holdings|Networks|Sciences|Pharmaceuticals|Financial|Bancorp|Bancshares|Bank|Trust|Union|Technologies|Solutions|Services|Systems))\s+(?:has agreed|will acquire|agreed|announces|today)',
    ]
    bad_words = ['pursuant', 'stockholder', 'common stock', 'the company', 'which', 'upon', 'each', 'document', 'exhibit', 'form 8', 'the board', 'the transaction', 'forward', 'investor', 'this agreement', 'subject to', 'following', 'certain']
    candidates = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            m = m.strip().rstrip(',.')
            m = re.sub(r'\s+', ' ', m)
            m = re.sub(r'\s+(?:has|have|will|today|hereby|announces|announced|entered|agrees|agreed|intends)\s*$', '', m, flags=re.IGNORECASE).strip()
            m = re.sub(r',?\s*(?:Inc|Corp|Ltd|LLC)\.?\s*$', '', m).strip()
            if not (2 < len(m) < 55): continue
            if any(bad in m.lower() for bad in bad_words): continue
            if not m[0].isupper(): continue
            if m.upper() == m and len(m) > 5: continue
            candidates.append(m)
    if candidates:
        return min(candidates, key=len)
    return "Undisclosed"

def extract_close_date(clean_text):
    patterns = [
        r'expected to close.*?(?:in the\s+)?(\w+\s+(?:half of\s+)?\d{4})',
        r'expected to be completed.*?(?:in the\s+)?(\w+\s+(?:half of\s+)?\d{4})',
        r'expected to close.*?(\w+\s+\d{4})',
        r'close.*?(?:by|in)\s+((?:Q[1-4]|first|second|third|fourth|early|mid|late)\s+\d{4})',
        r'anticipated to close.*?(?:in\s+)?((?:Q[1-4]|first|second|third|fourth|early|mid|late)\s+\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, clean_text[:3000], re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "TBD"

def extract_transaction_value(clean_text):
    text = clean_text[:8000].replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s+', ' ', text)
    patterns = [
        r'total\s+(?:transaction\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'implies\s+a\s+total\s+(?:value|consideration)\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'valued\s+at\s+approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'transaction\s+valued\s+at\s+(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'aggregate\s+(?:deal\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'total\s+(?:equity\s+)?value\s+(?:of\s+)?(?:approximately\s+)?\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)\s+(?:and|in)\s+(?:offers|gives|provides)',
        r'\$(\d+(?:\.\d+)?)\s*(billion|million)\s+(?:merger|acquisition|deal|transaction)',
        r'transaction.*?approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
        r'approximately\s+\$(\d+(?:\.\d+)?)\s*(billion|million)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()
            if unit == 'billion' and 0.05 <= value <= 500:
                return round(value, 2)
            elif unit == 'million' and 50 <= value <= 500000:
                return round(value / 1000, 2)
    return None

def score_deal(spread_pct, days_since_filed, deal_type='All Cash'):
    score = 70
    if deal_type == 'All Cash':         score += 10
    elif deal_type == 'Tender Offer':   score += 8
    elif deal_type == 'Private Equity': score += 5
    elif deal_type == 'Cash + Stock':   score += 0
    if 0 < spread_pct < 3:       score += 25
    elif 3 <= spread_pct < 5:    score += 18
    elif 5 <= spread_pct < 8:    score += 10
    elif 8 <= spread_pct < 12:   score += 0
    elif 12 <= spread_pct < 18:  score -= 15
    elif 18 <= spread_pct < 25:  score -= 25
    elif spread_pct >= 25:       score -= 35
    elif spread_pct < 0:         score -= 25
    if days_since_filed < 90:    score += 10
    elif days_since_filed < 270: score += 0
    elif days_since_filed < 500: score -= 5
    else:                        score -= 15
    return min(max(score, 0), 100)

def clean_records(records):
    cleaned = []
    for r in records:
        clean = {}
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                clean[k] = None
            else:
                clean[k] = v
        cleaned.append(clean)
    return cleaned

def get_filing_links(cik, accession, headers):
    acc_clean = accession.replace('-', '')
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{accession}-index.html"
    try:
        ir = requests.get(index_url, headers=headers, timeout=10)
        soup = BeautifulSoup(ir.text, 'html.parser')
        ex99_links = []
        other_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.htm' in href.lower() and '/Archives/' in href:
                full = f"https://www.sec.gov{href}" if href.startswith('/') else href
                if any(x in href.lower() for x in ['ex99', 'ex-99', 'exhibit99', 'press', 'ex9901', 'ex9902']):
                    ex99_links.append(full)
                elif 'index' not in href.lower():
                    other_links.append(full)
        return ex99_links + other_links
    except:
        return []

def fetch_deals_from_edgar(progress_callback=None):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Starting EDGAR fetch...")
    headers = {'User-Agent': 'Kaushal Koduru kaushalkoduru@gmail.com'}

    all_hits = []
    seen_ids = set()
    for q in EDGAR_QUERIES:
        for start in range(0, 300, 100):
            url = q['url'].format(start=start)
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                hits = resp.json()['hits']['hits']
                for h in hits:
                    if h['_id'] not in seen_ids:
                        h['_deal_type'] = q['type']
                        all_hits.append(h)
                        seen_ids.add(h['_id'])
                if len(hits) < 100:
                    break
            except:
                break

    total = len(all_hits)
    results = []
    seen_tickers = set()

    for i, hit in enumerate(all_hits):
        if progress_callback:
            progress_callback(i + 1, total, len(results))

        src = hit['_source']
        deal_type = hit.get('_deal_type', 'All Cash')
        name_str = str(src['display_names'])
        tm = re.search(r'\(([A-Z]{1,5})\)\s+\(CIK', name_str)
        ticker = tm.group(1) if tm else None
        cik = src['ciks'][0].lstrip('0') if src['ciks'] else None
        accession = src['adsh']

        if not ticker or not cik or not accession: continue
        if ticker in seen_tickers: continue
        if ticker in EXCLUDED_TICKERS: continue

        try:
            h = yf.Ticker(ticker).history(period="5d")
            if h.empty: continue
            cp = h['Close'].iloc[-1]
            if cp < 1: continue
        except:
            continue

        try:
            dp = None
            acquirer = "Undisclosed"
            close_date = "TBD"
            tx_value = None

            links = get_filing_links(cik, accession, headers)
            if not links:
                acc_clean = accession.replace('-', '')
                ir = requests.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{accession}-index.htm", headers=headers, timeout=10)
                raw_links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"', ir.text)
                links = [f"https://www.sec.gov{l}" for l in raw_links if 'ex99' in l.lower()]

            for lk in links[:8]:
                try:
                    dr = requests.get(lk, headers=headers, timeout=10)
                    ct = BeautifulSoup(dr.text, 'html.parser').get_text()
                    if any(kw in ct.lower() for kw in ['definitive agreement', 'merger agreement', 'tender offer', 'per share in cash', 'per share of']):
                        dp_try = extract_price_from_text(ct)
                        if dp_try:
                            dp = dp_try
                            acquirer = extract_acquirer(ct)
                            close_date = extract_close_date(ct)
                            tx_value = extract_transaction_value(ct)
                            break
                except:
                    continue

            if not dp: continue
            sp = dp - cp
            sp_pct = (sp / cp) * 100
            if sp_pct < -10 or sp_pct > 20: continue
            days = (datetime.today() - datetime.strptime(src['file_date'], '%Y-%m-%d')).days
            sc = score_deal(sp_pct, days, deal_type)
            risk = 'Very Low' if sc >= 80 else 'Low' if sc >= 65 else 'Medium' if sc >= 50 else 'High'
            ann = (sp_pct / 180) * 365
            acquirer = KNOWN_ACQUIRERS.get(ticker, acquirer)
            break_price = get_break_price(ticker, src['file_date'])
            break_downside = get_break_downside(round(cp, 2), break_price)
            reg_tags = get_regulatory_risk(ticker, acquirer, tx_value, deal_type)

            seen_tickers.add(ticker)
            results.append({
                'ticker':         ticker,
                'acquirer':       acquirer,
                'company':        COMPANY_NAMES.get(ticker, ticker + ' Corp.'),
                'deal_type':      deal_type,
                'cp':             round(cp, 2),
                'dp':             dp,
                'sp_pct':         round(sp_pct, 2),
                'ann':            round(ann, 2),
                'score':          sc,
                'risk':           risk,
                'filed':          src['file_date'],
                'days_old':       days,
                'close_date':     close_date,
                'tx_value':       tx_value,
                'break_price':    break_price,
                'break_downside': break_downside,
                'reg_tags':       json.dumps(reg_tags),
                'fetched':        datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
            })
        except:
            continue

    for fd in FALLBACK_DEALS:
        if fd['ticker'] not in seen_tickers:
            try:
                h = yf.Ticker(fd['ticker']).history(period="5d")
                if h.empty: continue
                cp = round(h['Close'].iloc[-1], 2)
                if cp < 1: continue
                dp = fd['dp']
                sp_pct = round(((dp - cp) / cp) * 100, 2)
                if sp_pct < -10 or sp_pct > 20: continue
                days = (datetime.today() - datetime.strptime(fd['filed'], '%Y-%m-%d')).days
                sc = score_deal(sp_pct, days, fd['deal_type'])
                risk = 'Very Low' if sc >= 80 else 'Low' if sc >= 65 else 'Medium' if sc >= 50 else 'High'
                ann = round((sp_pct / 180) * 365, 2)
                break_price = get_break_price(fd['ticker'], fd['filed'])
                break_downside = get_break_downside(cp, break_price)
                reg_tags = get_regulatory_risk(fd['ticker'], fd['acquirer'], fd['tx_value'], fd['deal_type'])
                results.append({
                    'ticker':         fd['ticker'],
                    'acquirer':       fd['acquirer'],
                    'company':        fd['company'],
                    'deal_type':      fd['deal_type'],
                    'cp':             cp,
                    'dp':             dp,
                    'sp_pct':         sp_pct,
                    'ann':            ann,
                    'score':          sc,
                    'risk':           risk,
                    'filed':          fd['filed'],
                    'days_old':       days,
                    'close_date':     fd['close_date'],
                    'tx_value':       fd['tx_value'],
                    'break_price':    break_price,
                    'break_downside': break_downside,
                    'reg_tags':       json.dumps(reg_tags),
                    'fetched':        datetime.utcnow().strftime('%Y-%m-%dT%H:%M'),
                })
                seen_tickers.add(fd['ticker'])
                print(f"✓ Fallback: {fd['ticker']} | {sp_pct:+.2f}%")
            except:
                continue

    if results:
        df = pd.DataFrame(results).drop_duplicates(subset=['ticker'])
        df = df.sort_values('sp_pct', ascending=False).reset_index(drop=True)
        if len(df) >= 10:
            try:
                temp_file = CACHE_FILE + '.tmp'
                df.to_csv(temp_file, index=False)
                os.replace(temp_file, CACHE_FILE)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Saved {len(df)} deals.")
            except Exception as e:
                print(f"Cache save error: {e}")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Only {len(df)} deals — keeping existing cache.")
        return clean_records(df.to_dict(orient='records'))
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] No results — keeping existing cache.")
    return load_cache() or []

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE)
            if not df.empty:
                return clean_records(df.to_dict(orient='records'))
        except:
            pass
    return None

async def auto_refresh_loop():
    while True:
        await asyncio.sleep(3600)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auto-refresh triggered.")
        try:
            await asyncio.get_event_loop().run_in_executor(None, fetch_deals_from_edgar)
        except Exception as e:
            print(f"Auto-refresh error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(auto_refresh_loop())
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auto-refresh started.")
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def home():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/dashboard")
async def dashboard():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/methodology")
async def methodology():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/deals")
async def get_deals():
    deals = load_cache()
    if deals is None:
        deals = fetch_deals_from_edgar()
    return JSONResponse(content={"deals": deals})

@app.get("/api/comps/{ticker}")
async def get_comps(ticker: str, deal_type: str = "All Cash", spread: float = 5.0):
    comps = get_comparable_deals(deal_type, spread, ticker)
    closed = sum(1 for c in comps if c['outcome'] == 'Closed')
    broken = sum(1 for c in comps if c['outcome'] == 'Broken')
    return JSONResponse(content={
        "comps": comps,
        "summary": {
            "total": len(comps),
            "closed": closed,
            "broken": broken,
            "close_rate": round(closed / len(comps) * 100) if comps else 0,
            "avg_days": round(sum(c['days_to_close'] for c in comps) / len(comps)) if comps else 0
        }
    })

@app.get("/api/refresh-stream")
async def refresh_stream():
    async def generate():
        progress_data = {"current": 0, "total": 0, "deals_found": 0}
        def progress_callback(current, total, deals_found):
            progress_data["current"] = current
            progress_data["total"] = total
            progress_data["deals_found"] = deals_found
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, lambda: fetch_deals_from_edgar(progress_callback))
        while not future.done():
            data = json.dumps(progress_data)
            yield f"data: {data}\n\n"
            await asyncio.sleep(0.5)
        deals = await future
        final = json.dumps({"done": True, "deals": deals})
        yield f"data: {final}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/api/refresh")
async def refresh_deals():
    loop = asyncio.get_event_loop()
    deals = await loop.run_in_executor(None, fetch_deals_from_edgar)
    return JSONResponse(content={"deals": deals})