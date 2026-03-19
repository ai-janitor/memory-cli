# =============================================================================
# batch_reembed_blank_and_stale.py — Orchestrate batch re-embed operation
# =============================================================================
# Purpose:     Find all blank and stale neurons, generate embeddings in batches,
#              write vectors to vec0, and report progress. This is the top-level
#              orchestrator for the "memory embed refresh" command.
# Rationale:   Neurons can become blank (model missing at write time) or stale
#              (content updated after embedding). This module finds them all,
#              processes them in configurable batch sizes using the batch embed
#              API for efficiency, and tolerates partial completion — already-
#              processed batches are committed, failures don't roll back progress.
# Responsibility:
#   - Discover blank + stale neurons via stale_and_blank_vector_detection
#   - Load each neuron's content + tags to build embedding input
#   - Process in batches using embed_batch (operation="index")
#   - Write vectors via write_vectors_batch
#   - Report progress: blank count, stale count, processed, failed
#   - Partial completion OK — each batch committed independently
# Organization:
#   ReembedProgress (dataclass) — progress/result tracking
#   batch_reembed(conn, project_id?, batch_size?) -> ReembedProgress
# =============================================================================

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field

from .embedding_input_content_plus_tags import build_embedding_input
from .embed_single_and_batch import embed_batch
from .stale_and_blank_vector_detection import (
    get_all_reembed_candidates,
    get_blank_neuron_ids,
    get_stale_neuron_ids,
)
from .vector_storage_vec0_write import write_vectors_batch

logger = logging.getLogger(__name__)


@dataclass
class ReembedProgress:
    """Track progress and results of a batch re-embed operation.

    Attributes:
        blank_count: Number of neurons with no existing embedding.
        stale_count: Number of neurons with outdated embeddings.
        total_candidates: Total neurons needing (re-)embedding (blank + stale, deduped).
        processed: Number of neurons successfully embedded and stored.
        failed: Number of neurons that failed to embed or store.
        failed_neuron_ids: List of neuron IDs that failed, for debugging.
    """

    blank_count: int = 0
    stale_count: int = 0
    total_candidates: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    failed_neuron_ids: list[int] = field(default_factory=list)


def batch_reembed(
    conn: sqlite3.Connection,
    model,
    project_id: str | None = None,
    batch_size: int = 32,
) -> ReembedProgress:
    """Find blank and stale neurons, embed them in batches, and write vectors.

    Processes in configurable batch sizes for memory efficiency. Each batch
    is committed independently — if a batch fails, previously committed
    batches are preserved (no global rollback).

    Args:
        conn: An open sqlite3.Connection with WAL mode.
        model: A loaded Llama instance configured for embedding.
        project_id: Optional project filter. None means all projects.
        batch_size: Number of neurons to embed per batch. Default 32.
                    Larger batches are more efficient but use more memory.

    Returns:
        ReembedProgress dataclass with counts and any failure details.
    """
    progress = ReembedProgress()

    # --- Step 1: Discover candidates ---
    # blank_ids = get_blank_neuron_ids(conn, project_id)
    # stale_ids = get_stale_neuron_ids(conn, project_id)
    # all_ids = get_all_reembed_candidates(conn, project_id)
    # progress.blank_count = len(blank_ids)
    # progress.stale_count = len(stale_ids)
    # progress.total_candidates = len(all_ids)
    blank_ids = get_blank_neuron_ids(conn, project_id)
    stale_ids = get_stale_neuron_ids(conn, project_id)
    all_ids = get_all_reembed_candidates(conn, project_id)
    progress.blank_count = len(blank_ids)
    progress.stale_count = len(stale_ids)
    progress.total_candidates = len(all_ids)

    # --- Step 2: Early exit if nothing to do ---
    # If all_ids is empty: return progress (all zeros)
    if not all_ids:
        return progress

    # --- Step 3: Process in batches ---
    # for batch_start in range(0, len(all_ids), batch_size):
    #   batch_ids = all_ids[batch_start : batch_start + batch_size]
    for batch_start in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[batch_start : batch_start + batch_size]

        #   --- Step 3a: Load neuron content + tags for this batch ---
        #   For each neuron_id in batch_ids:
        #     Fetch neuron content and tags from DB
        #     Build embedding input via build_embedding_input(content, tags)
        #   Collect as list of (neuron_id, embedding_input) pairs
        pairs: list[tuple[int, str, str]] = []  # (neuron_id, embedding_input, input_hash)
        for neuron_id in batch_ids:
            row = conn.execute(
                "SELECT content, embedding_input_hash FROM neurons WHERE id = ?", (neuron_id,)
            ).fetchone()
            if row is None:
                logger.warning("Neuron %s not found during batch reembed, skipping", neuron_id)
                progress.failed += 1
                progress.failed_neuron_ids.append(neuron_id)
                continue
            content = row[0]
            existing_hash = row[1]
            # Load associated tags
            tag_rows = conn.execute(
                """
                SELECT t.name FROM tags t
                JOIN neuron_tags nt ON t.id = nt.tag_id
                WHERE nt.neuron_id = ?
                """,
                (neuron_id,),
            ).fetchall()
            tags = [r[0] for r in tag_rows]
            embedding_input = build_embedding_input(content, tags)
            input_hash = hashlib.sha256(embedding_input.encode()).hexdigest()
            # Skip if embedding input hasn't actually changed
            if existing_hash is not None and input_hash == existing_hash:
                logger.debug("Neuron %s hash unchanged, skipping re-embed", neuron_id)
                progress.skipped += 1
                continue
            pairs.append((neuron_id, embedding_input, input_hash))

        if not pairs:
            continue

        #   --- Step 3b: Batch embed ---
        #   texts = [input_text for _, input_text in pairs]
        #   vectors = embed_batch(texts, operation="index")
        #   If vectors is None:
        #     All in this batch failed (model missing)
        #     progress.failed += len(batch_ids)
        #     progress.failed_neuron_ids.extend(batch_ids)
        #     continue
        texts = [input_text for _, input_text, _ in pairs]
        try:
            vectors = embed_batch(model, texts, "index")
        except Exception as e:
            logger.warning("embed_batch failed for batch starting at %s: %s", batch_start, e)
            progress.failed += len(pairs)
            progress.failed_neuron_ids.extend([nid for nid, _, _ in pairs])
            continue

        if vectors is None:
            # Model missing — all in this batch failed
            progress.failed += len(pairs)
            progress.failed_neuron_ids.extend([nid for nid, _, _ in pairs])
            continue

        #   --- Step 3c: Write vectors to vec0 and update hashes ---
        try:
            neuron_vector_pairs = list(zip([nid for nid, _, _ in pairs], vectors))
            write_vectors_batch(conn, neuron_vector_pairs)
            # Update embedding_input_hash and embedding_updated_at for each neuron
            import time
            now_ms = int(time.time() * 1000)
            for nid, _, ihash in pairs:
                conn.execute(
                    "UPDATE neurons SET embedding_input_hash = ?, embedding_updated_at = ? WHERE id = ?",
                    (ihash, now_ms, nid)
                )
            conn.commit()
            progress.processed += len(pairs)
        except (sqlite3.Error, ValueError) as e:
            logger.warning("write_vectors_batch failed for batch starting at %s: %s", batch_start, e)
            progress.failed += len(pairs)
            progress.failed_neuron_ids.extend([nid for nid, _, _ in pairs])

    # --- Step 4: Return final progress ---
    # return progress
    return progress
