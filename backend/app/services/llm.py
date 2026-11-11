"""Model abstraction layer for the AI analyst.

Only local, open-source inference is implemented (Ollama). Another backend
(e.g. llama.cpp's server, vLLM, LM Studio) can be added by implementing
``LLMProvider``. No paid API is used, and no API key is needed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import get_settings


class LLMUnavailable(RuntimeError):
    """The local model server cannot be reached or the model is missing."""


@dataclass
class ModelInfo:
    name: str
    size_bytes: int | None
    family: str
    parameter_size: str
    quantization: str
    embedding: bool  # heuristic: model looks like an embedding model


class LLMProvider(Protocol):
    name: str

    def list_models(self) -> list[ModelInfo]: ...

    def chat_stream(self, model: str, messages: list[dict], *, temperature: float, num_ctx: int) -> Iterator[str]: ...

    def embed(self, model: str, texts: list[str]) -> list[list[float]]: ...


EMBED_HINTS = ("embed", "bge", "e5-", "minilm", "gte-", "nomic", "arctic-embed", "mxbai")

# Tests replace this factory with one using httpx.MockTransport.
client_factory = lambda timeout: httpx.Client(timeout=timeout)  # noqa: E731


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        s = get_settings()
        self.base_url = (base_url or s.ollama_url).rstrip("/")
        self.timeout = timeout or s.ollama_timeout_seconds

    def _err(self, exc: Exception) -> LLMUnavailable:
        return LLMUnavailable(
            f"The local AI server (Ollama at {self.base_url}) is not reachable ({exc.__class__.__name__}). "
            "Start Ollama on the server to use the AI analyst. Everything else keeps working."
        )

    def list_models(self) -> list[ModelInfo]:
        try:
            with client_factory(5) as c:
                r = c.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._err(exc) from exc
        out = []
        for m in data.get("models", []):
            name = m.get("name") or m.get("model") or ""
            d = m.get("details") or {}
            fam = (d.get("family") or "").lower()
            out.append(
                ModelInfo(
                    name=name,
                    size_bytes=m.get("size"),
                    family=d.get("family") or "",
                    parameter_size=d.get("parameter_size") or "",
                    quantization=d.get("quantization_level") or "",
                    embedding=any(h in name.lower() for h in EMBED_HINTS) or "bert" in fam,
                )
            )
        return out

    def chat_stream(self, model: str, messages: list[dict], *, temperature: float, num_ctx: int) -> Iterator[str]:
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        try:
            with client_factory(self.timeout) as c, c.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                if r.status_code == 404:
                    raise LLMUnavailable(f"Model “{model}” is not installed in Ollama. Run: ollama pull {model}")
                if r.status_code != 200:
                    r.read()
                    raise LLMUnavailable(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise LLMUnavailable(f"Ollama error: {chunk['error']}")
                    piece = (chunk.get("message") or {}).get("content") or ""
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise self._err(exc) from exc

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        try:
            with client_factory(self.timeout) as c:
                r = c.post(f"{self.base_url}/api/embed", json={"model": model, "input": texts})
                if r.status_code == 404:
                    raise LLMUnavailable(f"Embedding model “{model}” is not installed. Run: ollama pull {model}")
                r.raise_for_status()
                vecs = r.json().get("embeddings")
        except (httpx.HTTPError, ValueError) as exc:
            raise self._err(exc) from exc
        if not isinstance(vecs, list) or len(vecs) != len(texts):
            raise LLMUnavailable("Unexpected embedding response from Ollama")
        return vecs


def get_provider() -> LLMProvider:
    return OllamaProvider()


def resolve_models(chat_pref: str = "", embed_pref: str = "") -> tuple[str | None, str | None, list[ModelInfo]]:
    """Pick chat and embedding models: user choice > server default > first suitable installed."""
    s = get_settings()
    models = get_provider().list_models()
    names = {m.name for m in models}

    def pick(pref: str, default: str, want_embed: bool) -> str | None:
        for cand in (pref, default):
            if cand and (cand in names or f"{cand}:latest" in names):
                return cand if cand in names else f"{cand}:latest"
        if want_embed:
            return next((m.name for m in models if m.embedding), None)
        return next((m.name for m in models if not m.embedding), None)

    return pick(chat_pref, s.ollama_chat_model, False), pick(embed_pref, s.ollama_embed_model, True), models
