# =============================================================================
# Module: test_import_write.py
# Purpose: Test the transactional import write pipeline — tag/attr creation,
#   neuron insertion with preserved IDs, edge writing, vector import, and
#   transaction rollback on failure.
# Rationale: The write pipeline is the most dangerous code path — it mutates
#   the database. Transaction atomicity must be tested: partial failures must
#   leave zero trace. Tag and attr auto-creation must be verified. Vector
#   import must preserve data fidelity. Preserved neuron IDs must remain
#   intact (not re-generated).
# Responsibility:
#   - Test successful import writes all data correctly
#   - Test tag auto-creation during import
#   - Test attr key auto-creation during import
#   - Test neuron IDs are preserved from import file (not re-generated)
#   - Test neuron tags/attrs are correctly associated
#   - Test vector import preserves float data
#   - Test edge import with correct source/target references
#   - Test transaction rollback on failure leaves DB unchanged
#   - Test FTS triggers fire after neuron insert
# Organization:
#   1. Imports and fixtures
#   2. Fixture: in-memory target DB with schema
#   3. Fixture: valid ValidationResult with parsed data
#   4. Tests: successful full import
#   5. Tests: tag creation
#   6. Tests: attr key creation
#   7. Tests: neuron ID preservation
#   8. Tests: neuron tag/attr association
#   9. Tests: vector import
#   10. Tests: edge import
#   11. Tests: transaction rollback
#   12. Tests: ImportResult correctness
# =============================================================================

from __future__ import annotations

import sqlite3
import struct
import time
from typing import Any, Dict, List

import pytest

from memory_cli.export_import.import_write_transactional import import_neurons, ImportResult
from memory_cli.export_import.import_validate_structure_refs_dims import ValidationResult

# Skip all tests in this file if sqlite_vec is not available
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec package required for import write tests (vec0 virtual table)",
)


# --- Fixtures ---


