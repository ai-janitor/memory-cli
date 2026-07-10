---
type: explanation
title: Knowledge Architecture — the Library Model
description: How knowledge is addressed across the memory graph and filesystem — graph = card catalog, filesystem = stacks, neuron = catalog card (pointer + summary, not the book). The no-orphan-docs rule and tier-by-tier navigation.
tags: [architecture, knowledge-model, library-model, okf, no-orphan]
timestamp: 2026-07-10
---

# Knowledge Architecture — the Library Model

How knowledge is *addressed* across the memory graph and the filesystem. The graph is the
**card catalog**; the filesystem is the **stacks**. A neuron is a **catalog card** — a thin
pointer with a summary — **not the book itself.** You don't cram a whole document into a neuron,
just as a library doesn't photocopy a book onto its index card.

This is the layer above the day-to-day conventions in
[claude-code-integration.md](claude-code-integration.md): *where* a thing lives and *how you
walk to it*, tier by tier.

> **Visual explainer:** [knowledge-architecture.html](knowledge-architecture.html) — a
> self-contained page with SVG diagrams of the four tiers, the card-vs-book rule, and the
> central/regional two-library model. Open it in a browser.

---

## The tiers

A library gets you from "I have a question" to "the paragraph I need" in four hops, narrowing at
each step. Our system mirrors it:

| # | Library | Our system | Addressed by | Convention at this tier |
|---|---|---|---|---|
| 1 | **Card catalog** | the hub index | `memory neuron list --tag hub` | deterministic entry; auto-injected each session by the SessionStart hook |
| 2 | **Section of the building** | a **hub** (neuron tagged `hub`) | hub name (route by mission) | 2–4 word name; body states an **inclusion rule** ("what belongs here") |
| 3 | **Row of shelves** | a **sub-grouping**: either child-index neurons *in-graph*, or a **folder with an INDEX** *on-disk* | `child_of` edges, or the folder's `INDEX.md`/`README` | every shelf is reachable from its section; every folder index is linked from its parent |
| 4 | **The book** | the **content**: a short fact living *in* a neuron, **or** a document *file* the neuron points to | the neuron body (short) or a file path (long) | atomic facts stay in the neuron; long/structured content → a file, neuron = thin card |

The narrowing: **catalog → section → shelf → book.** You never start at the book and hope; you
start at the catalog and walk down. (This is why blind `neuron search "<keyword>"` is the
failure mode — it teleports past tiers 1–3 and often lands on the wrong shelf.)

---

## Two libraries — central and regional (store federation)

The tiers above operate *within* one library. But there are **two kinds of library**, federated:

- **Central library — GLOBAL (`~/.memory/`).** One, shared. The system-wide reference collection
  every patron reaches from anywhere: profile, contacts, system rules/conventions, reusable
  cross-project IP, and the **directory of branches** (below).
- **Regional branch — LOCAL (`<project>/.memory/`).** Created with `memory init`. Holds that
  neighborhood's material: the project's findings, decisions, architecture, build-state.
  *A branch is defined by the **store**, not by a repo* — it's any directory where `memory init`
  was run (marked by `.memory/`), located by **ancestor-walk** from the cwd to the nearest one,
  exactly how the CLI resolves which store to use. Independent of git: a store can exist without
  a repo, and you can be deep in a subtree and still resolve to the branch root.
- **Foreign library — another project's store, read-only**, reached by `--db <path>` or a
  fingerprint handle.

### How they federate

- **Layered (PATH-style) search, regional-first.** Standing in a regional branch, a query hits
  **regional then central**, regional results first. `--global` restricts to central only. (The
  SessionStart hook likewise merges LOCAL + GLOBAL hubs into one catalog.)
- **Local wins.** On a conflict, the regional (closer, more context-specific) card overrides the
  central default.
- **Visibility is upward by default.** Regional automatically sees central; central does **not**
  automatically see a region, and one region can't see another. Central stays common; regional
  stays private.

### Inter-library call numbers (scoped handles + fingerprints)

Every neuron ID is **scoped** so a bare `42` can't be confused across libraries:

| Handle | Library |
|---|---|
| `LOCAL-42` | this regional branch |
| `GLOBAL-42` | central |
| `<fingerprint>:42` | a foreign branch (8-char hex assigned at `memory init`) |

Fingerprints auto-register in `~/.memory/stores.json` — *every store is both a memory graph and
a phonebook of every other store it's talked to.* Discover with `memory meta fingerprint` /
`memory meta stores`.

### Central → regional pointers (so central isn't blind to the branches)

Default visibility is upward, but you can deliberately make **central point down to a region** —
for when something working from central (or from another region, via central) needs to know a
region exists:

- **Cross-store edge.** A GLOBAL neuron can carry an edge to a regional neuron by fingerprint
  handle: `memory edge add GLOBAL-<id> <fingerprint>:<id> --type <rel>`. The central card now
  references the regional book.
