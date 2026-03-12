# Spec #5 — Embedding Engine

## Purpose

The embedding engine is the exclusive in-process interface between memory-cli and the
llama-cpp-python binding. It is responsible for: loading the embedding model once per
CLI invocation, prepending task-appropriate prefixes to input text, producing 768-dimensional
float vectors from text inputs (single and batch), writing those vectors to the vec0
virtual table, and supporting batch re-embedding of blank and stale vectors. All other
specs that need vectors call through this component — no other spec touches the Llama
object or writes embedding data directly.

---

## Requirements Traceability

| Requirement | Source |
|---|---|
| Embedding model loaded in-process via llama-cpp-python | §8 |
| Model: nomic-embed-text-v1.5, GGUF, Q8_0 quantization, 768 dimensions | §8 |
| Model loads once per CLI invocation | §8 |
| Embedding input: content text + tags concatenated | §8 |
| Task prefix prepended transparently: `search_document:` on store, `search_query:` on search | §8 |
| Storage format is separate from embedding input format | §8 |
| Embedding is decoupled — can store without embedding, re-embed later | §8 |
| Batch re-embed: finds blank vectors (never embedded) and stale vectors (content updated after vector timestamp) | §8 |
| Search queries also need embedding (same model, same invocation) | §8 |
| Vector dimension enforcement — all vectors must match configured dimensions | §9 |
| Model change in config marks all existing vectors stale | §9 |

---

## Dependencies

- **#2 Config & Initialization** — provides model path (GGUF file location), n_ctx setting,
  and any other model construction parameters stored in config.json.
- **#3 Schema & Migrations** — provides the vec0 virtual table (`vec_neurons`) into which
  vectors are written, and the neurons table columns that track embedding state
  (vector timestamp, stale flag).

---

## Behavior

### B1. Model Loading

- The embedding model is loaded at most once per CLI invocation. It is NOT reloaded
  between multiple embedding calls within a single process.
- The model file is the nomic-embed-text-v1.5.Q8_0.gguf GGUF. The path is read from
  config.json.
- The model must be initialized with `embedding=True`. This flag cannot be changed after
  construction — it must be set at load time.
- Context length (`n_ctx`) is read from config.json. The default is 2048. The model
  supports up to 8192, but 2048 is the configured default. Callers do not specify n_ctx;
  it comes from config.
- If the model file does not exist at the configured path, the engine reports a clear
  error referencing the missing path and the config key that should be updated. No
  vector operation proceeds.
- The model is NOT loaded on import or initialization of the module — it is loaded lazily
  on first use within an invocation, then held for the duration of that process.
- Model load is silent (verbose=False). Internal llama.cpp log output is suppressed.

### B2. Task Prefix Handling

- Every input text has a task prefix prepended by the engine before calling the underlying
  model. The prefix is determined by the operation type, not by the caller's text.
