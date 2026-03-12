# =============================================================================
# Module: test_project_detection.py
# Purpose: Test project name detection from git remote, git directory, cwd,
#   and the "unknown" fallback — including URL parsing edge cases.
# Rationale: Project detection runs automatically on every neuron creation.
#   It must handle diverse git URL formats (SSH, HTTPS, file://), edge cases
#   (bare repos, no remote, no git), and normalize consistently. URL parsing
#   bugs would silently tag neurons with wrong project names, making
#   project-scoped queries unreliable.
# Responsibility:
#   - Test git remote SSH URL extraction (git@host:user/repo.git)
#   - Test git remote HTTPS URL extraction
#   - Test git remote file:// URL extraction
#   - Test git remote local path extraction
#   - Test .git suffix stripping
#   - Test no remote falls through to git dir
#   - Test no git falls through to cwd
#   - Test cwd fallback
#   - Test root directory cwd falls through to "unknown"
#   - Test normalization (lowercase, [a-z0-9_-] only)
#   - Test "unknown" fallback when all levels fail
# Organization:
#   1. Imports and fixtures
#   2. Git remote URL extraction tests
#   3. Git directory fallback tests
#   4. CWD fallback tests
#   5. Normalization tests
#   6. Full fallback chain tests
#   7. URL parsing edge case tests
# =============================================================================

from __future__ import annotations

import subprocess
import pytest
from unittest.mock import MagicMock, patch

from memory_cli.neuron.project_detection_git_or_cwd import (
    detect_project,
    _from_git_remote,
    _from_git_dir,
    _from_cwd,
    _normalize_project_name,
    _extract_repo_name_from_url,
    FALLBACK_PROJECT,
)


# -----------------------------------------------------------------------------
# Helpers to create mock subprocess results
# -----------------------------------------------------------------------------

def _make_proc(returncode: int, stdout: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


# -----------------------------------------------------------------------------
# Git remote URL extraction tests
# -----------------------------------------------------------------------------

class TestProjectFromGitRemote:
    """Test project detection from git remote origin URL."""

    def test_ssh_url_with_git_suffix(self, monkeypatch):
        """git@github.com:user/my-project.git -> "my-project"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "git@github.com:user/my-project.git\n")
        )
        assert _from_git_remote() == "my-project"

    def test_ssh_url_without_git_suffix(self, monkeypatch):
        """git@github.com:user/my-project -> "my-project"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "git@github.com:user/my-project\n")
        )
        assert _from_git_remote() == "my-project"

    def test_https_url_with_git_suffix(self, monkeypatch):
        """https://github.com/user/my-project.git -> "my-project"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "https://github.com/user/my-project.git\n")
        )
        assert _from_git_remote() == "my-project"

    def test_https_url_without_git_suffix(self, monkeypatch):
        """https://github.com/user/my-project -> "my-project"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "https://github.com/user/my-project\n")
        )
        assert _from_git_remote() == "my-project"

    def test_file_url(self, monkeypatch):
        """file:///path/to/my-project.git -> "my-project"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "file:///path/to/my-project.git\n")
        )
        assert _from_git_remote() == "my-project"

    def test_local_path_url(self, monkeypatch):
        """/path/to/my-project.git -> "my-project"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "/path/to/my-project.git\n")
        )
        assert _from_git_remote() == "my-project"

    def test_gitlab_nested_groups(self, monkeypatch):
        """git@gitlab.com:group/subgroup/repo.git -> "repo".

        Only the final path segment (repo name) is extracted.
        """
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "git@gitlab.com:group/subgroup/repo.git\n")
        )
        assert _from_git_remote() == "repo"

    def test_trailing_slash_stripped(self, monkeypatch):
        """https://github.com/user/repo/ -> "repo"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "https://github.com/user/repo/\n")
        )
        assert _from_git_remote() == "repo"

    def test_subprocess_failure_returns_none(self, monkeypatch):
        """Non-zero exit code returns None."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(128, "")
        )
        assert _from_git_remote() is None

    def test_subprocess_exception_returns_none(self, monkeypatch):
        """Exception during subprocess returns None."""
        def raise_exc(*a, **kw):
            raise subprocess.SubprocessError("timeout")
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            raise_exc
        )
        assert _from_git_remote() is None


# -----------------------------------------------------------------------------
# Git directory fallback tests
# -----------------------------------------------------------------------------

