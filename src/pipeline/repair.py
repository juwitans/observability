"""stage: repair_page (generation, conditional) — fix flagged problems."""
from __future__ import annotations

from .. import llm, prompts, store
from ..schemas import ExtractResult, JudgeVerdict, LintResult, WikiPage


def repair_page(
    page: WikiPage,
    extracted: ExtractResult,
    verdict: JudgeVerdict,
    lint: LintResult,
) -> WikiPage:
    prompt = prompts.managed("repair_page", prompts.REPAIR_PAGE)
    content = prompt.compile(
        source=extracted.markdown[:12000],
        draft=page.markdown[:12000],
        verdict=f"groundedness={verdict.groundedness}, faithful={verdict.faithful}, issues={verdict.issues}",
        lint=str(lint.issues),
    )
    repaired = llm.llm_json(
        [{"role": "user", "content": content}],
        WikiPage,
        name="repair_page",
        prompt=prompt,
    )
    # Preserve identity + the true citation list from the original page.
    repaired.topic = page.topic
    repaired.slug = page.slug
    repaired.citations = list(page.citations)
    return repaired
