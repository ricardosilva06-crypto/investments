"""European fundamentals from ESEF annual financial reports (free, official).

Since 2020/2021, issuers listed on EU regulated markets must publish their annual
financial report in ESEF: XHTML with Inline XBRL tags from the IFRS taxonomy,
usually as a "report package" (.zip). Two free ways to get them into the app:

1. **Upload** a report package (.zip) or the .xhtml file, downloaded from the
   company's website or the national Officially Appointed Mechanism (OAM).
   Parsed entirely locally by ``parse_ixbrl`` (Inline XBRL 1.1).
2. **filings.xbrl.org** (XBRL International's free repository of ESEF filings),
   which also publishes each report converted to xBRL-JSON. Parsed by
   ``parse_xbrl_json`` (xBRL-JSON 1.0). Optional, by LEI.

Only non-dimensional numeric facts are kept (the consolidated totals); facts
with a dimension (segments, components of equity, ...) are skipped. Values are
stored exactly as tagged after applying the Inline XBRL ``scale`` and ``sign``.
Nothing is estimated. Reports are annual, so there are no quarterly figures.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

import httpx
from defusedxml import ElementTree as ET
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import EsefFact, EsefFiling, Security

IX_NS = ("http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL")
XBRLI = "http://www.xbrl.org/2003/instance"
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
MAX_PACKAGE_BYTES = 80 * 1024 * 1024
MAX_UNCOMPRESSED = 400 * 1024 * 1024
MAX_MEMBERS = 2000

FXO_BASE = "https://filings.xbrl.org"
client_factory = lambda: httpx.Client(timeout=60, follow_redirects=True)  # noqa: E731


class EsefError(ValueError):
    pass


@dataclass
class ParsedReport:
    lei: str
    entity_name: str
    period_end: date
    facts: list[dict] = field(default_factory=list)  # taxonomy, concept, unit, start, end, value
    skipped_dimensional: int = 0
    skipped_other: int = 0


def valid_lei(lei: str) -> bool:
    """ISO 17442 format and ISO 7064 MOD 97-10 check digits."""
    lei = lei.strip().upper()
    if not LEI_RE.match(lei):
        return False
    digits = "".join(str(int(c, 36)) for c in lei)
    return int(digits) % 97 == 1


# ------------------------------------------------------------------ helpers
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _prefix_for(namespace: str, nsmap: dict[str, str]) -> str:
    """Normalise the IFRS taxonomy to 'ifrs-full' whatever prefix the document uses."""
    if "xbrl.ifrs.org/taxonomy" in namespace and namespace.rstrip("/").endswith("ifrs-full"):
        return "ifrs-full"
    for p, uri in nsmap.items():
        if uri == namespace and p:
            return p
    return namespace.rstrip("/").rsplit("/", 1)[-1] or "ext"


def _text(el) -> str:
    return "".join(el.itertext())


def _parse_number(raw: str, fmt: str) -> Decimal:
    """Apply an Inline XBRL Transformation Registry format (common numeric ones)."""
    f = fmt.rsplit(":", 1)[-1].lower() if fmt else "num-dot-decimal"
    s = raw.strip().replace("\u00a0", " ").replace("\u202f", " ")
    if f in ("fixed-zero", "zerodash", "numdash") or s in ("-", "–", "—"):
        return Decimal(0)
    if f in ("num-comma-decimal", "numcommadecimal", "numspacecomma", "num-comma-decimal-apos"):
        s = re.sub(r"[ .'’]", "", s).replace(",", ".")
    elif f in ("num-dot-decimal", "numdotdecimal", "numspacedot", "numcommadot", "num-dot-decimal-apos", "numdotdecimalin"):
        s = re.sub(r"[ ,'’]", "", s)
    elif f in ("num-unit-decimal", "numunitdecimal"):
        parts = re.findall(r"\d+", s)
        if len(parts) >= 2:
            s = f"{parts[0]}.{parts[1]}"
    else:
        raise EsefError(f"unsupported number format {fmt}")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise EsefError(f"cannot read number '{raw}'") from exc


def _canonical_unit(measures: list[str], numerator: list[str] | None = None, denominator: list[str] | None = None) -> str:
    def m(q: str) -> str:
        loc = q.split(":")[-1]
        return "shares" if loc == "shares" else loc.upper() if len(loc) == 3 and loc.isalpha() else loc
    if numerator is not None:
        return f"{'*'.join(m(x) for x in numerator)}/{'*'.join(m(x) for x in denominator or [])}"
    return "*".join(m(x) for x in measures)


def _pick_period_end(facts: list[dict]) -> date:
    """The report's period: the most common end date of annual (≈1 year) durations, else the latest end."""
    years = Counter(f["end"] for f in facts if f["start"] and 350 <= (f["end"] - f["start"]).days <= 380)
    if years:
        latest = max(years)
        return latest
    if not facts:
        raise EsefError("No numeric facts found in this report.")
    return max(f["end"] for f in facts)


