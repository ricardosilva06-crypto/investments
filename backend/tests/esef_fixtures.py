"""Synthetic ESEF documents for a fictional issuer ("Example Europa SE"). TEST DATA ONLY.

The LEI is generated with valid ISO 17442 check digits but belongs to no real entity.
"""

import io
import json
import zipfile


def make_lei(base18: str) -> str:
    n = int("".join(str(int(c, 36)) for c in base18 + "00"))
    return f"{base18}{98 - n % 97:02d}"


LEI = make_lei("5299000EXAMPLE00EU")

IXBRL = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
  xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:ifrs="https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-full" xmlns:exe="http://example-europa.test/2023"
  xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
<head><title>Example Europa SE annual report 2023</title></head>
<body>
<div style="display:none"><ix:header><ix:hidden/><ix:resources>
  <xbrli:context id="FY23"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{LEI}</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="FY22"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{LEI}</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2022-01-01</xbrli:startDate><xbrli:endDate>2022-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="I23"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{LEI}</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="FY23_seg"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{LEI}</xbrli:identifier>
    <xbrli:segment><xbrldi:explicitMember dimension="ifrs:SegmentsAxis">exe:RetailMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
  <xbrli:unit id="EURps"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
</ix:resources></ix:header></div>
<p>Name: <ix:nonNumeric name="ifrs:NameOfReportingEntityOrNameOfParentEntity" contextRef="FY23">Example  Europa SE</ix:nonNumeric></p>
<table>
<tr><td>Revenue</td>
  <td><ix:nonFraction name="ifrs:Revenue" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal"><span>1.234</span>,5</ix:nonFraction></td>
  <td><ix:nonFraction name="ifrs:Revenue" contextRef="FY22" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">1.100,0</ix:nonFraction></td></tr>
<tr><td>Revenue retail segment</td><td><ix:nonFraction name="ifrs:Revenue" contextRef="FY23_seg" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">700,0</ix:nonFraction></td></tr>
<tr><td>Cost of sales</td><td><ix:nonFraction name="ifrs:CostOfSales" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">(734,5)</ix:nonFraction></td></tr>
<tr><td>Profit attributable to owners</td>
  <td><ix:nonFraction name="ifrs:ProfitLossAttributableToOwnersOfParent" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">150,0</ix:nonFraction></td>
  <td>(<ix:nonFraction name="ifrs:ProfitLossAttributableToOwnersOfParent" contextRef="FY22" unitRef="EUR" decimals="-5" scale="6" sign="-" format="ixt:num-comma-decimal">20,0</ix:nonFraction>)</td></tr>
<tr><td>Diluted EPS</td><td><ix:nonFraction name="ifrs:DilutedEarningsLossPerShare" contextRef="FY23" unitRef="EURps" decimals="2" format="ixt:num-comma-decimal">1,25</ix:nonFraction></td></tr>
<tr><td>Operating cash flow</td><td><ix:nonFraction name="ifrs:CashFlowsFromUsedInOperatingActivities" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">300,0</ix:nonFraction></td></tr>
<tr><td>Capex</td><td><ix:nonFraction name="ifrs:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">80,0</ix:nonFraction></td></tr>
<tr><td>Dividends paid</td><td><ix:nonFraction name="ifrs:DividendsPaidClassifiedAsFinancingActivities" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:fixed-zero">-</ix:nonFraction></td></tr>
<tr><td>Total assets</td><td><ix:nonFraction name="ifrs:Assets" contextRef="I23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">2.000,0</ix:nonFraction></td></tr>
<tr><td>Equity</td><td><ix:nonFraction name="ifrs:EquityAttributableToOwnersOfParent" contextRef="I23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">900,0</ix:nonFraction></td></tr>
<tr><td>Adjusted EBITDA (company measure)</td><td><ix:nonFraction name="exe:AdjustedEbitda" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">333,0</ix:nonFraction></td></tr>
<tr><td>Revenue (repeated in a note)</td><td><ix:nonFraction name="ifrs:Revenue" contextRef="FY23" unitRef="EUR" decimals="-5" scale="6" format="ixt:num-comma-decimal">1.234,5</ix:nonFraction></td></tr>
</table></body></html>
""".encode()


def package(xhtml: bytes = IXBRL, name: str = "exampleeuropa-2023-12-31-en") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{name}/META-INF/reportPackage.json", json.dumps({"documentInfo": {"documentType": "https://xbrl.org/report-package/2023"}}))
        z.writestr(f"{name}/reports/{name}.xhtml", xhtml)
        z.writestr("../evil.txt", b"zip-slip attempt must be ignored")
    return buf.getvalue()


def xbrl_json_2024() -> dict:
    ent = f"lei:{LEI}"

    def fact(concept, period, value, unit="iso4217:EUR", **dims):
        return {"value": str(value), "decimals": -5, "dimensions": {"concept": concept, "entity": ent, "period": period, "unit": unit, **dims}}

    return {
        "documentInfo": {"documentType": "https://xbrl.org/2021/xbrl-json",
                         "namespaces": {"ifrs-full": "https://xbrl.ifrs.org/taxonomy/2023-03-23/ifrs-full", "lei": "http://standards.iso.org/iso/17442"}},
        "facts": {
            "f1": fact("ifrs-full:Revenue", "2024-01-01T00:00:00/2025-01-01T00:00:00", 1400000000),
            "f2": fact("ifrs-full:Revenue", "2023-01-01T00:00:00/2024-01-01T00:00:00", 1240000000),  # restated comparative
            "f3": fact("ifrs-full:ProfitLossAttributableToOwnersOfParent", "2024-01-01T00:00:00/2025-01-01T00:00:00", 180000000),
            "f4": fact("ifrs-full:Assets", "2025-01-01T00:00:00", 2300000000),
            "f5": fact("ifrs-full:Revenue", "2024-01-01T00:00:00/2025-01-01T00:00:00", 800000000, **{"ifrs-full:SegmentsAxis": "x:Retail"}),
            "f6": {"value": "Example Europa SE", "dimensions": {"concept": "ifrs-full:NameOfReportingEntityOrNameOfParentEntity", "entity": ent,
                                                                "period": "2024-01-01T00:00:00/2025-01-01T00:00:00"}},
        },
    }
