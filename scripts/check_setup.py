"""Step 1 gate: confirm Langfuse is reachable and a throwaway trace lands.

Run:  python -m scripts.check_setup
Then look for a trace named 'setup_check' in the Langfuse UI.
"""
from __future__ import annotations

import os
import sys

from src import obs


def main() -> int:
    required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[FAIL] Missing env vars (check .env): {', '.join(missing)}")
        return 1

    print(f"Langfuse base URL: {os.environ['LANGFUSE_BASE_URL']}")

    client = obs.lf()
    if not client.auth_check():
        print("[FAIL] auth_check() failed — keys or base URL are wrong.")
        return 1
    print("[OK] auth_check() passed.")

    with obs.span("setup_check", input={"hello": "langfuse"}) as s:
        obs.update_span(output={"status": "ok"})
        trace_id = getattr(s, "trace_id", None)

    obs.flush()
    print("[OK] Throwaway trace 'setup_check' sent.")
    if trace_id:
        base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        print(f"      Look for trace id {trace_id} at {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
