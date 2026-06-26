"""Provider selection — the one place that decides live-vs-stub from the environment (Split 04)."""

from __future__ import annotations

import pytest

from chartextract.cli import main
from chartextract.provider import default_provider, live_key_present
from chartextract.provider.base import MissingAPIKeyError


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)


def test_live_key_present_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    assert live_key_present() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    assert live_key_present() is True


def test_default_provider_raises_missing_key_naming_var(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    with pytest.raises(MissingAPIKeyError, match="OPENAI_API_KEY"):
        default_provider()


def test_cli_offline_note_and_stub_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], path_report_path
) -> None:
    # No key → the CLI runs the stub and says so on stderr; stdout still has the worked example.
    _clear_keys(monkeypatch)
    rc = main(["extract", str(path_report_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "offline" in captured.err.lower()
    assert "not_assessed" in captured.out


def test_cli_stub_flag_forces_offline_even_with_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], path_report_path
) -> None:
    # A key is present, but --stub must keep it offline (no network in this test).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    rc = main(["extract", str(path_report_path), "--stub"])
    assert rc == 0
    assert "offline" in capsys.readouterr().err.lower()


def test_cli_selects_live_provider_when_key_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], path_report_path
) -> None:
    # With a key present and no --stub, the CLI picks the live provider and says so on stderr.
    # We swap default_provider for a stub so the test stays offline (the selection branch is what
    # we're covering, not the network).
    from chartextract import cli
    from chartextract.provider.stub import stub_for_path_report

    monkeypatch.setattr(cli, "live_key_present", lambda: True)
    monkeypatch.setattr(cli, "default_provider", stub_for_path_report)
    rc = main(["extract", str(path_report_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "running live" in captured.err.lower()
    assert "stub/claude-opus-4-8" in captured.err  # the swapped-in stub's provider/model label


def test_cli_missing_key_error_exits_3_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], path_report_path
) -> None:
    # A provider-layer missing-key surfaces as exit 3 with a clean message, never a traceback.
    from chartextract import cli
    from chartextract.provider.base import MissingAPIKeyError

    def _boom(*a: object, **k: object) -> object:
        raise MissingAPIKeyError("OPENAI_API_KEY is not set.")

    monkeypatch.setattr(cli, "extract", _boom)
    rc = main(["extract", str(path_report_path), "--stub"])
    assert rc == 3
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_cli_provider_error_exits_2_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], path_report_path
) -> None:
    from chartextract import cli
    from chartextract.provider.base import RefusalError

    def _boom(*a: object, **k: object) -> object:
        raise RefusalError("model refused")

    monkeypatch.setattr(cli, "extract", _boom)
    rc = main(["extract", str(path_report_path), "--stub"])
    assert rc == 2
    assert "refused" in capsys.readouterr().err.lower()
