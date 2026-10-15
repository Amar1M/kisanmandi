"""CLI smoke tests.

A command-line tool that only works when you run it by hand is a liability —
your cron job and your CI both call it. These tests pin the exit codes and the
machine-readable output contract.
"""

from __future__ import annotations

import json

import pytest

from kisanmandi.cli import main
from kisanmandi.storage.db import (
    get_engine,
    init_db,
    make_session_factory,
    session_scope,
    upsert_prices,
)


@pytest.fixture
def cli_env(test_settings, monkeypatch):
    """Point the CLI at throwaway settings for the duration of a test."""
    import kisanmandi.cli as cli_module

    monkeypatch.setattr(cli_module, "get_settings", lambda: test_settings)
    return test_settings


@pytest.fixture
def seeded_env(cli_env, make_series):
    engine = get_engine(cli_env.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    records = make_series(
        market="Kolar", district="Kolar", days=45, base=1200.0, slope=14.0
    )
    with session_scope(factory) as session:
        upsert_prices(session, records)
    return cli_env


class TestStats:
    def test_prints_config_and_counts(self, cli_env, capsys):
        assert main(["stats"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert "counts" in payload
        assert payload["has_personal_api_key"] is True


class TestAdviseCommand:
    def test_exits_1_with_no_data(self, cli_env, capsys):
        assert main(["advise", "--commodity", "Dragonfruit"]) == 1
        assert "No records" in capsys.readouterr().err

    def test_prints_a_headline_and_reasoning(self, seeded_env, capsys):
        assert main(["advise", "--commodity", "Tomato", "--district", "Kolar"]) == 0
        out = capsys.readouterr().out
        assert "action" in out
        assert "reasoning:" in out
        assert "Tomato" in out

    def test_json_output_is_machine_parseable(self, seeded_env, capsys):
        """`kisanmandi advise --json | jq` must work — no prose mixed into stdout."""
        assert main(["advise", "--commodity", "Tomato", "--district", "Kolar", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] in {"SELL_NOW", "HOLD", "TRANSPORT_TO_OTHER_MANDI"}


class TestModelsCommand:
    def test_prints_a_ranked_table(self, seeded_env, capsys):
        assert main(["models", "--commodity", "Tomato", "--district", "Kolar"]) == 0
        out = capsys.readouterr().out
        assert "model" in out and "skill" in out
        assert "drift" in out

    def test_exits_1_with_insufficient_history(self, cli_env, capsys):
        assert main(["models", "--commodity", "Tomato", "--min-train", "500"]) == 1
        assert "Need at least" in capsys.readouterr().err


class TestForecastCommand:
    def test_auto_model_agrees_with_the_backtest_winner(self, seeded_env, capsys):
        assert main(["forecast", "--commodity", "Tomato", "--market", "Kolar"]) == 0
        out = capsys.readouterr().out
        assert "auto-selected by backtest" in out

    def test_explicit_model_is_honoured(self, seeded_env, capsys):
        assert main(["forecast", "--commodity", "Tomato", "--market", "Kolar",
                     "--model", "moving_average"]) == 0
        assert "moving_average" in capsys.readouterr().out

    def test_exits_1_when_data_is_absent(self, cli_env, capsys):
        assert main(["forecast", "--commodity", "Dragonfruit"]) == 1


class TestQualityReportCommand:
    def test_writes_markdown_to_a_file(self, seeded_env, tmp_path, capsys):
        out_path = tmp_path / "report.md"
        assert main(["quality-report", "--out", str(out_path)]) == 0
        text = out_path.read_text(encoding="utf-8")
        assert "Mandi Price Data Quality Report" in text

    def test_prints_when_no_out_path(self, seeded_env, capsys):
        assert main(["quality-report"]) == 0
        assert "Data Quality Report" in capsys.readouterr().out


class TestLandingVerification:
    def test_exits_1_with_no_manifests(self, cli_env, capsys):
        assert main(["verify-landing"]) == 1
        assert "No manifests" in capsys.readouterr().err

    def test_verifies_intact_pages(self, cli_env, capsys):
        """Write a fake manifest + page, then confirm the checksum matches."""
        import hashlib

        zone_dir = cli_env.landing_local_dir
        page_bytes = json.dumps({"records": []}).encode()
        page_path = zone_dir / "raw" / "source=agmarknet" / "ingest_date=2026-10-15" / "page-0000.json"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_bytes(page_bytes)

        manifest_path = zone_dir / "manifests" / "source=agmarknet" / "ingest_date=2026-10-15"
        manifest_path.mkdir(parents=True, exist_ok=True)
        (manifest_path / "manifest.json").write_text(
            json.dumps(
                {
                    "pages": [
                        {
                            "key": "raw/source=agmarknet/ingest_date=2026-10-15/page-0000.json",
                            "sha256": hashlib.sha256(page_bytes).hexdigest(),
                            "bytes": len(page_bytes),
                            "records": 0,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        assert main(["verify-landing"]) == 0
        assert "verified 1/1" in capsys.readouterr().out

    def test_detects_tampered_pages(self, cli_env, capsys):
        """If someone edits a 'raw' file, verification must fail loudly."""
        zone_dir = cli_env.landing_local_dir
        page_path = zone_dir / "raw" / "source=agmarknet" / "ingest_date=2026-10-15" / "page-0000.json"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text('{"records": [], "tampered": true}', encoding="utf-8")

        manifest_path = zone_dir / "manifests" / "source=agmarknet" / "ingest_date=2026-10-15"
        manifest_path.mkdir(parents=True, exist_ok=True)
        (manifest_path / "manifest.json").write_text(
            json.dumps(
                {
                    "pages": [
                        {
                            "key": "raw/source=agmarknet/ingest_date=2026-10-15/page-0000.json",
                            "sha256": "0" * 64,  # does not match the file on disk
                            "bytes": 10,
                            "records": 0,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        assert main(["verify-landing"]) == 2
        assert "MISMATCH" in capsys.readouterr().err


class TestParser:
    def test_version_flag_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0

    def test_unknown_command_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            main(["frobnicate"])
        assert exc.value.code != 0
