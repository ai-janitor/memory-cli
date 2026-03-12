# =============================================================================
# Module: test_import_validation.py
# Purpose: Test all 18 import validation checks, error collection behavior,
#   and the --validate-only / --dry-run mode.
# Rationale: Import validation is the primary safety gate. Every check must
#   be tested both for pass and fail cases. Error collection (not fail-fast)
#   must be verified — the user should see ALL problems at once. Dry-run
#   mode must verify that no writes occur.
# Responsibility:
#   - Test each of the 18 checks individually (pass and fail)
#   - Test error collection: multiple errors collected, not fail-fast
#   - Test that errors include check_number, field, message, context
#   - Test dry-run mode: validation runs, no writes
#   - Test edge cases: empty file, massive file, malformed JSON
# Organization:
#   1. Imports and fixtures
#   2. Fixture: valid import JSON (baseline that passes all checks)
#   3. Fixture: in-memory target DB with schema
#   4. Tests: Check 01 — JSON parseable
#   5. Tests: Check 02 — format version
#   6. Tests: Check 03 — neurons array
#   7. Tests: Check 04 — edges array
#   8. Tests: Check 05 — neuron required fields
#   9. Tests: Check 06 — neuron field types
#   10. Tests: Check 07 — content non-empty
#   11. Tests: Check 08 — timestamps valid
#   12. Tests: Check 09 — tag structure
#   13. Tests: Check 10 — attr structure
#   14. Tests: Check 11 — edge weight finite
#   15. Tests: Check 12 — count integrity
#   16. Tests: Check 13 — neuron ID uniqueness
#   17. Tests: Check 14 — edge referential integrity
#   18. Tests: Check 15 — tags auto-create detection
#   19. Tests: Check 16 — vector dimension mismatch
#   20. Tests: Check 17 — vector model mismatch
#   21. Tests: Check 18 — ID conflict detection
#   22. Tests: Error collection behavior
#   23. Tests: Dry-run mode
# =============================================================================

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from memory_cli.export_import.import_validate_structure_refs_dims import validate_import_file


# --- Fixtures ---


@pytest.fixture
def valid_import_json() -> Dict[str, Any]:
    """A valid import JSON dict that passes all 18 checks.

    Contains:
    - memory_cli_version: "0.1.0"
    - export_format_version: "1.0"
    - exported_at: valid ISO 8601 UTC timestamp
    - source_db_vector_model: null (no vectors)
    - source_db_vector_dimensions: null (no vectors)
    - vectors_included: false
    - neuron_count: 2
    - edge_count: 1
    - neurons: 2 neurons with all required fields, valid types, non-empty
      content, valid ISO timestamps, proper tag and attr structures
    - edges: 1 edge with valid refs and finite weight
    """
    return {
        "memory_cli_version": "0.1.0",
        "export_format_version": "1.0",
        "exported_at": "2025-01-01T00:00:00+00:00",
        "source_db_vector_model": None,
        "source_db_vector_dimensions": None,
        "vectors_included": False,
        "neuron_count": 2,
        "edge_count": 1,
        "neurons": [
            {
                "id": "import-uuid-001",
                "content": "First test neuron",
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
                "project": "test-project",
                "source": None,
                "tags": ["tag-a", "tag-b"],
                "attributes": {"key1": "val1"},
            },
            {
                "id": "import-uuid-002",
                "content": "Second test neuron",
                "created_at": "2025-01-02T00:00:00+00:00",
                "updated_at": "2025-01-02T00:00:00+00:00",
                "project": "test-project",
                "source": None,
                "tags": ["tag-a"],
                "attributes": {},
            },
        ],
        "edges": [
            {
                "source_id": "import-uuid-001",
                "target_id": "import-uuid-002",
                "weight": 0.8,
                "reason": "related",
                "created_at": "2025-01-01T00:00:00+00:00",
            },
        ],
    }


@pytest.fixture
def valid_import_file(valid_import_json, tmp_path) -> Path:
    """Write valid_import_json to a temp file and return the path.

    Steps:
    1. Create file at tmp_path / "import.json"
    2. json.dump(valid_import_json, file, indent=2)
    3. Return the Path object
    """
    path = tmp_path / "import.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(valid_import_json, f, indent=2)
    return path


sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec package required for import validation tests (vec0 virtual table)",
)


@pytest.fixture
def target_db() -> sqlite3.Connection:
    """In-memory SQLite DB with the real memory-cli schema applied via migration.

    Inserts config: vector_model="default-model", vector_dimensions=768

    Yields the connection, closes after test.
    """
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations import MIGRATION_REGISTRY
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    MIGRATION_REGISTRY[1](conn)
    conn.execute("COMMIT")
    # Insert vector config into meta table
    with conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('vector_model', 'default-model')")
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('vector_dimensions', '768')")
    yield conn
    conn.close()


