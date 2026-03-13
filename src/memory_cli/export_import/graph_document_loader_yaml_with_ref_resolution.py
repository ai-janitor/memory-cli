# =============================================================================
# Module: graph_document_loader_yaml_with_ref_resolution.py
# Purpose: Load a human-authored graph document (YAML) that defines neurons
#   and edges together using local ref labels. Resolves refs to real neuron IDs
#   at import time — one file, one command, entire graph created.
# Rationale: Building a knowledge graph via 12+ individual CLI calls is painful.
#   A graph document format lets humans/agents define neurons with local labels
#   (refs) and edges that reference those labels. The loader creates neurons
#   first (collecting real IDs), then wires edges using the resolved ID map.
# Responsibility:
#   - Parse YAML graph document
#   - Validate structure: neurons with ref/content, edges with from/to
#   - Create neurons via neuron_add (reuses existing pipeline)
#   - Build ref→ID map from created neurons
#   - Create edges via edge_add using resolved IDs
#   - Return summary of what was created
# Organization:
#   1. Imports and constants
#   2. GraphDocumentResult dataclass
#   3. load_graph_document() — main entry point
#   4. _validate_graph_document() — structural validation
#   5. _create_neurons_and_collect_ids() — phase 1: neurons
#   6. _create_edges_from_refs() — phase 2: edges
# =============================================================================

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _is_scoped_handle(val: str) -> bool:
    """Check if a string looks like a scoped handle (LOCAL-42, GLOBAL-42, L-42, G-42).

    Does not validate DB existence — that happens at edge creation time.
    """
    from memory_cli.cli.scoped_handle_format_and_parse import parse_handle
    try:
        scope, _ = parse_handle(val)
        return scope is not None  # bare integers are not scoped handles
    except ValueError:
        return False


@dataclass
class GraphDocumentResult:
    """Summary of what the graph document loader created.

    Attributes:
        success: True if load completed without error.
        neurons_created: Count of neurons inserted.
        neurons_reused: Count of neurons matched to existing (dedup).
        edges_created: Count of edges inserted.
        ref_map: Mapping of ref labels to real neuron IDs.
        errors: List of error messages if any.
    """
    success: bool = False
    neurons_created: int = 0
    neurons_reused: int = 0
    edges_created: int = 0
    ref_map: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def load_graph_document(
    conn: sqlite3.Connection,
    file_path: str,
    source: Optional[str] = None,
    yaml_content: Optional[str] = None,
) -> GraphDocumentResult:
    """Load a YAML graph document, creating neurons and edges.

    Args:
        conn: Active SQLite connection to the memory database.
        file_path: Path to the YAML graph document (ignored if yaml_content provided).
        source: Optional source tag for all created neurons.
        yaml_content: If provided, parse this YAML string directly instead of
            reading from file_path. Enables stdin and --inline modes.

    Returns:
        GraphDocumentResult with counts and ref→ID map.

    Expected YAML format:
        neurons:
          - ref: interview
            content: "Interview details..."
            tags: [leidos, interview]
            type: event
            source: interview-prep
          - ref: payam
            content: "Payam Fard..."
            tags: [leidos, contact]
            type: person

        edges:
          - from: interview
            to: payam
            type: has_interviewer
            weight: 1.0

    Logic flow:
    1. Read and parse YAML (from yaml_content string or file_path)
    2. Validate document structure
    3. Phase 1: Create neurons, build ref→ID map
    4. Phase 2: Create edges using resolved refs
    5. Return result
    """
    import yaml

    result = GraphDocumentResult()

    # 1. Read and parse YAML — from string if provided, otherwise from file
    if yaml_content is not None:
        try:
            doc = yaml.safe_load(yaml_content)
        except Exception as e:
            result.errors.append(f"YAML parse error: {e}")
            return result
    else:
        path = Path(file_path)
        if not path.exists():
            result.errors.append(f"File not found: {file_path}")
            return result

        try:
            raw = path.read_text(encoding="utf-8")
            doc = yaml.safe_load(raw)
        except Exception as e:
            result.errors.append(f"YAML parse error: {e}")
            return result

    if not isinstance(doc, dict):
        result.errors.append(f"Document root must be a mapping, got {type(doc).__name__}")
        return result

    # 2. Validate document structure
    validation_errors = _validate_graph_document(doc)
    if validation_errors:
        result.errors.extend(validation_errors)
        return result

    neurons_spec = doc.get("neurons", [])
    edges_spec = doc.get("edges", [])

    # 3. Phase 1: Create neurons, build ref→ID map
    ref_map, neurons_created, neurons_reused, neuron_errors = _create_neurons_and_collect_ids(
        conn, neurons_spec, source_override=source,
    )
    result.ref_map = ref_map
    result.neurons_created = neurons_created
    result.neurons_reused = neurons_reused
    if neuron_errors:
        result.errors.extend(neuron_errors)
        return result

    # 4. Phase 2: Create edges using resolved refs
    edges_created, edge_errors = _create_edges_from_refs(conn, edges_spec, ref_map)
    result.edges_created = edges_created
    if edge_errors:
        result.errors.extend(edge_errors)
        return result

    # 5. Commit — edge_add inserts but does not commit
    conn.commit()

    result.success = True
    return result