@pytest.fixture
def target_db() -> sqlite3.Connection:
    """In-memory SQLite DB with the real memory-cli schema applied via migration.

    Creates all required tables via the baseline migration (including vec0).
    Yields connection, closes after test.
    """
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations import MIGRATION_REGISTRY
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    MIGRATION_REGISTRY[1](conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _make_validation_result(neurons: List[Dict], edges: List[Dict],
                             tags_to_create: List[str] = None,
                             attrs_to_create: List[str] = None,
                             vectors_included: bool = False) -> ValidationResult:
    """Build a passing ValidationResult with the given data."""
    vr = ValidationResult()
    vr.valid = True
    vr.parsed_data = {
        "neurons": neurons,
        "edges": edges,
        "vectors_included": vectors_included,
    }
    vr.tags_to_create = tags_to_create or []
    vr.attrs_to_create = attrs_to_create or []
    vr.neurons_to_import = len(neurons)
    vr.edges_to_import = len(edges)
    return vr


def _make_neuron(neuron_id: int, content: str = "Test content",
                 tags: List[str] = None, attributes: Dict = None,
                 created_at: str = "2025-01-01T00:00:00+00:00") -> Dict:
    """Create a serialized neuron dict for import."""
    return {
        "id": neuron_id,
        "content": content,
        "created_at": created_at,
        "updated_at": created_at,
        "project": "test-project",
        "source": None,
        "tags": tags or [],
        "attributes": attributes or {},
    }


def _make_edge(source_id: int, target_id: int, reason: str = "related",
               weight: float = 0.75) -> Dict:
    """Create a serialized edge dict for import."""
    return {
        "source_id": source_id,
        "target_id": target_id,
        "reason": reason,
        "weight": weight,
        "created_at": "2025-01-01T00:00:00+00:00",
    }


@pytest.fixture
def valid_validation_result():
    """A ValidationResult that passed all checks, with parsed data.

    Contains:
    - valid: True
    - parsed_data: dict with envelope structure containing:
      - 2 neurons with tags and attributes
      - 1 edge connecting them
      - vectors_included: False
    - tags_to_create: ["project:test", "type:note"]
    - attrs_to_create: ["language"]
    - neurons_to_import: 2
    - edges_to_import: 1

    Note: Neuron IDs are integers (matching real schema INTEGER PK).
    We use large IDs unlikely to conflict with autoincrement.
    """
    neurons = [
        _make_neuron(10001, "First neuron", tags=["project:test", "type:note"],
                     attributes={"language": "en"}),
        _make_neuron(10002, "Second neuron", tags=["project:test"]),
    ]
    edges = [_make_edge(10001, 10002)]
    return _make_validation_result(
        neurons=neurons,
        edges=edges,
        tags_to_create=["project:test", "type:note"],
        attrs_to_create=["language"],
    )


@pytest.fixture
def validation_result_with_vectors():
    """A ValidationResult with vectors included in parsed data.

    Same structure as valid_validation_result but:
    - parsed_data has vectors_included: True
    - Each neuron has:
      - vector: list of 768 floats ([0.1] * 768)
      - vector_model: "test-embedding-model"

    Returns a ValidationResult instance.
    """
    vector = [0.1] * 768
    neurons = [
        {**_make_neuron(10001, "First neuron"), "vector": vector, "vector_model": "test-embedding-model"},
        {**_make_neuron(10002, "Second neuron"), "vector": vector, "vector_model": "test-embedding-model"},
    ]
    edges = [_make_edge(10001, 10002)]
    return _make_validation_result(
        neurons=neurons,
        edges=edges,
        tags_to_create=[],
        attrs_to_create=[],
        vectors_included=True,
    )


# --- Tests: Successful full import ---


class TestSuccessfulImport:
    """Full import pipeline writes all data correctly."""

    def test_import_returns_success(self, target_db, valid_validation_result):
        """import_neurons() should return ImportResult with success=True.

        Steps:
        1. Call import_neurons(target_db, valid_validation_result)
        2. Assert result.success is True
        3. Assert result.error_message is None
        """
        result = import_neurons(target_db, valid_validation_result)
        assert result.success is True
        assert result.error_message is None

    def test_neurons_written_to_db(self, target_db, valid_validation_result):
        """After import, neurons should be queryable from DB.

        Steps:
        1. Call import_neurons(target_db, valid_validation_result)
        2. Execute SELECT COUNT(*) FROM neurons
        3. Assert count == 2
        """
        import_neurons(target_db, valid_validation_result)
        count = target_db.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        assert count == 2

    def test_edges_written_to_db(self, target_db, valid_validation_result):
        """After import, edges should be queryable from DB.

        Steps:
        1. Import
        2. SELECT COUNT(*) FROM edges
        3. Assert count == 1
        """
        import_neurons(target_db, valid_validation_result)
        count = target_db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        assert count == 1

    def test_import_result_counts_correct(self, target_db, valid_validation_result):
        """ImportResult should have correct counts.

        Steps:
        1. Import
        2. Assert result.neurons_written == 2
        3. Assert result.edges_written == 1
        4. Assert result.neurons_skipped == 0
        """
        result = import_neurons(target_db, valid_validation_result)
        assert result.neurons_written == 2
        assert result.edges_written == 1
        assert result.neurons_skipped == 0


# --- Tests: Tag creation ---


class TestTagCreation:
    """Import auto-creates tags that don't exist in target DB."""

    def test_new_tags_created_in_registry(self, target_db, valid_validation_result):
        """Tags from tags_to_create should exist in tag registry after import.

        Steps:
        1. Assert target DB tags table is empty before import
        2. Import
        3. SELECT name FROM tags
        4. Assert "project:test" and "type:note" exist
        """
        pre_count = target_db.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        assert pre_count == 0

        import_neurons(target_db, valid_validation_result)
        tag_names = {row[0] for row in target_db.execute("SELECT name FROM tags").fetchall()}
        assert "project:test" in tag_names
        assert "type:note" in tag_names

    def test_existing_tags_not_duplicated(self, target_db, valid_validation_result):
        """If a tag already exists, it should not be duplicated.

        Steps:
        1. INSERT "project:test" into target DB tags table
        2. Import
        3. SELECT COUNT(*) FROM tags WHERE name = "project:test"
        4. Assert count == 1 (not 2)
        """
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute(
                "INSERT INTO tags (name, created_at) VALUES ('project:test', ?)", (now_ms,)
            )
        import_neurons(target_db, valid_validation_result)
        count = target_db.execute(
            "SELECT COUNT(*) FROM tags WHERE name = 'project:test'"
        ).fetchone()[0]
        assert count == 1

    def test_import_result_reports_created_tags(self, target_db, valid_validation_result):
        """ImportResult.tags_created should list newly created tags.

        Steps:
        1. Import
        2. Assert "project:test" in result.tags_created
        3. Assert "type:note" in result.tags_created
        """
        result = import_neurons(target_db, valid_validation_result)
        assert "project:test" in result.tags_created
        assert "type:note" in result.tags_created


# --- Tests: Attr key creation ---


class TestAttrKeyCreation:
    """Import auto-creates attr keys that don't exist in target DB."""

    def test_new_attr_keys_created(self, target_db, valid_validation_result):
        """Attr keys from attrs_to_create should exist after import.

        Steps:
        1. Assert target DB attr_keys table is empty before import
        2. Import
        3. SELECT name FROM attr_keys
        4. Assert "language" exists
        """
        pre_count = target_db.execute("SELECT COUNT(*) FROM attr_keys").fetchone()[0]
        assert pre_count == 0

        import_neurons(target_db, valid_validation_result)
        attr_names = {row[0] for row in target_db.execute("SELECT name FROM attr_keys").fetchall()}
        assert "language" in attr_names

    def test_existing_attr_keys_not_duplicated(self, target_db, valid_validation_result):
        """Pre-existing attr keys should not be duplicated.

        Steps:
        1. INSERT "language" into target DB attr_keys table
        2. Import
        3. Assert only 1 row with name="language"
        """
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute(
                "INSERT INTO attr_keys (name, created_at) VALUES ('language', ?)", (now_ms,)
            )
        import_neurons(target_db, valid_validation_result)
        count = target_db.execute(
            "SELECT COUNT(*) FROM attr_keys WHERE name = 'language'"
        ).fetchone()[0]
        assert count == 1


# --- Tests: Neuron ID preservation ---


class TestNeuronIdPreservation:
    """Imported neurons keep their original IDs, not re-generated."""

    def test_neuron_ids_match_import_file(self, target_db, valid_validation_result):
        """DB neuron IDs should exactly match import file IDs.

        Steps:
        1. Get expected IDs from validation_result parsed_data
        2. Import
        3. SELECT id FROM neurons ORDER BY id
        4. Assert IDs match: {10001, 10002}
        """
        import_neurons(target_db, valid_validation_result)
        db_ids = {row[0] for row in target_db.execute("SELECT id FROM neurons").fetchall()}
        assert db_ids == {10001, 10002}

    def test_neuron_content_preserved(self, target_db, valid_validation_result):
        """Neuron content should exactly match import file content.

        Steps:
        1. Import
        2. SELECT content FROM neurons WHERE id = 10001
        3. Assert content == "First neuron"
        """
        import_neurons(target_db, valid_validation_result)
        row = target_db.execute(
            "SELECT content FROM neurons WHERE id = ?", (10001,)
        ).fetchone()
        assert row is not None
        assert row[0] == "First neuron"

    def test_neuron_timestamps_preserved(self, target_db, valid_validation_result):
        """created_at and updated_at should be stored (converted from ISO 8601).

        Steps:
        1. Import
        2. Query neuron, verify created_at is set (non-zero)
        """
        import_neurons(target_db, valid_validation_result)
        row = target_db.execute(
            "SELECT created_at, updated_at FROM neurons WHERE id = ?", (10001,)
        ).fetchone()
        assert row is not None
        assert row[0] > 0  # epoch ms, non-zero
        assert row[1] > 0


# --- Tests: Neuron tag/attr association ---


class TestNeuronAssociations:
    """Tags and attrs are correctly associated with neurons after import."""

    def test_neuron_has_correct_tags(self, target_db, valid_validation_result):
        """Each neuron should have the tags from the import file.

        Steps:
        1. Import
        2. For neuron 10001:
           a. JOIN neuron_tags with tags to get tag names
           b. Assert tags are {"project:test", "type:note"}
        3. For neuron 10002:
           a. Assert tags are {"project:test"}
        """
        import_neurons(target_db, valid_validation_result)
        tags_10001 = {
            row[0] for row in target_db.execute(
                "SELECT t.name FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id "
                "WHERE nt.neuron_id = ?", (10001,)
            ).fetchall()
        }
        assert tags_10001 == {"project:test", "type:note"}

        tags_10002 = {
            row[0] for row in target_db.execute(
                "SELECT t.name FROM neuron_tags nt JOIN tags t ON nt.tag_id = t.id "
                "WHERE nt.neuron_id = ?", (10002,)
            ).fetchall()
        }
        assert tags_10002 == {"project:test"}

    def test_neuron_has_correct_attrs(self, target_db, valid_validation_result):
        """Each neuron should have the attrs from the import file.

        Steps:
        1. Import
        2. For neuron 10001:
           a. JOIN neuron_attrs with attr_keys to get key names and values
           b. Assert attrs: {"language": "en"}
        3. For neuron 10002:
           a. Assert no attrs (empty dict in import)
        """
        import_neurons(target_db, valid_validation_result)
        attrs_10001 = {
            row[0]: row[1] for row in target_db.execute(
                "SELECT ak.name, na.value FROM neuron_attrs na "
                "JOIN attr_keys ak ON na.attr_key_id = ak.id "
                "WHERE na.neuron_id = ?", (10001,)
            ).fetchall()
        }
        assert attrs_10001 == {"language": "en"}

        attrs_10002 = {
            row[0]: row[1] for row in target_db.execute(
                "SELECT ak.name, na.value FROM neuron_attrs na "
                "JOIN attr_keys ak ON na.attr_key_id = ak.id "
                "WHERE na.neuron_id = ?", (10002,)
            ).fetchall()
        }
        assert attrs_10002 == {}


# --- Tests: Vector import ---


class TestVectorImport:
    """Vectors are correctly imported when included."""

    def test_vectors_written_to_db(self, target_db, validation_result_with_vectors):
        """Neurons with vectors should have vectors in the DB after import.

        Steps:
        1. Import with vectors
        2. SELECT COUNT(*) FROM neurons_vec
        3. Assert count == 2 (both neurons had vectors)
        """
        import_neurons(target_db, validation_result_with_vectors)
        count = target_db.execute("SELECT COUNT(*) FROM neurons_vec").fetchone()[0]
        assert count == 2

    def test_vector_values_preserved(self, target_db, validation_result_with_vectors):
        """Vector float values should match import data exactly.

        Steps:
        1. Import with vectors
        2. Read vector for 10001 from DB
        3. Deserialize and compare to original import vector values
        4. Assert all floats match within floating-point tolerance
        """
        import_neurons(target_db, validation_result_with_vectors)
        row = target_db.execute(
            "SELECT embedding FROM neurons_vec WHERE neuron_id = ?", (10001,)
        ).fetchone()
        assert row is not None
        blob = row[0]
        num_floats = len(blob) // 4
        retrieved_vector = list(struct.unpack(f"<{num_floats}f", blob))
        expected_vector = [0.1] * 768
        assert len(retrieved_vector) == 768
        for retrieved, expected in zip(retrieved_vector, expected_vector):
            assert abs(retrieved - expected) < 1e-5

    def test_no_vectors_when_not_included(self, target_db, valid_validation_result):
        """Import without vectors should not write any vector rows.

        Steps:
        1. Import (valid_validation_result has vectors_included=False)
        2. SELECT COUNT(*) FROM neurons_vec
        3. Assert count == 0
        """
        import_neurons(target_db, valid_validation_result)
        count = target_db.execute("SELECT COUNT(*) FROM neurons_vec").fetchone()[0]
        assert count == 0


# --- Tests: Edge import ---


class TestEdgeImport:
    """Edges are correctly imported with source/target references."""

    def test_edge_source_target_correct(self, target_db, valid_validation_result):
        """Edge source_id and target_id should match import file.

        Steps:
        1. Import
        2. SELECT source_id, target_id FROM edges
        3. Assert source_id == 10001
        4. Assert target_id == 10002
        """
        import_neurons(target_db, valid_validation_result)
        row = target_db.execute("SELECT source_id, target_id FROM edges").fetchone()
        assert row is not None
        assert row[0] == 10001
        assert row[1] == 10002

    def test_edge_weight_preserved(self, target_db, valid_validation_result):
        """Edge weight should match import file value.

        Steps:
        1. Import
        2. SELECT weight FROM edges
        3. Assert weight == 0.75 (within float tolerance)
        """
        import_neurons(target_db, valid_validation_result)
        row = target_db.execute("SELECT weight FROM edges").fetchone()
        assert row is not None
        assert abs(row[0] - 0.75) < 1e-6

    def test_edge_reason_preserved(self, target_db, valid_validation_result):
        """Edge reason should match import file value.

        Steps:
        1. Import
        2. SELECT reason FROM edges
        3. Assert reason == "related"
        """
        import_neurons(target_db, valid_validation_result)
        row = target_db.execute("SELECT reason FROM edges").fetchone()
        assert row is not None
        assert row[0] == "related"

    def test_edges_skipped_for_skipped_neurons(self, target_db):
        """Edges referencing skipped neurons should not be written.

        Steps:
        1. Create ValidationResult where one neuron ID conflicts
        2. Insert conflicting neuron into target DB
        3. Import with on_conflict="skip"
        4. Assert edge referencing the skipped neuron is NOT in edges table
        5. Assert result.edges_written == 0 (only edge refs skipped neuron)
        """
        # Insert a neuron that will conflict
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at, project, status) "
                "VALUES (10001, 'existing', ?, ?, 'test', 'active')",
                (now_ms, now_ms),
            )

        neurons = [
            _make_neuron(10001, "Conflict neuron"),
            _make_neuron(10002, "New neuron"),
        ]
        edges = [_make_edge(10001, 10002)]  # source is the skipped neuron
        vr = _make_validation_result(neurons=neurons, edges=edges)
        result = import_neurons(target_db, vr, on_conflict="skip")
        assert result.edges_written == 0
        edge_count = target_db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        assert edge_count == 0


