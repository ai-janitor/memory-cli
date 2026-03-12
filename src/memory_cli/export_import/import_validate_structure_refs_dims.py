# =============================================================================
# Module: import_validate_structure_refs_dims.py
# Purpose: Run all 18 validation checks on an import file before any writes.
#   Collects ALL errors (not fail-fast) so the user sees every problem at once.
# Rationale: Import validation must be exhaustive and non-destructive. Running
#   all checks before any writes means a failed import never leaves the DB in
#   a partial state. Collecting errors (not failing on first) gives the user
#   a complete picture of what needs fixing — much better UX than fix-one-
#   rerun-fix-another cycles.
# Responsibility:
#   - Parse JSON from file
#   - Validate envelope structure and format version
#   - Validate each neuron: required fields, types, content, timestamps,
#     tag structure, attribute structure
#   - Validate each edge: required fields, weight type, referential integrity
#   - Check count integrity (neuron_count matches neurons array length)
#   - Check neuron ID uniqueness within the file
#   - Check vector dimensions and model compatibility against target DB
#   - Check ID conflicts against target DB per --on-conflict mode
#   - Return structured validation result with errors and warnings
# Organization:
#   1. Imports and constants
#   2. ValidationResult dataclass — holds errors, warnings, parsed data
#   3. validate_import_file() — main entry point, orchestrates all 18 checks
#   4. _check_01_json_parseable() — parse raw JSON
#   5. _check_02_format_version_known() — envelope format version check
#   6. _check_03_neurons_array_present() — neurons key exists and is a list
#   7. _check_04_edges_array_present() — edges key exists and is a list
#   8. _check_05_neuron_required_fields() — each neuron has required fields
#   9. _check_06_neuron_field_types() — field types are correct
#   10. _check_07_neuron_content_nonempty() — content is non-empty string
#   11. _check_08_neuron_timestamps_valid() — ISO 8601 parseable
#   12. _check_09_neuron_tag_structure() — tags is list of strings
#   13. _check_10_neuron_attr_structure() — attributes is dict of str to str
#   14. _check_11_edge_weight_finite() — weight is finite float
#   15. _check_12_count_integrity() — neuron_count == len(neurons)
#   16. _check_13_neuron_id_uniqueness() — no duplicate IDs in file
#   17. _check_14_edge_referential_integrity() — edge source/target in neurons
#   18. _check_15_tags_auto_create() — tags not in DB are noted (not error)
#   19. _check_16_vector_dimension_mismatch() — dimension mismatch is error
#   20. _check_17_vector_model_mismatch() — model mismatch is warning
#   21. _check_18_id_conflict() — check per --on-conflict mode
# =============================================================================

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# --- Constants ---

# Known export format versions that this importer can handle.
KNOWN_FORMAT_VERSIONS: List[str] = ["1.0"]

# Required fields on every neuron in the import file.
NEURON_REQUIRED_FIELDS: List[str] = [
    "id", "content", "created_at", "updated_at", "tags", "attributes",
]

# Required fields on every edge in the import file.
EDGE_REQUIRED_FIELDS: List[str] = [
    "source_id", "target_id", "reason", "weight", "created_at",
]


@dataclass
class ValidationResult:
    """Holds the result of all 18 import validation checks.

    Attributes:
        valid: True if no errors were found (warnings are OK).
        errors: List of error dicts with {check_number, field, message, context}.
        warnings: List of warning dicts with {check_number, field, message, context}.
        parsed_data: The parsed JSON dict if check 01 passed, else None.
        neurons_to_import: Count of neurons that would be imported.
        edges_to_import: Count of edges that would be imported.
        neurons_skipped: Count of neurons skipped due to conflict resolution.
        tags_to_create: List of tag names that don't exist in target DB.
        attrs_to_create: List of attr key names that don't exist in target DB.
    """
    valid: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    parsed_data: Optional[Dict[str, Any]] = None
    neurons_to_import: int = 0
    edges_to_import: int = 0
    neurons_skipped: int = 0
    tags_to_create: List[str] = field(default_factory=list)
    attrs_to_create: List[str] = field(default_factory=list)


