# =============================================================================
# Module: test_graph_document_loader.py
# Purpose: Test the graph document loader YAML with ref resolution — focusing
#   on bug #25: _resolve_ref() must be scope-aware and reject cross-store edges.
# Rationale: Bug #25 — scoped handles like GLOBAL-94 were silently resolved to
#   bare int 94 regardless of the current store's scope. For cross-store edges
#   this produces wrong results silently. The fix raises a clear error when
#   the handle scope differs from the batch load's current_scope.
# Responsibility:
#   - Test that same-scope GLOBAL handles resolve to bare int (GLOBAL→GLOBAL OK)
#   - Test that same-scope LOCAL handles resolve to bare int (LOCAL→LOCAL OK)
#   - Test that cross-scope handles raise ValueError (LOCAL batch + GLOBAL ref)
#   - Test that cross-scope handles raise ValueError (GLOBAL batch + LOCAL ref)
#   - Test that bare integer refs bypass scope checking entirely
#   - Test that local ref labels bypass scope checking entirely
#   - Test that load_graph_document() surfaces cross-scope error in result.errors
#   - Test that load_graph_document() succeeds with same-scope handles end-to-end
# Organization:
#   1. Imports and fixtures
#   2. Unit tests for _resolve_ref() — scope-aware resolution
#   3. Integration tests for load_graph_document() — end-to-end scope propagation
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.export_import.graph_document_loader_yaml_with_ref_resolution import (
    _resolve_ref,
    load_graph_document,
)


# =============================================================================
# 1. FIXTURES
# =============================================================================

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema (needed for neuron_add + edge_add)."""
    sqlite_vec = pytest.importorskip(
        "sqlite_vec",
        reason="sqlite_vec required for full schema (vec0 table)",
    )
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


# =============================================================================
# 2. UNIT TESTS — _resolve_ref() scope-aware resolution
# =============================================================================

class TestResolveRefBareInt:
    """Bare integer refs always resolve without scope checking."""

    def test_bare_int_no_scope(self):
        assert _resolve_ref(42, {}) == 42

    def test_bare_int_with_local_scope(self):
        assert _resolve_ref(42, {}, current_scope="LOCAL") == 42

    def test_bare_int_with_global_scope(self):
        assert _resolve_ref(99, {}, current_scope="GLOBAL") == 99


class TestResolveRefLocalLabel:
    """Local ref labels (string keys in ref_map) always resolve without scope checking."""

    def test_local_label_no_scope(self):
        assert _resolve_ref("interview", {"interview": 7}) == 7

    def test_local_label_with_scope(self):
        assert _resolve_ref("payam", {"payam": 15}, current_scope="LOCAL") == 15

    def test_unknown_label_returns_none(self):
        assert _resolve_ref("missing", {}) is None


class TestResolveRefScopedHandle:
    """Scoped handle resolution — the core of bug #25."""

    def test_global_handle_no_scope_check_returns_bare_int(self):
        """When current_scope is None, scoped handles resolve without checking (legacy)."""
        assert _resolve_ref("GLOBAL-94", {}) == 94

    def test_local_handle_no_scope_check_returns_bare_int(self):
        assert _resolve_ref("LOCAL-7", {}) == 7

    def test_global_handle_same_scope_ok(self):
        """GLOBAL batch load + GLOBAL handle -> same scope -> bare int."""
        assert _resolve_ref("GLOBAL-94", {}, current_scope="GLOBAL") == 94

    def test_local_handle_same_scope_ok(self):
        """LOCAL batch load + LOCAL handle -> same scope -> bare int."""
        assert _resolve_ref("LOCAL-7", {}, current_scope="LOCAL") == 7

    def test_global_handle_cross_scope_raises(self):
        """LOCAL batch load + GLOBAL handle -> cross-store -> ValueError."""
        with pytest.raises(ValueError, match="Cross-store edges not yet supported"):
            _resolve_ref("GLOBAL-94", {}, current_scope="LOCAL")

    def test_local_handle_cross_scope_raises(self):
        """GLOBAL batch load + LOCAL handle -> cross-store -> ValueError."""
        with pytest.raises(ValueError, match="Cross-store edges not yet supported"):
            _resolve_ref("LOCAL-7", {}, current_scope="GLOBAL")

    def test_cross_scope_error_message_mentions_both_scopes(self):
        """Error message should name the handle scope and the current scope."""
        with pytest.raises(ValueError) as exc_info:
            _resolve_ref("GLOBAL-42", {}, current_scope="LOCAL")
        msg = str(exc_info.value)
        assert "GLOBAL" in msg
        assert "LOCAL" in msg

    def test_short_form_global_same_scope(self):
        """G-42 is equivalent to GLOBAL-42."""
        assert _resolve_ref("G-42", {}, current_scope="GLOBAL") == 42

    def test_short_form_global_cross_scope_raises(self):
        """G-42 with LOCAL scope triggers cross-store error."""
        with pytest.raises(ValueError, match="Cross-store edges not yet supported"):
            _resolve_ref("G-42", {}, current_scope="LOCAL")

    def test_short_form_local_same_scope(self):
        """L-7 is equivalent to LOCAL-7."""
        assert _resolve_ref("L-7", {}, current_scope="LOCAL") == 7

    def test_short_form_local_cross_scope_raises(self):
        """L-7 with GLOBAL scope triggers cross-store error."""
        with pytest.raises(ValueError, match="Cross-store edges not yet supported"):
            _resolve_ref("L-7", {}, current_scope="GLOBAL")

    def test_invalid_handle_returns_none(self):
        """Non-parseable strings that are not ref labels return None."""
        assert _resolve_ref("not-a-handle", {}) is None


