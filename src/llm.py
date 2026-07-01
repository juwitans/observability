"""llm.py — the ONE provider-agnostic LLM wrapper, traced as a generation.

Every LLM call in the project goes through `llm()` or `llm_json()`. The model is
chosen per-call (default from env), so any stage/experiment can swap models and
you compare cost/latency per-generation in Langfuse. No business logic depends
on a specific provider — only on the OpenAI-compatible chat-completions API.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from . import obs

_client: Optional[OpenAI] = None

T = TypeVar("T", bound=BaseModel)

# Roll up real token usage across every llm()/llm_json() call inside a block,
# so a caller (e.g. chat_turn) can report genuine token totals in the UI without
# threading usage through every stage. Same numbers Langfuse bills on.
_usage_sink: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "llm_usage_sink", default=None
)


@contextmanager
def collect_usage() -> Iterator[list]:
    """Accumulate per-call token usage for every LLM call made inside the block.

    Yields a list that fills with the usage dicts produced by `_usage`. Read it
    after the block exits to sum real input/output tokens for the turn.
    """
    sink: list = []
    token = _usage_sink.set(sink)
    try:
        yield sink
    finally:
        _usage_sink.reset(token)


def _record_usage(usage: Optional[dict]) -> None:
    if not usage:
        return
    sink = _usage_sink.get()
    if sink is not None:
        sink.append(usage)


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=os.environ.get("LLM_BASE_URL"),
            api_key=os.environ.get("LLM_API_KEY") or "sk-noop",
        )
    return _client


def default_model() -> str:
    m = os.environ.get("LLM_MODEL")
    if not m:
        raise RuntimeError("LLM_MODEL not set (check your .env).")
    return m


def judge_model() -> str:
    return os.environ.get("LLM_JUDGE_MODEL") or default_model()


def _usage(resp) -> Optional[dict]:
    """Token usage as a Langfuse `usage_details` dict.

    Keys are the canonical `input`/`output`/`total` (NOT `*_tokens`): Langfuse
    computes cost by multiplying each usage key by the matching key in the
    model definition's price map, and those prices are stored under `input` /
    `output`. Mismatched keys (e.g. `input_tokens`) record tokens but yield no
    cost — which is why cost stayed blank even after adding model pricing.
    """
    u = getattr(resp, "usage", None)
    if not u:
        return None
    return _clean_usage(
        {
            "input": getattr(u, "prompt_tokens", None),
            "output": getattr(u, "completion_tokens", None),
            "total": getattr(u, "total_tokens", None),
        }
    )


def _clean_usage(d: dict) -> Optional[dict]:
    out = {k: v for k, v in d.items() if v is not None}
    return out or None


def llm(
    messages: list[dict],
    *,
    model: Optional[str] = None,
    name: str = "llm_call",
    temperature: float = 0.2,
    prompt: Any = None,
    **kwargs,
) -> str:
    """Plain text completion, traced as a generation (captures model/tokens/cost)."""
    model = model or default_model()
    with obs.generation(name=name, model=model, input=messages, prompt=prompt):
        resp = _openai().chat.completions.create(
            model=model, messages=messages, temperature=temperature, **kwargs
        )
        text = resp.choices[0].message.content or ""
        usage = _usage(resp)
        obs.update_generation(output=text, usage_details=usage)
        _record_usage(usage)
        return strip_reasoning(text)


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models (e.g. minimax)."""
    text = _THINK_RE.sub("", text)
    # Drop an unclosed trailing <think> (truncation / streaming artifact).
    idx = text.lower().rfind("<think>")
    if idx != -1 and "</think>" not in text.lower()[idx:]:
        text = text[:idx]
    return text.strip()


def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction: handle reasoning blocks, ```json fences, prose."""
    text = strip_reasoning(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the widest {...} span (objects may contain nested braces).
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def llm_json(
    messages: list[dict],
    schema: Type[T],
    *,
    model: Optional[str] = None,
    name: str = "llm_json",
    temperature: float = 0.0,
    max_retries: int = 1,
    prompt: Any = None,
) -> T:
    """Structured completion validated against a Pydantic schema.

    Asks the model for a JSON object matching `schema`, validates it, and does
    up to `max_retries` self-repair rounds on parse/validation failure. Each
    attempt is its own generation span (so retries are visible in the trace).
    """
    model = model or default_model()
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    sys = {
        "role": "system",
        "content": (
            "Respond with ONLY a single valid JSON object that conforms to this "
            f"JSON Schema. No markdown fences, no prose.\n\n{schema_json}"
        ),
    }
    msgs = [sys, *messages]
    last_err: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        with obs.generation(name=name, model=model, input=msgs, prompt=prompt):
            try:
                resp = _openai().chat.completions.create(
                    model=model,
                    messages=msgs,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
            except Exception:
                # Provider may not support response_format; retry without it.
                resp = _openai().chat.completions.create(
                    model=model, messages=msgs, temperature=temperature
                )
            text = resp.choices[0].message.content or ""
            usage = _usage(resp)
            obs.update_generation(output=text, usage_details=usage)
            _record_usage(usage)
            try:
                obj = schema.model_validate(_extract_json(text))
                return obj
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                obs.update_generation(
                    level="WARNING",
                    status_message=f"JSON parse/validation failed: {e}",
                )
                msgs = [
                    *msgs,
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": f"That was not valid. Error: {e}. Return ONLY the corrected JSON object.",
                    },
                ]

    raise RuntimeError(f"llm_json failed after {max_retries + 1} attempts: {last_err}")
