"""Run the ingest pipeline over sources.yaml (one trace per source).

Run:  python -m scripts.ingest_all            # all sources
      python -m scripts.ingest_all --limit 1  # just the first (Step 3 gate)
      python -m scripts.ingest_all --url https://...  # a single URL
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from src import obs
from src.pipeline.ingest import ingest_source

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources.yaml"


def load_sources() -> list[dict]:
    data = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    return data.get("sources", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="ingest only the first N sources")
    ap.add_argument("--url", type=str, default=None, help="ingest a single URL")
    ap.add_argument("--topic", type=str, default="llm", help="topic for --url")
    args = ap.parse_args()

    if args.url:
        sources = [{"url": args.url, "topic": args.topic}]
    else:
        sources = load_sources()
        if args.limit:
            sources = sources[: args.limit]

    print(f"Ingesting {len(sources)} source(s)...\n")
    results = []
    for i, src in enumerate(sources, 1):
        url, topic = src["url"], src.get("topic", "llm")
        print(f"[{i}/{len(sources)}] {url}")
        outcome = ingest_source(url, topic)
        results.append(outcome)
        if outcome.error:
            print(f"    ERROR: {outcome.error}")
        else:
            print(
                f"    -> {outcome.slug}  groundedness={outcome.final_groundedness} "
                f"faithful={outcome.final_faithful} lint_passed={outcome.lint_passed} "
                f"repairs={outcome.repairs}"
            )
        obs.flush()

    ok = sum(1 for r in results if r.saved)
    print(f"\nDone. {ok}/{len(results)} pages saved. Inspect traces in Langfuse.")
    obs.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
