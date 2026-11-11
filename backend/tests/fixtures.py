"""Synthetic SEC/ECB/Tiingo payloads in the documented formats. TEST DATA ONLY.

"Example Corp" (CIK 1234567) is fictional; the numbers are invented solely to
exercise parsing, restatement handling, concept fallback and quarter derivation.
"""

CIK = 1234567


def f(start, end, val, form, filed, accn, fy=2024, fp="FY", frame=""):
    d = {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}
    if start:
        d["start"] = start
    if frame:
        d["frame"] = frame
    return d


K24 = ("10-K", "2025-02-15", "0001234567-25-000010")
K23 = ("10-K", "2024-02-15", "0001234567-24-000010")
K22 = ("10-K", "2023-02-15", "0001234567-23-000010")
Q1 = ("10-Q", "2024-05-01", "0001234567-24-000020")
Q2 = ("10-Q", "2024-08-01", "0001234567-24-000030")
Q3 = ("10-Q", "2024-11-01", "0001234567-24-000040")

COMPANYFACTS = {
    "cik": CIK,
    "entityName": "EXAMPLE CORP",
    "facts": {
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [f(None, "2025-01-31", 100, *K24)]}}},
        "us-gaap": {
            "Revenues": {"units": {"USD": [
                f("2024-01-01", "2024-12-31", 1200, *K24),
                f("2023-01-01", "2023-12-31", 1010, *K24, fy=2024),  # restated comparative (later filing wins)
                f("2023-01-01", "2023-12-31", 1000, *K23, fy=2023),
                f("2024-01-01", "2024-03-31", 250, *Q1, fp="Q1"),
                f("2024-04-01", "2024-06-30", 300, *Q2, fp="Q2"),
                f("2024-01-01", "2024-06-30", 550, *Q2, fp="Q2"),
                f("2024-07-01", "2024-09-30", 310, *Q3, fp="Q3"),
                f("2024-01-01", "2024-09-30", 860, *Q3, fp="Q3"),
            ]}},
            "SalesRevenueNet": {"units": {"USD": [f("2022-01-01", "2022-12-31", 900, *K22, fy=2022)]}},
            "NetIncomeLoss": {"units": {"USD": [
                f("2024-01-01", "2024-12-31", 120, *K24),
                f("2023-01-01", "2023-12-31", 100, *K23, fy=2023),
                f("2022-01-01", "2022-12-31", 80, *K22, fy=2022),
            ]}},
            "EarningsPerShareDiluted": {"units": {"USD/shares": [
                f("2024-01-01", "2024-12-31", 1.2, *K24),
                f("2023-01-01", "2023-12-31", 1.0, *K23, fy=2023),
                f("2024-01-01", "2024-03-31", 0.25, *Q1, fp="Q1"),
            ]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                f("2024-01-01", "2024-12-31", 260, *K24),
                f("2024-01-01", "2024-03-31", 50, *Q1, fp="Q1"),
                f("2024-01-01", "2024-06-30", 110, *Q2, fp="Q2"),
                f("2024-01-01", "2024-09-30", 180, *Q3, fp="Q3"),
            ]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [f("2024-01-01", "2024-12-31", 60, *K24)]}},
            "Assets": {"units": {"USD": [f(None, "2024-12-31", 5000, *K24), f(None, "2023-12-31", 4500, *K24)]}},
            "StockholdersEquity": {"units": {"USD": [f(None, "2024-12-31", 2000, *K24)]}},
            "AssetsCurrent": {"units": {"USD": [f(None, "2024-12-31", 900, *K24)]}},
            "LiabilitiesCurrent": {"units": {"USD": [f(None, "2024-12-31", 600, *K24)]}},
            "SomethingWeDoNotUse": {"units": {"USD": [f(None, "2024-12-31", 1, *K24)]}},
        },
    },
}

SUBMISSIONS = {
    "cik": str(CIK),
    "entityType": "operating",
    "sic": "7372",
    "sicDescription": "Services-Prepackaged Software",
    "name": "EXAMPLE CORP",
    "tickers": ["EXMP"],
    "exchanges": ["Nasdaq"],
    "category": "Large accelerated filer",
    "fiscalYearEnd": "1231",
    "stateOfIncorporationDescription": "DE",
    "addresses": {"business": {"street1": "1 Example Way", "city": "SPRINGFIELD", "stateOrCountry": "IL", "zipCode": "62701"}},
    "phone": "555-0100",
    "formerNames": [{"name": "EXAMPLE INC", "from": "2001-01-01", "to": "2010-01-01"}],
    "filings": {"recent": {
        "accessionNumber": ["0001234567-25-000010", "0001234567-24-000040", "0001234567-24-000099"],
        "filingDate": ["2025-02-15", "2024-11-01", "2024-10-01"],
        "reportDate": ["2024-12-31", "2024-09-30", ""],
        "form": ["10-K", "10-Q", "4"],
        "primaryDocument": ["exmp-20241231.htm", "exmp-20240930.htm", "form4.xml"],
        "primaryDocDescription": ["10-K", "10-Q", ""],
    }},
}

TIINGO = [
    {"date": "2024-12-30T00:00:00.000Z", "open": 10, "high": 11, "low": 9.5, "close": 10.5, "volume": 1000, "adjClose": 10.5},
    {"date": "2024-12-31T00:00:00.000Z", "open": 10.5, "high": 12, "low": 10, "close": 11.55, "volume": 1200, "adjClose": 11.55},
]

ECB_CSV = """KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-12-30,1.0444,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-12-31,1.0389,A
EXR.D.GBP.EUR.SP00.A,D,GBP,EUR,SP00,A,2024-12-31,0.82918,A
EXR.D.JPY.EUR.SP00.A,D,JPY,EUR,SP00,A,2024-12-31,,A
"""
