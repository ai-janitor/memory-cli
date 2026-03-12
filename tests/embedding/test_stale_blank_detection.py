# =============================================================================
# test_stale_blank_detection.py — Tests for blank/stale queries and filters
# =============================================================================
# Purpose:     Verify that blank and stale neuron detection queries return the
#              correct neuron IDs based on vec0 presence and timestamp comparison,
#              with optional project filtering.
# Rationale:   Accurate detection drives the batch re-embed process. False
#              negatives mean neurons never get embedded; false positives waste
#              compute re-embedding up-to-date neurons.
# Responsibility:
#   - Test get_blank_neuron_ids: finds neurons with no vec0 row
#   - Test get_stale_neuron_ids: finds neurons where updated_at > embedding_updated_at
#   - Test get_all_reembed_candidates: union of blank + stale, deduped
#   - Test project filter narrows results
#   - Test archived (status=archived) neurons are excluded
#   - Test fresh neurons (updated_at <= embedding_updated_at) are excluded from stale
# Organization:
#   Uses pytest fixtures with migrated in-memory SQLite seeded with test neurons.
# =============================================================================

from __future__ import annotations

import struct
import time

import pytest
import sqlite3

from memory_cli.embedding.stale_and_blank_vector_detection import (
    get_all_reembed_candidates,
    get_blank_neuron_ids,
    get_stale_neuron_ids,
)


@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including neurons_vec."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _make_blob() -> bytes:
    """Create a valid 768-dim zero vector blob."""
    return struct.pack("<768f", *([0.0] * 768))


