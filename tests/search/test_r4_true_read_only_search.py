# =============================================================================
# Module: test_r4_true_read_only_search.py
# Purpose: TESTER-FIRST red acceptance tests for R4 — true read-only search.
#   Source: docs/perf-boost-recommendations.md:83-104 (R4) + perf-fix-plan #1 +
#   second-look NEW-1/2/4. Implement task task-cccc1e3f.
#   These REDS ARE THE CONTRACT for the coder build. Coder done == green.
#   Coder may NOT edit these tests without tester sign-off.
#
# R4 = search must do ZERO writes. Four coupled sub-fixes:
#   (1) FTS trigger trg_neurons_fts_update → AFTER UPDATE OF content (needs a
#       v010 migration; today unconditional → every access bump rewrites FTS).
#   (2) gate/flush the access-count UPDATE (hydration :119-123) — read-only default.
#   (3) sample/one-commit-max latency, or a separate writer connection
#       (orchestrator _record_latency); no latency write on the search conn.
#   (4) replace extension-probe DDL (_vec_test/_fts5_test CREATE+DROP on every
#       open) with SELECT vec_version()/pragma_module_list.
#
# Mechanism: sqlite set_trace_callback captures every statement the search
#   connection executes → we assert none are persistent writes. Empirically the
#   current code emits: CREATE/DROP _vec_test, CREATE/DROP _fts5_test,
#   4× UPDATE neurons access_count, INSERT INTO search_latency — all must vanish.
# =============================================================================

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import threading

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite_vec required for search path")

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.neuron import neuron_add
from memory_cli.config import load_config
from memory_cli.search.light_search_pipeline_orchestrator import light_search, SearchOptions

# Persistent-write statements (temp objects explicitly excluded — a read path
# may use temp scratch; the R4 culprits are all persistent).
_WRITE_RE = re.compile(r"\s*(INSERT|UPDATE|DELETE|REPLACE|ALTER)\b", re.I)
_DDL_RE = re.compile(r"\s*(CREATE|DROP)\s+(?!TEMP\b|TEMPORARY\b)", re.I)


def _persistent_writes(stmts):
    out = []
    for s in stmts:
        if _WRITE_RE.match(s) or _DDL_RE.match(s):
            out.append(" ".join(s.split())[:100])
    return out


@pytest.fixture
def store_path():
    """A migrated, seeded store FILE (not :memory:) so we can reopen it as a
    fresh CLI invocation and open it read-only / concurrently."""
    d = tempfile.mkdtemp(prefix="mclit-r4.", dir="/tmp")
    p = os.path.join(d, "store.db")
    c = open_connection(p)
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 9)  # latest shipped
    neuron_add(c, "python asyncio concurrency tutorial", tags=["lang"], attrs={"type": "note"}, no_embed=True)
    neuron_add(c, "rust ownership borrow checker", tags=["lang"], attrs={"type": "note"}, no_embed=True)
    c.commit()
    c.close()
    yield p
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def _fresh_open(path):
    c = open_connection(path)
    load_and_verify_extensions(c)
    return c


# -----------------------------------------------------------------------------
# R4.1 — one FULL open+search does ZERO persistent writes
# -----------------------------------------------------------------------------

class TestFullSearchIsReadOnly:
    def test_open_plus_search_emits_no_persistent_write(self, store_path):
        stmts = []
        c = open_connection(store_path)
        c.set_trace_callback(stmts.append)
        load_and_verify_extensions(c)          # (4) probe DDL must be gone
        light_search(c, SearchOptions(query="python", fan_out_depth=0), config=load_config())
        c.close()

        writes = _persistent_writes(stmts)
        assert writes == [], (
            "search performed persistent writes (R4 requires ZERO):\n  "
            + "\n  ".join(writes)
        )


# -----------------------------------------------------------------------------
# R4.2 — v010 scopes the FTS trigger to content changes only
# -----------------------------------------------------------------------------

class TestV010ScopesFtsTrigger:
    def test_fts_trigger_fires_only_on_content_update(self, store_path):
        c = _fresh_open(store_path)
        try:
            run_pending_migrations(c, 9, 10)  # v010 — RED now (does not exist)
        except Exception as e:
            pytest.fail(f"R4 NOT IMPLEMENTED: v010 migration missing ({type(e).__name__}: {e})")

        row = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='trg_neurons_fts_update'"
        ).fetchone()
        assert row is not None, "trg_neurons_fts_update trigger missing"
        sql = " ".join(row[0].split()).lower()
        assert "update of content" in sql, (
            f"FTS trigger not scoped to content — still unconditional: {sql!r}"
        )

        # Golden: a content change still updates the FTS index (searchable by new token).
        nid = c.execute("SELECT id FROM neurons LIMIT 1").fetchone()[0]
        c.execute("UPDATE neurons SET content = ? WHERE id = ?", ("zzqqxx unique token", nid))
        c.commit()
        hit = c.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'zzqqxx'"
        ).fetchall()
        assert hit, "content update did not propagate to FTS (trigger over-scoped)"
        c.close()


