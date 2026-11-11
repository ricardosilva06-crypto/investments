"""News from free RSS/Atom feeds chosen by the administrator.

Only headlines, links, dates and a short plain-text excerpt are stored; the full
article stays on the publisher's site (copyright). Feeds are polled at most every
30 minutes with conditional requests (ETag / Last-Modified). Untrusted XML is
parsed with defusedxml (protects against entity-expansion attacks).
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx
from defusedxml import ElementTree as ET
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Feed, NewsItem

MIN_INTERVAL = timedelta(minutes=30)
MAX_BYTES = 3_000_000
KEEP_DAYS = 180
USER_AGENT = "InvestorIntelligence/1.0 (self-hosted RSS reader)"

client_factory = lambda: httpx.Client(timeout=20, follow_redirects=True)  # noqa: E731

SUGGESTED = [
    {"title": "SEC press releases", "url": "https://www.sec.gov/news/pressreleases.rss"},
    {"title": "ECB press releases", "url": "https://www.ecb.europa.eu/rss/press.html"},
    {"title": "Federal Reserve press releases", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
]


class FeedError(RuntimeError):
    pass


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _clean(s: str, limit: int = 400) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(re.sub(r"\s+", " ", s)).strip()
    return s[: limit - 1] + "…" if len(s) > limit else s


def _date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def _safe_link(url: str) -> str:
    url = (url or "").strip()
    return url if url.startswith(("https://", "http://")) else ""


def parse(xml_bytes: bytes) -> tuple[str, list[dict]]:
    """Parse RSS 2.0 or Atom. Returns (feed title, items)."""
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:  # defusedxml raises several types, incl. for forbidden entities
        raise FeedError(f"Not a valid RSS/Atom document ({exc.__class__.__name__})") from exc
    tag = root.tag.split("}")[-1]
    items: list[dict] = []
    if tag == "rss" or root.find("channel") is not None:
        ch = root.find("channel")
        title = _text(ch.find("title")) if ch is not None else ""
        for it in (ch.findall("item") if ch is not None else []):
            link = _safe_link(_text(it.find("link")))
            items.append({
                "guid": (_text(it.find("guid")) or link or _text(it.find("title")))[:500],
                "title": _clean(_text(it.find("title")), 500),
                "link": link,
                "summary": _clean(_text(it.find("description"))),
                "published_at": _date(_text(it.find("pubDate"))),
            })
    elif tag == "feed":
        ns = {"a": "http://www.w3.org/2005/Atom"}
        title = _text(root.find("a:title", ns))
        for e in root.findall("a:entry", ns):
            link_el = next((l for l in e.findall("a:link", ns) if l.get("rel", "alternate") == "alternate"), None)
            link = _safe_link(link_el.get("href") if link_el is not None else "")
            items.append({
                "guid": (_text(e.find("a:id", ns)) or link)[:500],
                "title": _clean(_text(e.find("a:title", ns)), 500),
                "link": link,
                "summary": _clean(_text(e.find("a:summary", ns)) or _text(e.find("a:content", ns))),
                "published_at": _date(_text(e.find("a:updated", ns)) or _text(e.find("a:published", ns))),
            })
    else:
        raise FeedError("Not an RSS or Atom feed")
    return title, [i for i in items if i["title"] and i["guid"]]


def fetch(db: Session, feed: Feed, force: bool = False) -> int:
    """Fetch one feed if due. Returns the number of new items."""
    now = utcnow()
    if not force and feed.last_fetch_at and now - feed.last_fetch_at < MIN_INTERVAL:
        return 0
    feed.last_fetch_at = now
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    if feed.etag:
        headers["If-None-Match"] = feed.etag
    if feed.last_modified:
        headers["If-Modified-Since"] = feed.last_modified
    try:
        with client_factory() as c, c.stream("GET", feed.url, headers=headers) as r:
            if r.status_code == 304:
                feed.status, feed.message = "ok", "Not modified"
                db.commit()
                return 0
            if r.status_code != 200:
                raise FeedError(f"HTTP {r.status_code}")
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FeedError("Feed is larger than 3 MB")
            etag, lm = r.headers.get("etag", ""), r.headers.get("last-modified", "")
        _, items = parse(body)
    except (httpx.HTTPError, FeedError) as exc:
        feed.status, feed.message = "error", str(exc) if isinstance(exc, FeedError) else f"Network error ({exc.__class__.__name__})"
        db.commit()
        return 0
    known = set(db.scalars(select(NewsItem.guid).where(NewsItem.feed_id == feed.id, NewsItem.guid.in_([i["guid"] for i in items]))))
    new = 0
    for i in items:
        if i["guid"] in known:
            continue
        db.add(NewsItem(feed_id=feed.id, **i))
        known.add(i["guid"])
        new += 1
    feed.etag, feed.last_modified = etag[:255], lm[:64]
    feed.status, feed.message = "ok", ""
    db.execute(delete(NewsItem).where(NewsItem.feed_id == feed.id, NewsItem.fetched_at < now - timedelta(days=KEEP_DAYS)))
    db.commit()
    return new


def fetch_all(db: Session) -> int:
    return sum(fetch(db, f) for f in db.scalars(select(Feed)).all())