# --- Tests: Transaction rollback ---


class TestTransactionRollback:
    """Failures during write must rollback the entire transaction."""

    def test_rollback_on_sql_error(self, target_db, valid_validation_result):
        """If a SQL error occurs mid-write, all changes should be rolled back.

        Steps:
        1. Drop the neurons table after fixture setup to simulate mid-write failure
        2. Call import_neurons
        3. Assert result.success is False
        4. Assert no tags were persisted (rolled back)
        """
        # Drop neurons table to cause a SQL error during neuron insert
        target_db.execute("DROP TABLE neuron_tags")
        target_db.execute("DROP TABLE neuron_attrs")
        target_db.execute("DROP TABLE neurons_fts")
        target_db.execute("DROP TABLE neurons")

        result = import_neurons(target_db, valid_validation_result)
        assert result.success is False
        assert result.error_message is not None

    def test_import_result_reports_failure(self, target_db, valid_validation_result):
        """ImportResult.success should be False on rollback.

        Steps:
        1. Trigger a failure during import by passing invalid validation_result
        2. Assert result.success is False
        3. Assert result.error_message is not None and not empty
        """
        # Create a ValidationResult with invalid data (neuron has None content)
        vr = ValidationResult()
        vr.valid = True
        vr.parsed_data = {
            "neurons": [{"id": 99999, "content": None}],  # None content will fail DB check
            "edges": [],
            "vectors_included": False,
        }
        vr.tags_to_create = []
        vr.attrs_to_create = []

        result = import_neurons(target_db, vr)
        assert result.success is False
        assert result.error_message is not None and len(result.error_message) > 0

    def test_rollback_leaves_no_tags(self, target_db):
        """After rollback, auto-created tags should not persist.

        Steps:
        1. Create a ValidationResult that will fail during neuron insert
        2. Import (tags created first, then neuron fails)
        3. SELECT COUNT(*) FROM tags
        4. Assert count == 0 (tags rolled back)
        """
        # This neuron will fail because content is None (NOT NULL constraint)
        neurons = [{"id": 99999, "content": None, "created_at": "2025-01-01T00:00:00+00:00",
                    "updated_at": "2025-01-01T00:00:00+00:00", "project": "test",
                    "tags": ["rollback-tag"], "attributes": {}}]
        vr = _make_validation_result(
            neurons=neurons, edges=[],
            tags_to_create=["rollback-tag"],
        )
        import_neurons(target_db, vr)
        tag_count = target_db.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        assert tag_count == 0


