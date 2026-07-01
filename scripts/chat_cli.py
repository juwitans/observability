"""Interactive chat session over the compiled wiki (one session per run).

Run:  python -m scripts.chat_cli
      python -m scripts.chat_cli --weak   # deliberately weak prompt (low faithfulness)
      python -m scripts.chat_cli --variant v2

Every turn is a trace; the whole conversation is grouped under one session_id,
so you can watch the multi-turn session replay in Langfuse.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from src import obs
from src.chat.answer import chat_turn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v1", choices=["v1", "v2", "weak"])
    ap.add_argument("--weak", action="store_true", help="shortcut for --variant weak")
    ap.add_argument("--session", default=None, help="reuse a session id")
    ap.add_argument("--user", default="demo-user")
    args = ap.parse_args()

    variant = "weak" if args.weak else args.variant
    session_id = args.session or f"chat-{uuid.uuid4().hex[:8]}"

    print(f"Session: {session_id}  (variant: {variant})")
    print("Ask about observability. Ctrl-C or 'exit' to quit.\n")

    try:
        while True:
            try:
                q = input("you> ").strip()
            except EOFError:
                break
            if not q or q.lower() in {"exit", "quit"}:
                break

            result = chat_turn(q, session_id=session_id, user_id=args.user, variant=variant)
            obs.flush()

            print(f"\nbot> {result.answer.answer}")
            if result.answer.cited_slugs:
                print(f"     cites: {', '.join(result.answer.cited_slugs)}")
            print(
                f"     [faithfulness={result.faithfulness.faithfulness:.2f} "
                f"relevance={result.faithfulness.answer_relevance:.2f}]\n"
            )
    except KeyboardInterrupt:
        pass
    finally:
        obs.flush()
        print(f"\nSession {session_id} ended. View the replay in Langfuse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
