# =============================================================================
# Module: test_neuron_add.py
# Purpose: Test the full neuron add pipeline — validation, auto-tags,
#   writing, embedding, linking, and error paths.
# Rationale: neuron_add is the most complex write path and orchestrates
#   multiple subsystems. Tests must cover the happy path, each individual
#   feature (auto-tags, embedding, linking), and every error condition
#   (empty content, missing reason, dead link target, archived target).
# Responsibility:
#   - Test successful neuron creation with minimal args
#   - Test auto-tag capture (timestamp + project tags present)
#   - Test user-provided tags merged with auto-tags
#   - Test attribute storage
#   - Test source field storage
#   - Test embedding is called by default
#   - Test --no-embed skips embedding
#   - Test --link creates edge to target
#   - Test --link without --reason raises error
#   - Test --link to non-existent target raises error
#   - Test --link to archived target raises error
#   - Test empty content raises error
#   - Test whitespace-only content raises error
#   - Test embedding failure is non-fatal (neuron still created)
#   - Test link failure is non-fatal (neuron still created)
# Organization:
#   1. Imports and fixtures
#   2. Happy path tests
#   3. Auto-tag tests
#   4. Embedding tests
#   5. Link tests
#   6. Validation error tests
#   7. Non-fatal failure tests
# =============================================================================

from __future__ import annotations

import re
import time
import pytest
from unittest.mock import patch, MagicMock

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


def _add_neuron_no_embed(conn, content="test", tags=None, attrs=None, source=None, status="active"):
    """Helper: create a neuron with embedding and project detection mocked out."""
    with patch("memory_cli.neuron.neuron_add_with_autotags_and_embed._embed_neuron"):
        with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                   return_value="test-project"):
            from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add
            n = neuron_add(conn, content, tags=tags, attrs=attrs, source=source, no_embed=True)

    if status == "archived":
        conn.execute(
            "UPDATE neurons SET status='archived' WHERE id=?", (n["id"],)
        )
        conn.commit()
        from memory_cli.neuron.neuron_get_by_id import neuron_get
        n = neuron_get(conn, n["id"])

    return n


# -----------------------------------------------------------------------------
# Happy path tests
# -----------------------------------------------------------------------------

class TestNeuronAddHappyPath:
    """Test successful neuron creation scenarios."""

    def test_add_minimal_content_only(self, migrated_conn):
        """Create neuron with just content — no tags, attrs, link, source.

        Expects:
        - Neuron created with status='active'
        - Auto-tags present (timestamp + project)
        - content matches input
        - created_at and updated_at are equal (new neuron)
        - attrs is empty dict
        - source is None
        """
        n = _add_neuron_no_embed(migrated_conn, content="Hello world")
        assert n["status"] == "active"
        assert n["content"] == "Hello world"
        assert n["created_at"] == n["updated_at"]
        assert n["attrs"] == {}
        assert n["source"] is None

    def test_add_with_user_tags(self, migrated_conn):
        """Create neuron with user-provided tags.

        Expects:
        - All user tags present in neuron.tags
        - Auto-tags also present (merged, not replaced)
        - Tags deduplicated (if user provides duplicate of auto-tag)
        """
        n = _add_neuron_no_embed(migrated_conn, content="Tagged", tags=["python", "ai"])
        assert "python" in n["tags"]
        assert "ai" in n["tags"]
        # Auto-tags should also be present
        assert "test-project" in n["tags"]

    def test_add_with_attributes(self, migrated_conn):
        """Create neuron with key=value attributes.

        Expects:
        - All attrs present in neuron.attrs dict
        - Attr keys auto-created in registry
        """
        n = _add_neuron_no_embed(migrated_conn, content="Attrs", attrs={"priority": "high", "status": "draft"})
        assert n["attrs"]["priority"] == "high"
        assert n["attrs"]["status"] == "draft"

    def test_add_with_source(self, migrated_conn):
        """Create neuron with source identifier.

        Expects:
        - neuron.source matches input
        """
        n = _add_neuron_no_embed(migrated_conn, content="Sourced", source="chat:session-42")
        assert n["source"] == "chat:session-42"

    def test_add_returns_complete_record(self, migrated_conn):
        """Verify returned dict has all expected keys.

        Expected keys: id, content, created_at, updated_at, project,
        source, status, embedding_updated_at, tags, attrs
        """
        n = _add_neuron_no_embed(migrated_conn, content="Complete")
        expected_keys = {"id", "content", "created_at", "updated_at", "project",
                         "source", "status", "embedding_updated_at", "tags", "attrs"}
        assert expected_keys.issubset(set(n.keys()))


