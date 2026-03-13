# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/batch_noun_handler.py
# PURPOSE: Register the "batch" noun with the CLI dispatch registry.
#          Batch provides bulk operations: export, import, reembed.
# RATIONALE: Agents and migration scripts need bulk operations that don't
#            require one-at-a-time CLI calls. Export/import enables backup and
#            transfer. Reembed handles model upgrades (regenerate all vectors).
# RESPONSIBILITY:
#   - Define verb map: export, import, reembed
#   - Define flag/arg specs for each verb
#   - Register with entrypoint dispatch via register_noun()
#   - Each verb handler: parse args, validate, call storage/embedding, return Result
# ORGANIZATION:
#   1. Verb handler stubs
#   2. Noun registration at module level
# =============================================================================

from __future__ import annotations

from typing import List, Any

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun


# =============================================================================
# VERB: export — dump database contents to a portable format
# =============================================================================
def handle_export(args: List[str], global_flags: Any) -> Any:
    """Export database contents to a portable format (JSON lines or similar).

    Args:
        args: [--output <path>, --type <neuron|edge|all>, --include-archived]
        global_flags: Parsed global flags.

    Returns:
        Result confirming export with path and counts.

    Pseudo-logic:
    1. Parse optional flags:
       - --output <path>: output file path (default: stdout)
       - --type <neuron|edge|all>: what to export (default "all")
       - --include-archived: include archived neurons (default False)
    2. Delegate to storage: batch_store.export(type, include_archived)
    3. If --output provided:
       a. Write to file at path
       b. Return Result with data={"path": path, "count": N}
    4. If no --output:
       a. Stream to stdout (data field holds the exported content)
    5. Return Result(status="ok", data={"exported": count, "path": path_or_stdout})
    6. Error path: DB not initialized, write permission denied, etc.
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import extract_flag
    try:
        rest = list(args)
        output, rest = extract_flag(rest, "--output")
        conn = get_connection(global_flags)
        from memory_cli.export_import import export_neurons
        data = export_neurons(conn)
        if output:
            import json
            from pathlib import Path
            Path(output).write_text(json.dumps(data, indent=2), encoding="utf-8")
            return Result(status="ok", data={"path": output, "neurons": len(data.get("neurons", []))})
        return Result(status="ok", data=data)
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: import — load data from a portable format into the database
# =============================================================================
def handle_import(args: List[str], global_flags: Any) -> Any:
    """Import data from a portable format into the database.

    Args:
        args: [--input <path>, --merge|--replace]
        global_flags: Parsed global flags.

    Returns:
        Result confirming import with counts.

    Pseudo-logic:
    1. Parse flags:
       - --input <path>: input file path (required, or stdin)
       - --merge: merge with existing data (default, skip duplicates)
       - --replace: replace existing data (dangerous, requires confirmation)
    2. Validate: input file exists and is readable
    3. Validate: data format is correct (JSON lines with expected fields)
    4. Delegate to storage: batch_store.import_data(data, mode)
    5. For each imported record:
       a. Insert or merge neuron
       b. Trigger embedding generation for new/changed content
       c. Restore edges, tags, attrs
    6. Return Result(status="ok", data={
         "imported": count, "skipped": skip_count, "errors": error_count
       })
    7. Error path: file not found, malformed data, DB errors
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        extract_flag, extract_bool_flag,
    )
    try:
        rest = list(args)
        input_path, rest = extract_flag(rest, "--input")
        replace_mode, rest = extract_bool_flag(rest, "--replace")
        on_conflict = "overwrite" if replace_mode else "skip"
        if input_path is None:
            return Result(status="error", error="--input <path> is required")
        conn = get_connection(global_flags)
        from memory_cli.export_import import validate_import_file, import_neurons
        validation = validate_import_file(input_path, conn, on_conflict=on_conflict)
        if not validation.valid:
            return Result(status="error", error="Validation failed", data=validation.errors)
        result = import_neurons(conn, validation, on_conflict=on_conflict)
        return Result(status="ok", data={
            "neurons_written": result.neurons_written,
            "neurons_skipped": result.neurons_skipped,
            "edges_written": result.edges_written,
        })
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: load — load a graph document (YAML with ref-based neurons + edges)
# =============================================================================
def handle_load(args: List[str], global_flags: Any) -> Any:
    """Load a YAML graph document, creating neurons and edges in one shot.

    Args:
        args: [<file-path>, --source <source>]
        global_flags: Parsed global flags.

    Returns:
        Result with counts of neurons/edges created and ref→ID map.

    Pseudo-logic:
    1. Parse positional arg: file path (required)
    2. Parse optional flag: --source <source> override
    3. Delegate to graph_document_loader_yaml_with_ref_resolution.load_graph_document()
    4. Return Result with data or error
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        require_positional, extract_flag,
    )
    try:
        rest = list(args)
        file_path, rest = require_positional(rest, "file")
        source, rest = extract_flag(rest, "--source")
        conn = get_connection(global_flags)
        from memory_cli.export_import.graph_document_loader_yaml_with_ref_resolution import (
            load_graph_document,
        )
        result = load_graph_document(conn, file_path, source=source)
        if not result.success:
            return Result(status="error", error="; ".join(result.errors))
        return Result(status="ok", data={
            "neurons_created": result.neurons_created,
            "neurons_reused": result.neurons_reused,
            "edges_created": result.edges_created,
            "ref_map": result.ref_map,
        })
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# VERB: reembed — regenerate embeddings for all neurons
# =============================================================================
def handle_reembed(args: List[str], global_flags: Any) -> Any:
    """Regenerate embeddings for all neurons (model upgrade scenario).

    Args:
        args: [--limit <N>, --force]
        global_flags: Parsed global flags.

    Returns:
        Result with reembedding progress/count.

    Pseudo-logic:
    1. Parse optional flags:
       - --limit <N>: process only N neurons (for testing/batching)
       - --force: reembed even if embedding already exists (default: skip existing)
    2. Get list of neurons to reembed:
       a. If --force: all neurons
       b. Else: neurons without embeddings or with stale embeddings
    3. For each neuron in batch:
       a. Generate new embedding from content
       b. Store embedding in sqlite-vec
       c. Update embedding timestamp
    4. Return Result(status="ok", data={
         "processed": count, "total": total, "skipped": skip_count
       })
    5. Error path: embedding model not available, DB errors
    """
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.db_connection_from_global_flags import get_connection_and_config
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        extract_flag, extract_bool_flag,
    )
    try:
        rest = list(args)
        batch_size, rest = extract_flag(rest, "--limit", type_fn=int, default=32)
        force, rest = extract_bool_flag(rest, "--force")
        conn, config = get_connection_and_config(global_flags)
        from memory_cli.embedding.model_loader_lazy_singleton import get_model
        from memory_cli.embedding import batch_reembed
        model = get_model(config.embedding.model_path)
        progress = batch_reembed(conn, model, batch_size=batch_size)
        return Result(status="ok", data={
            "processed": progress.processed,
            "skipped": progress.skipped,
            "failed": progress.failed,
        })
    except Exception as e:
        return Result(status="error", error=str(e))


# =============================================================================
# NOUN REGISTRATION
# =============================================================================
_VERB_MAP = {
    "export": handle_export,
    "import": handle_import,
    "load": handle_load,
    "reembed": handle_reembed,
}

_VERB_DESCRIPTIONS = {
    "export": "Export database contents to portable format",
    "import": "Import data from portable format",
    "load": "Load a YAML graph document (neurons + edges with ref labels)",
    "reembed": "Regenerate embeddings for all neurons",
}

_FLAG_DEFS = {
    "export": [
        {"name": "--output", "type": "str", "default": None, "desc": "Output file path (default: stdout)"},
        {"name": "--type", "type": "str", "default": "all", "desc": "What to export: neuron, edge, all"},
        {"name": "--include-archived", "type": "bool", "default": False, "desc": "Include archived neurons"},
    ],
    "import": [
        {"name": "--input", "type": "str", "default": None, "desc": "Input file path (default: stdin)"},
        {"name": "--merge", "type": "bool", "default": True, "desc": "Merge with existing data"},
        {"name": "--replace", "type": "bool", "default": False, "desc": "Replace existing data"},
    ],
    "load": [
        {"name": "<file>", "type": "str", "default": None, "desc": "Path to YAML graph document"},
        {"name": "--source", "type": "str", "default": None, "desc": "Override source for all neurons"},
    ],
    "reembed": [
        {"name": "--limit", "type": "int", "default": None, "desc": "Process only N neurons"},
        {"name": "--force", "type": "bool", "default": False, "desc": "Reembed even if embedding exists"},
    ],
}


def register() -> None:
    """Register the batch noun with the CLI dispatch registry.

    Pseudo-logic:
    1. Call register_noun("batch", {
         "verb_map": _VERB_MAP,
         "description": "Batch — bulk export, import, and reembedding",
         "verb_descriptions": _VERB_DESCRIPTIONS,
         "flag_defs": _FLAG_DEFS,
       })
    """
    register_noun("batch", {
        "verb_map": _VERB_MAP,
        "description": "Batch — bulk export, import, and reembedding",
        "verb_descriptions": _VERB_DESCRIPTIONS,
        "flag_defs": _FLAG_DEFS,
    })

# --- Self-register on import ---
register()
