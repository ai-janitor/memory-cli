# Spec #1 — CLI Dispatch & Output Formatting

## Purpose

This spec covers the outermost layer of the `memory` CLI: how commands are parsed, routed to noun handlers, how help is generated at three levels, how output is formatted (JSON vs plain text), and what exit codes the process emits. It is a separate unit because it is the skeleton into which all other specs plug — every noun handler registers into this dispatcher. Nothing can be built or tested without a working dispatch layer.

---

## Requirements Traceability

| Requirement | Source |
|---|---|
| Noun-verb grammar: `memory <noun> <verb> [args]` | §7.1 Grammar |
| Six nouns: neuron, tag, attr, edge, meta, batch | §7.1 Grammar |
| `memory help` — list all nouns | §7.3 Help |
| `memory <noun> help` — list all verbs for a noun | §7.3 Help |
| `memory <noun> <verb> --help` — flags and usage for a verb | §7.3 Help |
| Default output format is JSON | §7.4 Output Format |
| Alternative output format is plain text | §7.4 Output Format |
| Configurable default output format in config.json | §7.4 Output Format |
| `--format` flag overrides the default per invocation | §7.4 Output Format |
| Exit codes: 0=success/found, 1=not found, 2=error | §7.4 Output Format |

---

## Dependencies

None. This is Tier 0. All other noun handlers register into this dispatcher.

