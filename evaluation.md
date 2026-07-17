# eval-standard

Company convention for evaluating LLM/agent applications. Not a shared library — a set of conventions each project adopts by copying what it needs.

**Start here:** [`EVAL_STANDARD.md`](./EVAL_STANDARD.md)

## Layout
```
eval-standard/
├── EVAL_STANDARD.md          # the convention: two judge kinds, per-agent mix, wiring, recipe
├── human_override.md         # ← ours; the universal detector (all 3 agents)
├── detectors/                # event-detector prompts (binary, behavioral, cross-agent)
│   ├── user_distress.md      # ✓ authored (wiki chatbot)
│   ├── user_disagreement.md  # ✓ authored (wiki chatbot)
│   ├── out_of_scope.md       # ✓ authored (wiki chatbot)
│   └── insufficient_answer.md# ✓ authored (wiki chatbot)
└── (emitter seam)            # obs.emit_detector_score — see below
```

## The four Langfuse templates — now implemented for the wiki chatbot
`user_distress`, `user_disagreement`, `out_of_scope`, and `insufficient_answer` are published by Langfuse as copy-ready templates:
https://langfuse.com/blog/2026-04-01-llm-as-a-judge-production-monitoring

They are authored under `detectors/` in the same format as `human_override.md` (prompt + why-it-matters + and-then-what + wiring notes), and wired live into the wiki chatbot:

- **Runtime prompts** (managed/versioned in Langfuse): `src/prompts.py` (`DETECT_*`, `WIKI_SCOPE`).
- **Runner:** `src/evals/detectors.py` — one `llm_json` generation per detector on the judge model.
- **Online wiring:** `src/chat/answer.py` — single-turn detectors (`user_distress`, `out_of_scope`) score the current turn; cross-turn detectors (`user_disagreement`, `insufficient_answer`) score the previous turn's trace when the follow-up arrives.
- **Emitter seam:** `obs.emit_detector_score(...)`. This repo keeps the `langfuse` import confined to `src/obs.py` (project rule), so the score-emitter seam lives there rather than in a separate `wiring/score_emitter.py`. It still does the standard's job — one place, tags `agent` + `prompt_version`.
- **Demo/self-check:** `python -m scripts.demo_detectors` replays `src/evals/seed_conversations.yaml`.

## The split, in one line
Quality metrics → adopt DeepEval. Event detectors → own this small library. The harness is shared; the criteria are local.
