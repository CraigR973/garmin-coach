"""Batch 309: the web builds on Node 24, and CI builds what Vercel builds.

Vercel discontinued Node 20.x on 1 Oct 2026 and refused every build, production
included. Vercel takes its Node version from the root ``engines.node``; CI takes
it from each job's ``node-version``; a developer's shell takes it from
``.nvmrc``. The three moved together in Batch 309, and this test keeps them
together so CI can never pass a build Vercel would refuse.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

WEB_NODE_MAJOR = "24"


def node_pins(root: Path) -> dict[str, list[str]]:
    """Every place the repository names the web's Node major, by source."""
    package = json.loads((root / "package.json").read_text())
    engines = package["engines"]["node"]
    nvmrc = (root / ".nvmrc").read_text().strip()
    ci = (root / ".github" / "workflows" / "ci.yml").read_text()
    ci_versions = re.findall(r'node-version:\s*"?([0-9.x]+)"?', ci)
    return {
        "engines.node": [engines],
        ".nvmrc": [nvmrc],
        "ci.yml node-version": ci_versions,
    }


def _major(version: str) -> str:
    return version.split(".")[0].lstrip("v")


def test_engines_pin_node_24_as_vercel_requires() -> None:
    assert node_pins(REPO)["engines.node"] == [f"{WEB_NODE_MAJOR}.x"]


def test_nvmrc_and_every_ci_node_job_match_the_engines_pin() -> None:
    pins = node_pins(REPO)
    assert pins["ci.yml node-version"], "CI has no Node job to pin"
    majors = {source: {_major(v) for v in versions} for source, versions in pins.items()}
    assert majors == {source: {WEB_NODE_MAJOR} for source in pins}
