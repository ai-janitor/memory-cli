# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/manpage_noun_handler.py
# PURPOSE: Built-in reference pages for AI agents. Agents only have the CLI
#          binary — no repo, no README. The manpages teach usage.
# RATIONALE: The manpage noun breaks the noun-verb convention slightly — the
#            "verb" position is actually a topic name. Each topic is a plain
#            text reference page printed to stdout. No DB access needed.
# RESPONSIBILITY:
#   - Define topic content as plain text string constants
#   - Define verb map: one entry per topic, each prints its content
#   - Register with entrypoint dispatch via register_noun()
#   - When `memory manpage` is called with no topic, the help system
#     automatically shows the topic index (noun-level help)
# ORGANIZATION:
#   1. Topic content constants (plain text)
#   2. Topic handler functions (one per topic)
#   3. Verb map and noun registration
# =============================================================================

from __future__ import annotations

from typing import List, Any

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun


# =============================================================================
# TOPIC CONTENT — plain text string constants
# =============================================================================

_OVERVIEW = """\
memory — graph-based memory CLI for AI agents

Grammar:  memory <noun> <verb> [args] [flags]

Nouns and their verbs:
  neuron    add, get, list, update, archive, restore, search
  edge      add, get, list, delete
  tag       add, remove, list
  attr      add, get, list, delete
  batch     load
  gate      show, register, deregister
  meta      stats, version
  manpage   overview, how-to, people, search, graph-docs, stores, recipes,
            front-door, tag-conventions

Global flags (go BEFORE the noun):
  --format <json|text>   Output format (default: json)
  --db <path>            Database file path
  --config <path>        Config file path
  --help                 Show help at any level

Special commands:
  memory init            Create a new memory store
  memory --version       Show version

Quick examples:
  memory neuron add "deploy script is in scripts/deploy.sh"
  memory neuron search "deploy"
  memory neuron list --limit 5
  memory tag add 42 --tags project,ops
  memory edge add 42 99 --type relates_to
  memory batch load graph.yaml
  memory gate show                        (find the front door)
  memory --format text neuron list

Output:
  Default output is JSON envelopes: {"status": "ok", "data": ...}
  Use --format text for human-readable plain text.
  Exit codes: 0 = success, 1 = not found, 2 = error.

Help at every level:
  memory --help                   All nouns
  memory neuron --help            All verbs for neuron
  memory neuron add --help        Flags for neuron add

For topic-specific guides, run: memory manpage <topic>
Topics: people, search, graph-docs, stores, recipes, front-door, tag-conventions"""

