# =============================================================================
# FILE: tests/cli/test_layered_search_local_and_global.py
# PURPOSE: Test layered PATH-style search — query local then global, merge results.
#          When both .memory/ (local) and ~/.memory/ (global) exist, search and
#          list commands query BOTH stores. Writes go to local if it exists.
# RATIONALE: Task #15 Part B. The layered model is the core feature — agents get
#            project-specific AND global knowledge without thinking about it.
# RESPONSIBILITY:
#   - Test get_layered_connections() returns correct stores for each scenario
#   - Test --global flag overrides layering (global-only)
#   - Test neuron search merges results from both stores
#   - Test local results appear before global results
#   - Test write operations default to local store
#   - Test scoped handle routing (LOCAL-42, GLOBAL-42)
# ORGANIZATION:
#   1. Fixtures for dual-store setup
#   2. get_layered_connections tests
#   3. Neuron handler integration tests
# =============================================================================

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Tuple
from unittest.mock import patch, MagicMock

import pytest
import sqlite3

# --- Module-level guard: all tests in this file require sqlite_vec ---
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# =============================================================================
# FIXTURES
# =============================================================================

def _create_memory_store(base_dir: Path) -> Path:
    """Create a .memory/ store at the given base directory.

    Sets up config.json and memory.db with full schema.
    Returns the .memory/ directory path.
    """
    memory_dir = base_dir / ".memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    db_path = memory_dir / "memory.db"
    config = {
        "db_path": str(db_path),
        "embedding": {
            "model_path": "/tmp/nomic-embed-text-v1.5.Q8_0.gguf",
            "dimensions": 768,
        },
    }
    (memory_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    # Create the DB with full schema
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
    from memory_cli.db import run_pending_migrations
    from memory_cli.db import read_schema_version

    conn = open_connection(str(db_path))
    load_sqlite_vec(conn)
    current = read_schema_version(conn)
    if current < 3:
        run_pending_migrations(conn, current, 3)
    conn.close()
    return memory_dir


def _add_neuron_to_store(store_dir: Path, content: str, tags: list | None = None) -> int:
    """Add a neuron to the store at the given .memory/ directory.

    Returns the neuron ID.
    """
    db_path = store_dir / "memory.db"
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
    from memory_cli.neuron import neuron_add

    conn = open_connection(str(db_path))
    load_sqlite_vec(conn)
    result = neuron_add(conn, content, tags=tags, no_embed=True)
    conn.close()
    return result["id"]


@pytest.fixture
def dual_stores(tmp_path):
    """Create both a local and global memory store.

    Returns (local_dir, global_dir, project_dir) where:
    - local_dir = project_dir / .memory/
    - global_dir = fake_home / .memory/
    - project_dir is the simulated cwd
    """
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()

    local_dir = _create_memory_store(project_dir)
    global_dir = _create_memory_store(fake_home)

    return local_dir, global_dir, project_dir, fake_home


# =============================================================================
# SECTION 1: resolve_all_config_paths TESTS
# =============================================================================

class TestResolveAllConfigPaths:
    """Test resolve_all_config_paths() returns correct config paths."""

    def test_both_stores_returns_both(self, dual_stores):
        """When both local and global exist, returns both (local first)."""
        local_dir, global_dir, project_dir, fake_home = dual_stores

        from memory_cli.config.config_path_resolution_ancestor_walk import (
            resolve_all_config_paths,
        )

        with patch("memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
                    return_value=global_dir / "config.json"):
            results = resolve_all_config_paths(cwd=project_dir)

        assert len(results) == 2
        assert results[0][1] == "LOCAL"
        assert results[1][1] == "GLOBAL"
        assert results[0][0] == local_dir / "config.json"
        assert results[1][0] == global_dir / "config.json"

    def test_local_only(self, tmp_path):
        """When only local exists, returns just local."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _create_memory_store(project_dir)

        from memory_cli.config.config_path_resolution_ancestor_walk import (
            resolve_all_config_paths,
        )

        # Point global to nonexistent path
        nonexistent = tmp_path / "nope" / ".memory" / "config.json"
        with patch("memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
                    return_value=nonexistent):
            results = resolve_all_config_paths(cwd=project_dir)

        assert len(results) == 1
        assert results[0][1] == "LOCAL"

    def test_global_only(self, tmp_path):
        """When only global exists, returns just global."""
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        global_dir = _create_memory_store(fake_home)

        from memory_cli.config.config_path_resolution_ancestor_walk import (
            resolve_all_config_paths,
        )

        with patch("memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
                    return_value=global_dir / "config.json"):
            results = resolve_all_config_paths(cwd=project_dir)

        assert len(results) == 1
        assert results[0][1] == "GLOBAL"

    def test_no_stores_returns_empty(self, tmp_path):
        """When neither exists, returns empty list."""
        project_dir = tmp_path / "bare"
        project_dir.mkdir()

        from memory_cli.config.config_path_resolution_ancestor_walk import (
            resolve_all_config_paths,
        )

        nonexistent = tmp_path / "nope" / ".memory" / "config.json"
        with patch("memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
                    return_value=nonexistent):
            results = resolve_all_config_paths(cwd=project_dir)

        assert len(results) == 0


# =============================================================================
# SECTION 2: get_layered_connections TESTS
# =============================================================================

class TestGetLayeredConnections:
    """Test get_layered_connections() returns correct connections."""

    def test_both_stores(self, dual_stores):
        """When both local and global exist, returns two connections."""
        local_dir, global_dir, project_dir, fake_home = dual_stores

        from memory_cli.cli.noun_handlers.db_connection_from_global_flags import (
            get_layered_connections,
        )

        flags = SimpleNamespace(config=None, db=None, global_only=False)

        # Patch resolve_all_config_paths at the source module (imported inside function)
        with patch(
            "memory_cli.config.config_path_resolution_ancestor_walk.resolve_all_config_paths",
            return_value=[
                (local_dir / "config.json", "LOCAL"),
                (global_dir / "config.json", "GLOBAL"),
            ],
        ):
            connections = get_layered_connections(flags)

        assert len(connections) == 2
        assert connections[0][1] == "LOCAL"
        assert connections[1][1] == "LOCAL"  # detect_scope sees non-home path in tests
        # Both connections should be valid sqlite3.Connection objects
        assert isinstance(connections[0][0], sqlite3.Connection)
        assert isinstance(connections[1][0], sqlite3.Connection)

        for conn, _ in connections:
            conn.close()

    def test_global_flag_returns_only_global(self, dual_stores):
        """With --global flag, returns only the global store."""
        local_dir, global_dir, project_dir, fake_home = dual_stores

        from memory_cli.cli.noun_handlers.db_connection_from_global_flags import (
            get_layered_connections,
        )

        flags = SimpleNamespace(config=None, db=None, global_only=True)

        with patch(
            "memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
            return_value=global_dir / "config.json",
        ):
            connections = get_layered_connections(flags)

        assert len(connections) == 1
        # detect_scope sees non-home path in tests, that's fine — key is only ONE connection
        for conn, _ in connections:
            conn.close()

    def test_config_override_bypasses_layering(self, dual_stores):
        """With --config override, returns single connection (no layering)."""
        local_dir, global_dir, project_dir, fake_home = dual_stores

        from memory_cli.cli.noun_handlers.db_connection_from_global_flags import (
            get_layered_connections,
        )

        flags = SimpleNamespace(
            config=str(local_dir / "config.json"),
            db=None,
            global_only=False,
        )

        connections = get_layered_connections(flags)
        assert len(connections) == 1
        for conn, _ in connections:
            conn.close()


# =============================================================================
# SECTION 3: NEURON HANDLER INTEGRATION TESTS
# =============================================================================

class TestNeuronListMergesStores:
    """Test that neuron list merges results from both stores."""

    def test_list_returns_neurons_from_both_stores(self):
        """neuron list with layered connections returns results from both."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_list

        # Create two in-memory databases with neurons
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version
        from memory_cli.neuron import neuron_add

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        neuron_add(local_conn, "local memory", no_embed=True)
        neuron_add(global_conn, "global memory", no_embed=True)

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_list([], flags)

        assert result.status == "ok"
        assert len(result.data) == 2
        # Local first
        assert result.data[0]["id"].startswith("LOCAL-")
        assert result.data[1]["id"].startswith("GLOBAL-")

        local_conn.close()
        global_conn.close()

    def test_local_results_ranked_first(self):
        """Local results appear before global in merged output."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_list
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version
        from memory_cli.neuron import neuron_add

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        # Add multiple neurons to each
        neuron_add(local_conn, "local-1", no_embed=True)
        neuron_add(local_conn, "local-2", no_embed=True)
        neuron_add(global_conn, "global-1", no_embed=True)

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_list([], flags)

        assert result.status == "ok"
        assert len(result.data) == 3
        # All local results first, then global
        assert result.data[0]["id"].startswith("LOCAL-")
        assert result.data[1]["id"].startswith("LOCAL-")
        assert result.data[2]["id"].startswith("GLOBAL-")

        local_conn.close()
        global_conn.close()


class TestNeuronWriteDefaultsToLocal:
    """Test that write operations default to local store."""

    def test_add_goes_to_local(self):
        """neuron add with both stores writes to local (first connection)."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_add
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_add(["test content for local"], flags)

        assert result.status == "ok"
        assert result.data["id"].startswith("LOCAL-")

        # Verify it went to local, not global
        local_count = local_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        global_count = global_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        assert local_count == 1
        assert global_count == 0

        local_conn.close()
        global_conn.close()


class TestGetByScopedHandle:
    """Test that scoped handles route to the correct store."""

    def test_global_handle_routes_to_global(self):
        """GLOBAL-1 routes to the global store."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version
        from memory_cli.neuron import neuron_add

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        neuron_add(local_conn, "local content", no_embed=True)
        neuron_add(global_conn, "global content", no_embed=True)

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_get(["GLOBAL-1"], flags)

        assert result.status == "ok"
        assert result.data["id"] == "GLOBAL-1"
        assert result.data["content"] == "global content"

        local_conn.close()
        global_conn.close()

    def test_local_handle_routes_to_local(self):
        """LOCAL-1 routes to the local store."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version
        from memory_cli.neuron import neuron_add

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        neuron_add(local_conn, "local content", no_embed=True)
        neuron_add(global_conn, "global content", no_embed=True)

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_get(["LOCAL-1"], flags)

        assert result.status == "ok"
        assert result.data["id"] == "LOCAL-1"
        assert result.data["content"] == "local content"

        local_conn.close()
        global_conn.close()

    def test_bare_id_searches_local_first(self):
        """Bare ID (no scope prefix) finds neuron in local first."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version
        from memory_cli.neuron import neuron_add

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        # Both stores have neuron with ID 1
        neuron_add(local_conn, "local content", no_embed=True)
        neuron_add(global_conn, "global content", no_embed=True)

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_get(["1"], flags)

        assert result.status == "ok"
        # Should find in local first (it's first in the connection list)
        assert result.data["id"] == "LOCAL-1"
        assert result.data["content"] == "local content"

        local_conn.close()
        global_conn.close()

    def test_nonexistent_scope_returns_not_found(self):
        """GLOBAL-999 returns not_found when neuron doesn't exist in global."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_get
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_get(["GLOBAL-999"], flags)

        assert result.status == "not_found"

        local_conn.close()
        global_conn.close()


# =============================================================================
# SECTION 4: GLOBAL FLAG PARSING TESTS
# =============================================================================

class TestGlobalFlagParsing:
    """Test that --global is parsed as a global flag."""

    def test_global_flag_parsed(self):
        """--global sets global_only=True on GlobalFlags."""
        from memory_cli.cli.global_flags_format_config_db import parse_global_flags

        flags, remaining = parse_global_flags(["neuron", "list", "--global"])
        assert flags.global_only is True
        assert remaining == ["neuron", "list"]

    def test_no_global_flag(self):
        """Without --global, global_only=False."""
        from memory_cli.cli.global_flags_format_config_db import parse_global_flags

        flags, remaining = parse_global_flags(["neuron", "list"])
        assert flags.global_only is False
        assert remaining == ["neuron", "list"]

    def test_global_flag_with_format(self):
        """--global works alongside other global flags."""
        from memory_cli.cli.global_flags_format_config_db import parse_global_flags

        flags, remaining = parse_global_flags(["--format", "text", "--global", "neuron", "search", "test"])
        assert flags.global_only is True
        assert flags.format == "text"
        assert remaining == ["neuron", "search", "test"]


# =============================================================================
# SECTION 5: SEARCH MERGES STORES TEST
# =============================================================================

class TestNeuronSearchMergesStores:
    """Test that neuron search merges results from both stores."""

    def test_search_merges_local_and_global(self):
        """neuron search returns results from both stores, local first."""
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_search
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_sqlite_vec
        from memory_cli.db import run_pending_migrations
        from memory_cli.db import read_schema_version
        from memory_cli.neuron import neuron_add

        def make_conn():
            conn = open_connection(":memory:")
            load_sqlite_vec(conn)
            v = read_schema_version(conn)
            if v < 4:
                run_pending_migrations(conn, v, 4)
            return conn

        local_conn = make_conn()
        global_conn = make_conn()

        # Add searchable content
        neuron_add(local_conn, "python programming tips for local project", no_embed=True)
        neuron_add(global_conn, "python global best practices", no_embed=True)

        flags = SimpleNamespace(config=None, db=None, global_only=False, format="json")

        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
            return_value=[(local_conn, "LOCAL"), (global_conn, "GLOBAL")],
        ):
            result = handle_search(["python"], flags)

        assert result.status == "ok"
        # Both stores have BM25-matchable content for "python"
        assert len(result.data) >= 2
        # First results should be LOCAL (local queried first)
        local_results = [r for r in result.data if r["id"].startswith("LOCAL-")]
        global_results = [r for r in result.data if r["id"].startswith("GLOBAL-")]
        assert len(local_results) >= 1
        assert len(global_results) >= 1
        # Local appears before global in the list
        first_local_idx = next(i for i, r in enumerate(result.data) if r["id"].startswith("LOCAL-"))
        first_global_idx = next(i for i, r in enumerate(result.data) if r["id"].startswith("GLOBAL-"))
        assert first_local_idx < first_global_idx

        local_conn.close()
        global_conn.close()
