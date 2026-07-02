"""stage: extract_md (span) — HTML -> clean markdown.

Primary extractor is trafilatura. Some pages (e.g. sematext's glossary) return a
full HTML body that trafilatura's main-content heuristic still scores as empty —
so we fall back to a lenient lxml pass that pulls <p>/<li>/<h*> text. The span
records which extractor won (`extractor` metadata) so the meta layer shows it.
"""
from __future__ import annotations

import trafilatura
from lxml import html as lhtml

from .. import obs
from ..schemas import ExtractResult

# Minimum body we consider a "real" extraction; below this we try the fallback.
_MIN_CHARS = 400


def _trafilatura_md(html: str) -> str:
    return (
        trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        or ""
    )


def _lxml_fallback(html: str) -> str:
    """Lenient content extraction for pages trafilatura can't parse."""
    try:
        doc = lhtml.fromstring(html)
    except Exception:
        return ""
    for bad in doc.xpath("//script|//style|//nav|//footer|//header|//aside|//form|//noscript"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)

    parts: list[str] = []
    # Prefer the main/article region.
    nodes = doc.xpath("//main//p|//main//li|//main//h2|//main//h3|//article//p|//article//li|//article//h2|//article//h3")
    if not nodes:
        nodes = doc.xpath("//p|//li|//h2|//h3")
    for el in nodes:
        text = el.text_content().strip()
        if len(text) > 30:
            tag = el.tag.lower()
            parts.append(f"## {text}" if tag in {"h2", "h3"} else text)
    return "\n\n".join(parts)


def extract_md(url: str, html: str) -> ExtractResult:
    with obs.span(
        "extract_md", input={"url": url, "html_bytes": len(html.encode("utf-8", "ignore"))}
    ):
        markdown = _trafilatura_md(html)
        extractor = "trafilatura"

        if len(markdown) < _MIN_CHARS:
            fallback = _lxml_fallback(html)
            if len(fallback) > len(markdown):
                markdown, extractor = fallback, "lxml_fallback"

        result = ExtractResult(url=url, markdown=markdown, char_length=len(markdown))
        obs.update_span(
            output={"char_length": len(markdown), "preview": markdown[:500]},
            metadata={"wiki.extract.extractor": extractor},  # private namespace, §6
        )
        if len(markdown) < _MIN_CHARS:
            obs.update_span(
                level="WARNING",
                status_message=f"Thin extraction ({len(markdown)} chars) after fallback — page may be JS-rendered or blocked",
            )
        return result
