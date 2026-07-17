"""prompts.py — managed (versioned) prompts, linked to generations.

Each prompt is registered in Langfuse prompt management on first use and then
fetched, so every generation links to a specific prompt *version*. That makes a
quality change always attributable to a prompt edit (IMPLEMENTATION.md §5).

Placeholders use Langfuse's `{{var}}` syntax; callers `.compile(**vars)`.
"""
from __future__ import annotations

from . import obs

_cache: dict[tuple[str, str | None], object] = {}


def managed(name: str, default_text: str, label: str | None = None):
    """Fetch the managed prompt, creating it from `default_text` if absent."""
    key = (name, label)
    if key in _cache:
        return _cache[key]
    try:
        prompt = obs.get_prompt(name, label=label)
    except Exception:
        obs.upsert_prompt(name, default_text, labels=["production"])
        prompt = obs.get_prompt(name)
    _cache[key] = prompt
    return prompt


# ── Prompt texts ───────────────────────────────────────────────────────────
WRITE_PAGE = """\
You are the writer for an observability wiki. Compile ONE clean concept page.

You are given a NEW SOURCE and any RELATED existing wiki pages. Your job:
- Synthesize a single, coherent encyclopedic page on the concept the source is about.
- MERGE overlapping material from related pages rather than duplicating it.
- When sources DISAGREE, surface the disagreement explicitly and attribute each
  position — do not silently pick a side or invent a reconciliation.
- Ground every claim in the provided text. Do NOT add facts not present in the
  source or related pages.
- Cross-link related pages by their slug using markdown links like [title](slug.md).
- Cite the source URL(s) you used.

NEW SOURCE (url: {{url}}, topic: {{topic}}):
---
{{source}}
---

RELATED EXISTING PAGES:
{{related}}

Produce the page as the structured object requested.
"""

JUDGE_PAGE = """\
You are a strict faithfulness judge for an observability wiki.

Decide whether the DRAFT PAGE is grounded in the SOURCE TEXT. Penalize any claim
that is unsupported by, or contradicts, the source. Reward faithful synthesis and
correctly-attributed disagreements.

SOURCE TEXT:
---
{{source}}
---

DRAFT PAGE:
---
{{draft}}
---

Return: groundedness (0-1, fraction of claims supported), faithful (true only if
there are NO unsupported or contradicted claims), a list of specific issues, and
brief reasoning.
"""

REPAIR_PAGE = """\
You are repairing a wiki page that failed review. Fix ONLY the flagged problems
while preserving correct content. Stay grounded in the source; remove or correct
any unsupported/contradicted claims; fix broken cross-links.

SOURCE TEXT:
---
{{source}}
---

CURRENT DRAFT:
---
{{draft}}
---

JUDGE VERDICT: {{verdict}}
LINT ISSUES: {{lint}}

Return the corrected page as the structured object requested.
"""

# Chat answer — v1 is the baseline (permissive). v2 (strict grounding) is created
# by the experiment script to beat v1 on the golden set.
CHAT_ANSWER_V1 = """\
Answer the user's question about observability using the CONTEXT below.
Be helpful and thorough.

CONTEXT:
{{context}}

QUESTION: {{question}}

Cite the wiki page slugs you used.
"""

CHAT_ANSWER_V2 = """\
Answer the user's question STRICTLY from the CONTEXT below. Rules:
- Use ONLY facts present in the context. If the context does not cover something,
  say so explicitly rather than guessing.
- Attribute contested claims to the position that makes them.
- Cite the exact wiki page slug(s) each part of your answer draws on.

CONTEXT:
{{context}}

QUESTION: {{question}}
"""

# Deliberately weak prompt (demo): invites ungrounded elaboration -> low
# faithfulness. Used by `chat_cli --weak` to generate hard cases for the dataset.
CHAT_ANSWER_WEAK = """\
You are a knowledgeable observability expert. Answer the user's question.
Use the context if helpful, but feel free to add your own background knowledge
to make the answer comprehensive and impressive.

CONTEXT:
{{context}}

QUESTION: {{question}}
"""

FAITHFULNESS_JUDGE = """\
You are evaluating a chat answer for an observability wiki assistant.

Score two things from 0 to 1:
- faithfulness: is every claim in the ANSWER supported by the CONTEXT?
  (1 = fully grounded, 0 = mostly fabricated/contradicted)
- answer_relevance: does the ANSWER actually address the QUESTION?

QUESTION: {{question}}

CONTEXT:
---
{{context}}
---

ANSWER:
---
{{answer}}
---

Return faithfulness, answer_relevance, and brief reasoning.
"""


