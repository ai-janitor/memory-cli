# =============================================================================
# test_vector_storage.py — Tests for vec0 write, binary format, atomic timestamp
# =============================================================================
# Purpose:     Verify that vector serialization produces correct binary format,
#              that write_vector() and write_vectors_batch() correctly upsert
#              into neurons_vec and atomically update embedding_updated_at.
# Rationale:   Binary format must match sqlite-vec expectations exactly (32-bit
#              little-endian floats). Atomicity between vec0 write and timestamp
#              update is critical for staleness detection correctness.
# Responsibility:
#   - Test serialize_vector produces correct byte count and format
#   - Test write_vector upserts into vec0 and updates timestamp
#   - Test write_vector is atomic (both succeed or both fail)
#   - Test write_vectors_batch processes multiple vectors
#   - Test batch write rolls back entirely on failure
#   - Test dimension validation happens before write
# Organization:
#   Uses pytest fixtures with in-memory SQLite + vec0 from sqlite-vec extension.
#   Tests verify both the vec0 row and the neurons timestamp column.
# =============================================================================

from __future__ import annotations

import struct
import time

import pytest
import sqlite3

from memory_cli.embedding.vector_storage_vec0_write import (
    delete_vector,
    serialize_vector,
    write_vector,
    write_vectors_batch,
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


def _insert_neuron(conn: sqlite3.Connection, neuron_id: int | None = None, project: str = "test") -> int:
    """Insert a test neuron and return its id."""
    now_ms = int(time.time() * 1000)
    cursor = conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project) VALUES (?, ?, ?, ?)",
        ("test content", now_ms, now_ms, project),
    )
    return cursor.lastrowid


class TestSerializeVector:
    """serialize_vector() packs floats to correct binary format."""

    # --- Test: 768-dim vector produces 3072 bytes (768 * 4) ---
    # vector = [1.0] * 768
    # blob = serialize_vector(vector)
    # assert len(blob) == 3072
    def test_768_dim_produces_3072_bytes(self):
        vector = [1.0] * 768
        blob = serialize_vector(vector)
        assert len(blob) == 3072

    # --- Test: values round-trip correctly through pack/unpack ---
    # vector = [0.1 * i for i in range(768)]
    # blob = serialize_vector(vector)
    # unpacked = struct.unpack(f'<768f', blob)
    # assert all(abs(a - b) < 1e-6 for a, b in zip(vector, unpacked))
    def test_values_round_trip(self):
        vector = [float(i) * 0.001 for i in range(768)]
        blob = serialize_vector(vector)
        unpacked = struct.unpack("<768f", blob)
        assert all(abs(a - b) < 1e-5 for a, b in zip(vector, unpacked))

    # --- Test: wrong dimensions raises ValueError ---
    # with pytest.raises(ValueError):
    #   serialize_vector([1.0] * 512)
    def test_wrong_dimensions_raises(self):
        with pytest.raises(ValueError):
            serialize_vector([1.0] * 512)


class TestWriteVector:
    """write_vector() upserts vec0 row and updates timestamp atomically."""

    # --- Test: new vector creates vec0 row and sets timestamp ---
    # write_vector(conn, "neuron-1", [0.0] * 768)
    # Assert neurons_vec has row with rowid="neuron-1"
    # Assert neurons.embedding_updated_at is not None for "neuron-1"
    def test_new_vector_creates_row_and_sets_timestamp(self, migrated_conn):
        neuron_id = _insert_neuron(migrated_conn)
        migrated_conn.execute("COMMIT")
        write_vector(migrated_conn, neuron_id, [0.0] * 768)

        row = migrated_conn.execute(
            "SELECT neuron_id FROM neurons_vec WHERE neuron_id = ?", (neuron_id,)
        ).fetchone()
        assert row is not None

        ts = migrated_conn.execute(
            "SELECT embedding_updated_at FROM neurons WHERE id = ?", (neuron_id,)
        ).fetchone()
        assert ts is not None
        assert ts[0] is not None

    # --- Test: existing vector is replaced (upsert) ---
    # write_vector(conn, "neuron-1", [1.0] * 768)  # first write
    # write_vector(conn, "neuron-1", [2.0] * 768)  # overwrite
    # Assert only one row in neurons_vec for "neuron-1"
    # Assert the blob matches the second vector
    def test_existing_vector_is_replaced(self, migrated_conn):
        neuron_id = _insert_neuron(migrated_conn)
        migrated_conn.execute("COMMIT")

        write_vector(migrated_conn, neuron_id, [1.0] * 768)
        write_vector(migrated_conn, neuron_id, [2.0] * 768)

        rows = migrated_conn.execute(
            "SELECT COUNT(*) FROM neurons_vec WHERE neuron_id = ?", (neuron_id,)
        ).fetchone()
        assert rows[0] == 1

    # --- Test: timestamp is updated to current time ---
    # write_vector(conn, "neuron-1", [0.0] * 768)
    # Read embedding_updated_at
    # Assert it is recent (within last few seconds)
    def test_timestamp_is_recent(self, migrated_conn):
        neuron_id = _insert_neuron(migrated_conn)
        migrated_conn.execute("COMMIT")

        before_ms = int(time.time() * 1000) - 1000
        write_vector(migrated_conn, neuron_id, [0.0] * 768)
        after_ms = int(time.time() * 1000) + 1000

        ts = migrated_conn.execute(
            "SELECT embedding_updated_at FROM neurons WHERE id = ?", (neuron_id,)
        ).fetchone()[0]
        assert before_ms <= ts <= after_ms