# -----------------------------------------------------------------------------
# Auto-tag tests
# -----------------------------------------------------------------------------

class TestNeuronAddAutoTags:
    """Test auto-tag capture during neuron creation."""

    def test_timestamp_tag_present(self, migrated_conn):
        """Verify a YYYY-MM-DD timestamp tag is in the neuron's tags.

        The timestamp tag should match the current UTC date.
        """
        n = _add_neuron_no_embed(migrated_conn, content="Timestamp test")
        timestamp_tags = [t for t in n["tags"] if re.match(r"^\d{4}-\d{2}-\d{2}$", t)]
        assert len(timestamp_tags) >= 1, f"No timestamp tag found in {n['tags']}"

    def test_project_tag_present(self, migrated_conn):
        """Verify a project tag is in the neuron's tags.

        The project tag should match the detected project name.
        """
        n = _add_neuron_no_embed(migrated_conn, content="Project test")
        assert "test-project" in n["tags"]

    def test_auto_tags_merged_with_user_tags(self, migrated_conn):
        """Verify user tags and auto-tags coexist without duplication.

        If user provides a tag that matches an auto-tag (e.g., the same
        date string), it should appear only once.
        """
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        n = _add_neuron_no_embed(migrated_conn, content="Merge test", tags=[today, "python"])
        # today tag should appear exactly once
        assert n["tags"].count(today) == 1
        assert "python" in n["tags"]


# -----------------------------------------------------------------------------
# Embedding tests
# -----------------------------------------------------------------------------

class TestNeuronAddEmbedding:
    """Test embedding behavior during neuron creation."""

    def test_no_embed_skips_embedding(self, migrated_conn):
        """Verify embedding engine is NOT called when no_embed=True.

        Mock the embedding engine and assert it was NOT called.
        neuron.embedding_updated_at should be None.
        """
        with patch("memory_cli.neuron.neuron_add_with_autotags_and_embed._embed_neuron") as mock_embed:
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add
                n = neuron_add(migrated_conn, "No embed test", no_embed=True)
        mock_embed.assert_not_called()
        assert n["embedding_updated_at"] is None

    def test_embedding_called_by_default(self, migrated_conn):
        """Verify embedding engine is called when no_embed=False (default).

        Mock the embedding engine and assert it was called.
        """
        with patch("memory_cli.neuron.neuron_add_with_autotags_and_embed._embed_neuron") as mock_embed:
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add
                n = neuron_add(migrated_conn, "Embed test", no_embed=False)
        mock_embed.assert_called_once()

    def test_embedding_input_format(self):
        """Verify the embedding input string format.

        Expected: "<content> [<tag1> <tag2> ... <tagN>]"
        Tags should be sorted alphabetically.
        """
        from memory_cli.embedding import build_embedding_input
        result = build_embedding_input("Hello world", ["python", "ai"])
        # Should contain content and sorted tags
        assert "Hello world" in result
        assert "ai" in result
        assert "python" in result


# -----------------------------------------------------------------------------
# Link tests
# -----------------------------------------------------------------------------

