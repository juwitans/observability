"""improve/harvest.py — the automated sensor->dataset feed (IMPLEMENTATION.md §5.1).

Queries Langfuse for chat traces since the last run where a quality score fell
below threshold (faithfulness) OR an answer-failure detector fired
(user_disagreement / insufficient_answer), and appends them as items to the
hard-cases dataset. This automates the manual step in evals/build_dataset.py so
training data accumulates unattended from production traffic.

Idempotent by construction: item ids are deterministic (sha1 of dataset+question,
same scheme as build_dataset.py) so re-runs upsert instead of duplicating, and a
high-water mark in .harvest_state.json skips already-seen scores.

Only detectors that judge the ANSWER are harvested by default — out_of_scope and
user_distress describe the user's message, not answer quality, so their traces
don't belong in a generation-improvement dataset (EVAL_STANDARD.md §4).

Run:  python -m src.improve.harvest
      python -m src.improve.harvest --threshold 0.7 --dry-run
      python -m src.improve.harvest --all          # ignore the high-water mark
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import obs, retrieval

STATE_FILE = Path(__file__).resolve().parents[2] / ".harvest_state.json"

QUALITY_SCORE = "faithfulness"
DEFAULT_DETECTORS = ("user_disagreement", "insufficient_answer")
# Traces where these detectors fired are EXCLUDED: an out-of-scope question's
# refusal legitimately scores low on faithfulness, but it isn't a generation
# failure and would pollute the hard-cases dataset.
EXCLUDE_DETECTORS = ("out_of_scope",)


# ── High-water mark ──────────────────────────────────────────────────────────
def _load_since(path: Path) -> Optional[datetime]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(raw["last_run"])
    except Exception:
        return None


def _save_since(path: Path, dt: datetime) -> None:
    path.write_text(json.dumps({"last_run": dt.isoformat()}), encoding="utf-8")


def _score_time(score: Any) -> Optional[datetime]:
    ts = getattr(score, "timestamp", None)
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return ts


def _is_new(score: Any, since: Optional[datetime]) -> bool:
    if since is None:
        return True
    ts = _score_time(score)
    if ts is None:
        return True  # can't date it -> keep it; the deterministic item id dedups
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts > since


# ── Flagged-score queries (self-hosted-safe: scores endpoint, not v2 obs) ────
def _low_quality(threshold: float, limit: int, since: Optional[datetime]) -> list[Any]:
    res = obs.lf().api.scores.get_many(
        name=QUALITY_SCORE,
        data_type="NUMERIC",
        operator="<",
        value=threshold,
        limit=limit * 3,
    )
    return [s for s in (getattr(res, "data", None) or []) if _is_new(s, since)]


def _fired_detectors(names: tuple[str, ...], limit: int, since: Optional[datetime]) -> list[Any]:
    out: list[Any] = []
    for name in names:
        try:
            res = obs.lf().api.scores.get_many(name=name, data_type="BOOLEAN", limit=limit * 3)
        except Exception as e:  # noqa: BLE001
            print(f"    (skipping detector '{name}': {e})")
            continue
        for s in getattr(res, "data", None) or []:
            if getattr(s, "value", 0) and _is_new(s, since):
                out.append(s)
    return out


def _trace_question(trace_id: str) -> Optional[str]:
    try:
        tin = getattr(obs.lf().api.trace.get(trace_id), "input", None) or {}
        return tin.get("question") if isinstance(tin, dict) else None
    except Exception:
        return None


# ── Harvest ──────────────────────────────────────────────────────────────────
def harvest(
    dataset: str,
    threshold: float,
    detectors: tuple[str, ...],
    limit: int,
    since: Optional[datetime],
    dry_run: bool,
) -> int:
    flagged = [(QUALITY_SCORE, s) for s in _low_quality(threshold, limit, since)]
    flagged += [(getattr(s, "name", "detector"), s) for s in _fired_detectors(detectors, limit, since)]
    excluded = {
        getattr(s, "trace_id", None)
        for s in _fired_detectors(EXCLUDE_DETECTORS, limit, since=None)  # exclusion is timeless
    }

    # One candidate per trace; a trace flagged by several signals keeps them all
    # as reasons so the dataset item records WHY it was harvested.
    by_trace: dict[str, dict] = {}
    skipped_oos = 0
    for reason, s in flagged:
        trace_id = getattr(s, "trace_id", None)
        if not trace_id:
            continue
        if trace_id in excluded:
            skipped_oos += 1
            continue
        entry = by_trace.setdefault(trace_id, {"trace_id": trace_id, "reasons": {}})
        entry["reasons"][reason] = getattr(s, "value", None)
    if skipped_oos:
        print(f"  ({skipped_oos} flagged score(s) skipped: trace was out-of-scope)")

    candidates = list(by_trace.values())[:limit]
    print(f"Harvesting into '{dataset}': {len(flagged)} flagged score(s) -> "
          f"{len(candidates)} candidate trace(s)"
          + (f" since {since.isoformat()}" if since else " (no high-water mark)"))

    if not dry_run and candidates:
        try:
            obs.lf().get_dataset(dataset)
        except Exception:
            obs.lf().create_dataset(name=dataset)

    added = 0
    for c in candidates:
        question = _trace_question(c["trace_id"])
        if not question:
            print(f"  - skip {c['trace_id'][:12]}: no question on trace input")
            continue
        reasons = ", ".join(f"{k}={v}" for k, v in c["reasons"].items())
        if dry_run:
            print(f"  ~ would add [{reasons}] {question[:64]}")
            added += 1
            continue
        chunks = retrieval.search(question, top_k=3)
        item_id = hashlib.sha1(f"{dataset}:{question}".encode()).hexdigest()[:16]
        obs.lf().create_dataset_item(
            dataset_name=dataset,
            id=item_id,  # deterministic -> re-runs upsert instead of duplicating
            input={"question": question, "chunks": chunks},
            expected_output="",
            metadata={
                "source": "improve/harvest",
                "trace_id": c["trace_id"],
                "reasons": c["reasons"],
                "original_faithfulness": c["reasons"].get(QUALITY_SCORE),
                "harvested_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        added += 1
        print(f"  + [{reasons}] {question[:64]}  ({len(chunks)} chunks)")

    if not dry_run:
        obs.flush()
    print(f"\nDone. {added} item(s) {'would be ' if dry_run else ''}written to '{dataset}'.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", default="chat-hard-cases")
    ap.add_argument("--threshold", type=float, default=0.7,
                    help=f"harvest traces with {QUALITY_SCORE} below this")
    ap.add_argument("--detectors", default=",".join(DEFAULT_DETECTORS),
                    help="comma-separated detector score names to harvest on")
    ap.add_argument("--limit", type=int, default=20, help="max traces per run")
    ap.add_argument("--all", action="store_true", help="ignore the high-water mark")
    ap.add_argument("--dry-run", action="store_true", help="show candidates, write nothing")
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    since = None if args.all else _load_since(STATE_FILE)
    detectors = tuple(d.strip() for d in args.detectors.split(",") if d.strip())

    rc = harvest(args.dataset, args.threshold, detectors, args.limit, since, args.dry_run)
    if rc == 0 and not args.dry_run:
        _save_since(STATE_FILE, started)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
