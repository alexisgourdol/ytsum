"""Shared test fixtures"""

import pytest


@pytest.fixture(autouse=True)
def isolated_run_log(tmp_path, monkeypatch):
    """Point the run log at a temp DB so no test writes to the real one."""
    path = tmp_path / "runs.db"
    monkeypatch.setenv("YTSUM_RUNS_DB", str(path))
    monkeypatch.delenv("YTSUM_NO_RUN_LOG", raising=False)
    return path
