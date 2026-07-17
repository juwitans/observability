# User Disagreement Detector

**Type:** Event detector (binary)
**Timing:** Cross-turn — judges the **prior assistant answer** in light of the next user message. Fires on the follow-up turn; the score attaches to the **previous** turn's trace.
**Reusable across:** the wiki chatbot. (This is the chatbot's analog of the universal `human_override` — a human pushing back on the machine.)
**And then what?** When it fires, the user rejected or corrected the answer — an "LLM 404." Aggregate by topic: the same topic triggering disagreement repeatedly is a documentation gap or a system-prompt/knowledge fix waiting to happen.

> Adapted from Langfuse's published `user_disagreement` template
> (https://langfuse.com/blog/2026-04-01-llm-as-a-judge-production-monitoring).
> Runtime prompt lives in `src/prompts.py` as `DETECT_USER_DISAGREEMENT`.

---

## Judge prompt

```
You are a User Disagreement detector for a documentation chat assistant.

Decide whether, in the LAST USER MESSAGE, the user pushes back on, corrects, or
signals the PRIOR ASSISTANT ANSWER was wrong or did not work.

Rules:
- Score fired=true if the user says the answer was wrong, contradicts it, says it
  didn't work when tried, or that the described thing couldn't be found.
- Score fired=false for neutral follow-up questions, requests to escalate without
  blame, or new unrelated questions.
- Judge only opposition to the PRIOR ASSISTANT ANSWER, not general complaints.
```

**Inputs:** conversation history + the prior assistant answer + the last user message.
**Output:** `DetectorVerdict { fired: bool, comment: str }`.

---

## Decision rules

- **fired = true:** the user says it was wrong, contradicts it, reports it "didn't
  work when tried," or that a described step/thing couldn't be found.
- **fired = false:** neutral follow-ups, escalation requests without blame, or a
  brand-new unrelated question.

---

## Examples

- Answer recommended head-based sampling. *"That's wrong — the wiki says tail-based is the default here."* → **true**.
- Answer explained the three pillars. *"Got it. And where do profiles fit in?"* → **false** (neutral follow-up).

---

## Wiring notes

- Emit through `obs.emit_detector_score("user_disagreement", fired, ..., trace_id=<prev turn>)`,
  tagged `agent=wiki_chatbot` + `prompt_version`. Because it's **cross-turn**, pass the
  previous turn's `trace_id` so the flag records against the answer that was disputed.
- Watch `user_disagreement` rate grouped by `prompt_version` — a rising rate is the
  earliest sign the agent is degrading. (Alerting is deferred — see EVAL_STANDARD.md §5.)