def validate_import_file(
    file_path: str,
    db_conn: sqlite3.Connection,
    on_conflict: str = "error",
) -> ValidationResult:
    """Run all 18 validation checks on an import file.

    Args:
        file_path: Path to the JSON import file.
        db_conn: Active SQLite connection to the target memory database.
        on_conflict: Conflict resolution mode — "error", "skip", or "overwrite".

    Returns:
        ValidationResult with all errors and warnings collected.

    Logic flow:
    1. Initialize ValidationResult
    2. Run check 01 (JSON parseable)
       — if fails, return early (cannot continue without parsed data)
    3. Run checks 02-04 (format version, neurons array, edges array)
       — if any fail, return early (structure too broken to validate contents)
    4. Run checks 05-11 on each neuron:
       a. For each neuron at index i in neurons array:
          - check 05: required fields present
          - check 06: field types correct
          - check 07: content non-empty
          - check 08: timestamps valid ISO 8601
          - check 09: tag structure (list of strings)
          - check 10: attr structure (dict of str to str)
       b. Continue to next neuron even if this one has errors
    5. Run check 11 on each edge:
       a. For each edge at index i in edges array:
          - check required fields present (source_id, target_id, weight, etc.)
          - check weight is finite number
    6. Run checks 12-14 (structural integrity):
       - check 12: neuron_count == len(neurons), edge_count == len(edges)
       - check 13: neuron ID uniqueness within file
       - check 14: edge referential integrity (source/target in neurons)
    7. Run checks 15-17 (DB compatibility):
       - check 15: detect tags to auto-create (informational, not error)
       - check 16: vector dimension mismatch (error if mismatched)
       - check 17: vector model mismatch (warning only)
    8. Run check 18 (conflict detection):
       - check ID conflicts per on_conflict mode
    9. Set result.valid = (len(result.errors) == 0)
    10. Set result.neurons_to_import and result.edges_to_import counts
    11. Return result

    Error collection pattern:
    - Each _check_* function receives the result and appends to errors/warnings
    - No exceptions for validation failures — only for I/O errors
    - Each error dict has: check_number, field, message, context
    """
    pass


def _check_01_json_parseable(
    file_path: str,
    result: ValidationResult,
) -> bool:
    """Check 01: File exists and contains valid JSON.

    Logic flow:
    1. Attempt to open file_path for reading
    2. Attempt json.loads() on the file content
    3. If successful, store parsed dict in result.parsed_data, return True
    4. If FileNotFoundError -> append error with check_number=1, return False
    5. If json.JSONDecodeError -> append error with line/col info, return False
    6. If other IOError -> append error with message, return False

    Error format: {check_number: 1, field: "file", message: "...", context: {...}}
    """
    pass


def _check_02_format_version_known(
    data: Dict[str, Any],
    result: ValidationResult,
) -> bool:
    """Check 02: export_format_version is present and in KNOWN_FORMAT_VERSIONS.

    Logic flow:
    1. Check "export_format_version" key exists in data
    2. Check value is in KNOWN_FORMAT_VERSIONS list
    3. If key missing -> append error, return False
    4. If unknown version -> append error listing found vs known versions, return False
    5. Return True on success
    """
    pass


def _check_03_neurons_array_present(
    data: Dict[str, Any],
    result: ValidationResult,
) -> bool:
    """Check 03: "neurons" key exists and value is a list.

    Logic flow:
    1. Check "neurons" key exists in data
    2. Check isinstance(data["neurons"], list)
    3. If missing or wrong type -> append error, return False
    4. Return True on success
    """
    pass


def _check_04_edges_array_present(
    data: Dict[str, Any],
    result: ValidationResult,
) -> bool:
    """Check 04: "edges" key exists and value is a list.

    Logic flow:
    1. Check "edges" key exists in data
    2. Check isinstance(data["edges"], list)
    3. If missing or wrong type -> append error, return False
    4. Return True on success
    """
    pass