# =============================================================================
# 3. INTEGRATION TESTS — load_graph_document() end-to-end
# =============================================================================

_SIMPLE_YAML = """
neurons:
  - ref: alpha
    content: "Alpha neuron content"
  - ref: beta
    content: "Beta neuron content"
edges:
  - from: alpha
    to: beta
    type: related
"""

_CROSS_SCOPE_YAML_TEMPLATE = """
neurons:
  - ref: alpha
    content: "Alpha neuron content"
edges:
  - from: alpha
    to: {cross_ref}
    type: related
"""


class TestLoadGraphDocumentScopeIntegration:
    """Integration tests confirming current_scope propagates through load_graph_document."""

    def test_local_refs_succeed_without_scope(self, migrated_conn):
        """Basic doc with only local refs works with no scope specified."""
        from unittest.mock import patch
        with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                   return_value="test-project"):
            result = load_graph_document(
                migrated_conn,
                "<inline>",
                yaml_content=_SIMPLE_YAML,
            )
        assert result.success, f"Expected success, got errors: {result.errors}"
        assert result.neurons_created == 2
        assert result.edges_created == 1

    def test_local_refs_succeed_with_local_scope(self, migrated_conn):
        """Basic doc with local refs works when current_scope='LOCAL'."""
        from unittest.mock import patch
        with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                   return_value="test-project"):
            result = load_graph_document(
                migrated_conn,
                "<inline>",
                yaml_content=_SIMPLE_YAML,
                current_scope="LOCAL",
            )
        assert result.success, f"Expected success, got errors: {result.errors}"
        assert result.neurons_created == 2
        assert result.edges_created == 1

    def test_cross_scope_global_ref_in_local_batch_fails(self, migrated_conn):
        """LOCAL batch load with GLOBAL-94 edge ref must fail with a clear error."""
        from unittest.mock import patch
        yaml_content = _CROSS_SCOPE_YAML_TEMPLATE.format(cross_ref="GLOBAL-94")
        with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                   return_value="test-project"):
            result = load_graph_document(
                migrated_conn,
                "<inline>",
                yaml_content=yaml_content,
                current_scope="LOCAL",
            )
        assert not result.success
        assert any("Cross-store edges not yet supported" in e for e in result.errors), (
            f"Expected cross-store error in: {result.errors}"
        )

    def test_cross_scope_local_ref_in_global_batch_fails(self, migrated_conn):
        """GLOBAL batch load with LOCAL-7 edge ref must fail with a clear error."""
        from unittest.mock import patch
        yaml_content = _CROSS_SCOPE_YAML_TEMPLATE.format(cross_ref="LOCAL-7")
        with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                   return_value="test-project"):
            result = load_graph_document(
                migrated_conn,
                "<inline>",
                yaml_content=yaml_content,
                current_scope="GLOBAL",
            )
        assert not result.success
        assert any("Cross-store edges not yet supported" in e for e in result.errors), (
            f"Expected cross-store error in: {result.errors}"
        )

    def test_same_scope_global_ref_in_global_batch_ok(self, migrated_conn):
        """GLOBAL batch + GLOBAL-N ref pointing to an existing neuron should work.

        We create a neuron first to get its ID, then reference it as GLOBAL-<id>.
        """
        from unittest.mock import patch
        with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                   return_value="test-project"):
            # First, create a standalone neuron to get a real ID
            from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add
            existing = neuron_add(
                migrated_conn, "Pre-existing global neuron", no_embed=True,
            )
            existing_id = existing["id"]

            # Now build a YAML referencing that neuron as GLOBAL-<id>
            yaml_content = f"""
neurons:
  - ref: alpha
    content: "Alpha neuron content (global scope test)"
edges:
  - from: alpha
    to: GLOBAL-{existing_id}
    type: links_to
"""
            result = load_graph_document(
                migrated_conn,
                "<inline>",
                yaml_content=yaml_content,
                current_scope="GLOBAL",
            )

        assert result.success, f"Expected success, got errors: {result.errors}"
        assert result.edges_created == 1
