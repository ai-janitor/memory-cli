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
```

### Nouns

| Noun | Verbs |
|------|-------|
| `neuron` | add, get, list, update, archive, restore, search |
| `edge` | add, list, remove |
| `tag` | add, list, remove, rename |
| `attr` | set, get, list, remove |
| `batch` | export, import, reembed |
| `meta` | info, stats |

### Global flags

```
--format <json|text>   Output format (default: json)
--config <path>        Config file path
--db <path>            Database file path
--help                 Show help (works at any level)
```

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
