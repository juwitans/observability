"""stage: retrieve_related (span) — find existing wiki pages related to a draft.

Logs the ACTUAL retrieved text and page IDs (capture rule, §4.3) so a bad
cross-link or a missed merge can be diagnosed from the trace alone.
"""
from __future__ import annotations

from .. import obs, retrieval
from ..schemas import RelatedPage, RetrieveResult


def retrieve_related(
    query: str, top_k: int = 3, exclude_slug: str | None = None
) -> RetrieveResult:
    with obs.span(
        "retrieve_related",
        input={"query": query[:500], "top_k": top_k},
        # Identify the grounding source on the RAG span (OTel GenAI convention;
        # OBSERVABILITY_INSTRUMENTATION.md §1/§2 "Retrieval / RAG span").
        metadata={"gen_ai.data_source.id": "wiki"},
    ):
        hits = retrieval.search(query, top_k=top_k, exclude_slug=exclude_slug)
        related = [RelatedPage(**h) for h in hits]
        obs.update_span(
            output={
                "related": [
                    {"slug": r.slug, "title": r.title, "score": r.score, "text": r.text}
                    for r in related
                ],
                "count": len(related),
            }
        )
        return RetrieveResult(related=related)