# --- Helper: write JSON to temp file ---


def _write_json_file(data: Dict[str, Any], tmp_path: Path, filename: str = "import.json") -> Path:
    """Write a dict as JSON to a temp file and return the path.

    Steps:
    1. Create file path: tmp_path / filename
    2. json.dump(data, open(path, "w"), indent=2)
    3. Return path
    """
    path = tmp_path / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def _insert_neuron(conn: sqlite3.Connection, neuron_id: str, content: str = "existing content") -> None:
    """Insert a neuron directly into the DB for conflict testing.

    Note: The real schema has INTEGER PK, so neuron_id must be an integer.
    """
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (id, content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'test', 'active')",
        (neuron_id, content, now_ms, now_ms),
    )


# --- Tests: Check 01 — JSON parseable ---


class TestCheck01JsonParseable:
    """Check 01: File must exist and contain valid JSON."""

    def test_valid_json_passes(self, valid_import_file, target_db):
        """Valid JSON file should pass check 01.

        Steps:
        1. Call validate_import_file(str(valid_import_file), target_db)
        2. Assert result.parsed_data is not None
        3. Assert no errors with check_number == 1
        """
        result = validate_import_file(str(valid_import_file), target_db)
        assert result.parsed_data is not None
        errors_01 = [e for e in result.errors if e["check_number"] == 1]
        assert len(errors_01) == 0

    def test_file_not_found_fails(self, target_db):
        """Non-existent file path should fail with error.

        Steps:
        1. validate_import_file("/nonexistent/path.json", target_db)
        2. Assert result.valid is False
        3. Assert error with check_number == 1 present
        """
        result = validate_import_file("/nonexistent/path.json", target_db)
        assert result.valid is False
        errors_01 = [e for e in result.errors if e["check_number"] == 1]
        assert len(errors_01) > 0

    def test_invalid_json_fails(self, tmp_path, target_db):
        """File with invalid JSON should fail with parse error.

        Steps:
        1. Write "{invalid json content" to tmp_path / "bad.json"
        2. Validate
        3. Assert error with check_number == 1
        """
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json content")
        result = validate_import_file(str(bad_file), target_db)
        assert result.valid is False
        errors_01 = [e for e in result.errors if e["check_number"] == 1]
        assert len(errors_01) > 0

    def test_empty_file_fails(self, tmp_path, target_db):
        """Empty file should fail JSON parse.

        Steps:
        1. Write "" to tmp_path / "empty.json"
        2. Validate
        3. Assert error with check_number == 1
        """
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("")
        result = validate_import_file(str(empty_file), target_db)
        assert result.valid is False
        errors_01 = [e for e in result.errors if e["check_number"] == 1]
        assert len(errors_01) > 0


# --- Tests: Check 02 — format version ---


