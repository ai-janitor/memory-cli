from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from memory_cli.gate.gate_register_deregister import (
    GATE_REGISTRATION_SOURCE,
    GateRegistrationError,
    _find_representative_neuron,
    _hard_delete_neuron,
    _build_representative_content,
    register,
    deregister,
)
from memory_cli.gate.gate_compute_densest_node import GateResult


def _make_conn(scope_tag="local"):
    """Minimal in-memory SQLite with schema."""
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


def _insert_neuron(conn, content, source=None, status="active"):
    cur = conn.execute(
        "INSERT INTO neurons (content, source, status) VALUES (?, ?, ?)",
        (content, source, status),
    )
    conn.commit()
    return cur.lastrowid


def _insert_edge(conn, source_id, target_id, reason="", weight=1.0):
    conn.execute(
        "INSERT INTO edges (source_id, target_id, reason, weight) VALUES (?, ?, ?, ?)",
        (source_id, target_id, reason, weight),
    )
    conn.commit()


@pytest.fixture
def local_conn():
    conn = _make_conn("LOCAL")
    yield conn
    conn.close()


@pytest.fixture
def global_conn():
    conn = _make_conn("GLOBAL")
    yield conn
    conn.close()


@pytest.fixture
def local_path(tmp_path):
    return tmp_path / "my_project"


class TestFindRepresentativeNeuron:
    def test_returns_none_when_empty(self, global_conn):
        result = _find_representative_neuron(global_conn, "/some/path")
        assert result is None

    def test_finds_neuron_by_source_and_path(self, global_conn):
        path = "/Users/hung/projects/my_project"
        content = f"Gate registration for project: my_project\npath: {path}\nlocal_gate: no_gate"
        nid = _insert_neuron(global_conn, content, source=GATE_REGISTRATION_SOURCE)
        result = _find_representative_neuron(global_conn, path)
        assert result == nid

    def test_does_not_match_different_source(self, global_conn):
        path = "/Users/hung/projects/my_project"
        _insert_neuron(global_conn, f"path: {path}", source="something:else")
        result = _find_representative_neuron(global_conn, path)
        assert result is None

    def test_does_not_match_different_path(self, global_conn):
        _insert_neuron(
            global_conn,
            "Gate registration for project: other\npath: /other/path\nlocal_gate: no_gate",
            source=GATE_REGISTRATION_SOURCE,
        )
        result = _find_representative_neuron(global_conn, "/my/project")
        assert result is None

    def test_skips_archived_neuron(self, global_conn):
        """Archived (status != 'active') neurons are not returned."""
        path = "/Users/hung/projects/archived_project"
        nid = _insert_neuron(
            global_conn,
            f"path: {path}\n",
            source=GATE_REGISTRATION_SOURCE,
        )
        global_conn.execute("UPDATE neurons SET status = 'archived' WHERE id = ?", (nid,))
        global_conn.commit()
        result = _find_representative_neuron(global_conn, path)
        assert result is None


class TestHardDeleteNeuron:
    def test_deletes_neuron_and_edges(self, global_conn):
        a = _insert_neuron(global_conn, "alpha")
        b = _insert_neuron(global_conn, "beta")
        _insert_edge(global_conn, a, b)
        edges_removed = _hard_delete_neuron(global_conn, a)
        assert edges_removed == 1
        row = global_conn.execute("SELECT * FROM neurons WHERE id = ?", (a,)).fetchone()
        assert row is None

    def test_returns_zero_edges_when_isolated(self, global_conn):
        nid = _insert_neuron(global_conn, "lone neuron")
        count = _hard_delete_neuron(global_conn, nid)
        assert count == 0

    def test_deletes_tag_junctions(self, global_conn):
        nid = _insert_neuron(global_conn, "tagged neuron")
        global_conn.execute("INSERT INTO tags (name) VALUES ('t1')")
        global_conn.execute("INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (?, 1)", (nid,))
        global_conn.commit()
        _hard_delete_neuron(global_conn, nid)
        row = global_conn.execute("SELECT * FROM neuron_tags WHERE neuron_id = ?", (nid,)).fetchone()
        assert row is None

    def test_deletes_attr_junctions(self, global_conn):
        nid = _insert_neuron(global_conn, "attr neuron")
        global_conn.execute("INSERT INTO attrs (key) VALUES ('k1')")
        global_conn.execute("INSERT INTO neuron_attrs (neuron_id, attr_id, value) VALUES (?, 1, 'v')", (nid,))
        global_conn.commit()
        _hard_delete_neuron(global_conn, nid)
        row = global_conn.execute("SELECT * FROM neuron_attrs WHERE neuron_id = ?", (nid,)).fetchone()
        assert row is None


