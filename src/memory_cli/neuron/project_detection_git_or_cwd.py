# =============================================================================
# Module: project_detection_git_or_cwd.py
# Purpose: Detect the current project name from git remote URL, git directory
#   name, current working directory, or fall back to "unknown".
# Rationale: Every neuron is tagged with a project for scoped filtering.
#   Detection must be automatic (no user configuration) and deterministic.
#   Git remote is the strongest signal (same project name across clones),
#   followed by git dir name, then cwd basename. The fallback chain ensures
#   a project name is always available.
# Responsibility:
#   - Detect project name via 4-level fallback chain
#   - Normalize project name: lowercase, only [a-z0-9_-]
#   - Handle edge cases: bare repos, file:// URLs, nested dirs, no cwd
# Organization:
#   1. Imports
#   2. Constants (normalization regex)
#   3. detect_project() — main entry point
#   4. _from_git_remote() — extract repo name from git remote URL
#   5. _from_git_dir() — use git directory basename
#   6. _from_cwd() — use current working directory basename
#   7. _normalize_project_name() — lowercase + character filter
#   8. _extract_repo_name_from_url() — parse git remote URL formats
# =============================================================================

from __future__ import annotations

import os
import re
import subprocess
from typing import Optional


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
FALLBACK_PROJECT = "unknown"
# Only allow lowercase alphanumeric, hyphens, and underscores
PROJECT_NAME_PATTERN = re.compile(r"[^a-z0-9_-]")


def detect_project() -> str:
    """Detect the current project name via a 4-level fallback chain.

    Detection priority:
    1. Git remote URL -> extract repo name (strip .git suffix)
    2. No remote but .git exists -> git directory basename
    3. No git -> current working directory basename
    4. Can't determine cwd -> "unknown"

    Each level returns a normalized name. If a level fails or returns empty,
    the next level is tried.

    Returns:
        Normalized project name string (lowercase, [a-z0-9_-] only).
        Always returns a non-empty string (worst case: "unknown").
    """
    # --- Level 1: Git remote ---
    # result = _from_git_remote()
    # if result: return result

    # --- Level 2: Git directory ---
    # result = _from_git_dir()
    # if result: return result

    # --- Level 3: Current working directory ---
    # result = _from_cwd()
    # if result: return result

    # --- Level 4: Fallback ---
    # return FALLBACK_PROJECT

    pass


def _from_git_remote() -> Optional[str]:
    """Try to extract project name from git remote origin URL.

    Logic flow:
    1. Run: git remote get-url origin
       - subprocess.run with capture_output=True, text=True, timeout=5
       - On failure (non-zero exit, exception) -> return None
    2. Parse the URL via _extract_repo_name_from_url()
       - Handles SSH (git@host:user/repo.git), HTTPS, file:// formats
    3. Normalize via _normalize_project_name()
    4. Return normalized name, or None if empty

    Edge cases:
    - No git repo -> subprocess fails -> None
    - Git repo but no remote -> subprocess fails -> None
    - Remote URL is unusual format -> extraction may fail -> None

    Returns:
        Normalized project name, or None if detection fails.
    """
    # --- Run git command ---
    # try:
    #     result = subprocess.run(
    #         ["git", "remote", "get-url", "origin"],
    #         capture_output=True, text=True, timeout=5
    #     )
    #     if result.returncode != 0: return None
    #     url = result.stdout.strip()
    # except (subprocess.SubprocessError, FileNotFoundError, OSError):
    #     return None

    # --- Extract repo name ---
    # repo_name = _extract_repo_name_from_url(url)
    # if not repo_name: return None

    # --- Normalize ---
    # return _normalize_project_name(repo_name)

    pass


