# memory-cli

Graph-based memory CLI for AI agents. Store, connect, and search memories using neurons, edges, tags, and spreading activation — all backed by SQLite + sqlite-vec + llama.cpp embeddings.

## Why

AI agents forget between sessions. `memory-cli` gives them a local, portable graph of memories they can search by meaning, traverse by association, and ingest from conversation transcripts. No cloud dependency — everything runs locally.

## Architecture

- **Neurons** — content nodes (memories, facts, entities)
- **Edges** — directed, weighted connections between neurons
- **Tags** — categorical labels with AND/OR filtering
- **Attributes** — key-value metadata on neurons
- **Search** — hybrid retrieval: vector similarity (KNN) + BM25 full-text + spreading activation + temporal decay + RRF fusion
- **Heavy search** — optional Haiku-powered query expansion and re-ranking
- **Ingestion** — ingest Claude Code JSONL session transcripts into the graph

## Grammar

Noun-verb CLI: `memory <noun> <verb> [args] [flags]`

```
memory neuron add "The deploy script lives in scripts/deploy.sh"
memory neuron list --tag project:memory-cli
memory neuron search "deploy process"
memory edge add <source-id> <target-id> --reason "related"
memory tag list
memory meta stats
memory batch load graph.yaml
```

### Nouns

| Noun | Verbs |
|------|-------|
| `neuron` | add, get, list, update, archive, restore, search |
| `edge` | add, list, remove |
| `tag` | add, list, remove, rename |
| `attr` | set, get, list, remove |
| `batch` | export, import, load, reembed |
| `meta` | info, stats |

### Global flags

```
--format <json|text>   Output format (default: json)
--config <path>        Config file path
--db <path>            Database file path
--help                 Show help (works at any level)
```

## When to Use What

| Method | When | Example |
|--------|------|---------|
| `neuron add` | Quick capture mid-task — one fact, no structure | `memory neuron add "deploy script is in scripts/deploy.sh"` |
| `batch load` | Structured knowledge — multiple facts with relationships | A person, a meeting, talking points, and how they connect |
| `batch load --inline` | Structured knowledge, single tool call (no temp file) | `memory batch load --inline '<yaml>'` |

`neuron add` is the inbox — fast, unstructured, ephemeral. `batch load` is the filing cabinet — structured, connected, durable. `batch load --inline` is the filing cabinet without the paperwork — same structure, one tool call.

The difference matters because **edges are what make search work**. Spreading activation needs connections to traverse. A single neuron is a dot. A graph document is dots with lines between them — and those lines are what surface related memories when you search.

**Typical workflow:**
1. **During work:** `neuron add` for quick observations (short-term capture)
2. **End of session:** `batch load` a graph doc that structures what you learned (long-term storage)
3. **Over time:** Isolated neurons with no edges decay in search ranking; connected ones persist

## Memory Stores and Scoped Handles

`memory-cli` supports three scopes of memory, connected by edges into a single searchable graph:

```
        GLOBAL (~/.memory/)
           /          \
          /            \
    LOCAL-A            LOCAL-B
   (.memory/)         (.memory/)
    project A          project B
```

- **Global** (`~/.memory/`) — user preferences, cross-project knowledge, personal facts. Created with `memory init`.
- **Local** (`<project>/.memory/`) — project-specific knowledge. Created with `memory init --project`.
- **Foreign** — another project's local store, referenced by fingerprint.

### Scoped neuron handles

Every neuron ID returned by the CLI is scoped — preventing accidents when agents work across multiple projects. A bare `42` from project A means nothing in project B.

| Handle | Store | Scope | Example |
|--------|-------|-------|---------|
| `LOCAL-42` | `.memory/memory.db` in project dir | This project | Project-specific facts |
| `GLOBAL-42` | `~/.memory/memory.db` | User-wide | Preferences, cross-project knowledge |
| `a3f2:42` | Foreign store by fingerprint | Another project | Inter-project shared memory |

Handles are stored compact (`L-42`, `G-42`) but displayed explicit (`LOCAL-42`, `GLOBAL-42`). Both forms accepted on input.

### Store fingerprints

Each store gets a UUID fingerprint at `memory init` time, written to a metadata table in the DB. The fingerprint is how agents reference neurons across project boundaries:

```
Agent A (project A) stores a fact → gets back LOCAL-42
Agent A shares it as a3f2:42 (fingerprint:id)
Agent B (project B) can resolve a3f2:42 → finds project A's store → reads neuron #42
```

The DB is self-describing — the metadata table holds the fingerprint, project name, creation timestamp, and DB path. No external registry needed. When a store first resolves a foreign fingerprint, it caches the `{fingerprint: path}` mapping in its own `meta` table. Every store is both a memory graph and a phonebook of every other store it's ever talked to.

### Cross-store edges

Edges can connect neurons across any combination of stores:

```yaml
# In project B's graph document
neurons:
  - ref: deploy-fact
    content: "project B deploys to staging first"

edges:
  - from: deploy-fact
    to: GLOBAL-42              # user preference: "prefers cautious deploys"
    type: informed_by
  - from: deploy-fact
    to: a3f2:42                # project A's neuron: "deploy uses rsync to prod-west-2"
    type: learned_from
```

**Search traverses all three scopes.** An agent in project B searches "deploy process" — spreading activation hits the local fact, follows the edge to the global preference, follows another edge to project A's deploy knowledge. Three stores, one search, full context.

## Graph Document Import

Load an entire knowledge graph from a single YAML file:

```yaml
# interview-prep.yaml
neurons:
  - ref: interview
    content: "Video interview Friday March 13 at 1:00 PM ET"
    tags: [interview, 2026-03-13]
    type: event
    source: interview-prep
  - ref: payam
    content: "Payam Fard — Director of Software Engineering"
    tags: [interview, contact]
    type: person

edges:
  - from: interview
    to: payam
    type: has_interviewer
    weight: 1.0
```

```bash
# From file
memory batch load interview-prep.yaml

# Inline (single tool call — no temp file needed)
memory batch load --inline 'neurons: [{ref: q1, content: "Why do you want this role?", tags: [interview]}]'

# From stdin
echo '<yaml>' | memory batch load -
```

`ref` labels are local — resolved to real neuron IDs at import time. One file, one command, entire graph.

### Graph Document Format

```yaml
neurons:                          # required — list of neurons to create
  - ref: <label>                  # required — local label for edge references
    content: "..."                # required — neuron content
    tags: [tag1, tag2]            # optional — list of tags
    type: <type>                  # optional — stored as attr type=<type>
    source: <source>              # optional — origin identifier

edges:                            # optional — list of edges to create
  - from: <ref-or-id>            # required — local ref label or integer neuron ID
    to: <ref-or-id>              # required — local ref label or integer neuron ID
    type: <reason>               # optional — edge reason (default: "related")
    weight: <float>              # optional — edge weight (default: 1.0)
```

**Cross-file references:** Edge `from`/`to` accepts scoped neuron handles (`LOCAL-42`, `GLOBAL-42`) or bare integer IDs to link to neurons from previous loads:

```yaml
neurons:
  - ref: new-fact
    content: "A new fact that extends an existing neuron"

edges:
  - from: new-fact
    to: LOCAL-42                  # links to existing local neuron #42
    type: extends
  - from: new-fact
    to: GLOBAL-7                  # links to a global neuron
    type: informed_by
```

**Idempotent:** Loading the same file twice reuses existing neurons (matched by source + content) instead of creating duplicates.

## Install

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/ai-janitor/memory-cli/master/install.sh | bash
```

### Manual

```bash
git clone https://github.com/ai-janitor/memory-cli.git
cd memory-cli
pipx install .
```

### Developer

```bash
git clone https://github.com/ai-janitor/memory-cli.git
cd memory-cli
pipx install --editable .
```

### Post-install

```bash
# Initialize the memory store
memory init

# Download the embedding model
curl -L -o ~/.memory/models/default.gguf \
  https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf
```

## Requirements

- Python 3.11+
- SQLite with FTS5 (ships with Python)
- [sqlite-vec](https://github.com/asg017/sqlite-vec) — vector search extension
- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) — GGUF embedding engine
- [PyYAML](https://pyyaml.org/) — graph document import
- [anthropic](https://github.com/anthropics/anthropic-sdk-python) — for heavy search features (optional, needs `ANTHROPIC_API_KEY`)

## Development

```bash
# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Run without installing
uv run memory --help
python -m memory_cli --help
```

## License

MIT