_HOW_TO = """\
Agent Onboarding — Getting Started with memory-cli

This guide tells you everything you need to use memory-cli from scratch.

What memory-cli is for:
  Persistent knowledge across conversations. You forget between sessions.
  Memory doesn't. Store facts, decisions, contacts, and context once —
  retrieve them in any future session via semantic search.

Step 1 — Check the gate first
  Before adding anything, see what's already in the store:
    memory gate show
  This finds the front door (most-connected neuron) and lists the main
  topic clusters. Don't add duplicates of what's already there.

Step 2 — Two-store model (LOCAL vs GLOBAL)
  LOCAL store (.memory/ in a project dir):
    Project-specific knowledge — code patterns, deploy procedures,
    team contacts FOR THIS PROJECT.
    Created with:  memory init
    Used by default when .memory/ exists in the current directory.

  GLOBAL store (~/.memory/):
    Cross-project knowledge — personal preferences, contacts you use
    everywhere, reusable patterns.
    Created with:  memory init --global
    Access with:   memory --db ~/.memory/memory.db ...

  Rule of thumb: if you'd use it in multiple projects, it goes GLOBAL.
  If it's specific to one repo or session, it goes LOCAL.

Step 3 — File neurons under doors (parent edges)
  A "door" is a topic-cluster neuron that acts as an index. Example:
  neuron 42 might be "Project Architecture" — the door to all architecture
  neurons. File new facts under doors to keep the graph navigable:

    # Add a fact and wire it to its parent door in one step:
    memory neuron add "API rate limit is 1000 req/min" --parent 42 --edge-type child_of

    # Or add then wire separately:
    memory neuron add "API rate limit is 1000 req/min"
    memory edge add <new-id> 42 --type child_of

  This is how spreading activation finds related neurons: search "rate limit"
  → finds the fact → follows edge to neuron 42 → sees all architecture context.

Step 4 — The manifesto (what's worth storing)
  Not everything belongs in memory. Read the manifesto before bulk-adding:
    memory meta manifesto
  Short version: store durable facts, decisions, and relationships.
  Don't store transient state, logs, or anything that expires quickly.

Step 5 — Quick start workflow
  1. memory gate show                     Orient yourself
  2. memory meta manifesto                Calibrate what to store
  3. memory neuron add "..."              Add a fact
  4. memory neuron search "topic"         Retrieve later
  5. memory edge add <id> <door-id>       Wire to a topic cluster
  6. memory neuron list --limit 10        Browse recent neurons

More guides:
  memory manpage stores       LOCAL vs GLOBAL store details
  memory manpage front-door   The mansion pattern — gate neurons, houses
  memory manpage search       How search works (spreading activation)
  memory manpage recipes      Common patterns and workflows
  memory manpage overview     Full noun/verb reference"""

_PEOPLE = """\
People as Neurons

People are neurons with type=person. Store contacts, relationships, and
context in the memory graph.

Create a person:
  memory neuron add "Aditi Srivastava — PhD in AI, works at FEMA"

Add contact info (attrs upsert — safe to repeat):
  memory attr add <id> email "aditi.srivastava@live.com"
  memory attr add <id> employer "FEMA"
  memory attr add <id> phone "555-1234"

Tag them:
  memory tag add <id> --tags person,contact,ai-researcher

Connect people:
  memory edge add <person-id> <spouse-id> --type married_to
  memory edge add <person-id> <org-id> --type works_at

Update info (attrs upsert — overwrites safely):
  memory attr add <id> employer "New Place"

Person no longer relevant? Archive, don't delete:
  memory neuron archive <id>
  memory neuron restore <id>    # bring back if needed

Search:
  memory neuron search "aditi AI"

Why edges matter:
  Searching "who works at FEMA" finds Aditi.
  Spreading activation then follows her edges to find her husband,
  her projects, papers she reviewed — full context from one search."""

_SEARCH = """\
How Search Works

memory neuron search "query text" [--limit N] [--threshold F]

Search is a multi-stage pipeline that combines keyword matching, vector
similarity, and graph traversal to find relevant neurons.

Pipeline overview (10 stages):
  1. Query parsing        Extract terms, detect intent
  2. Keyword match        SQLite FTS5 full-text search
  3. Embedding lookup     Generate query vector via llama.cpp
  4. Vector similarity    sqlite-vec cosine similarity search
  5. Score fusion         Combine keyword + vector scores (RRF)
  6. Spreading activation BFS walk from top hits along edges
  7. Temporal decay       Penalize old neurons (half-life 30 days)
  8. Deduplication        Merge duplicates from different stages
  9. Ranking              Final score sort
  10. Pagination          Apply --limit and --offset

Spreading activation:
  After initial retrieval, the search walks edges from top-scoring
  neurons using BFS (breadth-first search). Each hop multiplies the
  score by a decay factor (default 0.5). Edge weights modulate the
  spread — stronger edges propagate more activation.

  This means: if you search "FEMA" and find Aditi, spreading activation
  follows her edges to find her husband, her projects, her papers —
  even if those neurons never mention "FEMA".

Temporal decay:
  Neurons lose relevance over time. A half-life of 30 days means a
  90-day-old neuron scores at 12.5% of its original weight. Recent
  memories surface first. This is automatic — no flags needed.

Practical examples:
  memory neuron search "deploy script"
  memory neuron search "meeting notes" --limit 20
  memory --format text neuron search "project status"
  memory neuron search "aditi" --threshold 0.5"""

