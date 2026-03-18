# =============================================================================
# Module: test_neuron_add_parent_flag.py
# Purpose: Test the --parent flag behavior in handle_add (neuron noun handler).
#   Covers four bugs/features:
#   - R64/task-65: Edge direction should be parent->child, not child->parent
#   - R65/task-66: Failed --parent should not create orphan neuron
#   - R66/task-67: Response should include edges created by --parent
#   - R67/task-68: Warn when neuron added without --parent
# =============================================================================

from __future__ import annotations

import json
import pytest
from types import SimpleNamespace
from unittest.mock import patch

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v004(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


@pytest.fixture
def global_flags(migrated_conn):
    """Fake global_flags that routes to the in-memory connection."""
    return SimpleNamespace(
        db=None, config=None, scope=None, output="json",
        _test_conn=migrated_conn,
    )


def _call_handle_add(args, global_flags, migrated_conn):
    """Call handle_add with mocked connections and project detection."""
    with patch(
        "memory_cli.cli.noun_handlers.db_connection_from_global_flags.get_layered_connections",
        return_value=[(migrated_conn, "LOCAL")],
    ), patch(
        "memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
        return_value="test-project",
    ):
        from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_add
        return handle_add(args, global_flags)


def _extract_raw_id(scoped_id):
    """Extract raw integer ID from a scoped handle like 'LOCAL-2'."""
    s = str(scoped_id)
    if "-" in s:
        return int(s.split("-", 1)[1])
    return int(s)


def _create_parent_neuron(conn):
    """Create a parent neuron and return its ID."""
    with patch(
        "memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
        return_value="test-project",
    ):
        from memory_cli.neuron import neuron_add
        parent = neuron_add(conn, "Parent neuron", no_embed=True)
    return parent["id"]


# -----------------------------------------------------------------------------
# R64/task-65: Edge direction should be parent->child
# -----------------------------------------------------------------------------

class TestParentEdgeDirection:
    """Verify --parent creates edge from parent to child (not child to parent)."""

    def test_edge_direction_parent_to_child(self, migrated_conn, global_flags):
        """Edge should have source_id=parent, target_id=new_child."""
        parent_id = _create_parent_neuron(migrated_conn)

        result = _call_handle_add(
            ["Child neuron", "--parent", str(parent_id), "--edge-type", "child_of"],
            global_flags,
            migrated_conn,
        )
        assert result.status == "ok"
        # result.data["id"] is a scoped handle like "LOCAL-2"; extract raw int
        raw_child_id = _extract_raw_id(result.data["id"])

        # Verify edge direction: parent -> child
        edge = migrated_conn.execute(
            "SELECT source_id, target_id, reason FROM edges WHERE source_id = ? AND target_id = ?",
            (parent_id, raw_child_id),
        ).fetchone()
        assert edge is not None, "Expected edge from parent to child"
        assert edge["source_id"] == parent_id
        assert edge["target_id"] == raw_child_id
        assert edge["reason"] == "child_of"

    def test_no_reverse_edge_exists(self, migrated_conn, global_flags):
        """There should be no edge from child to parent (the old buggy direction)."""
        parent_id = _create_parent_neuron(migrated_conn)

        result = _call_handle_add(
            ["Child neuron", "--parent", str(parent_id)],
            global_flags,
            migrated_conn,
        )
        raw_child_id = _extract_raw_id(result.data["id"])

        # Verify NO edge in reverse direction
        reverse_edge = migrated_conn.execute(
            "SELECT * FROM edges WHERE source_id = ? AND target_id = ?",
            (raw_child_id, parent_id),
        ).fetchone()
        assert reverse_edge is None, "Should not have edge from child to parent"


# -----------------------------------------------------------------------------
# R65/task-66: Failed --parent should not create orphan neuron
# -----------------------------------------------------------------------------

class TestFailedParentNoOrphan:
    """Verify --parent to non-existent ID fails without creating a neuron."""

    def test_nonexistent_parent_returns_error(self, migrated_conn, global_flags):
        """Should return error status when parent neuron doesn't exist."""
        result = _call_handle_add(
            ["Orphan attempt", "--parent", "999"],
            global_flags,
            migrated_conn,
        )
        assert result.status == "error"
        assert "999" in result.error
        assert "not found" in result.error.lower()

    def test_nonexistent_parent_no_neuron_created(self, migrated_conn, global_flags):
        """Neuron count should not increase when parent doesn't exist."""
        count_before = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]

        _call_handle_add(
            ["Orphan attempt", "--parent", "999"],
            global_flags,
            migrated_conn,
        )

        count_after = migrated_conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        assert count_after == count_before, "No neuron should be created when --parent fails"


# -----------------------------------------------------------------------------
# R66/task-67: Response should include edges created by --parent
# -----------------------------------------------------------------------------

class TestResponseIncludesEdges:
    """Verify neuron add response includes edges when --parent is used."""

    def test_response_has_edges_with_parent(self, migrated_conn, global_flags):
        """Response data should contain non-empty edges list."""
        parent_id = _create_parent_neuron(migrated_conn)

        result = _call_handle_add(
            ["Child with edges", "--parent", str(parent_id), "--edge-type", "sourced_from"],
            global_flags,
            migrated_conn,
        )
        assert result.status == "ok"
        edges = result.data.get("edges", [])
        assert len(edges) > 0, "Response should include edges created by --parent"

    def test_response_edge_has_correct_info(self, migrated_conn, global_flags):
        """The edge in the response should reflect the correct direction and type."""
        parent_id = _create_parent_neuron(migrated_conn)

        result = _call_handle_add(
            ["Child detail", "--parent", str(parent_id), "--edge-type", "sourced_from"],
            global_flags,
            migrated_conn,
        )
        edges = result.data.get("edges", [])
        # The child neuron should see an incoming edge from parent
        incoming = [e for e in edges if e.get("direction") == "in"]
        assert len(incoming) == 1
        assert incoming[0]["source"] == parent_id
        assert incoming[0]["reason"] == "sourced_from"


# -----------------------------------------------------------------------------
# R67/task-68: Warn when neuron added without --parent
# -----------------------------------------------------------------------------

class TestOrphanWarning:
    """Verify warning is emitted when no --parent specified."""

    def test_no_parent_emits_warning(self, migrated_conn, global_flags):
        """Meta should contain warnings when --parent not provided."""
        result = _call_handle_add(
            ["Orphan neuron"],
            global_flags,
            migrated_conn,
        )
        assert result.status == "ok"
        assert result.meta is not None
        warnings = result.meta.get("warnings", [])
        assert len(warnings) > 0
        assert "parent" in warnings[0].lower() or "unconnected" in warnings[0].lower()

    def test_with_parent_no_warning(self, migrated_conn, global_flags):
        """Meta should NOT contain orphan warning when --parent is provided."""
        parent_id = _create_parent_neuron(migrated_conn)

        result = _call_handle_add(
            ["Connected neuron", "--parent", str(parent_id)],
            global_flags,
            migrated_conn,
        )
        assert result.status == "ok"
        # Either meta is None or warnings is empty
        if result.meta is not None:
            warnings = result.meta.get("warnings", [])
            assert len(warnings) == 0
