"""Tier-1 checks on the orchestration furniture (Split 10): Makefile targets, README front-door
order, screenshot links, the Faithfulness-Firewall distinction, and the no-secret Docker setup.

These are static file checks — fast, deterministic, no installs — so CI can assert the front door is
intact without standing up the whole stack.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

REQUIRED_TARGETS = (
    "install",
    "test",
    "lint",
    "cov",
    "demo",
    "demo-stub",
    "serve",
    "eval",
    "e2e",
    "docker-build",
    "docker-up",
    "clean",
)


def _makefile() -> str:
    return (REPO / "Makefile").read_text(encoding="utf-8")


def _readme() -> str:
    return (REPO / "README.md").read_text(encoding="utf-8")


def test_makefile_declares_every_required_target() -> None:
    mk = _makefile()
    targets = set(re.findall(r"^([a-zA-Z][\w-]*):", mk, flags=re.MULTILINE))
    missing = [t for t in REQUIRED_TARGETS if t not in targets]
    assert not missing, f"Makefile missing targets: {missing}"


def test_readme_leads_in_the_required_order() -> None:
    md = _readme()
    # what/who -> Firewall distinction -> architecture -> money demo -> quickstart -> eval.
    order = [
        "schema-validated JSON",
        "Not the Faithfulness Firewall",
        "## Architecture",
        "## The money demo",
        "## Quickstart",
        "## Eval",
    ]
    positions = [md.find(s) for s in order]
    assert all(p >= 0 for p in positions), dict(zip(order, positions))
    assert positions == sorted(positions), f"README sections out of order: {positions}"


def test_readme_has_the_firewall_distinction_line() -> None:
    md = _readme()
    assert "Faithfulness Firewall" in md
    assert "Different input" in md and "different output" in md


def test_readme_screenshots_resolve() -> None:
    md = _readme()
    for rel in re.findall(r"docs/screenshots/[^)\s]+\.png", md):
        assert (REPO / rel).is_file(), f"missing screenshot: {rel}"


def test_readme_quickstart_make_targets_exist() -> None:
    md = _readme()
    mk = _makefile()
    targets = set(re.findall(r"^([a-zA-Z][\w-]*):", mk, flags=re.MULTILINE))
    for cmd in re.findall(r"make ([a-zA-Z][\w-]*)", md):
        assert cmd in targets, (
            f"README references `make {cmd}` but the Makefile has no such target"
        )


def test_readme_has_honesty_furniture() -> None:
    md = _readme().lower()
    assert "synthetic" in md and "real phi" in md
    assert "not a medical device" in md
    assert "opt-in" in md and "cost" in md


def test_docker_setup_bakes_no_secret() -> None:
    dockerfile = (REPO / "api" / "Dockerfile").read_text(encoding="utf-8")
    # The image must never COPY the .env or hardcode a key.
    assert "COPY .env" not in dockerfile
    assert (
        "ENV AZURE_OPENAI_API_KEY" not in dockerfile
        and "ENV OPENAI_API_KEY" not in dockerfile
    )
    # The build context excludes the secret.
    dockerignore = (REPO / ".dockerignore").read_text(encoding="utf-8")
    assert ".env" in dockerignore


def test_compose_reads_key_from_env_not_image() -> None:
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "env_file" in compose
    assert "8000" in compose


def test_eval_target_runs_offline() -> None:
    """`make eval`'s underlying command exits 0 with no key (deterministic stub leaderboard)."""
    proc = subprocess.run(
        [sys.executable, "-m", "eval.run", "--provider", "stub", "--no-write"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "HALLUCINATION-RATE" in proc.stdout
