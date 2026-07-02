"""ingest.py — orchestrates ONE trace per source.

Root span `ingest_source` with children, in order:
  fetch_source -> extract_md -> retrieve_related -> write_page -> judge_page
  -> lint_links -> [repair_page -> judge_page -> lint_links] x up to MAX_REPAIRS

The repair loop firing is the demo's debugging story: low judge score / lint
WARNING -> repair runs -> re-judge passes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import obs, store
from ..schemas import JudgeVerdict, LintResult, WikiPage
from .evaluate import judge_page
from .extract import extract_md
from .fetch import fetch_source
from .lint import lint_links
from .repair import repair_page
from .retrieve import retrieve_related
from .write import write_page

MAX_REPAIRS = 2


@dataclass
class IngestOutcome:
    url: str
    slug: str | None
    saved: bool
    repairs: int
    final_groundedness: float | None
    final_faithful: bool | None
    lint_passed: bool | None
    error: str | None = None


def _needs_repair(verdict: JudgeVerdict, lint: LintResult) -> bool:
    return (not verdict.faithful) or verdict.groundedness < 0.7 or (not lint.passed)


def ingest_source(url: str, topic: str) -> IngestOutcome:
    with obs.span("ingest_source", input={"url": url, "topic": topic}) as root:
        try:
            fetched = fetch_source(url)
            extracted = extract_md(url, fetched.html)

            # Retrieve related pages using the source text as the query.
            retrieved = retrieve_related(
                query=extracted.markdown[:2000], top_k=3
            )

            page: WikiPage = write_page(extracted, retrieved, topic=topic)
            store.save_raw(page.slug, extracted.markdown)

            known = store.all_slugs()
            verdict = judge_page(page, extracted)
            lint = lint_links(page, known_slugs=known)

            repairs = 0
            while _needs_repair(verdict, lint) and repairs < MAX_REPAIRS:
                repairs += 1
                obs.update_span(
                    metadata={"wiki.repair.round": repairs},  # private namespace, §6
                    level="WARNING",
                    status_message=f"Repair round {repairs} triggered",
                )
                page = repair_page(page, extracted, verdict, lint)
                verdict = judge_page(page, extracted)
                lint = lint_links(page, known_slugs=known)

            path = store.save_page(page)
            store.rebuild_index()

            outcome = IngestOutcome(
                url=url,
                slug=page.slug,
                saved=True,
                repairs=repairs,
                final_groundedness=verdict.groundedness,
                final_faithful=verdict.faithful,
                lint_passed=lint.passed,
            )
            obs.update_span(
                output={
                    "slug": page.slug,
                    "path": str(path.relative_to(store.ROOT)),
                    "repairs": repairs,
                    "groundedness": verdict.groundedness,
                    "faithful": verdict.faithful,
                    "lint_passed": lint.passed,
                }
            )
            if _needs_repair(verdict, lint):
                obs.update_span(
                    level="WARNING",
                    status_message="Saved but still flagged after max repair rounds",
                )
            return outcome

        except Exception as e:  # let the span record ERROR + stack trace
            obs.update_span(level="ERROR", status_message=f"{type(e).__name__}: {e}")
            return IngestOutcome(
                url=url,
                slug=None,
                saved=False,
                repairs=0,
                final_groundedness=None,
                final_faithful=None,
                lint_passed=None,
                error=str(e),
            )
