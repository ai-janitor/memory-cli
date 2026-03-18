# =============================================================================
# Module: test_neuron_prune_lru.py
# Purpose: Test LRU-based automatic archival via neuron_prune — stale neuron
#   detection, dry-run mode, priority ordering, restorability, freed weight.
# Organization:
#   1. Imports and fixtures
#   2. Basic prune tests (archives stale neurons)
#   3. Priority ordering tests (access_count=0 first)
#   4. Dry-run tests
#   5. Restorability tests
#   6. Freed weight calculation tests
#   7. Edge cases (no candidates, recently accessed safe)
# =============================================================================

from __future__ import annotations

import time
import pytest

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including v004 access tracking."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    apply_v004(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _insert_neuron(
    conn,
    content="test neuron",
    status="active",
    created_at_ms=None,
    last_accessed_at=None,
    access_count=0,
):
    """Insert a neuron with explicit access tracking fields. Returns neuron ID."""
    now_ms = created_at_ms or int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons
           (content, created_at, updated_at, project, source, status,
            last_accessed_at, access_count)
           VALUES (?, ?, ?, 'test-project', NULL, ?, ?, ?)""",
        (content, now_ms, now_ms, status, last_accessed_at, access_count),
    )
    conn.commit()
    return cursor.lastrowid


def _ms_days_ago(days: int) -> int:
    """Return millisecond timestamp for N days ago."""
    return int(time.time() * 1000) - (days * 86_400_000)


# -----------------------------------------------------------------------------
# Basic prune tests
# -----------------------------------------------------------------------------

class TestNeuronPruneBasic:
    """Test that prune archives stale neurons."""

    def test_prune_archives_old_unaccessed_neurons(self, migrated_conn):
        """Neurons created >30 days ago with no access should be archived."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        old_id = _insert_neuron(
            migrated_conn,
            content="old neuron",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30)

        assert report["pruned_count"] == 1
        assert report["dry_run"] is False
        # Verify neuron is actually archived
        row = migrated_conn.execute(
            "SELECT status FROM neurons WHERE id = ?", (old_id,)
        ).fetchone()
        assert row[0] == "archived"

    def test_prune_skips_recently_accessed_neurons(self, migrated_conn):
        """Neurons accessed within the window should NOT be pruned."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        _insert_neuron(
            migrated_conn,
            content="recently accessed",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=_ms_days_ago(5),  # accessed 5 days ago
            access_count=3,
        )

        report = neuron_prune(migrated_conn, days=30)

        assert report["candidate_count"] == 0
        assert report["pruned_count"] == 0

    def test_prune_skips_new_neurons_without_access(self, migrated_conn):
        """Neurons created recently (< days threshold) should NOT be pruned
        even if never accessed."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        _insert_neuron(
            migrated_conn,
            content="brand new neuron",
            created_at_ms=_ms_days_ago(5),  # only 5 days old
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30)

        assert report["candidate_count"] == 0

    def test_prune_skips_already_archived_neurons(self, migrated_conn):
        """Already-archived neurons should not be candidates."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        _insert_neuron(
            migrated_conn,
            content="already archived",
            status="archived",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30)

        assert report["candidate_count"] == 0

    def test_prune_configurable_days(self, migrated_conn):
        """--days flag controls the threshold."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        _insert_neuron(
            migrated_conn,
            content="10 days old",
            created_at_ms=_ms_days_ago(10),
            last_accessed_at=None,
            access_count=0,
        )

        # With 30-day window: not a candidate
        report_30 = neuron_prune(migrated_conn, days=30, dry_run=True)
        assert report_30["candidate_count"] == 0

        # With 7-day window: is a candidate
        report_7 = neuron_prune(migrated_conn, days=7, dry_run=True)
        assert report_7["candidate_count"] == 1


# -----------------------------------------------------------------------------
# Priority ordering tests
# -----------------------------------------------------------------------------

