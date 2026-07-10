# Daemon test lane (on-demand)

## Why a separate lane
- Live-daemon tests spawn a REAL detached `memory embed daemon` + load the
  139 MB embedding model per test.
- Many such tests in ONE pytest process trigger a native `llama_cpp` teardown
  crash (`free_model` `TypeError: 'NoneType'`) + model-load contention →
  non-deterministic full-suite failures (AC1b/AC7/meta-health flaked ~1/run).
- Root fix tracked in **backlog #75** (process isolation for model-loading
  tests). Until then, the default suite must not spawn real daemons.

## The gate
- Env flag: **`MEMORY_DAEMON_TESTS`**. Unset (default) → the live-daemon tests
  skip; the DEFAULT `uv run pytest tests/` is deterministic green.
- Gated (skip unless `MEMORY_DAEMON_TESTS=1`):
  - `tests/embedding/test_r6_daemon_introspection.py` — whole file (every test
    starts a real daemon).
  - `tests/embedding/test_r1_daemon_acceptance.py::TestTierBLiveDaemon` —
    AC1a, AC1b, AC6, AC7 (spawn a real daemon). AC4 is separately gated behind
    `MEMORY_PERF_TESTS` (#74); the flaky pgrep AC2 was removed (#73, superseded
    by the deterministic R6 introspection test).

## Coverage is MOVED, not dropped
- The DETERMINISTIC daemon contract is still in the default suite — the
  fake-daemon protocol reds (`AC3` kill-9, `AC5` skew, `AC8` timeout, `INV-1`
  import-boundary, `AC9` parity) never spawn a real daemon and stay ungated.
- The single-resident-copy acceptance (old AC2) is proven deterministically by
  `test_r6_daemon_introspection.py::TestDeterministicSingleInstance` — run it in
  the on-demand lane.

## Run the on-demand lane
```
MEMORY_DAEMON_TESTS=1 uv run pytest tests/embedding/test_r6_daemon_introspection.py -v
MEMORY_DAEMON_TESTS=1 uv run pytest tests/embedding/test_r1_daemon_acceptance.py -v
# perf lane (host-sensitive, #74):
MEMORY_PERF_TESTS=1 uv run pytest tests/embedding/test_r1_daemon_acceptance.py -k ac4 -v
```
Run this lane before a daemon/embedding release, and whenever daemon lifecycle,
flock single-instance, or introspection code changes.
