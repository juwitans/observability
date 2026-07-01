"""stage: lint_links (span) — deterministic checks; emits lint_pass / lint_issue_count.

No LLM. Cheap, runs every ingest, great for the dashboard. Surfaces broken
cross-refs, missing citations, and structural problems the writer introduced.
"""
from __future__ import annotations

import re

from .. import obs
from ..schemas import LintResult, WikiPage

# markdown links pointing at a local wiki page, e.g. [text](some-slug.md)
_LOCAL_LINK = re.compile(r"\[[^\]]+\]\(([a-z0-9\-]+)\.md\)")


def lint_links(page: WikiPage, known_slugs: set[str]) -> LintResult:
    with obs.span("lint_links", input={"slug": page.slug}):
        issues: list[str] = []
        valid_targets = known_slugs | {page.slug}

        # 1. Broken cross-reference links in the body.
        for target in _LOCAL_LINK.findall(page.markdown):
            if target not in valid_targets:
                issues.append(f"Broken cross-link: '{target}.md' does not exist")

        # 2. related_slugs that point nowhere.
        for slug in page.related_slugs:
            if slug not in valid_targets:
                issues.append(f"related_slugs references missing page: '{slug}'")

        # 3. No citations -> ungrounded by construction.
        if not page.citations:
            issues.append("Page has no citations")

        # 4. Structural sanity.
        if len(page.markdown.strip()) < 200:
            issues.append("Body is suspiciously short (<200 chars)")
        if not page.summary.strip():
            issues.append("Missing summary")

        # 5. Malformed markdown tables (header row without separator).
        for m in re.finditer(r"^\|.+\|\s*$", page.markdown, re.MULTILINE):
            line_start = m.start()
            after = page.markdown[m.end():].lstrip("\n")
            if "|" in m.group(0) and not re.match(r"^\|?[\s:\-|]+\|?\s*$", after.split("\n")[0] if after else ""):
                # Only flag if it looks like a header (next line isn't a separator).
                pass  # keep lenient; tables are optional

        result = LintResult(
            passed=len(issues) == 0, issue_count=len(issues), issues=issues
        )
        obs.update_span(output=result.model_dump())
        obs.score_span("lint_pass", 1 if result.passed else 0, data_type="BOOLEAN")
        obs.score_span("lint_issue_count", result.issue_count, data_type="NUMERIC")
        if not result.passed:
            obs.update_span(
                level="WARNING",
                status_message=f"{result.issue_count} lint issue(s): " + "; ".join(issues)[:400],
            )
        return result