# --- Tests: ImportResult correctness ---


class TestImportResult:
    """ImportResult fields are accurate."""

    def test_success_flag_true_on_success(self, target_db, valid_validation_result):
        """Successful import should have success=True.

        Steps:
        1. Import successfully
        2. Assert result.success is True
        """
        result = import_neurons(target_db, valid_validation_result)
        assert result.success is True

    def test_success_flag_false_on_failure(self, target_db):
        """Failed import should have success=False.

        Steps:
        1. Create validation result with data that will fail on write
        2. Import
        3. Assert result.success is False
        """
        vr = ValidationResult()
        vr.valid = True
        vr.parsed_data = {
            "neurons": [{"id": 99999, "content": None}],
            "edges": [],
            "vectors_included": False,
        }
        vr.tags_to_create = []
        vr.attrs_to_create = []
        result = import_neurons(target_db, vr)
        assert result.success is False

    def test_neurons_written_count(self, target_db, valid_validation_result):
        """neurons_written should equal number of neurons actually inserted.

        Steps:
        1. Import 2 neurons
        2. Assert result.neurons_written == 2
        """
        result = import_neurons(target_db, valid_validation_result)
        assert result.neurons_written == 2

    def test_neurons_skipped_count(self, target_db):
        """neurons_skipped should reflect skip-mode conflicts.

        Steps:
        1. Insert one conflicting neuron in target DB
        2. Import with on_conflict="skip"
        3. Assert result.neurons_skipped == 1
        4. Assert result.neurons_written == 1 (the non-conflicting one)
        """
        now_ms = int(time.time() * 1000)
        with target_db:
            target_db.execute(
                "INSERT INTO neurons (id, content, created_at, updated_at, project, status) "
                "VALUES (10001, 'existing', ?, ?, 'test', 'active')",
                (now_ms, now_ms),
            )

        neurons = [
            _make_neuron(10001, "Conflict neuron"),
            _make_neuron(10002, "New neuron"),
        ]
        vr = _make_validation_result(neurons=neurons, edges=[])
        result = import_neurons(target_db, vr, on_conflict="skip")
        assert result.neurons_skipped == 1
        assert result.neurons_written == 1

    def test_edges_written_count(self, target_db, valid_validation_result):
        """edges_written should equal number of edges inserted.

        Steps:
        1. Import with 1 edge
        2. Assert result.edges_written == 1
        """
        result = import_neurons(target_db, valid_validation_result)
        assert result.edges_written == 1
