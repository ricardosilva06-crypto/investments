import json
from decimal import Decimal

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db
from app.models import Security
from app.services import analyst, llm, sec_client

from .conftest import HDR, login, make_user
from .fixtures import CIK, COMPANYFACTS, SUBMISSIONS


def make_pdf(pages: list[str]) -> bytes:
    d = pymupdf.open()
    for t in pages:
        p = d.new_page()
        p.insert_textbox(pymupdf.Rect(50, 50, 550, 800), t, fontsize=10)
    return d.tobytes()


ANSWER = """## Verified data
- Revenue was USD 1,200 in the latest fiscal year [F1], up from 1,010 [F1].
- Net income was 120 [F1].
- The company expects 777 new stores [D1].
## Calculations
- Growth = 1,200 / 1,010 − 1 = 18.8% [C1]
## Assumptions
- None
## Opinion
- Solid growth, but verify the 999 figure.
"""


class FakeOllama:
    def __init__(self, models=("llama3.1:8b", "nomic-embed-text:latest"), answer=ANSWER):
        self.models, self.answer, self.requests = models, answer, []

    def handler(self, request: httpx.Request):
        self.requests.append(request)
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m, "size": 1, "details": {"family": "llama"}} for m in self.models]})
        if path == "/api/embed":
            body = json.loads(request.content)
            vecs = []
            for t in body["input"]:
                t = t.lower()
                vecs.append([t.count("store") + 0.1, t.count("risk") + 0.1, t.count("revenue") + 0.1, 0.1])
            return httpx.Response(200, json={"embeddings": vecs})
        if path == "/api/chat":
            body = json.loads(request.content)
            assert body["stream"] is True and body["messages"][0]["role"] == "system"
            words = self.answer.split(" ")
            lines = [json.dumps({"message": {"role": "assistant", "content": w + " "}, "done": False}) for w in words]
            lines.append(json.dumps({"done": True}))
            return httpx.Response(200, text="\n".join(lines))
        return httpx.Response(404)


@pytest.fixture()
def ollama(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(llm, "client_factory", lambda timeout: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    return fake


@pytest.fixture()
def company(app_env, monkeypatch):
    s = db.session_factory()()
    s.add(Security(ticker="EXMP", name="EXAMPLE CORP", cik=CIK, exchange="Nasdaq", source="test"))
    s.commit()
    s.close()
    monkeypatch.setattr(sec_client, "_MIN_INTERVAL", 0)
    monkeypatch.setattr(sec_client, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=COMPANYFACTS if "companyfacts" in r.url.path else SUBMISSIONS))))


def parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_status_unavailable_does_not_break_app(admin_client):
    s = admin_client.get("/api/ai/status").json()
    assert s["available"] is False and "not reachable" in s["message"]
    r = admin_client.post("/api/ai/chat", json={"message": "hi"}, headers=HDR)
    assert r.status_code == 503 and "Ollama" in r.json()["detail"]
    assert admin_client.get("/api/dashboard").status_code == 200


def test_status_and_model_selection(admin_client, ollama):
    s = admin_client.get("/api/ai/status").json()
    assert s["available"] and s["chat_model"] == "llama3.1:8b" and s["embed_model"] == "nomic-embed-text:latest"
    assert {m["name"]: m["embedding"] for m in s["models"]}["nomic-embed-text:latest"] is True
    s = admin_client.put("/api/ai/settings", json={"chat_model": "missing-model", "embed_model": "", "temperature": "0.5"}, headers=HDR).json()
    assert s["chat_model"] == "llama3.1:8b"  # unknown choice falls back to an installed model
    assert s["chosen_chat_model"] == "missing-model"