- **Branch Registry hub (recommended).** Keep a GLOBAL hub — *"Regional Branches / Project
  Stores"* — whose children are one card per branch: its fingerprint, store path, and a synopsis
  of "what this region covers." This is the agent-readable directory layered on top of
  `stores.json` (which is the raw, noisy auto-phonebook — stale worktrees, typos and all). From
  central, anyone can see *which regions exist and what they hold*, then resolve
  `<fingerprint>:id` to read across.

  **Make it self-enforcing.** Don't rely on agents to update central by hand. A small
  `branch-sync` step in the SessionStart hook resolves the active store (ancestor-walk); if it's
  a LOCAL branch (not the global store), it **upserts that branch's synopsis card** under the
  registry hub, keyed by a `branch-<fingerprint>` tag. The synopsis is mechanical and cheap (no
  LLM): local hub names, or top tags, plus a neuron count. Because central is **vector-searchable
  with 30-day temporal decay**, re-syncing each session both keeps live branches discoverable by
  meaning *and* lets dead branches sink in ranking on their own. Agents can enrich the synopsis
  prose; the mechanical skeleton is guaranteed fresh regardless of compliance.

So: automatic federation flows **up** (regional pulls central); deliberate signposts flow
**down** (central's registry + cross-store edges point to regions). The scoping rule still holds
— regional *content* stays regional; central holds the *directory* + the cross-cutting
collection.

---

## The graph/filesystem boundary — the core rule

> **The neuron is the catalog card. The file is the book. Keep them separate.**

A neuron should be *thin*: a 2–4 word title, a one- or two-line summary, edges to its hub and
related neurons, tags, and — when the depth lives in a file — a **pointer to that file's path**.
The file holds the depth.

**Decide by depth, at write time:**

- **Atomic fact / rule / contact / decision** → lives *fully in the neuron*. (e.g. "SAM expires
  2026-11-19"; a convention rule; a person's email.) No file.
- **Long, structured, or evolving document** → lives in a *file*; the neuron is a card that
  *indexes* it. (e.g. an audit, a plan, a whitepaper, a methodology writeup.) Don't paste the
  document into the neuron.

**Both directions must connect** (no orphans on either side):

- Card → book: the neuron names the file path (in the body, or a `source`/`path` attr).
- Book → shelf: the file sits in a folder whose `INDEX.md`/`README` lists it, and that index is
  linked from its parent, up to a repo root (`README.md` / `CLAUDE.md`). See the *No-Orphan
  Docs* rule below.

A document reachable from the graph but sitting in an unindexed folder is **half-orphaned** —
findable by the agent who already knows the neuron, invisible to one browsing the stacks. Both
paths must hold.

---

## No-Orphan Docs (the filesystem mirror of "no orphan neurons")

The graph already forbids orphan neurons (every neuron `child_of` a hub). The same gate applies
to files:

- Every document is listed in its **folder index** (`INDEX.md` or the folder's `README`).
- Every folder index is linked from its **parent** index, up to the repo root.
- A folder 1–2 levels up is itself a "document to capture" — its index *is* the shelf label.

**Exceptions (captured at the directory level, not per-file):** source code, tests, generated
artifacts, lockfiles. These are indexed by a one-line *role per directory* (the
`docs/<repo>-codebase-index.md` pattern — a directory tree with a role for each folder), not by
listing every file. The unit of capture for code is the **folder**, not the file.

**The gate / check.** Mirror of the graph's orphan query: a detector that finds `.md` files not
referenced by any `README`/`INDEX`/`CLAUDE.md`. Run on demand (or in CI) the same way you'd run
an orphan-neuron sweep.

---

## Worked example

A capability writeup that's too long for a neuron:

```
# 1) the book — a file, in an indexed folder
docs/capabilities/network-intrusion-prototype.md      # the depth
docs/capabilities/INDEX.md                             # lists it (shelf label)
README.md  → links docs/capabilities/INDEX.md          # shelf reachable from root

# 2) the card — a thin neuron that points to the book
memory neuron add "Network Intrusion Prototype — AI-driven NIDS prototype. \
Full writeup: docs/capabilities/network-intrusion-prototype.md" \
  --parent <Capabilities hub> --tags capability,prototype,active
memory attr add <id> path docs/capabilities/network-intrusion-prototype.md
```

Now the prototype is reachable **two ways**: catalog → Capabilities hub → card → file, *and*
browsing the stacks → README → capabilities INDEX → file. No orphan on either side.

---

## Why split catalog from stacks at all

- **Token cost.** The catalog (tiers 1–2) is cheap to push into every session; books are not.
  Push the index, pull the book on demand.
- **Search quality.** A graph of thin, well-edged cards searches and routes far better than a
  graph stuffed with full documents (embeddings blur, snippets bloat).
- **The right tool per tier.** Graph is great at *routing and relating*; the filesystem is great
  at *holding and versioning* depth. Use each for what it's good at; the neuron is the seam.

---

*This is the seed of the model — documented here in the CLI repo first. It should propagate to
the user's global `CLAUDE.md` and a `MEMORY CONVENTION` neuron so it's queryable alongside the
other conventions.*
