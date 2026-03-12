# =============================================================================
# Module: session_dedup_guard_by_session_id.py
# Purpose: Prevent double-ingestion of the same Claude Code session by
#   checking for existing neurons with a matching ingested_session_id
#   attribute. Implements Finding S-7 resolution.
# Rationale: Users may re-run `memory batch ingest` on the same file
#   accidentally, or a pipeline may retry after partial failure. Without
#   dedup, the graph accumulates duplicate neurons and edges. Checking the
#   ingested_session_id attribute is cheap (indexed lookup) and catches
#   exact duplicates. The --force flag provides an explicit override for
#   intentional re-ingestion.
# Responsibility:
#   - Query neurons by ingested_session_id attribute
#   - Return True/False for "already ingested"
#   - Provide count of existing neurons for user-facing warning
# Organization:
#   1. Imports
#   2. DedupCheckResult — dataclass for check result
#   3. check_session_already_ingested() — main entry point
#   4. _query_existing_session_neurons() — DB lookup helper
# =============================================================================

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class DedupCheckResult:
    """Result of a session dedup check.

    Attributes:
        already_ingested: True if neurons with this session_id exist.
        existing_neuron_count: Number of neurons found (0 if not ingested).
        session_id: The session ID that was checked.
    """

    already_ingested: bool
    existing_neuron_count: int
    session_id: str


def check_session_already_ingested(
    conn: sqlite3.Connection,
    session_id: str,
) -> DedupCheckResult:
    """Check if a session has already been ingested into the graph.

    Queries the neuron_attrs table for neurons that have an
    "ingested_session_id" attribute matching the given session_id.

    Logic flow:
    1. Call _query_existing_session_neurons(conn, session_id)
    2. If count > 0: return DedupCheckResult(already_ingested=True, count, session_id)
    3. If count == 0: return DedupCheckResult(already_ingested=False, 0, session_id)

    This function does NOT enforce the guard — the orchestrator decides
    whether to proceed based on the result and the --force flag.

    Args:
        conn: SQLite connection with neuron schema.
        session_id: The session ID to check for.

    Returns:
        DedupCheckResult indicating whether the session was already ingested.
    """
    # --- Query for existing session neurons ---
    # count = _query_existing_session_neurons(conn, session_id)
    count = _query_existing_session_neurons(conn, session_id)

    # --- Return result ---
    # return DedupCheckResult(
    #     already_ingested=(count > 0),
    #     existing_neuron_count=count,
    #     session_id=session_id,
    # )
    return DedupCheckResult(
        already_ingested=(count > 0),
        existing_neuron_count=count,
        session_id=session_id,
    )


def _query_existing_session_neurons(
    conn: sqlite3.Connection,
    session_id: str,
) -> int:
    """Query the count of neurons with matching ingested_session_id.

    Uses a JOIN between neurons, neuron_attrs, and attr_keys to find
    neurons where the "ingested_session_id" attribute matches.

    SQL logic:
    SELECT COUNT(DISTINCT n.id)
    FROM neurons n
    JOIN neuron_attrs na ON n.id = na.neuron_id
    JOIN attr_keys ak ON na.attr_key_id = ak.id
    WHERE ak.name = 'ingested_session_id'
      AND na.value = ?
      AND n.status = 'active'

    Only counts active neurons — archived neurons don't block re-ingestion.

    Args:
        conn: SQLite connection.
        session_id: The session ID value to match.

    Returns:
        Count of matching active neurons.
    """
    # --- Execute count query ---
    # cursor = conn.execute(
    #     """
    #     SELECT COUNT(DISTINCT n.id)
    #     FROM neurons n
    #     JOIN neuron_attrs na ON n.id = na.neuron_id
    #     JOIN attr_keys ak ON na.attr_key_id = ak.id
    #     WHERE ak.name = 'ingested_session_id'
    #       AND na.value = ?
    #       AND n.status = 'active'
    #     """,
    #     (session_id,),
    # )
    # return cursor.fetchone()[0]
    cursor = conn.execute(
        """
        SELECT COUNT(DISTINCT n.id)
        FROM neurons n
        JOIN neuron_attrs na ON n.id = na.neuron_id
        JOIN attr_keys ak ON na.attr_key_id = ak.id
        WHERE ak.name = 'ingested_session_id'
          AND na.value = ?
          AND n.status = 'active'
        """,
        (session_id,),
    )
    return cursor.fetchone()[0]
