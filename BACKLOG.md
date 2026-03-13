# memory-cli Backlog

## ~~HIGH — Global CLI Install (pipx/symlink)~~ SHIPPED v0.1.2

**Problem:** `memory` command only works inside the project venv. Every use requires `cd ~/projects/memory-cli && source .venv/bin/activate && memory ...`. This is unacceptable for a CLI tool that agents and humans need from anywhere.

**Solution:** One of:
- `pipx install .` — isolated global install, `memory` on PATH everywhere
- `pip install -e .` into a system/user Python — editable install
- Symlink wrapper in `~/bin/memory` that activates venv and forwards args (like `get-emails` does)

**Entry point already exists:** `[project.scripts] memory = "memory_cli.cli.entrypoint_and_argv_dispatch:main"` — just needs to be installed globally.

**Acceptance:** `memory neuron search "test"` works from any directory without venv activation.

---

## ~~HIGH — Graph Document Import (neurons + edges in one file)~~ SHIPPED v0.1.2

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

---

## EXPLORE — Short-Term / Long-Term Memory Consolidation
> minion backlog #4 · type: idea · priority: medium · flow-hint: feature

**Problem:** All neurons are treated equally. No mechanism distinguishes fleeting observations from deeply connected, frequently accessed knowledge. Temporal decay in search provides implicit forgetting, but there's no promotion — nothing makes a memory "stick."

**What exists today (implicit primitives):**
- Temporal decay in search scoring — recent neurons rank higher, older ones fade (short-term behavior)
- Spreading activation — frequently traversed paths get reinforced (long-term consolidation behavior)
- Tags and edges — structurally connected neurons are more retrievable (structure = long-term)
- Archive verb — manual eviction exists

**What's missing (the promotion side):**
- No salience/importance score on neurons
- No access tracking (search hits, get counts)
- No consolidation pass (periodic process to promote/synthesize)
- No automatic decay/eviction policy

**Cognitive science reference (Atkinson-Shiffrin model):**
Sensory → short-term (working memory, ~7 items, decays fast) → long-term (consolidated, stable, associative). The key mechanism is *consolidation* — rehearsal, association, and salience move things from short to long-term.

**AI memory system precedents:**
- *MemGPT/Letta* — tiered memory: conversation buffer (short-term) → archival storage (long-term), LLM decides what to promote
- *LangChain/LangGraph* — buffer memory (recent N) vs summary memory (compressed) vs entity memory (extracted facts)
- *Generative Agents (Stanford, Park et al.)* — recency + importance + relevance scores; periodic "reflection" synthesizes observations into higher-level insight neurons (consolidation step)

**Potential delta for memory-cli:**

| Component | LOE | What It Does |
|-----------|-----|-------------|
| 1. Access tracking | Small | Every `get`/`search` hit increments a counter + timestamp on the neuron. New columns: `access_count`, `last_accessed_at`. |
| 2. Salience score | Small | Computed field: `f(access_count, edge_count, recency, explicit_reinforcement)`. Could be a view or materialized on write. |
| 3. Consolidation pass | Medium | `memory meta consolidate` — periodic process that: finds high-salience neurons, strengthens edge weights, optionally synthesizes clusters into summary neurons (Haiku call). |
| 4. Auto-decay/eviction | Small | `memory meta gc` — archive neurons below a salience threshold with no edges and no access in N days. Already have `archive`. |
| 5. Tiered retrieval | Medium | Search scorer weighs salience alongside vector similarity, BM25, temporal decay, and activation. Modify RRF fusion to include salience as a signal. |
| 6. Reflection/synthesis | Large | The Stanford "reflections" pattern — synthesize N related neurons into a higher-level insight neuron, link it back. Requires Haiku call. Most ambitious piece. |

**The insight:** Every neuron starts as short-term. Edges are what make it long-term. An isolated neuron with no connections decays away. A heavily-connected one persists. The system is halfway there — the missing piece is access tracking + a consolidation loop.

**LOE estimate:**
- Items 1-2 (access tracking + salience): 1-2 sessions — small schema change, update get/search paths
- Items 3-4 (consolidation + gc): 1-2 sessions — new meta verbs, threshold logic
- Item 5 (tiered retrieval): 1 session — modify existing search scorer
- Item 6 (reflection/synthesis): 2-3 sessions — Haiku integration, clustering, prompt engineering

**Acceptance:** `memory meta consolidate` runs, promotes high-signal neurons, and search results demonstrably favor consolidated knowledge over isolated recent noise.
