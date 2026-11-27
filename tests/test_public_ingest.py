"""Public scheduled ingest safeguards: no key means no network call."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import run_public_ingest


def test_public_ingest_refuses_missing_personal_key(monkeypatch):
    monkeypatch.setattr(
        run_public_ingest,
        "Settings",
        lambda: SimpleNamespace(data_gov_api_key=""),
    )
    monkeypatch.setattr(
        run_public_ingest,
        "run_ingest",
        lambda *args, **kwargs: pytest.fail("must not contact the API without a personal key"),
    )

    with pytest.raises(SystemExit, match="refusing the shared demo key"):
        run_public_ingest.main()