class TestNeuronPrunePriority:
    """Test that access_count=0 neurons are prioritized."""

    def test_zero_access_count_listed_first(self, migrated_conn):
        """Neurons with access_count=0 should appear before those with higher counts."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        accessed_id = _insert_neuron(
            migrated_conn,
            content="accessed but stale",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=_ms_days_ago(45),
            access_count=5,
        )
        never_id = _insert_neuron(
            migrated_conn,
            content="never accessed",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30, dry_run=True)

        assert report["candidate_count"] == 2
        # never-accessed should be first
        assert report["candidates"][0]["id"] == never_id
        assert report["candidates"][1]["id"] == accessed_id


# -----------------------------------------------------------------------------
# Dry-run tests
# -----------------------------------------------------------------------------

class TestNeuronPruneDryRun:
    """Test dry-run mode reports without archiving."""

    def test_dry_run_does_not_archive(self, migrated_conn):
        """Dry-run should report candidates but leave them active."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        nid = _insert_neuron(
            migrated_conn,
            content="stale neuron",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30, dry_run=True)

        assert report["dry_run"] is True
        assert report["candidate_count"] == 1
        assert report["pruned_count"] == 0
        assert report["freed_weight"] == 0.0
        # Neuron should still be active
        row = migrated_conn.execute(
            "SELECT status FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "active"

    def test_dry_run_returns_candidate_details(self, migrated_conn):
        """Dry-run candidates should include id, content_preview, access_count."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        _insert_neuron(
            migrated_conn,
            content="a stale memory about something important",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30, dry_run=True)

        candidate = report["candidates"][0]
        assert "id" in candidate
        assert "content_preview" in candidate
        assert "access_count" in candidate
        assert candidate["access_count"] == 0


# -----------------------------------------------------------------------------
# Restorability tests
# -----------------------------------------------------------------------------

class TestNeuronPruneRestorability:
    """Test that pruned neurons can be restored."""

    def test_pruned_neuron_restorable(self, migrated_conn):
        """Pruned (archived) neurons should be restorable via neuron_restore."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune
        from memory_cli.neuron.neuron_archive_and_restore import neuron_restore

        nid = _insert_neuron(
            migrated_conn,
            content="restorable content",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        neuron_prune(migrated_conn, days=30)

        # Should be archived
        row = migrated_conn.execute(
            "SELECT status FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "archived"

        # Restore it
        restored = neuron_restore(migrated_conn, nid)
        assert restored["status"] == "active"
        assert restored["content"] == "restorable content"


# -----------------------------------------------------------------------------
# Freed weight calculation tests
# -----------------------------------------------------------------------------

class TestNeuronPruneFreedWeight:
    """Test that freed weight is correctly calculated."""

    def test_freed_weight_sums_edge_weights(self, migrated_conn):
        """Freed weight should sum weights of edges touching pruned neurons."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        old_id = _insert_neuron(
            migrated_conn,
            content="old neuron with edges",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )
        other_id = _insert_neuron(
            migrated_conn,
            content="other neuron",
            created_at_ms=_ms_days_ago(5),  # recent, won't be pruned
        )

        now_ms = int(time.time() * 1000)
        # Edge from old -> other (weight 1.5)
        migrated_conn.execute(
            "INSERT INTO edges (source_id, target_id, weight, reason, created_at) VALUES (?, ?, 1.5, 'test', ?)",
            (old_id, other_id, now_ms),
        )
        # Edge from other -> old (weight 0.5)
        migrated_conn.execute(
            "INSERT INTO edges (source_id, target_id, weight, reason, created_at) VALUES (?, ?, 0.5, 'test', ?)",
            (other_id, old_id, now_ms),
        )
        migrated_conn.commit()

        report = neuron_prune(migrated_conn, days=30)

        assert report["pruned_count"] == 1
        assert report["freed_weight"] == pytest.approx(2.0)

    def test_no_edges_zero_freed_weight(self, migrated_conn):
        """Neurons with no edges should report 0 freed weight."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        _insert_neuron(
            migrated_conn,
            content="isolated neuron",
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30)

        assert report["pruned_count"] == 1
        assert report["freed_weight"] == 0.0


# -----------------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------------

class TestNeuronPruneEdgeCases:
    """Test edge cases for the prune command."""

    def test_no_candidates_returns_empty_report(self, migrated_conn):
        """No stale neurons -> report with zeros."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        report = neuron_prune(migrated_conn, days=30)

        assert report["pruned_count"] == 0
        assert report["candidate_count"] == 0
        assert report["candidates"] == []
        assert report["freed_weight"] == 0.0
        assert report["days"] == 30

    def test_prune_with_old_accessed_at_beyond_window(self, migrated_conn):
        """Neuron with last_accessed_at older than cutoff should be pruned."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        nid = _insert_neuron(
            migrated_conn,
            content="accessed long ago",
            created_at_ms=_ms_days_ago(90),
            last_accessed_at=_ms_days_ago(45),
            access_count=2,
        )

        report = neuron_prune(migrated_conn, days=30)

        assert report["pruned_count"] == 1
        row = migrated_conn.execute(
            "SELECT status FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "archived"

    def test_content_preview_truncation(self, migrated_conn):
        """Long content should be truncated to 80 chars + ellipsis in preview."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune

        long_content = "x" * 200
        _insert_neuron(
            migrated_conn,
            content=long_content,
            created_at_ms=_ms_days_ago(60),
            last_accessed_at=None,
            access_count=0,
        )

        report = neuron_prune(migrated_conn, days=30, dry_run=True)

        preview = report["candidates"][0]["content_preview"]
        assert len(preview) == 83  # 80 + "..."
        assert preview.endswith("...")

    def test_days_zero_raises_error(self, migrated_conn):
        """days=0 should raise NeuronPruneError to prevent wiping all neurons."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune, NeuronPruneError

        _insert_neuron(
            migrated_conn,
            content="should not be touched",
            created_at_ms=_ms_days_ago(5),
            last_accessed_at=None,
            access_count=0,
        )

        with pytest.raises(NeuronPruneError, match="--days must be >= 1"):
            neuron_prune(migrated_conn, days=0)

        # Verify the neuron was NOT touched
        row = migrated_conn.execute(
            "SELECT status FROM neurons WHERE content = 'should not be touched'"
        ).fetchone()
        assert row[0] == "active"

    def test_days_negative_raises_error(self, migrated_conn):
        """Negative days should raise NeuronPruneError."""
        from memory_cli.neuron.neuron_prune_by_lru_age import neuron_prune, NeuronPruneError

        with pytest.raises(NeuronPruneError, match="--days must be >= 1"):
            neuron_prune(migrated_conn, days=-5)
