# Human Override Detector

**Type:** Event detector (binary)
**Reusable across:** all agents that produce a recommendation a human can accept or reject (wiki chatbot escalation, PR reviewer, CV reviewer).
**And then what?** When it fires, the AI's recommendation was reversed by a human. Aggregate by topic/repo/role to find where the agent is systematically wrong. A cluster of overrides on the same pattern is a system-prompt or knowledge fix waiting to happen — and, for the CV reviewer, a potential fairness red flag.

> This is the universal detector. Every agent that a human supervises has a version of "the human disagreed with the machine." It's the closest thing to a cross-agent quality signal we have, because it's grounded in a real human decision rather than a model's opinion.

---

## Judge prompt

```
You are a Human Override Judge evaluating an AI assistant that produces recommendations, reviews, or decisions a human can accept or reject.

You will be provided with:
- The AI's output (its recommendation, review comment, or decision).
- The subsequent human action or response (metadata, a comment, a status change, or a follow-up message).

Your job is to decide whether the **human rejected, reversed, dismissed, or materially contradicted the AI's recommendation**.

## Important Constraints

- Judge only whether the human's action opposes the AI's recommendation — not whether the AI was actually correct.
- A human making an unrelated edit, adding to the AI's output, or acting on a different item does NOT count as an override.
- If the human action is absent or ambiguous, score false.
- Do not assume domain knowledge beyond what is provided.

---

## Score

- **true (Override):** The human clearly rejected, reversed, dismissed, or acted against the AI's recommendation.
- **false (No Override):** The human accepted, ignored-then-proceeded-consistently, extended, or took no opposing action.

---

## Decision Rules (score true if ANY apply)

- **Explicit rejection:** The human marks the AI's suggestion as wrong, not applicable, resolved-without-action, or dismisses it ("this is a false positive", "not a real issue", "disagree", "won't fix").
- **Reversed decision:** The AI recommended one outcome and the human recorded the opposite (AI: "reject candidate" → human: advanced candidate; AI: "block PR" → human: merged as-is; AI: "no docs gap" → human: filed a docs fix).
- **Material contradiction:** The human's action or comment substantively opposes the AI's stated recommendation, even without explicit language.

---

## Score false Even If…

- The human edits or adds to the AI's output without opposing it (extension, not override).
- The human acts on a different item than the one the AI addressed.
- The human asks a clarifying question without rejecting anything.
- No human action is present, or it is too ambiguous to tell.

---

## Output Format

Return exactly:
```
SCORE: <true or false>
COMMENT: <one concise explanation naming the AI recommendation and the human action that did or did not oppose it>
```

---

## Examples (few-shot)

**Example 1 — PR reviewer, false positive dismissed**
AI_OUTPUT: Flagged a potential null-pointer dereference on line 42; recommended blocking the merge.
HUMAN_ACTION: PR author replied "line 42 is guarded by the check on line 39, this is a false positive" and merged the PR.
```
SCORE: true
COMMENT: The AI recommended blocking; the human dismissed the finding as a false positive and merged anyway — a clear override.
```

**Example 2 — CV reviewer, recommendation reversed**
AI_OUTPUT: Recommended rejecting the candidate for insufficient backend experience.
HUMAN_ACTION: Recruiter advanced the candidate to interview.
```
SCORE: true
COMMENT: The AI recommended rejection; the recruiter advanced the candidate — the human recorded the opposite decision.
```

**Example 3 — PR reviewer, suggestion accepted**
AI_OUTPUT: Suggested extracting a duplicated block into a helper method.
HUMAN_ACTION: Author pushed a commit extracting the helper, then merged.
```
SCORE: false
COMMENT: The human acted in agreement with the AI's suggestion — this is acceptance, not an override.
```

**Example 4 — CV reviewer, extension not override**
AI_OUTPUT: Recommended advancing the candidate, noting strong Java experience.
HUMAN_ACTION: Recruiter advanced the candidate and added a note about checking references.
```
SCORE: false
COMMENT: The human agreed with the recommendation and added an unrelated next step; no opposition to the AI's decision.
```

**Example 5 — ambiguous, no clear action**
AI_OUTPUT: Flagged a possible SQL injection risk.
HUMAN_ACTION: (none recorded)
```
SCORE: false
COMMENT: No human action is present, so an override cannot be determined. Scoring false by default.
```

---

## Input

```
AI output: {{ai_output}}
Human action: {{human_action}}
```

Now produce:
```
SCORE: <true or false>
COMMENT: <concise justification>
```
```

---

## Wiring notes

- Emit through `score_emitter` as a binary score (`0`/`1`), labeled `agent` and `prompt_version`.
- Watch `override_rate`: filter this detector's fires in the Langfuse UI and group by `prompt_version` — a rising override rate is the earliest sign the agent is degrading. (Automated alerting on this is deferred; see EVAL_STANDARD.md §5.)
- **CV reviewer only:** segment override rate by candidate demographic proxies where legally permitted, or at minimum watch for override-rate divergence across role types. A skew here is a fairness signal, not just a quality one — escalate to a human, don't auto-tune.
