# Spec #11 — Conversation Ingestion from JSONL

## Purpose

This spec covers `memory batch ingest <path>`, a bulk operation that reads a Claude Code session transcript (JSONL), sends its conversational content to Claude Haiku for entity/fact/relationship extraction, and creates neurons and edges in the memory graph from the extracted data. Haiku is a runtime product feature here — it is the extraction engine, not a development aid. This is the primary way AI agents accumulate persistent memory from past work sessions. Source attribution to the originating session file is tracked on every created neuron.

---

## Requirements Traceability

Addresses `REQUIREMENTS.md §3.2 Conversation Ingestion` in full:

- Feed a Claude Code session transcript (JSONL) into the CLI — §3.2 bullet 1
- Haiku extracts entities, facts, and relationships — §3.2 bullet 2
- Creates neurons and edges from extracted data — §3.2 bullet 3
- Source is Claude Code's `.claude/` session files — §3.2 bullet 4

Also traces to:

- §7.1 Grammar — `batch` is a registered noun; `ingest` is its verb
- §7.4 Output Format — JSON default, exit codes 0/1/2
- §2.1 Neurons — source and project attributes apply to created neurons
- §2.2 Edges — every edge carries a reason; weight defaults to 1.0
- §2.3 Capture Context — all neurons created in one ingest share a capture context edge
- §8 Embedding — created neurons are embedded immediately (same as manual neuron add)
- §12 Development Constraints — Haiku only for runtime product features, never for coding

---

## Dependencies

- **#2 Config & Initialization** — Haiku API key env var is read from config (`haiku.api_key_env_var`); resolved config must be loaded before ingestion begins
- **#5 Embedding Engine** — neurons created by ingestion are embedded immediately on creation
- **#6 Neuron CRUD & Storage** — all extracted entities and facts are created as neurons via the neuron-add path (same write flow: validate → store → tag → embed)
- **#7 Edge Management** — all extracted relationships are created as edges via the edge-add path; capture context linking also uses this path

---

## Behavior

### 11.1 — Command Syntax

```
memory batch ingest <path> [flags]
```

`<path>` is the path to a Claude Code session JSONL file. It may be an absolute path or a path relative to the current working directory. Both `.jsonl` files and their associated companion files (same UUID, no extension) are valid input — the JSONL file is the one with lines of JSON.

Flags:

- `--dry-run` — parse and call Haiku, print what would be created, but do not write to DB. Output format follows `--format` setting.
- `--project <name>` — override the project tag applied to created neurons. Default: auto-captured from the session file's `cwd` field (git repo name or directory name).
- `--tags <tag1,tag2,...>` — additional tags applied to all neurons created during this ingest. Additive with auto-captured tags.
- `--format json|text` — output format override (default from config).
- `--explain` — include extraction metadata in output: how many lines parsed, how many messages extracted, what Haiku returned before neuron/edge mapping.

### 11.2 — JSONL Parsing

The input file is read line-by-line. Each line is a JSON object. Lines that fail JSON parsing are skipped with a logged warning; they do not abort ingestion.

The following `type` values are relevant and extracted:

- `"user"` — human turn messages
- `"assistant"` — model response messages

All other types (`"file-history-snapshot"`, `"progress"`, `"system"`, and any unknown types) are ignored.

For `"user"` type lines, the message content is extracted from `message.content`. Content may be a string or an array of content blocks. Only text blocks are used; tool result blocks and image blocks are discarded.

For `"assistant"` type lines, the message content is extracted from `message.content` (array of content blocks). Only `"text"` type blocks are used; `"tool_use"` blocks are discarded.

Metadata extracted from each relevant line and carried forward:

- `timestamp` — ISO 8601 string from the line's `timestamp` field
- `cwd` — working directory at the time of the message, from the `cwd` field
- `sessionId` — the session UUID, from the `sessionId` field
- `role` — `"user"` or `"assistant"`

Empty or whitespace-only message bodies after extraction are skipped.

### 11.3 — Message Assembly for Haiku

After parsing, the extracted messages are assembled into a conversation transcript for Haiku. The transcript preserves turn order (by `timestamp`) and includes speaker labels (`Human:` and `Assistant:`).

The transcript is not the raw JSONL — it is a clean text reconstruction:

```
Human: <text content of user turn>
Assistant: <text content of assistant turn>
...
```

