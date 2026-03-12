# =============================================================================
# test_startup_drift_check.py — Tests for startup drift detection
# =============================================================================
# Purpose:     Verify that run_startup_drift_check correctly identifies all
#              drift scenarios: no drift, model drift only, dimension drift
#              only, both drifts simultaneously, and the "no vectors yet"
#              skip case.
# Rationale:   The startup check runs on EVERY CLI invocation. False positives
#              block the user unnecessarily. False negatives let them search
#              with garbage vectors. Both outcomes are unacceptable.
# Responsibility:
#   - Test no-drift path returns clean result
#   - Test model drift detection triggers handler
#   - Test dimension drift detection triggers hard block (exit 2)
#   - Test both drifts simultaneously (dimension takes precedence)
#   - Test empty DB (no vectors) skips all checks
#   - Test vectors_already_stale flag when stale marker is set
# Organization:
#   One test class per scenario. Uses in-memory SQLite with a meta table
#   seeded to the appropriate state. Mocks drift handlers to avoid
#   actual sys.exit or stderr writes during tests.
# =============================================================================

from __future__ import annotations

import pytest
from unittest.mock import patch
from memory_cli.integrity.startup_drift_check_model_and_dims import (
    run_startup_drift_check,
    DriftCheckResult,
    _read_meta_value,
    _extract_model_basename,
)


@pytest.fixture
def migrated_conn():
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


@pytest.fixture
def config():
    return {
        "embedding": {
            "model_path": "/path/to/nomic-embed-text-v1.5.Q8_0.gguf",
            "dimensions": 768,
            "n_ctx": 2048,
        }
    }


def _seed_real_model(conn, model_name: str, dims: int = 768) -> None:
    """Simulate first-vector-write seeding: overwrite 'default' with real model name."""
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_model', ?)", (model_name,))
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_dimensions', ?)", (str(dims),))
    conn.commit()


class TestNoDrift:
    """Tests for the happy path — config matches DB metadata."""

    def test_no_drift_returns_clean_result(self, migrated_conn, config) -> None:
        """When DB model and dims match config, all flags should be False.

        # --- Arrange ---
        # Create in-memory DB with meta table
        # Seed meta: embedding_model = "nomic-embed-text-v1.5.Q8_0.gguf"
        # Seed meta: embedding_dimensions = "768"
        # Config: embedding_model = "nomic-embed-text-v1.5.Q8_0.gguf", embedding_dimensions = 768

        # --- Act ---
        # result = run_startup_drift_check(conn, config)

        # --- Assert ---
        # result.model_drift == False
        # result.dimension_drift == False
        # result.vectors_already_stale == False
        # result.skipped == False
        """
        _seed_real_model(migrated_conn, "nomic-embed-text-v1.5.Q8_0.gguf", 768)
        result = run_startup_drift_check(migrated_conn, config)
        assert result.model_drift is False
        assert result.dimension_drift is False
        assert result.vectors_already_stale is False
        assert result.skipped is False

    def test_no_drift_with_full_model_path(self, migrated_conn) -> None:
        """Config may have full path — basename should be extracted for comparison.

        # --- Arrange ---
        # DB meta: embedding_model = "nomic-embed-text-v1.5.Q8_0.gguf"
        # Config: embedding_model = "/models/nomic-embed-text-v1.5.Q8_0.gguf"

        # --- Act ---
        # result = run_startup_drift_check(conn, config)

        # --- Assert ---
        # result.model_drift == False (basename matches)
        """
        _seed_real_model(migrated_conn, "nomic-embed-text-v1.5.Q8_0.gguf", 768)
        config_with_path = {
            "embedding": {
                "model_path": "/models/nomic-embed-text-v1.5.Q8_0.gguf",
                "dimensions": 768,
            }
        }
        result = run_startup_drift_check(migrated_conn, config_with_path)
        assert result.model_drift is False