class TestBuildRepresentativeContent:
    def test_with_gate(self):
        path = Path("/Users/hung/projects/myapp")
        gate = GateResult(neuron_id=42, edge_count=10)
        content = _build_representative_content(path, gate)
        assert "myapp" in content
        assert "gate_neuron_id=42" in content
        assert "edge_count=10" in content

    def test_without_gate(self):
        path = Path("/Users/hung/projects/empty_project")
        content = _build_representative_content(path, None)
        assert "empty_project" in content
        assert "no_gate" in content


class TestRegister:
    def test_register_creates_rep_neuron_and_returns_dict(self, local_conn, global_conn, local_path):
        """register() creates rep neuron in global and returns result dict."""
        with patch("memory_cli.neuron.neuron_add") as mock_add, \
             patch("memory_cli.gate.gate_compute_densest_node.compute_densest_node") as mock_gate:
            mock_gate.return_value = None
            mock_add.return_value = {"id": 99, "content": "gate registration"}
            result = register(local_conn, local_path, global_conn)
            assert "neuron_id" in result
            assert result["neuron_id"] == 99

    def test_register_edges_to_global_gate_if_exists(self, local_conn, global_conn, local_path):
        """register() creates edge from global gate to rep neuron."""
        with patch("memory_cli.neuron.neuron_add") as mock_add, \
             patch("memory_cli.gate.gate_compute_densest_node.compute_densest_node") as mock_gate, \
             patch("memory_cli.edge.edge_add") as mock_edge:
            # First call (local) returns None, second call (global) returns gate
            mock_gate.side_effect = [None, GateResult(neuron_id=1, edge_count=5)]
            mock_add.return_value = {"id": 99, "content": "gate registration"}
            result = register(local_conn, local_path, global_conn)
            assert result["edge_created"] is True
            mock_edge.assert_called_once()

    def test_register_raises_on_duplicate(self, local_conn, global_conn, local_path):
        """register() raises GateRegistrationError if project already registered."""
        # Insert an existing registration
        _insert_neuron(
            global_conn,
            f"path: {local_path}\ngate registration",
            source=GATE_REGISTRATION_SOURCE,
        )
        with patch("memory_cli.gate.gate_compute_densest_node.compute_densest_node") as mock_gate:
            mock_gate.return_value = None
            with pytest.raises(GateRegistrationError, match="already registered"):
                register(local_conn, local_path, global_conn)

    def test_register_no_edge_when_no_global_gate(self, local_conn, global_conn, local_path):
        """register() succeeds even when global store has no gate."""
        with patch("memory_cli.neuron.neuron_add") as mock_add, \
             patch("memory_cli.gate.gate_compute_densest_node.compute_densest_node") as mock_gate:
            mock_gate.return_value = None
            mock_add.return_value = {"id": 99, "content": "gate registration"}
            result = register(local_conn, local_path, global_conn)
            assert result["edge_created"] is False


class TestDeregister:
    def test_deregister_removes_rep_neuron(self, global_conn, local_path):
        """deregister() removes the representative neuron from global store."""
        nid = _insert_neuron(
            global_conn,
            f"Gate registration for project: {local_path.name}\npath: {local_path}\n",
            source=GATE_REGISTRATION_SOURCE,
        )
        result = deregister(local_path, global_conn)
        assert result["neuron_id"] == nid
        row = global_conn.execute("SELECT * FROM neurons WHERE id = ?", (nid,)).fetchone()
        assert row is None

    def test_deregister_removes_edges(self, global_conn, local_path):
        """deregister() removes edges connected to the rep neuron."""
        nid = _insert_neuron(
            global_conn,
            f"path: {local_path}\n",
            source=GATE_REGISTRATION_SOURCE,
        )
        gid = _insert_neuron(global_conn, "global gate")
        _insert_edge(global_conn, gid, nid)
        result = deregister(local_path, global_conn)
        assert result["edges_removed"] == 1

    def test_deregister_raises_when_not_registered(self, global_conn, local_path):
        """deregister() raises GateRegistrationError when nothing to deregister."""
        with pytest.raises(GateRegistrationError, match="No registration found"):
            deregister(local_path, global_conn)