def _from_git_dir() -> Optional[str]:
    """Try to extract project name from git repository root directory name.

    Logic flow:
    1. Run: git rev-parse --show-toplevel
       - On failure -> return None (not in a git repo)
    2. Extract basename of the returned path
    3. Normalize via _normalize_project_name()
    4. Return normalized name, or None if empty

    This handles the case where there's a .git directory but no remote
    configured (e.g., a new local repo).

    Returns:
        Normalized project name, or None if detection fails.
    """
    # --- Run git command ---
    # try:
    #     result = subprocess.run(
    #         ["git", "rev-parse", "--show-toplevel"],
    #         capture_output=True, text=True, timeout=5
    #     )
    #     if result.returncode != 0: return None
    #     git_root = result.stdout.strip()
    # except (subprocess.SubprocessError, FileNotFoundError, OSError):
    #     return None

    # --- Extract basename and normalize ---
    # basename = os.path.basename(git_root)
    # if not basename: return None
    # return _normalize_project_name(basename)

    pass


def _from_cwd() -> Optional[str]:
    """Try to extract project name from current working directory basename.

    Logic flow:
    1. Get cwd via os.getcwd()
       - On OSError (deleted cwd, permissions) -> return None
    2. Extract basename
    3. Normalize via _normalize_project_name()
    4. Return normalized name, or None if empty

    Edge cases:
    - Root directory "/" -> basename is empty string -> return None
    - cwd deleted while process is running -> OSError -> return None

    Returns:
        Normalized project name, or None if detection fails.
    """
    # --- Get cwd ---
    # try:
    #     cwd = os.getcwd()
    # except OSError:
    #     return None

    # --- Extract basename and normalize ---
    # basename = os.path.basename(cwd)
    # if not basename: return None
    # return _normalize_project_name(basename)

    pass


def _normalize_project_name(raw_name: str) -> Optional[str]:
    """Normalize a project name: lowercase, only [a-z0-9_-].

    Normalization rules:
    1. Convert to lowercase
    2. Replace any character not in [a-z0-9_-] with empty string
    3. Strip leading/trailing hyphens and underscores
    4. If result is empty -> return None

    Examples:
        "My-Project" -> "my-project"
        "foo.bar_baz" -> "foobar_baz"  (dot removed)
        "hello world!" -> "helloworld"  (space and ! removed)
        "..." -> None  (all characters removed)

    Args:
        raw_name: Raw project name string.

    Returns:
        Normalized name, or None if empty after normalization.
    """
    # --- Normalize ---
    # lowered = raw_name.lower()
    # cleaned = PROJECT_NAME_PATTERN.sub("", lowered)
    # stripped = cleaned.strip("-_")
    # return stripped if stripped else None

    pass


def _extract_repo_name_from_url(url: str) -> Optional[str]:
    """Extract repository name from a git remote URL.

    Supported formats:
    1. SSH: git@github.com:user/repo.git -> "repo"
    2. SSH: git@github.com:user/repo     -> "repo"
    3. HTTPS: https://github.com/user/repo.git -> "repo"
    4. HTTPS: https://github.com/user/repo     -> "repo"
    5. file:///path/to/repo.git -> "repo"
    6. file:///path/to/repo     -> "repo"
    7. /path/to/repo.git        -> "repo"  (local path)

    Logic flow:
    1. Strip trailing whitespace and trailing slashes
    2. Strip .git suffix if present
    3. For SSH format (contains ':' but not '://'): split on ':', take last part, split on '/', take last
    4. For others: split on '/', take last segment
    5. Return the repo name, or None if empty

    Args:
        url: Git remote URL string.

    Returns:
        Repository name string, or None if extraction fails.
    """
    # --- Clean URL ---
    # url = url.strip().rstrip("/")
    # if url.endswith(".git"):
    #     url = url[:-4]

    # --- Extract repo name ---
    # if ":" in url and "://" not in url:
    #     # SSH format: git@host:user/repo
    #     after_colon = url.split(":")[-1]
    #     name = after_colon.split("/")[-1]
    # else:
    #     # HTTPS, file://, or local path
    #     name = url.split("/")[-1]

    # return name if name else None

    pass
