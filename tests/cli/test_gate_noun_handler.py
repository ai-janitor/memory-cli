from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from memory_cli.cli.noun_handlers.gate_noun_handler import (
    handle_show,
    handle_register,
    handle_deregister,
)
from memory_cli.gate.gate_compute_densest_node import GateResult
from memory_cli.gate.gate_neighborhood_discovery import NeighborResult
from memory_cli.gate.store_discovery_all_local_gates import StoreGateResult
from memory_cli.gate.gate_register_deregister import GateRegistrationError


def _make_global_flags(db=None, config=None, global_only=False, format="json"):
    """Create a minimal GlobalFlags namespace."""
    return SimpleNamespace(db=db, config=config, global_only=global_only, format=format)


def _make_conn(scope_tag="local"):
    """Minimal in-memory SQLite with neurons + edges schema."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE neurons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            project TEXT, source TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES neurons(id),
            target_id INTEGER NOT NULL REFERENCES neurons(id),
            reason TEXT NOT NULL DEFAULT '',
            weight REAL NOT NULL DEFAULT 1.0
        )
    """)
    db.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)")
    db.execute("""
        CREATE TABLE neuron_tags (
            neuron_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
            PRIMARY KEY (neuron_id, tag_id)
        )
    """)
    db.execute("CREATE TABLE attrs (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE)")
    db.execute("""
        CREATE TABLE neuron_attrs (
            neuron_id INTEGER NOT NULL, attr_id INTEGER NOT NULL, value TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (neuron_id, attr_id)
        )
    """)
    db.commit()
    return db


def _make_config(db_path="memory.db", scope="LOCAL"):
    """Create a mock MemoryConfig-like object."""
    cfg = MagicMock()
    cfg.db_path = db_path
    return cfg


class TestHandleShow:
    def test_show_empty_store_returns_ok(self):
        """handle_show on an empty store: gate_neuron_id=None, houses=[]."""
        conn = _make_conn()
        flags = _make_global_flags()
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_scope",
            return_value=(conn, "LOCAL"),
        ), patch(
            "memory_cli.gate.gate_compute_densest_node.compute_densest_node",
            return_value=None,
        ), patch(
            "memory_cli.gate.store_discovery_all_local_gates.discover_all_local_gates",
            return_value=[],
        ):
            result = handle_show([], flags)
            assert result.status == "ok"
            cs = result.data["current_store"]
            assert cs["gate_neuron_id"] is None
            assert cs["edge_count"] == 0
            assert cs["houses"] == []
            assert result.data["all_stores"] == []

    def test_show_with_gate_and_houses(self):
        """handle_show with gate returns houses from neighborhood discovery."""
        conn = _make_conn()
        flags = _make_global_flags()
        gate = GateResult(neuron_id=10, edge_count=5)
        neighbors = [
            NeighborResult(target_id=20, reason="linked", weight=2.0),
            NeighborResult(target_id=30, reason="related", weight=1.5),
        ]
        stores = [
            StoreGateResult(store_path=Path("/my/project"), scope="LOCAL", gate_neuron_id=10, edge_count=5),
            StoreGateResult(store_path=Path("/home/user"), scope="GLOBAL", gate_neuron_id=100, edge_count=5),
        ]
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_scope",
            return_value=(conn, "LOCAL"),
        ), patch(
            "memory_cli.gate.gate_compute_densest_node.compute_densest_node",
            return_value=gate,
        ), patch(
            "memory_cli.gate.gate_neighborhood_discovery.discover_neighborhood",
            return_value=neighbors,
        ), patch(
            "memory_cli.gate.store_discovery_all_local_gates.discover_all_local_gates",
            return_value=stores,
        ):
            result = handle_show([], flags)
            assert result.status == "ok"
            cs = result.data["current_store"]
            assert cs["gate_neuron_id"] == 10
            assert cs["edge_count"] == 5
            assert len(cs["houses"]) == 2
            assert cs["houses"][0]["target_id"] == 20
            assert cs["houses"][0]["weight"] == 2.0
            all_stores = result.data["all_stores"]
            assert len(all_stores) == 2
            assert all_stores[0]["scope"] == "LOCAL"
            assert all_stores[1]["scope"] == "GLOBAL"

    def test_show_respects_top_n_flag(self):
        """handle_show passes --top-n to discover_neighborhood."""
        conn = _make_conn()
        flags = _make_global_flags()
        gate = GateResult(neuron_id=10, edge_count=5)
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_scope",
            return_value=(conn, "LOCAL"),
        ), patch(
            "memory_cli.gate.gate_compute_densest_node.compute_densest_node",
            return_value=gate,
        ), patch(
            "memory_cli.gate.gate_neighborhood_discovery.discover_neighborhood",
            return_value=[],
        ) as mock_discover, patch(
            "memory_cli.gate.store_discovery_all_local_gates.discover_all_local_gates",
            return_value=[],
        ):
            handle_show(["--top-n", "3"], flags)
            mock_discover.assert_called_once_with(conn, 10, top_n=3)

    def test_show_returns_error_on_exception(self):
        """handle_show wraps exceptions in error result."""
        flags = _make_global_flags()
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_scope",
            side_effect=RuntimeError("DB boom"),
        ):
            result = handle_show([], flags)
            assert result.status == "error"
            assert "DB boom" in result.error