Tool use output and file contents that appear inline in user messages (from Claude Code's bash output quoting style) are included as-is — they may contain factual content worth extracting.

The assembled transcript is sent to Haiku in a single API call (see §11.4). If the transcript exceeds Haiku's input context limit, it is split into chunks and sent in multiple sequential calls; results are merged. The chunk boundary is between message turns, not mid-message.

### 11.4 — Haiku Extraction Call

Haiku is called via the Anthropic API using the API key obtained by reading the environment variable named by `haiku.api_key_env_var` in config. If the env var is not set or empty, the CLI exits with code 2 and message: `Haiku API key not configured. Set environment variable: <var_name>`.

The model used is the Claude Haiku model as configured. No other model is used for extraction.

The prompt instructs Haiku to extract from the conversation:

1. **Entities** — people, systems, tools, projects, concepts, files, commands, URLs, or other proper nouns that are discussed as meaningful things
2. **Facts** — declarative statements, decisions, observations, constraints, findings, or learned information that has lasting value beyond the conversation moment
3. **Relationships** — explicit or strongly implied connections between two entities or facts, with a stated reason for the connection

Haiku returns structured output. The required output structure is a JSON object with three arrays:

```json
{
  "entities": [
    { "id": "<local_ref>", "content": "<entity description>" }
  ],
  "facts": [
    { "id": "<local_ref>", "content": "<fact statement>" }
  ],
  "relationships": [
    { "from_id": "<local_ref>", "to_id": "<local_ref>", "reason": "<why connected>" }
  ]
}
```

`id` / `from_id` / `to_id` are local reference strings used only to link relationships back to entities and facts within the same Haiku response — they are not persistent IDs and are discarded after neuron/edge creation.

If Haiku returns malformed JSON or missing fields, the CLI logs a warning and attempts partial extraction from whatever is parseable. If nothing is parseable, ingestion fails with exit code 2.

### 11.5 — Neuron Creation from Extracted Data

Each entity and each fact becomes one neuron. Creation uses the standard neuron-add path from #6.

Auto-applied attributes on each created neuron:

- `source`: the absolute path of the ingested JSONL file
- `project`: auto-captured from the session's `cwd` field (git repo name or directory name), overridable via `--project`
- `ingested_session_id`: the `sessionId` from the JSONL file
- `ingest_role`: `"entity"` or `"fact"` — which extraction category this neuron came from

Auto-applied tags on each created neuron:

- `ingested` — marks this neuron as coming from batch ingestion, not manual capture
- Any tags from `--tags` flag
- `project:<name>` tag (same project auto-capture as manual neuron add)

Timestamp on each neuron: the timestamp of the CLI invocation (not the message timestamp from the source JSONL). The source conversation timestamp is preserved in an attribute `source_timestamp` derived from the earliest message timestamp in the session, to distinguish when the memory was captured vs. when the source conversation happened.

Each created neuron is embedded immediately using #5 (same as manual capture). If the embedding model is unavailable, neurons are stored without embeddings (the blank-vector re-embed path from #8 handles this later).

### 11.6 — Edge Creation from Extracted Relationships

Each relationship extracted by Haiku becomes one edge. Creation uses the standard edge-add path from #7.

The `from_id` and `to_id` in Haiku's response reference local entity/fact IDs. These are resolved to the actual neuron IDs created in §11.5 using the local reference map. If a local reference in a relationship does not match any created neuron (Haiku hallucinated a reference), that relationship is skipped with a warning.

Edge fields:

- `source_id`: the neuron ID corresponding to `from_id`
- `target_id`: the neuron ID corresponding to `to_id`
- `reason`: the `reason` string from Haiku's response, verbatim
- `weight`: 1.0 (default)

### 11.7 — Capture Context Linking

All neurons created in a single `memory batch ingest` invocation share a capture context. After all entity/fact neurons are created, edges are added connecting each created neuron to every other created neuron with `reason: "co-occurred in session <sessionId>"` and `weight: 0.5` (lower weight than explicit semantic relationships to indicate contextual co-occurrence rather than semantic connection).

This implements §2.3: the session itself is the context that links all neurons created within it.

Finding: The full mesh of co-occurrence edges (N*(N-1)/2 edges for N neurons) can be large for long sessions. See §11.10 for the ambiguity flag on this.

### 11.8 — Output

On success, the CLI outputs a summary object:

```json
{
  "status": "ok",
  "session_id": "<UUID from JSONL>",
  "source_file": "<absolute path>",
  "messages_parsed": <int>,
  "entities_extracted": <int>,
  "facts_extracted": <int>,
  "relationships_extracted": <int>,
  "neurons_created": <int>,
  "edges_created": <int>,
  "skipped_relationships": <int>,
  "warnings": ["<warning string>", ...]
}
```

`warnings` includes: skipped lines (parse failures), unresolved relationship references, partial Haiku extraction failures, embedding unavailability.

With `--explain`, the output also includes the raw Haiku extraction JSON under a `"haiku_extraction"` key.

With `--dry-run`, the output includes `"would_create"` with the same structure but no DB writes occur. Exit code 0.

Exit codes:

- `0` — ingestion completed (even if some warnings were generated)
- `2` — fatal error: file not found, Haiku API key missing, Haiku API error, unparseable Haiku response with zero extracted items

### 11.9 — Idempotency and Duplicate Handling

Re-ingesting the same JSONL file creates duplicate neurons. There is no deduplication in v1. Each invocation creates a new set of neurons and edges. The `source` attribute and `ingested_session_id` attribute allow a future deduplification pass to identify and merge duplicates, but v1 does not implement this.

This is consistent with the §10 edge case policy: conflicting/duplicate memories both live; most recent outranks by default.

---

## Constraints

1. **Haiku is required.** Ingestion cannot proceed without a valid Haiku API key. There is no fallback extraction path using a local model or rule-based heuristics.

2. **API costs are incurred at runtime.** Every `memory batch ingest` call makes at least one Haiku API call. Long sessions may result in multiple calls if chunking is needed.

3. **No synthesis in output.** Haiku extracts structured data; it does not summarize or synthesize. The CLI outputs the raw extracted entities, facts, and relationships as neurons and edges — not a condensed narrative.

4. **Opaque storage.** Created neurons are stored in the same opaque DB as manually created neurons. Source file path and session ID are attributes, not separate tables. The caller cannot browse the extraction by session through the DB directly — the CLI is the only interface.

5. **Single-threaded.** Ingestion is a serial operation: parse → call Haiku → create neurons → create edges → create context links. No parallelism within a single invocation.

6. **Embedding model loaded in-process.** If neurons are being embedded immediately (the default path), the embedding model is loaded once for the invocation and used for all N neurons created. This is the same model-loads-once-per-invocation constraint as §8.

7. **JSONL from Claude Code only.** The parser is designed for Claude Code's session format. Other JSONL formats are out of scope for v1.

---

## Edge Cases

**Empty file** — JSONL file exists but has zero lines or zero relevant message lines. CLI exits with code 2 and message: `No extractable messages found in: <path>`.

**File not found** — CLI exits with code 2 and message: `File not found: <path>`.

**File is not valid JSONL at all** — every line fails JSON parsing. Treated as zero relevant messages. Exit code 2.

**Haiku extracts zero entities and zero facts** — session may have been entirely tool-use with no meaningful content (e.g., a session that only ran bash commands). CLI exits with code 0, `neurons_created: 0`. This is not an error.

**Haiku API rate limit or transient error** — CLI exits with code 2 and includes the HTTP status and Haiku error message in the output. No partial writes are committed if the Haiku call fails before any neurons are created.

**Partial Haiku call failure (chunked session)** — if the first chunk succeeds but a subsequent chunk fails, neurons from the first chunk are already written. The CLI exits with code 2, reports how many neurons were created before the failure, and includes a warning that the ingest is incomplete. Re-running will create duplicates for the successful chunks.

**Very long session** — sessions with hundreds of turns generate large transcripts. Chunking is used transparently. There is no user-facing limit on session length.

**JSONL companion file (no extension)** — Claude Code stores sessions as both `<uuid>.jsonl` and `<uuid>` (no extension, same content). If the user passes the extensionless path, the CLI reads it as JSONL anyway (format detection by content, not extension).

**Relationship references a non-existent local ID** — Haiku hallucinated a reference not in its own entity/fact list. Relationship is skipped. Warning included in output.

**`--project` override with empty string** — rejected. Exit code 2. Project must be a non-empty string.

**DB is locked** — another CLI process is writing. SQLite WAL mode and busy timeout apply (same as all other write operations). If the timeout is exceeded, exit code 2.

---

## Findings (Ambiguities and Gaps)

**F-1: Haiku model version not specified in requirements.**
§3.2 says "Haiku" but does not specify which Haiku model version (e.g., `claude-haiku-3`, `claude-haiku-3-5`). The config spec (#2) records `haiku.api_key_env_var` but requirements do not specify a `haiku.model` config key. This should be resolvable in config, not hardcoded. Flagging for config spec (#2) to add `haiku.model` with a sensible default.

**F-2: Capture context edges — full mesh vs. star topology.**
§2.3 says "a conversation... is itself a context that links all neurons created or referenced within it." This is ambiguous between a full mesh (O(N²) edges, every neuron directly connected to every other) and a star topology (one central "session" neuron with edges to all created neurons). For large sessions with many extracted neurons, a full mesh creates a very large number of edges. The spec implements the full mesh at weight 0.5, but this decision should be validated with the user. A star topology (single session-context neuron) would be more scalable and would make the session itself a first-class node. Not in requirements either way.

**F-3: Source timestamp granularity.**
The spec proposes using the earliest message timestamp from the session as `source_timestamp`. An alternative is using the session's first-message timestamp. The requirements do not specify which timestamp to use or whether per-neuron timestamps should reflect the position of the extracted content within the conversation. For v1, a single session-level timestamp is proposed, but per-extracted-item timestamps could be valuable for temporal search.

**F-4: Chunking strategy for long sessions is unspecified.**
Requirements do not specify how to handle sessions that exceed Haiku's context window. The spec proposes sequential chunking at turn boundaries. The chunk size (in tokens or turns), overlap strategy, and whether extracted entities from one chunk should inform extraction in the next chunk (continuity context) are all unspecified. Leaving as an implementation decision with the constraint that each chunk's extraction must be independently valid.

**F-5: No deduplication in v1 creates re-ingest risk.**
Re-ingesting the same session creates duplicate neurons. This is consistent with §10, but for batch ingestion the risk is higher because users may ingest the same session multiple times accidentally. A simple guard (check `ingested_session_id` attribute against existing neurons before writing) could prevent this without full deduplication logic. Not in requirements. Flagging as a quality-of-life gap.

**F-6: `--format` flag behavior with `--dry-run`.**
When `--dry-run` is combined with `--format text`, the text representation of "would create N neurons" is not specified. The JSON output structure is defined; the text rendering is left to CLI dispatch (#1).