# -----------------------------------------------------------------------------
# R4.3 — latency is not written on the search (read) connection
# -----------------------------------------------------------------------------

class TestLatencyOffSearchConnection:
    def test_no_latency_insert_on_search_conn(self, store_path):
        stmts = []
        c = open_connection(store_path)
        c.set_trace_callback(stmts.append)
        load_and_verify_extensions(c)
        light_search(c, SearchOptions(query="python", fan_out_depth=0), config=load_config())
        c.close()
        latency_writes = [s for s in stmts if "search_latency" in s.lower()
                          and _WRITE_RE.match(s)]
        assert latency_writes == [], (
            "latency was written on the search connection (R4: sample / separate "
            f"writer, one-commit-max): {latency_writes}"
        )


# -----------------------------------------------------------------------------
# R4.4 — the facet fast-path lane is also read-only (NEW-4: no uncommitted txn)
# -----------------------------------------------------------------------------

class TestFacetLaneReadOnly:
    def test_facet_search_emits_no_persistent_write(self, store_path):
        stmts = []
        c = open_connection(store_path)
        c.set_trace_callback(stmts.append)
        load_and_verify_extensions(c)
        env = light_search(c, SearchOptions(query="python", ntype="note"), config=load_config())
        in_txn = c.in_transaction
        c.close()
        writes = _persistent_writes(stmts)
        assert env.facet_fast is True
        assert writes == [], (
            "facet lane performed persistent writes (R4/NEW-4):\n  " + "\n  ".join(writes)
        )
        assert in_txn is False, "facet lane left an uncommitted write txn (holds WAL writer slot)"


# -----------------------------------------------------------------------------
# R4.5 — a read-only connection can complete a search (deterministic proof)
# -----------------------------------------------------------------------------

class TestReadOnlyConnectionSearch:
    def test_search_on_readonly_connection_succeeds(self, store_path):
        ro = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
        try:
            # Today: the extension probe DDL (CREATE _vec_test) / access-count
            # UPDATE → "attempt to write a readonly database"; load_and_verify
            # re-wraps that as RuntimeError. A true read-only search must succeed.
            load_and_verify_extensions(ro)
            env = light_search(ro, SearchOptions(query="python", ntype="note"), config=load_config())
            assert env.exit_code == 0
        except (sqlite3.OperationalError, RuntimeError) as e:
            pytest.fail(f"search wrote to a read-only connection (R4 not read-only): {e}")
        finally:
            ro.close()


# -----------------------------------------------------------------------------
# R4.6 — concurrency: 4 parallel searches, no 'database is locked'
# -----------------------------------------------------------------------------

class TestConcurrentReadOnlySearches:
    def test_four_parallel_readonly_searches_all_succeed(self, store_path):
        # DETERMINISTIC concurrency proof (not a flaky timing race): open each of
        # 4 workers on a READ-ONLY connection and search concurrently. A true
        # read-only search never takes the WAL single-writer slot → all four
        # succeed. Today the write-on-read (probe DDL / access-count UPDATE)
        # raises "attempt to write a readonly database" → RED. A barrier forces
        # genuine overlap; busy_timeout=0 forbids masking any real contention.
        errors = []
        barrier = threading.Barrier(4)

        def worker():
            try:
                ro = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
                ro.execute("PRAGMA busy_timeout=0")
                load_and_verify_extensions(ro)
                barrier.wait(timeout=10)
                for _ in range(5):
                    light_search(ro, SearchOptions(query="python", ntype="note"), config=load_config())
                ro.close()
            except (sqlite3.OperationalError, RuntimeError) as e:
                # RuntimeError = load_and_verify re-wrap of the readonly-write error.
                errors.append(str(e))
            except threading.BrokenBarrierError:
                errors.append("barrier broken")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], (
            "parallel read-only searches failed — search is not read-only, so it "
            f"contends for the WAL writer slot under fleet concurrency: {errors[:4]}"
        )
