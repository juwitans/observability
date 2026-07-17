"""Replay scripted conversations to exercise the EVENT DETECTORS (EVAL_STANDARD §3).

Each conversation in src/evals/seed_conversations.yaml is engineered to trip one
detector on a specific turn. This runs them through the real `chat_turn` so the
detector scores land in Langfuse, and prints a PASS/FAIL self-check of whether the
expected detector fired (a quick read on the DETECTORS' accuracy, separate from the
chatbot's answer quality).

Cross-turn detectors (user_disagreement, insufficient_answer) fire on the FOLLOW-UP
message and score the PREVIOUS turn's trace — so watch for their flags on turn 2.

Run:  python -m scripts.demo_detectors
      python -m scripts.demo_detectors --variant v2
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import yaml

from src import obs
from src.chat.answer import chat_turn

SEED = Path(__file__).resolve().parents[1] / "src" / "evals" / "seed_conversations.yaml"

# Which detector class fires on the turn it's judged from.
_CROSS_TURN = {"user_disagreement", "insufficient_answer"}


def _fired(result, name: str) -> bool:
    """Was detector `name` fired on this turn? Cross-turn flags live in
    `prior_detectors` (they judge the previous answer); single-turn in `detectors`."""
    bucket = result.prior_detectors if name in _CROSS_TURN else result.detectors
    v = bucket.get(name)
    return bool(v and v.fired)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v1", choices=["v1", "v2", "weak"])
    args = ap.parse_args()

    convos = yaml.safe_load(SEED.read_text(encoding="utf-8"))["conversations"]
    passes = failures = 0

    for convo in convos:
        session_id = f"detect-{convo['name']}-{uuid.uuid4().hex[:6]}"
        print(f"\n=== {convo['name']}  (session {session_id}) ===")
        for i, turn in enumerate(convo["turns"], 1):
            msg = turn["msg"]
            expected = set(turn.get("expect") or [])
            r = chat_turn(msg, session_id=session_id, user_id="detector-demo", variant=args.variant)
            obs.flush()

            all_flags = {**r.detectors, **r.prior_detectors}
            fired = {name for name, v in all_flags.items() if v.fired}
            print(f"[turn {i}] you> {msg[:80]}{'...' if len(msg) > 80 else ''}")
            print(f"          fired: {sorted(fired) or '—'}")

            for name in expected:
                ok = _fired(r, name)
                print(f"          {'PASS' if ok else 'FAIL'}: expected '{name}' to fire")
                passes += ok
                failures += not ok

    obs.flush()
    print(f"\nDone. Self-check: {passes} passed, {failures} failed. "
          f"Inspect the detector scores per session in the Langfuse UI.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
