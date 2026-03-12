# =============================================================================
# Module: auto_tag_capture_timestamp_and_project.py
# Purpose: Generate auto-tags for neuron creation — a timestamp tag (YYYY-MM-DD)
#   and a project tag (detected from git/cwd).
# Rationale: Every neuron gets automatic temporal and project context without
#   user effort. Timestamp tags enable time-range queries ("show me everything
#   from last week"). Project tags enable project-scoped filtering. Auto-tags
#   are mandatory — they cannot be skipped or removed by the user.
# Responsibility:
#   - Generate timestamp tag from current UTC date
#   - Generate project tag from project_detection module
#   - Merge auto-tags with user-provided tags
#   - Deduplicate after normalization
# Organization:
#   1. Imports
#   2. capture_auto_tags() — main entry point
#   3. _generate_timestamp_tag() — UTC date to YYYY-MM-DD string
#   4. _generate_project_tag() — delegate to project_detection
#   5. merge_and_deduplicate_tags() — combine user + auto tags
# =============================================================================

from __future__ import annotations

import datetime
from typing import List, Optional


def capture_auto_tags() -> List[str]:
    """Generate the set of auto-tags for a new neuron.

    Returns auto-tags that will be merged with user-provided tags.
    Currently generates two auto-tags:
    1. Timestamp tag: YYYY-MM-DD of current UTC date
    2. Project tag: detected from git remote / dir / cwd

    Logic flow:
    1. Generate timestamp tag via _generate_timestamp_tag()
    2. Generate project tag via _generate_project_tag()
    3. Return [timestamp_tag, project_tag]

    Returns:
        List of auto-tag name strings (always exactly 2 elements).
    """
    # auto_tags = []
    # auto_tags.append(_generate_timestamp_tag())
    # auto_tags.append(_generate_project_tag())
    # return auto_tags

    auto_tags = []
    auto_tags.append(_generate_timestamp_tag())
    auto_tags.append(_generate_project_tag())
    return auto_tags


def _generate_timestamp_tag() -> str:
    """Generate a timestamp tag from the current UTC date.

    Format: YYYY-MM-DD (e.g., "2026-03-11")

    Logic flow:
    1. Get current UTC datetime via datetime.datetime.now(datetime.timezone.utc)
    2. Format as YYYY-MM-DD string via .strftime("%Y-%m-%d")
    3. Return the formatted string

    Returns:
        Date string in YYYY-MM-DD format.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _generate_project_tag() -> str:
    """Generate a project tag by delegating to project_detection.

    Logic flow:
    1. Import detect_project from project_detection_git_or_cwd
    2. Call detect_project() to get the project name
    3. Return the project name as-is (already normalized by detect_project)

    Returns:
        Normalized project name string.
    """
    # from .project_detection_git_or_cwd import detect_project
    # return detect_project()

    from .project_detection_git_or_cwd import detect_project
    return detect_project()


def merge_and_deduplicate_tags(
    user_tags: Optional[List[str]],
    auto_tags: List[str],
) -> List[str]:
    """Merge user-provided tags with auto-tags and deduplicate.

    Auto-tags are always included — user cannot suppress them.
    Deduplication is case-insensitive (both user and auto tags will be
    normalized by the tag registry, but we deduplicate here to avoid
    redundant registry calls).

    Logic flow:
    1. Start with auto_tags as the base set
    2. If user_tags is not None:
       a. For each user_tag:
          - Normalize: strip whitespace, lowercase
          - If not already in the set (case-insensitive), add it
    3. Return deduplicated list

    Note: The tag registry will normalize again on insert, but deduplicating
    here avoids redundant INSERT OR IGNORE calls.

    Args:
        user_tags: Optional list of user-provided tag names (raw).
        auto_tags: List of auto-generated tag names (already normalized).

    Returns:
        Deduplicated list of tag names (auto-tags first, then user tags).
    """
    # --- Build deduplicated list ---
    # seen = set()
    # result = []
    # for tag in auto_tags:
    #     normalized = tag.strip().lower()
    #     if normalized not in seen:
    #         seen.add(normalized)
    #         result.append(normalized)
    # if user_tags:
    #     for tag in user_tags:
    #         normalized = tag.strip().lower()
    #         if normalized not in seen:
    #             seen.add(normalized)
    #             result.append(normalized)
    # return result

    seen = set()
    result = []
    for tag in auto_tags:
        normalized = tag.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    if user_tags:
        for tag in user_tags:
            normalized = tag.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
    return result
