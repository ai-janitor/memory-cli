from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from memory_cli.gate.store_discovery_all_local_gates import (
    StoreGateResult,
    discover_all_local_gates,
)


def _make_store(base_path, name, add_neurons=False, add_edges=False):
    """Create a minimal .memory store structure at base_path/name/.memory/."""
    store = base_path / name / ".memory"
    store.mkdir(parents=True, exist_ok=True)
    db_path = store / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS neurons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            weight REAL NOT NULL DEFAULT 1.0
        )
    """)
    if add_neurons:
        conn.execute("INSERT INTO neurons (content) VALUES ('A')")
        conn.execute("INSERT INTO neurons (content) VALUES ('B')")
    if add_edges:
        conn.execute("INSERT INTO edges (source_id, target_id, reason) VALUES (1, 2, 'link')")
    conn.commit()
    conn.close()
    config = store / "config.json"
    config.write_text(json.dumps({"db_path": str(db_path)}))
    return config


class TestNoStores:
    def test_no_stores_returns_empty(self, tmp_path):
        """When no config paths found, returns []."""
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert result == []


class TestSkippedStores:
    def test_missing_db_path_in_config_skipped(self, tmp_path):
        """Config without db_path field is skipped."""
        store = tmp_path / "store" / ".memory"
        store.mkdir(parents=True)
        config = store / "config.json"
        config.write_text(json.dumps({"other_key": "value"}))
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert result == []

    def test_nonexistent_db_file_skipped(self, tmp_path):
        """Config pointing to a non-existent DB file is skipped."""
        store = tmp_path / "store" / ".memory"
        store.mkdir(parents=True)
        config = store / "config.json"
        config.write_text(json.dumps({"db_path": str(store / "nonexistent.db")}))
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert result == []

    def test_malformed_config_json_skipped(self, tmp_path):
        """Malformed JSON in config is skipped gracefully."""
        store = tmp_path / "store" / ".memory"
        store.mkdir(parents=True)
        config = store / "config.json"
        config.write_text("{not valid json")
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert result == []


class TestEmptyStore:
    def test_empty_db_returns_none_gate(self, tmp_path):
        """Store with empty DB (no neurons) -> gate_neuron_id=None, edge_count=0."""
        config = _make_store(tmp_path, "empty_store")
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert len(result) == 1
            assert result[0].gate_neuron_id is None
            assert result[0].edge_count == 0

    def test_neurons_no_edges_returns_none_gate(self, tmp_path):
        """Store with neurons but no edges -> gate_neuron_id=None, edge_count=0."""
        config = _make_store(tmp_path, "no_edge_store", add_neurons=True)
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert len(result) == 1
            assert result[0].gate_neuron_id is None


class TestStoreWithGate:
    def test_gate_found_in_populated_store(self, tmp_path):
        """Store with neurons and edges -> gate_neuron_id set, edge_count > 0."""
        config = _make_store(tmp_path, "live_store", add_neurons=True, add_edges=True)
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert len(result) == 1
            assert result[0].gate_neuron_id is not None
            assert result[0].edge_count > 0

    def test_store_path_is_two_levels_up_from_config(self, tmp_path):
        """store_path is derived correctly: config.parent.parent."""
        config = _make_store(tmp_path, "myproject")
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert len(result) == 1
            assert result[0].store_path == config.parent.parent


class TestMultipleStores:
    def test_two_stores_both_returned(self, tmp_path):
        """LOCAL and GLOBAL stores both returned."""
        local_cfg = _make_store(tmp_path, "local_store", add_neurons=True, add_edges=True)
        global_cfg = _make_store(tmp_path, "global_store", add_neurons=True, add_edges=True)
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(local_cfg, "LOCAL"), (global_cfg, "GLOBAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert len(result) == 2

    def test_bad_store_skipped_good_store_returned(self, tmp_path):
        """If one store is bad (missing DB), it's skipped; others still returned."""
        good_cfg = _make_store(tmp_path, "good_store", add_neurons=True, add_edges=True)
        bad_store = tmp_path / "bad_store" / ".memory"
        bad_store.mkdir(parents=True)
        bad_cfg = bad_store / "config.json"
        bad_cfg.write_text(json.dumps({"db_path": str(bad_store / "missing.db")}))
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(bad_cfg, "LOCAL"), (good_cfg, "GLOBAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert len(result) == 1


class TestReturnType:
    def test_returns_store_gate_result(self, tmp_path):
        """Each result is a StoreGateResult namedtuple."""
        config = _make_store(tmp_path, "typed_store", add_neurons=True, add_edges=True)
        with patch(
            "memory_cli.gate.store_discovery_all_local_gates.resolve_all_config_paths",
            return_value=[(config, "LOCAL")],
        ):
            result = discover_all_local_gates(cwd=tmp_path)
            assert len(result) == 1
            assert isinstance(result[0], StoreGateResult)
            assert hasattr(result[0], "store_path")
            assert hasattr(result[0], "scope")
            assert hasattr(result[0], "gate_neuron_id")
            assert hasattr(result[0], "edge_count")
