#!/usr/bin/env python3
"""ChartExtract - the one-command money demo (Split 10).

Tells the whole story end to end in a terminal, two ways::

    python demo.py                      # offline stub (default): no key, no network, deterministic
    python demo.py --stub               # the same, explicit
    python demo.py --live               # against the live provider (GPT-5.5); falls back to --stub
                                        #   with a printed note if no key is configured
    python demo.py --sample intake_form # the intake document instead of the pathology report
    python demo.py --stub --open        # also launch the API + open the browser to the live UI

The narration *is* the pitch:

  1. **load** the sample document into canonical text (the single offset source),
  2. **extract** it through the real pipeline (``load -> route -> parse -> ground -> assemble``),
  3. print the **field table** (name . value . flag . confidence . match_quality),
  4. spotlight the **honest nulls** - a value the model *couldn't* ground is returned as ``null``,
     flagged, never invented (e.g. ``margin_status`` cited-absent, ``lymph_nodes_positive`` silent),
  5. run the offline **eval leaderboard** (macro-F1, hallucination-rate 0, routing accuracy).

Everything is ASCII-only so it prints identically on any console (including a Windows cp1252 one),
and the offline path never touches the network - the demo runs in well under a minute with no key.

This module ships **no new product logic**: it imports the engine (``chartextract``) and the eval
harness (``eval``) and narrates what they already do.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parent
EXAMPLES_DIR = REPO / "examples"

#: The samples the demo can narrate (id -> filename). Both ship with the repo (Split 01).
_SAMPLES = {
    "path_report": "path_report.txt",
    "intake_form": "intake_form.txt",
}

#: Plain-English gloss for each null flag, shown in the "honest nulls" spotlight.
_FLAG_GLOSS = {
    "not_found": "the model found nothing to extract - returned null, not a guess",
    "not_assessed": "the document explicitly says it was not assessed - a cited absence",
    "not_grounded": "the model proposed a value that does not appear in the source - rejected",
    "needs_review": "grounded weakly (low confidence / partial match) - routed to a human",
    "ambiguous_span": "the cited span matches more than one place - routed to a human",
}

_BAR = "=" * 78


# ---------------------------------------------------------------------------
# Small, dependency-free helpers (kept local so the demo runs on a bare checkout).
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Minimal ``.env`` loader (no dependency); never overwrites an already-set variable.

    Lets ``--live`` pick up ``AZURE_OPENAI_*`` / ``OPENAI_API_KEY`` from a repo-root ``.env``
    exactly like the CLI and eval harness do.
    """
    path = REPO / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# ---------------------------------------------------------------------------
# Provider selection - reuse the engine's rule; never reinvent it.
# ---------------------------------------------------------------------------


def _resolve_provider(want_live: bool):
    """Return ``(provider_factory_arg, mode_note)``.

    Offline by default. ``--live`` uses the live provider **only** when a key is configured;
    otherwise it prints a fallback note and degrades to the stub - never a traceback.
    """
    from chartextract import live_key_present

    if want_live and live_key_present():
        from chartextract import default_provider

        provider = default_provider()
        return (
            provider,
            f"LIVE  ({provider.provider}/{provider.model}) - opt-in, costs money",
        )
    if want_live:
        print(
            "note: --live requested but no API key is configured "
            "(set AZURE_OPENAI_API_KEY / OPENAI_API_KEY in .env).\n"
            "      falling back to the offline stub - deterministic, $0, no network.",
            file=sys.stderr,
        )
    return None, "OFFLINE STUB  (canned data, $0, no network - deterministic)"


def _stub_provider(sample_id: str):
    """The deterministic stub preloaded to match the sample's doc type."""
    from chartextract import stub_for_intake, stub_for_path_report

    return stub_for_intake() if sample_id == "intake_form" else stub_for_path_report()


# ---------------------------------------------------------------------------
# The narrated story.
# ---------------------------------------------------------------------------


def _render_table(result) -> str:
    """The field table: name . value . flag . confidence . match_quality."""
    lines = [
        f"{'field':<26} {'value':<26} {'flag':<15} {'conf':>5}  match_quality",
        f"{'-' * 26} {'-' * 26} {'-' * 15} {'-' * 5}  {'-' * 13}",
    ]
    for f in result.fields:
        value = "(null)" if f.value is None else str(f.value)
        flag = f.flag if f.flag is not None else "accepted"
        lines.append(
            f"{f.name:<26} {value:<26.26} {flag:<15} {f.confidence:>5.2f}  {f.match_quality}"
        )
    return "\n".join(lines)


def _spotlight_nulls(result, doc_text: str) -> None:
    """Show every nulled field with its flag and (when cited) the exact source sentence."""
    nulls = [f for f in result.fields if f.value is None]
    if not nulls:
        print("  (every field grounded - no nulls in this document)")
        return
    for f in nulls:
        gloss = _FLAG_GLOSS.get(f.flag or "", "")
        print(f"  {f.name}  ->  null   [{f.flag}]")
        if gloss:
            print(f"      {gloss}")
        # A cited absence (not_assessed) keeps offsets into the verbatim sentence it was read from.
        if f.char_start is not None and f.char_end is not None:
            cited = doc_text[f.char_start : f.char_end].strip()
            if cited:
                print(f'      cited sentence: "{cited}"')
        # A rejected proposal keeps what the model *said* (so the UI can disclose it honestly).
        if f.model_value is not None:
            print(
                f'      the model proposed: "{f.model_value}" (not in the source -> rejected)'
            )


