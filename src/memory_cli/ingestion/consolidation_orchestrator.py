# =============================================================================
# Module: consolidation_orchestrator.py
# Purpose: Orchestrate entity extraction consolidation on existing neurons.
#   Finds unconsolidated neurons, extracts entities/facts/relationships via
#   Haiku, creates sub-neurons with provenance metadata, wires edges with
#   confidence < 1.0, and marks parent neurons as consolidated.
# Rationale: Consolidation is a post-hoc enrichment pass that decomposes
#   existing knowledge blobs into structured sub-entities. This is separate
#   from ingestion (which processes raw JSONL sessions) because consolidation
#   operates on neurons already in the graph. The orchestrator must be
#   idempotent — re-running on already-consolidated neurons is a no-op.
# Responsibility:
#   - Find unconsolidated neurons (no consolidated_at attribute)
#   - For each: extract via Haiku, create sub-neurons, wire edges
#   - Set consolidated_at timestamp on parent after successful extraction
#   - Track results: neurons created, edges created, warnings
#   - Support single-neuron and batch modes
# Organization:
#   1. Imports
#   2. ConsolidationResult — summary dataclass
#   3. consolidate_neuron() — single neuron consolidation
#   4. consolidate_all() — batch consolidation of unconsolidated neurons
#   5. find_unconsolidated_neurons() — query for neurons needing consolidation
#   6. _create_sub_neurons_and_edges() — create sub-neurons + wire edges
#   7. _set_consolidated_timestamp() — mark parent as consolidated
# =============================================================================

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..registries import attr_autocreate
from ..neuron.neuron_add_with_autotags_and_embed import neuron_add
from ..edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError


# Confidence weight for extracted edges (< 1.0 per manifesto).
# Authored edges retain the default 1.0.
EXTRACTED_EDGE_WEIGHT = 0.85


@dataclass
class ConsolidationResult:
    """Summary of a consolidation pass.

    Attributes:
        neurons_processed: Number of parent neurons processed.
        neurons_skipped: Number already consolidated (idempotent skip).
        sub_neurons_created: Total sub-neurons created across all parents.
        edges_created: Total edges wired between parents and sub-neurons.
        warnings: Non-fatal warning messages.
        errors: Fatal errors per neuron (neuron_id -> error message).
    """

    neurons_processed: int = 0
    neurons_skipped: int = 0
    sub_neurons_created: int = 0
    edges_created: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: Dict[int, str] = field(default_factory=dict)


def consolidate_neuron(
    conn: sqlite3.Connection,
    neuron_id: int,
    force: bool = False,
) -> ConsolidationResult:
    """Consolidate a single neuron: extract entities/facts, create sub-neurons, wire edges.

    Logic flow:
    1. Fetch the neuron content and check if already consolidated
       - If consolidated and not force: return result with neurons_skipped=1
    2. Call Haiku extraction on neuron content
    3. Create sub-neurons for each extracted entity/fact
       - Attrs: extracted_by=haiku, extraction_method=consolidation,
         parent_neuron_id=<id>
       - Tags: "extracted", auto-tags
    4. Wire edges: parent -> sub-neuron with reason and weight < 1.0
    5. Set consolidated_at timestamp on parent neuron
    6. Return ConsolidationResult

    Args:
        conn: SQLite connection with full schema.
        neuron_id: ID of the neuron to consolidate.
        force: If True, re-consolidate even if already consolidated.

    Returns:
        ConsolidationResult with counts and any warnings/errors.
    """
    result = ConsolidationResult()

    # --- Fetch neuron ---
    row = conn.execute(
        "SELECT id, content FROM neurons WHERE id = ? AND status = 'active'",
        (neuron_id,),
    ).fetchone()
    if row is None:
        result.errors[neuron_id] = f"Neuron {neuron_id} not found or archived"
        return result

    content = row[1]

    # --- Check if already consolidated ---
    if not force and _is_consolidated(conn, neuron_id):
        result.neurons_skipped = 1
        return result

    # --- Extract via Haiku ---
    from .consolidation_extraction import consolidation_extract, ConsolidationError

    try:
        extraction = consolidation_extract(content)
    except ConsolidationError as e:
        result.errors[neuron_id] = str(e)
        return result

    # --- Skip if nothing extracted ---
    if not extraction.entities and not extraction.facts:
        # Still mark as consolidated (nothing to extract is a valid outcome)
        _set_consolidated_timestamp(conn, neuron_id)
        result.neurons_processed = 1
        return result

    # --- Create sub-neurons and edges ---
    sub_count, edge_count, warnings = _create_sub_neurons_and_edges(
        conn, neuron_id, extraction
    )
    result.sub_neurons_created = sub_count
    result.edges_created = edge_count
    result.warnings.extend(warnings)

    # --- Mark parent as consolidated ---
    _set_consolidated_timestamp(conn, neuron_id)
    result.neurons_processed = 1

    return result