def test_document_upload_index_and_privacy(admin_client, ollama, app_env):
    pdf = make_pdf(["Annual report 2024. Revenue grew strongly. " * 20, "Store expansion: we plan 777 new stores next year. " * 20,
                    "Risk factors: competition and currency risk. " * 20])
    r = admin_client.post("/api/documents", files={"file": ("report.pdf", pdf, "application/pdf")}, data={"title": "Annual report"}, headers=HDR)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["pages"] == 3
    d = admin_client.get(f"/api/documents/{doc['id']}").json()
    assert d["status"] == "ready" and d["embed_model"] == "nomic-embed-text:latest"
    f = admin_client.get(f"/api/documents/{doc['id']}/file")
    assert f.status_code == 200 and f.content.startswith(b"%PDF")

    from app.main import app

    make_user("mallory")
    with TestClient(app) as m:
        login(m, "mallory")
        assert m.get(f"/api/documents/{doc['id']}").status_code == 404
        assert m.get(f"/api/documents/{doc['id']}/file").status_code == 404
        assert m.get("/api/documents").json() == []

    bad = admin_client.post("/api/documents", files={"file": ("x.pdf", b"not a pdf at all", "application/pdf")}, headers=HDR)
    assert bad.status_code == 422
    scanned = admin_client.post("/api/documents", files={"file": ("s.pdf", make_pdf([""]), "application/pdf")}, headers=HDR)
    assert scanned.status_code == 422 and "No extractable text" in scanned.json()["detail"]  # blank page, no image
    assert admin_client.delete(f"/api/documents/{doc['id']}", headers=HDR).status_code == 204
    assert admin_client.get("/api/documents").json() == []


def test_hybrid_search_finds_relevant_page(admin_client, ollama):
    pdf = make_pdf(["General introduction about the company history. " * 20, "Store expansion: we plan 777 new stores next year. " * 20,
                    "Risk factors: competition and currency risk. " * 20])
    doc_id = admin_client.post("/api/documents", files={"file": ("r.pdf", pdf, "application/pdf")}, headers=HDR).json()["id"]
    from app.models import Document
    from app.services import documents as docsvc

    s = db.session_factory()()
    d = s.get(Document, doc_id)
    hits = docsvc.search(s, [d], "How many new stores are planned?", k=3, embed_model="nomic-embed-text:latest")
    assert hits[0].page == 2
    hits_kw = docsvc.search(s, [d], "currency risk", k=3, embed_model=None)
    assert hits_kw[0].page == 3
    s.close()


