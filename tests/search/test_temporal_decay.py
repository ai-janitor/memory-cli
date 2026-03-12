# =============================================================================
# Module: test_temporal_decay.py
# Purpose: Test exponential temporal decay — stage 6 of the light search
#   pipeline. Verifies decay formula, half-life behavior, edge cases
#   (brand new neurons, very old neurons, missing timestamps).
# Rationale: Temporal decay directly affects result ranking. The formula
#   e^(-lambda*t) with half-life 30 days must produce exactly 0.5 at 30 days.
#   Edge cases (future timestamps, missing timestamps) must be handled
#   gracefully to prevent NaN or negative scores.
# Responsibility:
#   - Test decay formula: e^(-lambda*t), lambda = ln(2)/half_life
#   - Test half-life: weight = 0.5 at exactly 30 days
#   - Test brand new neuron: weight = 1.0 (age 0)
#   - Test very old neuron: weight approaches 0 (age >> half_life)
#   - Test missing timestamp: weight defaults to 1.0
#   - Test custom half-life parameter
#   - Test age computation from millisecond timestamps
# Organization:
#   1. Imports and fixtures
#   2. Decay formula tests
#   3. Half-life boundary tests
#   4. Edge case tests (new, old, missing, future)
#   5. Age computation tests
# =============================================================================

from __future__ import annotations

import math
import time

import pytest

