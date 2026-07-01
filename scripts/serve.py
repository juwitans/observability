"""Launch the demo chat web UI.

Run:  python -m scripts.serve
Then open http://localhost:8000
"""
from __future__ import annotations

import uvicorn


def main() -> None:
    print("Chat UI:  http://localhost:8000")
    uvicorn.run("src.web.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
