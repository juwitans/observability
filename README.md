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

## What's traced & scored (signals reference)

Everything below is emitted from `src/obs.py` (spans/scores/sessions) and
`src/llm.py` (generations). There are **two trace types**.

**Ingest — one trace per source URL:**

```
ingest_source                 root span · wiki.repair.round · WARNING/ERROR
├─ fetch_source               span
│  └─ http_get                span · http.*/url.* attrs · WARN <500B, ERROR ≥400
├─ extract_md                 span · wiki.extract.extractor = trafilatura|lxml_fallback
├─ retrieve_related           span · gen_ai.data_source.id=wiki · logs retrieved text
├─ write_page                 generation · prompt=write_page
├─ judge_page                 generation · prompt=judge_page
├─ lint_links                 span · deterministic, no LLM
└─ [repair loop ×≤2]  repair_page (gen) → judge_page (gen) → lint_links
```

**Chat — one trace per turn (`chat_turn`), grouped under a Langfuse session:**

```
chat_turn                     root span · session_id + user_id
├─ retrieve_context           span · gen_ai.data_source.id=wiki · logs chunks
├─ generate_answer            generation · prompt = v1 | v2 | weak
└─ faithfulness_eval          generation · the hallucination judge
```

**Scores (online evaluation):**

| Trace | Score | Type | Emitted by |
|---|---|---|---|
| Ingest | `groundedness` | NUMERIC 0–1 | `judge_page` |
| Ingest | `faithfulness` | BOOLEAN | `judge_page` |
| Ingest | `lint_pass` | BOOLEAN | `lint_links` |
| Ingest | `lint_issue_count` | NUMERIC | `lint_links` |
| Chat | `faithfulness` | NUMERIC 0–1 | `faithfulness_eval` |
| Chat | `answer_relevance` | NUMERIC 0–1 | `faithfulness_eval` |
| Chat | `user_distress` | BOOLEAN | event detector |
| Chat | `out_of_scope` | BOOLEAN | event detector |
| Chat | `user_disagreement` | BOOLEAN | event detector *(scores the prior turn)* |
| Chat | `insufficient_answer` | BOOLEAN | event detector *(scores the prior turn)* |

**Event detectors vs. quality metrics.** The first two chat scores are *quality
metrics* ("how good, 0–1?"). The four BOOLEAN ones are *event detectors* ("did X
happen, yes/no?") from `EVAL_STANDARD.md §3` — binary, narrow, action-tied. Two are
single-turn (judge the current user message); two are **cross-turn** — they judge the
*previous* answer against the follow-up message, so their score attaches to the prior
turn's trace. They run online inside `chat_turn`, are emitted through the
`obs.emit_detector_score` seam (tagged `agent` + `prompt_version`), and surface as
chips in the web UI. Prompts: `src/prompts.py`; runner: `src/evals/detectors.py`;
specs: `detectors/`. Replay demo: `python -m scripts.demo_detectors`. Sampling knob:
`DETECTOR_SAMPLE_RATE` (default 1.0).

**Per-generation quantitative capture:** model name, input/output/total **tokens**,
**cost** (USD, computed by Langfuse from the model price map), and **latency** —
captured automatically because every LLM call is a `generation` with a `model`.
Failing stages set **`level="WARNING"`/`"ERROR"`** with a status message.

> These are span-attached quantities that Langfuse aggregates into dashboards —
> not OpenTelemetry *metrics* (no counters/histograms are exported).

## OpenTelemetry vs. Langfuse — what's what

Langfuse v4 runs on OpenTelemetry, so *everything* here is emitted as OTel spans.
But that doesn't make it all portable: most fields are carried under `langfuse.*`
attribute keys that only Langfuse understands. Verified against the installed SDK
(`langfuse/_client/attributes.py`), the signals fall into **three** buckets.

**A. Native OTel — a generic OTel backend recognizes these as-is**

- The **trace/span tree** — parent/child nesting, context propagation, trace/span
  IDs, timings.
- **`session.id`** and **`user.id`** — `obs.session(session_id, user_id)` maps onto
  these registered OTel semantic-convention attributes.
- The **`OTEL_SEMCONV_STABILITY_OPT_IN`** SDK opt-in (`obs.py`).

**B. Real OTel spans, but Langfuse-keyed attributes** — the *structure* ports; the
*payload keys* don't. Everything below is set through the Langfuse SDK and lands
under a `langfuse.observation.*` key:

| What the code sets | OTel attribute actually emitted |
|---|---|
| `as_type="span"`/`"generation"` | `langfuse.observation.type` |
| `model=` → tokens/cost | `langfuse.observation.model.name` / `…usage_details` / `…cost_details` |
| `input=` / `output=` | `langfuse.observation.input` / `…output` |
| `level` + `status_message` | `langfuse.observation.level` / `…status_message` |
| `prompt=` link | `langfuse.observation.prompt.name` / `…version` |
| **any `metadata={…}`** | `langfuse.observation.metadata.<key>` |

> **Caveat on the "OTel" attribute names.** The conventionally-named keys the stages
> set — `gen_ai.data_source.id`, `http.request.method`, `url.full`,
> `http.response.status_code`, and the private `wiki.*` keys — are all passed as
> **metadata**, so they're flattened under `langfuse.observation.metadata.` (e.g.
> `langfuse.observation.metadata.gen_ai.data_source.id`). They're *named* per OTel
> convention (deliberate, to signal intent and ease a future remap) but are **not**
> emitted as canonical top-level OTel GenAI/HTTP attributes.

**C. Pure Langfuse — no OTel representation at all** (separate ingestion/API):

- **Scores** — `groundedness`, `faithfulness`, `answer_relevance`, `lint_pass`,
  `lint_issue_count`.
- **Managed/versioned prompts**, **datasets & experiments**, the **cost computation**
  (usage keys × model price map), and the deep-link/query helpers.

**Swapping backends** means rewriting only `src/obs.py` (point an OTLP exporter at
your collector — not wired today). You'd keep the span tree, sessions, and users for
free; you'd remap every `langfuse.observation.*` key; and you'd have to rebuild
scores/prompts/datasets yourself.

> **Mental model:** *structure and identity are OTel (portable); semantics and
> evaluation are Langfuse.*

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

## Point it at a different corpus

The pipeline is domain-agnostic — to make the chatbot answer about something else, you
only edit **`sources.yaml`** and re-run ingest. No tracing or app code changes.

1. Replace the entries in `sources.yaml` with your own sources:

   ```yaml
   sources:
     - url: https://example.com/some-article
       topic: llm            # required; see the constraint below
       stance: "…"           # optional human note (ignored by the loader)
   ```

2. Rebuild the corpus:

   ```bash
   python -m scripts.ingest_all
   ```

3. Run the chat UI — it now answers from the new pages.

Things to know:

- **`raw/` and `wiki/` are generated, not hand-edited.** Ingest fetches each URL,
  writes the cleaned markdown to `raw/`, and compiles cross-linked pages into `wiki/`.
  Both are regenerated on every run (and are gitignored).
- **`topic` must be one of** `traditional`, `otel`, `llm`, or `contrarian` (defined in
  `src/schemas.py`). Map your sources onto those, or edit that one line to use your own
  set of topics.
- Sources must be **fetchable public URLs** — the pipeline downloads and extracts the
  main article body at ingest time.

Swapping the corpus with zero instrumentation changes is itself the point: it shows the
observability layer is model-, framework-, and domain-agnostic.