Note: The dispatcher must accept a config object (from spec #2 Config & Initialization) to read the configured default output format. However, the dispatch layer itself does not depend on spec #2 being complete first — it only depends on the config interface contract being defined. At integration time, the config-loading result is passed in.

---

## Behavior

### 1. Invocation Grammar

The CLI entry point is the `memory` command. Every invocation has one of the following forms:

```
memory help
memory <noun> help
memory <noun> <verb> [flags] [args]
memory <noun> <verb> --help
```

- `<noun>` is one of exactly six values: `neuron`, `tag`, `attr`, `edge`, `meta`, `batch`. These are case-sensitive and lowercase only.
- `<verb>` is any string registered by the noun handler for that noun.
- `[flags]` are optional key-value pairs (e.g., `--format json`, `--limit 10`).
- `[args]` are optional positional arguments. Their meaning is defined per-verb by the noun handler.

### 2. Dispatch Routing

**Step 1 — Parse argv.**
The dispatcher reads `sys.argv[1:]`. The first positional token is treated as `<noun>`. The second positional token is treated as `<verb>`. Remaining tokens are passed to the noun handler unmodified.

**Step 2 — Special-case `help` as the first token.**
If `argv[1]` is `help` (or absent), dispatch to the top-level help behavior (see §3.1).

**Step 3 — Validate noun.**
If `argv[1]` is not one of the six registered nouns and is not `help`, the dispatcher emits an error and exits with code 2. The error message names the invalid token and lists the valid nouns.

**Step 4 — Special-case `help` as the second token.**
If `argv[2]` is `help`, dispatch to the noun-level help behavior (see §3.2).

**Step 5 — Validate verb.**
If `argv[2]` is absent (no verb provided), treat as noun-level help (same as §3.2). If `argv[2]` is not a verb registered under the given noun, the dispatcher emits an error and exits with code 2. The error message names the invalid verb and lists the valid verbs for that noun.

**Step 6 — Detect `--help` flag.**
If `--help` is present anywhere in the remaining tokens for a valid `<noun> <verb>` invocation, dispatch to verb-level help behavior (see §3.3).

**Step 7 — Invoke noun handler.**
Pass the remaining tokens (after removing noun and verb) to the noun handler's verb function. The noun handler returns a result object. The dispatcher formats and prints the result according to the active output format (see §4), then exits with the appropriate exit code (see §5).

### 3. Help System

Help output is always printed to stdout. Help always exits with code 0.

#### 3.1 Top-Level Help (`memory help` or bare `memory`)

Prints a single block containing:
- A one-line description: "memory — graph-based memory CLI for AI agents"
- A usage line: `memory <noun> <verb> [flags] [args]`
- A section header "Nouns:" followed by a two-column list: noun name on the left, one-line description on the right. All six nouns appear in this list. The one-line descriptions are fixed strings defined in the dispatcher registration, not generated dynamically.
- A footer line: `Run 'memory <noun> help' for verbs.`

The fixed one-line descriptions for each noun:
- `neuron` — store and retrieve facts, entities, and concepts
- `tag` — manage the tag registry
- `attr` — manage the attribute registry
- `edge` — manage relationships between neurons
- `meta` — inspect database metadata and stats
- `batch` — bulk operations

#### 3.2 Noun-Level Help (`memory <noun> help` or `memory <noun>` with no verb)

Prints a single block containing:
- A usage line: `memory <noun> <verb> [flags]`
- A section header "Verbs:" followed by a two-column list: verb name on the left, one-line description on the right. All verbs registered for that noun appear in this list.
- A footer line: `Run 'memory <noun> <verb> --help' for flags.`

The verb list comes from the registration provided by each noun handler. The dispatcher does not hard-code verb names.

#### 3.3 Verb-Level Help (`memory <noun> <verb> --help`)

Prints a single block containing:
- A usage line: `memory <noun> <verb> [flags] [args]`
- A one-paragraph description of what the verb does.
- A section header "Flags:" followed by a list of flags with their types, defaults, and one-line descriptions.
- Global flags applicable to all verbs (see §3.4) are listed at the bottom under a separate section header "Global flags:".

The verb description and flag list come from the registration provided by the noun handler. The dispatcher does not hard-code verb behavior.

#### 3.4 Global Flags

The following flags apply to every verb and are handled by the dispatcher before invoking the noun handler:

| Flag | Type | Default | Description |
|---|---|---|---|
| `--format` | string | from config | Output format: `json` or `text` |
| `--config` | string | `~/.memory/config.json` | Path to config file |
| `--db` | string | from config | Path to the database file |

`--format`, `--config`, and `--db` are consumed by the dispatcher and do not reach the noun handler as raw tokens. The noun handler receives a pre-resolved context that includes the active format, config path, and db path.

### 4. Output Formatting

#### 4.1 Format Selection

The active output format is determined in this priority order (highest to lowest):
1. `--format <value>` flag provided on the command line.
2. `output_format` field in the loaded config.json.
3. Hardcoded default: `json`.

Valid values for `--format` and `output_format` in config are: `json` and `text`. Any other value is an error (exit code 2) with a message naming the invalid value.

#### 4.2 JSON Format

All output in JSON format is a single JSON object printed to stdout. The object is always valid JSON. There is no trailing newline after the closing `}` unless a newline is required by the platform.

The top-level JSON object has the following fixed keys:

| Key | Type | Always present | Description |
|---|---|---|---|
| `status` | string | yes | One of: `"ok"`, `"not_found"`, `"error"` |
| `data` | object or array or null | yes | The payload. `null` when status is not `"ok"`. |
| `error` | string or null | yes | Human-readable error message. `null` when status is `"ok"`. |
| `meta` | object or null | conditional | Optional metadata (e.g., pagination info). `null` if not applicable. |

The `data` field structure is defined per-verb by the noun handler spec. The dispatcher does not dictate the shape of `data`.

The `meta` field, when present, contains at minimum:
- `total`: integer — total number of results available (for list/search operations).
- `limit`: integer — the limit applied.
- `offset`: integer — the offset applied.

For non-list operations (single-item get, create, delete), `meta` is `null`.

#### 4.3 Plain Text Format

Plain text format is optimized for human readability in a terminal. There is no machine-parseable structure guaranteed.

Rules for plain text output:
- Success output: print each result item as a human-readable line or block. Exact formatting is defined per-verb by the noun handler.
- Not-found output: print a single line: `Not found.`
- Error output: print a single line beginning with `Error:` followed by the error message.
- For list operations, print results one per block, separated by a blank line.
- Pagination info, if applicable, is printed as a trailing line: `(Showing <offset+1>-<offset+count> of <total>)`.

#### 4.4 Stderr vs Stdout

All output data (JSON or plain text) goes to stdout. Diagnostic messages, warnings, and progress indicators that are NOT part of the result go to stderr. Stderr output never interferes with machine parsing of stdout.

#### 4.5 Empty Result Sets

An empty result set (e.g., a list that returns zero items) is a success, not a not-found:
- JSON: `{"status": "ok", "data": [], "error": null, "meta": {"total": 0, "limit": N, "offset": M}}`
- Plain text: print the pagination line `(Showing 0 results)` with no other body content.

### 5. Exit Codes

| Code | Meaning | When it applies |
|---|---|---|
| `0` | Success / found | The command completed successfully, including empty result sets |
| `1` | Not found | A specific item was requested by ID or unique key and was not found |
| `2` | Error | Any other failure: invalid arguments, parse errors, DB errors, config errors |

Exit code rules:
- `0` is returned for list operations even if the list is empty.
- `1` is returned only when a specific singular lookup (get by ID, get by name, etc.) returns no result.
- `2` is returned for all failure conditions: bad noun, bad verb, bad flag value, missing required argument, DB failure, config failure, or any unhandled exception.
- Help always exits with `0`.

### 6. Error Output

When the dispatcher detects an error before invoking a noun handler (bad noun, bad verb, bad flag value), it produces output in the active format (JSON or plain text) following the same output structure defined in §4.

In JSON format, an error before format resolution (i.e., `--format` has an invalid value) falls back to JSON since no valid format was determined. The error is written to stdout as a JSON object with `status: "error"`.

If the active format cannot be determined and cannot fall back to JSON (e.g., corrupted argv), the error is written to stderr as plain text, and the process exits with code 2.

### 7. Noun Handler Registration Contract

Each noun handler registers with the dispatcher by providing:
- The noun name (string, must be one of the six valid nouns).
- A map of verb names to verb handler functions.
- For each verb: a one-line description, a multi-line description, and a flag definition list.
- For each flag: name, type (string, integer, boolean, float), default value (or null if required), and a one-line description.

The dispatcher validates at startup (before any command is processed) that:
- No duplicate nouns are registered.
- No duplicate verbs are registered within a noun.
- All registered nouns are in the valid set of six.

If registration validation fails, the process exits with code 2 and an error message identifying the conflict. This is a programming error, not a user error.

### 8. `memory init` Special Case

`memory init` is a top-level command — an intentional exception to the noun-verb grammar (like `git init`). The dispatcher recognizes `init` as a special first token before noun resolution. Two forms:

- `memory init` — creates global config and DB at `~/.memory/`
- `memory init --project` — creates project-scoped config and DB at `.memory/` in cwd

`memory init` may run before any config or DB file exists. The dispatcher must not attempt to load config or DB before invoking the init handler. The handler is responsible for creating these files.

**F-1 resolved:** User confirmed `memory init` is a top-level exception, not `memory meta init`.

### 9. `--config` and `--db` Flag Behavior

- `--config <path>`: overrides the config resolution chain (see Spec #2 §2.2). The specified path must be an absolute or relative filesystem path. If the file does not exist and the command is not `memory init`, the dispatcher exits with code 2 and an error message.
- `--db <path>`: overrides the database path specified in config.json. The dispatcher passes this override into the context given to the noun handler. The noun handler is responsible for using this path instead of the config-specified path when opening the database.

---

## Constraints

- The CLI must be invokable as a single command: `memory`. There is no requirement for a Python-specific invocation form in the final installed product.
- Output must not include ANSI escape codes (color, bold, etc.) in JSON format. Plain text format may use ANSI codes only if stdout is a TTY (detected at runtime). If stdout is a pipe or file, plain text output is also ANSI-free.
- The total startup-to-output latency attributable to dispatch and output formatting (excluding config loading, DB opening, and noun handler execution) must be imperceptible — no artificial delays, no banner printing, no version check network calls.
- No output is produced by the dispatcher before it has determined the active format, except for the fatal pre-format-resolution error case described in §6.

---

## Edge Cases

### E-1: No arguments (`memory` with nothing)
Treated as `memory help`. Prints top-level help. Exits 0.

### E-2: Unknown noun
`memory foobar` → error output naming `foobar` as unknown, lists valid nouns. Exits 2.

### E-3: Known noun, no verb (`memory neuron`)
Treated as `memory neuron help`. Prints noun-level help. Exits 0.

### E-4: Known noun, unknown verb (`memory neuron foobar`)
Error output naming `foobar` as unknown for `neuron`, lists valid verbs for `neuron`. Exits 2.

### E-5: `--format` with invalid value (`memory neuron list --format xml`)
Error output: invalid format value `xml`, valid values are `json` and `text`. Exits 2. Output uses JSON (fallback since format was not resolved).

### E-6: `--format` appears after positional args
`memory neuron search "some query" --format text` — `--format` is a global flag and must be recognized wherever it appears in the token stream, not just immediately after the verb.

### E-7: `--help` mixed with other flags
`memory neuron add --content "foo" --help` — `--help` anywhere in the token stream triggers verb-level help. The other flags are ignored. Exits 0.

### E-8: Noun handler raises an unhandled exception
The dispatcher catches all unhandled exceptions from noun handlers. In JSON format, it emits `{"status": "error", "data": null, "error": "<exception message>", "meta": null}`. In plain text, it emits `Error: <exception message>`. Exits 2. The full stack trace is written to stderr.

### E-9: Config file missing for a non-init command
If no config file is found (neither project-scoped `.memory/config.json` in any ancestor directory nor global `~/.memory/config.json`) and the command is not `memory init`, the dispatcher emits an error: "No config found. Run 'memory init' to initialize." Exits 2.

### E-10: `--config` path that does not exist
Error: "Config file not found at <path>". Exits 2.

### E-11: Empty string as noun or verb
`memory "" list` — an empty string is not a valid noun. Treated the same as an unknown noun. Exits 2.

### E-12: Help output format
Help output is always plain text regardless of the active output format and regardless of `--format`. Help is for humans. Exits 0.

### E-13: `--format` with `--help`
`memory neuron list --help --format json` — `--help` takes priority. Prints verb-level help as plain text. Exits 0.

### E-14: Noun handler registration conflict (programming error)
If two handlers attempt to register the same noun, or if a handler registers an unrecognized noun, the process exits with code 2 at startup before processing any command. This is caught at import/registration time, not at dispatch time.

---

## Findings (Ambiguities and Gaps)

**F-1 (from §8 above):** `memory init` placement. Requirements §7.2 writes `memory init` as if it is a top-level command (`memory init`), which breaks the noun-verb grammar defined in §7.1. This spec places it under the `meta` noun as `memory meta init`. However, if the user intends `init` to live at the top level, a special case is needed in the dispatcher. This must be confirmed before implementation.

**F-2:** The `batch` noun is listed in §7.1 as one of the six nouns but has no further definition in the requirements (§7.5 covers export/import under spec #12, which is a separate unit). The batch noun's verbs are not defined in the requirements visible to this spec. The dispatcher must accept the batch noun registration, but the verbs cannot be enumerated here. The spec for #12 Export/Import must define what verbs register under `batch`.

**F-3:** The requirements state the exit code for "not found" is `1`, and for "error" is `2`, but do not explicitly define what constitutes "not found" vs "error" in the context of list operations with zero results. This spec resolves it as: zero results from a list is `0` (success), and only singular lookups by ID/key that find nothing are `1`. If the user disagrees, the exit code table in §5 must be revised.

**F-4:** Plain text format output structure per verb is described as "defined per noun handler spec" for `data` content, but the plain text representation of individual neuron or search result objects is not specified here. Each noun handler spec must define its own plain text rendering. This creates a dependency: the CLI dispatch spec cannot fully specify plain text output without the noun handler specs. The dispatcher's responsibility ends at calling the formatter with the noun handler's result object.

**F-5:** The requirements do not specify whether `memory --help` (with a double-dash) should behave the same as `memory help`. This spec treats them as equivalent — `--help` as the first token triggers top-level help.

---

## v0.3.x Amendment (2026-03-14)

The following changes shipped in v0.3.0-v0.3.2. They supersede the corresponding v1 spec sections above.

### A-1: `--global` added as a global flag

`--global` is now a global flag handled by the dispatcher, alongside `--format`, `--config`, and `--db`.

**Supersedes:** Section 3.4 Global Flags table — add:

| Flag | Type | Default | Description |
|---|---|---|---|
| `--global` | boolean | false | Force global store, skip local |

`--global` is consumed by the dispatcher and passed to noun handlers via the resolved context, same as `--config` and `--db`.

### A-2: `tag list` verb gains `--sort count` and `--limit N`

The `tag list` verb now accepts:
- `--sort count` — sort tags by usage count (descending) instead of alphabetical
- `--limit N` — return only the top N tags

These are verb-level flags registered by the tag noun handler, not global flags.

### A-3: `--verbose` flag on neuron verbs

The `neuron get`, `neuron list`, and `neuron search` verbs now accept `--verbose` (boolean flag, default false).

- Default (no `--verbose`): returns lean fields only — id, content, tags, created_at, source (plus score/match_type for search results)
- With `--verbose`: returns full schema — all fields including status, updated_at, project, attributes, embedding_updated_at

### A-4: Handle prefix auto-routing

Neuron IDs now encode their store scope via prefixes: `GLOBAL-<id>`, `LOCAL-<id>`, or `<fingerprint>:<id>`.

When a prefixed handle is provided to `neuron get`, `neuron update`, `neuron archive`, or `neuron restore`, the CLI auto-routes to the correct store without requiring `--global`. The prefix is parsed before dispatch.

### A-5: JSON output envelope — `warnings` array

The JSON output envelope now includes a `"warnings": []` array. Populated with string messages when degradation occurs (e.g., Haiku fallback, embedding unavailable). Empty array when clean.

**Supersedes:** Section 4.2 — add `warnings` to the fixed keys table.
