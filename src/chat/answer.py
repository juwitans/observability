"""chat: generate_answer (generation) + chat_turn orchestration with sessions.

One trace per user turn; all turns in a conversation grouped under one session
via `propagate_attributes(session_id=...)` (v4). Children:
  retrieve_context -> generate_answer -> faithfulness_eval
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .. import llm, obs, prompts
from ..evals.faithfulness import faithfulness_eval
from ..schemas import ChatAnswer, ChatChunk, FaithfulnessVerdict
from .retrieve import retrieve_context

# Map a logical prompt choice to (managed prompt name, default text).
_ANSWER_PROMPTS = {
    "v1": ("chat_answer", prompts.CHAT_ANSWER_V1),
    "v2": ("chat_answer_v2", prompts.CHAT_ANSWER_V2),
    "weak": ("chat_answer_weak", prompts.CHAT_ANSWER_WEAK),
}


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


def chat_turn(
    question: str,
    session_id: str,
    user_id: str | None = None,
    variant: str = "v1",
    top_k: int = 3,
) -> TurnResult:
    """Handle one user turn as a single trace, grouped under `session_id`."""
    with obs.span("chat_turn", input={"question": question, "variant": variant}) as root:
        with obs.session(session_id=session_id, user_id=user_id):
            with llm.collect_usage() as usages:
                t0 = time.perf_counter()
                chunks = retrieve_context(question, top_k=top_k)
                t1 = time.perf_counter()
                answer = generate_answer(question, chunks, variant=variant)
                t2 = time.perf_counter()
                verdict = faithfulness_eval(question, chunks, answer.answer)
                t3 = time.perf_counter()
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
            return TurnResult(
                answer=answer,
                chunks=chunks,
                faithfulness=verdict,
                trace_id=getattr(root, "trace_id", None),
                spans=spans,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=llm.default_model(),
            )