class TestProjectFromGitDir:
    """Test project detection from git directory name (no remote)."""

    def test_git_dir_basename(self, monkeypatch):
        """Git root at /home/user/my-project -> "my-project".

        When there's no remote but we're in a git repo.
        """
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "/home/user/my-project\n")
        )
        assert _from_git_dir() == "my-project"

    def test_git_dir_with_special_chars(self, monkeypatch):
        """Git root "My Project!" -> "myproject" (normalized).

        Special characters removed, spaces removed, lowercased.
        """
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(0, "/home/user/My Project!\n")
        )
        assert _from_git_dir() == "myproject"

    def test_no_git_returns_none(self, monkeypatch):
        """Non-zero exit code (not in git repo) returns None."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(128, "")
        )
        assert _from_git_dir() is None


# -----------------------------------------------------------------------------
# CWD fallback tests
# -----------------------------------------------------------------------------

class TestProjectFromCwd:
    """Test project detection from current working directory."""

    def test_cwd_basename(self, monkeypatch):
        """CWD /home/user/my-project -> "my-project".

        When there's no git repo at all.
        """
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.os.getcwd",
            lambda: "/home/user/my-project"
        )
        assert _from_cwd() == "my-project"

    def test_root_directory_falls_through(self, monkeypatch):
        """CWD "/" -> basename is empty -> falls through to "unknown".

        Root directory has no meaningful basename.
        """
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.os.getcwd",
            lambda: "/"
        )
        assert _from_cwd() is None

    def test_cwd_oserror_falls_through(self, monkeypatch):
        """When os.getcwd() raises OSError -> falls through to "unknown".

        Can happen if cwd is deleted while process is running.
        """
        def raise_oserror():
            raise OSError("deleted")
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.os.getcwd",
            raise_oserror
        )
        assert _from_cwd() is None


# -----------------------------------------------------------------------------
# Normalization tests
# -----------------------------------------------------------------------------

class TestProjectNameNormalization:
    """Test the _normalize_project_name function."""

    def test_lowercase_conversion(self):
        """MY-PROJECT -> "my-project"."""
        assert _normalize_project_name("MY-PROJECT") == "my-project"

    def test_dots_removed(self):
        """my.project -> "myproject"."""
        assert _normalize_project_name("my.project") == "myproject"

    def test_spaces_removed(self):
        """my project -> "myproject"."""
        assert _normalize_project_name("my project") == "myproject"

    def test_special_chars_removed(self):
        """my@project!v2 -> "myprojectv2"."""
        assert _normalize_project_name("my@project!v2") == "myprojectv2"

    def test_hyphens_preserved(self):
        """my-project -> "my-project"."""
        assert _normalize_project_name("my-project") == "my-project"

    def test_underscores_preserved(self):
        """my_project -> "my_project"."""
        assert _normalize_project_name("my_project") == "my_project"

    def test_numbers_preserved(self):
        """project123 -> "project123"."""
        assert _normalize_project_name("project123") == "project123"

    def test_all_invalid_chars_returns_none(self):
        """"..." -> None (all dots removed, nothing left)."""
        assert _normalize_project_name("...") is None

    def test_leading_trailing_hyphens_stripped(self):
        """-my-project- -> "my-project"."""
        assert _normalize_project_name("-my-project-") == "my-project"


# -----------------------------------------------------------------------------
# Full fallback chain tests
# -----------------------------------------------------------------------------

class TestProjectDetectionFallbackChain:
    """Test the complete 4-level fallback chain."""

    def test_git_remote_takes_priority(self, monkeypatch):
        """When git remote is available, it wins over git dir and cwd."""
        call_count = {"remote": 0, "toplevel": 0}

        def mock_run(args, **kw):
            if "get-url" in args:
                call_count["remote"] += 1
                return _make_proc(0, "git@github.com:user/from-remote.git\n")
            elif "--show-toplevel" in args:
                call_count["toplevel"] += 1
                return _make_proc(0, "/path/from-gitdir\n")
            return _make_proc(128, "")

        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            mock_run
        )
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.os.getcwd",
            lambda: "/path/from-cwd"
        )
        result = detect_project()
        assert result == "from-remote"

    def test_git_dir_used_when_no_remote(self, monkeypatch):
        """When no remote but in git repo, git dir name is used."""
        def mock_run(args, **kw):
            if "get-url" in args:
                return _make_proc(128, "")  # no remote
            elif "--show-toplevel" in args:
                return _make_proc(0, "/path/from-gitdir\n")
            return _make_proc(128, "")

        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            mock_run
        )
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.os.getcwd",
            lambda: "/path/from-cwd"
        )
        result = detect_project()
        assert result == "from-gitdir"

    def test_cwd_used_when_no_git(self, monkeypatch):
        """When no git repo, cwd basename is used."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(128, "")
        )
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.os.getcwd",
            lambda: "/home/user/my-cwd-project"
        )
        result = detect_project()
        assert result == "my-cwd-project"

    def test_unknown_when_all_fail(self, monkeypatch):
        """When all detection methods fail, returns "unknown"."""
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.subprocess.run",
            lambda *a, **kw: _make_proc(128, "")
        )
        monkeypatch.setattr(
            "memory_cli.neuron.project_detection_git_or_cwd.os.getcwd",
            lambda: "/"
        )
        result = detect_project()
        assert result == FALLBACK_PROJECT


# -----------------------------------------------------------------------------
# URL parsing edge case tests
# -----------------------------------------------------------------------------

class TestExtractRepoNameFromUrl:
    """Test the _extract_repo_name_from_url helper."""

    def test_empty_url_returns_none(self):
        """Empty string -> None."""
        assert _extract_repo_name_from_url("") is None

    def test_just_git_suffix(self):
        """.git -> None (nothing left after stripping suffix)."""
        # After stripping .git we get empty string -> None
        result = _extract_repo_name_from_url(".git")
        assert result is None

    def test_url_with_port(self):
        """ssh://git@github.com:22/user/repo.git -> "repo"."""
        # ssh:// has ://, so falls into the non-SSH branch
        result = _extract_repo_name_from_url("ssh://git@github.com:22/user/repo.git")
        assert result == "repo"

    def test_whitespace_only_url_returns_none(self):
        """Whitespace-only URL -> None after strip."""
        result = _extract_repo_name_from_url("   ")
        assert result is None

    def test_https_deeply_nested(self):
        """https://gitlab.com/a/b/c/repo.git -> "repo"."""
        result = _extract_repo_name_from_url("https://gitlab.com/a/b/c/repo.git")
        assert result == "repo"
