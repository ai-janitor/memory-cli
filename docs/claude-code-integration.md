# Claude Code Integration — Deterministic Memory Auto-Load + Organizing Conventions

How to wire `memory` into Claude Code (or any agent harness) so the knowledge graph
**auto-loads into every session**, and the conventions that keep the graph navigable
instead of becoming a junk pile. This is the end-to-end setup, written so it's reproducible
on a fresh machine.

> **The core problem this solves.** `memory` is *pull, not push* — neurons are never loaded
> unless an agent explicitly searches. A fresh agent doesn't know the store exists, what's in
> it, or how it's organized, so it either ignores memory or dumps facts in randomly. The fix is
> two halves: **(1)** a deterministic hook that injects the *topic index* (not the whole store)
> at session start, and **(2)** a small set of organizing conventions, themselves stored as
> neurons, that the index points the agent to.

---

## Part 1 — Auto-load via a SessionStart hook

Claude Code's `CLAUDE.md` can *instruct* an agent to "check memory first," but that's
compliance, not a guarantee. A **SessionStart hook** runs a command unconditionally and
injects its stdout into the session's opening context — deterministic regardless of the model.

### Prerequisites

```bash
# memory installed + on PATH (see README Install)
memory init --global                                   # create the global store
curl -L -o ~/.memory/models/default.gguf \             # embedding model
  https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf
# at least one hub neuron exists (see Part 2 bootstrapping)
```

### 1a. The hook script

Save as `~/.claude/hooks/session-memory.sh`, then `chmod +x` it:

```bash
#!/usr/bin/env bash
# SessionStart hook — inject the memory topic map + token rules into context.
# Deterministic: runs regardless of agent compliance.
export TMPDIR="${TMPDIR:-$HOME/.cache}"          # see TMPDIR caveat below

echo "=== MEMORY TOPIC INDEX — hubs (LOCAL + GLOBAL), via: memory neuron list --tag hub ==="
memory neuron list --tag hub 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin).get('data', [])
    for n in sorted(d, key=lambda x: str(x['id'])):
        head = n['content'].replace(chr(10), ' ').split('—')[0].split('.')[0].strip()[:46]
        print('  -', n['id'], '::', head)
except Exception:
    print('  (memory unavailable this session)')
"
echo ""
# Library-model orientation — sourced from the CLI itself (single source of truth),
# so the model is conveyed every session without a hardcoded copy in the hook.
memory manpage architecture brief 2>/dev/null || \
  echo "Route by mission: catalog (list --tag hub) -> section -> shelf -> book. Neuron = card, not the book."
echo ""
echo "(Memory conventions: open the MEMORY CONVENTION hub. Reference hubs by name, not ID.)"

# Self-enforcing branch registry: if this session resolves to a LOCAL store (a
# regional branch, found by ancestor-walk — not a repo), upsert its synopsis card
# in the central registry. Writes only when the synopsis changed. See branch-sync.sh.
[ -x "$HOME/.claude/hooks/branch-sync.sh" ] && "$HOME/.claude/hooks/branch-sync.sh" >/dev/null 2>&1
```