_GRAPH_DOCS = """\
YAML Graph Document Format

batch load imports structured knowledge from YAML files. Each file
defines neurons and edges in a single document.

Format:
  neurons:
    - ref: 1
      content: "The deploy script lives at scripts/deploy.sh"
      tags: [ops, deploy]
      type: memory
      source: "session-2024-01-15"

    - ref: 2
      content: "Production server is prod-web-01.internal"
      tags: [ops, infra]

  edges:
    - from: 1
      to: 2
      type: relates_to
      weight: 1.0

Field reference:
  Neurons:
    ref       Integer reference ID (local to this file, for edges)
    content   The memory text (required)
    tags      List of tag strings (optional)
    type      Neuron type string (optional, default "memory")
    source    Origin identifier (optional)

  Edges:
    from      Ref ID of source neuron (matches a neuron ref in this file)
    to        Ref ID of target neuron (matches a neuron ref in this file)
    type      Edge type string (e.g., relates_to, causes, part_of)
    weight    Float 0.0-1.0 (optional, default 1.0)

Three input modes:
  memory batch load graph.yaml          # from file
  memory batch load -                   # from stdin
  memory batch load --inline '...'      # inline YAML string

Ref resolution:
  Refs are local integers (1, 2, 3...) scoped to the document.
  After import, neurons get real IDs. Edges reference the local refs,
  which are resolved to real IDs during import.

Cross-file refs:
  To link to neurons from a previous import, use their real IDs
  (the ones returned by the previous batch load) instead of refs.

Idempotency:
  batch load is NOT idempotent — running it twice creates duplicates.
  Design your workflow to load once, then use neuron update for changes.

Examples:
  # Load a project knowledge graph
  memory batch load project-context.yaml

  # Pipe from another tool
  generate-graph | memory batch load -

  # Quick inline graph
  memory batch load --inline '
  neurons:
    - ref: 1
      content: "API endpoint is /v2/agents"
      tags: [api, docs]
  '"""

_STORES = """\
Memory Stores — LOCAL, GLOBAL, Foreign

memory-cli supports multiple isolated memory stores. Each store is a
separate SQLite database with its own neurons, edges, and embeddings.

Three scopes:

  LOCAL (project-scoped):
    Created by: memory init (in a project directory)
    Location:   .memory/memory.db (in project root)
    Use for:    Project-specific knowledge — code patterns, deploy
                procedures, team contacts for THIS project.

  GLOBAL (user-scoped):
    Created by: memory init --global  (or first run)
    Location:   ~/.memory/memory.db
    Use for:    Cross-project knowledge — personal preferences,
                general contacts, reusable patterns.

  Foreign (read-only access to another store):
    Accessed via: --db /path/to/other/memory.db
    Use for:    Reading a teammate's shared memory store, or
                querying a project you're not currently in.

Scoped handles:
  When working with multiple stores, neuron IDs include a scope prefix:
    LOCAL-42     Neuron 42 in the local store
    GLOBAL-42    Neuron 42 in the global store
    <fingerprint>:42   Neuron 42 in a foreign store

  Within a single store, plain integer IDs work fine:
    memory neuron get 42

When to use which store:
  - Working on a project?  Use LOCAL (default, no flags needed)
  - Personal preferences?  Use GLOBAL: memory --db ~/.memory/memory.db ...
  - Sharing knowledge?     Point --db at a shared location

Cross-store edges:
  Edges can connect neurons across stores using scoped handles.
  Example: link a LOCAL project neuron to a GLOBAL contact.

Store fingerprints and cross-store references:
  Each store gets a unique 8-char hex fingerprint at init time (UUID prefix).
  Fingerprints enable cross-store neuron references without knowing file paths:
    a3f2b7c1:42   Neuron 42 in store with fingerprint a3f2b7c1

  Discover fingerprints:
    memory meta fingerprint          Show this store's fingerprint
    memory meta stores               List all known stores and fingerprints

  All stores auto-register in ~/.memory/stores.json at init time.
  The CLI resolves fingerprint:id handles by looking up the fingerprint
  in the registry to find the store's database path.

Init commands:
  memory init                     Create LOCAL store in current dir
  memory init --global            Create GLOBAL store in ~/.memory/
  memory init --db /custom/path   Create store at custom location"""