class TestModelDrift:
    """Tests for model drift detection (config model != DB model)."""

    def test_model_drift_detected(self, migrated_conn, config) -> None:
        """Different model name should set model_drift flag.

        # --- Arrange ---
        # DB meta: embedding_model = "nomic-embed-v1.5.Q8_0.gguf"
        # DB meta: embedding_dimensions = "768"
        # Config: embedding_model = "bge-small-en-v1.5.Q8_0.gguf", embedding_dimensions = 768

        # --- Act ---
        # Mock handle_model_drift to prevent actual side effects
        # result = run_startup_drift_check(conn, config)

        # --- Assert ---
        # result.model_drift == True
        """
        _seed_real_model(migrated_conn, "old-nomic-embed.gguf", 768)
        config_new_model = {
            "embedding": {
                "model_path": "/path/to/nomic-embed-text-v1.5.Q8_0.gguf",
                "dimensions": 768,
            }
        }
        with patch("memory_cli.integrity.startup_drift_check_model_and_dims.handle_model_drift"):
            result = run_startup_drift_check(migrated_conn, config_new_model)
        assert result.model_drift is True

    def test_model_drift_calls_handler(self, migrated_conn, config) -> None:
        """Model drift should delegate to handle_model_drift.

        # --- Arrange ---
        # Set up model mismatch scenario

        # --- Act ---
        # Patch handle_model_drift, run check

        # --- Assert ---
        # handle_model_drift called once with (conn, old_name, new_name, new_dims)
        """
        _seed_real_model(migrated_conn, "old-model.gguf", 768)
        config_new_model = {
            "embedding": {
                "model_path": "/path/to/nomic-embed-text-v1.5.Q8_0.gguf",
                "dimensions": 768,
            }
        }
        with patch(
            "memory_cli.integrity.startup_drift_check_model_and_dims.handle_model_drift"
        ) as mock_handler:
            run_startup_drift_check(migrated_conn, config_new_model)
        mock_handler.assert_called_once_with(
            migrated_conn,
            "old-model.gguf",
            "nomic-embed-text-v1.5.Q8_0.gguf",
            768,
        )


class TestDimensionDrift:
    """Tests for dimension drift detection (config dims != DB dims)."""

    def test_dimension_drift_exits_with_code_2(self, migrated_conn) -> None:
        """Dimension mismatch should trigger sys.exit(2) via handler.

        # --- Arrange ---
        # DB meta: embedding_dimensions = "768"
        # Config: embedding_dimensions = 384

        # --- Act ---
        # Expect SystemExit with code 2

        # --- Assert ---
        # pytest.raises(SystemExit) with exit code 2
        """
        _seed_real_model(migrated_conn, "nomic-embed-text-v1.5.Q8_0.gguf", 768)
        config_wrong_dims = {
            "embedding": {
                "model_path": "/path/to/nomic-embed-text-v1.5.Q8_0.gguf",
                "dimensions": 384,
            }
        }
        with pytest.raises(SystemExit) as exc_info:
            run_startup_drift_check(migrated_conn, config_wrong_dims)
        assert exc_info.value.code == 2

    def test_dimension_drift_checked_before_model_drift(self, migrated_conn) -> None:
        """Dimension drift is more severe — should be checked first.

        # --- Arrange ---
        # Set up BOTH model drift AND dimension drift
        # DB: model = "old.gguf", dims = "768"
        # Config: model = "new.gguf", dims = 384

        # --- Act ---
        # Should exit 2 for dimension drift, never reaching model drift check

        # --- Assert ---
        # SystemExit(2) raised
        # handle_model_drift was NOT called
        """
        _seed_real_model(migrated_conn, "old.gguf", 768)
        config_both_drifts = {
            "embedding": {
                "model_path": "/path/to/new.gguf",
                "dimensions": 384,
            }
        }
        with patch(
            "memory_cli.integrity.startup_drift_check_model_and_dims.handle_model_drift"
        ) as mock_model_handler:
            with pytest.raises(SystemExit) as exc_info:
                run_startup_drift_check(migrated_conn, config_both_drifts)
        assert exc_info.value.code == 2
        mock_model_handler.assert_not_called()


class TestBothDrifts:
    """Tests for simultaneous model and dimension drift."""

    def test_dimension_drift_takes_precedence(self, migrated_conn) -> None:
        """When both drifts present, dimension drift blocks first.

        # --- Arrange ---
        # DB: model = "old.gguf", dims = "768"
        # Config: model = "new.gguf", dims = 384

        # --- Act / Assert ---
        # SystemExit(2) from dimension drift
        # Model drift handler never invoked
        """
        _seed_real_model(migrated_conn, "old.gguf", 768)
        config_both_drifts = {
            "embedding": {
                "model_path": "/path/to/new.gguf",
                "dimensions": 384,
            }
        }
        with patch(
            "memory_cli.integrity.startup_drift_check_model_and_dims.handle_model_drift"
        ) as mock_model:
            with pytest.raises(SystemExit) as exc_info:
                run_startup_drift_check(migrated_conn, config_both_drifts)
        assert exc_info.value.code == 2
        mock_model.assert_not_called()


