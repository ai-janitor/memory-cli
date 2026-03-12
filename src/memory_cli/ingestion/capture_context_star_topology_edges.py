# =============================================================================
# Module: capture_context_star_topology_edges.py
# Purpose: Create a central "session context" neuron and star-topology edges
#   linking it to every neuron created during a single ingestion run.
#   Implements Finding S-6 resolution — context capture via star topology.
# Rationale: Neurons extracted from the same session share conversational
#   context that isn't captured by entity/fact relationships alone. A star
#   topology (one central context neuron linked to all session neurons)
#   preserves the "co-occurred in the same session" signal. This aids
#   spreading activation search — activating any session neuron can spread
#   to siblings via the context hub. Weight 0.5 reflects moderate (not
#   dominant) contextual relevance.
# Responsibility:
#   - Create one session context neuron per ingestion run
#   - Create edges from context neuron to each created neuron
#   - Set edge weight to 0.5 and reason to "co-occurred in session <id>"
#   - Return context neuron ID and edge count
# Organization:
#   1. Imports
#   2. Constants (default edge weight, context neuron content template)
#   3. capture_context_star() — main entry point
#   4. _create_context_neuron() — create the central hub neuron
#   5. _create_star_edges() — create edges from hub to all session neurons
# =============================================================================

from __future__ import annotations

import sqlite3
from typing import List, Optional, Tuple

from ..neuron.neuron_add_with_autotags_and_embed import neuron_add
from ..edge.edge_add_with_reason_and_weight import edge_add


# -----------------------------------------------------------------------------
# Constants — star topology configuration.
# -----------------------------------------------------------------------------
CONTEXT_EDGE_WEIGHT = 0.5
CONTEXT_NEURON_CONTENT_TEMPLATE = "Session context: {session_id}"
CONTEXT_EDGE_REASON_TEMPLATE = "co-occurred in session {session_id}"


def capture_context_star(
    conn: sqlite3.Connection,
    session_id: str,
    neuron_ids: List[int],
    project: Optional[str] = None,
) -> Tuple[int, int]:
    """Create a session context neuron and star edges to all session neurons.

    This is the final stage of the ingestion pipeline. The context neuron
    acts as a hub node — its content describes the session, and it links
    to every neuron created from that session.

    Logic flow:
    1. If neuron_ids is empty: return (0, 0) — nothing to link
    2. Create context neuron via _create_context_neuron(conn, session_id, project)
       - Content: "Session context: <session_id>"
       - Tags: ["ingested", "session-context"]
       - Attrs: {"ingested_session_id": session_id, "context_type": "session_hub"}
    3. Create star edges via _create_star_edges(conn, ctx_id, neuron_ids, session_id)
       - One edge per neuron_id, all from ctx_id
       - Weight: 0.5, Reason: "co-occurred in session <session_id>"
    4. Return (context_neuron_id, edge_count)

    Args:
        conn: SQLite connection with full schema.
        session_id: Session identifier for content and edge reasons.
        neuron_ids: List of neuron IDs created during this ingestion.
        project: Optional project name for context neuron tagging.

    Returns:
        Tuple of (context_neuron_id, number_of_star_edges_created).
    """
    # --- Guard: nothing to link ---
    # if not neuron_ids:
    #     return (0, 0)
    if not neuron_ids:
        return (0, 0)

    # --- Create context hub neuron ---
    # ctx_id = _create_context_neuron(conn, session_id, project)
    ctx_id = _create_context_neuron(conn, session_id, project)

    # --- Create star edges ---
    # edge_count = _create_star_edges(conn, ctx_id, neuron_ids, session_id)
    edge_count = _create_star_edges(conn, ctx_id, neuron_ids, session_id)

    # return (ctx_id, edge_count)
    return (ctx_id, edge_count)


def _create_context_neuron(
    conn: sqlite3.Connection,
    session_id: str,
    project: Optional[str] = None,
) -> int:
    """Create the central session context neuron.

    This neuron's content describes the session. It's tagged as a
    session-context node so it can be filtered in search results
    (users typically want the leaf neurons, not the hub).

    Logic flow:
    1. Format content from CONTEXT_NEURON_CONTENT_TEMPLATE
    2. Build tags: ["ingested", "session-context"]
       - Add "project:<name>" if project is provided
    3. Build attrs: {"ingested_session_id": session_id, "context_type": "session_hub"}
    4. Call neuron_add(conn, content, tags=tags, attrs=attrs, no_embed=True)
       - no_embed=True: context neuron content is not semantically useful for search
    5. Return neuron ID

    Args:
        conn: SQLite connection.
        session_id: Session ID for content and attribution.
        project: Optional project name.

    Returns:
        ID of the created context neuron.
    """
    # --- Build neuron parameters ---
    # content = CONTEXT_NEURON_CONTENT_TEMPLATE.format(session_id=session_id)
    # tags = ["ingested", "session-context"]
    # if project:
    #     tags.append(f"project:{project}")
    # attrs = {"ingested_session_id": session_id, "context_type": "session_hub"}
    content = CONTEXT_NEURON_CONTENT_TEMPLATE.format(session_id=session_id)
    tags = ["ingested", "session-context"]
    if project:
        tags.append(f"project:{project}")
    attrs = {"ingested_session_id": session_id, "context_type": "session_hub"}

    # --- Create neuron ---
    # result = neuron_add(conn, content, tags=tags, attrs=attrs, no_embed=True)
    # return result["id"]
    result = neuron_add(conn, content, tags=tags, attrs=attrs, no_embed=True)
    return result["id"]


def _create_star_edges(
    conn: sqlite3.Connection,
    context_neuron_id: int,
    neuron_ids: List[int],
    session_id: str,
) -> int:
    """Create edges from the context hub neuron to each session neuron.

    Each edge has weight 0.5 and a reason indicating session co-occurrence.
    Individual edge failures are logged as warnings but don't abort the batch.

    Logic flow:
    1. Format reason from CONTEXT_EDGE_REASON_TEMPLATE
    2. For each neuron_id in neuron_ids:
       a. Call edge_add(conn, context_neuron_id, neuron_id,
                        reason=reason, weight=CONTEXT_EDGE_WEIGHT)
       b. On success: increment count
       c. On failure: log warning, continue (don't abort batch)
    3. Return count of edges created

    Args:
        conn: SQLite connection.
        context_neuron_id: ID of the hub neuron.
        neuron_ids: IDs of leaf neurons to link to.
        session_id: Session ID for edge reason text.

    Returns:
        Number of star edges successfully created.
    """
    # --- Create edges in loop ---
    # reason = CONTEXT_EDGE_REASON_TEMPLATE.format(session_id=session_id)
    # count = 0
    # for nid in neuron_ids:
    #     try:
    #         from ..edge.edge_add_with_validation import edge_add
    #         edge_add(conn, context_neuron_id, nid, reason=reason, weight=CONTEXT_EDGE_WEIGHT)
    #         count += 1
    #     except Exception as e:
    #         import logging
    #         logging.warning(f"Star edge to neuron {nid} failed: {e}")
    reason = CONTEXT_EDGE_REASON_TEMPLATE.format(session_id=session_id)
    count = 0
    for nid in neuron_ids:
        try:
            edge_add(conn, context_neuron_id, nid, reason=reason, weight=CONTEXT_EDGE_WEIGHT)
            count += 1
        except Exception as e:
            import logging
            logging.warning(f"Star edge to neuron {nid} failed: {e}")

    # return count
    return count
