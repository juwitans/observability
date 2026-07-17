"""improve/judge_check.py — judge-vs-human agreement (IMPLEMENTATION.md §5.1 step 2).

Meta-eval that gates optimization: before the faithfulness judge is used as an
optimization objective (improve/optimize.py), measure how often it agrees with a
human. Optimizing against an unmeasured judge Goodharts it — score rises, real
quality doesn't.

Two modes:

  1. Build the labeling worksheet (pulls recent judged chat turns from Langfuse):
       python -m src.improve.judge_check --build-worksheet [--limit 50]
     Then a human fills in `human_label: faithful | unfaithful` per case in
     human_labels.yaml (judge the ANSWER against the cited wiki/<slug>.md pages).
     Rebuilding merges: already-filled labels are preserved.

  2. Report agreement (default mode):
       python -m src.improve.judge_check [--threshold 0.7]
     Judge verdict = faithful when judge_faithfulness >= threshold. Prints
     agreement %, the disagreement cases, and a threshold sweep to help pick the
     cutoff. Target: >= ~85-90% agreement before trusting the judge (§7 step 10).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

import yaml

from .. import obs

WORKSHEET = Path(__file__).resolve().parent / "human_labels.yaml"

HEADER = """\
# Judge-trust labeling worksheet (built by: python -m src.improve.judge_check --build-worksheet)
#
# For each case: read the answer, open the cited wiki/<slug>.md pages, and set
#   human_label: faithful     — every claim in the answer is supported by the cited pages
#   human_label: unfaithful   — the answer asserts something the pages don't support
# Leave human_label empty to skip a case. `judge_faithfulness` is what the LLM
# judge said — do NOT let it anchor you; label from the sources.
"""

FAITHFUL = {"faithful", "true", "yes", True}
UNFAITHFUL = {"unfaithful", "false", "no", False}


# ── Worksheet building ───────────────────────────────────────────────────────
def _recent_judged_turns(limit: int) -> list[dict]:
    """Recent chat turns that have a numeric faithfulness score, newest first."""
    res = obs.lf().api.scores.get_many(name="faithfulness", data_type="NUMERIC", limit=limit * 2)
    cases, seen = [], set()
    for s in getattr(res, "data", None) or []:
        trace_id = getattr(s, "trace_id", None)
        value = getattr(s, "value", None)
        if not trace_id or value is None or trace_id in seen:
            continue
        seen.add(trace_id)
        try:
            trace = obs.lf().api.trace.get(trace_id)
        except Exception:
            continue
        tin = getattr(trace, "input", None) or {}
        tout = getattr(trace, "output", None) or {}
        if not isinstance(tin, dict) or not isinstance(tout, dict):
            continue
        question, answer = tin.get("question"), tout.get("answer")
        if not question or not answer:
            continue
        cases.append({
            "trace_id": trace_id,
            "question": question,
            "answer": answer,
            "cited_slugs": tout.get("cited_slugs") or [],
            "judge_faithfulness": round(float(value), 3),
            "human_label": None,
            "notes": "",
        })
        if len(cases) >= limit:
            break
    return cases


def build_worksheet(limit: int) -> int:
    existing: dict[str, dict] = {}
    if WORKSHEET.exists():
        prior = yaml.safe_load(WORKSHEET.read_text(encoding="utf-8")) or {}
        existing = {c["trace_id"]: c for c in prior.get("cases", []) if c.get("trace_id")}

    cases = _recent_judged_turns(limit)
    kept_labels = 0
    for c in cases:
        old = existing.get(c["trace_id"])
        if old and old.get("human_label") is not None:
            c["human_label"], c["notes"] = old["human_label"], old.get("notes", "")
            kept_labels += 1
    # Keep previously labeled cases that fell out of the recent window — labels
    # are expensive; never silently drop one.
    new_ids = {c["trace_id"] for c in cases}
    for tid, old in existing.items():
        if tid not in new_ids and old.get("human_label") is not None:
            cases.append(old)
            kept_labels += 1

    body = yaml.safe_dump({"cases": cases}, allow_unicode=True, sort_keys=False, width=100)
    WORKSHEET.write_text(HEADER + body, encoding="utf-8")
    print(f"Worksheet written: {WORKSHEET}")
    print(f"  {len(cases)} case(s), {kept_labels} already labeled, "
          f"{len(cases) - kept_labels} awaiting a human_label.")
    return 0


# ── Agreement report ─────────────────────────────────────────────────────────
def _human_verdict(label: Any) -> Optional[bool]:
    if isinstance(label, str):
        label = label.strip().lower()
    if label in FAITHFUL:
        return True
    if label in UNFAITHFUL:
        return False
    return None


def report(threshold: float) -> int:
    if not WORKSHEET.exists():
        print("No worksheet yet — run with --build-worksheet first.")
        return 1
    data = yaml.safe_load(WORKSHEET.read_text(encoding="utf-8")) or {}
    labeled = []
    for c in data.get("cases", []):
        human = _human_verdict(c.get("human_label"))
        if human is not None:
            labeled.append((c, human, c["judge_faithfulness"] >= threshold))
    if not labeled:
        print("No labeled cases yet — fill in human_label in the worksheet first.")
        return 1

    agree = [x for x in labeled if x[1] == x[2]]
    missed = [x for x in labeled if x[2] and not x[1]]  # judge faithful, human unfaithful
    alarms = [x for x in labeled if x[1] and not x[2]]  # judge unfaithful, human faithful

    pct = 100 * len(agree) / len(labeled)
    print(f"Judge-vs-human agreement @ threshold {threshold}: "
          f"{pct:.0f}%  ({len(agree)}/{len(labeled)} labeled cases)")
    print(f"  missed hallucinations (judge said faithful, human said unfaithful): {len(missed)}")
    print(f"  false alarms          (judge said unfaithful, human said faithful): {len(alarms)}")
    for name, group in (("MISSED", missed), ("FALSE ALARM", alarms)):
        for c, _, _ in group:
            print(f"    [{name}] judge={c['judge_faithfulness']}  {c['question'][:60]}  ({c['trace_id'][:12]})")

    print("\nThreshold sweep (agreement % at each cutoff):")
    for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        n = sum(1 for c, human, _ in labeled if human == (c["judge_faithfulness"] >= t))
        print(f"  >= {t}: {100 * n / len(labeled):.0f}%")

    gate = "PASSED" if pct >= 85 else "NOT met"
    print(f"\nGate (>=85%): {gate}."
          + ("" if pct >= 85 else " Tune the judge prompt and re-check before running optimize.py."))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-worksheet", action="store_true",
                    help="pull recent judged turns into the labeling worksheet")
    ap.add_argument("--limit", type=int, default=50, help="worksheet size")
    ap.add_argument("--threshold", type=float, default=0.7,
                    help="judge verdict = faithful when score >= this")
    args = ap.parse_args()
    if args.build_worksheet:
        return build_worksheet(args.limit)
    return report(args.threshold)


if __name__ == "__main__":
    raise SystemExit(main())
