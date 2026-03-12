# Spec #4 — Tag & Attribute Registries

## Purpose

Define the complete behavior of two managed-enum registries: the tag registry and the attribute registry. Both registries map human-readable names to stable integer IDs. They serve as the authoritative lookup tables for all tag and attribute references across the system. Tags describe context/moment of a memory. Attribute keys name the key side of key-value metadata on neurons.

---

## Requirements Traceability

| Requirement | Source |
|---|---|
| Tag registry: managed enum, integer IDs | §5 Tags |
| All tags normalized to lowercase on write | §5 Tags |
| Tags referenced by name (auto-resolved to ID, auto-created if not exists) | §5 Tags |
| Tags referenced by ID | §5 Tags |
| Tags carry context about WHY a memory exists | §5 Tags |
| Tags included in embedding input | §5 Tags |
| Tag filtering: AND and OR, no complex grouping in v1 | §5 Tags |
| No empty tags possible | §5 Tags |
| Tag CRUD: `tag add`, `tag list`, `tag remove` | §5 Tags, §7.1 Grammar |
| Attribute keys stored as IDs in a registry (same pattern as tags) | §6 Attributes |
| CLI is the only admin interface for attributes | §6 Attributes |
| Attr CRUD: `attr add`, `attr list`, `attr remove` | §6 Attributes, §7.1 Grammar |
| Noun-verb grammar: `memory tag <verb>`, `memory attr <verb>` | §7.1 Grammar |
| JSON output default, plain text alternative | §7.4 Output Format |
| Exit codes 0=success/found, 1=not found, 2=error | §7.4 Output Format |

---

## Dependencies

- **#3 Schema & Migrations** — the `tags` registry table and `attr_keys` registry table must exist before any registry operation can execute.

---

## Behavior

### 4.1 Tag Registry

#### 4.1.1 Data Model

Each tag entry consists of:
- `id` — integer, auto-assigned, stable, never reused
- `name` — text, unique, stored in lowercase

The `id` is the internal reference used everywhere else in the system (neuron-tag join table, FTS input, export format). The `name` is the external interface for humans and agents.

#### 4.1.2 `memory tag add <name>`

- Accepts one tag name per invocation.
- Normalizes `name` to lowercase before any lookup or write.
- If a tag with that normalized name already exists: returns the existing record (id + name). Exit 0.
- If no tag with that name exists: inserts a new row, assigns the next available integer ID, returns the new record. Exit 0.
- The add operation is idempotent — calling it twice with the same name produces the same result.
- Rejects empty string. Exit 2.
- Rejects names that normalize to empty string after stripping whitespace. Exit 2.

#### 4.1.3 `memory tag list`

- Returns all tag registry entries, ordered by `id` ascending.
- Each entry: `id` and `name`.
- If no tags exist: returns empty list. Exit 0. (Not exit 1 — empty is a valid state.)
- Supports `--format json` (default) and `--format text`.
- JSON output: array of objects `[{"id": N, "name": "..."}]`.
- Text output: one `id\tname` pair per line.

#### 4.1.4 `memory tag remove <name-or-id>`

- Accepts either the tag name (string) or tag ID (integer) as the argument.
- If specified by name: normalizes to lowercase before lookup.
- If the tag does not exist: Exit 1 (not found).
- If the tag exists and is referenced by any neuron: the behavior is defined by a referential integrity policy.
  - **Finding F-1:** The requirements do not specify what happens when a tag that is in use is removed. See Findings section.
- If the tag exists and is NOT referenced by any neuron: removes the row from the registry. Exit 0.
- Returns the removed record (id + name) on success. Exit 0.

#### 4.1.5 Auto-Create on Reference

- When any operation (e.g., `memory neuron add --tags foo,bar`) references a tag by name, the tag registry is checked.
- If the tag name (normalized to lowercase) does not exist in the registry, it is created automatically.
- Auto-created tags are identical to explicitly added tags — same normalization, same ID assignment.
- This lookup-or-create operation is atomic with respect to the calling operation.
- The caller receives the resolved integer ID regardless of whether the tag was pre-existing or newly created.

#### 4.1.6 Lookup by Name or ID

- Consumers of the registry (neuron write, search filtering, export/import) may resolve a tag by either name or ID.
- Name lookup: normalizes to lowercase, returns ID. Creates if not exists (auto-create).
- ID lookup: returns name. Does not auto-create. Returns not-found error if ID is unknown.

#### 4.1.7 Normalization Rules

- Normalization is always to lowercase.
- Leading and trailing whitespace is stripped before normalization.
- Internal whitespace is preserved as-is (a tag named `"my project"` is valid).
- Normalization happens at the registry boundary — callers pass raw input, registry normalizes.
- Tags are compared after normalization: `"Python"` and `"python"` resolve to the same tag.

