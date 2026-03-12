# =============================================================================
# Module: export_envelope_format_v1.py
# Purpose: Build the versioned export envelope JSON structure that wraps
#   exported neurons and edges. The envelope provides metadata for validation
#   on import: version info, counts, vector config, and timestamps.
# Rationale: A versioned envelope enables forward-compatible imports — future
#   versions can read v1 exports even if the format evolves. Count fields
#   (neuron_count, edge_count) enable integrity checks without parsing the
#   full arrays. Vector metadata (model, dimensions) enables dimension
#   mismatch detection before attempting to write vectors.
# Responsibility:
#   - Accept export data (neurons list, edges list, metadata)
#   - Build the complete envelope dict with all required metadata fields
#   - Serialize to JSON string with deterministic formatting
#   - Provide the current format version constant
# Organization:
#   1. Imports and constants
#   2. EXPORT_FORMAT_VERSION — current format version string
#   3. build_export_envelope() — main entry point
#   4. _build_metadata_header() — envelope metadata fields
#   5. serialize_envelope_to_json() — dict to formatted JSON string
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# --- Constants ---

# Current export format version. Increment on breaking changes to the envelope
# structure. Import validation checks this against known versions.
EXPORT_FORMAT_VERSION: str = "1.0"


def build_export_envelope(
    neurons: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    vectors_included: bool,
    source_db_vector_model: Optional[str] = None,
    source_db_vector_dimensions: Optional[int] = None,
    memory_cli_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the complete export envelope wrapping neurons and edges.

    Args:
        neurons: List of serialized neuron dicts.
        edges: List of serialized edge dicts.
        vectors_included: Whether vector embeddings are included.
        source_db_vector_model: Model name used to generate vectors in source DB.
        source_db_vector_dimensions: Dimensionality of vectors in source DB.
        memory_cli_version: Current memory-cli version string.

    Returns:
        Complete envelope dict ready for JSON serialization.

    Envelope structure:
    {
        "memory_cli_version": str,
        "export_format_version": "1.0",
        "exported_at": str (ISO 8601 UTC),
        "source_db_vector_model": str or null,
        "source_db_vector_dimensions": int or null,
        "vectors_included": bool,
        "neuron_count": int,
        "edge_count": int,
        "neurons": [...],
        "edges": [...]
    }

    Logic flow:
    1. Call _build_metadata_header() to get top-level metadata fields
    2. Add neuron_count = len(neurons)
    3. Add edge_count = len(edges)
    4. Attach neurons array
    5. Attach edges array
    6. Return the assembled envelope dict

    Note: Key order is intentional — metadata first, counts next, data last.
    This makes the envelope human-scannable when viewing raw JSON.
    """
    # 1. Call _build_metadata_header() to get top-level metadata fields
    header = _build_metadata_header(
        vectors_included=vectors_included,
        source_db_vector_model=source_db_vector_model,
        source_db_vector_dimensions=source_db_vector_dimensions,
        memory_cli_version=memory_cli_version,
    )
    # 2. Add neuron_count = len(neurons)
    # 3. Add edge_count = len(edges)
    # 4. Attach neurons array
    # 5. Attach edges array
    envelope = {
        **header,
        "neuron_count": len(neurons),
        "edge_count": len(edges),
        "neurons": neurons,
        "edges": edges,
    }
    return envelope


def _build_metadata_header(
    vectors_included: bool,
    source_db_vector_model: Optional[str],
    source_db_vector_dimensions: Optional[int],
    memory_cli_version: Optional[str],
) -> Dict[str, Any]:
    """Build the metadata header fields for the envelope.

    Logic flow:
    1. Get current UTC timestamp via datetime.now(timezone.utc)
    2. Format as ISO 8601 string via .isoformat()
    3. If memory_cli_version not provided, attempt to read from package metadata
       — use importlib.metadata.version("memory-cli") if available
       — fallback to "unknown" if package not installed
    4. Return dict with keys:
       - memory_cli_version: str
       - export_format_version: EXPORT_FORMAT_VERSION constant
       - exported_at: ISO 8601 UTC string
       - source_db_vector_model: str or None
       - source_db_vector_dimensions: int or None
       - vectors_included: bool
    """
    # 1. Get current UTC timestamp via datetime.now(timezone.utc)
    # 2. Format as ISO 8601 string via .isoformat()
    exported_at = datetime.now(timezone.utc).isoformat()

    # 3. If memory_cli_version not provided, attempt to read from package metadata
    if memory_cli_version is None:
        try:
            from importlib.metadata import version as _pkg_version
            memory_cli_version = _pkg_version("memory-cli")
        except Exception:
            memory_cli_version = "unknown"

    # 4. Return dict with all header metadata fields
    return {
        "memory_cli_version": memory_cli_version,
        "export_format_version": EXPORT_FORMAT_VERSION,
        "exported_at": exported_at,
        "source_db_vector_model": source_db_vector_model,
        "source_db_vector_dimensions": source_db_vector_dimensions,
        "vectors_included": vectors_included,
    }


def serialize_envelope_to_json(
    envelope: Dict[str, Any],
    indent: int = 2,
) -> str:
    """Serialize the envelope dict to a formatted JSON string.

    Args:
        envelope: The complete export envelope dict.
        indent: JSON indentation level (default 2 for readability).

    Returns:
        JSON string with trailing newline.

    Logic flow:
    1. Use json.dumps with sort_keys=False (preserve insertion order)
       — envelope key order is intentional: metadata first, data last
    2. Set ensure_ascii=False for Unicode content preservation
    3. Set indent for human readability
    4. Append trailing newline for POSIX compliance
    5. Return the JSON string
    """
    # 1. Use json.dumps with sort_keys=False (preserve insertion order)
    # 2. Set ensure_ascii=False for Unicode content preservation
    # 3. Set indent for human readability
    # 4. Append trailing newline for POSIX compliance
    return json.dumps(envelope, indent=indent, sort_keys=False, ensure_ascii=False) + "\n"
