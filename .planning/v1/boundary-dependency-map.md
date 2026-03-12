# Boundary Dependency Map — v1

Every edge in the dependency graph with contract type and status.

---

## Boundary: #1 CLI Dispatch ↔ All Noun Handlers (#4, #6, #7, #8, #9, #10, #11, #12, #13)
- Contract type: signal (function registration — each noun registers its verb handlers with the dispatcher)
- Status: [pending]
- Edges: dispatcher routes `memory <noun> <verb>` to the correct handler function; handler returns structured data; dispatcher formats output (JSON/text)

## Boundary: #2 Config ↔ #3 Schema
- Contract type: data shape (config provides db_path string to schema module for connection)
- Status: [pending]
- Edges: schema module reads db_path from loaded config to open/create SQLite connection

## Boundary: #2 Config ↔ #5 Embedding Engine
- Contract type: data shape (config provides model_path, n_ctx, n_gpu_layers to embedding module)
- Status: [pending]
- Edges: embedding engine reads model settings from config to construct Llama instance

## Boundary: #2 Config ↔ #9 Heavy Search
- Contract type: data shape (config provides Haiku API key env var name)
- Status: [pending]
- Edges: heavy search reads API key config to call Haiku

## Boundary: #2 Config ↔ #11 Conversation Ingestion
- Contract type: data shape (config provides Haiku API key env var name)
- Status: [pending]
- Edges: ingestion reads API key config to call Haiku

## Boundary: #3 Schema ↔ #4 Tag/Attr Registries
- Contract type: data shape (table names, column names for tag/attr registry tables)
- Status: [pending]
- Edges: tag/attr modules read/write to registry tables defined by schema

## Boundary: #3 Schema ↔ #5 Embedding Engine
- Contract type: data shape (vec0 virtual table name, embedding column spec, neuron_id column)
- Status: [pending]
- Edges: embedding engine writes vectors to vec0 table; reads for staleness check

## Boundary: #3 Schema ↔ #6 Neuron CRUD
- Contract type: data shape (neurons table columns, FTS5 table name)
- Status: [pending]
- Edges: neuron CRUD reads/writes neurons table; FTS5 triggers auto-sync

## Boundary: #3 Schema ↔ #7 Edge Management
- Contract type: data shape (edges table columns: source_id, target_id, reason, weight, created_at)
- Status: [pending]
- Edges: edge module reads/writes edges table

## Boundary: #3 Schema ↔ #8 Light Search
- Contract type: data shape (FTS5 table for BM25, vec0 table for vector search, edges table for activation)
- Status: [pending]
- Edges: search queries FTS5, vec0 (two-step), and edges tables

## Boundary: #4 Tags ↔ #6 Neuron CRUD
- Contract type: signal (tag resolution — neuron add calls tag registry to resolve names → IDs, auto-create)
- Status: [pending]
- Edges: neuron add receives tag names, calls tag registry to get/create IDs, stores neuron-tag associations

## Boundary: #4 Tags ↔ #8 Light Search
- Contract type: signal (tag filtering — search calls tag module to resolve filter tags, apply AND/OR logic)
- Status: [pending]
- Edges: search receives --tags/--tags-any flags, calls tag module to resolve to IDs, applies filter

## Boundary: #5 Embedding ↔ #6 Neuron CRUD
- Contract type: signal (embed on write — neuron add calls embedding engine after storing content)
- Status: [pending]
- Edges: neuron add passes content + tags text to embedding engine; engine returns vector; neuron module stores vector via schema

## Boundary: #5 Embedding ↔ #8 Light Search
- Contract type: signal (query embedding — search calls embedding engine to embed the search query)
- Status: [pending]
- Edges: search passes query text to embedding engine with search_query prefix; engine returns vector for vec0 KNN query

## Boundary: #6 Neurons ↔ #7 Edge Management
- Contract type: signal (--link flag — neuron add delegates to edge module to create edge with reason)
- Status: [pending]
- Edges: neuron add calls edge add when --link is provided; edge module validates both neuron IDs exist

## Boundary: #6 Neurons ↔ #10 Traversal
- Contract type: signal (timeline — traversal reads neurons ordered by timestamp from a starting neuron)
- Status: [pending]
- Edges: traversal queries neurons table for chronological neighbors

## Boundary: #7 Edges ↔ #8 Light Search
- Contract type: signal (spreading activation — search calls edge traversal for graph fan-out)
- Status: [pending]
- Edges: search passes seed neuron IDs to spreading activation BFS; BFS queries edges table for neighbors; returns activated neuron IDs with scores

## Boundary: #7 Edges ↔ #10 Traversal
- Contract type: signal (goto — traversal reads edges from a neuron to follow connections)
- Status: [pending]
- Edges: goto traversal queries edges table for connected neurons

## Boundary: #8 Light Search ↔ #9 Heavy Search
- Contract type: signal (re-rank — heavy search takes light search results list, returns re-ranked list)
- Status: [pending]
- Edges: heavy search receives scored neuron list from light search; calls Haiku for re-ranking and query expansion; may re-invoke light search with expanded terms; returns re-ranked results in same format

## Boundary: #13 Metadata ↔ #2 Config
- Contract type: data shape (drift detection compares config values against DB metadata values)
- Status: [pending]
- Edges: metadata module reads config (model name, dimensions) and compares to DB metadata table

## Boundary: #13 Metadata ↔ #5 Embedding
- Contract type: signal (model change detection — metadata marks vectors stale when model config changes)
- Status: [pending]
- Edges: metadata module detects model name mismatch → marks all vectors as stale in embedding/vector tables
