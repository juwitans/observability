"""Step 2 gate: a single traced LLM call lands in Langfuse with cost/tokens.

Run:  python -m scripts.smoke_llm
Then open the 'smoke_llm' trace and confirm model, tokens and cost are present.
"""
from __future__ import annotations

import sys

from src import llm, obs


def main() -> int:
    print(f"Model: {llm.default_model()}")
    with obs.span("smoke_llm"):
        out = llm.llm(
            [{"role": "user", "content": "Reply with exactly: observability works."}],
            name="smoke_generation",
            temperature=0,
        )
    obs.flush()
    print(f"[OK] LLM replied: {out!r}")
    print("      Open the 'smoke_llm' trace; check the generation has tokens + cost.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
