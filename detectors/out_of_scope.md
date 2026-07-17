# Out-of-Scope Detector

**Type:** Event detector (binary)
**Timing:** Single-turn — judges the last user message against the agent's declared scope.
**Reusable across:** any agent with a defined scope (the wiki chatbot here).
**And then what?** When it fires, a user asked for something outside what the agent is for. Cluster similar out-of-scope requests in the Langfuse UI to inform product decisions — expand scope, or set user expectations up front.

> Adapted from Langfuse's published `out_of_scope` template
> (https://langfuse.com/blog/2026-04-01-llm-as-a-judge-production-monitoring).
> Runtime prompt lives in `src/prompts.py` as `DETECT_OUT_OF_SCOPE`; the agent's
> scope is the single source of truth in `prompts.WIKI_SCOPE`.

---

## Judge prompt

```
You are an Out-of-Scope detector for a documentation chat assistant.

Decide whether the LAST USER MESSAGE asks for something outside the agent's defined
scope. The scope is defined SOLELY by the text below — use no other assumptions.

AGENT SCOPE: {{scope}}

Rules:
- Score fired=true ONLY when the request has no plausible connection to the scope.
- Score fired=false for adjacent, niche, or ambiguous requests. If unsure, score false.
- Judge the user's request, not whether the assistant answered it well.
```

**Inputs:** the agent scope text (`prompts.WIKI_SCOPE`) + the last user message.
**Output:** `DetectorVerdict { fired: bool, comment: str }`.

---

## Decision rules

- **fired = true:** the request has **no plausible connection** to the scope
  (the observability/LLM-observability wiki domain).
- **fired = false:** adjacent, niche, or ambiguous requests; if the scope is vague,
  default to false.

---

## Examples

- Scope = observability wiki. *"Give me a recipe for chocolate chip cookies."* → **true**.
- Scope = observability wiki. *"How does sampling interact with cardinality?"* → **false** (in-domain).

---

## Wiring notes

- Emit through `obs.emit_detector_score("out_of_scope", fired, ...)`, tagged
  `agent=wiki_chatbot` + `prompt_version`. Lands on the **current** turn's trace.
- Edit `prompts.WIKI_SCOPE` to retune scope — the detector follows automatically.
