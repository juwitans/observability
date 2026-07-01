"""stage: write_page (generation) — draft a compiled wiki page from a source."""
from __future__ import annotations

from .. import llm, prompts, store
from ..schemas import ExtractResult, RetrieveResult, WikiPage


def _format_related(retrieved: RetrieveResult) -> str:
    if not retrieved.related:
        return "(none yet — this may be the first page on its topic)"
    blocks = []
    for r in retrieved.related:
        blocks.append(f"### {r.title} (slug: {r.slug})\n{r.text[:1500]}")
    return "\n\n".join(blocks)


def write_page(
    extracted: ExtractResult,
    retrieved: RetrieveResult,
    topic: str,
    suggested_title: str | None = None,
) -> WikiPage:
    prompt = prompts.managed("write_page", prompts.WRITE_PAGE)
    content = prompt.compile(
        url=extracted.url,
        topic=topic,
        source=extracted.markdown[:12000],
        related=_format_related(retrieved),
    )
    page = llm.llm_json(
        [{"role": "user", "content": content}],
        WikiPage,
        name="write_page",
        prompt=prompt,
    )
    # Normalize slug; keep topic authoritative from sources.yaml.
    page.topic = topic  # type: ignore[assignment]
    page.slug = store.slugify(page.slug or page.title or suggested_title or "page")
    # Citations are the ACTUAL ingested source, not in-article outbound links the
    # model may have copied from the body (those look like hallucinated sourcing).
    page.citations = [extracted.url]
    return page
