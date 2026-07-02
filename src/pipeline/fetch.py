"""stage: fetch_source (span) — pull raw HTML for one source URL."""
from __future__ import annotations

import httpx

from .. import obs
from ..schemas import FetchResult

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; wiki-obs-poc/0.1; +internal-demo) "
        "Python-httpx"
    )
}


def fetch_source(url: str, timeout: float = 30.0) -> FetchResult:
    with obs.span("fetch_source", input={"url": url}):
        # The downstream HTTP call gets its OWN child span so it nests under the
        # stage instead of being opaque inside it (OBSERVABILITY_INSTRUMENTATION.md
        # §1/§3: downstream DB/HTTP spans nest under their tool/stage span). httpx
        # is not OTel-auto-instrumented here, so we emit it manually using the OTel
        # http.*/url.* attribute names.
        with obs.span(
            "http_get", metadata={"http.request.method": "GET", "url.full": url}
        ):
            resp = httpx.get(
                url, follow_redirects=True, timeout=timeout, headers=_HEADERS
            )
            html = resp.text
            byte_size = len(html.encode("utf-8", errors="ignore"))
            obs.update_span(
                output={
                    "http.response.status_code": resp.status_code,
                    "http.response.body.size": byte_size,
                }
            )
        result = FetchResult(
            url=url, status=resp.status_code, byte_size=byte_size, html=html
        )
        obs.update_span(output={"status": resp.status_code, "byte_size": byte_size})
        if resp.status_code >= 400:
            obs.update_span(
                level="ERROR",
                status_message=f"HTTP {resp.status_code} fetching {url}",
            )
            resp.raise_for_status()
        elif byte_size < 500:
            obs.update_span(
                level="WARNING",
                status_message=f"Suspiciously small response ({byte_size} bytes)",
            )
        return result
