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
    # 1. Initialize ValidationResult
    result = ValidationResult()

    # 2. Run check 01 (JSON parseable) — if fails, return early
    if not _check_01_json_parseable(file_path, result):
        result.valid = False
        return result

    data = result.parsed_data

    # 3. Run checks 02-04 — if any fail, return early
    ok02 = _check_02_format_version_known(data, result)
    ok03 = _check_03_neurons_array_present(data, result)
    ok04 = _check_04_edges_array_present(data, result)
    if not (ok02 and ok03 and ok04):
        result.valid = len(result.errors) == 0
        return result

    neurons = data["neurons"]
    edges = data["edges"]

    # 4. Run checks 05-10 on each neuron
    for idx, neuron in enumerate(neurons):
        has_required = _check_05_neuron_required_fields(neuron, idx, result)
        _check_06_neuron_field_types(neuron, idx, result)
        _check_07_neuron_content_nonempty(neuron, idx, result)
        _check_08_neuron_timestamps_valid(neuron, idx, result)
        _check_09_neuron_tag_structure(neuron, idx, result)
        _check_10_neuron_attr_structure(neuron, idx, result)

    # 5. Run check 11 on each edge (weight and required fields)
    for idx, edge in enumerate(edges):
        # Check required fields on edge
        missing = [f for f in EDGE_REQUIRED_FIELDS if f not in edge]
        if missing:
            for field_name in missing:
                result.errors.append({
                    "check_number": 6,
                    "field": f"edges[{idx}].{field_name}",
                    "message": f"Edge at index {idx} is missing required field '{field_name}'",
                    "context": {"index": idx, "missing_field": field_name},
                })
        _check_11_edge_weight_finite(edge, idx, result)

    # 6. Run checks 12-14 (structural integrity)
    _check_12_count_integrity(data, result)
    _check_13_neuron_id_uniqueness(neurons, result)
    _check_14_edge_referential_integrity(neurons, edges, result)

    # 7. Run checks 15-17 (DB compatibility)
    _check_15_tags_auto_create(neurons, db_conn, result)
    _check_16_vector_dimension_mismatch(data, db_conn, result)
    _check_17_vector_model_mismatch(data, db_conn, result)

    # 8. Run check 18 (conflict detection)
    _check_18_id_conflict(neurons, db_conn, on_conflict, result)

    # 9. Set result.valid based on errors
    result.valid = len(result.errors) == 0

    # 10. Set counts
    # Count neurons that would be imported (not skipped)
    result.neurons_to_import = len(neurons) - result.neurons_skipped
    result.edges_to_import = len(edges)

    return result


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
    # 1. Attempt to open file_path for reading
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        result.errors.append({
            "check_number": 1,
            "field": "file",
            "message": f"File not found: {file_path}",
            "context": {"file_path": file_path},
        })
        return False
    except OSError as exc:
        result.errors.append({
            "check_number": 1,
            "field": "file",
            "message": f"I/O error reading file: {exc}",
            "context": {"file_path": file_path, "error": str(exc)},
        })
        return False

    # 2. Attempt json.loads() on the file content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        result.errors.append({
            "check_number": 1,
            "field": "file",
            "message": f"JSON parse error at line {exc.lineno}, col {exc.colno}: {exc.msg}",
            "context": {"line": exc.lineno, "col": exc.colno, "error": exc.msg},
        })
        return False

    # 3. Verify parsed result is a dict (object)
    if not isinstance(parsed, dict):
        result.errors.append({
            "check_number": 1,
            "field": "file",
            "message": f"JSON root must be an object, got {type(parsed).__name__}",
            "context": {"actual_type": type(parsed).__name__},
        })
        return False

    # 4. Store parsed dict in result.parsed_data
    result.parsed_data = parsed
    return True


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
    # 1. Check "export_format_version" key exists in data
    if "export_format_version" not in data:
        result.errors.append({
            "check_number": 2,
            "field": "export_format_version",
            "message": "Missing required field 'export_format_version'",
            "context": {},
        })
        return False

    # 2. Check value is in KNOWN_FORMAT_VERSIONS list
    version = data["export_format_version"]
    if version not in KNOWN_FORMAT_VERSIONS:
        result.errors.append({
            "check_number": 2,
            "field": "export_format_version",
            "message": (
                f"Unknown format version '{version}'. "
                f"Known versions: {KNOWN_FORMAT_VERSIONS}"
            ),
            "context": {"found": version, "known": KNOWN_FORMAT_VERSIONS},
        })
        return False
    return True


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
    if "neurons" not in data or not isinstance(data["neurons"], list):
        result.errors.append({
            "check_number": 3,
            "field": "neurons",
            "message": "'neurons' field must be present and be an array",
            "context": {"found_type": type(data.get("neurons")).__name__},
        })
        return False
    return True


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
    if "edges" not in data or not isinstance(data["edges"], list):
        result.errors.append({
            "check_number": 4,
            "field": "edges",
            "message": "'edges' field must be present and be an array",
            "context": {"found_type": type(data.get("edges")).__name__},
        })
        return False
    return True


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
    all_present = True
    for field_name in NEURON_REQUIRED_FIELDS:
        if field_name not in neuron:
            result.errors.append({
                "check_number": 5,
                "field": f"neurons[{index}].{field_name}",
                "message": f"Neuron at index {index} is missing required field '{field_name}'",
                "context": {"index": index, "missing_field": field_name},
            })
            all_present = False
    return all_present


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
    all_ok = True

    # id can be int or str (real schema uses INTEGER PK, export format represents as str or int)
    if "id" in neuron and not isinstance(neuron["id"], (str, int)):
        result.errors.append({
            "check_number": 6,
            "field": f"neurons[{index}].id",
            "message": (
                f"Neuron at index {index}, field 'id' must be a string or integer, "
                f"got {type(neuron['id']).__name__}"
            ),
            "context": {"index": index, "field": "id", "actual_type": type(neuron["id"]).__name__},
        })
        all_ok = False

    # Required string fields (excluding id)
    for field_name in ("content", "created_at", "updated_at"):
        if field_name in neuron and not isinstance(neuron[field_name], str):
            result.errors.append({
                "check_number": 6,
                "field": f"neurons[{index}].{field_name}",
                "message": (
                    f"Neuron at index {index}, field '{field_name}' must be a string, "
                    f"got {type(neuron[field_name]).__name__}"
                ),
                "context": {"index": index, "field": field_name, "actual_type": type(neuron[field_name]).__name__},
            })
            all_ok = False

    # Optional nullable string fields
    for field_name in ("project", "source"):
        if field_name in neuron and neuron[field_name] is not None:
            if not isinstance(neuron[field_name], str):
                result.errors.append({
                    "check_number": 6,
                    "field": f"neurons[{index}].{field_name}",
                    "message": (
                        f"Neuron at index {index}, field '{field_name}' must be a string or null, "
                        f"got {type(neuron[field_name]).__name__}"
                    ),
                    "context": {"index": index, "field": field_name, "actual_type": type(neuron[field_name]).__name__},
                })
                all_ok = False

    # tags must be list
    if "tags" in neuron and not isinstance(neuron["tags"], list):
        result.errors.append({
            "check_number": 6,
            "field": f"neurons[{index}].tags",
            "message": f"Neuron at index {index}, field 'tags' must be an array, got {type(neuron['tags']).__name__}",
            "context": {"index": index, "actual_type": type(neuron["tags"]).__name__},
        })
        all_ok = False

    # attributes must be dict
    if "attributes" in neuron and not isinstance(neuron["attributes"], dict):
        result.errors.append({
            "check_number": 6,
            "field": f"neurons[{index}].attributes",
            "message": f"Neuron at index {index}, field 'attributes' must be an object, got {type(neuron['attributes']).__name__}",
            "context": {"index": index, "actual_type": type(neuron["attributes"]).__name__},
        })
        all_ok = False

    # Optional vector fields
    if "vector" in neuron and not isinstance(neuron["vector"], list):
        result.errors.append({
            "check_number": 6,
            "field": f"neurons[{index}].vector",
            "message": f"Neuron at index {index}, field 'vector' must be an array if present",
            "context": {"index": index},
        })
        all_ok = False

    if "vector_model" in neuron and not isinstance(neuron["vector_model"], str):
        result.errors.append({
            "check_number": 6,
            "field": f"neurons[{index}].vector_model",
            "message": f"Neuron at index {index}, field 'vector_model' must be a string if present",
            "context": {"index": index},
        })
        all_ok = False

    return all_ok


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
    content = neuron.get("content")
    if not isinstance(content, str):
        return True  # type check (check 06) handles non-string
    if not content.strip():
        result.errors.append({
            "check_number": 7,
            "field": f"neurons[{index}].content",
            "message": f"Neuron at index {index} has empty or whitespace-only content",
            "context": {"index": index},
        })
        return False
    return True


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
    all_ok = True
    for field_name in ("created_at", "updated_at"):
        value = neuron.get(field_name)
        if not isinstance(value, str):
            continue  # type check (check 06) handles non-string
        try:
            datetime.fromisoformat(value)
        except (ValueError, TypeError):
            result.errors.append({
                "check_number": 8,
                "field": f"neurons[{index}].{field_name}",
                "message": (
                    f"Neuron at index {index}, field '{field_name}' is not a valid "
                    f"ISO 8601 timestamp: '{value}'"
                ),
                "context": {"index": index, "field": field_name, "value": value},
            })
            all_ok = False
    return all_ok


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
    tags = neuron.get("tags")
    if not isinstance(tags, list):
        return True  # type check (check 06) handles non-list
    all_ok = True
    for j, item in enumerate(tags):
        if not isinstance(item, str):
            result.errors.append({
                "check_number": 9,
                "field": f"neurons[{index}].tags[{j}]",
                "message": (
                    f"Neuron at index {index}, tag at position {j} must be a string, "
                    f"got {type(item).__name__}"
                ),
                "context": {"index": index, "tag_index": j, "actual_type": type(item).__name__},
            })
            all_ok = False
    return all_ok


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
    attrs = neuron.get("attributes")
    if not isinstance(attrs, dict):
        return True  # type check (check 06) handles non-dict
    all_ok = True
    for key, val in attrs.items():
        if not isinstance(key, str):
            result.errors.append({
                "check_number": 10,
                "field": f"neurons[{index}].attributes",
                "message": f"Neuron at index {index}, attribute key must be a string, got {type(key).__name__}: {key!r}",
                "context": {"index": index, "key": repr(key), "key_type": type(key).__name__},
            })
            all_ok = False
        if not isinstance(val, str):
            result.errors.append({
                "check_number": 10,
                "field": f"neurons[{index}].attributes.{key}",
                "message": (
                    f"Neuron at index {index}, attribute '{key}' value must be a string, "
                    f"got {type(val).__name__}"
                ),
                "context": {"index": index, "key": key, "value_type": type(val).__name__},
            })
            all_ok = False
    return all_ok


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
    weight = edge.get("weight")
    if not isinstance(weight, (int, float)):
        result.errors.append({
            "check_number": 11,
            "field": f"edges[{index}].weight",
            "message": f"Edge at index {index} weight must be a number, got {type(weight).__name__}",
            "context": {"index": index, "actual_type": type(weight).__name__},
        })
        return False
    if isinstance(weight, float) and not math.isfinite(weight):
        result.errors.append({
            "check_number": 11,
            "field": f"edges[{index}].weight",
            "message": f"Edge at index {index} weight must be finite, got {weight}",
            "context": {"index": index, "value": str(weight)},
        })
        return False
    return True


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
    all_ok = True
    if "neuron_count" in data:
        expected = data["neuron_count"]
        actual = len(data["neurons"])
        if expected != actual:
            result.errors.append({
                "check_number": 12,
                "field": "neuron_count",
                "message": f"neuron_count {expected} does not match actual neuron count {actual}",
                "context": {"expected": expected, "actual": actual},
            })
            all_ok = False
    if "edge_count" in data:
        expected = data["edge_count"]
        actual = len(data["edges"])
        if expected != actual:
            result.errors.append({
                "check_number": 12,
                "field": "edge_count",
                "message": f"edge_count {expected} does not match actual edge count {actual}",
                "context": {"expected": expected, "actual": actual},
            })
            all_ok = False
    return all_ok


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
    # Only include hashable IDs; non-hashable types (list, dict) are already
    # flagged by check_06 and must be excluded here to avoid TypeError.
    ids = [n.get("id") for n in neurons if isinstance(n.get("id"), (str, int, float, type(None)))]
    id_set = set(ids)
    if len(ids) == len(id_set):
        return True

    # Find duplicates
    from collections import Counter
    counts = Counter(ids)
    all_ok = True
    for neuron_id, count in counts.items():
        if count > 1:
            dup_indices = [i for i, n in enumerate(neurons) if n.get("id") == neuron_id]
            result.errors.append({
                "check_number": 13,
                "field": "neurons[].id",
                "message": f"Duplicate neuron ID '{neuron_id}' found at indices {dup_indices}",
                "context": {"id": neuron_id, "indices": dup_indices},
            })
            all_ok = False
    return all_ok


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
    # 1. Build set of neuron IDs from neurons array (exclude unhashable types
    #    such as list/dict — already flagged by check_06)
    neuron_id_set = {n.get("id") for n in neurons if isinstance(n.get("id"), (str, int, float, type(None)))}
    all_ok = True
    for i, edge in enumerate(edges):
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        if source_id not in neuron_id_set:
            result.errors.append({
                "check_number": 14,
                "field": f"edges[{i}].source_id",
                "message": f"Edge at index {i} source_id '{source_id}' not found in neurons array",
                "context": {"index": i, "source_id": source_id},
            })
            all_ok = False
        if target_id not in neuron_id_set:
            result.errors.append({
                "check_number": 14,
                "field": f"edges[{i}].target_id",
                "message": f"Edge at index {i} target_id '{target_id}' not found in neurons array",
                "context": {"index": i, "target_id": target_id},
            })
            all_ok = False
    return all_ok


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
    # 1. Collect all unique tag names across all neurons
    import_tags: set = set()
    import_attrs: set = set()
    for neuron in neurons:
        tags_val = neuron.get("tags") or []
        if isinstance(tags_val, list):
            for tag in tags_val:
                if isinstance(tag, str):
                    import_tags.add(tag)
        attrs_val = neuron.get("attributes") or {}
        if isinstance(attrs_val, dict):
            for key in attrs_val.keys():
                if isinstance(key, str):
                    import_attrs.add(key)

    # 2. Query existing tag names from target DB
    existing_tag_rows = db_conn.execute("SELECT name FROM tags").fetchall()
    existing_tags = {row[0] for row in existing_tag_rows}

    # 3. Compute new tags
    new_tags = import_tags - existing_tags
    result.tags_to_create = sorted(new_tags)

    # 4. Query existing attr key names from target DB
    existing_attr_rows = db_conn.execute("SELECT name FROM attr_keys").fetchall()
    existing_attrs = {row[0] for row in existing_attr_rows}

    # 5. Compute new attrs
    new_attrs = import_attrs - existing_attrs
    result.attrs_to_create = sorted(new_attrs)


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
    # 1. Skip if vectors_included is False or missing
    if not data.get("vectors_included"):
        return True

    # 2. Get source_db_vector_dimensions from data envelope
    source_dims = data.get("source_db_vector_dimensions")
    if source_dims is None:
        return True

    # 3. Query target DB config for vector dimensions (try meta table first, then config)
    target_dims = None
    for table, key_col, val_col, key_val in [
        ("meta", "key", "value", "vector_dimensions"),
        ("config", "key", "value", "vector_dimensions"),
    ]:
        try:
            row = db_conn.execute(
                f"SELECT {val_col} FROM {table} WHERE {key_col} = ?", (key_val,)
            ).fetchone()
            if row:
                target_dims = int(row[0])
                break
        except Exception:
            continue

    # 4. If both set and they differ -> append ERROR
    if target_dims is not None and source_dims != target_dims:
        result.errors.append({
            "check_number": 16,
            "field": "source_db_vector_dimensions",
            "message": (
                f"Vector dimension mismatch: import file has {source_dims} dimensions, "
                f"target DB has {target_dims} dimensions"
            ),
            "context": {"import_dims": source_dims, "target_dims": target_dims},
        })
        return False
    return True


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
    # 1. Skip if vectors_included is False or missing
    if not data.get("vectors_included"):
        return

    # 2. Get source_db_vector_model from data envelope
    source_model = data.get("source_db_vector_model")
    if source_model is None:
        return

    # 3. Query target DB config for vector model name
    target_model = None
    for table, key_col, val_col, key_val in [
        ("meta", "key", "value", "vector_model"),
        ("config", "key", "value", "vector_model"),
    ]:
        try:
            row = db_conn.execute(
                f"SELECT {val_col} FROM {table} WHERE {key_col} = ?", (key_val,)
            ).fetchone()
            if row:
                target_model = row[0]
                break
        except Exception:
            continue

    # 4. If both set and they differ -> append WARNING
    if target_model is not None and source_model != target_model:
        result.warnings.append({
            "check_number": 17,
            "field": "source_db_vector_model",
            "message": (
                f"Vector model mismatch: import file used '{source_model}', "
                f"target DB uses '{target_model}'. "
                "Semantic search quality may be degraded."
            ),
            "context": {"import_model": source_model, "target_model": target_model},
        })


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
    # 1. Collect all neuron IDs from import
    import_ids = [n.get("id") for n in neurons if n.get("id") is not None]
    if not import_ids:
        return

    # 2. Query target DB for conflicting IDs
    # Use a parameterized query with IN clause
    placeholders = ",".join("?" * len(import_ids))
    try:
        rows = db_conn.execute(
            f"SELECT id FROM neurons WHERE id IN ({placeholders})",
            import_ids,
        ).fetchall()
    except Exception:
        return

    conflicting_ids = {row[0] for row in rows}
    if not conflicting_ids:
        return

    # 3-7. Handle based on on_conflict mode
    for neuron_id in conflicting_ids:
        if on_conflict == "error":
            result.errors.append({
                "check_number": 18,
                "field": "neurons[].id",
                "message": f"Neuron ID '{neuron_id}' already exists in target database",
                "context": {"neuron_id": neuron_id},
            })
        elif on_conflict == "skip":
            result.warnings.append({
                "check_number": 18,
                "field": "neurons[].id",
                "message": f"Neuron ID '{neuron_id}' already exists — will be skipped",
                "context": {"neuron_id": neuron_id},
            })
        elif on_conflict == "overwrite":
            result.warnings.append({
                "check_number": 18,
                "field": "neurons[].id",
                "message": f"Neuron ID '{neuron_id}' already exists — will be replaced",
                "context": {"neuron_id": neuron_id},
            })

    # Update neurons_skipped for skip mode
    if on_conflict == "skip":
        result.neurons_skipped = len(conflicting_ids)
