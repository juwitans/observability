"""chat: generate_answer (generation) + chat_turn orchestration with sessions.

One trace per user turn; all turns in a conversation grouped under one session
via `propagate_attributes(session_id=...)` (v4). Children:
  retrieve_context -> generate_answer -> faithfulness_eval

Event detectors (EVAL_STANDARD.md §3) also run here, distinct from the quality
metrics above:
  - single-turn (user_distress, out_of_scope): judge THIS user message; the score
    lands on this turn's trace.
  - cross-turn (user_disagreement, insufficient_answer): when a follow-up message
    arrives, judge the PREVIOUS answer against it; the score lands on the PREVIOUS
    turn's trace. A tiny per-session store (`_LAST_TURN`) remembers the prior turn.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field

from .. import llm, obs, prompts
from ..evals import detectors
from ..evals.faithfulness import faithfulness_eval
from ..schemas import ChatAnswer, ChatChunk, DetectorVerdict, FaithfulnessVerdict
from .retrieve import retrieve_context

# Map a logical prompt choice to (managed prompt name, default text).
_ANSWER_PROMPTS = {
    "v1": ("chat_answer", prompts.CHAT_ANSWER_V1),
    "v2": ("chat_answer_v2", prompts.CHAT_ANSWER_V2),
    "weak": ("chat_answer_weak", prompts.CHAT_ANSWER_WEAK),
}


@dataclass
class PrevTurn:
    """The prior turn in a session, so cross-turn detectors can judge it."""
    question: str
    answer: str
    trace_id: str | None


# Per-session memory of the last turn. In-memory and single-process — fine for
# this POC (the app already keeps state on the local filesystem, no DB). A
# multi-worker deployment would need a shared store keyed by session_id.
_LAST_TURN: dict[str, PrevTurn] = {}


def _detectors_enabled() -> bool:
    """Sample a fraction of turns for detection (EVAL_STANDARD.md §5). Default 1.0
    for the demo; set DETECTOR_SAMPLE_RATE=0 to disable, 0.2 for 20%, etc."""
    try:
        rate = float(os.environ.get("DETECTOR_SAMPLE_RATE", "1.0"))
    except ValueError:
        rate = 1.0
    return random.random() < rate


def _format_context(chunks: list[ChatChunk]) -> str:
    if not chunks:
        return "(no relevant wiki pages found)"
    return "\n\n".join(f"[{c.slug}] {c.title}\n{c.text[:2000]}" for c in chunks)


def generate_answer(
    question: str, chunks: list[ChatChunk], variant: str = "v1"
) -> ChatAnswer:
    name, default = _ANSWER_PROMPTS.get(variant, _ANSWER_PROMPTS["v1"])
    prompt = prompts.managed(name, default)
    content = prompt.compile(question=question, context=_format_context(chunks))
    answer = llm.llm_json(
        [{"role": "user", "content": content}],
        ChatAnswer,
        name="generate_answer",
        prompt=prompt,
    )
    return answer


@dataclass
class TurnResult:
    answer: ChatAnswer
    chunks: list[ChatChunk]
    faithfulness: FaithfulnessVerdict
    trace_id: str | None = None
    # Real per-turn telemetry, captured live (not from Langfuse) so the web UI's
    # trace panel shows genuine spans/tokens rather than mock numbers.
    spans: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    # Event-detector flags. `detectors` are about THIS turn's user message;
    # `prior_detectors` are about the PREVIOUS answer (scored on its trace), so the
    # UI can annotate the earlier message bubble.
    detectors: dict[str, DetectorVerdict] = field(default_factory=dict)
    prior_detectors: dict[str, DetectorVerdict] = field(default_factory=dict)


def chat_turn(
    question: str,
    session_id: str,
    user_id: str | None = None,
    variant: str = "v1",
    top_k: int = 3,
) -> TurnResult:
    """Handle one user turn as a single trace, grouped under `session_id`."""
    prev = _LAST_TURN.get(session_id)
    run_detectors = _detectors_enabled()
    prior_detectors: dict[str, DetectorVerdict] = {}
    detector_flags: dict[str, DetectorVerdict] = {}

    with obs.span("chat_turn", input={"question": question, "variant": variant}) as root:
        with obs.session(session_id=session_id, user_id=user_id):
            # Cross-turn detectors: judge the PREVIOUS answer in light of this new
            # message; the score attaches to the previous turn's trace.
            if run_detectors and prev is not None:
                history = f"User: {prev.question}\nAssistant: {prev.answer}"
                prior_detectors["user_disagreement"] = detectors.detect_user_disagreement(
                    prev.answer, question, history, target_trace_id=prev.trace_id
                )
                prior_detectors["insufficient_answer"] = detectors.detect_insufficient_answer(
                    prev.answer, question, history, target_trace_id=prev.trace_id
                )

            with llm.collect_usage() as usages:
                t0 = time.perf_counter()
                chunks = retrieve_context(question, top_k=top_k)
                t1 = time.perf_counter()
                answer = generate_answer(question, chunks, variant=variant)
                t2 = time.perf_counter()
                verdict = faithfulness_eval(question, chunks, answer.answer)
                t3 = time.perf_counter()

            # Single-turn detectors: judge THIS user message; score this trace.
            if run_detectors:
                history = f"User: {prev.question}\nAssistant: {prev.answer}" if prev else ""
                detector_flags["user_distress"] = detectors.detect_user_distress(question, history)
                detector_flags["out_of_scope"] = detectors.detect_out_of_scope(question)

            spans = [
                {"name": "retrieve_context", "ms": round((t1 - t0) * 1000)},
                {"name": "generate_answer", "ms": round((t2 - t1) * 1000)},
                {"name": "faithfulness_eval", "ms": round((t3 - t2) * 1000)},
            ]
            tokens_in = sum(u.get("input") or 0 for u in usages)
            tokens_out = sum(u.get("output") or 0 for u in usages)
            obs.update_span(
                output={
                    "answer": answer.answer,
                    "cited_slugs": answer.cited_slugs,
                    "faithfulness": verdict.faithfulness,
                    "answer_relevance": verdict.answer_relevance,
                }
            )
            trace_id = getattr(root, "trace_id", None)
            # Remember this turn so the NEXT message can judge it cross-turn.
            _LAST_TURN[session_id] = PrevTurn(
                question=question, answer=answer.answer, trace_id=trace_id
            )
            return TurnResult(
                answer=answer,
                chunks=chunks,
                faithfulness=verdict,
                trace_id=trace_id,
                spans=spans,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=llm.default_model(),
                detectors=detector_flags,
                prior_detectors=prior_detectors,
            )
