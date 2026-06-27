"""Packaging gate (Split 12): each package has complete metadata, builds an sdist+wheel, and the
console entry points are declared so a clean install exposes ``chartextract`` + ``chartextract-api``.

The metadata checks are fast and always run. The actual ``python -m build`` is skipped when the
``build`` module isn't installed (so Tier-1 never fails on a bare machine) but runs in CI, where it
is the real proof that the distributions are well-formed.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: (package dir, distribution name, expected console-script entry point or None).
_PACKAGES = (
    ("core", "chartextract", "chartextract"),
    ("eval", "chartextract-eval", None),
    ("api", "chartextract-api", "chartextract-api"),
)


def _pyproject(pkg: str) -> dict:
    return tomllib.loads(
        (_REPO_ROOT / pkg / "pyproject.toml").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(("pkg", "dist_name", "_script"), _PACKAGES)
def test_metadata_complete(pkg: str, dist_name: str, _script: str | None) -> None:
    project = _pyproject(pkg)["project"]
    assert project["name"] == dist_name
    assert project["version"] == "0.1.0"
    assert project["description"]
    assert project["requires-python"] == ">=3.11"
    assert project["license"]  # consistent with the root LICENSE
    assert any("Python :: 3" in c for c in project["classifiers"])


@pytest.mark.parametrize(("pkg", "_dist", "script"), _PACKAGES)
def test_entry_points_declared(pkg: str, _dist: str, script: str | None) -> None:
    project = _pyproject(pkg)["project"]
    scripts = project.get("scripts", {})
    if script is None:
        assert "scripts" not in project or not scripts
    else:
        assert script in scripts


def test_root_license_present_and_referenced() -> None:
    license_file = _REPO_ROOT / "LICENSE"
    assert license_file.is_file()
    text = license_file.read_text(encoding="utf-8")
    assert "Shamim Ahamed" in text
    # Every package declares a license consistent with the root file.
    for pkg, _dist, _script in _PACKAGES:
        assert _pyproject(pkg)["project"]["license"]


@pytest.mark.skipif(
    importlib.util.find_spec("build") is None,
    reason="the `build` frontend is not installed (CI installs it)",
)
@pytest.mark.parametrize(("pkg", "dist_name", "script"), _PACKAGES)
def test_build_sdist_and_wheel(
    pkg: str, dist_name: str, script: str | None, tmp_path: Path
) -> None:
    outdir = tmp_path / "dist"
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(outdir),
                pkg,
            ],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        # `--no-isolation` builds in-tree; remove the transient build artifacts it leaves behind.
        shutil.rmtree(_REPO_ROOT / pkg / "build", ignore_errors=True)

    wheels = list(outdir.glob("*.whl"))
    sdists = list(outdir.glob("*.tar.gz"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    assert len(sdists) == 1, f"expected one sdist, got {sdists}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
        metadata = zf.read(next(n for n in names if n.endswith("METADATA"))).decode()
        assert "Requires-Python: >=3.11" in metadata
        if script is not None:
            ep = zf.read(
                next(n for n in names if n.endswith("entry_points.txt"))
            ).decode()
            assert script in ep
