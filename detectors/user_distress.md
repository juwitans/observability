# User Distress Detector

**Type:** Event detector (binary)
**Timing:** Single-turn — judges the last user message alone.
**Reusable across:** the wiki chatbot (any conversational agent a human talks to directly).
**And then what?** When it fires, a user expressed profanity or strong frustration. Treat the trace as high-priority for manual review; a cluster on the same topic points at a concrete failure worth fixing. Aggregate by topic in the Langfuse UI.

> Adapted from Langfuse's published `user_cursing` template
> (https://langfuse.com/blog/2026-04-01-llm-as-a-judge-production-monitoring).
> Runtime prompt lives in `src/prompts.py` as `DETECT_USER_DISTRESS` (managed/
> versioned in Langfuse); this file is the human-readable spec.

---

## Judge prompt

```
You are a User Distress detector for a documentation chat assistant.

Decide whether the LAST USER MESSAGE contains profanity or intense frustration that
clearly goes beyond mild annoyance — an explicit signal the user is unhappy.

Rules:
- Judge ONLY the last user message. Ignore the assistant's responses.
- Score fired=true for explicit profanity or strong frustration/anger.
- Score fired=false for mild expressions ("ugh", "seriously?", "hmm that's odd").
- Do not infer distress that isn't clearly expressed.
```

**Inputs:** conversation history (context only) + the last user message.
**Output:** `DetectorVerdict { fired: bool, comment: str }`.

---

## Decision rules

- **fired = true:** explicit profanity, cursing, or anger clearly beyond mild annoyance.
- **fired = false:** mild venting ("ugh", "seriously?"), neutral confusion, no user message.

---

## Examples

- *"This is absolute garbage, you clearly have no idea what the hell you're talking about."* → **true**
- *"ugh, that wasn't quite what I meant"* → **false** (mild, not distress).

---

## Wiring notes

- Emit through `obs.emit_detector_score("user_distress", fired, ...)` as a binary `0/1`
  score, tagged `agent=wiki_chatbot` + `prompt_version`.
- The score lands on the **current** turn's trace (single-turn detector).
- Filter fires in the Langfuse UI and group by topic; recurring distress on one topic
  is a real failure signal. (Automated alerting is deferred — see EVAL_STANDARD.md §5.)