def _check_05_neuron_required_fields(
    neuron: Dict[str, Any],
    index: int,
    result: ValidationResult,
) -> bool:
    """Check 05: A single neuron dict has all required fields.

    Logic flow:
    1. For each field in NEURON_REQUIRED_FIELDS:
       a. If field not in neuron -> append error with neuron index and field name
    2. Return True only if ALL required fields present
    """
    pass


def _check_06_neuron_field_types(
    neuron: Dict[str, Any],
    index: int,
    result: ValidationResult,
) -> bool:
    """Check 06: Neuron field values have correct types.

    Expected types:
    - id: str
    - content: str
    - created_at: str
    - updated_at: str
    - project: str or None (optional, nullable)
    - source: str or None (optional, nullable)
    - tags: list
    - attributes: dict
    - vector: list (if present, optional)
    - vector_model: str (if present, optional)

    Logic flow:
    1. For each required field, check isinstance against expected type
    2. For optional nullable fields (project, source), allow None
    3. For optional fields (vector, vector_model), only check if present
    4. Append error for each type mismatch with expected vs actual type name
    5. Return True only if all checked fields have correct types
    """
    pass


def _check_07_neuron_content_nonempty(
    neuron: Dict[str, Any],
    index: int,
    result: ValidationResult,
) -> bool:
    """Check 07: Neuron content is a non-empty string after stripping whitespace.

    Logic flow:
    1. Get content field value (skip if not str — type check handles that)
    2. Call .strip() on content
    3. If result is empty string -> append error with neuron index
    4. Return True if non-empty after strip
    """
    pass


def _check_08_neuron_timestamps_valid(
    neuron: Dict[str, Any],
    index: int,
    result: ValidationResult,
) -> bool:
    """Check 08: created_at and updated_at are valid ISO 8601 timestamps.

    Logic flow:
    1. For each timestamp field ("created_at", "updated_at"):
       a. Get value (skip if not str — type check handles that)
       b. Attempt datetime.fromisoformat(value)
       c. If parse fails -> append error with neuron index and invalid value
    2. Return True only if both timestamps parse successfully
    """
    pass


def _check_09_neuron_tag_structure(
    neuron: Dict[str, Any],
    index: int,
    result: ValidationResult,
) -> bool:
    """Check 09: tags is a list where every item is a string.

    Logic flow:
    1. Get tags value (skip if not list — type check handles that)
    2. For each item at position j in tags:
       a. If not isinstance(item, str) -> append error with neuron index,
          tag position j, and actual type
    3. Return True only if all items are strings
    """
    pass


def _check_10_neuron_attr_structure(
    neuron: Dict[str, Any],
    index: int,
    result: ValidationResult,
) -> bool:
    """Check 10: attributes is a dict with string keys and string values.

    Logic flow:
    1. Get attributes value (skip if not dict — type check handles that)
    2. For each (key, value) pair in attributes:
       a. If key is not str -> append error with neuron index and key repr
       b. If value is not str -> append error with neuron index, key, and value type
    3. Return True only if all keys and values are strings
    """
    pass


def _check_11_edge_weight_finite(
    edge: Dict[str, Any],
    index: int,
    result: ValidationResult,
) -> bool:
    """Check 11: Edge weight is a finite number (not NaN, not Inf).

    Logic flow:
    1. Get weight value from edge
    2. Check isinstance(weight, (int, float))
       — if not numeric -> append error, return False
    3. If float, check math.isfinite(weight)
       — if NaN or Inf -> append error, return False
    4. Return True if weight is finite number
    """
    pass


def _check_12_count_integrity(
    data: Dict[str, Any],
    result: ValidationResult,
) -> bool:
    """Check 12: neuron_count matches len(neurons), edge_count matches len(edges).

    Logic flow:
    1. If "neuron_count" key present in data:
       a. Compare data["neuron_count"] to len(data["neurons"])
       b. If mismatch -> append error with expected vs actual count
    2. If "edge_count" key present in data:
       a. Compare data["edge_count"] to len(data["edges"])
       b. If mismatch -> append error with expected vs actual count
    3. If count keys missing, skip (they are metadata, absence is not an error)
    4. Return True only if all present counts match
    """
    pass


