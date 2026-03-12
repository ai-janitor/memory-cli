# =============================================================================
# Module: neuron_and_edge_creator_from_extraction.py
# Purpose: Map Haiku extraction results (entities, facts, relationships) into
#   memory graph primitives — neurons for entities/facts, edges for
#   relationships. Handles local ID resolution and creation metadata.
# Rationale: The extraction stage produces abstract items with local IDs.
#   This module bridges the gap between Haiku's output format and the
#   neuron/edge CRUD layer. It resolves local IDs to actual neuron IDs
#   after creation, and gracefully handles unresolvable references (Haiku
#   may reference IDs that don't appear in entities/facts, or creation
#   of a referenced neuron may have failed).
# Responsibility:
#   - Create one neuron per entity and one per fact
#   - Apply ingestion metadata as attributes (source, project, session_id, role)
#   - Apply tags ("ingested", project:<name>, user-provided tags)
#   - Build local-ID-to-neuron-ID mapping as neurons are created
#   - Create edges from relationships using the ID mapping
#   - Skip unresolvable references with warnings
#   - Return creation summary with counts and warnings
# Organization:
#   1. Imports
#   2. CreationResult — dataclass for creation summary
#   3. create_neurons_and_edges() — main entry point
#   4. _create_neuron_from_item() — create a single neuron with metadata
#   5. _create_edges_from_relationships() — resolve IDs and create edges
#   6. _build_ingestion_attrs() — build standard attribute dict
#   7. _build_ingestion_tags() — build standard tag list
# =============================================================================

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# TYPE_CHECKING avoids circular imports at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .haiku_extraction_entities_facts_rels import (
        ExtractedEntity,
        ExtractedFact,
        ExtractedRelationship,
        ExtractionResult,
    )


@dataclass
class CreationResult:
    """Summary of neuron and edge creation from an extraction.

    Tracks what was created, what failed, and the mapping from
    Haiku local IDs to actual neuron IDs.

    Attributes:
        neuron_count: Number of neurons successfully created.
        edge_count: Number of edges successfully created.
        neuron_ids: List of all created neuron IDs.
        local_id_to_neuron_id: Mapping from Haiku local IDs to neuron IDs.
        warnings: List of non-fatal warning messages.
    """

    neuron_count: int = 0
    edge_count: int = 0
    neuron_ids: List[int] = field(default_factory=list)
    local_id_to_neuron_id: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def create_neurons_and_edges(
    conn: sqlite3.Connection,
    extraction: "ExtractionResult",
    source: str,
    project: Optional[str],
    tags: Optional[List[str]],
    session_id: str,
) -> CreationResult:
    """Create neurons and edges from a Haiku extraction result.

    Two-pass process: first create all neurons (building the ID map),
    then create all edges (resolving IDs from the map).

    Logic flow:
    1. Initialize CreationResult
    2. Build standard ingestion tags via _build_ingestion_tags(project, tags)
    3. Build standard ingestion attrs via _build_ingestion_attrs(source, project, session_id)

    4. Pass 1 — Create neurons:
       a. For each entity in extraction.entities:
          - Create neuron with role="entity" in attrs
          - On success: add to local_id_to_neuron_id mapping
          - On failure: append warning, continue
       b. For each fact in extraction.facts:
          - Create neuron with role="fact" in attrs
          - On success: add to local_id_to_neuron_id mapping
          - On failure: append warning, continue

    5. Pass 2 — Create edges:
       - Call _create_edges_from_relationships(
             conn, extraction.relationships, result.local_id_to_neuron_id
         )
       - Collect edge count and warnings

    6. Return CreationResult

    Error semantics:
    - Individual neuron creation failure -> warning, skip that neuron
    - Individual edge creation failure -> warning, skip that edge
    - All failures are non-fatal at this level (orchestrator decides severity)

    Args:
        conn: SQLite connection with full schema.
        extraction: ExtractionResult from Haiku.
        source: Source identifier (JSONL file path).
        project: Project name for tagging and attributes.
        tags: Additional user-provided tags.
        session_id: Session ID for dedup and attribution.

    Returns:
        CreationResult with counts, ID mapping, and warnings.
    """
    # --- Initialize result and build metadata ---
    # result = CreationResult()
    # ingestion_tags = _build_ingestion_tags(project, tags)
    # ingestion_attrs = _build_ingestion_attrs(source, project, session_id)

    # --- Pass 1: Create neurons for entities ---
    # for entity in extraction.entities:
    #     try:
    #         neuron_id = _create_neuron_from_item(
    #             conn, entity.content, "entity",
    #             ingestion_tags, ingestion_attrs, entity.local_id
    #         )
    #         result.local_id_to_neuron_id[entity.local_id] = neuron_id
    #         result.neuron_ids.append(neuron_id)
    #         result.neuron_count += 1
    #     except Exception as e:
    #         result.warnings.append(f"Failed to create entity neuron '{entity.local_id}': {e}")

    # --- Pass 1 continued: Create neurons for facts ---
    # for fact in extraction.facts:
    #     try:
    #         neuron_id = _create_neuron_from_item(
    #             conn, fact.content, "fact",
    #             ingestion_tags, ingestion_attrs, fact.local_id
    #         )
    #         result.local_id_to_neuron_id[fact.local_id] = neuron_id
    #         result.neuron_ids.append(neuron_id)
    #         result.neuron_count += 1
    #     except Exception as e:
    #         result.warnings.append(f"Failed to create fact neuron '{fact.local_id}': {e}")

    # --- Pass 2: Create edges from relationships ---
    # edge_count, edge_warnings = _create_edges_from_relationships(
    #     conn, extraction.relationships, result.local_id_to_neuron_id
    # )
    # result.edge_count = edge_count
    # result.warnings.extend(edge_warnings)

    # return result

    pass