_RECIPES = """\
Common Patterns and Workflows

1. Quick capture during work, consolidate later
   -----------------------------------------------
   During a work session, dump facts fast:
     memory neuron add "API rate limit is 1000 req/min"
     memory neuron add "Auth token expires every 24h"
     memory neuron add "Config lives at /etc/app/config.yaml"

   At end of session, organize with tags and edges:
     memory tag add 10 --tags api,limits
     memory tag add 11 --tags auth,security
     memory tag add 12 --tags config,ops
     memory edge add 10 11 --type relates_to

2. Model a person with contact info
   -----------------------------------
     memory neuron add "Jane Park — SRE lead, on-call rotation owner"
     memory attr add <id> email "jane.park@company.com"
     memory attr add <id> phone "555-0199"
     memory attr add <id> team "platform-sre"
     memory tag add <id> --tags person,sre,oncall

3. Link project knowledge to global preferences
   -----------------------------------------------
     # In local store:
     memory neuron add "This project uses 4-space indent, black formatter"
     # Link to global coding preferences if they exist:
     memory edge add <local-id> GLOBAL-5 --type implements

4. Search and follow associations
   ---------------------------------
     memory neuron search "deploy"
     # Found neuron 42 about deploy scripts
     memory edge list 42
     # See edges to related neurons — follow them:
     memory neuron get 55   # linked server info
     memory neuron get 60   # linked runbook

5. Batch import from YAML
   -------------------------
   Create a file (e.g., onboarding.yaml):
     neurons:
       - ref: 1
         content: "Repo is at github.com/org/app"
         tags: [repo, onboarding]
       - ref: 2
         content: "CI pipeline runs on merge to main"
         tags: [ci, onboarding]
     edges:
       - from: 1
         to: 2
         type: part_of

   Load it:
     memory batch load onboarding.yaml

6. Daily standup memory pattern
   ------------------------------
     memory neuron add "2024-01-15: Fixed auth bug in /login endpoint"
     memory tag add <id> --tags standup,auth,bugfix
     # Later, find all standup entries:
     memory neuron list --tag standup"""

_FRONT_DOOR = """\
The Memory Mansion — Front Door and Graph Navigation

Your memory graph is a mansion. Neurons are rooms, edges are hallways,
and the gate neuron is the front door — the most connected neuron in
your store, the natural entry point for navigating the graph.

Key concepts:

  Front door (gate neuron):
    The neuron with the most edges. It connects to the main topic
    clusters in your store. Find it with:
      memory gate show

  Houses:
    Neurons directly connected to the gate. Each house is a topic
    cluster — a group of related memories. gate show lists the top
    houses with their edge reasons and weights.

  Hallways (edges):
    Connections between neurons. Build new hallways with edge add.
    Insert a room between two existing rooms with edge splice:
      memory edge add 42 99 --type relates_to
      memory edge splice 42 99 --through 77 --type refines

  Cross-store navigation:
    Each store has a unique fingerprint (8-char hex). Reference neurons
    in other projects using fingerprint:id handles:
      memory neuron get a3f2b7c1:42
    Run `memory meta fingerprint` to see your store's fingerprint.
    Run `memory meta stores` to list all known stores.

  Registering in the global directory:
    Announce your project store to the global memory mansion:
      memory gate register       (from a local project store)
      memory gate deregister     (remove the announcement)
    This creates a representative neuron in ~/.memory/ so cross-project
    search can discover your project.

Practical workflow:
  1. memory gate show                     Find your front door
  2. memory neuron get <gate-id>          Read the gate neuron
  3. memory edge list <gate-id>           See all houses (topic clusters)
  4. memory neuron get <house-id>         Explore a house
  5. memory neuron search "topic"         Search within the mansion

The mansion grows organically. As you add neurons and edges, the gate
may shift to a new most-connected neuron. That is expected — the front
door moves to where the action is."""