def consolidate_all(
    conn: sqlite3.Connection,
    limit: Optional[int] = None,
) -> ConsolidationResult:
    """Consolidate all unconsolidated neurons in the database.

    Finds neurons without a consolidated_at attribute and runs
    consolidation on each. Accumulates results across all neurons.

    Args:
        conn: SQLite connection with full schema.
        limit: Optional max number of neurons to process.

    Returns:
        Aggregated ConsolidationResult.
    """
    result = ConsolidationResult()
    neuron_ids = find_unconsolidated_neurons(conn, limit=limit)

    for nid in neuron_ids:
        single = consolidate_neuron(conn, nid)
        result.neurons_processed += single.neurons_processed
        result.neurons_skipped += single.neurons_skipped
        result.sub_neurons_created += single.sub_neurons_created
        result.edges_created += single.edges_created
        result.warnings.extend(single.warnings)
        result.errors.update(single.errors)

    return result


def find_unconsolidated_neurons(
    conn: sqlite3.Connection,
    limit: Optional[int] = None,
) -> List[int]:
    """Find active neurons that have not been consolidated yet.

    A neuron is considered unconsolidated if it has no 'consolidated_at'
    attribute in the neuron_attrs table.

    Args:
        conn: SQLite connection.
        limit: Optional max number of neuron IDs to return.

    Returns:
        List of neuron IDs needing consolidation, ordered by created_at ASC.
    """
    query = """
        SELECT n.id
        FROM neurons n
        WHERE n.status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM neuron_attrs na
              JOIN attr_keys ak ON na.attr_key_id = ak.id
              WHERE na.neuron_id = n.id AND ak.name = 'consolidated_at'
          )
        ORDER BY n.created_at ASC
    """
    if limit is not None:
        query += f" LIMIT {int(limit)}"

    rows = conn.execute(query).fetchall()
    return [row[0] for row in rows]


def _is_consolidated(conn: sqlite3.Connection, neuron_id: int) -> bool:
    """Check if a neuron has already been consolidated.

    Args:
        conn: SQLite connection.
        neuron_id: Neuron ID to check.

    Returns:
        True if the neuron has a consolidated_at attribute.
    """
    row = conn.execute(
        """SELECT 1 FROM neuron_attrs na
           JOIN attr_keys ak ON na.attr_key_id = ak.id
           WHERE na.neuron_id = ? AND ak.name = 'consolidated_at'""",
        (neuron_id,),
    ).fetchone()
    return row is not None


