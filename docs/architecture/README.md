---
type: index
title: memory-cli architecture decisions (ADR index)
description: Append-only Architecture Decision Records. New decision that changes an earlier one = a NEW ADR that supersedes it. Significant structural decisions live here, not in chat/commits/code.
tags: [adr, architecture, index, decisions]
timestamp: 2026-07-10
---

# Architecture Decision Records

- Format: `NNNN-kebab-title.md`, Status/Date header, Context/Decision/
  Consequences (+ Alternatives). Append-only — a changed decision gets a NEW
  ADR that supersedes; never edit a sealed ADR in place except Status.
- Standard: ADR (Nygard) + GLOBAL-764 (every droid project keeps this folder).
- Entry catalog parent: [../README.md](../README.md).

## Records

- [0001-resident-embedding-daemon.md](0001-resident-embedding-daemon.md) —
  one warm process holds the GGUF; CLI embeds over a unix socket; in-process
  fallback, never hang; embed-only. **Supersedes**
  `diagnostics/0001` §3 (daemon DEFER). `status: accepted` (gate PASS, invariants verified live).