_TAG_CONVENTIONS = """\
Tag Naming Conventions

Tags are the primary filtering mechanism in memory-cli. Good tag hygiene
keeps your graph navigable as it grows. This guide defines conventions
for naming, categorizing, and maintaining tags.

Auto-tags (always applied, cannot suppress):
  YYYY-MM-DD     UTC date when neuron was created (e.g., 2026-03-16)
  <project>      Detected from git remote or directory name (e.g., memory-cli)

Three tag categories:

  1. STRUCTURAL TYPES — what the neuron IS
  ─────────────────────────────────────────
  These classify the neuron's role in the graph.

    person          A human being (contact, colleague, etc.)
    contact         A person with stored contact info (email, phone)
    system-rule     A behavioral rule for agents (do X, never Y)
    feedback        User correction or preference for agent behavior
    pipeline        Part of a processing pipeline or build step
    manifesto       Core principle or design philosophy
    decision        An architectural or project decision record
    reference       A pointer to an external resource or document
    session         Captured from a specific work session

  2. DOMAIN GROUPINGS — what the neuron is ABOUT
  ───────────────────────────────────────────────
  These describe the subject matter. Use lowercase, hyphen-separated.

    career          Job search, interviews, resume, skills
    email / emails  Email-sourced content or email-related facts
    cli             CLI design, commands, argument parsing
    infra           Infrastructure, servers, deploy, ops
    tooling         Developer tools, build systems, CI/CD
    architecture    System design, component structure
    financial       Money, taxes, budgets, transactions
    govcon          Government contracting domain

  3. TEMPORAL — when, beyond the auto-date
  ─────────────────────────────────────────
  Auto-tags handle day-level granularity. Add manual temporal tags only
  for coarser groupings or named periods.

    YYYY-MM         Month grouping (e.g., 2026-03) — use sparingly
    q1-2026         Quarter grouping — only if you query by quarter
    sprint-14       Sprint or iteration name

  Do NOT duplicate the auto-date: the system already tags 2026-03-16.

Naming rules:
  - Lowercase only (enforced — tags are normalized to lowercase)
  - Hyphens for multi-word tags: job-search, system-rule, car-tax
  - No underscores, no camelCase, no spaces in tag names
  - Singular preferred: person not persons, email not email-messages
  - Short and specific: cli not command-line-interface

Good vs bad examples:
  GOOD                          BAD
  ────                          ───
  person                        Person (uppercase — normalized anyway)
  system-rule                   system_rule (underscore)
  career                        career-stuff (vague suffix)
  cli                           command-line-interface (too long)
  job-search                    jobSearch (camelCase)
  feedback                      agent-feedback-from-user (over-specific)
  2026-03                       march-2026 (non-standard temporal)
  pipeline                      build-and-deploy-pipeline (too long)

Compound tags — when to split:
  Use compound tags only when the combination is a distinct concept:
    cli-build-pipeline     OK — specific pipeline identity
    arc-b60                OK — specific project/artifact code

  Split when tags are independently useful:
    memory tag add <id> --tags career,interview    (not career-interview)
    memory tag add <id> --tags person,contact      (not person-contact)

Revisit thresholds — when to audit your tags:
  - 50+ distinct tags:  Review for synonyms and merge opportunities.
    Run: memory tag list --sort count
    Look for: near-duplicates (deploy vs deployment), unused tags (count=1).
  - Tags with count=1:  Likely too specific. Consider removing or merging.
  - 10+ structural tags on one neuron:  Over-tagged. Pick the 3-5 most
    relevant. Tags are for filtering, not for describing every facet.
  - Monthly:  Run `memory tag list --sort count --limit 20` and check
    that your top tags still reflect your actual query patterns.

Tag lifecycle:
  1. Create — tags auto-create on first use (no pre-registration needed)
  2. Apply — memory tag add <id> --tags tag1,tag2
  3. Query — memory neuron list --tag <tag>
  4. Audit — memory tag list --sort count (find bloat)
  5. Prune — memory tag remove <id> tag-name (clean up)

Cross-store tags:
  Tags are store-local. The tag "person" in LOCAL and "person" in GLOBAL
  are independent. This is by design — each store has its own taxonomy.
  Use consistent naming across stores for your own sanity."""

