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

---

## ~~HIGH — batch load: YAML date tags parsed as datetime.date, not string~~ SHIPPED v0.1.3

**Problem:** `memory batch load` fails when a tag looks like a date (e.g., `2026-03-13`). YAML auto-parses it as `datetime.date`, then the tag creation code calls `.strip()` on it and crashes: `'datetime.date' object has no attribute 'strip'`.

**Observed:** Loading a graph doc with `tags: [leidos, interview, 2026-03-13]` — had to quote it as `"2026-03-13"` to work around.

**Fix:** In the batch load tag processing, coerce all tag values to `str()` before passing to the tag creation path. One line: `tag = str(tag).strip()`. Date tags are common (temporal queries depend on them), so this should just work without quoting.

**Acceptance:** `tags: [leidos, interview, 2026-03-13]` (unquoted) loads without error.

---

## ~~HIGH — batch load: Scoped handles rejected in edge from/to fields~~ NOT REPRODUCIBLE v0.2.2

**Problem:** `memory batch load` rejects scoped handles (`GLOBAL-42`, `LOCAL-42`) in edge `from`/`to` fields with error: `"ref 'GLOBAL-64' not found in neurons"`. The README (lines 186-200) documents this as a supported feature, and `memory edge add` handles scoped handles correctly via `parse_handle()`.

**Root cause:** Validation in `graph_document_loader_yaml_with_ref_resolution.py` line 227 checks `elif val not in refs_seen` — but `refs_seen` only contains local ref labels from the YAML's `neurons` section. Scoped handles like `GLOBAL-64` are strings, pass the `isinstance(val, str)` check, then fail the `refs_seen` lookup.

**The edge creation phase** (`_create_edges_from_refs()`, line 341) would handle them correctly if they got past validation — it already does `ref_map.get(from_ref)` lookups. The problem is purely in the validation gate.

**Fix:** In `_validate_graph_document()` (line 227), before rejecting a string ref as missing, check if it's a valid scoped handle via `parse_handle()`. If it parses successfully, accept it — the DB existence check happens at edge creation time. Alternatively, add scoped handles to `refs_seen` during validation after confirming the neuron exists in the DB.

**Files:**
- Bug: `src/memory_cli/export_import/graph_document_loader_yaml_with_ref_resolution.py` (line 227)
- Reference: `src/memory_cli/cli/noun_handlers/edge_noun_handler.py` (lines 60-61 — correct usage of `parse_handle()`)
- Utility: `src/memory_cli/cli/scoped_handle_format_and_parse.py` (`parse_handle()`)

**Acceptance:** `memory batch load --inline 'neurons: [{ref: x, content: "test"}] edges: [{from: x, to: GLOBAL-42, type: relates_to}]'` succeeds when GLOBAL-42 exists.

---

## ~~HIGH — batch load: No dedup — identical content creates duplicate neurons~~ SHIPPED v0.1.3

**Problem:** Running `memory batch load` on a graph doc that contains content already in the DB creates duplicate neurons. No content-hash or idempotency check. We loaded the same interview prep twice (once via individual calls, once via batch load) and got 14 results for "leidos interview" — every neuron duplicated.

**Observed:** Neurons 4-8 (individual calls) and 17-21 (batch load) have identical content. Also neurons 12-16 appeared from an earlier batch load attempt. Search returns 14 hits for content that should be 5.

**Fix options:**
1. **Content hash dedup** — hash neuron content on create, reject or merge if hash exists. Simple, catches exact dupes.
2. **Ref-based idempotency** — if a neuron with the same `source` + `ref` already exists, update instead of create. More flexible, allows intentional re-loads.
3. **`--upsert` flag** — opt-in: `memory batch load --upsert file.yaml` merges with existing; without flag, skip or warn on dupes.

**Preferred:** Option 2 (source + ref idempotency) with option 1 as a safety net. The `ref` label in graph docs is already a natural key — use it.

**Acceptance:** Running `memory batch load file.yaml` twice produces the same number of neurons, not double.