def _dedupe(facts: list[dict]) -> list[dict]:
    seen, out = set(), []
    for f in facts:
        key = (f["taxonomy"], f["concept"], f["unit"], f["start"], f["end"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


# ------------------------------------------------------------------ inline XBRL
def _nsmap_of(xml: bytes) -> dict[str, str]:
    """Prefix -> namespace declarations (ElementTree does not expose them; iXBRL names are prefixed QNames)."""
    return {p.decode(): u.decode() for p, u in re.findall(rb'xmlns:([A-Za-z0-9_.\-]+)\s*=\s*["\']([^"\']+)["\']', xml)}


def parse_ixbrl(documents: list[bytes]) -> ParsedReport:
    """Parse one Inline XBRL document set (one or more XHTML files sharing contexts/units)."""
    contexts: dict[str, dict] = {}
    units: dict[str, str] = {}
    raw_facts: list[tuple[dict, object]] = []
    names: list[str] = []
    for xml in documents:
        nsmap = _nsmap_of(xml)
        try:
            root = ET.fromstring(xml)
        except Exception as exc:  # defusedxml raises several types (incl. forbidden entities)
            raise EsefError(f"Not a valid XHTML/Inline XBRL document ({exc.__class__.__name__})") from exc
        for el in root.iter():
            ns, loc = _ns(el.tag), _local(el.tag)
            if ns == XBRLI and loc == "context":
                ident = el.find(f"{{{XBRLI}}}entity/{{{XBRLI}}}identifier")
                period = el.find(f"{{{XBRLI}}}period")
                dims = el.find(f".//{{{XBRLI}}}segment")
                scen = el.find(f".//{{{XBRLI}}}scenario")
                inst = period.find(f"{{{XBRLI}}}instant") if period is not None else None
                start = period.find(f"{{{XBRLI}}}startDate") if period is not None else None
                end = period.find(f"{{{XBRLI}}}endDate") if period is not None else None
                try:
                    if inst is not None:
                        s_, e_ = None, date.fromisoformat(_text(inst).strip()[:10])
                    else:
                        s_, e_ = date.fromisoformat(_text(start).strip()[:10]), date.fromisoformat(_text(end).strip()[:10])
                except (AttributeError, ValueError):
                    continue
                contexts[el.get("id")] = {
                    "lei": (_text(ident).strip().upper() if ident is not None else ""),
                    "scheme": ident.get("scheme", "") if ident is not None else "",
                    "start": s_, "end": e_,
                    "dimensional": (dims is not None and len(list(dims)) > 0) or (scen is not None and len(list(scen)) > 0),
                }
            elif ns == XBRLI and loc == "unit":
                div = el.find(f"{{{XBRLI}}}divide")
                if div is not None:
                    num = [_text(m).strip() for m in div.findall(f"{{{XBRLI}}}unitNumerator/{{{XBRLI}}}measure")]
                    den = [_text(m).strip() for m in div.findall(f"{{{XBRLI}}}unitDenominator/{{{XBRLI}}}measure")]
                    units[el.get("id")] = _canonical_unit([], num, den)
                else:
                    units[el.get("id")] = _canonical_unit([_text(m).strip() for m in el.findall(f"{{{XBRLI}}}measure")])
            elif ns in IX_NS and loc == "nonFraction":
                raw_facts.append(({"name": el.get("name", ""), "context": el.get("contextRef", ""), "unit": el.get("unitRef", ""),
                                   "scale": el.get("scale", "0"), "sign": el.get("sign", ""), "format": el.get("format", ""),
                                   "nil": el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true", "nsmap": nsmap}, el))
            elif ns in IX_NS and loc == "nonNumeric" and el.get("name", "").endswith(":NameOfReportingEntityOrNameOfParentEntity"):
                names.append(re.sub(r"\s+", " ", _text(el)).strip())

    report = ParsedReport(lei="", entity_name=names[0][:255] if names else "", period_end=date.min)
    facts: list[dict] = []
    leis = Counter()
    for a, el in raw_facts:
        ctx = contexts.get(a["context"])
        if ctx is None or a["nil"]:
            report.skipped_other += 1
            continue
        if ctx["dimensional"]:
            report.skipped_dimensional += 1
            continue
        prefix, _, local = a["name"].partition(":")
        namespace = a["nsmap"].get(prefix, "")
        taxonomy = _prefix_for(namespace, a["nsmap"]) if namespace else prefix
        try:
            v = _parse_number(_text(el), a["format"])
            v = v.scaleb(int(a["scale"] or 0))
        except (EsefError, ValueError):
            report.skipped_other += 1
            continue
        if a["sign"] == "-":
            v = -v
        leis[ctx["lei"]] += 1
        facts.append({"taxonomy": taxonomy, "concept": local, "unit": units.get(a["unit"], ""), "start": ctx["start"],
                      "end": ctx["end"], "value": v})
    if not leis:
        raise EsefError("No XBRL-tagged numbers were found. Is this an ESEF (inline XBRL) report?")
    report.lei = leis.most_common(1)[0][0]
    report.facts = _dedupe(facts)
    report.period_end = _pick_period_end(report.facts)
    return report


def read_package(data: bytes, filename: str) -> list[bytes]:
    """Return the inline XBRL document(s) of an ESEF report package (.zip) or a single .xhtml/.html file."""
    if len(data) > MAX_PACKAGE_BYTES:
        raise EsefError("File is larger than 80 MB.")
    if data[:2] != b"PK":
        if b"inlineXBRL" not in data[:200_000] and b"inlineXBRL" not in data:
            raise EsefError("Not an ESEF report: expected a report package (.zip) or an inline XBRL .xhtml file.")
        return [data]
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise EsefError("The .zip file is damaged.") from exc
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        raise EsefError("The package is too large once unpacked.")
    docs = []
    for i in infos:
        name = i.filename.replace("\\", "/")
        if i.is_dir() or name.startswith("/") or ".." in name.split("/"):
            continue
        if "/reports/" in f"/{name}" and name.lower().endswith((".xhtml", ".html", ".htm")):
            docs.append(z.read(i))
    if not docs:  # some packages place the report elsewhere
        docs = [z.read(i) for i in infos if i.filename.lower().endswith((".xhtml", ".html")) and not i.is_dir()]
    docs = [d for d in docs if b"inlineXBRL" in d]
    if not docs:
        raise EsefError("No inline XBRL report found inside the package.")
    return docs


# ------------------------------------------------------------------ xBRL-JSON
def _oim_period(p: str) -> tuple[date | None, date]:
    """xBRL-JSON periods use exclusive end datetimes: '2023-01-01T00:00:00' means end of 2022-12-31."""
    def d(s: str) -> date:
        dt = datetime.fromisoformat(s.replace("Z", ""))
        return (dt - timedelta(days=1)).date() if dt.time() == datetime.min.time() and "T" in s else dt.date()
    if "/" in p:
        a, b = p.split("/", 1)
        start = datetime.fromisoformat(a.replace("Z", "")).date()
        return start, d(b)
    return None, d(p)


def parse_xbrl_json(doc: dict) -> ParsedReport:
    facts_in = doc.get("facts")
    if not isinstance(facts_in, dict):
        raise EsefError("Not an xBRL-JSON document")
    prefixes = (doc.get("documentInfo") or {}).get("namespaces") or {}
    report = ParsedReport(lei="", entity_name="", period_end=date.min)
    facts, leis, names = [], Counter(), []
    core = {"concept", "entity", "period", "unit", "language", "noteId"}
    for f in facts_in.values():
        dims = f.get("dimensions") or {}
        concept = dims.get("concept", "")
        if concept.endswith(":NameOfReportingEntityOrNameOfParentEntity") and isinstance(f.get("value"), str):
            names.append(f["value"].strip())
        if "unit" not in dims or f.get("value") is None:
            continue  # non-numeric or nil
        if set(dims) - core:
            report.skipped_dimensional += 1
            continue
        try:
            value = Decimal(str(f["value"]))
            start, end = _oim_period(dims["period"])
        except (InvalidOperation, ValueError, KeyError):
            report.skipped_other += 1
            continue
        prefix, _, local = concept.partition(":")
        taxonomy = _prefix_for(prefixes.get(prefix, ""), prefixes) if prefixes.get(prefix) else prefix
        unit = dims["unit"]
        if "/" in unit:
            num, den = unit.split("/", 1)
            unit_c = _canonical_unit([], [num], [den])
        else:
            unit_c = _canonical_unit([unit])
        entity = dims.get("entity", "")
        leis[entity.split(":", 1)[-1].upper()] += 1
        facts.append({"taxonomy": taxonomy, "concept": local, "unit": unit_c, "start": start, "end": end, "value": value})
    if not leis:
        raise EsefError("No numeric facts in this xBRL-JSON document.")
    report.lei = leis.most_common(1)[0][0]
    report.entity_name = names[0][:255] if names else ""
    report.facts = _dedupe(facts)
    report.period_end = _pick_period_end(report.facts)
    return report


# ------------------------------------------------------------------ storage
def store(db: Session, report: ParsedReport, source: str, source_ref: str, raw: bytes, viewer_url: str = "") -> tuple[EsefFiling, bool]:
    """Store a parsed report. Re-importing the same file is a no-op. Returns (filing, created)."""
    if not valid_lei(report.lei):
        raise EsefError(f"The report's entity identifier '{report.lei}' is not a valid LEI.")
    sha = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(select(EsefFiling).where(EsefFiling.lei == report.lei, EsefFiling.period_end == report.period_end,
                                                  EsefFiling.sha256 == sha))
    if existing:
        return existing, False
    # A new version of the same year's report (e.g. a corrected filing) replaces the old one.
    for old in db.scalars(select(EsefFiling).where(EsefFiling.lei == report.lei, EsefFiling.period_end == report.period_end)):
        db.execute(delete(EsefFact).where(EsefFact.filing_id == old.id))
        db.delete(old)
    filing = EsefFiling(lei=report.lei, entity_name=report.entity_name, period_end=report.period_end, source=source,
                        source_ref=source_ref[:500], viewer_url=viewer_url[:500], sha256=sha, fact_count=len(report.facts))
    db.add(filing)
    db.flush()
    db.bulk_insert_mappings(EsefFact, [dict(filing_id=filing.id, lei=report.lei, **f) for f in report.facts])
    return filing, True


def link_security(db: Session, lei: str, ticker: str, name: str, exchange: str | None) -> Security:
    """Create (or update) the security that represents this issuer in search, watchlists and company pages."""
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 20 or not all(c.isalnum() or c in ".-:" for c in ticker):
        raise EsefError("Ticker may contain letters, digits, '.', '-' or ':' (max 20).")
    sec = db.scalar(select(Security).where(Security.ticker == ticker))
    if sec and sec.lei not in (None, lei):
        raise EsefError(f"Ticker {ticker} is already used by another company.")
    if sec and sec.cik:
        raise EsefError(f"Ticker {ticker} is an SEC-registered security; choose a different symbol (e.g. with an exchange suffix).")
    other = db.scalar(select(Security).where(Security.lei == lei, Security.ticker != ticker))
    if other:
        raise EsefError(f"This company is already linked to ticker {other.ticker}.")
    if sec is None:
        sec = Security(ticker=ticker, name=name[:255] or ticker, cik=None, lei=lei, exchange=exchange or None, source="esef", is_listed=True)
        db.add(sec)
    else:
        sec.lei, sec.name, sec.exchange, sec.source = lei, name[:255] or sec.name, exchange or sec.exchange, "esef"
    return sec


# ------------------------------------------------------------------ facts for statements
def facts_for(db: Session, lei: str) -> list[SimpleNamespace]:
    """ESEF facts shaped like SEC facts so the same statement builder applies.

    The report's period end acts as the "filed" date: a later report's restated comparatives
    win over the original figures, mirroring the SEC "latest filing wins" rule.
    """
    filings = {f.id: f for f in db.scalars(select(EsefFiling).where(EsefFiling.lei == lei))}
    out = []
    for f in db.scalars(select(EsefFact).where(EsefFact.lei == lei)):
        fl = filings.get(f.filing_id)
        if fl is None:
            continue
        out.append(SimpleNamespace(
            taxonomy=f.taxonomy, concept=f.concept, unit=f.unit, start=f.start, end=f.end, value=f.value,
            accession=f"ESEF-{fl.id}", fy=fl.period_end.year, fp="FY", form="ESEF", filed=fl.period_end, frame="",
        ))
    return out


# ------------------------------------------------------------------ filings.xbrl.org (optional)
def _abs(url: str) -> str:
    if not url:
        return ""
    return url if url.startswith(("https://", "http://")) else f"{FXO_BASE}/{url.lstrip('/')}"


def fxo_filings(lei: str) -> list[dict]:
    """List a company's ESEF filings on filings.xbrl.org (JSON:API). Field names per the public docs."""
    params = {"filter[entity.identifier]": lei, "include": "entity", "page[size]": "50"}
    try:
        with client_factory() as c:
            r = c.get(f"{FXO_BASE}/api/filings", params=params, headers={"Accept": "application/vnd.api+json"})
    except httpx.HTTPError as exc:
        raise EsefError(f"filings.xbrl.org is not reachable ({exc.__class__.__name__}).") from exc
    if r.status_code != 200:
        raise EsefError(f"filings.xbrl.org returned HTTP {r.status_code}.")
    try:
        data = r.json().get("data") or []
    except ValueError as exc:
        raise EsefError("Unexpected response from filings.xbrl.org.") from exc
    out = []
    for item in data:
        a = item.get("attributes") or {}
        pe = a.get("period_end") or a.get("last_end_date") or ""
        try:
            period_end = date.fromisoformat(str(pe)[:10])
        except ValueError:
            continue
        out.append({"id": str(item.get("id", "")), "period_end": period_end, "json_url": _abs(a.get("json_url") or ""),
                    "viewer_url": _abs(a.get("viewer_url") or ""), "package_url": _abs(a.get("package_url") or ""),
                    "errors": a.get("error_count")})
    out.sort(key=lambda x: x["period_end"], reverse=True)
    return out


def fxo_import(db: Session, lei: str, max_reports: int = 5) -> list[tuple[EsefFiling, bool]]:
    """Import the latest reports of an issuer from filings.xbrl.org (xBRL-JSON)."""
    listing = [f for f in fxo_filings(lei) if f["json_url"]]
    if not listing:
        raise EsefError("No ESEF filings with xBRL-JSON found on filings.xbrl.org for this LEI.")
    # One report per period end (the first listed is kept).
    seen, chosen = set(), []
    for f in listing:
        if f["period_end"] not in seen:
            seen.add(f["period_end"])
            chosen.append(f)
    results = []
    for f in chosen[:max_reports]:
        try:
            with client_factory() as c:
                r = c.get(f["json_url"])
        except httpx.HTTPError as exc:
            raise EsefError(f"Download failed ({exc.__class__.__name__}).") from exc
        if r.status_code != 200 or len(r.content) > MAX_PACKAGE_BYTES:
            raise EsefError(f"Could not download {f['json_url']} (HTTP {r.status_code}).")
        try:
            report = parse_xbrl_json(r.json())
        except ValueError as exc:
            raise EsefError(f"Invalid xBRL-JSON at {f['json_url']}") from exc
        if report.lei != lei:
            raise EsefError(f"Report at {f['json_url']} belongs to a different LEI ({report.lei}).")
        results.append(store(db, report, "filings.xbrl.org", f["json_url"], r.content, f["viewer_url"]))
    db.commit()
    return results
