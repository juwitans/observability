"""store.py — filesystem read/write for raw sources and compiled wiki pages.

Mirrors Karpathy's pattern: `raw/` is immutable source material, `wiki/` holds
the LLM-maintained compiled pages. No DB needed for the POC.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from .schemas import WikiPage

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw" / "observability"
WIKI_DIR = ROOT / "wiki" / "observability"
INDEX_PATH = ROOT / "wiki" / "index.md"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "page"


# ── raw/ ───────────────────────────────────────────────────────────────────
def save_raw(slug: str, markdown: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{slug}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


# ── wiki/ ──────────────────────────────────────────────────────────────────
def _frontmatter(page: WikiPage) -> str:
    meta = {
        "title": page.title,
        "slug": page.slug,
        "topic": page.topic,
        "related_slugs": page.related_slugs,
        "citations": page.citations,
    }
    return "---\n" + yaml.safe_dump(meta, sort_keys=False).strip() + "\n---\n\n"


def save_page(page: WikiPage) -> Path:
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    path = WIKI_DIR / f"{page.slug}.md"
    body = page.markdown.strip() + "\n"
    path.write_text(_frontmatter(page) + body, encoding="utf-8")
    return path


def _parse_page(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    return {
        "slug": meta.get("slug", path.stem),
        "title": meta.get("title", path.stem),
        "topic": meta.get("topic", ""),
        "citations": meta.get("citations", []),
        "related_slugs": meta.get("related_slugs", []),
        "body": body.strip(),
        "path": path,
    }


def load_pages(exclude_slug: Optional[str] = None) -> list[dict]:
    if not WIKI_DIR.exists():
        return []
    pages = []
    for path in sorted(WIKI_DIR.glob("*.md")):
        page = _parse_page(path)
        if exclude_slug and page["slug"] == exclude_slug:
            continue
        pages.append(page)
    return pages


def page_exists(slug: str) -> bool:
    return (WIKI_DIR / f"{slug}.md").exists()


def all_slugs() -> set[str]:
    return {p["slug"] for p in load_pages()}


# ── index.md ───────────────────────────────────────────────────────────────
def rebuild_index() -> Path:
    pages = load_pages()
    by_topic: dict[str, list[dict]] = {}
    for p in pages:
        by_topic.setdefault(p["topic"] or "other", []).append(p)

    lines = ["# Observability Wiki — Index\n", f"_{len(pages)} pages._\n"]
    for topic in sorted(by_topic):
        lines.append(f"\n## {topic}\n")
        for p in sorted(by_topic[topic], key=lambda x: x["title"]):
            lines.append(f"- [{p['title']}](observability/{p['slug']}.md)")
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return INDEX_PATH
