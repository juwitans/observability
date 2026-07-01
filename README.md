# LLM Wiki — Agent Observability POC

A small, self-contained demo of what **good observability for LLM apps** actually
looks like — deep multi-stage traces, error surfacing with a self-healing repair
loop, online hallucination/faithfulness scoring, and an improvement loop that turns
flagged production traces into evaluation datasets and prompt experiments.

The app itself is a **Karpathy-style "LLM Wiki"**: a pipeline ingests source articles
and compiles them into cross-linked wiki pages, and a chat front end answers questions
grounded in those pages. Every step is traced in [Langfuse](https://langfuse.com).

> **Two layers.** The *object layer* is the wiki app (ingest pipeline + chat). The
> *meta layer* is the Langfuse telemetry observing it. The corpus happens to be *about
> observability* so you can judge the answers yourself — but the traces are of the
> pipeline, not the articles.

## What it demonstrates

- **Hierarchical tracing** — one trace per ingest/turn, with a span per stage.
- **Error tracking + repair** — stages emit `WARNING`/`ERROR`; a low judge score
  triggers an automatic repair-and-re-judge loop.
- **Online evaluation** — every answer is scored for `faithfulness` and
  `answer_relevance` by an LLM judge.
- **Cost & latency** — captured per generation (model/tokens/cost).
- **The improvement loop** — flagged traces → a Langfuse dataset → a prompt v1-vs-v2
  experiment on that golden set.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Web UI | FastAPI + a single static HTML page |
| Observability | Langfuse (self-hosted, v4 / OpenTelemetry-based) |
| LLM access | any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter, Ollama, …) |
| Structured output | Pydantic v2 |
| Retrieval | dependency-free TF-IDF / cosine over the compiled `wiki/` |
| Storage | local filesystem (`raw/`, `wiki/`) — no database |

## Prerequisites

- Python 3.11 or newer
- A running **self-hosted Langfuse** instance (for the traces/scores/datasets)
- An **OpenAI-compatible LLM endpoint** and API key

## Getting started

```bash
git clone <repo-url>
cd observability-agent

python -m venv .venv
.venv\Scripts\activate           # Windows PowerShell/cmd
# source .venv/bin/activate      # macOS / Linux

pip install -r requirements.txt
cp .env.example .env             # then fill in the values below
```

Configure `.env`:

| Variable | Description |
|---|---|
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse UI → Settings → API Keys |
| `LANGFUSE_BASE_URL` | e.g. `http://localhost:3000` |
| `LLM_BASE_URL` / `LLM_API_KEY` | your OpenAI-compatible endpoint |
| `LLM_MODEL` | main model (write / repair / answer) |
| `LLM_JUDGE_MODEL` | cheaper model for judges / evals |
| `LLM_MODEL_V2` | *(optional)* second model for the experiment |
| `LLM_PRICE_IN` / `LLM_PRICE_OUT` | *(optional)* USD per 1M tokens, for the UI's cost estimate |

## Usage

Start the chat web UI:

```bash
python -m scripts.serve          # open http://localhost:8000
```

Ask a question and each answer shows its faithfulness score, citations, and a live
trace panel (spans, tokens, cost) with a link into Langfuse. Switch the answer prompt
between **weak**, **v1**, and **v2** to watch the faithfulness score move.

To run the full pipeline and evaluation loop from the command line:

```bash
python -m scripts.ingest_all         # compile the corpus into wiki/ pages
python -m scripts.chat_cli           # interactive chat in the terminal
python -m src.evals.build_dataset    # flagged traces → a Langfuse dataset
python -m src.evals.run_experiment   # prompt v1 vs v2 over that dataset
```

> Every script's result is meant to be inspected in the Langfuse UI — that's where the
> traces, scores, sessions, datasets, and experiments show up.

## How it works

**Ingest** — for each source: `fetch → extract → retrieve related pages → write page →
judge → lint links → (repair if flagged) → re-judge`. One trace per source, one span
per stage; the writer/judge/repair steps are LLM generations.

**Chat** — for each turn: `retrieve context → generate answer → faithfulness eval`.
Turns in a conversation are grouped under one Langfuse **session**.

All Langfuse calls live in `src/obs.py`, and all LLM calls go through `src/llm.py`.
Because instrumentation is confined to those two files, the model, provider, and corpus
are swappable without touching any tracing code.

**Instrumentation rules the code follows:**

- Only `src/obs.py` imports `langfuse`; everything else uses its helpers.
- Every deterministic stage is a `span`; every LLM call is a `generation`, so model,
  tokens, and cost are captured automatically.
- Retrieval spans log the **actual retrieved text**, and LLM spans log their arguments
  and raw results — so a wrong answer can always be diagnosed from the trace.
- Failures set `level="WARNING"` / `"ERROR"` with a status message; the repair loop is
  visible as a *low score → WARNING → repair → re-judge* sequence.
- Answer prompts are **versioned in Langfuse** and linked to the generations that use
  them, so a quality change is always attributable to a specific prompt version.

## Project structure

```
src/
  obs.py        # the only file that imports langfuse (spans/scores/sessions/prompts)
  llm.py        # the only LLM wrapper (provider-agnostic, traced as a generation)
  schemas.py    # Pydantic contracts between stages
  store.py      # raw/ + wiki/ filesystem and index builder
  retrieval.py  # TF-IDF/cosine retrieval over wiki/
  pipeline/     # ingest stages: fetch, extract, retrieve, write, judge, lint, repair
  chat/         # retrieve_context, generate_answer, sessions
  evals/        # faithfulness judge, build_dataset, run_experiment
  web/          # FastAPI app + static chat UI
scripts/        # serve, ingest_all, chat_cli, and setup checks
sources.yaml    # the curated corpus of source URLs
```

## Portability

Because instrumentation is confined to `obs.py` / `llm.py` and the corpus is just
`sources.yaml` + `raw/`, the same pipeline can be re-pointed at a completely different
(even bilingual) corpus with **zero changes to the tracing code** — you only swap the
sources. That swap is itself the proof that the observability layer is model-,
framework-, and domain-agnostic.
