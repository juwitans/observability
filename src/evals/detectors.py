"""evals/detectors.py — event detectors (EVAL_STANDARD.md §3).

Binary "did X happen?" judges for the wiki chatbot, distinct from the quality
metrics in faithfulness.py. Each detector is a cheap-judge-model generation with
a managed (versioned) prompt, returns a `DetectorVerdict{fired, comment}`, AND
emits a binary score through the single `obs.emit_detector_score` seam.

Two timing classes:
  - single-turn (user_distress, out_of_scope): judge the incoming user message;
    score lands on the CURRENT trace (`target_trace_id=None`).
  - cross-turn (user_disagreement, insufficient_answer): judge the PRIOR answer in
    light of the new user message; score lands on the PRIOR turn's trace
    (`target_trace_id=<prev trace_id>`), because that's the answer being judged.
"""
from __future__ import annotations

from typing import Optional

from .. import llm, obs, prompts
from ..schemas import DetectorVerdict


def _judge(prompt_name: str, default_text: str, name: str, **vars) -> tuple[DetectorVerdict, object]:
    """Run one detector generation on the judge model; return (verdict, prompt)."""
    prompt = prompts.managed(prompt_name, default_text)
    content = prompt.compile(**vars)
    verdict = llm.llm_json(
        [{"role": "user", "content": content}],
        DetectorVerdict,
        name=name,
        model=llm.judge_model(),
        prompt=prompt,
    )
    return verdict, prompt


def _emit(score_name: str, verdict: DetectorVerdict, prompt: object, target_trace_id: Optional[str]) -> None:
    obs.emit_detector_score(
        score_name,
        verdict.fired,
        comment=verdict.comment,
        trace_id=target_trace_id,
        prompt_version=getattr(prompt, "version", None),
    )


# ── Single-turn detectors (score the current trace) ─────────────────────────
def detect_user_distress(user_message: str, history: str = "") -> DetectorVerdict:
    verdict, prompt = _judge(
        "detect_user_distress", prompts.DETECT_USER_DISTRESS, "detect_user_distress",
        history=history or "(none)", user_message=user_message,
    )
    _emit("user_distress", verdict, prompt, target_trace_id=None)
    return verdict


def detect_out_of_scope(user_message: str) -> DetectorVerdict:
    verdict, prompt = _judge(
        "detect_out_of_scope", prompts.DETECT_OUT_OF_SCOPE, "detect_out_of_scope",
        scope=prompts.WIKI_SCOPE, user_message=user_message,
    )
    _emit("out_of_scope", verdict, prompt, target_trace_id=None)
    return verdict


# ── Cross-turn detectors (score the PRIOR turn's trace) ─────────────────────
def detect_user_disagreement(
    prev_answer: str, user_message: str, history: str = "", *, target_trace_id: Optional[str] = None
) -> DetectorVerdict:
    verdict, prompt = _judge(
        "detect_user_disagreement", prompts.DETECT_USER_DISAGREEMENT, "detect_user_disagreement",
        history=history or "(none)", prev_answer=prev_answer, user_message=user_message,
    )
    _emit("user_disagreement", verdict, prompt, target_trace_id=target_trace_id)
    return verdict


def detect_insufficient_answer(
    prev_answer: str, user_message: str, history: str = "", *, target_trace_id: Optional[str] = None
) -> DetectorVerdict:
    verdict, prompt = _judge(
        "detect_insufficient_answer", prompts.DETECT_INSUFFICIENT_ANSWER, "detect_insufficient_answer",
        history=history or "(none)", prev_answer=prev_answer, user_message=user_message,
    )
    _emit("insufficient_answer", verdict, prompt, target_trace_id=target_trace_id)
    return verdict
