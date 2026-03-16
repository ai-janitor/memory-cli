from __future__ import annotations

import sqlite3
import pytest
from memory_cli.gate.gate_neighborhood_discovery import (
    NeighborResult,
    DEFAULT_TOP_N,
    discover_neighborhood,
)


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


class TestEmptyGate:
    def test_no_edges_returns_empty_list(self, conn):
        """Gate neuron with no edges -> empty list."""
        gate = _add_neuron(conn, "gate")
        result = discover_neighborhood(conn, gate)
        assert result == []

    def test_unconnected_gate_neighbors_empty(self, conn):
        """Other neurons exist but none connected to gate -> empty list."""
        gate = _add_neuron(conn, "gate")
        _add_neuron(conn, "A")
        _add_neuron(conn, "B")
        result = discover_neighborhood(conn, gate)
        assert result == []


class TestSingleNeighbor:
    def test_outgoing_edge(self, conn):
        """Gate -> neighbor via outgoing edge."""
        gate = _add_neuron(conn, "gate")
        house1 = _add_neuron(conn, "house1")
        _add_edge(conn, gate, house1, "points_to")
        result = discover_neighborhood(conn, gate)
        assert len(result) == 1
        assert result[0].target_id == house1
        assert result[0].reason == "points_to"

    def test_incoming_edge(self, conn):
        """neighbor -> gate via incoming edge: neighbor is still discovered."""
        gate = _add_neuron(conn, "gate")
        house1 = _add_neuron(conn, "house1")
        _add_edge(conn, house1, gate, "references")
        result = discover_neighborhood(conn, gate)
        assert len(result) == 1
        assert result[0].target_id == house1


class TestSortByWeight:
    def test_sorted_weight_desc(self, conn):
        """Multiple neighbors returned sorted by weight descending."""
        gate = _add_neuron(conn, "gate")
        low = _add_neuron(conn, "low")
        high = _add_neuron(conn, "high")
        mid = _add_neuron(conn, "mid")
        _add_edge(conn, gate, low, weight=0.5)
        _add_edge(conn, gate, high, weight=3.0)
        _add_edge(conn, gate, mid, weight=1.5)
        result = discover_neighborhood(conn, gate)
        assert result[0].target_id == high
        assert result[1].target_id == mid
        assert result[2].target_id == low


class TestTopN:
    def test_top_n_limits_results(self, conn):
        """top_n parameter limits number of results returned."""
        gate = _add_neuron(conn, "gate")
        for i in range(5):
            nid = _add_neuron(conn, f"node{i}")
            _add_edge(conn, gate, nid)
        result = discover_neighborhood(conn, gate, top_n=2)
        assert len(result) == 2

    def test_top_n_default_is_10(self, conn):
        """Default top_n is 10."""
        assert DEFAULT_TOP_N == 10
        gate = _add_neuron(conn, "gate")
        for i in range(15):
            nid = _add_neuron(conn, f"node{i}")
            _add_edge(conn, gate, nid)
        result = discover_neighborhood(conn, gate)
        assert len(result) == 10

    def test_top_n_larger_than_available(self, conn):
        """top_n larger than available neighbors returns all neighbors."""
        gate = _add_neuron(conn, "gate")
        a = _add_neuron(conn, "A")
        b = _add_neuron(conn, "B")
        _add_edge(conn, gate, a)
        _add_edge(conn, gate, b)
        result = discover_neighborhood(conn, gate, top_n=100)
        assert len(result) == 2


class TestDeduplication:
    def test_bidirectional_edges_deduplicated(self, conn):
        """If gate<->neighbor has edges in both directions, neighbor appears once."""
        gate = _add_neuron(conn, "gate")
        neighbor = _add_neuron(conn, "neighbor")
        _add_edge(conn, gate, neighbor, "out", 2.0)
        _add_edge(conn, neighbor, gate, "in", 1.0)
        result = discover_neighborhood(conn, gate)
        assert len(result) == 1
        assert result[0].target_id == neighbor


class TestReturnType:
    def test_returns_neighbor_result_namedtuple(self, conn):
        """Each result is a NeighborResult namedtuple."""
        gate = _add_neuron(conn, "gate")
        a = _add_neuron(conn, "A")
        _add_edge(conn, gate, a, "link")
        result = discover_neighborhood(conn, gate)
        assert len(result) == 1
        assert isinstance(result[0], NeighborResult)
        assert hasattr(result[0], "target_id")
        assert hasattr(result[0], "reason")
        assert hasattr(result[0], "weight")

    def test_weight_is_float(self, conn):
        """Weight field is a float."""
        gate = _add_neuron(conn, "gate")
        a = _add_neuron(conn, "A")
        _add_edge(conn, gate, a)
        result = discover_neighborhood(conn, gate)
        assert isinstance(result[0].weight, float)
