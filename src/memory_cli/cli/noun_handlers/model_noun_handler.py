# =============================================================================
# FILE: src/memory_cli/cli/noun_handlers/model_noun_handler.py
# PURPOSE: Register the "model" noun with the CLI dispatch registry.
#          Model provides download management for embedding GGUF files.
# RESPONSIBILITY:
#   - Define verb map: download
#   - Define flag/arg specs for download verb
#   - Register with entrypoint dispatch via register_noun()
#   - Download handler: fetch GGUF model file with progress
# ORGANIZATION:
#   1. Verb handler
#   2. Noun registration at module level
# =============================================================================

from __future__ import annotations

from typing import List, Any

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun


_MODEL_URL = (
    "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF"
    "/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf"
)
_MODEL_FILENAME = "default.gguf"


# =============================================================================
# VERB: download — fetch the nomic-embed-text-v1.5 GGUF model
# =============================================================================
def handle_download(args: List[str], global_flags: Any) -> Any:
    """Download the nomic-embed-text-v1.5 Q8_0 GGUF model.

    Default: downloads to global store ~/.memory/models/default.gguf.
    --force: re-download even if file already exists.

    Central resolution in model_loader_lazy_singleton means all stores
    automatically find the global model — no per-store symlink needed.
    """
    import sys
    from pathlib import Path
    from memory_cli.cli.output_envelope_json_and_text import Result
    from memory_cli.cli.noun_handlers.arg_parse_extract_positional_and_flags import (
        extract_bool_flag,
    )

    try:
        rest = list(args)
        force, rest = extract_bool_flag(rest, "--force")

        # Always download to global store
        home = Path.home()
        target_dir = home / ".memory" / "models"
        target_path = target_dir / _MODEL_FILENAME

        # Check if file already exists
        if target_path.exists() and not target_path.is_symlink() and not force:
            return Result(
                status="ok",
                data={
                    "path": str(target_path),
                    "message": f"Model already exists at {target_path}. Use --force to re-download.",
                    "skipped": True,
                },
            )

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        # Download with progress
        _download_with_progress(str(target_path), sys.stderr)

        return Result(
            status="ok",
            data={
                "path": str(target_path),
                "message": f"Model downloaded to {target_path}",
                "skipped": False,
            },
        )
    except Exception as e:
        return Result(status="error", error=str(e))


def _download_with_progress(dest_path: str, output_stream: Any) -> None:
    """Download model file from HuggingFace with progress display."""
    import urllib.request
    from pathlib import Path

    dest = Path(dest_path)
    tmp_path = dest.with_suffix(".gguf.tmp")

    output_stream.write(f"Downloading model to {dest}...\n")
    output_stream.flush()

    req = urllib.request.Request(_MODEL_URL, headers={"User-Agent": "memory-cli"})
    response = urllib.request.urlopen(req)
    total = int(response.headers.get("Content-Length", 0))
    downloaded = 0
    chunk_size = 1024 * 1024  # 1 MB chunks

    try:
        with open(tmp_path, "wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 // total
                    mb_done = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    output_stream.write(
                        f"\r  {mb_done:.1f}/{mb_total:.1f} MB ({pct}%)"
                    )
                    output_stream.flush()

        # Rename tmp to final
        tmp_path.replace(dest)
        output_stream.write("\n")
        output_stream.flush()
    except BaseException:
        # Clean up partial download on any failure
        if tmp_path.exists():
            tmp_path.unlink()
        raise


# =============================================================================
# NOUN REGISTRATION
# =============================================================================
_VERB_MAP = {
    "download": handle_download,
}

_VERB_DESCRIPTIONS = {
    "download": "Download the nomic-embed-text-v1.5 Q8_0 GGUF embedding model (~134 MB)",
}

_FLAG_DEFS = {
    "download": [
        {"name": "--force", "type": "bool", "default": False, "desc": "Re-download even if model already exists"},
    ],
}


def register() -> None:
    """Register the model noun with the CLI dispatch registry."""
    register_noun("model", {
        "verb_map": _VERB_MAP,
        "description": "Model — download and manage embedding models",
        "verb_descriptions": _VERB_DESCRIPTIONS,
        "flag_defs": _FLAG_DEFS,
    })


# --- Self-register on import ---
register()
