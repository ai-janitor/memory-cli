# Stage 3 Checklist — v1

- [done] Survey existing codebases: minion-factory, skills library, current project
- [done] Survey skills library (~/.skills/) for overlapping skills — 8 of 241 scanned, no overlap
- [done] Technical feasibility: llama-cpp-python binding — confirmed, v0.3.16, embed() API
- [done] Technical feasibility: sqlite-vec — confirmed, pip install, 768-dim fine, sub-75ms at 100K
- [done] Technical feasibility: FTS5 — confirmed, built into Python sqlite3, BM25 scores accessible
- [done] Technical feasibility: nomic-embed-text-v1.5 — confirmed, Q8_0 at 140 MiB, GGUF on HuggingFace
- [done] Prior art: Mem0, Zep/Graphiti, Engram, Cog, LangMem, Hindsight, MemoClaw surveyed
- [done] Analyze QMD reference repo — hybrid search pipeline, two-step vector pattern, RRF fusion, schema
- [done] Analyze llama.cpp reference — embedding API, batch support, task prefixes
- [done] Document findings in .planning/v1/research/ (5 files + _findings.md summary)
- [done] Record upstream-affecting findings in upstream-feedback.md (8 items)
- [done] Present findings to user with key questions
- [done] User approved — R-1 accepted (task prefixes), R-7 accepted (edge weights in v1). Proceed to Stage 4.
