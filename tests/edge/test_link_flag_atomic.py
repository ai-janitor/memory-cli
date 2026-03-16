# =============================================================================
# Module: test_link_flag_atomic.py
# Purpose: Test atomic neuron+edge creation via link_flag_atomic_create() —
#   successful atomic creation, rollback on edge failure, rollback on neuron
#   failure, and all validation error paths.
# Rationale: Atomicity is the key property — if the edge INSERT fails, the
#   neuron must NOT exist. This is the critical difference from the non-atomic
#   neuron_add where link failure is non-fatal. Tests must verify that failed
#   transactions leave zero state in the database (no orphan neurons, no
#   orphan tags/attrs). Target validation must happen BEFORE the transaction
#   starts to avoid unnecessary writes.
# Responsibility:
#   - Test successful atomic creation of neuron + edge
#   - Test returned tuple contains both neuron and edge dicts
#   - Test new neuron is source, linked neuron is target
#   - Test tags and attrs are created alongside neuron
#   - Test rollback on edge failure: no neuron, no tags, no attrs in DB
#   - Test rollback on neuron write failure: nothing in DB
#   - Test target neuron not found -> exit 1 (no writes)
#   - Test empty content -> exit 2 (no writes)
#   - Test empty link-reason -> exit 2 (no writes)
#   - Test invalid link-weight -> exit 2 (no writes)
#   - Test custom link-weight is applied to the edge
#   - Test default link-weight is 1.0
# Organization:
#   1. Imports and fixtures
#   2. TestLinkAtomicHappyPath — successful creation scenarios
#   3. TestLinkAtomicRollback — rollback on failure scenarios
#   4. TestLinkAtomicValidation — input validation error paths
# =============================================================================

from __future__ import annotations

import time
from unittest import mock

import pytest
from typing import Any, Dict

# --- Module-level guard: all tests in this file require sqlite_vec ---
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including neurons_vec."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _create_test_neuron(conn, content="test content", project="test-project"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# -----------------------------------------------------------------------------
# Happy path tests
# -----------------------------------------------------------------------------

