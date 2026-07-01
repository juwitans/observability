# LLM Wiki — Agent Observability POC

A from-scratch proof that **adequate agent observability** is more than cost/latency
dashboards: deep multi-stage traces, error surfacing + a self-healing repair loop,
online hallucination/faithfulness evaluation, and a historical-data improvement loop
(datasets → experiments).

> **Two layers, never blurred.** The *object layer* is this wiki app (an ingest
> pipeline + a chat front end). The *meta layer* is Langfuse telemetry. The corpus
> happens to be *about* observability so you can judge the answers yourself — but the
> spans are *of the pipeline*, not the articles.

Backend: **self-hosted Langfuse** (v4, OTel-based). Instrumentation lives only in
`src/obs.py` (+ the `src/llm.py` wrapper), so the model, framework, and corpus are all
swappable without touching instrumentation.

---

## Quick start (easiest — the web chat UI)

The dependencies are already installed in the bundled `.venv`. **Call that venv's
Python directly** — this avoids the `No module named langfuse` error you get when the
venv isn't activated and the system Python runs instead:

```powershell
# from the project root (PowerShell)
.venv\Scripts\python.exe -m scripts.serve
# then open http://localhost:8000
```

> **Why not just `python -m scripts.serve`?** Plain `python` resolves to your *system*
> Python, which doesn't have `langfuse` installed — hence `No module named langfuse`.
> `.venv\Scripts\python.exe` is the interpreter that has every dependency, so it always
> works regardless of whether the venv is "activated" in the current shell.

Prefer activating once, then using plain `python` for the rest of the session:

```powershell
.venv\Scripts\Activate.ps1        # PowerShell  (.venv\Scripts\activate.bat for cmd.exe)
python -m scripts.serve           # now `python` == the venv Python
```

If activation is blocked by PowerShell execution policy, either use the direct-path form
above, or allow it for this session:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

---

## Setup (fresh clone — deps not yet installed)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on *nix)
pip install -r requirements.txt
cp .env.example .env              # then fill in your keys
```

Fill `.env`:

| Var | What |
|---|---|
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | from Langfuse UI → Settings → API Keys |
| `LANGFUSE_BASE_URL` | e.g. `http://localhost:3000` (note: `BASE_URL`, not `BASEURL`) |
| `LLM_BASE_URL` / `LLM_API_KEY` | your OpenAI-compatible endpoint |
| `LLM_MODEL` | main model (write / repair / answer) |
| `LLM_JUDGE_MODEL` | cheaper model (judges / evals) |
| `LLM_MODEL_V2` | optional second model for the experiment |

> Models are chosen **per call**, so you can swap them freely and compare
> cost/latency per generation in Langfuse.

---

## Run order (each step has a Langfuse-UI verification gate)

> The `python` below assumes the venv is **activated**. If it isn't, swap `python` for
> `.venv\Scripts\python.exe` in every command (see Quick start above).

```bash
python -m scripts.check_setup            # 1. throwaway trace 'setup_check' appears
python -m scripts.smoke_llm              # 2. one traced LLM call w/ tokens + cost
python -m scripts.ingest_all --limit 1   # 3. one source end-to-end; inspect the trace tree
python -m scripts.ingest_all             # 4. full corpus; wiki/ + wiki/index.md build
python -m scripts.chat_cli               # 5. multi-turn chat grouped under one session
#   (faithfulness scores appear automatically on each turn — step 6)
python -m src.evals.build_dataset        # 7a. flagged traces -> 'chat-hard-cases' dataset
python -m src.evals.run_experiment       # 7b. answer-v1 vs answer-v2 experiment
```

### Easiest demo: the web chat UI

```bash
python -m scripts.serve        # then open http://localhost:8000
```

A single-page chat. Pick the answer-prompt variant (**v1** grounded · **v2** strict ·
**weak** hallucination-prone), ask a question, and each answer shows its faithfulness
score, citations, and a **“view trace ↗”** link straight into Langfuse. Ask the same
question with **weak** then **v2** to watch the faithfulness score jump — that's the
hallucination story in one screen. There's also a non-interactive scripted version:
`python -m scripts.chat_demo --weak`.

---

## Demo script

Frame it once: *"The bottom layer (Langfuse) observes the top layer (the wiki
pipeline). The pipeline is reading about observability so you can judge the answers
yourselves."*

**Moment 1 — deep trace + repair (fix-it-fast).**
Run `python -m scripts.ingest_all --limit 1` live and open the `ingest_source` trace.
Show the multi-stage tree (`fetch_source → extract_md → retrieve_related → write_page
→ judge_page → lint_links → repair_page → judge_page`), per-stage latency/cost, the
`groundedness`/`faithfulness` scores, and a case where `lint_links` raised a WARNING
and `repair_page` fired and re-judged clean. Contrast with a single-span HR-bot trace.

**Moment 2 — hallucination caught + the loop (improve-over-time).**
In chat, ask *"How does LLM observability differ from traditional observability?"*
Show the session replay (multi-turn grouped by `session_id`), the answer + citations,
and the `faithfulness` score. Then generate a weak answer:
`python -m scripts.chat_cli --weak` → a low-faithfulness trace → `build_dataset` pulls
it into the golden set → `run_experiment` shows **answer-v2 beating answer-v1** on
faithfulness. The delta is the artifact.

Close on the rubric (IMPLEMENTATION.md Appendix B): tick off each capability.

---

## Architecture

```
src/
  obs.py        # ONLY file that imports langfuse — span/score/session/prompt helpers
  llm.py        # ONLY LLM wrapper — provider-agnostic, traced as a generation
  schemas.py    # Pydantic contracts between stages
  store.py      # raw/ + wiki/ filesystem; index builder
  retrieval.py  # dependency-free TF-IDF/cosine over wiki/
  pipeline/     # fetch → extract → retrieve → write → judge → lint → repair → ingest
  chat/         # retrieve_context → generate_answer (+ sessions) → faithfulness_eval
  evals/        # faithfulness judge, build_dataset, run_experiment
scripts/        # check_setup, smoke_llm, ingest_all, chat_cli
sources.yaml    # curated corpus (overlapping + contradictory sources)
```

**Instrumentation invariants**
- Only `src/obs.py` imports `langfuse`; everything else uses its helpers.
- Every deterministic stage is a `span`; every LLM call is a `generation`
  (model/tokens/cost captured automatically).
- Retrieval spans log the **actual retrieved text**; LLM spans log args + raw results.
- Errors set `level="WARNING"/"ERROR"` + `status_message`; the repair loop is visible
  as a low score → WARNING → repair → re-judge sequence.
- Prompts are **managed/versioned** in Langfuse and linked to their generations.

---

## Phase 2 — "applies anywhere" (designed for, not built)

Because instrumentation is confined to `obs.py`/`llm.py` and the corpus is just
`sources.yaml` + `raw/`, the same pipeline can be re-pointed at a different, even
bilingual corpus (e.g. koreanwikiproject.com) with **zero instrumentation changes** —
new sources only. That swap is itself the proof that the observability layer is model-,
framework-, and domain-agnostic. Kept out of phase 1 so the eval layer stays clean
(monolingual ground truth).