def _insert_neuron(
    conn: sqlite3.Connection,
    content: str = "test",
    project: str = "proj-a",
    updated_at: int | None = None,
    embedding_updated_at: int | None = None,
    status: str = "active",
) -> int:
    """Insert a test neuron and return its integer id."""
    now_ms = int(time.time() * 1000)
    if updated_at is None:
        updated_at = now_ms
    cursor = conn.execute(
        """INSERT INTO neurons
           (content, created_at, updated_at, project, embedding_updated_at, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (content, now_ms, updated_at, project, embedding_updated_at, status),
    )
    return cursor.lastrowid


def _insert_vec(conn: sqlite3.Connection, neuron_id: int) -> None:
    """Insert a vec0 row for the given neuron."""
    blob = _make_blob()
    conn.execute(
        "INSERT OR REPLACE INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
        (neuron_id, blob),
    )


@pytest.fixture
def seeded_conn(migrated_conn):
    """DB seeded with neurons in various embedding states."""
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 10000  # 10 seconds ago

    # blank-proj-a: no vec0 row, project=proj-a
    blank_a = _insert_neuron(migrated_conn, content="blank a", project="proj-a", updated_at=now_ms)

    # blank-proj-b: no vec0 row, project=proj-b
    blank_b = _insert_neuron(migrated_conn, content="blank b", project="proj-b", updated_at=now_ms)

    # stale-proj-a: has vec0, updated_at > embedding_updated_at
    stale_a = _insert_neuron(
        migrated_conn,
        content="stale a",
        project="proj-a",
        updated_at=now_ms,
        embedding_updated_at=old_ms,
    )
    _insert_vec(migrated_conn, stale_a)

    # stale-proj-b: has vec0, updated_at > embedding_updated_at
    stale_b = _insert_neuron(
        migrated_conn,
        content="stale b",
        project="proj-b",
        updated_at=now_ms,
        embedding_updated_at=old_ms,
    )
    _insert_vec(migrated_conn, stale_b)

    # fresh-proj-a: has vec0, embedding_updated_at >= updated_at
    fresh_a = _insert_neuron(
        migrated_conn,
        content="fresh a",
        project="proj-a",
        updated_at=old_ms,
        embedding_updated_at=now_ms,
    )
    _insert_vec(migrated_conn, fresh_a)

    # archived-blank: no vec0, but archived
    archived_blank = _insert_neuron(
        migrated_conn, content="archived blank", project="proj-a", status="archived"
    )

    # archived-stale: has vec0, stale, but archived
    archived_stale = _insert_neuron(
        migrated_conn,
        content="archived stale",
        project="proj-a",
        updated_at=now_ms,
        embedding_updated_at=old_ms,
        status="archived",
    )
    _insert_vec(migrated_conn, archived_stale)

    migrated_conn.execute("COMMIT")

    return {
        "conn": migrated_conn,
        "blank_a": blank_a,
        "blank_b": blank_b,
        "stale_a": stale_a,
        "stale_b": stale_b,
        "fresh_a": fresh_a,
        "archived_blank": archived_blank,
        "archived_stale": archived_stale,
    }


class TestBlankDetection:
    """get_blank_neuron_ids() finds neurons with no vec0 row."""

    # --- Test: returns blank neurons only ---
    # result = get_blank_neuron_ids(conn)
    # assert set(result) == {"blank-1", "blank-2"}
    # "fresh-1", "stale-1", "stale-2" should NOT be included (they have vec0 rows)
    def test_returns_blank_neurons_only(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_blank_neuron_ids(conn)
        assert set(result) == {seeded_conn["blank_a"], seeded_conn["blank_b"]}

    # --- Test: excludes archived neurons ---
    # "archived-blank" should NOT appear in results
    def test_excludes_archived(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_blank_neuron_ids(conn)
        assert seeded_conn["archived_blank"] not in result

    # --- Test: project filter ---
    # result = get_blank_neuron_ids(conn, project_id="proj-a")
    # assert result == ["blank-1"]
    # "blank-2" is in proj-b, should not appear
    def test_project_filter(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_blank_neuron_ids(conn, project_id="proj-a")
        assert result == [seeded_conn["blank_a"]]


class TestStaleDetection:
    """get_stale_neuron_ids() finds neurons where updated_at > embedding_updated_at."""

    # --- Test: returns stale neurons only ---
    # result = get_stale_neuron_ids(conn)
    # assert set(result) == {"stale-1", "stale-2"}
    # "fresh-1" should NOT be included (it's up to date)
    # "blank-1", "blank-2" should NOT be included (no embedding_updated_at)
    def test_returns_stale_neurons_only(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_stale_neuron_ids(conn)
        assert set(result) == {seeded_conn["stale_a"], seeded_conn["stale_b"]}

    # --- Test: excludes archived neurons ---
    # "archived-stale" should NOT appear in results
    def test_excludes_archived(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_stale_neuron_ids(conn)
        assert seeded_conn["archived_stale"] not in result

    def test_excludes_fresh_neurons(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_stale_neuron_ids(conn)
        assert seeded_conn["fresh_a"] not in result

    def test_excludes_blank_neurons(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_stale_neuron_ids(conn)
        assert seeded_conn["blank_a"] not in result
        assert seeded_conn["blank_b"] not in result

    # --- Test: project filter ---
    # result = get_stale_neuron_ids(conn, project_id="proj-b")
    # assert result == ["stale-2"]
    def test_project_filter(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_stale_neuron_ids(conn, project_id="proj-b")
        assert result == [seeded_conn["stale_b"]]


class TestAllReembedCandidates:
    """get_all_reembed_candidates() returns blank + stale, deduplicated."""

    # --- Test: returns union of blank and stale ---
    # result = get_all_reembed_candidates(conn)
    # assert set(result) == {"blank-1", "blank-2", "stale-1", "stale-2"}
    def test_returns_union_of_blank_and_stale(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_all_reembed_candidates(conn)
        assert set(result) == {
            seeded_conn["blank_a"],
            seeded_conn["blank_b"],
            seeded_conn["stale_a"],
            seeded_conn["stale_b"],
        }

    # --- Test: blanks come before stale in result order ---
    # result = get_all_reembed_candidates(conn)
    # blank_positions = [result.index(x) for x in ["blank-1", "blank-2"]]
    # stale_positions = [result.index(x) for x in ["stale-1", "stale-2"]]
    # assert max(blank_positions) < min(stale_positions)
    def test_blanks_before_stale_in_order(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_all_reembed_candidates(conn)
        blank_ids = {seeded_conn["blank_a"], seeded_conn["blank_b"]}
        stale_ids = {seeded_conn["stale_a"], seeded_conn["stale_b"]}
        blank_positions = [result.index(x) for x in blank_ids if x in result]
        stale_positions = [result.index(x) for x in stale_ids if x in result]
        assert max(blank_positions) < min(stale_positions)

    # --- Test: project filter ---
    # result = get_all_reembed_candidates(conn, project_id="proj-a")
    # assert set(result) == {"blank-1", "stale-1"}
    def test_project_filter(self, seeded_conn):
        conn = seeded_conn["conn"]
        result = get_all_reembed_candidates(conn, project_id="proj-a")
        assert set(result) == {seeded_conn["blank_a"], seeded_conn["stale_a"]}

    # --- Test: no candidates returns empty list ---
    # Use a DB with only fresh neurons
    # result = get_all_reembed_candidates(conn)
    # assert result == []
    def test_no_candidates_returns_empty(self, migrated_conn):
        # Only insert a fresh neuron (has vec, up to date)
        now_ms = int(time.time() * 1000)
        old_ms = now_ms - 10000
        neuron_id = _insert_neuron(
            migrated_conn,
            updated_at=old_ms,
            embedding_updated_at=now_ms,
        )
        _insert_vec(migrated_conn, neuron_id)
        migrated_conn.execute("COMMIT")

        result = get_all_reembed_candidates(migrated_conn)
        assert result == []