class TestNoVectorsYet:
    """Tests for the skip case — no vectors have ever been written."""

    def test_skip_when_default_metadata(self, migrated_conn, config) -> None:
        """If embedding_model is 'default' (migration seed), skip.

        # --- Arrange ---
        # Create in-memory DB with meta seeded to 'default' (migration default)

        # --- Act ---
        # result = run_startup_drift_check(conn, config)

        # --- Assert ---
        # result.skipped == True
        # No handlers called
        """
        # Migration already seeds embedding_model = 'default' — no additional setup needed
        result = run_startup_drift_check(migrated_conn, config)
        assert result.skipped is True

    def test_skip_does_not_warn(self, migrated_conn, config, capsys) -> None:
        """Skip case should produce no stderr output.

        # --- Arrange ---
        # Default meta (migration state)

        # --- Act ---
        # Capture stderr during run_startup_drift_check

        # --- Assert ---
        # stderr is empty
        """
        run_startup_drift_check(migrated_conn, config)
        captured = capsys.readouterr()
        assert captured.err == ""


class TestVectorsAlreadyStale:
    """Tests for the stale-vector warning on startup."""

    def test_stale_flag_detected(self, migrated_conn, config) -> None:
        """If vectors_marked_stale_at is set, result should reflect it.

        # --- Arrange ---
        # DB meta: embedding_model = "nomic-embed-text-v1.5.Q8_0.gguf", embedding_dimensions = "768"
        # DB meta: vectors_marked_stale_at = "2025-06-01T00:00:00+00:00"
        # Config matches DB model and dims (no new drift)

        # --- Act ---
        # result = run_startup_drift_check(conn, config)

        # --- Assert ---
        # result.vectors_already_stale == True
        # result.model_drift == False (no new drift, just existing stale)
        """
        _seed_real_model(migrated_conn, "nomic-embed-text-v1.5.Q8_0.gguf", 768)
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', ?)",
            ("2025-06-01T00:00:00+00:00",),
        )
        migrated_conn.commit()
        result = run_startup_drift_check(migrated_conn, config)
        assert result.vectors_already_stale is True
        assert result.model_drift is False

    def test_stale_warning_emitted_to_stderr(self, migrated_conn, config, capsys) -> None:
        """Stale vectors should produce a warning on stderr.

        # --- Arrange ---
        # Set vectors_marked_stale_at in meta

        # --- Act ---
        # Capture stderr during check

        # --- Assert ---
        # stderr contains warning about stale vectors with timestamp
        """
        _seed_real_model(migrated_conn, "nomic-embed-text-v1.5.Q8_0.gguf", 768)
        migrated_conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('vectors_marked_stale_at', ?)",
            ("2025-06-01T00:00:00+00:00",),
        )
        migrated_conn.commit()
        run_startup_drift_check(migrated_conn, config)
        captured = capsys.readouterr()
        assert "stale" in captured.err.lower() or "WARNING" in captured.err
        assert "2025-06-01" in captured.err


class TestHelpers:
    """Tests for internal helper functions."""

    def test_read_meta_value_existing_key(self, migrated_conn) -> None:
        """_read_meta_value should return value for existing key.

        # --- Arrange ---
        # Insert ('test_key', 'test_value') into meta table

        # --- Act ---
        # result = _read_meta_value(conn, 'test_key')

        # --- Assert ---
        # result == 'test_value'
        """
        migrated_conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('test_key', 'test_value')")
        result = _read_meta_value(migrated_conn, "test_key")
        assert result == "test_value"

    def test_read_meta_value_missing_key(self, migrated_conn) -> None:
        """_read_meta_value should return None for missing key.

        # --- Arrange ---
        # (use migrated DB — key won't exist)

        # --- Act ---
        # result = _read_meta_value(conn, 'nonexistent')

        # --- Assert ---
        # result is None
        """
        result = _read_meta_value(migrated_conn, "nonexistent_key_xyz")
        assert result is None

    def test_extract_model_basename_full_path(self) -> None:
        """_extract_model_basename should strip directory path.

        # --- Act ---
        # result = _extract_model_basename("/models/nomic-embed-v1.5.Q8_0.gguf")

        # --- Assert ---
        # result == "nomic-embed-v1.5.Q8_0.gguf"
        """
        result = _extract_model_basename("/models/nomic-embed-v1.5.Q8_0.gguf")
        assert result == "nomic-embed-v1.5.Q8_0.gguf"

    def test_extract_model_basename_already_basename(self) -> None:
        """_extract_model_basename should handle bare filename.

        # --- Act ---
        # result = _extract_model_basename("nomic-embed-v1.5.Q8_0.gguf")

        # --- Assert ---
        # result == "nomic-embed-v1.5.Q8_0.gguf"
        """
        result = _extract_model_basename("nomic-embed-v1.5.Q8_0.gguf")
        assert result == "nomic-embed-v1.5.Q8_0.gguf"
