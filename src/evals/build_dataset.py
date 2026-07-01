"""build_dataset.py — flagged chat traces -> a Langfuse dataset ("golden set").

Queries Langfuse for chat answers with low `faithfulness`, and pushes each as a
dataset item {question, retrieved context (chunks), notes}. The retrieved context
is reconstructed deterministically from the current wiki so experiments are
comparable. Falls back to a curated seed set (seed_cases.yaml) when no flagged
traces are found yet.

Run:  python -m src.evals.build_dataset
      python -m src.evals.build_dataset --threshold 0.6 --dataset chat-hard-cases
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml

from .. import obs, retrieval

SEED = Path(__file__).resolve().parent / "seed_cases.yaml"


def _ensure_dataset(name: str) -> None:
    try:
        obs.lf().get_dataset(name)
    except Exception:
        obs.lf().create_dataset(name=name)


def _chunks_for(question: str, top_k: int = 3) -> list[dict]:
    return retrieval.search(question, top_k=top_k)


def _low_faithfulness_questions(threshold: float, limit: int) -> list[dict]:
    """Best-effort pull of low-faithfulness chat questions from Langfuse.

    The self-hosted v2 observations/metrics endpoints are unavailable, so we go
    through scores + traces. Wrapped defensively; returns [] on any API quirk so
    the seed fallback can take over.
    """
    out: list[dict] = []
    try:
        api = obs.lf().api
        # Numeric faithfulness scores below threshold (self-hosted-safe: scores
        # endpoint is unaffected by the v2 observations/metrics caveat).
        scores = api.scores.get_many(
            name="faithfulness",
            data_type="NUMERIC",
            operator="<",
            value=threshold,
            limit=limit * 3,
        )
        seen: set[str] = set()
        for s in getattr(scores, "data", []) or []:
            value = getattr(s, "value", None)
            trace_id = getattr(s, "trace_id", None)
            if value is None or trace_id is None or trace_id in seen:
                continue
            seen.add(trace_id)
            trace = api.trace.get(trace_id)
            tin = getattr(trace, "input", None) or {}
            question = tin.get("question") if isinstance(tin, dict) else None
            if question:
                out.append({"question": question, "faithfulness": value, "trace_id": trace_id})
            if len(out) >= limit:
                break
    except Exception as e:  # noqa: BLE001
        print(f"    (Langfuse query unavailable: {e}; using seed fallback)")
    return out


def _seed_questions() -> list[dict]:
    data = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    return [{"question": c["question"], "notes": c.get("notes", "")} for c in data["cases"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--dataset", default="chat-hard-cases")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--seed-only", action="store_true", help="ignore Langfuse, use seed set")
    args = ap.parse_args()

    _ensure_dataset(args.dataset)

    # Harvested low-faithfulness traces first, then top up with seed cases so the
    # golden set is never empty. Dedup by question; items are idempotent by id.
    harvested = [] if args.seed_only else _low_faithfulness_questions(args.threshold, args.limit)
    for c in harvested:
        c["source"] = "Langfuse low-faithfulness traces"
    seen = {c["question"] for c in harvested}
    seed = [c for c in _seed_questions() if c["question"] not in seen]
    for c in seed:
        c["source"] = "seed_cases.yaml"
    cases = harvested + seed

    print(f"Building dataset '{args.dataset}' from {len(cases)} case(s) "
          f"({len(harvested)} harvested + {len(seed)} seed)...")
    for c in cases:
        question = c["question"]
        chunks = _chunks_for(question)
        item_id = hashlib.sha1(f"{args.dataset}:{question}".encode()).hexdigest()[:16]
        obs.lf().create_dataset_item(
            dataset_name=args.dataset,
            id=item_id,  # deterministic -> re-runs upsert instead of duplicating
            input={"question": question, "chunks": chunks},
            expected_output=c.get("notes", ""),
            metadata={
                "source": c.get("source"),
                "trace_id": c.get("trace_id"),
                "original_faithfulness": c.get("faithfulness"),
            },
        )
        print(f"  + [{c.get('source','?')[:6]}] {question[:64]}  ({len(chunks)} chunks)")

    obs.flush()
    print(f"\nDone. Dataset '{args.dataset}' ready in Langfuse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