class TestHandleRegister:
    def _make_local_setup(self, tmp_path):
        """Create minimal local store config for handle_register."""
        (tmp_path / ".memory").mkdir(parents=True)
        db_file = tmp_path / ".memory" / "memory.db"
        cfg = _make_config(str(db_file))
        conn = _make_conn()
        return conn, cfg

    def test_register_from_local_succeeds(self, tmp_path):
        """handle_register from a local store creates registration successfully."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        global_conn = _make_conn("GLOBAL")
        flags = _make_global_flags()
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="LOCAL",
        ), patch(
            "memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
        ) as mock_global_path, patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags._open_config_path",
            return_value=(global_conn, "memory.db"),
        ), patch(
            "memory_cli.gate.gate_register_deregister.register",
            return_value={
                "neuron_id": 42,
                "project_path": str(tmp_path),
                "edge_created": True,
                "global_gate_id": 1,
                "message": "Registered project in global store",
            },
        ):
            mock_global_path.return_value = MagicMock(is_file=MagicMock(return_value=True))
            result = handle_register([], flags)
            assert result.status == "ok"
            assert result.data["neuron_id"] == 42

    def test_register_from_global_returns_error(self, tmp_path):
        """handle_register from global store returns error."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        flags = _make_global_flags()
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="GLOBAL",
        ):
            result = handle_register([], flags)
            assert result.status == "error"
            assert "global" in result.error.lower()
            assert "Cannot register" in result.error

    def test_register_error_when_global_store_missing(self, tmp_path):
        """handle_register returns error when global store doesn't exist."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        flags = _make_global_flags()
        missing_path = MagicMock()
        missing_path.is_file.return_value = False
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="LOCAL",
        ), patch(
            "memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
            return_value=missing_path,
        ):
            result = handle_register([], flags)
            assert result.status == "error"
            assert "global" in result.error.lower()
            assert "No global" in result.error

    def test_register_propagates_registration_error(self, tmp_path):
        """handle_register propagates GateRegistrationError as error result."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        global_conn = _make_conn("GLOBAL")
        flags = _make_global_flags()
        present_path = MagicMock()
        present_path.is_file.return_value = True
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="LOCAL",
        ), patch(
            "memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
            return_value=present_path,
        ), patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags._open_config_path",
            return_value=(global_conn, "memory.db"),
        ), patch(
            "memory_cli.gate.gate_register_deregister.register",
            side_effect=GateRegistrationError("already registered"),
        ):
            result = handle_register([], flags)
            assert result.status == "error"
            assert "already registered" in result.error


class TestHandleDeregister:
    def _make_local_setup(self, tmp_path):
        """Create minimal local store config for handle_deregister."""
        (tmp_path / ".memory").mkdir(parents=True)
        db_file = tmp_path / ".memory" / "memory.db"
        cfg = _make_config(str(db_file))
        conn = _make_conn()
        return conn, cfg

    def test_deregister_from_local_succeeds(self, tmp_path):
        """handle_deregister from a local store removes registration successfully."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        global_conn = _make_conn("GLOBAL")
        flags = _make_global_flags()
        present_path = MagicMock()
        present_path.is_file.return_value = True
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="LOCAL",
        ), patch(
            "memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
            return_value=present_path,
        ), patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags._open_config_path",
            return_value=(global_conn, "memory.db"),
        ), patch(
            "memory_cli.gate.gate_register_deregister.deregister",
            return_value={
                "neuron_id": 42,
                "project_path": str(tmp_path),
                "edges_removed": 1,
                "message": "Deregistered project from global store",
            },
        ):
            result = handle_deregister([], flags)
            assert result.status == "ok"
            assert result.data["neuron_id"] == 42
            assert result.data["edges_removed"] == 1

    def test_deregister_from_global_returns_error(self, tmp_path):
        """handle_deregister from global store returns error."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        flags = _make_global_flags()
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="GLOBAL",
        ):
            result = handle_deregister([], flags)
            assert result.status == "error"
            assert "global" in result.error.lower()
            assert "Cannot deregister" in result.error

    def test_deregister_error_when_global_store_missing(self, tmp_path):
        """handle_deregister returns error when global store doesn't exist."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        flags = _make_global_flags()
        missing_path = MagicMock()
        missing_path.is_file.return_value = False
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="LOCAL",
        ), patch(
            "memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
            return_value=missing_path,
        ):
            result = handle_deregister([], flags)
            assert result.status == "error"
            assert "global" in result.error.lower()
            assert "No global" in result.error

    def test_deregister_propagates_registration_error(self, tmp_path):
        """handle_deregister propagates GateRegistrationError as error result."""
        local_conn, local_cfg = self._make_local_setup(tmp_path)
        global_conn = _make_conn("GLOBAL")
        flags = _make_global_flags()
        present_path = MagicMock()
        present_path.is_file.return_value = True
        with patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_connection_and_config",
            return_value=(local_conn, local_cfg),
        ), patch(
            "memory_cli.cli.scoped_handle_format_and_parse.detect_scope",
            return_value="LOCAL",
        ), patch(
            "memory_cli.config.config_path_resolution_ancestor_walk._global_config_path",
            return_value=present_path,
        ), patch(
            "memory_cli.cli.noun_handlers.db_connection_from_global_flags._open_config_path",
            return_value=(global_conn, "memory.db"),
        ), patch(
            "memory_cli.gate.gate_register_deregister.deregister",
            side_effect=GateRegistrationError("No registration found"),
        ):
            result = handle_deregister([], flags)
            assert result.status == "error"
            assert "No registration found" in result.error
