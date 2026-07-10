# =============================================================================
# Module: test_r5_model_resolution.py
# Purpose: TESTER-FIRST reds for R5 — model-resolution correctness (#66/#67).
#   Impl task-eeb73b1b. REDS ARE THE CONTRACT; coder no test edits.
#   Lead ruling (2026-07-10): #66/#67 quality outcome is already shipped on the
#   live path (17a0553 central resolution + 88b8b6a config threading). So R5 =
#     (A) REGRESSION GUARDS locking the shipped behavior (born-green but legit;
#         mutation-proven — a broken resolution reds them), and
#     (B) one DELTA RED: kill the bare load_config() fallback in the retrieval
#         stage — a config=None call must raise an EXPLICIT error, not silently
#         load_config() (the silent-wrong-store path that dead-vectored the
#         emails store for 3 months). Sole caller already threads config.
# =============================================================================

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite_vec required for search path")

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.neuron import neuron_add
from memory_cli.search.light_search_pipeline_orchestrator import light_search, SearchOptions
from memory_cli.config import load_config

_CENTRAL = Path(os.path.expanduser("~")) / ".memory" / "models" / "default.gguf"
requires_central = pytest.mark.skipif(
    not _CENTRAL.exists(),
    reason="central ~/.memory/models/default.gguf required to prove resolution",
)


def _seeded():
    c = open_connection(":memory:")
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 10)
    neuron_add(c, "python asyncio concurrency note", no_embed=True)
    c.commit()
    return c


# -----------------------------------------------------------------------------
# R5.A1 — GUARD (mutation-proven): config with model_path=None resolves the
#   central default → vector available. Locks #66 against regression.
# -----------------------------------------------------------------------------

@requires_central
class TestCentralResolutionGuard:
    def test_null_model_path_resolves_central_vector_available(self):
        conn = _seeded()
        cfg = load_config()
        cfg.embedding.model_path = None  # fresh-store shape (init writes null)
        env = light_search(conn, SearchOptions(query="python", fan_out_depth=0), config=cfg)
        assert env.vector_unavailable is False, (
            f"null model_path did not resolve the central default (#66 regressed): "
            f"{env.vector_unavailable_reason}"
        )
        conn.close()

    def test_absent_explicit_path_falls_through_to_central(self):
        # #66 step 2→3: explicit model_path set but file absent → central default.
        conn = _seeded()
        cfg = load_config()
        cfg.embedding.model_path = "/no/such/model.gguf"
        env = light_search(conn, SearchOptions(query="python", fan_out_depth=0), config=cfg)
        assert env.vector_unavailable is False, (
            "absent explicit model_path did not fall through to the central "
            f"default: {env.vector_unavailable_reason}"
        )
        conn.close()


# -----------------------------------------------------------------------------
# R5.B — DELTA RED: kill the bare load_config() fallback. A retrieval call with
#   config=None must raise an EXPLICIT error, never silently load_config()
#   (which resolves the WRONG store's config — the silent-dead-vector bug).
# -----------------------------------------------------------------------------

class TestConfigRequiredNoSilentLoad:
    def test_none_config_raises_explicit_not_silent_load(self):
        conn = _seeded()
        # Sentinel: if the retrieval stage still bare-loads config, we detect the
        # call; after R5 it must NOT be reached — config is required + explicit.
        import memory_cli.config as cfgmod
        called = {"n": 0}
        real_load = cfgmod.load_config

        def spy():
            called["n"] += 1
            return real_load()

        with pytest.raises((ValueError, TypeError, RuntimeError)):
            import memory_cli.config as _c
            _c.load_config = spy
            try:
                light_search(conn, SearchOptions(query="python", fan_out_depth=0), config=None)
            finally:
                _c.load_config = real_load
        assert called["n"] == 0, (
            "retrieval stage silently called load_config() for a config=None "
            "search — R5 kills this bare fallback (config must be threaded/required)"
        )
        conn.close()