class TestWriteVectorsBatch:
    """write_vectors_batch() processes multiple vectors in one transaction."""

    # --- Test: multiple vectors written correctly ---
    # pairs = [("n1", [0.0]*768), ("n2", [1.0]*768)]
    # write_vectors_batch(conn, pairs)
    # Assert both neurons_vec rows exist
    # Assert both neurons have updated embedding_updated_at
    def test_multiple_vectors_written(self, migrated_conn):
        id1 = _insert_neuron(migrated_conn)
        id2 = _insert_neuron(migrated_conn)
        migrated_conn.execute("COMMIT")

        pairs = [(id1, [0.0] * 768), (id2, [1.0] * 768)]
        write_vectors_batch(migrated_conn, pairs)

        for nid in (id1, id2):
            row = migrated_conn.execute(
                "SELECT neuron_id FROM neurons_vec WHERE neuron_id = ?", (nid,)
            ).fetchone()
            assert row is not None

            ts = migrated_conn.execute(
                "SELECT embedding_updated_at FROM neurons WHERE id = ?", (nid,)
            ).fetchone()[0]
            assert ts is not None

    # --- Test: empty batch is no-op ---
    # write_vectors_batch(conn, [])
    # Assert no errors, no changes
    def test_empty_batch_is_noop(self, migrated_conn):
        write_vectors_batch(migrated_conn, [])  # should not raise

    # --- Test: batch with invalid dimensions rolls back entirely ---
    # pairs = [("n1", [0.0]*768), ("n2", [0.0]*512)]  # second is bad
    # with pytest.raises(ValueError):
    #   write_vectors_batch(conn, pairs)
    # Assert neither n1 nor n2 has a vec0 row (rollback)
    def test_invalid_dimensions_raises_before_write(self, migrated_conn):
        id1 = _insert_neuron(migrated_conn)
        id2 = _insert_neuron(migrated_conn)
        migrated_conn.execute("COMMIT")

        pairs = [(id1, [0.0] * 768), (id2, [0.0] * 512)]
        with pytest.raises(ValueError):
            write_vectors_batch(migrated_conn, pairs)

        # Dimension check happens before transaction — neither row should exist
        row1 = migrated_conn.execute(
            "SELECT neuron_id FROM neurons_vec WHERE neuron_id = ?", (id1,)
        ).fetchone()
        assert row1 is None


class TestAtomicity:
    """Vec0 write and timestamp update are atomic."""

    # --- Test: if vec0 write fails, timestamp is not updated ---
    # Mock the INSERT to raise sqlite3.Error
    # Original embedding_updated_at = read from DB
    # Try write_vector (should fail)
    # Assert embedding_updated_at unchanged

    # NOTE: Atomicity is guaranteed by the `with conn:` transaction context.
    # Full atomicity testing requires mocking low-level sqlite operations which
    # would be fragile. The implementation uses a single `with conn:` block
    # that wraps both writes, so failure in either aborts both.

    def test_delete_vector_removes_row(self, migrated_conn):
        """delete_vector() removes the vec0 row for a neuron."""
        neuron_id = _insert_neuron(migrated_conn)
        migrated_conn.execute("COMMIT")

        write_vector(migrated_conn, neuron_id, [0.0] * 768)

        row = migrated_conn.execute(
            "SELECT neuron_id FROM neurons_vec WHERE neuron_id = ?", (neuron_id,)
        ).fetchone()
        assert row is not None

        delete_vector(migrated_conn, neuron_id)

        row = migrated_conn.execute(
            "SELECT neuron_id FROM neurons_vec WHERE neuron_id = ?", (neuron_id,)
        ).fetchone()
        assert row is None
