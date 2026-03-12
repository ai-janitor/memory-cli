# Light Search Pipeline

Covers: BM25 keyword matching via FTS5 (porter unicode61), vector similarity via
sqlite-vec (two-step query pattern to avoid JOIN hangs), RRF fusion (reciprocal
rank fusion, k=60, rank-based), spreading activation (Python BFS, linear decay
0.75/0.50/0.25, configurable rate, visited set for cycles, edge weight modulation),
tag filtering (AND via --tags, OR via --tags-any), temporal decay (recent neurons
rank higher), fan-out depth (--fan-out-depth N, default 1), pagination (--limit N
--offset M), --explain debug mode (BM25 score, vector score, hop distance, decay,
temporal weight breakdown).

Requirements traced: §4.1 Light Search, §4.3 Search Output, §11 Spreading Activation.
Dependencies: #3 Schema, #4 Tags, #5 Embedding, #6 Neurons, #7 Edges.