def test_grounded_chat_with_sources_and_verification(admin_client, ollama, company):
    admin_client.get("/api/companies/EXMP")  # downloads SEC data (mocked)
    pdf = make_pdf(["Store expansion: we plan 777 new stores next year. " * 20])
    doc_id = admin_client.post("/api/documents", files={"file": ("r.pdf", pdf, "application/pdf")}, data={"ticker": "EXMP"}, headers=HDR).json()["id"]
    r = admin_client.post("/api/ai/chat", json={"task": "company_analysis", "tickers": ["exmp"], "document_ids": [doc_id], "message": ""}, headers=HDR)
    assert r.status_code == 200, r.text
    events = parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "token" in kinds
    meta = events[0][1]
    ids = {s["id"] for s in meta["sources"]}
    assert {"S1", "F1", "C1", "D1"} <= ids
    # The prompt sent to the model contains the SEC figures and the rules.
    chat_req = next(q for q in ollama.requests if q.url.path == "/api/chat")
    body = json.loads(chat_req.content)
    prompt = body["messages"][-1]["content"]
    assert "SOURCES:" in prompt and "Revenue" in prompt and "0.0012" not in prompt
    assert "Never invent" in body["messages"][0]["content"]
    done = events[-1][1]
    v = done["verification"]
    assert v["has_structure"] is True
    assert v["unmatched_verified"] == []  # 1,200 / 1,010 / 120 / 777 all appear in sources
    assert "999" in v["unmatched_other"]  # number not in any source is flagged
    conv = admin_client.get(f"/api/ai/conversations/{meta['conversation_id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["model"] == "llama3.1:8b" and conv["messages"][1]["sources"]

    # Follow-up inherits the company and documents.
    r2 = admin_client.post("/api/ai/chat", json={"conversation_id": meta["conversation_id"], "message": "And the risks?"}, headers=HDR)
    m2 = parse_sse(r2.text)[0][1]
    assert any(s["id"] == "F1" for s in m2["sources"])
    chat_req2 = [q for q in ollama.requests if q.url.path == "/api/chat"][-1]
    msgs = json.loads(chat_req2.content)["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]

    # Save as thesis note with provenance footer.
    note = admin_client.post(f"/api/ai/messages/{done['message_id']}/save-note", json={}, headers=HDR).json()
    n = admin_client.get(f"/api/notes/{note['note_id']}").json()
    assert n["security"]["ticker"] == "EXMP" and "AI-generated by local model llama3.1:8b" in n["body"] and "[F1]" in n["body"]


def test_chat_validation_and_isolation(admin_client, ollama, company):
    assert admin_client.post("/api/ai/chat", json={"task": "bull_bear"}, headers=HDR).status_code == 422
    assert admin_client.post("/api/ai/chat", json={"task": "compare", "tickers": ["EXMP"]}, headers=HDR).status_code == 422
    assert admin_client.post("/api/ai/chat", json={"task": "nope", "message": "x"}, headers=HDR).status_code == 422
    r = admin_client.post("/api/ai/chat", json={"message": "hello"}, headers=HDR)
    cid = parse_sse(r.text)[0][1]["conversation_id"]
    from app.main import app

    make_user("mallory")
    with TestClient(app) as m:
        login(m, "mallory")
        m.get("/api/ai/status")
        assert m.get(f"/api/ai/conversations/{cid}").status_code == 404
        assert m.post("/api/ai/chat", json={"conversation_id": cid, "message": "x"}, headers=HDR).status_code == 404
        assert m.get("/api/ai/conversations").json() == []


def test_missing_price_and_financials_are_stated(admin_client, ollama, app_env):
    s = db.session_factory()()
    s.add(Security(ticker="NOFA", name="NO FACTS INC", cik=None, exchange="NYSE", source="test"))
    s.commit()
    s.close()
    r = admin_client.post("/api/ai/chat", json={"task": "valuation", "tickers": ["NOFA"]}, headers=HDR)
    meta = parse_sse(r.text)[0][1]
    assert any("No financial statements" in w for w in meta["warnings"])
    prompt = json.loads([q for q in ollama.requests if q.url.path == "/api/chat"][-1].content)["messages"][-1]["content"]
    assert "Do not state a share price" in prompt and "Do not state its financial figures" in prompt


def test_portfolio_context(admin_client, ollama):
    p = admin_client.post("/api/portfolios", json={"name": "Core"}, headers=HDR).json()
    admin_client.post(f"/api/portfolios/{p['id']}/transactions", json={"symbol": "ASML.AS", "currency": "EUR", "kind": "buy",
                      "trade_date": "2024-01-02", "quantity": "3", "price": "600"}, headers=HDR)
    r = admin_client.post("/api/ai/chat", json={"task": "portfolio"}, headers=HDR)
    meta = parse_sse(r.text)[0][1]
    assert any(s["kind"] == "portfolio" for s in meta["sources"])
    prompt = json.loads([q for q in ollama.requests if q.url.path == "/api/chat"][-1].content)["messages"][-1]["content"]
    assert "ASML.AS | EUR | 3 | 1800.00" in prompt


def test_verify_numbers_unit_handling():
    vals = [Decimal("391035000000"), Decimal("0.2397"), Decimal("6.08")]
    ans = "## Verified data\n- Revenue USD 391.0 billion [F1]; margin 24.0% [C1]; EPS $6.08 [F1]; 2024 results; 3 segments\n## Opinion\n- Fine."
    v = analyst.verify_numbers(ans, vals)
    assert v["unmatched_verified"] == [] and v["checked"] == 3
    v2 = analyst.verify_numbers("## Verified data\n- Revenue USD 450 billion [F1]", vals)
    assert v2["unmatched_verified"] == ["450 billion"] and v2["has_structure"] is False