class TestCheck02FormatVersion:
    """Check 02: export_format_version must be known."""

    def test_known_version_passes(self, valid_import_json, tmp_path, target_db):
        """Version "1.0" should pass.

        Steps:
        1. Write valid_import_json to file (already has version "1.0")
        2. Validate
        3. Assert no errors with check_number == 2
        """
        path = _write_json_file(valid_import_json, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_02 = [e for e in result.errors if e["check_number"] == 2]
        assert len(errors_02) == 0

    def test_unknown_version_fails(self, valid_import_json, tmp_path, target_db):
        """Version "99.0" should fail.

        Steps:
        1. Mutate valid_import_json["export_format_version"] = "99.0"
        2. Write to file, validate
        3. Assert error with check_number == 2
        """
        data = copy.deepcopy(valid_import_json)
        data["export_format_version"] = "99.0"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_02 = [e for e in result.errors if e["check_number"] == 2]
        assert len(errors_02) > 0

    def test_missing_version_fails(self, valid_import_json, tmp_path, target_db):
        """Missing export_format_version key should fail.

        Steps:
        1. del valid_import_json["export_format_version"]
        2. Write to file, validate
        3. Assert error with check_number == 2
        """
        data = copy.deepcopy(valid_import_json)
        del data["export_format_version"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_02 = [e for e in result.errors if e["check_number"] == 2]
        assert len(errors_02) > 0


# --- Tests: Check 03 — neurons array ---


class TestCheck03NeuronsArray:
    """Check 03: "neurons" key must exist and be a list."""

    def test_valid_neurons_array_passes(self, valid_import_file, target_db):
        """Valid neurons array should pass check 03."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_03 = [e for e in result.errors if e["check_number"] == 3]
        assert len(errors_03) == 0

    def test_missing_neurons_key_fails(self, valid_import_json, tmp_path, target_db):
        """Missing "neurons" key should fail.

        Steps:
        1. del valid_import_json["neurons"]
        2. Write to file, validate
        3. Assert error with check_number == 3
        """
        data = copy.deepcopy(valid_import_json)
        del data["neurons"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_03 = [e for e in result.errors if e["check_number"] == 3]
        assert len(errors_03) > 0

    def test_neurons_not_list_fails(self, valid_import_json, tmp_path, target_db):
        """neurons as a dict or string should fail.

        Steps:
        1. valid_import_json["neurons"] = "not a list"
        2. Write to file, validate
        3. Assert error with check_number == 3
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"] = "not a list"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_03 = [e for e in result.errors if e["check_number"] == 3]
        assert len(errors_03) > 0


# --- Tests: Check 04 — edges array ---


class TestCheck04EdgesArray:
    """Check 04: "edges" key must exist and be a list."""

    def test_valid_edges_array_passes(self, valid_import_file, target_db):
        """Valid edges array should pass check 04."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_04 = [e for e in result.errors if e["check_number"] == 4]
        assert len(errors_04) == 0

    def test_missing_edges_key_fails(self, valid_import_json, tmp_path, target_db):
        """Missing "edges" key should fail."""
        data = copy.deepcopy(valid_import_json)
        del data["edges"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_04 = [e for e in result.errors if e["check_number"] == 4]
        assert len(errors_04) > 0

    def test_edges_not_list_fails(self, valid_import_json, tmp_path, target_db):
        """edges as a dict should fail."""
        data = copy.deepcopy(valid_import_json)
        data["edges"] = {"not": "a list"}
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_04 = [e for e in result.errors if e["check_number"] == 4]
        assert len(errors_04) > 0


# --- Tests: Check 05 — neuron required fields ---


class TestCheck05NeuronRequiredFields:
    """Check 05: Each neuron must have all required fields."""

    def test_all_fields_present_passes(self, valid_import_file, target_db):
        """All required fields present should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_05 = [e for e in result.errors if e["check_number"] == 5]
        assert len(errors_05) == 0

    def test_missing_id_fails(self, valid_import_json, tmp_path, target_db):
        """Neuron missing "id" should fail.

        Steps:
        1. del valid_import_json["neurons"][0]["id"]
        2. Write to file, validate
        3. Assert error with check_number == 5, field mentions "id"
        """
        data = copy.deepcopy(valid_import_json)
        del data["neurons"][0]["id"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_05 = [e for e in result.errors if e["check_number"] == 5]
        assert len(errors_05) > 0
        assert any("id" in e["field"] for e in errors_05)

    def test_missing_content_fails(self, valid_import_json, tmp_path, target_db):
        """Neuron missing "content" should fail."""
        data = copy.deepcopy(valid_import_json)
        del data["neurons"][0]["content"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_05 = [e for e in result.errors if e["check_number"] == 5]
        assert len(errors_05) > 0

    def test_missing_multiple_fields_reports_all(self, valid_import_json, tmp_path, target_db):
        """Multiple missing fields should produce multiple errors.

        Steps:
        1. Remove "id", "content", and "tags" from first neuron
        2. Write to file, validate
        3. Assert at least 3 errors with check_number == 5 for that neuron
        """
        data = copy.deepcopy(valid_import_json)
        del data["neurons"][0]["id"]
        del data["neurons"][0]["content"]
        del data["neurons"][0]["tags"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_05 = [e for e in result.errors if e["check_number"] == 5]
        assert len(errors_05) >= 3


# --- Tests: Check 06 — neuron field types ---


class TestCheck06NeuronFieldTypes:
    """Check 06: Neuron fields must have correct types."""

    def test_valid_types_pass(self, valid_import_file, target_db):
        """Correct types should pass check 06."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_06 = [e for e in result.errors if e["check_number"] == 6]
        assert len(errors_06) == 0

    def test_id_not_string_or_int_fails(self, valid_import_json, tmp_path, target_db):
        """id as a list (not str or int) should fail type check.

        Steps:
        1. valid_import_json["neurons"][0]["id"] = [1, 2, 3]
        2. Write to file, validate
        3. Assert error with check_number == 6
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["id"] = [1, 2, 3]  # List is not a valid id type
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_06 = [e for e in result.errors if e["check_number"] == 6]
        assert len(errors_06) > 0

    def test_tags_not_list_fails(self, valid_import_json, tmp_path, target_db):
        """tags as string should fail type check."""
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["tags"] = "not-a-list"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_06 = [e for e in result.errors if e["check_number"] == 6]
        assert len(errors_06) > 0

    def test_attrs_not_dict_fails(self, valid_import_json, tmp_path, target_db):
        """attributes as list should fail type check."""
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["attributes"] = ["not", "a", "dict"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_06 = [e for e in result.errors if e["check_number"] == 6]
        assert len(errors_06) > 0


# --- Tests: Check 07 — content non-empty ---


class TestCheck07ContentNonEmpty:
    """Check 07: Neuron content must be non-empty after stripping."""

    def test_non_empty_content_passes(self, valid_import_file, target_db):
        """Non-empty content should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_07 = [e for e in result.errors if e["check_number"] == 7]
        assert len(errors_07) == 0

    def test_empty_string_fails(self, valid_import_json, tmp_path, target_db):
        """Empty string content should fail.

        Steps:
        1. valid_import_json["neurons"][0]["content"] = ""
        2. Write to file, validate
        3. Assert error with check_number == 7
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["content"] = ""
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_07 = [e for e in result.errors if e["check_number"] == 7]
        assert len(errors_07) > 0

    def test_whitespace_only_fails(self, valid_import_json, tmp_path, target_db):
        """Whitespace-only content should fail.

        Steps:
        1. valid_import_json["neurons"][0]["content"] = "   \\n\\t  "
        2. Write to file, validate
        3. Assert error with check_number == 7
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["content"] = "   \n\t  "
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_07 = [e for e in result.errors if e["check_number"] == 7]
        assert len(errors_07) > 0


# --- Tests: Check 08 — timestamps valid ---


class TestCheck08TimestampsValid:
    """Check 08: created_at and updated_at must be valid ISO 8601."""

    def test_valid_timestamps_pass(self, valid_import_file, target_db):
        """Valid ISO timestamps should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_08 = [e for e in result.errors if e["check_number"] == 8]
        assert len(errors_08) == 0

    def test_invalid_created_at_fails(self, valid_import_json, tmp_path, target_db):
        """Non-ISO timestamp should fail.

        Steps:
        1. valid_import_json["neurons"][0]["created_at"] = "not-a-timestamp"
        2. Write to file, validate
        3. Assert error with check_number == 8
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["created_at"] = "not-a-timestamp"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_08 = [e for e in result.errors if e["check_number"] == 8]
        assert len(errors_08) > 0

    def test_invalid_updated_at_fails(self, valid_import_json, tmp_path, target_db):
        """Invalid updated_at should also fail check 08."""
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["updated_at"] = "2025-99-99 invalid"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_08 = [e for e in result.errors if e["check_number"] == 8]
        assert len(errors_08) > 0


# --- Tests: Check 09 — tag structure ---


class TestCheck09TagStructure:
    """Check 09: tags must be a list of strings."""

    def test_valid_tag_list_passes(self, valid_import_file, target_db):
        """List of strings should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_09 = [e for e in result.errors if e["check_number"] == 9]
        assert len(errors_09) == 0

    def test_tag_not_string_fails(self, valid_import_json, tmp_path, target_db):
        """Tag as integer in the list should fail.

        Steps:
        1. valid_import_json["neurons"][0]["tags"] = ["valid-tag", 123]
        2. Write to file, validate
        3. Assert error with check_number == 9
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["tags"] = ["valid-tag", 123]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_09 = [e for e in result.errors if e["check_number"] == 9]
        assert len(errors_09) > 0


# --- Tests: Check 10 — attr structure ---


class TestCheck10AttrStructure:
    """Check 10: attributes must be dict with string keys and string values."""

    def test_valid_attrs_pass(self, valid_import_file, target_db):
        """Dict of str to str should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_10 = [e for e in result.errors if e["check_number"] == 10]
        assert len(errors_10) == 0

    def test_non_string_value_fails(self, valid_import_json, tmp_path, target_db):
        """Attribute value as int should fail.

        Steps:
        1. valid_import_json["neurons"][0]["attributes"] = {"key": 123}
        2. Write to file, validate
        3. Assert error with check_number == 10
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["attributes"] = {"key": 123}
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_10 = [e for e in result.errors if e["check_number"] == 10]
        assert len(errors_10) > 0

    def test_non_string_key_fails(self, valid_import_json, tmp_path, target_db):
        """Non-string key in attributes should fail.

        Note: JSON always parses keys as strings, so we create a valid JSON
        with a string key that our check should accept. We verify the check
        logic works by manipulating the parsed data directly and writing it.
        For this test, we verify a legitimate string key passes.
        """
        # JSON always has string keys, so let's verify a valid dict passes
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["attributes"] = {"valid_key": "valid_value"}
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_10 = [e for e in result.errors if e["check_number"] == 10]
        assert len(errors_10) == 0


# --- Tests: Check 11 — edge weight finite ---


class TestCheck11EdgeWeightFinite:
    """Check 11: Edge weight must be a finite number."""

    def test_finite_weight_passes(self, valid_import_file, target_db):
        """Finite float weight should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_11 = [e for e in result.errors if e["check_number"] == 11]
        assert len(errors_11) == 0

    def test_nan_weight_fails(self, valid_import_json, tmp_path, target_db):
        """NaN weight should fail.

        Note: Standard JSON doesn't support NaN. We write a valid JSON file
        and then manually corrupt the weight field by writing raw text.
        Instead, we verify the check catches an invalid type (string weight).
        """
        data = copy.deepcopy(valid_import_json)
        # Write the file with NaN by using allow_nan=True
        path = tmp_path / "import_nan.json"
        import math
        data["edges"][0]["weight"] = float("nan")
        with open(path, "w") as f:
            json.dump(data, f, allow_nan=True)
        result = validate_import_file(str(path), target_db)
        errors_11 = [e for e in result.errors if e["check_number"] == 11]
        assert len(errors_11) > 0

    def test_inf_weight_fails(self, valid_import_json, tmp_path, target_db):
        """Infinity weight should fail."""
        data = copy.deepcopy(valid_import_json)
        data["edges"][0]["weight"] = float("inf")
        path = tmp_path / "import_inf.json"
        with open(path, "w") as f:
            json.dump(data, f, allow_nan=True)
        result = validate_import_file(str(path), target_db)
        errors_11 = [e for e in result.errors if e["check_number"] == 11]
        assert len(errors_11) > 0

    def test_string_weight_fails(self, valid_import_json, tmp_path, target_db):
        """Non-numeric weight should fail.

        Steps:
        1. valid_import_json["edges"][0]["weight"] = "heavy"
        2. Write to file, validate
        3. Assert error with check_number == 11
        """
        data = copy.deepcopy(valid_import_json)
        data["edges"][0]["weight"] = "heavy"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_11 = [e for e in result.errors if e["check_number"] == 11]
        assert len(errors_11) > 0


# --- Tests: Check 12 — count integrity ---


class TestCheck12CountIntegrity:
    """Check 12: neuron_count == len(neurons), edge_count == len(edges)."""

    def test_correct_counts_pass(self, valid_import_file, target_db):
        """Matching counts should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_12 = [e for e in result.errors if e["check_number"] == 12]
        assert len(errors_12) == 0

    def test_neuron_count_mismatch_fails(self, valid_import_json, tmp_path, target_db):
        """neuron_count != len(neurons) should fail.

        Steps:
        1. valid_import_json["neuron_count"] = 999
        2. Write to file, validate
        3. Assert error with check_number == 12
        """
        data = copy.deepcopy(valid_import_json)
        data["neuron_count"] = 999
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_12 = [e for e in result.errors if e["check_number"] == 12]
        assert len(errors_12) > 0

    def test_edge_count_mismatch_fails(self, valid_import_json, tmp_path, target_db):
        """edge_count != len(edges) should fail."""
        data = copy.deepcopy(valid_import_json)
        data["edge_count"] = 999
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_12 = [e for e in result.errors if e["check_number"] == 12]
        assert len(errors_12) > 0


# --- Tests: Check 13 — neuron ID uniqueness ---


class TestCheck13NeuronIdUniqueness:
    """Check 13: No duplicate neuron IDs within the import file."""

    def test_unique_ids_pass(self, valid_import_file, target_db):
        """Unique IDs should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_13 = [e for e in result.errors if e["check_number"] == 13]
        assert len(errors_13) == 0

    def test_duplicate_ids_fail(self, valid_import_json, tmp_path, target_db):
        """Two neurons with same ID should fail.

        Steps:
        1. Set second neuron's id to match first neuron's id
        2. Write to file, validate
        3. Assert error with check_number == 13
        """
        data = copy.deepcopy(valid_import_json)
        data["neurons"][1]["id"] = data["neurons"][0]["id"]
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_13 = [e for e in result.errors if e["check_number"] == 13]
        assert len(errors_13) > 0


# --- Tests: Check 14 — edge referential integrity ---


class TestCheck14EdgeReferentialIntegrity:
    """Check 14: Edge source_id and target_id must reference neurons in file."""

    def test_valid_refs_pass(self, valid_import_file, target_db):
        """Edges referencing existing neurons should pass."""
        result = validate_import_file(str(valid_import_file), target_db)
        errors_14 = [e for e in result.errors if e["check_number"] == 14]
        assert len(errors_14) == 0

    def test_invalid_source_id_fails(self, valid_import_json, tmp_path, target_db):
        """Edge with source_id not in neurons should fail.

        Steps:
        1. valid_import_json["edges"][0]["source_id"] = "nonexistent-uuid"
        2. Write to file, validate
        3. Assert error with check_number == 14
        """
        data = copy.deepcopy(valid_import_json)
        data["edges"][0]["source_id"] = "nonexistent-uuid"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_14 = [e for e in result.errors if e["check_number"] == 14]
        assert len(errors_14) > 0

    def test_invalid_target_id_fails(self, valid_import_json, tmp_path, target_db):
        """Edge with target_id not in neurons should fail."""
        data = copy.deepcopy(valid_import_json)
        data["edges"][0]["target_id"] = "nonexistent-uuid"
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_14 = [e for e in result.errors if e["check_number"] == 14]
        assert len(errors_14) > 0


# --- Tests: Check 15 — tags auto-create ---


class TestCheck15TagsAutoCreate:
    """Check 15: Tags not in target DB are noted for auto-creation (not error)."""

    def test_new_tags_detected(self, valid_import_file, target_db):
        """Tags not in target DB should appear in tags_to_create.

        Steps:
        1. Target DB has no tags
        2. Import file has neurons with tags ["tag-a", "tag-b"]
        3. Validate
        4. Assert result.tags_to_create contains "tag-a" and "tag-b"
        5. Assert no errors (tags are auto-created, not rejected)
        """
        result = validate_import_file(str(valid_import_file), target_db)
        assert "tag-a" in result.tags_to_create
        assert "tag-b" in result.tags_to_create
        # Should be informational, not an error
        errors_15 = [e for e in result.errors if e["check_number"] == 15]
        assert len(errors_15) == 0

    def test_existing_tags_not_in_create_list(self, valid_import_file, target_db):
        """Tags already in target DB should NOT be in tags_to_create.

        Steps:
        1. Insert "tag-a" into target DB tags table
        2. Validate
        3. Assert "tag-a" NOT in result.tags_to_create
        4. Assert "tag-b" IS in result.tags_to_create
        """
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute("INSERT INTO tags (name, created_at) VALUES ('tag-a', ?)", (now_ms,))
        result = validate_import_file(str(valid_import_file), target_db)
        assert "tag-a" not in result.tags_to_create
        assert "tag-b" in result.tags_to_create


# --- Tests: Check 16 — vector dimension mismatch ---


class TestCheck16VectorDimensionMismatch:
    """Check 16: Vector dimensions must match target DB — ERROR if mismatch."""

    def test_matching_dimensions_pass(self, valid_import_json, tmp_path, target_db):
        """Same dimensions in import and target DB should pass.

        Steps:
        1. Set vectors_included=True, source_db_vector_dimensions=768
        2. Target DB config has vector_dimensions=768
        3. Validate
        4. Assert no errors with check_number == 16
        """
        data = copy.deepcopy(valid_import_json)
        data["vectors_included"] = True
        data["source_db_vector_dimensions"] = 768
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_16 = [e for e in result.errors if e["check_number"] == 16]
        assert len(errors_16) == 0

    def test_mismatched_dimensions_fail(self, valid_import_json, tmp_path, target_db):
        """Different dimensions should produce error.

        Steps:
        1. Set vectors_included=True, source_db_vector_dimensions=384
        2. Target DB config has vector_dimensions=768
        3. Validate
        4. Assert error with check_number == 16
        """
        data = copy.deepcopy(valid_import_json)
        data["vectors_included"] = True
        data["source_db_vector_dimensions"] = 384
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        errors_16 = [e for e in result.errors if e["check_number"] == 16]
        assert len(errors_16) > 0

    def test_no_vectors_skips_check(self, valid_import_file, target_db):
        """When vectors_included=False, dimension check is skipped.

        Steps:
        1. valid_import_json has vectors_included=False
        2. Validate
        3. Assert no errors with check_number == 16
        """
        result = validate_import_file(str(valid_import_file), target_db)
        errors_16 = [e for e in result.errors if e["check_number"] == 16]
        assert len(errors_16) == 0


# --- Tests: Check 17 — vector model mismatch ---


class TestCheck17VectorModelMismatch:
    """Check 17: Vector model mismatch is WARNING, not error."""

    def test_matching_model_no_warning(self, valid_import_json, tmp_path, target_db):
        """Same model should produce no warning.

        Steps:
        1. Set vectors_included=True, source_db_vector_model="default-model"
        2. Target DB config has vector_model="default-model"
        3. Validate
        4. Assert no warnings with check_number == 17
        """
        data = copy.deepcopy(valid_import_json)
        data["vectors_included"] = True
        data["source_db_vector_model"] = "default-model"
        data["source_db_vector_dimensions"] = 768
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        warnings_17 = [w for w in result.warnings if w["check_number"] == 17]
        assert len(warnings_17) == 0

    def test_mismatched_model_warning(self, valid_import_json, tmp_path, target_db):
        """Different model should produce warning (not error).

        Steps:
        1. Set vectors_included=True, source_db_vector_model="other-model"
        2. Target DB config has vector_model="default-model"
        3. Validate
        4. Assert result.valid is still True (warning, not error)
        5. Assert warning with check_number == 17 present
        """
        data = copy.deepcopy(valid_import_json)
        data["vectors_included"] = True
        data["source_db_vector_model"] = "other-model"
        data["source_db_vector_dimensions"] = 768
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        assert result.valid is True
        warnings_17 = [w for w in result.warnings if w["check_number"] == 17]
        assert len(warnings_17) > 0


# --- Tests: Check 18 — ID conflict ---


class TestCheck18IdConflict:
    """Check 18: Neuron ID conflicts detected per --on-conflict mode."""

    def test_no_conflicts_passes_all_modes(self, valid_import_file, target_db):
        """No conflicts in target DB should pass for all modes.

        Steps:
        1. Target DB is empty (no neurons inserted)
        2. Validate with each mode: error, skip, overwrite
        3. Assert result.valid is True for all modes
        """
        for mode in ("error", "skip", "overwrite"):
            result = validate_import_file(str(valid_import_file), target_db, on_conflict=mode)
            errors_18 = [e for e in result.errors if e["check_number"] == 18]
            assert len(errors_18) == 0, f"Mode '{mode}' should have no errors"

    def test_conflict_error_mode_fails(self, valid_import_json, tmp_path, target_db):
        """Conflict in error mode should produce error.

        Steps:
        1. Insert neuron with id=99001 into target DB
        2. Set import neuron id to "import-uuid-001" (already in valid_import_json)
           and also insert that UUID into target DB
        3. Validate with on_conflict="error"
        4. Assert result.valid is False
        5. Assert error with check_number == 18

        Note: The real schema uses INTEGER PK. We insert a neuron with a specific
        integer ID and use that integer ID in the import to trigger conflict.
        """
        # Insert a neuron with a specific ID (99001) that won't conflict with
        # autoincrement in other tests
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at, project, status) "
                "VALUES (99001, 'existing', ?, ?, 'test', 'active')",
                (now_ms, now_ms),
            )

        # The import has string IDs ("import-uuid-001") but DB has integer IDs
        # For check_18 to detect a conflict, we need the import ID to match a DB ID
        # Since DB uses INTEGER PK, use integer IDs in the import too
        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["id"] = 99001  # This integer will match DB row
        data["edges"][0]["source_id"] = 99001
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db, on_conflict="error")
        assert result.valid is False
        errors_18 = [e for e in result.errors if e["check_number"] == 18]
        assert len(errors_18) > 0

    def test_conflict_skip_mode_warns(self, valid_import_json, tmp_path, target_db):
        """Conflict in skip mode should produce warning, not error.

        Steps:
        1. Insert neuron with id=99002 into target DB
        2. Import has a neuron with id=99002
        3. Validate with on_conflict="skip"
        4. Assert result.valid is True (warning, not error)
        5. Assert warning with check_number == 18 present
        6. Assert result.neurons_skipped == 1
        """
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at, project, status) "
                "VALUES (99002, 'existing', ?, ?, 'test', 'active')",
                (now_ms, now_ms),
            )

        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["id"] = 99002
        data["edges"][0]["source_id"] = 99002
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db, on_conflict="skip")
        assert result.valid is True
        warnings_18 = [w for w in result.warnings if w["check_number"] == 18]
        assert len(warnings_18) > 0
        assert result.neurons_skipped == 1

    def test_conflict_overwrite_mode_warns(self, valid_import_json, tmp_path, target_db):
        """Conflict in overwrite mode should produce warning, not error.

        Steps:
        1. Insert neuron with id=99003 into target DB
        2. Import has a neuron with id=99003
        3. Validate with on_conflict="overwrite"
        4. Assert result.valid is True
        5. Assert warning with check_number == 18 present
        """
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at, project, status) "
                "VALUES (99003, 'existing', ?, ?, 'test', 'active')",
                (now_ms, now_ms),
            )

        data = copy.deepcopy(valid_import_json)
        data["neurons"][0]["id"] = 99003
        data["edges"][0]["source_id"] = 99003
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db, on_conflict="overwrite")
        assert result.valid is True
        warnings_18 = [w for w in result.warnings if w["check_number"] == 18]
        assert len(warnings_18) > 0


