"""ChartExtract CLI — ``chartextract extract <doc> [--schema ...] [--json]`` (spec §5).

Runs the pipeline and prints the field table (name · value · flag · confidence) plus the footer
counts and the priced ``$/doc`` / latency caption — or the full :class:`ExtractionResult` JSON with
``--json``. The live Azure-OpenAI **GPT-5.5** provider is used when a key is configured
(``AZURE_OPENAI_API_KEY`` / ``OPENAI_API_KEY``); otherwise — or with ``--stub`` — it drives the
:class:`StubProvider`, so ``chartextract extract examples/path_report.txt`` reproduces the §5 worked
example with no network. A one-line note on stderr always says which mode ran.

Errors are surfaced honestly, never a traceback: an unresolved doc type exits ``2`` with a
"pass --schema" hint; a missing key exits ``3``.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .load import load
from .pipeline import extract
from .provider import default_provider, live_key_present
from .provider.base import MissingAPIKeyError, ProviderClient, ProviderError
from .provider.stub import StubProvider, stub_for_intake, stub_for_path_report
from .router import UnknownDocTypeError
from .schemas import ExtractionResult

#: Minimal offline doc-type guess for the stub's canned classifier, by document header keyword.
#: Only used when no ``--schema`` override is passed (live routing uses the Haiku classifier).
_PATHOLOGY_MARKERS = ("pathology",)
_INTAKE_MARKERS = ("intake",)


def _offline_guess_key(text: str) -> str:
    """Guess the doc type for the offline stub from header keywords (``unknown`` if unsure)."""
    head = text[:200].lower()
    if any(m in head for m in _PATHOLOGY_MARKERS):
        return "pathology"
    if any(m in head for m in _INTAKE_MARKERS):
        return "intake"
    return "unknown"


def _stub_provider(text: str, schema: str | None) -> ProviderClient:
    """Build the offline stub, preloaded to match the resolved doc type so the demo round-trips.

    An explicit ``--schema`` selects the canned output directly; otherwise a header-keyword guess
    does. ``unknown`` returns a bare stub so the router surfaces the "pick a schema" path.
    """
    key = schema or _offline_guess_key(text)
    if key == "intake":
        return stub_for_intake()
    if key == "unknown":
        return StubProvider(classify_result=("unknown", 0.0))
    return stub_for_path_report()


def _make_provider(text: str, schema: str | None, *, use_stub: bool) -> ProviderClient:
    """Pick the provider: live GPT-5.5 when a key is configured, else the offline stub.

    ``--stub`` (``use_stub``) forces offline even with a key. A note is printed to stderr so the
    user always knows whether the numbers came from a live model or canned data.
    """
    if not use_stub and live_key_present():
        try:
            provider = default_provider()
        except MissingAPIKeyError:  # pragma: no cover - live_key_present already gated this
            pass
        else:
            print(f"running live: {provider.provider}/{provider.model}", file=sys.stderr)
            return provider
    print("running offline: stub provider (canned data, $0)", file=sys.stderr)
    return _stub_provider(text, schema)


def _format_result(result: ExtractionResult) -> str:
    """Render the field table + footer counts + cost/latency caption."""
    lines = [
        f"doc_type : {result.doc_type}    model: {result.model}    "
        f"(prompt {result.prompt_version}, schema {result.schema_version})",
        "",
        f"{'field':<26} {'value':<32} {'flag':<16} conf",
        f"{'-' * 26} {'-' * 32} {'-' * 16} ----",
    ]
    for f in result.fields:
        value = "(null)" if f.value is None else str(f.value)
        flag = f.flag if f.flag is not None else "accepted"
        lines.append(f"{f.name:<26} {value:<32.32} {flag:<16} {f.confidence:.2f}")
    lines += [
        "",
        f"{result.n_grounded} grounded | {result.n_null} null | "
        f"{result.n_needs_review} needs-review   "
        f"(${result.cost_usd:.6f}, {result.latency_s:.3f}s)",
    ]
    if not result.highlight_available:
        lines.append("note: no text layer — character highlighting unavailable for this document.")
    return "\n".join(lines)


def _cmd_extract(args: argparse.Namespace) -> int:
    # Load once to guess the type for the offline provider, then run the full pipeline on the path.
    loaded = load(args.doc)
    provider = _make_provider(loaded.text, args.schema, use_stub=args.stub)
    result = extract(args.doc, schema=args.schema, provider=provider)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(_format_result(result))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chartextract", description="ChartExtract — grounded clinical field extraction."
    )
    parser.add_argument("--version", action="version", version=f"chartextract {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    e = sub.add_parser("extract", help="extract structured fields from a clinical document")
    e.add_argument("doc", help="path to a document (.txt/.pdf) or inline text")
    e.add_argument(
        "--schema",
        default=None,
        help="force a schema (pathology|intake); omit to route automatically",
    )
    e.add_argument("--json", action="store_true", help="print the full ExtractionResult as JSON")
    e.add_argument(
        "--stub",
        action="store_true",
        help="force the offline stub provider even when a live API key is configured",
    )
    e.set_defaults(func=_cmd_extract)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except UnknownDocTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except MissingAPIKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (ProviderError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - thin entrypoint
    raise SystemExit(main())