> The orientation text lives in the CLI as `memory manpage architecture` (full) /
> `memory manpage architecture brief` (the hook's compact version) — one authoritative source.
> See [knowledge-architecture.md](knowledge-architecture.md) for the full model.

What it injects: the **topic index only** — every hub's ID + first-line heading. Not the full
store. Cost is ~150–250 tokens/session. The closing line routes the agent to the convention
hub for the rules. (Optionally add a second block that prints one always-relevant hub in full —
e.g. token/efficiency rules — via `memory neuron search "<HUB NAME>" --global`.)

### 1b. Wire it in `~/.claude/settings.json`

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "/Users/<you>/.claude/hooks/session-memory.sh" } ] }
    ]
  }
}
```

### 1c. Verify

Open a new session. The opening context should contain the `MEMORY TOPIC INDEX` block listing
your hubs. Because the hook runs `memory neuron list --tag hub` **live**, any hub you add later
appears automatically next session — nothing to re-edit.

### TMPDIR caveat

The hook (and `memory` generally) writes scratch files during embedding/search. On macOS the
per-session temp dir can fill, surfacing as spurious `ENOSPC`. Pin `TMPDIR` to a stable path
(`~/.cache`) in the hook and in any cron/automation that shells out to `memory`.

---

## Part 2 — Organizing conventions (what makes the graph navigable)

The hook delivers an *index*. These conventions are what make that index meaningful. Store them
**as neurons** under a dedicated hub (suggested name: `MEMORY CONVENTION`) so they're queryable
and self-documenting — the org scheme lives in the same graph it governs.

| Convention | Rule |
|---|---|
| **Root is index** | `memory neuron list --tag hub` is the deterministic entry point. Route by mission to a hub *before* keyword search. |
| **Hubs = topic houses** | A hub is a neuron tagged `hub`. Every real neuron hangs off one via a `child_of` edge. Hub label = 2–4 words. |
| **No orphans** | Every neuron is `child_of` a hub; every hub is reachable from the index. An isolated neuron is noise. |
| **Edge direction** | `memory edge add <HUB> <CHILD> --type child_of` (hub → child). Edges can be added post-hoc, not just at neuron-create time. |
| **Child leads with title** | Neuron content starts with a 2–4 word title phrase so it's readable in a listing. |
| **Reference by name** | Cite hubs/neurons by NAME or tag, never a hardcoded ID — IDs are stable but get archived/superseded; names + tags survive. |
| **Store scoping** | **GLOBAL** (`~/.memory`, `--global`) = profile, contacts, system-rules/conventions, reusable cross-project IP only. **LOCAL** (`<project>/.memory/`) = everything tied to one project. GLOBAL is **not** a catch-all. New project + project-specific fact → `memory init` a LOCAL store first, *then* add (a bare `add` with no `.memory/` present silently lands in GLOBAL = pollution). When unsure "reusable or project-local?" → default LOCAL; promote to GLOBAL only once a 2nd project needs it. |
| **When to cut a new hub** | Promote a grouping to a hub only when it's a *stable retrieval destination*, not a mere attribute. Heuristic: new hub when ≥3 of {a real future mission starts here · the nearest existing hub would mislead · ≥3 children soon · one-sentence inclusion rule · 2–4 word non-vague name}. Otherwise file under the nearest honest hub with a `hub-candidate:<name>` tag. Demote/merge hubs that stop being routing destinations. |

### Each hub carries its own inclusion rule

Write the hub's body to state *what belongs under it* (e.g. "INCLUSION: a thing we BUILD or
OFFER — not a registration, person, or compliance item"). Then an agent browsing the index
knows where a new fact goes without asking.

### Bootstrapping (chicken-and-egg)

The hook needs hubs to list; conventions need a hub to live under. Seed once:

```bash
# 1) the convention hub itself
memory neuron add "MEMORY CONVENTION — how this graph is organized. Children = the rules. \
Enter before restructuring memory or adding hubs." --global --tags hub,convention

# 2) add each rule from the table above as a child
memory neuron add "Store Scoping — GLOBAL = profile/contacts/rules/cross-project IP only; \
project-specific → that project's LOCAL .memory/. GLOBAL is not a catch-all." \
  --global --parent <convention-hub-id> --tags convention
# ...repeat for the other rules...

# 3) seed your first domain hubs (tagged hub), then file neurons under them
```

After that, the hook surfaces every hub each session, and the convention hub teaches any cold
agent the rules on demand. The system becomes self-documenting and self-updating.

---

## Why "index in the hook, rules in the graph"

Pushing the *whole* store into every session is expensive and noisy. Pushing nothing leaves the
agent blind. The split — **push the lightweight index, pull the heavyweight rules/content on
demand** — keeps session cost flat (~150–250 tok) while guaranteeing discoverability: the agent
always sees the map and always knows where the legend is.
