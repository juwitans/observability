# Insufficient Answer Detector

**Type:** Event detector (binary)
**Timing:** Cross-turn — judges the **prior assistant answer** in light of the next user message. Fires on the follow-up turn; the score attaches to the **previous** turn's trace.
**Reusable across:** the wiki chatbot.
**And then what?** When it fires, the user signaled the answer was too thin — asked for more. Recurring topics where users "ask for more" indicate a knowledge-base gap or a prompt-calibration need. Filter the flagged traces and read the preceding assistant turns.

> Adapted from Langfuse's published `insufficient_answer` template
> (https://langfuse.com/blog/2026-04-01-llm-as-a-judge-production-monitoring).
> Runtime prompt lives in `src/prompts.py` as `DETECT_INSUFFICIENT_ANSWER`.

---

## Judge prompt

```
You are an Insufficient Answer detector for a documentation chat assistant.

Decide whether, in the LAST USER MESSAGE, the user signals the PRIOR ASSISTANT
ANSWER was too brief, vague, or didn't fully address their need.

Rules:
- Score fired=true for explicit elaboration requests ("can you explain more?",
  "that doesn't really answer it") or clearly implied insufficiency.
- Score fired=false for natural follow-ups that build on a complete answer without
  reproach. Do NOT confuse a brand-new question with an insufficiency signal.
- Judge only against the PRIOR ASSISTANT ANSWER.
```

**Inputs:** conversation history + the prior assistant answer + the last user message.
**Output:** `DetectorVerdict { fired: bool, comment: str }`.

---

## Decision rules

- **fired = true:** explicit "explain more / that's too vague / that barely answers it,"
  or clearly implied insufficiency about the prior answer.
- **fired = false:** natural follow-ups that build on a complete answer; a new question.
  The distinction from `user_disagreement`: insufficiency = "not enough," disagreement =
  "wrong."

---

## Examples

- Answer briefly defined hallucination detection. *"That's way too vague — can you go into much more detail?"* → **true**.
- Same answer. *"Thanks. Does that apply to RAG specifically?"* → **false** (builds on a complete answer).

---

## Wiring notes

- Emit through `obs.emit_detector_score("insufficient_answer", fired, ..., trace_id=<prev turn>)`,
  tagged `agent=wiki_chatbot` + `prompt_version`. **Cross-turn** — pass the previous
  turn's `trace_id` so the flag records against the answer judged too thin.
- Cluster fires by topic in the Langfuse UI to find knowledge-base gaps.
