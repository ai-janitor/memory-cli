# =============================================================================
# Module: config_schema_and_defaults.py
# Purpose: Define the canonical config schema, default values, and validation
#   rules as pure data structures — no I/O, no side effects.
# Rationale: Separating schema from loading means the schema is testable in
#   isolation and reusable by init (to write defaults) and loader (to merge).
#   Validation rules live here so there's one source of truth for what's valid.
# Responsibility:
#   - CONFIG_DEFAULTS dict: complete default config matching config.json shape
#   - VALIDATION_RULES: per-field type checks, range constraints, enum values
#   - ConfigSchema dataclass: typed representation of a validated config
# Organization:
#   1. Imports
#   2. CONFIG_DEFAULTS constant
#   3. VALIDATION_RULES constant
#   4. ConfigSchema dataclass
#   5. Helper: build_config_with_defaults() — merge user JSON over defaults
# =============================================================================

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# -----------------------------------------------------------------------------
# CONFIG_DEFAULTS — Complete default config matching the JSON shape.
# This is what gets written to config.json on `memory init` and what gets
# merged under user-provided values during config loading.
#
# Schema:
#   db_path: str — absolute path to SQLite DB file
#   embedding.model_path: str — absolute path to GGUF embedding model
#   embedding.n_ctx: int >= 512, context window size for embedding model
#   embedding.n_batch: int >= 1, batch size for embedding inference
#   embedding.dimensions: int > 0, output embedding vector dimensionality
#   search.default_limit: int >= 1, max results returned by search
#   search.fan_out_depth: int [0, 10], graph traversal depth for spreading activation
#   search.decay_rate: float (0.0, 1.0) exclusive, activation decay per hop
#   search.temporal_decay_enabled: bool, whether to apply time-based decay
#   haiku.api_key_env_var: str, env var name holding the Anthropic API key
#   output.default_format: str "json"|"text", CLI output format
# -----------------------------------------------------------------------------
# CONFIG_DEFAULTS: Dict[str, Any] = { ... }
# NOTE: db_path and embedding.model_path have no universal default — they are
# set relative to the store dir during init. The defaults here are None/empty
# to signal "must be set by init or user".

CONFIG_DEFAULTS: Dict[str, Any] = {
    "db_path": None,
    "embedding": {
        "model_path": None,
        "n_ctx": 2048,
        "n_batch": 512,
        "dimensions": 768,
    },
    "search": {
        "default_limit": 10,
        "fan_out_depth": 1,
        "decay_rate": 0.25,
        "temporal_decay_enabled": True,
        "latency_threshold_ms": 500.0,
    },
    "haiku": {
        "api_key_env_var": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-4-5-20251001",
    },
    "output": {
        "default_format": "json",
    },
}


# -----------------------------------------------------------------------------
# VALIDATION_RULES — Per-field validation constraints.
# Each key maps to a dict describing: type, required, range/enum, custom check.
#
# Structure: Dict[dotted_key_path, ValidationRule]
# Example: "embedding.n_ctx" -> { type: int, min: 512 }
#          "output.default_format" -> { type: str, enum: ["json", "text"] }
#
# Design decisions:
#   - Dotted paths match the nested JSON structure for easy lookup
#   - Unknown keys are IGNORED (forward compatibility) — no error on extra keys
#   - Absolute path validation: db_path and model_path must start with "/"
#   - Range checks: min/max for ints, exclusive bounds for decay_rate
# -----------------------------------------------------------------------------
# VALIDATION_RULES: Dict[str, Dict[str, Any]] = { ... }

VALIDATION_RULES: Dict[str, Dict[str, Any]] = {
    "db_path": {
        "type": str,
        "required": True,
        "absolute_path": True,
    },
    "embedding.model_path": {
        "type": str,
        "required": True,
        "absolute_path": True,
    },
    "embedding.n_ctx": {
        "type": int,
        "min": 512,
    },
    "embedding.n_batch": {
        "type": int,
        "min": 1,
    },
    "embedding.dimensions": {
        "type": int,
        "min_exclusive": 0,
    },
    "search.default_limit": {
        "type": int,
        "min": 1,
    },
    "search.fan_out_depth": {
        "type": int,
        "min": 0,
        "max": 10,
    },
    "search.decay_rate": {
        "type": float,
        "min_exclusive": 0.0,
        "max_exclusive": 1.0,
    },
    "search.temporal_decay_enabled": {
        "type": bool,
    },
    "search.latency_threshold_ms": {
        "type": float,
        "min_exclusive": 0.0,
    },
    "haiku.api_key_env_var": {
        "type": str,
        "non_empty": True,
    },
    "output.default_format": {
        "type": str,
        "enum": ["json", "text"],
    },
}


