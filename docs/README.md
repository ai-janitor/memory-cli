---
type: index
title: memory-cli docs — entry catalog (ONE DOOR)
description: Navigation catalog for the memory-cli docs bundle. Every doc reachable from here in ≤3 hops (OKF traversability).
tags: [index, catalog, navigation, okf, docs]
timestamp: 2026-07-10
---

# memory-cli docs — entry catalog

The ONE DOOR into the docs bundle. Route by mission, narrow to the doc. Every doc below is
reachable in ≤3 hops. New doc → add its row here (no-orphan-docs rule,
[knowledge-architecture](knowledge-architecture.md)).

Bundle = OKF (Open Knowledge Format): one concept per file, path = identity, markdown links =
the graph. Standard: `~/.droid/refs/open-knowledge-format.md`.

## Fast path — what do you need?

| you need… | open |
|---|---|
| the knowledge/library model (catalog→section→shelf→book, no-orphan rule) | [knowledge-architecture.md](knowledge-architecture.md) |
| agent auto-load / Claude Code integration setup | [claude-code-integration.md](claude-code-integration.md) |
| every product object + wiring + dead/unused tally | [object-model.md](object-model.md) |
| query-path cost map + ranked bottlenecks (LIGHT search) | [performance-analysis.md](performance-analysis.md) |
| ordered fix plan over the perf bottlenecks (quick wins → architecture → scale) | [perf-fix-plan.md](perf-fix-plan.md) |
| dead-code delete candidates + wire/defer decisions | [dead-code-and-unused.md](dead-code-and-unused.md) |
| second-look perf findings beyond the top-5 (multi-store 2× wall, corrected refs) | [perf-second-look-findings.md](perf-second-look-findings.md) |
| ranked perf boost recommendations (what/why/how/acceptance/effort, merged + backlog) | [perf-boost-recommendations.md](perf-boost-recommendations.md) |
| a diagnosis / architecture review / fix methodology | [diagnostics/](#diagnostics) |
| a per-change spec / gate / result (MEM-FIX / MEM-FEAT) | [delegations/](#delegations) |
| a checklist certification transcript | [certs/](#certs) |

## Architecture & knowledge model

- [knowledge-architecture.md](knowledge-architecture.md) — the library model: catalog→section→shelf→book; neuron = card, file = book; no-orphan-docs rule. (also `knowledge-architecture.html`, rendered)
- [claude-code-integration.md](claude-code-integration.md) — agent auto-load (SessionStart hook) + organizing conventions (hubs, catalog-first, store scoping, hub promotion/demotion)

## Reference

- [object-model.md](object-model.md) — account-for-object catalog: ~95 objects / 14 domains; unused tally (5 fully-dead / ~20 product-unused-but-tested). `type: reference`
- [performance-analysis.md](performance-analysis.md) — stage-by-stage cost map + top-5 bottlenecks for `memory neuron search`, benchmarked on the live store. `type: reference`
- [perf-fix-plan.md](perf-fix-plan.md) — ordered fix plan over the top-5: quick wins (write-on-read, BFS PRAGMA+N+1) → architecture (resident embedding daemon) → scale-later (vec0 ANN). Per-fix acceptance test/risk/owner. `type: reference`
- [dead-code-and-unused.md](dead-code-and-unused.md) — action catalog over object-model.md unused tally: Class A (5 fully-dead delete candidates) + Class B decision table (wire/defer per unit). `type: reference`
- [perf-second-look-findings.md](perf-second-look-findings.md) — independent second-look over perf-analysis/perf-fix-plan: 5 new findings (FTS trigger amplification, probe-DDL writes, multi-store 2× wall, facet rollback, tag-affinity explosion) + corrected line refs. `type: reference`
- [perf-boost-recommendations.md](perf-boost-recommendations.md) — ranked boost recommendations merged from perf-fix-plan + second-look + backlog (#72 #66 #67 #35); each item = what/why/how/acceptance/effort. `type: reference`

## Diagnostics

Investigations + methodology. Home: `docs/diagnostics/`.

- [0001-neuron-search-architecture-review.md](diagnostics/0001-neuron-search-architecture-review.md) — architecture review after the 2026-07-09 fleet load storm (load 600+); verifies root causes, finds the fix-not-deployed gap. `type: report`
- [0002-search-fix-methodology.md](diagnostics/0002-search-fix-methodology.md) — execution methodology for the ranked fixes: per-fix scope, acceptance criteria, deploy gate. `type: plan`

## Delegations

Per-change specs, gates, results, baselines for each MEM-FIX / MEM-FEAT. Home: `docs/delegations/`.

- MEM-FEAT-0001 — `neuron tree` verb (spec)
- MEM-FIX-0001..0005 — search/config/model-resolution fixes (spec · gate · result)
- MEM-FIX-0007 — `--type`/`--tag` facet fast-path (baseline · spec · gate · result)
- MEM-FIX-0008 — facet fast-path empty-BM25 phrase fallback (spec · gate · result)
- BATCH-2026-06-10-closeout — batch closeout record

## Certs

Checklist certification transcripts (agile-working, per task). Home: `docs/certs/`.

- object-model-transcript.md · performance-analysis-transcript.md · task-a1051fca…-transcript.md

## Related

- Requirements: `REQUIREMENTS.md` (clean, latest) · `REQUIREMENTS-RAW.md` (immutable)
- Change history: `CHANGELOG.md` (Keep-a-Changelog; product behavior/install changes)
- Session state: `.planning/v1/SESSION-STATE.md`, `.planning/v2/SESSION-STATE.md`

## Gaps (flagged, not yet closed)

- `knowledge-architecture.md` + `claude-code-integration.md` lack OKF frontmatter (`type:`) — retrofit pending.
- `docs/delegations/` + `docs/certs/` files lack frontmatter — process artifacts; low priority.
