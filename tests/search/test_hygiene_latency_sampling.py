# =============================================================================
# Module: test_hygiene_latency_sampling.py
# Purpose: Regression test for N3 hygiene (task-74c20c2e, coder e7afb5d) — the
#   file-backed latency side-channel writer SAMPLES 1-in-N so fleet storms don't
#   open+commit a writer per search. Locks the sampling; mutation-provable (drop
#   sampling → every search writes a row). Tester-owned.
# =============================================================================

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite_vec required for search path")

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.neuron import neuron_add
from memory_cli.config import load_config
from memory_cli.search import light_search_pipeline_orchestrator as orch
from memory_cli.search.light_search_pipeline_orchestrator import light_search, SearchOptions


def _latency_rows(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("SELECT COUNT(*) FROM search_latency").fetchone()[0]
    finally:
        c.close()


def test_file_backed_latency_is_sampled_one_in_n():
    d = tempfile.mkdtemp(prefix="mclit-lat.", dir="/tmp")
    path = os.path.join(d, "store.db")
    c = open_connection(path)
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 10)
    neuron_add(c, "python asyncio note", attrs={"type": "note"}, no_embed=True)
    c.commit()

    n = orch._LATENCY_SAMPLE_EVERY  # sample period (deterministic counter)
    orch._latency_sample_i = 0      # reset shared counter for a deterministic count

    runs = n * 2  # two full sample periods
    cfg = load_config()
    for _ in range(runs):
        light_search(c, SearchOptions(query="python", ntype="note"), config=cfg)
    c.close()

    rows = _latency_rows(path)
    # 1-in-N sampling → exactly `runs / n` rows (not `runs`).
    assert rows == runs // n, (
        f"file-backed latency wrote {rows} rows for {runs} searches — expected "
        f"{runs // n} (1-in-{n} sampling). N3 sampling regressed = fleet writer storm."
    )

    import shutil
    shutil.rmtree(d, ignore_errors=True)