@dataclass
class EmbeddingConfig:
    """Typed representation of the embedding section of config."""

    # model_path: str
    # n_ctx: int
    # n_batch: int
    # dimensions: int

    model_path: str
    n_ctx: int
    n_batch: int
    dimensions: int


@dataclass
class SearchConfig:
    """Typed representation of the search section of config."""

    # default_limit: int
    # fan_out_depth: int
    # decay_rate: float
    # temporal_decay_enabled: bool

    default_limit: int
    fan_out_depth: int
    decay_rate: float
    temporal_decay_enabled: bool
    latency_threshold_ms: float


@dataclass
class HaikuConfig:
    """Typed representation of the haiku section of config."""

    # api_key_env_var: str

    api_key_env_var: str
    model: str


@dataclass
class OutputConfig:
    """Typed representation of the output section of config."""

    # default_format: str

    default_format: str


@dataclass
class ConfigSchema:
    """Typed representation of a validated memory-cli config.

    Constructed from a validated dict after defaults are merged and all fields
    pass validation. This is the object the rest of the codebase receives —
    never raw dicts.

    Fields mirror the JSON schema exactly. Nested sections (embedding, search,
    haiku, output) are represented as nested dataclasses.
    """

    # --- Top-level fields ---
    # db_path: str — absolute path to the SQLite database file

    # --- Embedding section ---
    # model_path: str — absolute path to the GGUF model file
    # n_ctx: int — context window size (>= 512, default 2048)
    # n_batch: int — batch size (>= 1, default 512)
    # dimensions: int — vector dimensions (> 0, default 768)

    # --- Search section ---
    # default_limit: int — max search results (>= 1, default 10)
    # fan_out_depth: int — graph traversal depth ([0, 10], default 1)
    # decay_rate: float — activation decay per hop ((0.0, 1.0), default 0.25)
    # temporal_decay_enabled: bool — time-based decay toggle (default True)

    # --- Haiku section ---
    # api_key_env_var: str — env var name for API key (default "ANTHROPIC_API_KEY")

    # --- Output section ---
    # default_format: str — "json" or "text" (default "json")

    db_path: str
    embedding: EmbeddingConfig
    search: SearchConfig
    haiku: HaikuConfig
    output: OutputConfig


