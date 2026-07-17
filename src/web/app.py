"""Minimal FastAPI chat front end for the demo.

Serves a single HTML page and a /api/chat endpoint that runs one `chat_turn`
(retrieve -> answer -> faithfulness eval) and returns the answer, citations,
scores, and deep links into the Langfuse trace + session — so during a demo you
can click straight from an answer to its trace.

Run:  python -m scripts.serve     (or: uvicorn src.web.app:app --reload)
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import obs, store
from ..chat.answer import chat_turn

app = FastAPI(title="LLM Wiki — Observability Demo")

_HTML = (Path(__file__).parent / "static" / "chat.html").read_text(encoding="utf-8")


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    variant: str = "v1"  # v1 | v2 | weak


def _estimate_cost(tokens_in: int, tokens_out: int) -> float | None:
    """Cost in USD from real token counts, if per-1M pricing is configured.

    Set LLM_PRICE_IN / LLM_PRICE_OUT (USD per 1M tokens) in .env to show cost;
    unset means we return None rather than invent a number.
    """
    price_in = os.environ.get("LLM_PRICE_IN")
    price_out = os.environ.get("LLM_PRICE_OUT")
    if price_in is None and price_out is None:
        return None
    try:
        pin = float(price_in or 0)
        pout = float(price_out or 0)
    except ValueError:
        return None
    return round(tokens_in / 1_000_000 * pin + tokens_out / 1_000_000 * pout, 6)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _HTML


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/info")
def info() -> dict:
    """Corpus size for the UI header ("grounded in N wiki docs")."""
    try:
        doc_count = len(store.load_pages())
    except Exception:
        doc_count = 0
    return {"doc_count": doc_count}


def _serialize_detectors(verdicts: dict) -> dict:
    """Flatten {name: DetectorVerdict} -> {name: {fired, comment}} for the UI."""
    return {name: {"fired": v.fired, "comment": v.comment} for name, v in verdicts.items()}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    session_id = req.session_id or f"web-{uuid.uuid4().hex[:8]}"
    result = chat_turn(
        req.question,
        session_id=session_id,
        user_id="web-demo",
        variant=req.variant,
    )
    obs.flush()
    latency_ms = sum(s["ms"] for s in result.spans)
    return {
        "session_id": session_id,
        "answer": result.answer.answer,
        "cited_slugs": result.answer.cited_slugs,
        "faithfulness": round(result.faithfulness.faithfulness, 2),
        "answer_relevance": round(result.faithfulness.answer_relevance, 2),
        "retrieved": [
            {"slug": c.slug, "title": c.title, "score": round(c.score, 3)}
            for c in result.chunks
        ],
        "spans": result.spans,
        "latency_ms": latency_ms,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": _estimate_cost(result.tokens_in, result.tokens_out),
        "model": result.model,
        "variant": req.variant,
        "trace_id": result.trace_id,
        "trace_url": obs.trace_url(result.trace_id),
        "session_url": obs.session_url(session_id),
        # Event detectors (EVAL_STANDARD §3). `detectors` are about THIS turn's
        # message; `prior_detectors` are about the PREVIOUS answer (the UI annotates
        # the earlier bubble with them).
        "detectors": _serialize_detectors(result.detectors),
        "prior_detectors": _serialize_detectors(result.prior_detectors),
    }