def _create_sub_neurons_and_edges(
    conn: sqlite3.Connection,
    parent_id: int,
    extraction: Any,
) -> Tuple[int, int, List[str]]:
    """Create sub-neurons from extraction results and wire edges to parent.

    For each extracted entity/fact:
    1. Create a sub-neuron with provenance attributes
    2. Wire an edge from parent -> sub-neuron with weight < 1.0

    For each extracted relationship:
    3. Wire an edge between the relevant sub-neurons with weight < 1.0

    Args:
        conn: SQLite connection.
        parent_id: ID of the parent neuron being consolidated.
        extraction: ExtractionResult from Haiku.

    Returns:
        Tuple of (sub_neuron_count, edge_count, warnings).
    """
    import warnings as _warnings

    sub_count = 0
    edge_count = 0
    warn_list: List[str] = []
    local_id_to_neuron_id: Dict[str, int] = {}

    # --- Build provenance attrs ---
    provenance_attrs = {
        "extracted_by": "haiku",
        "extraction_method": "consolidation",
        "parent_neuron_id": str(parent_id),
    }

    # --- Create sub-neurons for entities ---
    for entity in extraction.entities:
        try:
            attrs = {
                **provenance_attrs,
                "ingest_role": "entity",
                "ingest_local_id": entity.local_id,
            }
            result = neuron_add(
                conn,
                entity.content,
                tags=["extracted"],
                attrs=attrs,
                no_embed=False,
            )
            nid = result["id"]
            local_id_to_neuron_id[entity.local_id] = nid
            sub_count += 1

            # Wire edge: parent -> sub-neuron
            try:
                edge_add(
                    conn, parent_id, nid,
                    reason=f"extracted_entity: {entity.content[:80]}",
                    weight=EXTRACTED_EDGE_WEIGHT,
                )
                edge_count += 1
            except EdgeAddError as e:
                warn_list.append(f"Edge parent->{nid} failed: {e}")

        except Exception as e:
            warn_list.append(
                f"Failed to create entity sub-neuron '{entity.local_id}': {e}"
            )

    # --- Create sub-neurons for facts ---
    for fact in extraction.facts:
        try:
            attrs = {
                **provenance_attrs,
                "ingest_role": "fact",
                "ingest_local_id": fact.local_id,
            }
            result = neuron_add(
                conn,
                fact.content,
                tags=["extracted"],
                attrs=attrs,
                no_embed=False,
            )
            nid = result["id"]
            local_id_to_neuron_id[fact.local_id] = nid
            sub_count += 1

            # Wire edge: parent -> sub-neuron
            try:
                edge_add(
                    conn, parent_id, nid,
                    reason=f"extracted_fact: {fact.content[:80]}",
                    weight=EXTRACTED_EDGE_WEIGHT,
                )
                edge_count += 1
            except EdgeAddError as e:
                warn_list.append(f"Edge parent->{nid} failed: {e}")

        except Exception as e:
            warn_list.append(
                f"Failed to create fact sub-neuron '{fact.local_id}': {e}"
            )

    # --- Wire edges for extracted relationships ---
    for rel in extraction.relationships:
        source_id = local_id_to_neuron_id.get(rel.from_id)
        target_id = local_id_to_neuron_id.get(rel.to_id)
        if source_id is None:
            warn_list.append(
                f"Unresolvable from_id '{rel.from_id}' in relationship"
            )
            continue
        if target_id is None:
            warn_list.append(
                f"Unresolvable to_id '{rel.to_id}' in relationship"
            )
            continue
        try:
            edge_add(
                conn, source_id, target_id,
                reason=rel.reason,
                weight=EXTRACTED_EDGE_WEIGHT,
            )
            edge_count += 1
        except EdgeAddError as e:
            warn_list.append(
                f"Edge {rel.from_id}->{rel.to_id} failed: {e}"
            )

    return (sub_count, edge_count, warn_list)


def _set_consolidated_timestamp(conn: sqlite3.Connection, neuron_id: int) -> None:
    """Set the consolidated_at attribute on a neuron.

    Uses ISO 8601 format timestamp in UTC.

    Args:
        conn: SQLite connection.
        neuron_id: Neuron ID to mark as consolidated.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    attr_key_id = attr_autocreate(conn, "consolidated_at")
    # Upsert: if already exists (force mode), update the value
    conn.execute(
        """INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value)
           VALUES (?, ?, ?)""",
        (neuron_id, attr_key_id, timestamp),
    )
    conn.commit()
