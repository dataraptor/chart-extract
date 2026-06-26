"""ChartExtract CLI — usage stub (real `extract` command lands in Split 03).

This split ships only the entrypoint so ``chartextract`` resolves and ``--version`` works; the
``extract <doc>`` command is wired once the offline pipeline exists.
"""

from __future__ import annotations

import sys

from . import __version__

_USAGE = (
    f"chartextract {__version__}\n"
    "usage: chartextract extract <doc>   (coming in Split 03)\n"
    "\n"
    "The extraction pipeline is not wired yet. This is a scaffold entrypoint.\n"
)


def main(argv: list[str] | None = None) -> int:
    """Print usage and exit 0. Real argument parsing arrives with the pipeline (Split 03)."""
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] in {"--version", "-V"}:
        print(f"chartextract {__version__}")
        return 0
    print(_USAGE, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin entrypoint
    raise SystemExit(main())
