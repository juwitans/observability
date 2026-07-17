"""obs.py — the ONE place that imports langfuse.

Every other module in this project gets tracing, scoring and session helpers
from here. Keeping the import surface to a single file is what makes the
observability backend swappable and the instrumentation consistent
(IMPLEMENTATION.md §2 "Rule").

API verified against Langfuse Python SDK v4 (OTel-based, observation-centric).
See memory: langfuse-v4-python-api.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import sys

from dotenv import load_dotenv

load_dotenv()  # pull .env into the environment before the client reads it

# Pin the OTel GenAI semantic-convention generation before importing anything
# OTel-based (OBSERVABILITY_INSTRUMENTATION.md §5 "Version-churn management":
# emit current-generation agent/tool span names and treat drift as a config
# knob, not a rewrite). setdefault so a real .env value still wins.
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")

# Private attribute namespace for domain concepts the GenAI spec doesn't cover
# (OBSERVABILITY_INSTRUMENTATION.md §6). Never shadow a `gen_ai.*` key; prefix
# everything custom with this so a future OTel addition can't collide.
PRIVATE_NS = "wiki"

# The single langfuse import surface for the whole project.
from langfuse import Evaluation, get_client, observe, propagate_attributes  # noqa: E402,F401


def _patch_self_hosted_compat() -> None:
    """Tolerate older self-hosted servers (e.g. Langfuse 3.x) that omit fields the
    v4 SDK marks required (`media_references` on dataset items). Makes the field
    optional so dataset reads/writes parse against an older server."""
    try:
        from langfuse.api.commons.types.dataset_item import DatasetItem

        field = DatasetItem.model_fields.get("media_references")
        if field is not None and field.is_required():
            field.default = None
            DatasetItem.model_rebuild(force=True)
    except Exception:
        pass


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252 and crash printing unicode (→, smart
    quotes) in answers/content. Force utf-8 so scripts don't die on output."""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
            except Exception:
                pass


_patch_self_hosted_compat()
_force_utf8_stdout()

_client = None


