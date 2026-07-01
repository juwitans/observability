"""retrieval.py — dependency-free lexical retrieval over the compiled wiki.

A tiny TF-IDF/cosine scorer. No embeddings, no DB — deterministic and good
enough for a ~10-page corpus. Shared by both pipeline retrieve_related and the
chat retriever; each wraps this in its own Langfuse span and logs the ACTUAL
retrieved text (capture rule, §4.3).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from . import store

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = set(
    "the a an and or of to in is are for on with as by be this that it from at "
    "we you they i not but can will into its their our your his her so if then".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _idf(docs_tokens: list[list[str]]) -> dict[str, float]:
    n = len(docs_tokens)
    df: Counter = Counter()
    for toks in docs_tokens:
        for t in set(toks):
            df[t] += 1
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


def _vec(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = Counter(tokens)
    return {t: c * idf.get(t, 1.0) for t, c in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def search(query: str, top_k: int = 3, exclude_slug: Optional[str] = None) -> list[dict]:
    """Return top_k wiki pages most relevant to `query`, each with its text."""
    pages = store.load_pages(exclude_slug=exclude_slug)
    if not pages:
        return []

    docs_tokens = [tokenize(p["title"] + " " + p["body"]) for p in pages]
    idf = _idf(docs_tokens)
    qvec = _vec(tokenize(query), idf)

    scored = []
    for page, toks in zip(pages, docs_tokens):
        score = _cosine(qvec, _vec(toks, idf))
        scored.append((score, page))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, page in scored[:top_k]:
        if score <= 0:
            continue
        results.append(
            {
                "slug": page["slug"],
                "title": page["title"],
                "score": round(score, 4),
                "text": page["body"],
            }
        )
    return results