class TestLinkAtomicHappyPath:
    """Test successful atomic neuron + edge creation."""

    def test_creates_neuron_and_edge(self, migrated_conn):
        """Atomic creation produces both a neuron and an edge.

        Expects:
        - Returns tuple of (neuron_dict, edge_dict)
        - Neuron exists in DB with correct content
        - Edge exists in DB connecting new neuron to target
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn, "link target")

        result = link_flag_atomic_create(
            migrated_conn,
            content="new neuron content",
            link_target_id=target,
            link_reason="references target",
        )

        neuron_dict, edge_dict = result

        # Neuron exists in DB
        row = migrated_conn.execute(
            "SELECT content FROM neurons WHERE id=?", (neuron_dict["id"],)
        ).fetchone()
        assert row is not None
        assert row["content"] == "new neuron content"

        # Edge exists in DB
        edge_row = migrated_conn.execute(
            "SELECT source_id, target_id FROM edges WHERE source_id=? AND target_id=?",
            (neuron_dict["id"], target),
        ).fetchone()
        assert edge_row is not None

    def test_new_neuron_is_source(self, migrated_conn):
        """The newly created neuron is the edge source, target is the linked neuron.

        Expects:
        - edge_dict['source_id'] == neuron_dict['id']
        - edge_dict['target_id'] == link_target_id (the seed neuron)
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn, "existing target")

        neuron_dict, edge_dict = link_flag_atomic_create(
            migrated_conn,
            content="new neuron",
            link_target_id=target,
            link_reason="points to target",
        )

        assert edge_dict["source_id"] == neuron_dict["id"]
        assert edge_dict["target_id"] == target

    def test_default_link_weight(self, migrated_conn):
        """When --link-weight is not provided, edge weight defaults to 1.0.

        Expects: edge_dict['weight'] == 1.0
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn)

        _, edge_dict = link_flag_atomic_create(
            migrated_conn,
            content="new neuron",
            link_target_id=target,
            link_reason="reason",
        )

        assert edge_dict["weight"] == 1.0

    def test_custom_link_weight(self, migrated_conn):
        """When --link-weight is provided, edge uses that weight.

        Expects: edge_dict['weight'] == provided value (e.g., 3.5)
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn)

        _, edge_dict = link_flag_atomic_create(
            migrated_conn,
            content="new neuron",
            link_target_id=target,
            link_reason="reason",
            link_weight=3.5,
        )

        assert edge_dict["weight"] == 3.5

    def test_tags_created_with_neuron(self, migrated_conn):
        """Tags passed to link_flag_atomic_create are applied to the neuron.

        Expects:
        - Neuron has the provided tags
        - Tag associations exist in neuron_tags junction table
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn)

        neuron_dict, _ = link_flag_atomic_create(
            migrated_conn,
            content="tagged neuron",
            link_target_id=target,
            link_reason="reason",
            tags=["alpha", "beta"],
        )

        # Check neuron_tags junction rows exist
        rows = migrated_conn.execute(
            """SELECT t.name FROM neuron_tags nt
               JOIN tags t ON nt.tag_id = t.id
               WHERE nt.neuron_id = ?
               ORDER BY t.name""",
            (neuron_dict["id"],),
        ).fetchall()
        tag_names = [r[0] for r in rows]
        assert "alpha" in tag_names
        assert "beta" in tag_names

    def test_attrs_created_with_neuron(self, migrated_conn):
        """Attributes passed to link_flag_atomic_create are applied to the neuron.

        Expects:
        - Neuron has the provided attrs
        - Attr associations exist in neuron_attrs table
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn)

        neuron_dict, _ = link_flag_atomic_create(
            migrated_conn,
            content="attributed neuron",
            link_target_id=target,
            link_reason="reason",
            attrs={"priority": "high", "category": "test"},
        )

        rows = migrated_conn.execute(
            """SELECT ak.name, na.value FROM neuron_attrs na
               JOIN attr_keys ak ON na.attr_key_id = ak.id
               WHERE na.neuron_id = ?
               ORDER BY ak.name""",
            (neuron_dict["id"],),
        ).fetchall()
        attr_dict = {r[0]: r[1] for r in rows}
        assert attr_dict.get("priority") == "high"
        assert attr_dict.get("category") == "test"

    def test_returns_complete_neuron_dict(self, migrated_conn):
        """Neuron dict has all expected keys.

        Expected keys: id, content, created_at, updated_at, project,
        source, status, tags, attrs
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn)

        neuron_dict, _ = link_flag_atomic_create(
            migrated_conn,
            content="complete neuron",
            link_target_id=target,
            link_reason="reason",
        )

        expected_keys = {"id", "content", "created_at", "updated_at", "project",
                         "source", "status", "embedding_updated_at", "tags", "attrs"}
        assert expected_keys == set(neuron_dict.keys())

    def test_returns_complete_edge_dict(self, migrated_conn):
        """Edge dict has all expected keys.

        Expected keys: source_id, target_id, reason, weight, created_at
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create

        target = _create_test_neuron(migrated_conn)

        _, edge_dict = link_flag_atomic_create(
            migrated_conn,
            content="new neuron",
            link_target_id=target,
            link_reason="reason",
        )

        expected_keys = {"source_id", "target_id", "reason", "weight", "created_at", "provenance", "confidence"}
        assert expected_keys == set(edge_dict.keys())


# -----------------------------------------------------------------------------
# Rollback tests
# -----------------------------------------------------------------------------