def _get_nested(config: Dict[str, Any], dotted_path: str) -> Any:
    keys = dotted_path.split(".")
    current = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def build_config_with_defaults(user_config: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge user-provided config over CONFIG_DEFAULTS.

    Logic flow:
    1. Deep copy CONFIG_DEFAULTS
    2. For each key in user_config, recursively overwrite the default
    3. Unknown keys in user_config are preserved (forward compat)
    4. Return merged dict (not yet validated — caller must validate)

    Args:
        user_config: Parsed JSON from config.json (may be partial).

    Returns:
        Complete config dict with all defaults filled in.
    """
    # 1. Deep copy CONFIG_DEFAULTS
    merged = copy.deepcopy(CONFIG_DEFAULTS)

    # 2. Recursively merge user_config over merged defaults
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                _deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    # 3. Unknown keys in user_config are preserved (forward compat)
    _deep_merge(merged, user_config)

    # 4. Return merged dict
    return merged


def validate_config(config: Dict[str, Any]) -> list[str]:
    """Validate a merged config dict against VALIDATION_RULES.

    Logic flow:
    1. For each rule in VALIDATION_RULES:
       a. Extract value at dotted path from config
       b. Check type matches expected
       c. Check range/enum constraints
       d. Check absolute path requirement for path fields
    2. Collect all errors (don't fail on first — report all)
    3. Return list of error strings (empty = valid)

    Validation rules applied:
    - db_path: must be str, must be absolute path (starts with /)
    - embedding.model_path: must be str, must be absolute path
    - embedding.n_ctx: must be int, >= 512
    - embedding.n_batch: must be int, >= 1
    - embedding.dimensions: must be int, > 0
    - search.default_limit: must be int, >= 1
    - search.fan_out_depth: must be int, [0, 10] inclusive
    - search.decay_rate: must be float, (0.0, 1.0) exclusive
    - search.temporal_decay_enabled: must be bool
    - haiku.api_key_env_var: must be str, non-empty
    - output.default_format: must be str, one of ["json", "text"]

    Edge cases:
    - EC-5: decay_rate exactly 0.0 or 1.0 -> error (exclusive bounds)
    - EC-6: n_ctx = 511 -> error (must be >= 512)
    - EC-12: unknown keys -> silently ignored (forward compat)

    Args:
        config: Merged config dict (after defaults applied).

    Returns:
        List of validation error strings. Empty list means valid.
    """
    errors = []

    # 1. For each rule in VALIDATION_RULES
    for dotted_path, rule in VALIDATION_RULES.items():
        value = _get_nested(config, dotted_path)

        # a. Check required / None case
        if value is None:
            if rule.get("required"):
                errors.append(f"{dotted_path}: required but is None or missing")
            continue

        expected_type = rule.get("type")

        # b. Check type matches expected
        # Special case: bool is subclass of int in Python — must check bool first
        if expected_type is not None:
            if expected_type is float and isinstance(value, int) and not isinstance(value, bool):
                # Allow int where float is expected (JSON parses 1 as int not float)
                value = float(value)
            if not isinstance(value, expected_type):
                errors.append(
                    f"{dotted_path}: expected {expected_type.__name__}, got {type(value).__name__}"
                )
                continue

        # c. Check range/enum constraints
        if "min" in rule and value < rule["min"]:
            errors.append(f"{dotted_path}: must be >= {rule['min']}, got {value}")

        if "max" in rule and value > rule["max"]:
            errors.append(f"{dotted_path}: must be <= {rule['max']}, got {value}")

        if "min_exclusive" in rule and value <= rule["min_exclusive"]:
            errors.append(f"{dotted_path}: must be > {rule['min_exclusive']}, got {value}")

        if "max_exclusive" in rule and value >= rule["max_exclusive"]:
            errors.append(f"{dotted_path}: must be < {rule['max_exclusive']}, got {value}")

        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"{dotted_path}: must be one of {rule['enum']}, got {value!r}")

        if rule.get("non_empty") and not value:
            errors.append(f"{dotted_path}: must be non-empty string")

        # d. Check absolute path requirement for path fields
        if rule.get("absolute_path") and not value.startswith("/"):
            errors.append(f"{dotted_path}: must be an absolute path (starts with /), got {value!r}")

    # 2. Return list of error strings (empty = valid)
    return errors


def dict_to_config_schema(config: Dict[str, Any]) -> ConfigSchema:
    """Convert a validated config dict into a ConfigSchema dataclass.

    Precondition: config has been validated (no errors from validate_config).

    Logic flow:
    1. Extract each nested section into its typed dataclass
    2. Construct and return ConfigSchema with all sections populated

    Args:
        config: Validated config dict.

    Returns:
        ConfigSchema instance.
    """
    # 1. Extract each nested section into its typed dataclass
    emb = config["embedding"]
    embedding = EmbeddingConfig(
        model_path=emb["model_path"],
        n_ctx=emb["n_ctx"],
        n_batch=emb["n_batch"],
        dimensions=emb["dimensions"],
    )

    srch = config["search"]
    search = SearchConfig(
        default_limit=srch["default_limit"],
        fan_out_depth=srch["fan_out_depth"],
        decay_rate=float(srch["decay_rate"]),
        temporal_decay_enabled=srch["temporal_decay_enabled"],
        latency_threshold_ms=float(srch.get("latency_threshold_ms", 500.0)),
    )

    haiku_sec = config["haiku"]
    haiku = HaikuConfig(
        api_key_env_var=haiku_sec["api_key_env_var"],
        model=haiku_sec.get("model", "claude-haiku-4-5-20251001"),
    )

    out = config["output"]
    output = OutputConfig(
        default_format=out["default_format"],
    )

    # 2. Construct and return ConfigSchema with all sections populated
    return ConfigSchema(
        db_path=config["db_path"],
        embedding=embedding,
        search=search,
        haiku=haiku,
        output=output,
    )
