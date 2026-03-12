# llama-cpp-python Embedding Feasibility

## Verdict: Fully feasible

## Installation
```
pip install llama-cpp-python
```
Latest: v0.3.16

## Embedding API

Two methods on `Llama` class:

### `embed()` — raw, recommended
```python
embeddings = llm.embed(["text1", "text2"], normalize=True, truncate=True)
# Returns: List[List[float]] — list of 768-dim vectors
```

### `create_embedding()` — OpenAI-compatible
```python
response = llm.create_embedding(["text1", "text2"])
# Returns dict with response["data"][0]["embedding"]
```

## Model Loading
```python
from llama_cpp import Llama
llm = Llama(
    model_path="nomic-embed-text-v1.5.Q8_0.gguf",
    embedding=True,    # REQUIRED — must be set at construction
    n_ctx=2048,        # default 512, model supports up to 8192
    n_batch=512,
    verbose=False,
)
```

## nomic-embed-text-v1.5 GGUF

Official: https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF

| Quant | Size | MSE vs F32 |
|-------|------|------------|
| F16 | 262 MiB | 4.21e-10 |
| Q8_0 | 140 MiB | 5.79e-06 |
| Q4_K_M | 81 MiB | 2.42e-04 |

Recommended: Q8_0 (140 MiB) — negligible quality loss.

Download: `huggingface-cli download nomic-ai/nomic-embed-text-v1.5-GGUF nomic-embed-text-v1.5.Q8_0.gguf`

## CRITICAL: Task Instruction Prefixes Required

nomic-embed-text-v1.5 REQUIRES text prefixes:
- `search_document: <text>` — for indexing/storing
- `search_query: <text>` — for search queries
- `clustering: <text>` — for clustering
- `classification: <text>` — for classification

Must be prepended to input text before calling embed(). Without them, embedding quality degrades significantly.

## Matryoshka Dimensions
Supports variable dimensions via truncation: 768, 512, 256, 128, 64.
MTEB scores: 768d=62.28, 256d=61.04, 64d=56.10.

## Gotchas
1. `embedding=True` is mandatory at construction — cannot toggle later
2. Default n_ctx=512 is low — set to 2048+
3. Llama object is NOT thread-safe — use mutex if sharing
4. Model loads into RAM at construction (~140 MiB for Q8_0, sub-second)
5. Batch support confirmed — List[str] input works
