# memory-cli Backlog

## HIGH — Global CLI Install (pipx/symlink)

**Problem:** `memory` command only works inside the project venv. Every use requires `cd ~/projects/memory-cli && source .venv/bin/activate && memory ...`. This is unacceptable for a CLI tool that agents and humans need from anywhere.

**Solution:** One of:
- `pipx install .` — isolated global install, `memory` on PATH everywhere
- `pip install -e .` into a system/user Python — editable install
- Symlink wrapper in `~/bin/memory` that activates venv and forwards args (like `get-emails` does)

**Entry point already exists:** `[project.scripts] memory = "memory_cli.cli.entrypoint_and_argv_dispatch:main"` — just needs to be installed globally.

**Acceptance:** `memory neuron search "test"` works from any directory without venv activation.

---

## HIGH — Graph Document Import (neurons + edges in one file)

**Problem:** Storing a structured knowledge graph (e.g., interview prep with 5 neurons and 7 edges) requires 12+ individual CLI calls. `batch import` exists but uses the flat export format — not a human-authored graph document.

**Solution:** Support a "graph document" format (YAML or JSON) that defines neurons and edges together with local references:

```yaml
# interview-prep.yaml
neurons:
  - ref: interview
    content: "Leidos Video Interview — Friday March 13..."
    tags: [leidos, interview, 2026-03-13]
    type: event
    source: interview-prep
  - ref: payam
    content: "Payam Fard — Director of Software Engineering..."
    tags: [leidos, interview, contact]
    type: person

edges:
  - from: interview
    to: payam
    type: has_interviewer
    weight: 1.0
```

Then: `memory batch load interview-prep.yaml` — one call, entire graph.

**Key:** `ref` fields are local labels resolved at import time. Neurons get real IDs, edges use the resolved IDs.

**Acceptance:** Single file, single command, entire graph created with edges wired correctly.
