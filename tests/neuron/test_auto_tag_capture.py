# =============================================================================
# Module: test_auto_tag_capture.py
# Purpose: Test auto-tag generation — timestamp tag format, project tag
#   generation, merging with user tags, and deduplication.
# Rationale: Auto-tags are mandatory on every neuron. The timestamp format
#   must be exact (YYYY-MM-DD) for time-range queries to work. The merge
#   and deduplication logic must handle edge cases like user providing the
#   same tag as an auto-tag, case variations, and empty user tag lists.
# Responsibility:
#   - Test timestamp tag format is YYYY-MM-DD
#   - Test timestamp tag matches current UTC date
#   - Test project tag is generated from project_detection
#   - Test capture_auto_tags returns exactly 2 tags
#   - Test merge_and_deduplicate_tags combines correctly
#   - Test deduplication is case-insensitive
#   - Test user tag matching auto-tag is deduplicated
#   - Test None user tags handled correctly
#   - Test empty user tags list handled correctly
# Organization:
#   1. Imports and fixtures
#   2. Timestamp tag tests
#   3. Project tag tests
#   4. capture_auto_tags integration tests
#   5. merge_and_deduplicate_tags tests
# =============================================================================

from __future__ import annotations

import datetime
import re
import pytest

from memory_cli.neuron.auto_tag_capture_timestamp_and_project import (
    capture_auto_tags,
    _generate_timestamp_tag,
    _generate_project_tag,
    merge_and_deduplicate_tags,
)


# -----------------------------------------------------------------------------
# Timestamp tag tests
# -----------------------------------------------------------------------------

class TestTimestampTag:
    """Test timestamp auto-tag generation."""

    def test_timestamp_tag_format(self):
        """Verify timestamp tag matches YYYY-MM-DD regex.

        Pattern: 4 digits, dash, 2 digits, dash, 2 digits.
        """
        tag = _generate_timestamp_tag()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", tag), f"Tag '{tag}' does not match YYYY-MM-DD"

    def test_timestamp_tag_matches_utc_date(self, monkeypatch):
        """Verify timestamp tag matches current UTC date.

        Freeze time and verify the tag matches the frozen date.
        """
        frozen_dt = datetime.datetime(2026, 3, 11, 14, 30, 0, tzinfo=datetime.timezone.utc)

        class FakeDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen_dt

        monkeypatch.setattr(
            "memory_cli.neuron.auto_tag_capture_timestamp_and_project.datetime.datetime",
            FakeDatetime
        )
        tag = _generate_timestamp_tag()
        assert tag == "2026-03-11"

    def test_timestamp_tag_is_string(self):
        """Verify timestamp tag is a plain string, not a date object."""
        tag = _generate_timestamp_tag()
        assert isinstance(tag, str)


# -----------------------------------------------------------------------------
# Project tag tests
# -----------------------------------------------------------------------------

class TestProjectTag:
    """Test project auto-tag generation."""

    def test_project_tag_from_detection(self, monkeypatch):
        """Verify project tag delegates to project_detection module.

        Mock detect_project() and verify the returned tag matches.
        """
        monkeypatch.setattr(
            "memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
            lambda: "mocked-project"
        )
        # _generate_project_tag is patched at module level, so capture_auto_tags
        # calls the mock. We also test directly:
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.detect_project",
            lambda: "direct-project"
        )
        tag = _generate_project_tag()
        assert tag == "direct-project"

    def test_project_tag_is_normalized(self, monkeypatch):
        """Verify project tag is lowercase, [a-z0-9_-] only.

        The project_detection module handles normalization, but
        verify the output format here.
        """
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.detect_project",
            lambda: "test-project"
        )
        tag = _generate_project_tag()
        assert re.match(r"^[a-z0-9_-]+$", tag), f"Tag '{tag}' not normalized"


# -----------------------------------------------------------------------------
# capture_auto_tags integration tests
# -----------------------------------------------------------------------------