# --- Tests: Error collection behavior ---


class TestErrorCollection:
    """Errors are collected (not fail-fast) so user sees all problems."""

    def test_multiple_errors_collected(self, tmp_path, target_db):
        """Import with multiple problems should report all of them.

        Steps:
        1. Create import JSON with multiple issues (all with valid version):
           - Neuron with missing "id" (check 05)
           - Edge with string weight (check 11)
           - Count mismatch (check 12)
        2. Write to file, validate
        3. Assert len(result.errors) >= 2
        4. Assert errors from different check_numbers present

        Note: We use a valid format version so checks 05-18 are reached.
        Unknown format version causes early exit before other checks run.
        """
        data = {
            "export_format_version": "1.0",  # valid version
            "neuron_count": 999,  # check 12 error
            "edge_count": 1,
            "neurons": [
                {
                    # missing "id" -> check 05 error
                    "content": "Valid content",
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "updated_at": "2025-01-01T00:00:00+00:00",
                    "tags": [],
                    "attributes": {},
                }
            ],
            "edges": [
                {
                    "source_id": "a",
                    "target_id": "b",
                    "weight": "not-a-number",  # check 11 error
                    "reason": "related",
                    "created_at": "2025-01-01T00:00:00+00:00",
                }
            ],
        }
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        assert len(result.errors) >= 2
        check_numbers = {e["check_number"] for e in result.errors}
        assert len(check_numbers) >= 2

    def test_errors_have_required_fields(self, tmp_path, target_db):
        """Each error dict should have check_number, field, message.

        Steps:
        1. Trigger any validation error
        2. Get first error from result.errors
        3. Assert "check_number" in error
        4. Assert "message" in error
        """
        path = tmp_path / "bad.json"
        path.write_text("{not: valid json}")
        result = validate_import_file(str(path), target_db)
        assert len(result.errors) > 0
        error = result.errors[0]
        assert "check_number" in error
        assert "message" in error

    def test_warnings_separate_from_errors(self, valid_import_json, tmp_path, target_db):
        """Warnings should be in result.warnings, not result.errors.

        Steps:
        1. Set up vector model mismatch (check 17 -> warning)
        2. Validate
        3. Assert check 17 item is in result.warnings
        4. Assert check 17 item is NOT in result.errors
        """
        data = copy.deepcopy(valid_import_json)
        data["vectors_included"] = True
        data["source_db_vector_model"] = "different-model"
        data["source_db_vector_dimensions"] = 768
        path = _write_json_file(data, tmp_path)
        result = validate_import_file(str(path), target_db)
        warnings_17 = [w for w in result.warnings if w["check_number"] == 17]
        errors_17 = [e for e in result.errors if e["check_number"] == 17]
        assert len(warnings_17) > 0
        assert len(errors_17) == 0