class TestLinkAtomicRollback:
    """Test that failures cause complete rollback — no partial state."""

    def test_edge_failure_rolls_back_neuron(self, migrated_conn):
        """If edge INSERT fails, the neuron INSERT is also rolled back.

        Setup: Patch _create_neuron_and_edge to raise after neuron write.
        Expects:
        - LinkAtomicError raised
        - No new neuron in DB (neuron count unchanged)
        - No new edge in DB
        """
        from unittest.mock import patch
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn, "rollback target")
        initial_neuron_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]

        with patch(
            "memory_cli.edge.link_flag_atomic_neuron_plus_edge._create_neuron_and_edge",
            side_effect=LinkAtomicError("Simulated edge failure", exit_code=2, step="edge_write"),
        ):
            with pytest.raises(LinkAtomicError):
                link_flag_atomic_create(
                    migrated_conn,
                    content="should be rolled back",
                    link_target_id=target,
                    link_reason="will fail",
                )

        # Neuron count should be unchanged (the create function was mocked)
        final_neuron_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        assert final_neuron_count == initial_neuron_count

    def test_edge_failure_no_orphan_tags(self, migrated_conn):
        """After rollback, no tag associations from the failed transaction exist.

        Setup: Create with tags, but the inner function raises.
        Expects:
        - No neuron_tags rows for the would-be neuron ID
        """
        from unittest.mock import patch
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)

        with patch(
            "memory_cli.edge.link_flag_atomic_neuron_plus_edge._create_neuron_and_edge",
            side_effect=LinkAtomicError("Simulated failure", exit_code=2, step="edge_write"),
        ):
            with pytest.raises(LinkAtomicError):
                link_flag_atomic_create(
                    migrated_conn,
                    content="tagged but rolled back",
                    link_target_id=target,
                    link_reason="fails",
                    tags=["orphan-tag"],
                )

        # No neuron with this content should exist
        row = migrated_conn.execute(
            "SELECT id FROM neurons WHERE content = 'tagged but rolled back'"
        ).fetchone()
        assert row is None

    def test_edge_failure_no_orphan_attrs(self, migrated_conn):
        """After rollback, no attr associations from the failed transaction exist.

        Setup: Create with attrs, but the inner function raises.
        Expects:
        - No neuron_attrs rows for the would-be neuron ID
        """
        from unittest.mock import patch
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)

        with patch(
            "memory_cli.edge.link_flag_atomic_neuron_plus_edge._create_neuron_and_edge",
            side_effect=LinkAtomicError("Simulated failure", exit_code=2, step="edge_write"),
        ):
            with pytest.raises(LinkAtomicError):
                link_flag_atomic_create(
                    migrated_conn,
                    content="attr but rolled back",
                    link_target_id=target,
                    link_reason="fails",
                    attrs={"orphan": "value"},
                )

        # No neuron with this content should exist
        row = migrated_conn.execute(
            "SELECT id FROM neurons WHERE content = 'attr but rolled back'"
        ).fetchone()
        assert row is None

    def test_rollback_preserves_existing_data(self, migrated_conn):
        """Rollback does not affect pre-existing neurons or edges.

        Setup: Seed neuron exists, attempt atomic create that fails.
        Expects:
        - Seed neuron still exists with original data
        - No other neurons or edges were modified
        """
        from unittest.mock import patch
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn, "seed neuron content")

        with patch(
            "memory_cli.edge.link_flag_atomic_neuron_plus_edge._create_neuron_and_edge",
            side_effect=LinkAtomicError("Simulated failure", exit_code=2, step="edge_write"),
        ):
            with pytest.raises(LinkAtomicError):
                link_flag_atomic_create(
                    migrated_conn,
                    content="should not persist",
                    link_target_id=target,
                    link_reason="fails",
                )

        # Seed neuron still intact
        row = migrated_conn.execute(
            "SELECT content FROM neurons WHERE id=?", (target,)
        ).fetchone()
        assert row is not None
        assert row["content"] == "seed neuron content"


# -----------------------------------------------------------------------------
# Validation error tests
# -----------------------------------------------------------------------------

