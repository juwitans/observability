"""Non-interactive multi-turn chat demo (Gates 5 & 6).

Runs a scripted conversation as ONE session so you can see the multi-turn session
replay + faithfulness scores in Langfuse without typing.

Run:  python -m scripts.chat_demo                 # grounded (v1)
      python -m scripts.chat_demo --weak           # weak prompt -> low faithfulness
      python -m scripts.chat_demo --variant v2     # strict grounding
"""
from __future__ import annotations

import argparse
import sys
import uuid

from src import obs
from src.chat.answer import chat_turn

TURNS = [
    "How does LLM observability differ from traditional observability?",
    "Which of those differences matters most for catching hallucinations?",
    "So are the traditional three pillars useless for LLM apps?",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v1", choices=["v1", "v2", "weak"])
    ap.add_argument("--weak", action="store_true")
    args = ap.parse_args()
    variant = "weak" if args.weak else args.variant

    session_id = f"demo-{variant}-{uuid.uuid4().hex[:6]}"
    print(f"Session: {session_id}  (variant: {variant})\n")

    for i, q in enumerate(TURNS, 1):
        print(f"[turn {i}] you> {q}")
        r = chat_turn(q, session_id=session_id, user_id="demo-user", variant=variant)
        obs.flush()
        print(f"          bot> {r.answer.answer[:280]}{'...' if len(r.answer.answer) > 280 else ''}")
        print(f"          cites={r.answer.cited_slugs}  "
              f"faithfulness={r.faithfulness.faithfulness:.2f}  "
              f"relevance={r.faithfulness.answer_relevance:.2f}\n")

    obs.flush()
    print(f"Done. Open session '{session_id}' in Langfuse for the multi-turn replay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
