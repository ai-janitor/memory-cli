# sqlite-vec + FTS5 Feasibility

## Verdict: Fully feasible. Both confirmed working in Python.

## sqlite-vec

### Installation
```
pip install sqlite-vec
```

### Loading in Python
```python
import sqlite3
import sqlite_vec

db = sqlite3.connect("memory.db")
db.enable_load_extension(True)
sqlite_vec.load(db)
db.enable_load_extension(False)
```

### GOTCHA: macOS system Python
macOS system SQLite does NOT support extension loading. Fix: use Homebrew Python or pysqlite3 package.

### SQL Syntax
```sql
-- Create vector table
CREATE VIRTUAL TABLE vec_neurons USING vec0(
  neuron_id INTEGER PRIMARY KEY,
  embedding float[768]
);

-- Insert (blob format via Python)
INSERT INTO vec_neurons(neuron_id, embedding) VALUES (?, ?);
-- Vector as struct.pack(f'{768}f', *values)

-- KNN query
SELECT neuron_id, distance
FROM vec_neurons
WHERE embedding MATCH :query_vector AND k = 20
ORDER BY distance;
```

### Performance (768-dim)
- 1K vectors: trivial (<5ms)
- 100K vectors: ~75ms per query
- Storage: 100K vectors at 768-dim float32 = ~300 MB

### Critical: Two-step queries
sqlite-vec + JOINs cause hangs (known issue). Query vec table alone first, then JOIN results to main tables.

## FTS5

### Built into Python sqlite3 — zero setup needed

```sql
CREATE VIRTUAL TABLE neurons_fts USING fts5(
  content,
  tags,
  tokenize='porter unicode61'
);
```

### BM25 Scoring
```sql
SELECT rowid, bm25(neurons_fts, 10.0, 1.0) as score
FROM neurons_fts
WHERE neurons_fts MATCH 'search terms'
ORDER BY score;  -- ascending (raw scores are negative)
```

Raw BM25 scores are negative. Normalize: `|x| / (1 + |x|)` → [0, 1).

### Coexistence
FTS5 and sqlite-vec coexist in same database, no conflicts.

## Hybrid Fusion: RRF

Reciprocal Rank Fusion — uses rank positions, not raw scores. No normalization needed.

```python
def reciprocal_rank_fusion(fts_results, vec_results, k=60):
    scores = {}
    for rank, doc_id in enumerate(fts_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    for rank, (doc_id, _) in enumerate(vec_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

k=60 is the standard. Used by Azure AI Search, Weaviate, etc.
