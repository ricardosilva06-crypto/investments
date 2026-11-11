"""ESEF (EU annual reports) import: upload a report package or fetch from filings.xbrl.org."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import EsefFact, EsefFiling, Security, User
from ..services import esef

router = APIRouter(prefix="/api", tags=["esef"])


class EsefFilingOut(BaseModel):
    id: int
    lei: str
    entity_name: str
    period_end: date
    source: str
    source_ref: str
    viewer_url: str
    fact_count: int
    imported_at: datetime


class EsefCompanyOut(BaseModel):
    lei: str
    entity_name: str
    ticker: str | None
    exchange: str | None
    reports: list[EsefFilingOut]


def _filing_out(f: EsefFiling) -> EsefFilingOut:
    return EsefFilingOut(id=f.id, lei=f.lei, entity_name=f.entity_name, period_end=f.period_end, source=f.source,
                         source_ref=f.source_ref, viewer_url=f.viewer_url, fact_count=f.fact_count, imported_at=f.imported_at)


@router.get("/esef/companies", response_model=list[EsefCompanyOut])
def companies(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    by_lei: dict[str, list[EsefFiling]] = {}
    for f in db.scalars(select(EsefFiling).order_by(EsefFiling.period_end.desc())):
        by_lei.setdefault(f.lei, []).append(f)
    secs = {s.lei: s for s in db.scalars(select(Security).where(Security.lei.in_(by_lei)))} if by_lei else {}
    out = []
    for lei, fl in by_lei.items():
        s = secs.get(lei)
        out.append(EsefCompanyOut(lei=lei, entity_name=next((f.entity_name for f in fl if f.entity_name), ""),
                                  ticker=s.ticker if s else None, exchange=s.exchange if s else None,
                                  reports=[_filing_out(f) for f in fl]))
    return sorted(out, key=lambda c: (c.ticker is None, c.entity_name or c.lei))


class UploadResult(BaseModel):
    filing: EsefFilingOut
    created: bool
    facts: int
    skipped_dimensional: int
    skipped_other: int
    linked_ticker: str | None


@router.post("/admin/esef/upload", response_model=UploadResult, status_code=201)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    data = await file.read(esef.MAX_PACKAGE_BYTES + 1)
    try:
        docs = esef.read_package(data, file.filename or "")
        report = esef.parse_ixbrl(docs)
        filing, created = esef.store(db, report, "upload", file.filename or "upload", data)
    except esef.EsefError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    db.commit()
    sec = db.scalar(select(Security).where(Security.lei == report.lei))
    return UploadResult(filing=_filing_out(filing), created=created, facts=len(report.facts),
                        skipped_dimensional=report.skipped_dimensional, skipped_other=report.skipped_other,
                        linked_ticker=sec.ticker if sec else None)


class LinkIn(BaseModel):
    lei: str = Field(min_length=20, max_length=20)
    ticker: str = Field(min_length=1, max_length=20)
    name: str = Field("", max_length=255)
    exchange: str | None = Field(None, max_length=32)


@router.post("/admin/esef/link")
def link(data: LinkIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    lei = data.lei.strip().upper()
    if not esef.valid_lei(lei):
        raise HTTPException(422, "Invalid LEI (check digits do not match).")
    if not db.scalar(select(func.count()).select_from(EsefFiling).where(EsefFiling.lei == lei)):
        raise HTTPException(404, "Import at least one report for this LEI first.")
    name = data.name.strip() or db.scalar(select(EsefFiling.entity_name).where(EsefFiling.lei == lei, EsefFiling.entity_name != "")) or ""
    try:
        sec = esef.link_security(db, lei, data.ticker, name, (data.exchange or "").strip() or None)
    except esef.EsefError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    db.commit()
    return {"ticker": sec.ticker, "lei": lei, "name": sec.name}


class FetchIn(BaseModel):
    lei: str = Field(min_length=20, max_length=20)
    max_reports: int = Field(5, ge=1, le=10)


@router.post("/admin/esef/fetch")
def fetch(data: FetchIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    lei = data.lei.strip().upper()
    if not esef.valid_lei(lei):
        raise HTTPException(422, "Invalid LEI (check digits do not match).")
    try:
        results = esef.fxo_import(db, lei, data.max_reports)
    except esef.EsefError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    sec = db.scalar(select(Security).where(Security.lei == lei))
    return {"imported": sum(1 for _, c in results if c), "already_present": sum(1 for _, c in results if not c),
            "reports": [_filing_out(f).model_dump() for f, _ in results], "linked_ticker": sec.ticker if sec else None}


@router.delete("/admin/esef/filings/{filing_id}", status_code=204)
def delete_filing(filing_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    f = db.get(EsefFiling, filing_id)
    if f is None:
        raise HTTPException(404, "Report not found")
    db.execute(delete(EsefFact).where(EsefFact.filing_id == f.id))
    db.delete(f)
    db.commit()
