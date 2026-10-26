"""Gate pnpm audit results with reviewed advisory exceptions."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewedAdvisory:
    severity: str
    reason: str


REVIEWED_ADVISORIES: dict[str, ReviewedAdvisory] = {
    "GHSA-wrjc-x8rr-h8h6": ReviewedAdvisory(
        severity="moderate",
        reason=(
            "React Router 6 open-redirect bypass. This app uses client-side "
            "declarative routing and same-origin-normalized navigation targets; "
            "React Router 7 migration is tracked separately."
        ),
    ),
    "GHSA-jjmj-jmhj-qwj2": ReviewedAdvisory(
        severity="moderate",
        reason=(
            "React Router DOM open redirect leading to XSS. No query-controlled "
            "redirect target was found; React Router 7 migration is tracked separately."
        ),
    ),
    "GHSA-337j-9hxr-rhxg": ReviewedAdvisory(
        severity="moderate",
        reason=(
            "React Router SSR hydration constructor injection. Not applicable to "
            "this Vite client-only declarative-mode app."
        ),
    ),
    "GHSA-2v37-7h3g-55p8": ReviewedAdvisory(
        severity="high",
        reason=(
            "nanoid infinite-loop-on-size-zero, only reachable via postcss's "
            "internal ID generation (build-time only, never user input, never "
            "called with size=0). Pulled in transitively by tailwindcss/vite/"
            "autoprefixer dev tooling, not shipped to the browser bundle."
        ),
    ),
    "GHSA-vfj7-8cjw-p6xm": ReviewedAdvisory(
        severity="high",
        reason=(
            "braces stack exhaustion on deeply nested patterns (<= 3.0.3; no fixed "
            "version yet). Reached only through tailwindcss's build-time file globbing "
            "(chokidar, fast-glob, micromatch), via the tailwindcss-animate plugin. The "
            "patterns are the repo's own Tailwind content globs, never user input, and "
            "nothing of it ships to the browser bundle. Approved by Craig, 3 Oct 2026; "
            "revisit when a fixed braces is published."
        ),
    ),
    "GHSA-rj75-hqrm-r3gf": ReviewedAdvisory(
        severity="moderate",
        reason=(
            "postcss-selector-parser quadratic parsing of flat selectors (< 7.1.6; fixed "
            "only in 7.x, and tailwindcss 3.4 and postcss-nested require ^6, whose last "
            "release, 6.1.4, is affected). Reached only through tailwindcss's build-time "
            "selector parsing, via the tailwindcss-animate plugin, on the repo's own CSS; "
            "the advisory itself says build-time use on trusted sources is not affected, "
            "and nothing of it ships to the browser bundle. Batch 314, 6 Oct 2026, decided "
            "under Craig's delegation of 6 Oct; revisit with a Tailwind 4 move or a 6.x fix."
        ),
    ),
}

FAIL_SEVERITIES = {"high", "critical"}


def _run_pnpm_audit() -> dict[str, object]:
    proc = subprocess.run(
        ["pnpm", "audit", "--prod", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = proc.stdout.strip()
    if not output:
        if proc.returncode == 0:
            return {"advisories": {}}
        raise SystemExit(proc.stderr.strip() or "pnpm audit produced no JSON output")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"pnpm audit produced invalid JSON: {exc}") from exc


def main() -> None:
    audit = _run_pnpm_audit()
    advisories = audit.get("advisories", {})
    if not isinstance(advisories, dict):
        raise SystemExit("pnpm audit JSON did not contain an advisories object")

    failures: list[str] = []
    reviewed: list[str] = []
    for advisory in advisories.values():
        if not isinstance(advisory, dict):
            continue
        ghsa = str(advisory.get("github_advisory_id") or advisory.get("id"))
        severity = str(advisory.get("severity", "")).lower()
        title = str(advisory.get("title", "untitled advisory"))
        exception = REVIEWED_ADVISORIES.get(ghsa)
        if exception and severity == exception.severity:
            reviewed.append(f"{ghsa} ({severity}): {title} -- {exception.reason}")
            continue
        if severity in FAIL_SEVERITIES or exception is None:
            failures.append(f"{ghsa} ({severity}): {title}")

    for line in reviewed:
        print(f"reviewed JS advisory exception: {line}")

    if failures:
        for line in failures:
            print(f"unreviewed JS advisory: {line}", file=sys.stderr)
        raise SystemExit(1)

    print("JS dependency audit passed")


if __name__ == "__main__":
    main()