def _run_eval_leaderboard() -> None:
    """Run the offline eval suite and print the leaderboard (deterministic; no latency line)."""
    try:
        from eval.dataset import load_gold
        from eval.run import aggregate, render_leaderboard, run_suite
    except ImportError:
        print(
            "  (eval harness not installed - run `pip install -e eval/` to see the leaderboard)",
            file=sys.stderr,
        )
        return

    records = load_gold()
    n_docs = sum(1 for r in records if r.labels)
    doc_records, _latencies = run_suite(records, provider_name="stub", repeats=1)
    lb = aggregate(
        doc_records, n_docs=n_docs, generated_at="demo", provider="stub", repeats=1
    )
    # Pass no latencies: the leaderboard is then byte-identical across runs (timings would vary).
    print(render_leaderboard(lb, latencies=None))


def run_story(sample_id: str, *, want_live: bool) -> int:
    """Print the end-to-end money demo for ``sample_id``. Returns a process exit code."""
    from chartextract import load
    from chartextract.pipeline import extract

    filename = _SAMPLES[sample_id]
    doc_path = EXAMPLES_DIR / filename

    provider, mode_note = _resolve_provider(want_live)
    if provider is None:
        provider = _stub_provider(sample_id)

    print(_BAR)
    print(
        "  ChartExtract - grounded clinical extraction with a null-not-a-guess guarantee"
    )
    print(f"  Mode: {mode_note}")
    print(_BAR)

    _section("1. LOAD")
    loaded = load(doc_path)
    print(
        f"  {filename}  ({loaded.n_chars} chars, canonical text - the single offset source)"
    )

    _section("2. EXTRACT  (load -> route -> parse -> ground-in-code -> assemble)")
    result = extract(doc_path, provider=provider)
    print(
        f"  doc_type={result.doc_type}   model={result.model}   "
        f"prompt={result.prompt_version}   schema={result.schema_version}"
    )
    print()
    print(_render_table(result))
    print()
    print(
        f"  {result.n_grounded} grounded . {result.n_null} null . "
        f"{result.n_needs_review} needs-review   (${result.cost_usd:.4f}/doc)"
    )
    if want_live and provider is not None and result.model != "stub":
        print(f"  latency: {result.latency_s:.2f}s  (live model call)")

    _section(
        "3. THE HONEST NULLS  (a value it can't ground is null + flagged, never invented)"
    )
    _spotlight_nulls(result, loaded.text)

    _section("4. EVAL LEADERBOARD  (offline stub - the headline: hallucination-rate 0)")
    _run_eval_leaderboard()

    print()
    print(_BAR)
    print(
        "  Synthetic data only - not real PHI. Not a medical device; for demonstration only."
    )
    print(
        "  Live calls are opt-in and cost money; this offline demo is free and reproducible."
    )
    print(_BAR)
    return 0


# ---------------------------------------------------------------------------
# Optional: launch the API + open the browser to the live UI.
# ---------------------------------------------------------------------------


def _serve_and_open(sample_id: str, *, host: str, port: int, want_live: bool) -> int:
    """Launch ``chartextract-api`` (serving ``app/`` same-origin) and open the browser.

    Blocks on the server until interrupted. The stub demo opens ``/?stub=1`` so the page shows the
    canned data even if a key happens to be present; the live demo opens ``/``.
    """
    suffix = "" if want_live else "?stub=1"
    url = f"http://{host}:{port}/{suffix}"
    print(f"\nlaunching the UI at {url}  (Ctrl+C to stop)\n", flush=True)
    try:
        webbrowser.open(url)
    except Exception:  # pragma: no cover - headless box without a browser
        pass

    from chartextract_api.cli import main as api_main

    return api_main(["--host", host, "--port", str(port)])


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="demo.py",
        description="ChartExtract one-command money demo (terminal + optional UI).",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--stub",
        action="store_true",
        help="offline canned demo (default): no key, no network",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="live provider (opt-in); falls back to --stub with no key",
    )
    p.add_argument(
        "--sample",
        choices=sorted(_SAMPLES),
        default="path_report",
        help="which bundled document to narrate (default: path_report)",
    )
    p.add_argument(
        "--open",
        action="store_true",
        help="also launch the API and open the browser to the UI",
    )
    p.add_argument(
        "--host", default="127.0.0.1", help="host for --open (default 127.0.0.1)"
    )
    p.add_argument(
        "--port", type=int, default=8000, help="port for --open (default 8000)"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _load_env()

    # ASCII-only output; keep robust on a non-UTF-8 console (never crash on a glyph - spec §15).
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            try:
                reconfig(errors="backslashreplace")
            except (
                ValueError,
                OSError,
            ):  # pragma: no cover - stream not reconfigurable
                pass

    code = run_story(args.sample, want_live=args.live)
    if args.open and code == 0:
        return _serve_and_open(
            args.sample, host=args.host, port=args.port, want_live=args.live
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
