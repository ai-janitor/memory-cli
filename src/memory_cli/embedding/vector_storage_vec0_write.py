# =============================================================================
# vector_storage_vec0_write.py — Write vectors to vec0, binary serialization
# =============================================================================
# Purpose:     Write embedding vectors to the sqlite-vec virtual table
#              (neurons_vec) keyed by neuron_id. Handles binary serialization
#              of float vectors into the packed 32-bit format sqlite-vec expects,
#              and atomically updates the neuron's embedding_updated_at timestamp.
# Rationale:   sqlite-vec stores vectors as binary blobs of packed 32-bit floats.
#              The vector write and timestamp update must be atomic — if one
#              succeeds without the other, the staleness detection logic breaks.
#              A single transaction wraps both operations.
# Responsibility:
#   - Serialize a list[float] vector to bytes (32-bit little-endian floats)
#   - Write/upsert the vector into neurons_vec keyed by neuron_id
#   - Update neurons.embedding_updated_at to current UTC timestamp
#   - Both operations in a single transaction (atomic)
#   - Validate dimensions before write (delegate to dimension_enforcement)
#   - Batch write support for re-embed operations
# Organization:
#   serialize_vector(vector) -> bytes — pack floats to binary
#   write_vector(conn, neuron_id, vector) -> None — single vector write
#   write_vectors_batch(conn, neuron_id_vector_pairs) -> None — batch write
# =============================================================================

from __future__ import annotations

import sqlite3
import struct
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from .dimension_enforcement_768 import validate_dimensions

# Type alias
Vector = list[float]


def serialize_vector(vector: Vector) -> bytes:
    """Serialize a float vector to sqlite-vec binary blob format.

    sqlite-vec expects vectors as packed 32-bit little-endian floats.

    Args:
        vector: A list of floats (must be exactly 768 dimensions).

    Returns:
        Bytes object containing the packed float32 values.
    """
    # --- Step 1: Validate dimensions ---
    # validate_dimensions(vector)  # delegate to dimension_enforcement_768
    validate_dimensions(vector)

    # --- Step 2: Pack to binary ---
    # import struct
    # Use struct.pack with '<768f' format (little-endian, 768 floats)
    # Result is 768 * 4 = 3072 bytes
    # return struct.pack(f'<{len(vector)}f', *vector)
    return struct.pack(f"<{len(vector)}f", *vector)


def write_vector(conn: sqlite3.Connection, neuron_id: int, vector: Vector) -> None:
    """Write a single embedding vector to vec0 and update the neuron timestamp.

    Both operations are atomic within a single transaction. If the vector
    already exists for this neuron_id, it is replaced (upsert).

    Args:
        conn: An open sqlite3.Connection with WAL mode and FK enabled.
        neuron_id: The integer ID of the neuron this vector belongs to.
        vector: A 768-dim float vector to store.

    Raises:
        ValueError: If vector dimensions are not exactly 768.
        sqlite3.Error: If the database write fails.
    """
    # --- Step 1: Serialize the vector ---
    # blob = serialize_vector(vector)
    blob = serialize_vector(vector)

    # --- Step 2: Begin atomic write (transaction) ---
    # Use conn as context manager or explicit BEGIN/COMMIT
    now_ms = int(time.time() * 1000)

    # --- Step 3: Upsert into neurons_vec ---
    # INSERT OR REPLACE INTO neurons_vec (rowid, embedding) VALUES (?, ?)
    # Note: rowid maps to neuron_id in the vec0 virtual table
    # Pass (neuron_id, blob) as parameters

    # --- Step 4: Update embedding_updated_at ---
    # UPDATE neurons SET embedding_updated_at = datetime('now') WHERE id = ?
    # Pass (neuron_id,) as parameter

    # --- Step 5: Commit transaction ---
    # Transaction commits when context manager exits normally
    # Note: vec0 does not support INSERT OR REPLACE when a row already exists.
    # Use DELETE + INSERT pattern for upsert behavior.
    with conn:
        conn.execute("DELETE FROM neurons_vec WHERE neuron_id = ?", (neuron_id,))
        conn.execute(
            "INSERT INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
            (neuron_id, blob),
        )
        conn.execute(
            "UPDATE neurons SET embedding_updated_at = ? WHERE id = ?",
            (now_ms, neuron_id),
        )


def write_vectors_batch(
    conn: sqlite3.Connection,
    neuron_id_vector_pairs: list[tuple[int, Vector]],
) -> None:
    """Write multiple embedding vectors to vec0 with timestamp updates.

    All writes happen in a single transaction for efficiency and atomicity.
    If any single write fails, the entire batch rolls back.

    Args:
        conn: An open sqlite3.Connection.
        neuron_id_vector_pairs: List of (neuron_id, vector) tuples to write.

    Raises:
        ValueError: If any vector dimensions are not exactly 768.
        sqlite3.Error: If the database write fails (entire batch rolls back).
    """
    # --- Step 1: Validate all vectors before starting transaction ---
    # for neuron_id, vector in neuron_id_vector_pairs:
    #   validate_dimensions(vector)  # fail fast before any writes
    for _neuron_id, vector in neuron_id_vector_pairs:
        validate_dimensions(vector)

    # --- Step 2: Serialize all vectors ---
    # serialized = [(nid, serialize_vector(vec)) for nid, vec in neuron_id_vector_pairs]
    serialized = [(nid, serialize_vector(vec)) for nid, vec in neuron_id_vector_pairs]

    # --- Step 3: Single transaction for all writes ---
    # with conn:  # transaction context manager
    #   for neuron_id, blob in serialized:
    #     INSERT OR REPLACE INTO neurons_vec (rowid, embedding) VALUES (?, ?)
    #     UPDATE neurons SET embedding_updated_at = datetime('now') WHERE id = ?

    # --- Step 4: Transaction auto-commits on success, auto-rolls-back on error ---
    # Note: vec0 does not support INSERT OR REPLACE when a row already exists.
    # Use DELETE + INSERT pattern for upsert behavior.
    now_ms = int(time.time() * 1000)
    with conn:
        for neuron_id, blob in serialized:
            conn.execute("DELETE FROM neurons_vec WHERE neuron_id = ?", (neuron_id,))
            conn.execute(
                "INSERT INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
                (neuron_id, blob),
            )
            conn.execute(
                "UPDATE neurons SET embedding_updated_at = ? WHERE id = ?",
                (now_ms, neuron_id),
            )


def delete_vector(conn: sqlite3.Connection, neuron_id: int) -> None:
    """Delete the embedding vector for a neuron from vec0.

    Args:
        conn: An open sqlite3.Connection.
        neuron_id: The integer ID of the neuron whose vector to delete.
    """
    conn.execute("DELETE FROM neurons_vec WHERE neuron_id = ?", (neuron_id,))