from memory_cli.search.temporal_decay_exponential_halflife import (
    apply_temporal_decay,
    _compute_temporal_weight,
    _neuron_age_days,
    DEFAULT_HALF_LIFE_DAYS,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with schema."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    return conn


def _insert_neuron_with_timestamp(conn, created_at_ms, content="test"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, 'test', 'active')",
        (content, created_at_ms, now_ms),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


@pytest.fixture
def decay_db(migrated_conn):
    """DB with neurons of varying creation timestamps."""
    conn = migrated_conn
    now_s = time.time()
    now_ms = int(now_s * 1000)
    conn.execute("BEGIN")
    # Neuron 1: created now (age 0)
    _insert_neuron_with_timestamp(conn, now_ms, "brand new")
    # Neuron 2: created 30 days ago
    created_30 = int((now_s - 30 * 86400) * 1000)
    _insert_neuron_with_timestamp(conn, created_30, "30 days old")
    # Neuron 3: created 60 days ago
    created_60 = int((now_s - 60 * 86400) * 1000)
    _insert_neuron_with_timestamp(conn, created_60, "60 days old")
    # Neuron 4: created 365 days ago
    created_365 = int((now_s - 365 * 86400) * 1000)
    _insert_neuron_with_timestamp(conn, created_365, "365 days old")
    # Neuron 5: created 1 second ago
    created_1s = int((now_s - 1) * 1000)
    _insert_neuron_with_timestamp(conn, created_1s, "1 second old")
    conn.execute("COMMIT")
    return conn, now_s


# -----------------------------------------------------------------------------
# Decay formula tests
# -----------------------------------------------------------------------------

class TestTemporalDecayFormula:
    """Test the exponential decay formula and its properties."""

    def test_age_zero_weight_is_one(self):
        """Verify weight = e^0 = 1.0 for a brand new neuron."""
        decay_lambda = math.log(2) / 30
        result = _compute_temporal_weight(0.0, decay_lambda)
        assert abs(result - 1.0) < 1e-10

    def test_half_life_weight_is_half(self):
        """Verify weight = 0.5 at exactly half_life days (30 days).

        lambda = ln(2)/30, age=30: e^(-ln(2)) = 0.5
        """
        half_life = 30.0
        decay_lambda = math.log(2) / half_life
        result = _compute_temporal_weight(30.0, decay_lambda)
        assert abs(result - 0.5) < 1e-10

    def test_double_half_life_weight_is_quarter(self):
        """Verify weight = 0.25 at 2x half_life (60 days).

        e^(-2*ln(2)) = 0.25
        """
        half_life = 30.0
        decay_lambda = math.log(2) / half_life
        result = _compute_temporal_weight(60.0, decay_lambda)
        assert abs(result - 0.25) < 1e-10

    def test_weight_always_positive(self):
        """Verify weight is always > 0, even for very old neurons.

        365 days old: weight ≈ 0.0001, but still positive.
        """
        decay_lambda = math.log(2) / 30
        result = _compute_temporal_weight(365.0, decay_lambda)
        assert result > 0.0

    def test_weight_monotonically_decreasing(self):
        """Verify older neurons have strictly lower weights."""
        decay_lambda = math.log(2) / 30
        ages = [0, 10, 30, 60, 90, 180, 365]
        weights = [_compute_temporal_weight(age, decay_lambda) for age in ages]
        for i in range(len(weights) - 1):
            assert weights[i] > weights[i + 1]


# -----------------------------------------------------------------------------
# Half-life boundary tests
# -----------------------------------------------------------------------------

class TestTemporalDecayHalfLife:
    """Test half-life parameter behavior."""

    def test_default_half_life_30_days(self):
        """Verify default half_life_days = 30."""
        assert DEFAULT_HALF_LIFE_DAYS == 30

    def test_custom_half_life_7_days(self):
        """Verify custom half_life_days=7 produces weight=0.5 at 7 days.

        lambda = ln(2)/7, age=7: e^(-ln(2)) = 0.5
        """
        decay_lambda = math.log(2) / 7
        result = _compute_temporal_weight(7.0, decay_lambda)
        assert abs(result - 0.5) < 1e-10

    def test_custom_half_life_365_days(self):
        """Verify custom half_life_days=365 produces slow decay.

        At 30 days: weight ≈ e^(-30*ln(2)/365) ≈ 0.944 (barely decayed).
        """
        decay_lambda = math.log(2) / 365
        result = _compute_temporal_weight(30.0, decay_lambda)
        expected = math.exp(-30 * math.log(2) / 365)
        assert abs(result - expected) < 1e-10
        assert result > 0.9  # barely decayed


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

class TestTemporalDecayEdgeCases:
    """Test edge cases for temporal decay."""

    def test_missing_timestamp_weight_is_one(self, decay_db):
        """Verify weight = 1.0 when neuron's created_at is missing/None.

        No penalty for unknown age — assumes recent.
        """
        conn, now_s = decay_db
        # Create a candidate with neuron_id that doesn't exist in DB
        candidates = [{"neuron_id": 9999}]
        result = apply_temporal_decay(conn, candidates, now=now_s)
        assert result[0]["temporal_weight"] == 1.0

    def test_future_timestamp_weight_is_one(self, decay_db):
        """Verify weight = 1.0 when neuron has future timestamp.

        Age clamped to 0 — no negative decay (which would be a boost).
        """
        conn, now_s = decay_db
        # Create neuron with future timestamp (1 day in the future)
        future_ms = int((now_s + 86400) * 1000)
        conn.execute("BEGIN")
        nid = _insert_neuron_with_timestamp(conn, future_ms, "future")
        conn.execute("COMMIT")
        candidates = [{"neuron_id": nid}]
        result = apply_temporal_decay(conn, candidates, now=now_s)
        assert result[0]["temporal_weight"] == 1.0

    def test_very_recent_neuron_weight_near_one(self, decay_db):
        """Verify weight ≈ 1.0 for a neuron created 1 second ago."""
        conn, now_s = decay_db
        # Neuron 5 created 1 second ago
        candidates = [{"neuron_id": 5}]
        result = apply_temporal_decay(conn, candidates, now=now_s)
        assert result[0]["temporal_weight"] > 0.9999

    def test_very_old_neuron_weight_near_zero(self, decay_db):
        """Verify weight approaches 0 for neuron created years ago.

        At 365 days with half_life=30: weight ≈ 2^(-365/30) ≈ 0.000006
        """
        conn, now_s = decay_db
        # Neuron 4 is 365 days old
        candidates = [{"neuron_id": 4}]
        result = apply_temporal_decay(conn, candidates, now=now_s)
        assert result[0]["temporal_weight"] < 0.001

    def test_empty_candidates_returns_empty(self, decay_db):
        """Verify empty candidate list returns empty list."""
        conn, now_s = decay_db
        result = apply_temporal_decay(conn, [], now=now_s)
        assert result == []

    def test_now_injection_for_testing(self, decay_db):
        """Verify the `now` parameter allows injecting current time.

        Useful for deterministic tests — don't depend on real clock.
        """
        conn, now_s = decay_db
        candidates = [{"neuron_id": 2}]  # 30 days old
        result = apply_temporal_decay(conn, candidates, now=now_s)
        # Should be approximately 0.5
        assert abs(result[0]["temporal_weight"] - 0.5) < 0.01


# -----------------------------------------------------------------------------
# Age computation tests
# -----------------------------------------------------------------------------

class TestNeuronAgeDays:
    """Test the _neuron_age_days helper function."""

    def test_milliseconds_to_days_conversion(self):
        """Verify correct conversion from ms timestamp to days.

        1 day = 86400 seconds = 86400000 milliseconds.
        """
        now_s = 1000000.0  # arbitrary base time
        one_day_ago_ms = int((now_s - 86400) * 1000)
        result = _neuron_age_days(one_day_ago_ms, now_s)
        assert abs(result - 1.0) < 1e-9

    def test_fractional_days(self):
        """Verify fractional days are computed correctly.

        12 hours = 0.5 days.
        """
        now_s = 1000000.0
        half_day_ago_ms = int((now_s - 43200) * 1000)
        result = _neuron_age_days(half_day_ago_ms, now_s)
        assert abs(result - 0.5) < 1e-9

    def test_age_clamped_to_zero(self):
        """Verify negative age (future timestamp) is clamped to 0."""
        now_s = 1000000.0
        future_ms = int((now_s + 86400) * 1000)  # 1 day in the future
        result = _neuron_age_days(future_ms, now_s)
        assert result == 0.0
