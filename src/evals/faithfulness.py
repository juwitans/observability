"""evals/faithfulness.py — online LLM-as-judge on chat answers.

Runs as a `faithfulness_eval` generation inside each chat turn and emits two
scores: `faithfulness` and `answer_relevance`. This is the hallucination detector.
"""
from __future__ import annotations

from .. import llm, obs, prompts
from ..schemas import ChatChunk, FaithfulnessVerdict


def _format_context(chunks: list[ChatChunk]) -> str:
    if not chunks:
        return "(no context retrieved)"
    return "\n\n".join(f"[{c.slug}] {c.title}\n{c.text[:1500]}" for c in chunks)


def judge_faithfulness(
    question: str, context: str, answer: str, name: str = "faithfulness_eval"
) -> FaithfulnessVerdict:
    """Pure judge: runs the LLM-as-judge generation, returns a verdict.

    Does NOT emit scores — used both by the online eval (which then emits) and by
    the offline experiment evaluator (which returns Evaluation objects instead).
    """
    prompt = prompts.managed("faithfulness_judge", prompts.FAITHFULNESS_JUDGE)
    content = prompt.compile(question=question, context=context, answer=answer)
    return llm.llm_json(
        [{"role": "user", "content": content}],
        FaithfulnessVerdict,
        name=name,
        model=llm.judge_model(),
        prompt=prompt,
    )


def faithfulness_eval(
    question: str, chunks: list[ChatChunk], answer: str
) -> FaithfulnessVerdict:
    verdict = judge_faithfulness(question, _format_context(chunks), answer)
    obs.score_span(
        "faithfulness",
        verdict.faithfulness,
        data_type="NUMERIC",
        comment=verdict.reasoning[:500],
    )
    obs.score_span(
        "answer_relevance",
        verdict.answer_relevance,
        data_type="NUMERIC",
    )
    if verdict.faithfulness < 0.6:
        obs.update_generation(
            level="WARNING",
            status_message=f"Low faithfulness ({verdict.faithfulness:.2f}) — possible hallucination",
        )
    return verdict
