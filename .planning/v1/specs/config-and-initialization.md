# Spec #2 — Config & Initialization

## Purpose

This spec covers the `memory init` command, the config file schema at `~/.memory/config.json`, config loading and validation on every CLI invocation, and the `--config` and `--db` global flag overrides. It is a separate unit because config loading is the first thing every other spec depends on: no other spec can execute correctly without knowing the DB path, embedding model settings, and search defaults. The init command also creates the DB file itself (delegating schema creation to #3, which runs immediately after config load). Config is Tier 0 — it depends on nothing.

---

## Requirements Traceability

Addresses `REQUIREMENTS.md §7.2 Init & Config` in full:

- `memory init` creates default config and DB — §7.2 bullet 1
- Config file at `~/.memory/config.json` is root of all settings — §7.2 bullet 2
- Config includes: db path, embedding model settings, defaults for search behavior, Haiku API key env var — §7.2 bullet 3
- `--config` and `--db` flags override for edge cases — §7.2 bullet 4

Transitively supports all other specs via the contract that a loaded, validated config object is available at the start of every command.

---

## Dependencies

None. This is Tier 0. All other specs depend on this one.

---

## Behavior

### 2.1 — Global Flags (apply to every command, not just init)

Every invocation of `memory` accepts two optional global flags:

- `--config <path>` — use this file instead of `~/.memory/config.json`
- `--db <path>` — use this database file instead of the path stored in config

These flags are resolved before any command logic runs. They do not modify the config file on disk. They apply only to the current invocation.

If `--db` is specified without `--config`, it overrides only the `db_path` key from whatever config file was loaded. All other config values come from the resolved config file.

If `--config` specifies a path that does not exist, the CLI exits with code 2 and message: `Config file not found: <path>`.

If `--db` specifies a path that does not exist, the CLI does not error at config-load time — the DB might be created by `memory init` or a subsequent schema-migration step. The path is accepted as-is.

### 2.2 — Config File Location Resolution

On every invocation (except when `--config` is provided), the CLI resolves the config path using this chain (first match wins):

1. If `--config <path>` is provided, use that path.
2. Walk up from the current working directory looking for `.memory/config.json` in each ancestor directory. If found, use it (project-scoped memory).
3. Fall back to `~/.memory/config.json` (global memory, expanding `~` to the user's home directory).

This is analogous to `.git/` discovery — the closest ancestor with `.memory/` wins.

The resolved path is the authoritative config path for the duration of the invocation. The DB path comes from the resolved config's `db_path` field (which for project-scoped stores will be relative to `.memory/`).

### 2.3 — Config File Schema

The config file is JSON. The top-level object contains exactly these keys:

```
db_path               string   Absolute path to the SQLite DB file.
                               Default: ~/.memory/memory.db (expanded at init time, stored as absolute path)

embedding.model_path  string   Absolute path to the GGUF model file.
                               Default: ~/.memory/models/nomic-embed-text-v1.5.Q8_0.gguf

embedding.n_ctx       integer  Context window size for the embedding model.
                               Default: 2048. Minimum: 512.

embedding.n_batch     integer  Batch size for embedding.
                               Default: 512. Minimum: 1.

embedding.dimensions  integer  Expected vector dimensionality. Must match model output.
                               Default: 768.

search.default_limit  integer  Default number of results returned by search.
                               Default: 10. Minimum: 1.

search.fan_out_depth  integer  Default spreading activation depth.
                               Default: 1. Minimum: 0. Maximum: 10.

search.decay_rate     float    Linear decay per hop in spreading activation.
                               Default: 0.25. Range: (0.0, 1.0) exclusive.

search.temporal_decay_enabled  boolean  Whether temporal recency affects ranking.
                               Default: true.

haiku.api_key_env_var  string  Name of the environment variable that holds the Anthropic API key
                               for Haiku calls. The CLI reads the key from os.environ at runtime
                               using this variable name. The key itself is never stored in config.
                               Default: "ANTHROPIC_API_KEY"

output.default_format  string  Default output format for all commands. Valid values: "json", "text".
                               Default: "json"
```

No other top-level keys are defined in v1. Unknown keys in the config file are ignored (forward compatibility).

All path values in config are stored as absolute paths. Relative paths in the config file are an error (see §2.5 Validation).

### 2.4 — `memory init` Command

**Invocation:**
- `memory init` — creates global config and DB at `~/.memory/`
- `memory init --project` — creates project-scoped config and DB at `.memory/` in the current working directory

`memory init` is a top-level command (exception to noun-verb grammar, like `git init`).

**Pre-conditions checked in order:**

1. Determine scope: if `--project` flag is present, target directory is `<cwd>/.memory/`. Otherwise, target directory is `~/.memory/` (expanded to absolute).
2. Resolve config path: `<target_dir>/config.json`. Apply `--config` override if present.
3. Resolve DB path: if `--db` is provided, that is the DB path. Otherwise, `<target_dir>/memory.db` (absolute).

**Behavior:**

1. **Config file existence check:** If the resolved config file already exists, the CLI prints a message and stops without modifying anything:
   `Config already exists at <path>. Use --force to reinitialize.`
   Exit code: 0.

2. **`--force` flag:** If `--force` is provided alongside `memory init`, the CLI proceeds even if config already exists. It overwrites the config file with defaults. It does NOT delete or modify the existing DB file.

3. **Create config directory:** Create the target directory (`.memory/` for project-scoped, `~/.memory/` for global) if it does not exist. Create all intermediate directories. If directory creation fails (permissions, disk full), exit with code 2 and message: `Failed to create config directory <dir>: <OS error message>`.

4. **Write config file:** Write the config JSON to the resolved config path with all default values. The `db_path` in the written config is the resolved DB path (absolute). The `embedding.model_path` is `~/.memory/models/nomic-embed-text-v1.5.Q8_0.gguf` expanded to absolute. Write with standard file permissions (0o644). If write fails, exit code 2 with `Failed to write config: <OS error>`.

5. **Create DB directory:** Create the directory containing the DB file if it does not exist. If creation fails, exit code 2 with `Failed to create DB directory <dir>: <OS error>`.

6. **Create DB file:** Create an empty SQLite DB file at the resolved DB path if it does not already exist. The file is created as an empty file — schema creation is the responsibility of Spec #3 (Schema & Migrations), which runs on every startup. If the DB file creation fails, exit code 2 with `Failed to create DB file <path>: <OS error>`.

7. **Create models directory:** For global init, create `~/.memory/models/` if it does not exist. For project-scoped init, create `.memory/models/` if it does not exist. Do not download the model. Print a note:
   `Model directory created at <path>. Download the embedding model before use:`
   `  huggingface-cli download nomic-ai/nomic-embed-text-v1.5-GGUF nomic-embed-text-v1.5.Q8_0.gguf --local-dir <models_dir>`

8. **Success output:**
   - JSON format (default): `{"status": "ok", "config": "<config_path>", "db": "<db_path>"}`
   - Text format: `Initialized memory-cli.\n  Config: <config_path>\n  DB: <db_path>`
   Exit code: 0.

**Note on `--db` interaction with `memory init`:** If `--db <path>` is provided, the DB file is created at that path AND the `db_path` field in the written config file reflects that override path. This is the one case where `--db` has a persistent effect: init stores the flag value into the config file.

### 2.5 — Config Loading (every invocation except `memory init`)

Every command other than `memory init` runs config loading before any command logic. The loading sequence:

1. **Resolve config path** (see §2.2).
2. **Existence check:** If the config file does not exist at the resolved path, exit code 2:
   `No config found at <path>. Run 'memory init' to create one.`
3. **Parse JSON:** If the file is not valid JSON, exit code 2:
   `Config file is not valid JSON: <path>`
4. **Apply defaults:** For each expected key that is missing from the file, silently apply the default value. This ensures forward compatibility when new config keys are added in later versions.
5. **Apply `--db` override:** If `--db <path>` was provided, replace the `db_path` value from the loaded config with the provided path. This override is in-memory only; the config file on disk is not modified.
6. **Validate:** Run validation checks (see §2.5.1 below).
7. **Return the loaded config object** for use by all subsequent spec logic.

#### 2.5.1 — Validation Rules

Run after loading and applying defaults. Any validation failure exits with code 2 and a message identifying the failing field and reason.

- `db_path`: must be a non-empty string. Must be an absolute path (starts with `/`). The directory containing it must exist or be creatable — validation does not create it; existence is checked passively at this stage.
- `embedding.model_path`: must be a non-empty string. Must be an absolute path.
- `embedding.n_ctx`: must be an integer >= 512.
- `embedding.n_batch`: must be an integer >= 1.
- `embedding.dimensions`: must be an integer > 0.
- `search.default_limit`: must be an integer >= 1.
- `search.fan_out_depth`: must be an integer in range [0, 10].
- `search.decay_rate`: must be a float in the range (0.0, 1.0) exclusive.
- `output.default_format`: must be one of `"json"` or `"text"`.
- `haiku.api_key_env_var`: must be a non-empty string.

Relative paths in `db_path` or `embedding.model_path` are an error:
`Config error: <field> must be an absolute path, got: <value>`

Unknown keys are not an error — they are ignored.

### 2.6 — Config File Encoding and Formatting

The config file is UTF-8 encoded JSON. When written by `memory init`, it is pretty-printed with 2-space indentation. The file must be human-readable so that users can manually edit it.

### 2.7 — Environment Variable for Haiku API Key

The `haiku.api_key_env_var` field stores the NAME of an environment variable, not the key value itself. At config load time, the CLI does NOT read or validate the env var — it is only read at the point of a Haiku call (Spec #9, Spec #11). Config loading succeeds even if the named env var is unset.

### 2.8 — `--format` Flag Interaction

The `--format` flag (defined in Spec #1 CLI Dispatch) overrides `output.default_format` for a single invocation. The loaded config's `output.default_format` is the fallback when `--format` is not specified. Config loading sets this value; CLI dispatch applies the override.

---

## Constraints

- Config file must parse in under 100ms on any supported platform (it is a small JSON file; this is trivially achievable).
- Config loading must be synchronous and complete before any other command logic begins.
- The config file must remain human-editable: no binary formats, no compression, no encryption.
- Path expansion (e.g., `~`) is performed at init time and stored as absolute paths. At load time, no expansion is applied — paths in the file are used as-is.
- The CLI must not write to the config file during normal operation (non-init commands). Config is read-only at runtime.
- Config validation must not perform network calls or DB operations.

---

## Edge Cases

### EC-1: `memory init` run twice without `--force`
The second run detects the existing config file and prints the "already exists" message. Exit code 0. No files modified.

### EC-2: `memory init --force` with an existing DB
The config file is overwritten with defaults. The DB file is NOT touched. If the new config's `db_path` differs from what was previously in the config (e.g., the user is re-initing with a different `--db`), the old DB file remains on disk unmodified.

### EC-3: Config file exists but is empty
Empty file is not valid JSON. Exit code 2: `Config file is not valid JSON: <path>`.

### EC-4: Config file exists but is a directory
JSON parse will fail or OS read will fail. Exit code 2 with the appropriate error message.

### EC-5: Config file has all keys missing (e.g., `{}`)
All defaults are applied. Validation runs on the defaults. Since all defaults are valid, this succeeds silently.

### EC-6: `--db` points to a path in a directory that does not exist
At config-load time, this is not validated beyond being a non-empty absolute path. The missing directory is not an error at config load. The error surfaces later when the DB layer (Spec #3) attempts to open or create the file.

### EC-7: `embedding.model_path` points to a file that does not exist
Not an error at config load time. The error surfaces when the embedding engine (Spec #5) attempts to load the model.

### EC-8: `haiku.api_key_env_var` names an env var that is not set
Not an error at config load time. The error surfaces when a Haiku call is attempted (Specs #9 and #11).

### EC-9: `--config` and `--db` provided together
Both are applied: config is loaded from the `--config` path, then `db_path` is overridden with the `--db` value.

### EC-10: Config file is world-writable or has unusual permissions
The CLI reads and parses the file regardless of permissions (as long as the process can read it). No permission enforcement beyond what the OS provides.

### EC-11: `db_path` in config is a relative path (user manually edited the file)
Validation fails: `Config error: db_path must be an absolute path, got: <value>`. Exit code 2.

### EC-12: `output.default_format` is an unrecognized value (user manually edited the file)
Validation fails: `Config error: output.default_format must be "json" or "text", got: <value>`. Exit code 2.

### EC-13: Multiple simultaneous `memory init` invocations
No file locking is specified for init. Two concurrent inits may both detect the config is absent and both attempt to write it. The last writer wins. This is an acceptable race condition for a single-user CLI tool running init exactly once. No data loss risk since init only writes default values.

### EC-14: `search.fan_out_depth` set to 0 in config
Zero is valid. A fan-out depth of 0 means spreading activation does not spread beyond seed nodes. Results include only direct matches. This is not an error.

### EC-15: `search.decay_rate` of 0.0 or 1.0 (boundary values)
Both are invalid: the range is exclusive. 0.0 would mean no decay (all hops score equally), and 1.0 would mean immediate zero activation at hop 1. Validation rejects both. Exit code 2.

---

## Findings

### Finding F-1: Init behavior when `--db` is provided — persistent vs. transient
The spec states that `memory init --db <path>` writes the `--db` path into the config file. This is the only time `--db` has a persistent side effect. For all other commands, `--db` is transient (in-memory only). This distinction is intentional but not explicitly stated in the requirements. **It is the most logical interpretation**: init is the setup command, and providing `--db` during init means "set up with this DB path." Flagged for user confirmation if the persistent-during-init behavior is not desired.

### Finding F-2: `--force` flag not mentioned in requirements
The requirements say `memory init` "creates default config and DB" but do not specify re-init behavior. The `--force` flag is added here as the only safe way to re-run init. Without it, a second `memory init` would silently succeed or fail — both are bad. Flagged as an addition beyond the literal requirements text.

### Finding F-3: Model download not part of init
Requirements do not specify that `memory init` downloads the embedding model. Init creates directories and prints instructions; it does not download. This is consistent with the spirit of the requirements (init creates config + DB, not the model). Flagged in case the user intended init to also download the model.

### Finding F-4: Config file location is fixed at `~/.memory/config.json` with no XDG support
The requirements specify this path explicitly. No XDG base dir support, no `MEMORY_CONFIG` environment variable override (beyond `--config` flag). This is what the requirements say. Flagged as a potential portability consideration for future versions.

### Finding F-5: No `memory config get/set` subcommands specified
The requirements describe `memory init` and the config file but do not define CLI subcommands for reading or writing individual config values. Users must edit the file manually. This is intentional per the requirements but flagged in case config sub-commands are desired without a full requirements change.

---

## v0.3.x Amendment (2026-03-14)

The following changes shipped in v0.3.0-v0.3.2. They supersede the corresponding v1 spec sections above.

### A-1: Init default flipped — local-first

`memory init` now creates a **local** project store at `.memory/` in the current working directory (git-style). This is the default.

`memory init --global` creates the global store at `~/.memory/`.

The `--project` flag is **removed**. It was replaced by making local the default.

**Supersedes:** Section 2.4 which described `memory init` as global-default and `memory init --project` as project-scoped.

### A-2: `--global` flag added as global CLI flag

`--global` is now a global flag (like `--config` and `--db`) available on all commands, not just `init`.

When `--global` is passed on any command, the CLI skips the local store and operates against the global store only.

**Supersedes:** Section 2.1 Global Flags table — add `--global` (boolean, default false, "Force global store, skip local").

### A-3: Layered PATH-style search

Writes go to the local store if `.memory/` exists, global otherwise.

Reads/searches are **layered**: the CLI queries the local store first, then the global store, and merges results with local neurons ranked higher. Stores are no longer fully isolated on read.

**Supersedes:** The v1 assumption that project-scoped memory is fully isolated.

### A-4: Config schema additions

The following keys were added to the config schema (Section 2.3):

- `search.temporal_half_life_days` (integer, default 30) — half-life for exponential temporal decay
- `haiku.model` (string, default "claude-haiku-4-5-20251001") — Haiku model name for runtime LLM calls