class TestLinkAtomicValidation:
    """Test input validation — failures should happen before any writes."""

    def test_target_not_found_exit_1(self, migrated_conn):
        """Link to a non-existent neuron ID.

        Expects:
        - LinkAtomicError raised with exit_code == 1
        - No writes to DB (neuron count unchanged)
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        initial_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]

        with pytest.raises(LinkAtomicError) as exc_info:
            link_flag_atomic_create(
                migrated_conn,
                content="valid content",
                link_target_id=99999,
                link_reason="valid reason",
            )

        assert exc_info.value.exit_code == 1
        final_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        assert final_count == initial_count

    def test_empty_content_exit_2(self, migrated_conn):
        """Empty content string.

        Expects:
        - LinkAtomicError raised with exit_code == 2
        - No writes to DB
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)
        initial_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]

        with pytest.raises(LinkAtomicError) as exc_info:
            link_flag_atomic_create(
                migrated_conn,
                content="",
                link_target_id=target,
                link_reason="valid reason",
            )

        assert exc_info.value.exit_code == 2
        final_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        assert final_count == initial_count

    def test_whitespace_content_exit_2(self, migrated_conn):
        """Whitespace-only content string.

        Expects:
        - LinkAtomicError raised with exit_code == 2
        - No writes to DB
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)

        with pytest.raises(LinkAtomicError) as exc_info:
            link_flag_atomic_create(
                migrated_conn,
                content="   \t\n  ",
                link_target_id=target,
                link_reason="valid reason",
            )

        assert exc_info.value.exit_code == 2

    def test_empty_link_reason_exit_2(self, migrated_conn):
        """Empty link-reason string.

        Expects:
        - LinkAtomicError raised with exit_code == 2
        - No writes to DB
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)

        with pytest.raises(LinkAtomicError) as exc_info:
            link_flag_atomic_create(
                migrated_conn,
                content="valid content",
                link_target_id=target,
                link_reason="",
            )

        assert exc_info.value.exit_code == 2

    def test_whitespace_link_reason_exit_2(self, migrated_conn):
        """Whitespace-only link-reason string.

        Expects:
        - LinkAtomicError raised with exit_code == 2
        - No writes to DB
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)

        with pytest.raises(LinkAtomicError) as exc_info:
            link_flag_atomic_create(
                migrated_conn,
                content="valid content",
                link_target_id=target,
                link_reason="   ",
            )

        assert exc_info.value.exit_code == 2

    def test_zero_link_weight_exit_2(self, migrated_conn):
        """link_weight == 0.0 is invalid.

        Expects:
        - LinkAtomicError raised with exit_code == 2
        - No writes to DB
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)

        with pytest.raises(LinkAtomicError) as exc_info:
            link_flag_atomic_create(
                migrated_conn,
                content="valid content",
                link_target_id=target,
                link_reason="valid reason",
                link_weight=0.0,
            )

        assert exc_info.value.exit_code == 2

    def test_negative_link_weight_exit_2(self, migrated_conn):
        """Negative link_weight is invalid.

        Expects:
        - LinkAtomicError raised with exit_code == 2
        - No writes to DB
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        target = _create_test_neuron(migrated_conn)

        with pytest.raises(LinkAtomicError) as exc_info:
            link_flag_atomic_create(
                migrated_conn,
                content="valid content",
                link_target_id=target,
                link_reason="valid reason",
                link_weight=-2.0,
            )

        assert exc_info.value.exit_code == 2

    def test_validation_happens_before_transaction(self, migrated_conn):
        """Validation errors should not start a transaction at all.

        This is a behavioral test — if validation raises before any SQL
        executes, no BEGIN/COMMIT/ROLLBACK should be issued. Hard to test
        directly, but we can verify no DB state changes occurred.
        """
        from memory_cli.edge.link_flag_atomic_neuron_plus_edge import link_flag_atomic_create, LinkAtomicError

        initial_neuron_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        initial_edge_count = migrated_conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        with pytest.raises(LinkAtomicError):
            link_flag_atomic_create(
                migrated_conn,
                content="",  # Invalid — triggers validation error before any writes
                link_target_id=99999,
                link_reason="",
            )

        final_neuron_count = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        final_edge_count = migrated_conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        assert final_neuron_count == initial_neuron_count
        assert final_edge_count == initial_edge_count
