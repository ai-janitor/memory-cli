---
type: reference
title: Known gaps + deferred work
description: Tracked gaps, deferred items, and follow-ups for memory-cli — each with source ref + trigger condition so nothing is lost.
tags: [known-gaps, deferred, backlog, performance]
timestamp: 2026-07-10
---

# Known gaps + deferred work

Deferred ≠ dropped. Each item = source ref + the condition that should REVIVE it.
Do NOT build deferred items now — wait for the trigger.

## Deferred — perf (corpus-growth triggered)

Source: [perf-boost-recommendations.md](perf-boost-recommendations.md) § Defer (lines 127-135).

| # | Item | Source ref | Trigger — build WHEN | Notes |
|---|---|---|---|---|
| D1 | **ANN vector index** — replace vec0 brute-force KNN | perf-boost § Defer; perf-fix-plan #5 | corpus **N ≫ 1k** neurons | vec0 KNN is O(N) but only ~ms at 769 neurons today. Structural time-bomb, not a now-problem. |
| D2 | **tag-affinity row caps** — cap per-tag candidate pull | perf-boost § Defer; `tag_affinity_scoring_shared_tags.py:284-288` | **only if a sub-timer shows it** — ADD SUB-TIMER FIRST | One common seed tag (`hub`/`person`/`system-rule`) drags most of corpus into candidates. Co-suspect for flat ~30 ms scoring — UNPROVEN. Measure before capping. |
| D3 | **fuzzy fallback full-table scan** — Python Levenshtein over all neurons | perf-boost § Defer; `fuzzy_fallback_levenshtein.py:38-47` | scale-later (alongside D1) | Zero-result path ONLY. Loads all neurons+tags+attrs into Python. Low blast radius today. |
| D4 | **`search_latency` pruning** — bound the metrics table | perf-boost § Defer | table growth becomes noticeable | Unbounded but tiny rows. Note-only; add a retention/prune policy if it grows. |

## Related

- [performance-analysis.md](performance-analysis.md) — cost map + measurement gaps
- [perf-fix-plan.md](perf-fix-plan.md) — the ACTIVE (non-deferred) fix plan
- [perf-second-look-findings.md](perf-second-look-findings.md) — second-look findings