def _create_neuron_from_item(
    conn: sqlite3.Connection,
    content: str,
    ingest_role: str,
    tags: List[str],
    base_attrs: Dict[str, str],
    local_id: str,
) -> int:
    """Create a single neuron from an extracted entity or fact.

    Delegates to neuron_add() from the neuron package, with ingestion-specific
    metadata added to attributes.

    Logic flow:
    1. Build attrs dict by copying base_attrs and adding:
       - "ingest_role" -> ingest_role ("entity" or "fact")
       - "ingest_local_id" -> local_id (for traceability)
    2. Call neuron_add(conn, content, tags=tags, attrs=attrs, source=attrs["source"])
       - Embedding happens inside neuron_add (unless no_embed is set)
    3. Return the created neuron's ID

    Args:
        conn: SQLite connection.
        content: Neuron content text.
        ingest_role: "entity" or "fact".
        tags: List of tags to apply.
        base_attrs: Standard ingestion attributes.
        local_id: Haiku-assigned local ID for this item.

    Returns:
        The created neuron's ID.

    Raises:
        Any exception from neuron_add — caller handles.
    """
    # --- Build full attrs ---
    # attrs = {**base_attrs, "ingest_role": ingest_role, "ingest_local_id": local_id}

    # --- Create neuron via neuron_add ---
    # from ..neuron.neuron_add_with_autotags_and_embed import neuron_add
    # result = neuron_add(conn, content, tags=tags, attrs=attrs, source=attrs.get("source"))
    # return result["id"]

    pass


def _create_edges_from_relationships(
    conn: sqlite3.Connection,
    relationships: List["ExtractedRelationship"],
    id_map: Dict[str, int],
) -> Tuple[int, List[str]]:
    """Create edges from extracted relationships, resolving local IDs.

    Logic flow:
    1. For each relationship:
       a. Look up from_id in id_map -> source_neuron_id
       b. Look up to_id in id_map -> target_neuron_id
       c. If either is missing: append warning, skip this relationship
       d. Call edge_add(conn, source_neuron_id, target_neuron_id, relationship.reason)
       e. On success: increment edge_count
       f. On failure: append warning
    2. Return (edge_count, warnings)

    Args:
        conn: SQLite connection.
        relationships: List of extracted relationships with local IDs.
        id_map: Mapping from Haiku local IDs to actual neuron IDs.

    Returns:
        Tuple of (edge_count, list of warning strings).
    """
    # --- Resolve and create edges ---
    # edge_count = 0
    # warnings = []
    # for rel in relationships:
    #     source_id = id_map.get(rel.from_id)
    #     target_id = id_map.get(rel.to_id)
    #     if source_id is None:
    #         warnings.append(f"Unresolvable from_id '{rel.from_id}' in relationship")
    #         continue
    #     if target_id is None:
    #         warnings.append(f"Unresolvable to_id '{rel.to_id}' in relationship")
    #         continue
    #     try:
    #         from ..edge.edge_add_with_validation import edge_add
    #         edge_add(conn, source_id, target_id, rel.reason)
    #         edge_count += 1
    #     except Exception as e:
    #         warnings.append(f"Failed to create edge {rel.from_id}->{rel.to_id}: {e}")

    # return (edge_count, warnings)

    pass


def _build_ingestion_tags(
    project: Optional[str],
    user_tags: Optional[List[str]],
) -> List[str]:
    """Build the standard tag list for ingested neurons.

    All ingested neurons get:
    - "ingested" tag (always)
    - "project:<name>" tag (if project is provided)
    - Any user-provided tags from --tags

    Args:
        project: Optional project name.
        user_tags: Optional list of additional tags from --tags flag.

    Returns:
        Deduplicated list of tag strings.
    """
    # --- Build tag list ---
    # tags = ["ingested"]
    # if project:
    #     tags.append(f"project:{project}")
    # if user_tags:
    #     tags.extend(user_tags)
    # return list(dict.fromkeys(tags))  # deduplicate preserving order

    pass


def _build_ingestion_attrs(
    source: str,
    project: Optional[str],
    session_id: str,
) -> Dict[str, str]:
    """Build the standard attribute dict for ingested neurons.

    All ingested neurons get these attributes for traceability:
    - "source" -> file path of the JSONL file
    - "project" -> project name (if provided)
    - "ingested_session_id" -> session ID for dedup
    - "source_timestamp" -> will be filled per-neuron from earliest message

    Args:
        source: JSONL file path string.
        project: Optional project name.
        session_id: Session ID from the JSONL file.

    Returns:
        Dict of attribute key-value pairs.
    """
    # --- Build attrs dict ---
    # attrs = {
    #     "source": source,
    #     "ingested_session_id": session_id,
    # }
    # if project:
    #     attrs["project"] = project
    # return attrs

    pass