def lf():
    """Return the env-configured Langfuse singleton."""
    global _client
    if _client is None:
        _client = get_client()
    return _client


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so we never overwrite a field with nothing."""
    return {k: v for k, v in d.items() if v is not None}


# ── Tracing ────────────────────────────────────────────────────────────────
@contextmanager
def span(
    name: str,
    input: Any = None,
    metadata: Optional[dict] = None,
) -> Iterator[Any]:
    """A deterministic stage. Children auto-nest under the active observation."""
    with lf().start_as_current_observation(
        as_type="span", name=name, input=input, metadata=metadata
    ) as obs:
        yield obs


@contextmanager
def generation(
    name: str,
    model: str,
    input: Any = None,
    metadata: Optional[dict] = None,
    prompt: Any = None,
) -> Iterator[Any]:
    """An LLM call. `model` lets Langfuse compute tokens/cost automatically.

    `prompt` links a managed (versioned) prompt to the generation so quality
    changes are attributable to a specific prompt version.
    """
    kwargs = _clean(
        dict(name=name, model=model, input=input, metadata=metadata, prompt=prompt)
    )
    with lf().start_as_current_observation(as_type="generation", **kwargs) as obs:
        yield obs


def update_span(
    output: Any = None,
    level: Optional[str] = None,
    status_message: Optional[str] = None,
    metadata: Optional[dict] = None,
    input: Any = None,
) -> None:
    lf().update_current_span(
        **_clean(
            dict(
                output=output,
                level=level,
                status_message=status_message,
                metadata=metadata,
                input=input,
            )
        )
    )


def update_generation(
    output: Any = None,
    usage_details: Optional[dict] = None,
    metadata: Optional[dict] = None,
    input: Any = None,
    level: Optional[str] = None,
    status_message: Optional[str] = None,
) -> None:
    lf().update_current_generation(
        **_clean(
            dict(
                output=output,
                usage_details=usage_details,
                metadata=metadata,
                input=input,
                level=level,
                status_message=status_message,
            )
        )
    )


# ── Scores (online evaluation) ─────────────────────────────────────────────
def score_span(
    name: str, value, data_type: str = "NUMERIC", comment: Optional[str] = None
) -> None:
    lf().score_current_span(**_clean(dict(name=name, value=value, data_type=data_type, comment=comment)))


def score_trace(
    name: str, value, data_type: str = "NUMERIC", comment: Optional[str] = None
) -> None:
    lf().score_current_trace(**_clean(dict(name=name, value=value, data_type=data_type, comment=comment)))


# ── Event-detector scores (EVAL_STANDARD.md §5 wiring) ─────────────────────
# The single seam for emitting binary event-detector flags. Every detector score
# is tagged with `agent` + `prompt_version` (in metadata) so scores can be filtered
# and grouped per agent and per prompt version. Passing `trace_id` (and optionally
# `observation_id`) lets a *cross-turn* detector attach its flag to a PRIOR turn's
# trace — e.g. "turn N's answer caused disagreement on turn N+1" is recorded on
# turn N. Omit both to score the currently-active trace.
DETECTOR_AGENT = "wiki_chatbot"


def emit_detector_score(
    name: str,
    fired: bool,
    comment: Optional[str] = None,
    *,
    trace_id: Optional[str] = None,
    observation_id: Optional[str] = None,
    prompt_version: Optional[int | str] = None,
    agent: str = DETECTOR_AGENT,
) -> None:
    metadata = _clean(dict(agent=agent, prompt_version=prompt_version, detector=True))
    if trace_id is None:
        # No target trace given -> score the active trace in context.
        lf().score_current_trace(
            **_clean(dict(name=name, value=1 if fired else 0, data_type="BOOLEAN",
                          comment=comment, metadata=metadata))
        )
    else:
        lf().create_score(
            **_clean(dict(name=name, value=1 if fired else 0, data_type="BOOLEAN",
                          trace_id=trace_id, observation_id=observation_id,
                          comment=comment, metadata=metadata))
        )


# ── Sessions (v4: propagate_attributes, NOT update_current_trace) ──────────
@contextmanager
def session(session_id: str, user_id: Optional[str] = None) -> Iterator[None]:
    """Group every observation created inside under one session_id."""
    with propagate_attributes(**_clean(dict(session_id=session_id, user_id=user_id))):
        yield


# ── Prompt management ──────────────────────────────────────────────────────
def get_prompt(name: str, label: Optional[str] = None):
    return lf().get_prompt(**_clean(dict(name=name, label=label)))


def upsert_prompt(name: str, prompt: str, labels: Optional[list[str]] = None, config: Optional[dict] = None):
    """Create (or add a new version of) a managed text prompt."""
    return lf().create_prompt(
        **_clean(dict(name=name, type="text", prompt=prompt, labels=labels or ["production"], config=config))
    )


# ── Querying (self-hosted: legacy namespaces) ──────────────────────────────
def legacy_observations():
    """v2 observations/metrics endpoints are unavailable on self-hosted; use legacy."""
    return lf().api.legacy.observations_v1


def trace_url(trace_id: Optional[str]) -> Optional[str]:
    """Deep link to a trace in the Langfuse UI (for the demo web app)."""
    if not trace_id:
        return None
    try:
        return lf().get_trace_url(trace_id=trace_id)
    except Exception:
        return None


def session_url(session_id: str) -> Optional[str]:
    """Deep link to a session replay in the Langfuse UI."""
    try:
        pid = lf()._get_project_id()
        base = os.environ.get("LANGFUSE_BASE_URL", "").rstrip("/")
        if pid and base:
            return f"{base}/project/{pid}/sessions/{session_id}"
    except Exception:
        pass
    return None


def flush() -> None:
    lf().flush()


def shutdown() -> None:
    lf().shutdown()