#### 4.1.8 Tag Filtering Primitives

- The registry exposes two filtering operations for use by the search pipeline (#8):
  - **AND filter** (`--tags`): a neuron matches if it has ALL of the specified tags.
  - **OR filter** (`--tags-any`): a neuron matches if it has ANY of the specified tags.
- These are defined here because they are implemented against the tag registry data model, but they are invoked by the search and neuron list commands.
- No complex boolean grouping (e.g., `(A AND B) OR C`) is supported in v1.
- Both filters accept tag names (resolved to IDs before comparison) or tag IDs directly.
- Multiple tags in one filter are comma-separated or passed as repeated flags — behavior is consistent with #1 CLI Dispatch.
- An empty tag filter (no `--tags` or `--tags-any` specified) means no tag restriction — all neurons are eligible.

#### 4.1.9 No Empty Tags Invariant

- The system guarantees no neuron exists with zero tags.
- Auto-capture at write time (timestamp tag, project tag) ensures minimum tag context.
- This invariant is enforced by the neuron write operation (#6), not by the tag registry itself. The registry has no knowledge of which neurons exist.

---

### 4.2 Attribute Registry

The attribute registry follows the exact same pattern as the tag registry. The distinction: tags are standalone labels (a neuron "has" a tag), while attributes are keys in key-value pairs (a neuron has attribute `status=active`). The registry manages only the key side. The value is stored with the neuron and is free-form text.

#### 4.2.1 Data Model

Each attribute key entry consists of:
- `id` — integer, auto-assigned, stable, never reused
- `name` — text, unique, stored in lowercase

The `id` is used in the neuron attribute join table. The `name` is the external interface.

#### 4.2.2 `memory attr add <name>`

- Accepts one attribute key name per invocation.
- Normalizes `name` to lowercase before any lookup or write.
- If the key already exists: returns the existing record. Exit 0. (Idempotent.)
- If the key does not exist: inserts, assigns next integer ID, returns new record. Exit 0.
- Rejects empty string or whitespace-only name. Exit 2.

#### 4.2.3 `memory attr list`

- Returns all attribute key registry entries, ordered by `id` ascending.
- Each entry: `id` and `name`.
- Empty list is a valid result. Exit 0.
- JSON output: array of objects `[{"id": N, "name": "..."}]`.
- Text output: one `id\tname` pair per line.

#### 4.2.4 `memory attr remove <name-or-id>`

- Accepts either the attribute key name or ID.
- If specified by name: normalizes to lowercase before lookup.
- If not found: Exit 1.
- If found and referenced by any neuron attribute: referential integrity policy applies.
  - **Finding F-2:** Same open question as F-1 for tags. See Findings section.
- If found and not referenced: removes row. Returns removed record. Exit 0.

#### 4.2.5 Auto-Create on Reference

- When a neuron write operation references an attribute key by name, the attr registry is checked.
- If the key does not exist (normalized): it is created automatically.
- Same atomicity requirement as tag auto-create.

#### 4.2.6 Lookup by Name or ID

- Same as tag lookup: name lookup normalizes + auto-creates; ID lookup returns name without auto-create.

#### 4.2.7 Normalization Rules

- Identical to tag normalization: lowercase, strip leading/trailing whitespace.

#### 4.2.8 Attribute Values

- Values are NOT stored in the attribute registry.
- The registry is keys-only. Values are free-form text stored in the neuron's attribute data.
- The registry has no knowledge of what values are in use.
- There is no validation of attribute values at the registry layer.

---

### 4.3 Shared Registry Contract

Both registries share these behavioral invariants:

1. **ID stability:** once an integer ID is assigned to a name, that pairing is permanent. Removing a name does not free its ID for reuse. IDs are never recycled.
2. **Normalization at boundary:** the registry normalizes on every write and every lookup. Callers need not pre-normalize.
3. **Idempotent add:** `add` is safe to call repeatedly with the same name.
4. **Auto-create on reference:** the registry creates entries on demand when called from other operations. This is the primary creation path during normal use.
5. **CLI add is explicit creation:** `memory tag add` and `memory attr add` are explicit creation commands, useful for pre-registering known tags/keys before neurons are written.
6. **Name uniqueness:** within each registry, names are unique after normalization. Cross-registry uniqueness is not required — a tag named `project` and an attribute key named `project` can coexist.

---

### 4.4 Output Format

Both `tag` and `attr` commands use the standard output format from #1 CLI Dispatch:

- Default: JSON
- Alternative: `--format text`
- `--format` flag overrides the configured default from config.json

**Single record (add/remove response):**
```json
{"id": 7, "name": "python"}
```

**List response:**
```json
[{"id": 1, "name": "python"}, {"id": 2, "name": "rust"}]
```

**Error response (exit 2):**
```json
{"error": "tag name cannot be empty"}
```

**Not found response (exit 1):**
```json
{"error": "tag not found: 'nosuchname'"}
```

---

### 4.5 Exit Codes

| Condition | Exit Code |
|---|---|
| Successful add, list, or remove | 0 |
| Tag/attr not found (remove by name or ID that doesn't exist) | 1 |
| Invalid input (empty name, malformed ID) | 2 |
| Database error | 2 |

---

## Constraints

- The CLI is the only interface for managing registry entries. No direct DB access is valid.
- Attribute key names and tag names live in separate namespaces — there is no collision between them even if names are identical.
- Registry tables must be created by #3 Schema before any registry operation runs. If tables don't exist, the CLI exits 2 with an error indicating that `memory init` has not been run.
- The tag registry is read-only at search time — search operations never create new tags or modify the registry.
- Integer IDs are assigned by the database (auto-increment). The registry layer does not manage ID generation independently.
- No pagination on `list` for v1 — the full registry is returned. Registry size is assumed to be small (hundreds, not millions).

---

## Edge Cases

1. **Remove a tag/attr key that is in active use:** See F-1 and F-2 in Findings.
2. **Name collision across normalization:** `"Python"`, `"PYTHON"`, and `"python"` all resolve to the same registry entry. The stored name is always the normalized (lowercase) form. The first writer's case does not matter — normalization wins.
3. **Integer ID provided as string to CLI:** The CLI must parse the argument and distinguish between an integer-looking string (ID lookup) and a non-integer string (name lookup). Argument `"7"` is an ID. Argument `"my-tag"` is a name.
4. **Attribute key value pair where key doesn't exist yet:** Auto-create handles this. The key is created, value is stored. The registry never sees values.
5. **Concurrent writes (two agents adding same tag simultaneously):** SQLite WAL mode + unique constraint on `name` means one write wins, the other gets a constraint error and retries with a lookup. The outcome is the same: one entry exists. Atomicity is enforced at the DB layer.
6. **Import with unknown tag IDs:** The import operation (#12) must validate that all tag IDs in the import file exist in the registry before committing. This check is the registry's responsibility to answer — import asks "does ID N exist?" and the registry answers yes/no.
7. **Tag list when database is empty (just initialized):** Returns empty list `[]`. Not an error. No auto-populated default tags.
8. **Whitespace-only tag name:** Rejected. After stripping, the name is empty, which fails the empty-name check. Exit 2.

---

## Findings

**F-1 — Referential integrity on tag remove (ambiguous):**
The requirements do not specify what happens when `memory tag remove <name>` is called for a tag that is currently assigned to one or more neurons. Two options exist: (a) reject the removal with an error listing the referencing neuron count, (b) cascade-remove all neuron-tag associations and then remove the registry entry. Option (a) is safer and more consistent with "opaque storage" — the agent calling `remove` gets feedback before data loss. Option (b) silently modifies neuron data without an explicit neuron-update operation. Recommended: Option (a) — block removal if tag is in use, return count of referencing neurons in the error response. This leaves the decision to the caller, which aligns with the AI-first design principle.

**F-2 — Referential integrity on attr key remove (ambiguous):**
Same ambiguity as F-1. Attribute keys that are in use on neurons — should remove block or cascade? Same recommendation: block removal if the key is in active use on any neuron, report the count. The caller (human or agent) can then decide to update or archive affected neurons before removing the key.

**F-3 — Tag names with special characters (not specified):**
The requirements specify lowercase normalization but do not restrict the character set of tag names. Are tags like `"c++"`, `"v2.0"`, or `"my tag"` valid? The requirements give examples (`project`, `source`, `status`) that are all simple alphanumeric-hyphen names, but no explicit restriction is stated. Recommended interpretation: any non-empty string is a valid tag name, subject to normalization. If a restricted character set is desired, it should be added to requirements explicitly.

**F-4 — `memory tag list` filtering (not specified):**
The `tag list` command has no filtering options defined. For large registries, filtering by name prefix or substring might be useful. In v1, the registry is expected to be small, so full list is sufficient. No action required unless registry grows beyond hundreds of entries.

**F-5 — Attribute value types (not specified):**
The requirements describe attributes as "key-value metadata" with examples `project`, `source`, `status (active/superseded/archived)`. The value side is always treated as free-form text. There is no type system for attribute values in v1. Validation of values (e.g., enforcing that `status` is one of a known set) is explicitly out of scope — CLI is the only admin interface, values are free-form.