# =============================================================================
# TOPIC HANDLERS — each prints its content and returns a Result
# =============================================================================

def _make_topic_handler(content: str):
    """Factory: create a verb handler that prints topic content.

    Pseudo-logic:
    1. Ignore args and global_flags — manpages need no DB or parsing
    2. Print content to stdout as plain text (never JSON-wrapped)
    3. Exit 0 immediately — manpages are reference text, not data operations
    """
    def handler(args: List[str], global_flags: Any) -> Any:
        import sys
        from memory_cli.cli.output_envelope_json_and_text import write_output
        write_output(content, stream=sys.stdout)
        sys.exit(0)
    return handler

handle_overview = _make_topic_handler(_OVERVIEW)
handle_how_to = _make_topic_handler(_HOW_TO)
handle_people = _make_topic_handler(_PEOPLE)
handle_search = _make_topic_handler(_SEARCH)
handle_graph_docs = _make_topic_handler(_GRAPH_DOCS)
handle_stores = _make_topic_handler(_STORES)
handle_recipes = _make_topic_handler(_RECIPES)
handle_front_door = _make_topic_handler(_FRONT_DOOR)
handle_tag_conventions = _make_topic_handler(_TAG_CONVENTIONS)


# =============================================================================
# NOUN REGISTRATION — executed at import time
# =============================================================================
_VERB_MAP = {
    "overview": handle_overview,
    "how-to": handle_how_to,
    "people": handle_people,
    "search": handle_search,
    "graph-docs": handle_graph_docs,
    "stores": handle_stores,
    "recipes": handle_recipes,
    "front-door": handle_front_door,
    "tag-conventions": handle_tag_conventions,
}

_VERB_DESCRIPTIONS = {
    "overview": "Full CLI guide — nouns, verbs, flags",
    "how-to": "Agent onboarding guide — start here if new",
    "people": "How to model people, contacts, relationships",
    "search": "How search works — hybrid retrieval, spreading activation",
    "graph-docs": "YAML graph document format, batch load, inline/stdin",
    "stores": "Memory stores — LOCAL, GLOBAL, foreign, scoped handles",
    "recipes": "Common patterns and workflows",
    "front-door": "The memory mansion — gate neurons, houses, graph navigation",
    "tag-conventions": "Tag naming conventions — structural, domain, temporal categories",
}

_FLAG_DEFS = {
    "overview": [],
    "how-to": [],
    "people": [],
    "search": [],
    "graph-docs": [],
    "stores": [],
    "recipes": [],
    "front-door": [],
    "tag-conventions": [],
}


def register() -> None:
    """Register the manpage noun with the CLI dispatch registry.

    Pseudo-logic:
    1. Call register_noun("manpage", {...}) with verb map, description, etc.
    2. When `memory manpage` is called with no topic, the dispatch system
       calls show_noun_help() which lists all topics — serving as the index.
    """
    register_noun("manpage", {
        "verb_map": _VERB_MAP,
        "description": "Built-in reference pages — run: memory manpage <topic>",
        "verb_descriptions": _VERB_DESCRIPTIONS,
        "flag_defs": _FLAG_DEFS,
    })

# --- Self-register on import ---
register()
