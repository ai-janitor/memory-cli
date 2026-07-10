# =============================================================================
# Module: test_hygiene_latency_sampling.py
# Purpose: Regression test for N3/B1 latency sampling (task-74c20c2e, e7afb5d +
#   B1 revise). memory-cli is 1-SEARCH-PER-PROCESS on the fleet, so the sampler
#   MUST be STATELESS (Bernoulli 1/N per call) — a per-process deterministic
#   counter records ZERO on a one-shot process (i=1, 1%N!=0 → never writes),
#   which is the B1 bug this test must catch.
#
# The sampler is stateless, so M independent searches == M one-shot processes.
# Over M searches on a file-backed DB we expect ~M/N rows: NOT 0 (counter bug),
# NOT M (no sampling). random is seeded → deterministic, non-flaky.
#
# NB: earlier this test ran many searches in ONE process on :memory: (always
# writes) — that MASKED the B1 zero-write bug. File-backed + one-shot semantics
# is the red that actually catches it.
# =============================================================================

from __future__ import annotations

import os
import random
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


def test_file_backed_latency_sampled_stateless_one_in_n():
    d = tempfile.mkdtemp(prefix="mclit-lat.", dir="/tmp")
    path = os.path.join(d, "store.db")
    c = open_connection(path)
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 10)
    neuron_add(c, "python asyncio note", attrs={"type": "note"}, no_embed=True)
    c.commit()

    rate = orch._LATENCY_SAMPLE_RATE          # 1/N Bernoulli probability
    m = 200                                    # 200 one-shot-equivalent searches
    expected = m * rate                        # ~20
    random.seed(20260710)                      # deterministic Bernoulli → non-flaky

    cfg = load_config()
    for _ in range(m):
        light_search(c, SearchOptions(query="python", ntype="note"), config=cfg)
    c.close()

    rows = _latency_rows(path)
    # A one-shot process MUST have a nonzero chance to record — 0 rows over 200
    # searches means the deterministic-counter B1 bug (never writes on one-shot).
    assert rows > 0, (
        f"0 latency rows over {m} one-shot-equivalent searches — the sampler is a "
        "per-process counter that never fires on a 1-search-per-process fleet CLI "
        "(B1 zero-write bug). Must be STATELESS Bernoulli."
    )
    # …and not EVERY search (that's no sampling → fleet writer storm).
    assert rows < m, f"latency wrote on every search ({rows}/{m}) — sampling absent"
    # …and roughly the 1/N rate (loose band around the seeded Binomial mean).
    assert expected * 0.3 <= rows <= expected * 3.0, (
        f"latency rows {rows} not ~{expected:.0f} (1-in-{1/rate:.0f} Bernoulli) "
        f"over {m} searches"
    )

    import shutil
    shutil.rmtree(d, ignore_errors=True)