- Two operation types exist:
  - **Index** (storing a neuron's embedding): prefix `search_document: `
  - **Query** (embedding a search query): prefix `search_query: `
- The caller specifies the operation type (index vs. query). The engine prepends the
  prefix transparently. The raw text and the prefixed text are never mixed up in storage.
- The prefix is prepended as-is with a single trailing space before the input text.
  No other transformation is applied to the prefix or the text.
- The prefix is an implementation detail of the engine. No other spec constructs or
  manages prefixed strings.

### B3. Embedding Input Construction

- The embedding input for a neuron is: `<task_prefix><content_text> <tags_string>`
- The tags string is the space-separated list of tag names associated with the neuron,
  normalized to lowercase (per tag registry behavior from #4). Tags carry semantic
  meaning and are included in the embedding input.
- The content text is the raw neuron content — not HTML-escaped, not truncated by the
  caller. If the combined input exceeds the model's configured n_ctx, the engine applies
  truncation (controlled by the `truncate=True` parameter to `embed()`).
- The storage format (what is saved in the neurons table) is separate from the embedding
  input format. The prefixed, tag-appended string is used only for generating the vector —
  it is never stored as the neuron's content.

### B4. Single Embedding

- The engine can embed a single text input and return a single 768-dimensional float
  vector.
- The returned vector is L2-normalized (normalize=True). Normalization enables cosine
  similarity via inner product, which sqlite-vec uses internally.
- The caller provides the text and operation type. The engine prepends the prefix and
  calls the model.

### B5. Batch Embedding

- The engine can embed a list of text inputs in one model call and return a corresponding
  list of 768-dimensional float vectors.
- All inputs in a batch share the same operation type (either all index or all query).
  Mixed-type batches are not supported in a single call.
- Batch embedding is more efficient than N sequential single-embed calls. The internal
  model call accepts a List[str] and returns List[List[float]].
- The order of returned vectors corresponds to the order of input texts.
- If the batch is empty (empty list), the engine returns an empty list without calling
  the model.

### B6. Vector Storage

- After generating a vector, the engine writes it to the vec0 virtual table
  (`vec_neurons`) keyed by neuron_id.
- The vector is serialized to binary format (32-bit floats, packed) before insertion, as
  required by sqlite-vec's blob storage format.
- The engine also updates the neuron's embedding timestamp and clears the stale flag in
  the neurons table as part of the same write operation. These two writes (vec table +
  neuron metadata) are atomic within a transaction.
- The engine does NOT handle neuron creation or content storage — it only handles
  embedding generation and vector persistence.

### B7. Stale and Blank Vector Detection

- A vector is **blank** when the neuron has never been embedded: the vec0 table has no
  row for that neuron_id.
- A vector is **stale** when the neuron's content was updated after the embedding
  timestamp stored in the neurons table. Staleness is detected by comparing the neuron's
  `updated_at` timestamp against its `embedded_at` timestamp.
- The engine exposes a query interface: given an optional filter (project, tag, or
  "all"), return the list of neuron IDs that are blank or stale.
- This query is used by the batch re-embed operation.

### B8. Batch Re-Embed Operation

- The batch re-embed operation finds all blank and stale vectors (using B7), generates
  fresh embeddings for each affected neuron, and writes the updated vectors.
- The input construction for each neuron during re-embed follows B3: content + tags,
  using the `search_document:` prefix.
- Re-embed processes neurons in batches (not one-at-a-time) to take advantage of the
  model's batch API (B5).
- Re-embed reports progress: how many neurons were found blank, how many stale, how many
  were processed successfully, and how many failed (if any).
- Re-embed is triggered by `memory batch re-embed`. It is not triggered automatically
  on startup.
- If the model is unavailable during re-embed, the operation fails with a clear error.
  Partially-completed re-embeds are not rolled back — neurons that were already
  re-embedded remain embedded; the rest stay blank/stale.

### B9. Query Embedding

- Search queries (light and heavy search) embed the query string using the `search_query:`
  prefix.
- For heavy search with query expansion, multiple query variants may be generated. These
  are batched into a single embed() call (same invocation, same loaded model) to avoid
  redundant model usage.
- The query vector is returned to the caller (light search pipeline); it is not stored
  anywhere.

### B10. Embedding Unavailability (Fallback)

- If the model file is not found or the model fails to load, operations that require
  embedding (neuron add with immediate embed, search with vector component) behave as
  follows:
  - Neuron add: stores the neuron without embedding (blank vector state). The neuron is
    written to the DB. A warning is included in the output.
  - Search: falls back to BM25-only search (no vector component). A warning is included
    in the output noting that vector similarity is unavailable.
- The engine does not silently swallow errors. All failures produce output that explains
  what happened and what the caller can do (e.g., check model path in config).

### B11. Thread Safety

- The Llama object is NOT thread-safe. The engine is designed for single-process, single-
  threaded use within one CLI invocation.
- If concurrent access patterns emerge (multiple agents running memory-cli simultaneously),
  each process has its own model instance. Coordination is at the SQLite level (WAL mode,
  busy timeout), not at the embedding engine level.
- No mutex or locking is required within a single CLI invocation since embedding calls
  are sequential in a single process.

### B12. Vector Dimension Enforcement

- The engine enforces that all vectors produced are exactly 768 dimensions.
- On vector write, if the dimension of the generated vector does not match the configured
  dimension (from config.json and DB metadata), the write is rejected with an error.
- This enforcement is a guard against misconfiguration (e.g., wrong model loaded,
  Matryoshka truncation applied unexpectedly).
- The engine does NOT support Matryoshka dimension truncation in v1. The full 768-dim
  vector is always used.

---

## Constraints

- **Model loaded at most once per invocation.** No re-loading within a process.
- **`embedding=True` is mandatory** at Llama construction. Cannot be toggled post-init.
- **n_ctx default is 2048.** Must be explicitly set — the llama-cpp-python default (512)
  is too small and causes silent truncation at 512 tokens.
- **Task prefixes are required.** Omitting them degrades embedding quality significantly
  for nomic-embed-text-v1.5. The engine always applies them; callers cannot bypass them.
- **Q8_0 quantization is the default recommended model.** 140 MiB on disk, sub-second
  load, negligible quality loss (MSE 5.79e-06 vs F32).
- **Vectors are 768-dimensional float32.** Stored as packed binary blobs in sqlite-vec.
- **Normalization is always applied** (`normalize=True`). The engine does not return
  un-normalized vectors.
- **Truncation is always applied** (`truncate=True`). Inputs exceeding n_ctx are silently
  truncated by the model binding, not rejected.
- **Batch size is not artificially capped** by the engine in v1. The underlying model
  binding handles batching internally. If performance issues arise with very large batches,
  this is noted as a future constraint.
- **The GGUF model file is not bundled.** It must be downloaded separately. The
  `memory init` command (spec #2) documents the download step; the embedding engine
  itself validates the file exists at the configured path.

---

## Edge Cases

### EC1. Model file missing at query time
If a user runs `memory neuron search` and the model file is absent, vector search is
skipped and BM25-only results are returned with a warning. The exit code reflects success
(results were returned), but the warning is present in output.

### EC2. Model file missing at write time
If a user runs `memory neuron add` and the model file is absent, the neuron is stored
(content, tags, metadata) but the vector is blank. The output warns that the neuron was
stored without embedding and suggests running `memory batch re-embed` after fixing the
model path.

### EC3. Empty content neuron
A neuron with empty content (if the schema allows it) would produce an embedding of just
the task prefix + tags. This is not an engine error — the engine embeds whatever input
it receives. Schema-level constraints on empty content are spec #6's concern.

### EC4. Neuron with no tags
Embedding input reduces to `<prefix><content>` (no tag string). This is valid. The
engine does not inject placeholder text when tags are absent.

### EC5. Re-embed interrupted mid-batch
If `memory batch re-embed` is interrupted (signal, crash), neurons processed before the
interruption retain their fresh vectors. Neurons not yet processed remain blank or stale.
The next re-embed run will pick up remaining neurons. No compensation or recovery logic
is required — the stale detection query handles this naturally.

### EC6. Model changed in config
When the model name/path in config.json is changed, spec #13 (Metadata & Integrity)
detects the drift and marks all existing vectors stale. The embedding engine itself does
not detect model changes — it loads whatever path is configured. The stale marking is
#13's responsibility; re-embedding is then triggered via `memory batch re-embed`.

### EC7. Batch with one element
A batch of one text input is valid and follows the same code path as a multi-element
batch. The engine does not optimize single-element batches to use a different API call.

### EC8. Very long neuron content
If neuron content exceeds n_ctx tokens, the model truncates at the token boundary.
The stored content is NOT truncated — only the embedding input is truncated. The raw
content in the neurons table is always preserved in full.

### EC9. Tags change after embedding
When tags are added or removed from a neuron after initial embedding, the neuron's
`updated_at` timestamp advances past `embedded_at`, marking the vector stale. This is
correct behavior — tag changes affect the embedding input and thus the vector should be
refreshed. Re-embed will pick it up.

---

## Findings

### F1. Model size discrepancy in requirements
The clean requirements (§8) state "~260MB" but Q8_0 is 140 MiB. F16 is 262 MiB. The
recommended quantization is Q8_0. The spec uses Q8_0 as the default. The requirements
text is slightly stale but was noted in upstream feedback (R-2). No action required —
the spec is correct.

### F2. n_batch parameter not specified in requirements
The research note shows `n_batch=512` as a model construction parameter. Requirements
do not specify this. It controls how many tokens are processed in parallel during
embedding generation (internal to llama.cpp). This is a HOW concern — the spec does
not prescribe it. The implementation can use a reasonable default (512) or make it
configurable. Flagged for implementer awareness.

### F3. "Model loads once per CLI invocation" — singleton semantics unspecified
The requirement says the model loads once per invocation. The spec interprets this as:
a single Llama instance is created lazily on first use and held for the process lifetime.
The mechanism (module-level singleton, dependency injection, or context object) is not
prescribed — that is a HOW decision. The WHAT is: no more than one load per process,
no unloading and reloading within a single invocation.

### F4. Batch re-embed batch size
The spec says neurons are processed "in batches" but does not specify the batch size.
This is a HOW decision. The implementer should use a reasonable internal chunk size
(e.g., 32-64 neurons per embed() call) to balance memory usage and throughput. This
could be made configurable in the future but is not a v1 requirement.

### F5. Matryoshka dimensions explicitly excluded
The research confirms nomic-embed-text-v1.5 supports 768, 512, 256, 128, and 64 dimensions
via truncation. The spec explicitly uses only 768. If a future version wants to support
smaller dimensions (e.g., for storage efficiency), this is a dimension-configuration
change that would require re-embedding all vectors. This is noted as a future concern,
not a v1 constraint.

### F6. `create_embedding()` vs `embed()` — spec uses `embed()`
llama-cpp-python provides both `embed()` (raw, returns List[List[float]]) and
`create_embedding()` (OpenAI-compatible dict). The spec designates `embed()` as the
interface because it returns vectors directly without dict unwrapping. This is a minor
HOW preference that the implementer should follow for simplicity.

### F7. No streaming or async embedding
The spec does not address streaming or async embedding. All embedding calls are
synchronous. This is consistent with memory-cli being a synchronous CLI tool. Async
embedding is not a v1 concern.
