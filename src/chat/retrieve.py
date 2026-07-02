"""chat: retrieve_context (span) — query-time retrieval over wiki/.

Logs retrieved wiki chunks WITH page IDs (capture rule, §4.3).
"""
from __future__ import annotations

from .. import obs, retrieval
from ..schemas import ChatChunk


def retrieve_context(query: str, top_k: int = 3) -> list[ChatChunk]:
    with obs.span(
        "retrieve_context",
        input={"query": query, "top_k": top_k},
        # Identify the grounding source on the RAG span (OTel GenAI convention;
        # OBSERVABILITY_INSTRUMENTATION.md §1/§2 "Retrieval / RAG span").
        metadata={"gen_ai.data_source.id": "wiki"},
    ):
        hits = retrieval.search(query, top_k=top_k)
        chunks = [ChatChunk(**h) for h in hits]
        obs.update_span(
            output={
                "chunks": [
                    {"slug": c.slug, "title": c.title, "score": c.score, "text": c.text}
                    for c in chunks
                ],
                "count": len(chunks),
            }
        )
        return chunks