def _validate_graph_document(doc: Dict[str, Any]) -> List[str]:
    """Validate the structure of a graph document.

    Checks:
    - neurons key exists and is a list
    - Each neuron has ref (str) and content (str)
    - ref labels are unique
    - edges key (if present) is a list
    - Each edge has from (str) and to (str)
    - Edge from/to refs exist in the neurons list, or are external refs
      (integer neuron IDs for cross-file references)

    Returns:
        List of error strings (empty if valid).
    """
    errors: List[str] = []

    # Neurons validation
    neurons = doc.get("neurons")
    if neurons is None:
        errors.append("Missing 'neurons' key")
        return errors
    if not isinstance(neurons, list):
        errors.append(f"'neurons' must be a list, got {type(neurons).__name__}")
        return errors

    refs_seen: set = set()
    for i, neuron in enumerate(neurons):
        if not isinstance(neuron, dict):
            errors.append(f"neurons[{i}]: must be a mapping, got {type(neuron).__name__}")
            continue
        ref = neuron.get("ref")
        if ref is None:
            errors.append(f"neurons[{i}]: missing 'ref' field")
        elif not isinstance(ref, str):
            errors.append(f"neurons[{i}]: 'ref' must be a string, got {type(ref).__name__}")
        elif ref in refs_seen:
            errors.append(f"neurons[{i}]: duplicate ref '{ref}'")
        else:
            refs_seen.add(ref)

        content = neuron.get("content")
        if content is None:
            errors.append(f"neurons[{i}]: missing 'content' field")
        elif not isinstance(content, str) or not content.strip():
            errors.append(f"neurons[{i}]: 'content' must be a non-empty string")

    # Edges validation (optional section)
    # Edge from/to can be:
    #   - A local ref label (string matching a neuron in this file)
    #   - An integer neuron ID (cross-file reference to existing DB neuron)
    #   - A scoped handle (LOCAL-42, GLOBAL-42, L-42, G-42) — validated at create time
    edges = doc.get("edges")
    if edges is not None:
        if not isinstance(edges, list):
            errors.append(f"'edges' must be a list, got {type(edges).__name__}")
        else:
            for i, edge in enumerate(edges):
                if not isinstance(edge, dict):
                    errors.append(f"edges[{i}]: must be a mapping")
                    continue
                for field_name in ("from", "to"):
                    val = edge.get(field_name)
                    if val is None:
                        errors.append(f"edges[{i}]: missing '{field_name}' field")
                    elif isinstance(val, int):
                        pass  # external neuron ID — validated at create time
                    elif not isinstance(val, str):
                        errors.append(f"edges[{i}]: '{field_name}' must be a string or integer")
                    elif val not in refs_seen and not _is_scoped_handle(val):
                        errors.append(f"edges[{i}]: '{field_name}' ref '{val}' not found in neurons")

    return errors