# ── Event detectors (EVAL_STANDARD.md §3) ───────────────────────────────────
# Binary "did X happen?" judges, one narrow check each, adapted from Langfuse's
# published support-agent templates for our wiki chatbot. Each returns a
# DetectorVerdict {fired, comment}. The human-readable specs live in detectors/.

# The agent's scope, quoted verbatim by the out_of_scope detector. This is the
# single source of truth for "what is this bot for" — edit it here and the
# detector follows.
WIKI_SCOPE = """\
This assistant answers questions about software observability and LLM/agent
observability — concepts like tracing, metrics, logging, the three pillars,
OpenTelemetry, sampling, and LLM hallucination detection — grounded in a curated
wiki corpus. It is a documentation Q&A assistant for that domain. It is NOT a
general-purpose assistant, a coding assistant, a personal assistant, or a chatbot
for unrelated topics (weather, cooking, math homework, medical/legal advice, etc.).
"""

DETECT_USER_DISTRESS = """\
You are a User Distress detector for a documentation chat assistant.

Decide whether the LAST USER MESSAGE contains profanity or intense frustration that
clearly goes beyond mild annoyance — an explicit signal the user is unhappy.

Rules:
- Judge ONLY the last user message. Ignore the assistant's responses.
- Score fired=true for explicit profanity or strong frustration/anger.
- Score fired=false for mild expressions ("ugh", "seriously?", "hmm that's odd").
- Do not infer distress that isn't clearly expressed.

CONVERSATION SO FAR (for context only):
---
{{history}}
---

LAST USER MESSAGE:
---
{{user_message}}
---

Return fired (true/false) and a one-line comment naming the evidence.
"""

DETECT_OUT_OF_SCOPE = """\
You are an Out-of-Scope detector for a documentation chat assistant.

Decide whether the LAST USER MESSAGE asks for something outside the agent's defined
scope. The scope is defined SOLELY by the text below — use no other assumptions.

AGENT SCOPE:
---
{{scope}}
---

Rules:
- Score fired=true ONLY when the request has no plausible connection to the scope.
- Score fired=false for adjacent, niche, or ambiguous requests. If unsure, score false.
- Judge the user's request, not whether the assistant answered it well.

LAST USER MESSAGE:
---
{{user_message}}
---

Return fired (true/false) and a one-line comment explaining the scope match or mismatch.
"""

DETECT_USER_DISAGREEMENT = """\
You are a User Disagreement detector for a documentation chat assistant.

Decide whether, in the LAST USER MESSAGE, the user pushes back on, corrects, or
signals the PRIOR ASSISTANT ANSWER was wrong or did not work.

Rules:
- Score fired=true if the user says the answer was wrong, contradicts it, says it
  didn't work when tried, or that the described thing couldn't be found.
- Score fired=false for neutral follow-up questions, requests to escalate without
  blame, or new unrelated questions.
- Judge only opposition to the PRIOR ASSISTANT ANSWER, not general complaints.

CONVERSATION SO FAR (for context):
---
{{history}}
---

PRIOR ASSISTANT ANSWER:
---
{{prev_answer}}
---

LAST USER MESSAGE:
---
{{user_message}}
---

Return fired (true/false) and a concise comment naming the disagreement (or its absence).
"""

DETECT_INSUFFICIENT_ANSWER = """\
You are an Insufficient Answer detector for a documentation chat assistant.

Decide whether, in the LAST USER MESSAGE, the user signals the PRIOR ASSISTANT
ANSWER was too brief, vague, or didn't fully address their need.

Rules:
- Score fired=true for explicit elaboration requests ("can you explain more?",
  "that doesn't really answer it") or clearly implied insufficiency.
- Score fired=false for natural follow-ups that build on a complete answer without
  reproach. Do NOT confuse a brand-new question with an insufficiency signal.
- Judge only against the PRIOR ASSISTANT ANSWER.

CONVERSATION SO FAR (for context):
---
{{history}}
---

PRIOR ASSISTANT ANSWER:
---
{{prev_answer}}
---

LAST USER MESSAGE:
---
{{user_message}}
---

Return fired (true/false) and a one-line comment.
"""
