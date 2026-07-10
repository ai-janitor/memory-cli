# =============================================================================
# model_loader_lazy_singleton.py — Lazy singleton Llama loader, config-driven
# =============================================================================
# Purpose:     Load the nomic-embed-text-v1.5 Q8_0 GGUF model exactly once per
#              CLI invocation using a lazy singleton pattern. The model is only
#              loaded when first needed, not at import time.
# Rationale:   Embedding model loading is expensive (~200ms+). A singleton avoids
#              redundant loads within a single CLI invocation. Lazy loading avoids
#              paying the cost for commands that don't need embeddings (e.g. list,
#              get). Config-driven params allow tuning without code changes.
# Responsibility:
#   - Provide get_model() that returns a Llama instance, loading on first call
#   - Read model_path, n_ctx, n_batch from config module
#   - Validate model file exists before loading; raise FileNotFoundError if missing
#   - Pass embedding=True, verbose=False to Llama constructor
#   - Thread-safe singleton (module-level, single-threaded CLI is fine but guard anyway)
#   - Provide reset_model() for testing (clear the singleton)
# Organization:
#   Module-level _model_instance variable (the singleton)
#   get_model() -> Llama — public entry point
#   reset_model() -> None — test utility to clear singleton
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # Llama type hint will come from llama_cpp

# --- Module-level singleton state ---
# _model_instance: Optional[Llama] = None
# _model_loaded: bool = False  # distinguishes "not loaded" from "load returned None"
_model_instance: Any = None
_model_loaded: bool = False


def get_model(config: Any):  # -> Llama
    """Return the singleton Llama embedding model, loading it on first call.

    Reads configuration for:
        - model_path: absolute path to the .gguf file
        - n_ctx: context window size (default 2048)
        - n_batch: batch size for processing (default 512)

    Returns:
        A llama_cpp.Llama instance configured for embedding.

    Raises:
        FileNotFoundError: If the model file does not exist at model_path.
        RuntimeError: If llama-cpp-python fails to load the model.
    """
    global _model_instance, _model_loaded

    # --- Step 1: Check if singleton already loaded ---
    # If _model_instance is not None (or _model_loaded is True), return it immediately
    if _model_loaded:
        return _model_instance

    # --- Step 2: Read config values ---
    # model_path = config.get_model_path()  # absolute path to .gguf
    # n_ctx = config.get_embedding_n_ctx()  # default 2048
    # n_batch = config.get_embedding_n_batch()  # default 512
    model_path = config.embedding.model_path
    n_ctx = config.embedding.n_ctx
    n_batch = config.embedding.n_batch

    # --- Step 2.5: Central resolution order ---
    # 1. config.embedding.model_path set AND file exists → use it (explicit wins)
    # 2. config.embedding.model_path set AND file absent → fall through to central
    # 3. ~/.memory/models/default.gguf exists → use it (central default)
    # 4. None of the above → raise FileNotFoundError
    central_path = Path.home() / ".memory" / "models" / "default.gguf"

    if model_path is not None:
        explicit = Path(model_path)
        if explicit.exists() and explicit.is_file():
            path = explicit  # step 1: explicit wins
        elif central_path.exists() and central_path.is_file():
            path = central_path  # step 2→3: fall through to central
        else:
            raise FileNotFoundError(
                f"No embedding model found. Run: memory model download"
                f" (config path absent: {model_path})"
            )
    else:
        # model_path is None (new store written with null)
        if central_path.exists() and central_path.is_file():
            path = central_path  # step 3: central default
        else:
            raise FileNotFoundError(
                "No embedding model found. Run: memory model download"
            )

    # --- Step 3: (resolved above — path is set) ---

    # --- Step 4: Load the model ---
    # from llama_cpp import Llama
    # _model_instance = Llama(
    #     model_path=str(path),
    #     embedding=True,
    #     n_ctx=n_ctx,
    #     n_batch=n_batch,
    #     verbose=False,
    # )
    from llama_cpp import Llama  # noqa: PLC0415 — deferred import to avoid hard dependency
    # Thread cap: prefer embedding.daemon_n_threads (ADR 0001) over llama.cpp
    # cpu_count defaults — bounds fleet embed CPU for both daemon and inproc.
    n_threads = getattr(config.embedding, "daemon_n_threads", None)
    llama_kwargs: dict = {
        "model_path": str(path),
        "embedding": True,
        "n_ctx": n_ctx,
        "n_batch": n_batch,
        "verbose": False,
        "use_mmap": True,
    }
    if n_threads is not None and int(n_threads) >= 1:
        nt = int(n_threads)
        llama_kwargs["n_threads"] = nt
        llama_kwargs["n_threads_batch"] = nt
    _model_instance = Llama(**llama_kwargs)

    # --- Step 5: Store and return ---
    # _model_loaded = True
    # return _model_instance
    _model_loaded = True
    return _model_instance


def reset_model() -> None:
    """Clear the singleton model instance. Used only in tests.

    After calling this, the next get_model() call will reload the model
    from disk. This allows tests to swap config values between loads.
    """
    global _model_instance, _model_loaded

    # --- Reset singleton state ---
    # global _model_instance, _model_loaded
    # _model_instance = None
    # _model_loaded = False
    _model_instance = None
    _model_loaded = False
