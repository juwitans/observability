"""stage: judge_page (generation) — LLM-as-judge; emits groundedness/faithfulness."""
from __future__ import annotations

from .. import llm, obs, prompts
from ..schemas import ExtractResult, JudgeVerdict, WikiPage


def judge_page(page: WikiPage, extracted: ExtractResult) -> JudgeVerdict:
    prompt = prompts.managed("judge_page", prompts.JUDGE_PAGE)
    content = prompt.compile(
        source=extracted.markdown[:12000],
        draft=page.markdown[:12000],
    )
    verdict = llm.llm_json(
        [{"role": "user", "content": content}],
        JudgeVerdict,
        name="judge_page",
        model=llm.judge_model(),
        prompt=prompt,
    )

    # Online scores attached to this generation.
    obs.score_span(
        "groundedness",
        verdict.groundedness,
        data_type="NUMERIC",
        comment=verdict.reasoning[:500],
    )
    obs.score_span(
        "faithfulness",
        1 if verdict.faithful else 0,
        data_type="BOOLEAN",
        comment="; ".join(verdict.issues)[:500],
    )

    if not verdict.faithful or verdict.groundedness < 0.7:
        obs.update_generation(
            level="WARNING",
            status_message=(
                f"Low groundedness ({verdict.groundedness:.2f}) / "
                f"{len(verdict.issues)} issue(s)"
            ),
        )
    return verdict