class TestCaptureAutoTags:
    """Test the capture_auto_tags() entry point."""

    def test_returns_exactly_two_tags(self, monkeypatch):
        """Verify capture_auto_tags always returns a list of exactly 2."""
        monkeypatch.setattr(
            "memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
            lambda: "test-project"
        )
        tags = capture_auto_tags()
        assert len(tags) == 2

    def test_first_tag_is_timestamp(self, monkeypatch):
        """Verify first element is the timestamp tag."""
        monkeypatch.setattr(
            "memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
            lambda: "test-project"
        )
        tags = capture_auto_tags()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", tags[0])

    def test_second_tag_is_project(self, monkeypatch):
        """Verify second element is the project tag."""
        monkeypatch.setattr(
            "memory_cli.neuron.auto_tag_capture_timestamp_and_project._generate_project_tag",
            lambda: "test-project"
        )
        tags = capture_auto_tags()
        assert tags[1] == "test-project"


# -----------------------------------------------------------------------------
# merge_and_deduplicate_tags tests
# -----------------------------------------------------------------------------

class TestMergeAndDeduplicateTags:
    """Test merging user tags with auto-tags."""

    def test_auto_tags_always_included(self):
        """Verify auto-tags are present in output regardless of user tags."""
        auto_tags = ["2026-03-11", "my-project"]
        result = merge_and_deduplicate_tags(None, auto_tags)
        assert "2026-03-11" in result
        assert "my-project" in result

    def test_user_tags_appended_after_auto_tags(self):
        """Verify user tags come after auto-tags in the output list."""
        auto_tags = ["2026-03-11", "my-project"]
        user_tags = ["python", "ai"]
        result = merge_and_deduplicate_tags(user_tags, auto_tags)
        # Auto-tags must come first
        assert result[0] == "2026-03-11"
        assert result[1] == "my-project"
        # User tags must be present
        assert "python" in result
        assert "ai" in result

    def test_duplicate_user_tag_deduplicated(self):
        """Verify duplicate user tag (matching auto-tag) is removed.

        If user provides "2026-03-11" and auto-tag is "2026-03-11",
        output should contain it only once.
        """
        auto_tags = ["2026-03-11", "my-project"]
        user_tags = ["2026-03-11", "python"]
        result = merge_and_deduplicate_tags(user_tags, auto_tags)
        assert result.count("2026-03-11") == 1

    def test_case_insensitive_deduplication(self):
        """Verify deduplication is case-insensitive.

        If auto-tag is "test-project" and user provides "Test-Project",
        only one should appear.
        """
        auto_tags = ["2026-03-11", "test-project"]
        user_tags = ["Test-Project", "python"]
        result = merge_and_deduplicate_tags(user_tags, auto_tags)
        # "test-project" should appear exactly once (normalized form)
        lower_result = [t.lower() for t in result]
        assert lower_result.count("test-project") == 1

    def test_none_user_tags_handled(self):
        """Verify None user_tags returns just auto-tags."""
        auto_tags = ["2026-03-11", "my-project"]
        result = merge_and_deduplicate_tags(None, auto_tags)
        assert result == ["2026-03-11", "my-project"]

    def test_empty_user_tags_handled(self):
        """Verify empty list user_tags returns just auto-tags."""
        auto_tags = ["2026-03-11", "my-project"]
        result = merge_and_deduplicate_tags([], auto_tags)
        assert result == ["2026-03-11", "my-project"]

    def test_user_tags_whitespace_stripped(self):
        """Verify user tags are stripped of whitespace during merge.

        "  my-tag  " should become "my-tag".
        """
        auto_tags = ["2026-03-11", "my-project"]
        user_tags = ["  my-tag  ", " python "]
        result = merge_and_deduplicate_tags(user_tags, auto_tags)
        assert "my-tag" in result
        assert "python" in result
        # Verify whitespace-padded versions are NOT in the result
        assert "  my-tag  " not in result

    def test_result_is_list(self):
        """Verify result is a list type."""
        result = merge_and_deduplicate_tags(["a"], ["b", "c"])
        assert isinstance(result, list)
