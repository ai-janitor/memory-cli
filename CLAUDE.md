# memory-cli

## Maintenance mode
LIVE, gated repo with a pytest suite. For a defect fix or additive verb, use the
**maintain-operate-orchestration** skill (`~/.skills/maintain-operate-orchestration/`):
acceptance-test-first → scope → spec → baseline → delegate → gate → changelog. Per-change
specs live in `docs/delegations/`. ⚠️ Baseline-green must be checked **multi-run**
(`uv run pytest tests/` ×5) — the suite has latent flakiness (time/allocation-sensitive
tests); a single green run is not a stable baseline. (First applied 2026-06-09 for `neuron tree`.)

## Project Status
/decompose v2 IN PROGRESS. Stage 7 (Scaffold) — tree approved, content fan-out next. Read `.planning/v2/SESSION-STATE.md` to resume.

## Quick Context
Graph-based memory CLI for AI agents. Python + llama-cpp-python + SQLite + sqlite-vec. Noun-verb grammar (`memory <noun> <verb>`). Neurons, edges, tags, spreading activation search.

## Key Files
- `REQUIREMENTS-RAW.md` — IMMUTABLE raw requirements
- `REQUIREMENTS.md` — clean requirements (latest)
- `.planning/v1/SESSION-STATE.md` — full session state for resumption
- `.planning/v1/raw-to-clean-trace.md` — requirement traceability
- `docs/knowledge-architecture.md` — the library model (catalog→section→shelf→book); neuron = card, file = book (graph indexes, filesystem holds depth); no-orphan-docs rule
- `docs/claude-code-integration.md` — agent auto-load setup (SessionStart hook) + organizing conventions (hubs, catalog-first, store scoping, hub promotion/demotion)

## Reference Repos
- `/Users/hung/projects/qmd-reference/` — QMD by Tobi Lütke (hybrid search reference)
- `/Users/hung/projects/llama-cpp-reference/` — llama.cpp (embedding engine reference)

## Development Constraints
- **Never use Haiku for coding.** All implementation, scaffolding, and code generation must use Sonnet or Opus. Haiku is only for runtime product features (conversation ingestion extraction, search re-ranking/query expansion) — never for writing code.

## User
- Thinks in analogies (neurons, gotos, time series)
- Wants conversational requirements, not formal specs
- Values opaque storage — AI agents must not browse the DB
- Pragmatic about LLM costs — Haiku where it makes sense for runtime product features, not for development
- "I'm a machine like you dude" — doesn't need breaks
