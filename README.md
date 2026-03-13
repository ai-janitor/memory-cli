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

`neuron add` is the inbox — fast, unstructured, ephemeral. `batch load` is the filing cabinet — structured, connected, durable.

The difference matters because **edges are what make search work**. Spreading activation needs connections to traverse. A single neuron is a dot. A graph document is dots with lines between them — and those lines are what surface related memories when you search.

**Typical workflow:**
1. **During work:** `neuron add` for quick observations (short-term capture)
2. **End of session:** `batch load` a graph doc that structures what you learned (long-term storage)
3. **Over time:** Isolated neurons with no edges decay in search ranking; connected ones persist

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
memory batch load interview-prep.yaml
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

**Cross-file references:** Edge `from`/`to` accepts integer neuron IDs to link to neurons from previous loads:

```yaml
neurons:
  - ref: new-fact
    content: "A new fact that extends an existing neuron"

edges:
  - from: new-fact
    to: 42                        # links to existing neuron #42
    type: extends
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