def _create_neurons_and_collect_ids(
    conn: sqlite3.Connection,
    neurons_spec: List[Dict[str, Any]],
    source_override: Optional[str] = None,
) -> tuple:
    """Create neurons from spec and return ref→ID map.

    Args:
        conn: Active SQLite connection.
        neurons_spec: List of neuron dicts from the YAML document.
        source_override: If provided, overrides per-neuron source.

    Returns:
        Tuple of (ref_map dict, error list).

    Logic flow:
    1. For each neuron spec:
       a. Extract ref, content, tags, type, source
       b. Call neuron_add() to create the neuron
       c. Map ref → returned neuron ID
    2. Return (ref_map, errors)
    """
    from memory_cli.neuron import neuron_add

    ref_map: Dict[str, int] = {}
    errors: List[str] = []
    created = 0
    reused = 0

    for i, spec in enumerate(neurons_spec):
        ref = spec["ref"]
        content = spec["content"]
        raw_tags = spec.get("tags")
        tags = [str(t).strip() for t in raw_tags] if raw_tags else None
        source = source_override or spec.get("source")
        ntype = spec.get("type")
        attrs = {"type": ntype} if ntype else None

        try:
            # Dedup: if a neuron with same source + content exists, reuse it
            existing = _find_existing_neuron(conn, content, source)
            if existing is not None:
                ref_map[ref] = existing
                reused += 1
                continue

            result = neuron_add(
                conn, content, tags=tags, source=source, attrs=attrs, no_embed=True,
            )
            neuron_id = result["id"]
            ref_map[ref] = neuron_id
            created += 1
        except Exception as e:
            errors.append(f"neurons[{i}] ref='{ref}': failed to create — {e}")

    return ref_map, created, reused, errors


def _find_existing_neuron(
    conn: sqlite3.Connection,
    content: str,
    source: Optional[str],
) -> Optional[int]:
    """Check if a neuron with the same content and source already exists.

    Returns:
        Neuron ID if found, None otherwise.
    """
    if source:
        row = conn.execute(
            "SELECT id FROM neurons WHERE content = ? AND source = ? AND status = 'active' LIMIT 1",
            (content, source),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM neurons WHERE content = ? AND status = 'active' LIMIT 1",
            (content,),
        ).fetchone()
    return row[0] if row else None


def _resolve_ref(ref: Any, ref_map: Dict[str, int]) -> Optional[int]:
    """Resolve an edge ref to an integer neuron ID.

    Resolution order:
    1. Integer — direct neuron ID
    2. String in ref_map — local YAML ref label
    3. Scoped handle (LOCAL-42, GLOBAL-42) — parse to extract integer ID
    4. None — unresolvable
    """
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str):
        if ref in ref_map:
            return ref_map[ref]
        # Try scoped handle parse
        from memory_cli.cli.scoped_handle_format_and_parse import parse_handle
        try:
            scope, nid = parse_handle(ref)
            if scope is not None:
                return nid
        except ValueError:
            pass
    return None


def _create_edges_from_refs(
    conn: sqlite3.Connection,
    edges_spec: List[Dict[str, Any]],
    ref_map: Dict[str, int],
) -> tuple:
    """Create edges using resolved ref→ID mappings.

    Args:
        conn: Active SQLite connection.
        edges_spec: List of edge dicts from the YAML document.
        ref_map: Mapping of ref labels to real neuron IDs.

    Returns:
        Tuple of (edges_created count, error list).

    Logic flow:
    1. For each edge spec:
       a. Resolve from/to refs to real IDs via ref_map
       b. Extract type (reason) and weight
       c. Call edge_add() to create the edge
    2. Return (count, errors)
    """
    from memory_cli.edge import edge_add

    created = 0
    errors: List[str] = []

    for i, spec in enumerate(edges_spec):
        from_ref = spec["from"]
        to_ref = spec["to"]
        reason = spec.get("type", spec.get("reason", "related"))
        weight = spec.get("weight")

        # Resolve refs: integer = direct neuron ID, string = local ref label or scoped handle
        source_id = _resolve_ref(from_ref, ref_map)
        target_id = _resolve_ref(to_ref, ref_map)

        if source_id is None:
            errors.append(f"edges[{i}]: from ref '{from_ref}' has no resolved ID")
            continue
        if target_id is None:
            errors.append(f"edges[{i}]: to ref '{to_ref}' has no resolved ID")
            continue

        try:
            edge_add(conn, source_id, target_id, reason, weight=weight)
            created += 1
        except Exception as e:
            errors.append(f"edges[{i}] {from_ref}→{to_ref}: failed — {e}")

    return created, errors
