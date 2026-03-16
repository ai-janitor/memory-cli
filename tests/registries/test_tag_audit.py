# =============================================================================
# Module: test_tag_audit.py
# Purpose: Test the tag_audit function — usage statistics, type pattern
#   classification, noise candidate identification, and sort order.
# =============================================================================

from __future__ import annotations

import sqlite3

import pytest

from memory_cli.registries.tag_registry_crud_normalize_autocreate import (
    tag_add,
    tag_audit,
)


# -----------------------------------------------------------------------------
# Fixtures — in-memory SQLite DB with tags, neuron_tags, and neurons tables.
# -----------------------------------------------------------------------------

@pytest.fixture
def conn():
    """Create an in-memory SQLite DB with tags, neuron_tags, and neurons tables."""
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE neuron_tags (
            neuron_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE neurons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            project TEXT NOT NULL DEFAULT 'test',
            source TEXT,
            status TEXT NOT NULL DEFAULT 'active'
        )
    """)
    yield c
    c.close()


def _add_neuron(conn, content="test neuron"):
    """Helper: insert a neuron and return its id."""
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project) VALUES (?, 0, 0, 'test')",
        (content,),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _link_tag(conn, neuron_id, tag_id):
    """Helper: insert a neuron_tags junction row."""
    conn.execute(
        "INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
        (neuron_id, tag_id),
    )


# =============================================================================
# TestTagAuditEmpty — empty database
# =============================================================================
class TestTagAuditEmpty:
    def test_empty_db_returns_zero_counts(self, conn):
        result = tag_audit(conn)
        assert result["total_tags"] == 0
        assert result["total_neurons"] == 0
        assert result["tags"] == []
        assert result["noise_candidates"] == []

    def test_tags_exist_but_no_neurons(self, conn):
        """Tags with zero usage still appear in the audit."""
        tag_add(conn, "orphan")
        result = tag_audit(conn)
        assert result["total_tags"] == 1
        assert result["total_neurons"] == 0
        assert result["tags"][0]["name"] == "orphan"
        assert result["tags"][0]["count"] == 0
        # count=0 is not noise (noise = count==1)
        assert result["noise_candidates"] == []


# =============================================================================
# TestTagAuditCounting — correct neuron counts per tag
# =============================================================================
class TestTagAuditCounting:
    def test_single_tag_single_neuron(self, conn):
        n1 = _add_neuron(conn)
        t = tag_add(conn, "python")
        _link_tag(conn, n1, t["id"])
        result = tag_audit(conn)
        assert result["total_tags"] == 1
        assert result["total_neurons"] == 1
        assert result["tags"][0]["count"] == 1

    def test_multiple_tags_varied_counts(self, conn):
        n1 = _add_neuron(conn, "a")
        n2 = _add_neuron(conn, "b")
        n3 = _add_neuron(conn, "c")
        t_popular = tag_add(conn, "popular")
        t_medium = tag_add(conn, "medium")
        t_rare = tag_add(conn, "rare")
        # popular: 3 neurons, medium: 2, rare: 1
        for n in [n1, n2, n3]:
            _link_tag(conn, n, t_popular["id"])
        for n in [n1, n2]:
            _link_tag(conn, n, t_medium["id"])
        _link_tag(conn, n1, t_rare["id"])

        result = tag_audit(conn)
        assert result["total_tags"] == 3
        assert result["total_neurons"] == 3
        # Sorted by count DESC
        assert result["tags"][0]["name"] == "popular"
        assert result["tags"][0]["count"] == 3
        assert result["tags"][1]["name"] == "medium"
        assert result["tags"][1]["count"] == 2
        assert result["tags"][2]["name"] == "rare"
        assert result["tags"][2]["count"] == 1


# =============================================================================
# TestTagAuditNoiseCandidates — singleton detection
# =============================================================================
class TestTagAuditNoiseCandidates:
    def test_noise_candidates_are_count_one(self, conn):
        n1 = _add_neuron(conn)
        n2 = _add_neuron(conn, "b")
        t_good = tag_add(conn, "good")
        t_noise = tag_add(conn, "noise")
        _link_tag(conn, n1, t_good["id"])
        _link_tag(conn, n2, t_good["id"])
        _link_tag(conn, n1, t_noise["id"])

        result = tag_audit(conn)
        assert "noise" in result["noise_candidates"]
        assert "good" not in result["noise_candidates"]

    def test_zero_count_not_noise(self, conn):
        """Tags with zero neurons are not noise candidates (noise = exactly 1)."""
        tag_add(conn, "unused")
        result = tag_audit(conn)
        assert result["noise_candidates"] == []


# =============================================================================
# TestTagAuditTypePatterns — structural classification
# =============================================================================
class TestTagAuditTypePatterns:
    def test_date_pattern(self, conn):
        tag_add(conn, "2025-03-16")
        result = tag_audit(conn)
        assert result["tags"][0]["type_pattern"] == "date"

    def test_user_pattern(self, conn):
        tag_add(conn, "python")
        result = tag_audit(conn)
        assert result["tags"][0]["type_pattern"] == "user"

    def test_mixed_patterns(self, conn):
        tag_add(conn, "2025-01-01")
        tag_add(conn, "my-project")
        tag_add(conn, "important note")
        result = tag_audit(conn)
        patterns = {t["name"]: t["type_pattern"] for t in result["tags"]}
        assert patterns["2025-01-01"] == "date"
        assert patterns["my-project"] == "user"
        assert patterns["important note"] == "user"


# =============================================================================
# TestTagAuditSortOrder — count DESC, then name ASC
# =============================================================================
class TestTagAuditSortOrder:
    def test_sort_by_count_desc_then_name_asc(self, conn):
        n1 = _add_neuron(conn)
        t_b = tag_add(conn, "beta")
        t_a = tag_add(conn, "alpha")
        # Both have count=1 — should sort alpha before beta
        _link_tag(conn, n1, t_b["id"])
        _link_tag(conn, n1, t_a["id"])

        result = tag_audit(conn)
        names = [t["name"] for t in result["tags"]]
        assert names == ["alpha", "beta"]