def _check_13_neuron_id_uniqueness(
    neurons: List[Dict[str, Any]],
    result: ValidationResult,
) -> bool:
    """Check 13: No duplicate neuron IDs within the import file.

    Logic flow:
    1. Collect all neuron "id" values into a list
    2. Build a set from the list
    3. If len(list) != len(set) -> duplicates exist
    4. Find the duplicate IDs by counting occurrences
    5. Append one error per duplicate ID listing which indices have that ID
    6. Return True only if all IDs are unique
    """
    pass


def _check_14_edge_referential_integrity(
    neurons: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    result: ValidationResult,
) -> bool:
    """Check 14: Every edge's source_id and target_id exist in the neurons array.

    Logic flow:
    1. Build set of neuron IDs from neurons array
    2. For each edge at index i:
       a. If "source_id" not in neuron ID set -> append error with edge index
       b. If "target_id" not in neuron ID set -> append error with edge index
    3. Return True only if all edges have valid source and target refs
    """
    pass


def _check_15_tags_auto_create(
    neurons: List[Dict[str, Any]],
    db_conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    """Check 15: Identify tags in import that don't exist in target DB.

    These are NOT errors — tags are auto-created on import.
    This populates result.tags_to_create for informational/dry-run output.

    Logic flow:
    1. Collect all unique tag names across all neurons' tags lists
    2. Query existing tag names from target DB tag registry
    3. Compute difference: import_tags - existing_tags = new_tags
    4. Store sorted list in result.tags_to_create
    5. Also collect all unique attr key names across all neurons' attributes dicts
    6. Query existing attr key names from target DB attr key registry
    7. Compute difference: import_attrs - existing_attrs = new_attrs
    8. Store sorted list in result.attrs_to_create
    """
    pass


def _check_16_vector_dimension_mismatch(
    data: Dict[str, Any],
    db_conn: sqlite3.Connection,
    result: ValidationResult,
) -> bool:
    """Check 16: Vector dimensions in import match target DB dimensions.

    Logic flow:
    1. If data.get("vectors_included") is False or missing -> skip, return True
    2. Get source_db_vector_dimensions from data envelope
    3. Query target DB config for vector dimensions
    4. If both are set and they differ -> append ERROR
       (writing wrong-dimension vectors would corrupt the vector index)
    5. Return True only if dimensions match or check was skipped
    """
    pass


def _check_17_vector_model_mismatch(
    data: Dict[str, Any],
    db_conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    """Check 17: Vector model in import vs target DB — WARNING only.

    Logic flow:
    1. If data.get("vectors_included") is False or missing -> skip
    2. Get source_db_vector_model from data envelope
    3. Query target DB config for vector model name
    4. If both are set and they differ -> append WARNING (not error)
       — different models can produce same-dimension vectors, but semantic
         similarity search quality may be degraded
    5. Do not set result.valid to False (warnings do not block import)
    """
    pass


def _check_18_id_conflict(
    neurons: List[Dict[str, Any]],
    db_conn: sqlite3.Connection,
    on_conflict: str,
    result: ValidationResult,
) -> None:
    """Check 18: Detect neuron ID conflicts with existing DB neurons.

    Behavior depends on --on-conflict mode:
    - "error": Any ID conflict -> append error (blocks import)
    - "skip": ID conflicts -> append warning, increment neurons_skipped
    - "overwrite": ID conflicts -> append warning (informational only)

    Logic flow:
    1. Collect all neuron IDs from import into a list
    2. Query target DB: SELECT id FROM neurons WHERE id IN (?)
    3. Build set of conflicting IDs (intersection)
    4. If no conflicts -> return (nothing to report)
    5. If on_conflict == "error":
       a. Append one error per conflicting ID
    6. If on_conflict == "skip":
       a. Append one warning per conflicting ID
       b. Set result.neurons_skipped = len(conflicting_ids)
    7. If on_conflict == "overwrite":
       a. Append one warning per conflicting ID noting it will be replaced
    """
    pass
