"""Public scheduled ingest safeguards: no key means no network call."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_script(name: str):
    script = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load script at {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_public_ingest = _load_script("run_public_ingest")


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
