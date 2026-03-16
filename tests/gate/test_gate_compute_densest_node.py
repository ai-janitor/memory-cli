from __future__ import annotations

import sqlite3
import pytest
from memory_cli.gate.gate_compute_densest_node import GateResult, compute_densest_node


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE neurons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
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
    db.commit()
    return db


def _add_neuron(conn, content):
    cur = conn.execute("INSERT INTO neurons (content) VALUES (?)", (content,))
    conn.commit()
    return cur.lastrowid


def _add_edge(conn, source_id, target_id, reason="", weight=1.0):
    conn.execute(
        "INSERT INTO edges (source_id, target_id, reason, weight) VALUES (?, ?, ?, ?)",
        (source_id, target_id, reason, weight),
    )
    conn.commit()


class TestEmptyStore:
    def test_no_neurons_returns_none(self, conn):
        """Empty store: no neurons, no edges -> None."""
        result = compute_densest_node(conn)
        assert result is None

    def test_neurons_no_edges_returns_none(self, conn):
        """Neurons exist but no edges -> None (no connectivity to measure)."""
        _add_neuron(conn, "alpha")
        _add_neuron(conn, "beta")
        result = compute_densest_node(conn)
        assert result is None


class TestSingleNeuron:
    def test_single_neuron_with_self_loop(self, conn):
        """Single neuron with a self-loop edge -> returns that neuron, count=2."""
        nid = _add_neuron(conn, "solo")
        _add_edge(conn, nid, nid)
        result = compute_densest_node(conn)
        assert result is not None
        assert result.neuron_id == nid
        assert result.edge_count == 2

    def test_single_neuron_one_outgoing(self, conn):
        """Two neurons, one edge: source neuron has degree 1, target has degree 1."""
        s = _add_neuron(conn, "source")
        t = _add_neuron(conn, "target")
        _add_edge(conn, s, t)
        result = compute_densest_node(conn)
        assert result is not None
        # Tie: both have degree 1, lowest ID wins
        assert result.neuron_id == s
        assert result.edge_count == 1


class TestDensestNodeSelection:
    def test_highest_degree_wins(self, conn):
        """Neuron with most total edges (both directions) is selected."""
        hub = _add_neuron(conn, "hub")
        spoke1 = _add_neuron(conn, "spoke1")
        spoke2 = _add_neuron(conn, "spoke2")
        _add_edge(conn, hub, spoke1)
        _add_edge(conn, hub, spoke2)
        result = compute_densest_node(conn)
        assert result.neuron_id == hub
        assert result.edge_count == 2

    def test_incoming_edges_count_toward_degree(self, conn):
        """Incoming edges count toward total degree, not just outgoing."""
        a = _add_neuron(conn, "A")
        b = _add_neuron(conn, "B")
        c = _add_neuron(conn, "C")
        _add_edge(conn, b, a)
        _add_edge(conn, c, a)
        result = compute_densest_node(conn)
        assert result.neuron_id == a
        assert result.edge_count == 2

    def test_mixed_directions_summed(self, conn):
        """Total degree = outgoing + incoming for each neuron."""
        center = _add_neuron(conn, "center")
        left = _add_neuron(conn, "left")
        right = _add_neuron(conn, "right")
        _add_edge(conn, center, left)
        _add_edge(conn, right, center)
        result = compute_densest_node(conn)
        assert result.neuron_id == center
        assert result.edge_count == 2


class TestTieBreak:
    def test_tie_break_lowest_id_wins(self, conn):
        """When two neurons have equal edge count, lowest ID wins."""
        first = _add_neuron(conn, "first")
        second = _add_neuron(conn, "second")
        _add_edge(conn, first, second)
        result = compute_densest_node(conn)
        assert result.neuron_id == first

    def test_tie_break_three_way(self, conn):
        """Three-way tie -> lowest ID of the three wins."""
        a = _add_neuron(conn, "A")
        b = _add_neuron(conn, "B")
        c = _add_neuron(conn, "C")
        _add_edge(conn, a, b)
        _add_edge(conn, b, c)
        _add_edge(conn, c, a)
        result = compute_densest_node(conn)
        assert result.neuron_id == a


class TestReturnType:
    def test_returns_gate_result_namedtuple(self, conn):
        """Return type is GateResult(neuron_id, edge_count)."""
        a = _add_neuron(conn, "A")
        b = _add_neuron(conn, "B")
        _add_edge(conn, a, b)
        result = compute_densest_node(conn)
        assert isinstance(result, GateResult)
        assert hasattr(result, "neuron_id")
        assert hasattr(result, "edge_count")

    def test_edge_count_is_int(self, conn):
        """edge_count must be an integer."""
        a = _add_neuron(conn, "A")
        b = _add_neuron(conn, "B")
        _add_edge(conn, a, b)
        result = compute_densest_node(conn)
        assert isinstance(result.edge_count, int)