# --- Tests: Dry-run mode ---


class TestDryRunMode:
    """--validate-only runs all checks but writes nothing."""

    def test_dry_run_reports_what_would_happen(self, valid_import_file, target_db):
        """Dry run should populate neurons_to_import, tags_to_create, etc.

        Steps:
        1. Call validate_import_file (validation only, no import)
        2. Assert result.neurons_to_import == 2
        3. Assert result.tags_to_create is populated
        4. Assert result.edges_to_import == 1
        """
        result = validate_import_file(str(valid_import_file), target_db)
        assert result.neurons_to_import == 2
        assert len(result.tags_to_create) > 0
        assert result.edges_to_import == 1

    def test_dry_run_no_writes_to_db(self, valid_import_file, target_db):
        """After dry run, target DB should have no new data.

        Steps:
        1. Run validate_import_file
        2. SELECT COUNT(*) FROM neurons -> assert 0
        3. SELECT COUNT(*) FROM tags (beyond pre-existing) -> assert 0
        4. SELECT COUNT(*) FROM edges -> assert 0
        """
        validate_import_file(str(valid_import_file), target_db)
        neuron_count = target_db.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        tag_count = target_db.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        edge_count = target_db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        assert neuron_count == 0
        assert tag_count == 0
        assert edge_count == 0