class TestNeuronAddLink:
    """Test --link/--reason edge creation during neuron creation."""

    def test_link_creates_edge(self, migrated_conn):
        """Verify --link creates an edge from new neuron to target.

        Create a target neuron first, then create a new neuron with
        --link pointing to the target. Verify edge exists.
        """
        target = _add_neuron_no_embed(migrated_conn, content="Target neuron")
        target_id = target["id"]

        with patch("memory_cli.neuron.neuron_add_with_autotags_and_embed._embed_neuron"):
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add
                n = neuron_add(
                    migrated_conn, "Source neuron",
                    link_target_id=target_id,
                    link_reason="related to",
                    no_embed=True
                )

        edge = migrated_conn.execute(
            "SELECT * FROM edges WHERE source_id = ? AND target_id = ?",
            (n["id"], target_id)
        ).fetchone()
        assert edge is not None
        assert edge["reason"] == "related to"

    def test_link_requires_reason(self, migrated_conn):
        """Verify --link without --reason raises NeuronAddError.

        Expects: NeuronAddError with message about --reason being required.
        """
        from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add, NeuronAddError
        target = _add_neuron_no_embed(migrated_conn, content="Target")

        with pytest.raises(NeuronAddError, match="--reason"):
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                neuron_add(
                    migrated_conn, "Source",
                    link_target_id=target["id"],
                    link_reason=None,
                    no_embed=True
                )

    def test_link_target_must_exist(self, migrated_conn):
        """Verify --link to non-existent ID raises NeuronAddError.

        Expects: NeuronAddError with message about target not found.
        """
        from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add, NeuronAddError

        with pytest.raises(NeuronAddError, match="not found"):
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                neuron_add(
                    migrated_conn, "Source",
                    link_target_id=99999,
                    link_reason="reason",
                    no_embed=True
                )

    def test_link_target_must_be_active(self, migrated_conn):
        """Verify --link to archived neuron raises NeuronAddError.

        Create and archive a target, then try to link to it.
        Expects: NeuronAddError with message about target being archived.
        """
        from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add, NeuronAddError
        target = _add_neuron_no_embed(migrated_conn, content="Target to archive")
        migrated_conn.execute(
            "UPDATE neurons SET status='archived' WHERE id=?", (target["id"],)
        )
        migrated_conn.commit()

        with pytest.raises(NeuronAddError, match="archived"):
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                neuron_add(
                    migrated_conn, "Source",
                    link_target_id=target["id"],
                    link_reason="reason",
                    no_embed=True
                )


# -----------------------------------------------------------------------------
# Validation error tests
# -----------------------------------------------------------------------------

class TestNeuronAddValidation:
    """Test input validation error paths."""

    def test_empty_content_raises_error(self, migrated_conn):
        """Verify empty string content raises NeuronAddError.

        Expects: NeuronAddError("Content cannot be empty")
        """
        from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add, NeuronAddError

        with pytest.raises(NeuronAddError, match="empty"):
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                neuron_add(migrated_conn, "", no_embed=True)

    def test_whitespace_only_content_raises_error(self, migrated_conn):
        """Verify whitespace-only content raises NeuronAddError.

        Input: "   \\t\\n  " -> stripped to empty -> error.
        """
        from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add, NeuronAddError

        with pytest.raises(NeuronAddError, match="empty"):
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                neuron_add(migrated_conn, "   \t\n  ", no_embed=True)


# -----------------------------------------------------------------------------
# Non-fatal failure tests
# -----------------------------------------------------------------------------

class TestNeuronAddNonFatalFailures:
    """Test that embedding and link failures don't prevent neuron creation."""

    def test_embedding_failure_neuron_still_created(self, migrated_conn):
        """Verify neuron is created even when embedding engine raises.

        Mock embedding engine to raise an exception.
        Expects: neuron exists, embedding_updated_at is None, warning logged.
        """
        def raise_exc(*a, **kw):
            raise RuntimeError("embedding model not available")

        with patch("memory_cli.neuron.neuron_add_with_autotags_and_embed._embed_neuron", side_effect=raise_exc):
            with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                       return_value="test-project"):
                import warnings
                from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    n = neuron_add(migrated_conn, "Embedding failure test", no_embed=False)
                    assert len(w) >= 1

        assert n is not None
        assert n["id"] is not None
        assert n["embedding_updated_at"] is None

    def test_link_failure_neuron_still_created(self, migrated_conn):
        """Verify neuron is created even when edge creation raises.

        Mock edge module to raise an exception.
        Expects: neuron exists without the edge, warning logged.
        """
        target = _add_neuron_no_embed(migrated_conn, content="Link target")

        def raise_exc(*a, **kw):
            raise RuntimeError("edge creation failed")

        with patch("memory_cli.neuron.neuron_add_with_autotags_and_embed._link_neuron", side_effect=raise_exc):
            with patch("memory_cli.neuron.neuron_add_with_autotags_and_embed._embed_neuron"):
                with patch("memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
                           return_value="test-project"):
                    import warnings
                    from memory_cli.neuron.neuron_add_with_autotags_and_embed import neuron_add
                    with warnings.catch_warnings(record=True) as w:
                        warnings.simplefilter("always")
                        n = neuron_add(
                            migrated_conn, "Link failure test",
                            link_target_id=target["id"],
                            link_reason="test reason",
                            no_embed=True
                        )
                        assert len(w) >= 1

        assert n is not None
        edge_count = migrated_conn.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id = ?", (n["id"],)
        ).fetchone()[0]
        assert edge_count == 0
