"""schemas.py — typed contracts between pipeline stages (Pydantic v2)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Topic = Literal["traditional", "otel", "llm", "contrarian"]


# ── Pipeline stage I/O ─────────────────────────────────────────────────────
class FetchResult(BaseModel):
    url: str
    status: int
    byte_size: int
    html: str


class ExtractResult(BaseModel):
    url: str
    markdown: str
    char_length: int


class RelatedPage(BaseModel):
    slug: str
    title: str
    score: float
    text: str  # the ACTUAL retrieved text (capture rule, §4.3)


class RetrieveResult(BaseModel):
    related: list[RelatedPage] = Field(default_factory=list)


class WikiPage(BaseModel):
    """The compiled concept page the writer produces."""
    title: str
    slug: str
    topic: Topic
    summary: str = Field(description="One-paragraph abstract.")
    markdown: str = Field(description="Full page body in markdown.")
    related_slugs: list[str] = Field(
        default_factory=list, description="Slugs of related wiki pages to cross-link."
    )
    citations: list[str] = Field(
        default_factory=list, description="Source URLs this page is grounded in."
    )


class JudgeVerdict(BaseModel):
    """Output of judge_page (LLM-as-judge)."""
    groundedness: float = Field(ge=0.0, le=1.0, description="0-1: how supported by sources.")
    faithful: bool = Field(description="True if no unsupported/contradicted claims.")
    issues: list[str] = Field(default_factory=list, description="Specific problems found.")
    reasoning: str = Field(default="", description="Brief justification.")


class LintResult(BaseModel):
    """Deterministic link/structure checks."""
    passed: bool
    issue_count: int
    issues: list[str] = Field(default_factory=list)


# ── Chat ───────────────────────────────────────────────────────────────────
class ChatChunk(BaseModel):
    slug: str
    title: str
    score: float
    text: str


class ChatAnswer(BaseModel):
    answer: str
    cited_slugs: list[str] = Field(default_factory=list)


class FaithfulnessVerdict(BaseModel):
    """Output of the online chat faithfulness judge."""
    faithfulness: float = Field(ge=0.0, le=1.0, description="0-1: answer supported by context.")
    answer_relevance: float = Field(ge=0.0, le=1.0, description="0-1: answer addresses the question.")
    reasoning: str = Field(default="")


# ── Event detectors ─────────────────────────────────────────────────────────
class DetectorVerdict(BaseModel):
    """Output of a binary event detector (EVAL_STANDARD.md §1: "did X happen?").

    Unlike a quality metric, this is a yes/no flag tied to an action, not a 0-1
    score. `fired=True` means the event was detected on the judged turn.
    """
    fired: bool = Field(description="True if the event was detected.")
    comment: str = Field(default="", description="One-line justification naming the evidence.")
