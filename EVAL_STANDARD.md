# Evaluation Standard

How we evaluate LLM/agent applications across the company. This is a **convention**, not a shared runtime library — each project adopts it by (a) picking its quality-metric mix, (b) copying the event-detector prompts it needs, and (c) wiring scores into Langfuse using the same helper.

The one sentence to remember: **the harness is shared, the criteria are local.**

---

## 1. Two kinds of judge (don't conflate them)

| | **Quality metrics** | **Event detectors** |
|---|---|---|
| Question | "How good is this output, 0–1?" | "Did *X* happen, yes/no?" |
| Output | continuous score | binary flag |
| Examples | faithfulness, answer relevancy, bias | user disagreed, human overrode the AI, out-of-scope |
| Source | **adopt DeepEval / RAGAS** — don't rewrite | **author here** — these are behavioral, no framework ships them |
| Reuse | criteria diverge sharply by task | reusable across agents — a human overriding the AI means the same everywhere |

The counterintuitive part: the **reusable** layer is the event detectors (behavioral signals about the human's reaction), *not* the quality metrics (which are task-specific). Build the detector library; borrow the quality metrics.

### Why event detectors matter (they catch what quality scores miss)
A quality score tells you the average. An event detector tells you when something specific happened that's worth acting on. Good detectors are **binary, narrow, and tied to an action** — every detector must answer "and then what?" (who sees it, what they do). "quality: 0.7" can't be acted on; "user cursed → review this trace this week" can.

---

## 2. Quality metrics — adopt DeepEval, don't build

DeepEval gives 50+ benchmarked, self-explaining metrics, model-agnostic (works with our self-hosted judge model). Use its ready-made metrics where they fit; use `G-Eval` (plain-English `evaluation_steps`) to author task-specific criteria without writing a judge from scratch.

**Do not** hand-write faithfulness / relevancy / hallucination judges — DeepEval's are research-backed and already exist. The POC's original hand-rolled versions are kept only as a reference; new projects use DeepEval.

> **Known limitation to design around:** these metrics evaluate the *generator*, not the *corpus*. A RAG answer can score 0.95 faithfulness and still be wrong if the retrieved content itself is stale. "Is my knowledge source current" is a separate check the owning team is responsible for — it is not covered by any eval framework.

---

## 3. Event detectors — the library in `detectors/`

Binary LLM-as-judge prompts, one check each, copy-paste into a project's Langfuse online-evaluation setup. Seeded from Langfuse's published templates; extend with our own.

| Detector | File | What it catches | Reusable across our 3 agents? |
|---|---|---|---|
| User distress | `detectors/user_distress.md` | profanity / strong frustration | Wiki chatbot |
| User disagreement | `detectors/user_disagreement.md` | user rejected/corrected the answer (LLM "404") | Wiki chatbot |
| Out-of-scope | `detectors/out_of_scope.md` | request outside the agent's defined scope | Wiki chatbot |
| Insufficient answer | `detectors/insufficient_answer.md` | user asked for more — answer too thin | Wiki chatbot |
| **Human override** | `detectors/human_override.md` | a human rejected/reversed the AI's recommendation | **All three** — this is the universal one |

The first four come from Langfuse's support-agent templates. `human_override` is ours, and it's the most broadly useful: every agent that produces a recommendation a human can accept or reject has a version of it.

> **Implemented for the wiki chatbot.** The four chatbot detectors are authored under `detectors/` and wired **online** into the app: runtime prompts in `src/prompts.py` (`DETECT_*`, `WIKI_SCOPE`), runner in `src/evals/detectors.py`, wiring in `src/chat/answer.py`, emitted through the `obs.emit_detector_score` seam. Single-turn detectors (`user_distress`, `out_of_scope`) score the current turn; cross-turn detectors (`user_disagreement`, `insufficient_answer`) score the *previous* turn's trace when the follow-up message arrives. Replay demo: `python -m scripts.demo_detectors`.

---

## 4. Per-agent judge mix

Same harness, different selection. This table is the whole point of the standard.

### 1. Wiki chatbot (RAG)
- **Quality (DeepEval):** Faithfulness, Answer Relevancy, Contextual Relevancy.
- **Event detectors:** `user_disagreement` (→ docs gap), `insufficient_answer` (→ knowledge-base gap), `out_of_scope`, `user_distress`.
- **Note:** this is the classic support-chatbot shape — the Langfuse templates apply almost verbatim.

### 2. PR reviewer (agent, all Gitea repos)
- **Quality:** `ToolCorrectnessMetric` (right tools called?) + a G-Eval "review correctness" (did the flagged issue actually exist? penalize false positives hard).
- **Event detectors:** `human_override` (author dismissed the bot's comment = false-positive signal). No distress/cursing — devs interact via PR comments, not chat.
- **Note:** almost no overlap with the chatbot's quality set. Same harness, different metrics — proof that "one generic judge" was the wrong idea.

### 3. CV reviewer (HR)
- **Quality:** `BiasMetric` + toxicity (this is the whole risk surface, not optional), consistency (same CV → same verdict), G-Eval "job-relevance."
- **Event detectors:** `human_override` (recruiter overrode the AI recommendation).
- **HARD CONSTRAINT — data residency:** CV content is personnel data. Every judge on this agent runs through **self-hosted Langfuse only**. No SaaS eval tool ever sees a CV. Bias is the primary metric here, not quality.

---

## 5. Wiring

Each score is emitted to Langfuse, tagged with `agent` and `prompt_version` so scores can be filtered and grouped per trace, per prompt version, and per agent. Langfuse holds the scores for trace-level inspection, filtering, and dataset-building. Keep the emit behind a single helper (`wiring/score_emitter.py`) so the Langfuse SDK is only imported in one place and the backend stays swappable.

**Alerting / drift — deferred, and a known limitation.** Automated "page me when faithfulness drops 15%" is not covered by Langfuse-only; its native capabilities are dashboards and score views, not threshold alerting. For now we rely on reviewing flagged traces in the Langfuse UI. If automated quality-alerting or longitudinal drift detection becomes a requirement, it needs a metrics/alerting layer added on top — a deliberate later step, not part of this standard yet.

**Sampling policy:** judges are LLM calls — cost and latency apply. Default: sample a percentage of production traces (not 100%), use a cheap judge model (a mini/flash-class model beats a frontier model on cost-per-eval and often on accuracy after prompt tuning), low temperature. Full-traffic scoring only for the HR bias metric, where missing a case is worse than the cost.

---

## 6. How to add a new judge (recipe)

1. **Quality metric?** Check DeepEval first. If a built-in fits, use it. If not, write a `G-Eval` with plain-English `evaluation_steps`. Do not hand-roll a judge.
2. **Event detector?** Copy the closest `detectors/*.md`, rewrite the decision rules + few-shot examples for your case. Keep it **binary, narrow, action-tied**.
3. **Wire it** through `score_emitter` so it lands in Langfuse. Tag `agent` + `prompt_version`.
4. **Set a sample rate** and pick the judge model.
5. **Review flagged traces** in the Langfuse UI regularly — this is how detectors surface failure patterns while alerting is deferred.
6. **Tune the judge over time** — a judge prompt is a prompt; it needs improvement like any other.
