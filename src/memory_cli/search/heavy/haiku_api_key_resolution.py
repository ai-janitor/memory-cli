# =============================================================================
# Module: haiku_api_key_resolution.py
# Purpose: Resolve the Anthropic API key from the environment variable named
#   in config, validate it's present and non-empty, and return it for use
#   by Haiku API calls.
# Rationale: API key resolution is a separate concern from prompt building
#   and API calling. Isolating it makes it testable (mock os.environ) and
#   gives a single place to enforce the "key never logged or output" rule.
#   The config indirection (env var name in config, not the key itself)
#   means the key never touches disk.
# Responsibility:
#   - Read haiku.api_key_env_var from config
#   - Look up that env var name in os.environ
#   - Validate the value is present and non-empty (after strip)
#   - Return the key string
#   - Never log, print, or include the key in error messages
# Organization:
#   1. Imports
#   2. Custom exception
#   3. resolve_haiku_api_key() — main resolution function
# =============================================================================

from __future__ import annotations

import os
from typing import Any


class HaikuApiKeyError(Exception):
    """Raised when the Haiku API key cannot be resolved.

    Attributes:
        env_var_name: The env var name that was looked up (safe to log).
        reason: Why resolution failed (missing, empty).
    """

    pass


def resolve_haiku_api_key(config: Any) -> str:
    """Resolve the Anthropic API key from environment.

    Resolution flow:
    1. Read env var name from config.haiku.api_key_env_var
       - Expected to be a string like "ANTHROPIC_API_KEY"
       - If config section missing or field empty: raise HaikuApiKeyError
    2. Look up os.environ[env_var_name]
       - If env var not set: raise HaikuApiKeyError
         "Environment variable '{env_var_name}' is not set"
       - If env var is empty/whitespace: raise HaikuApiKeyError
         "Environment variable '{env_var_name}' is empty"
    3. Return the stripped key value

    Security:
    - The key value is NEVER included in error messages
    - The key value is NEVER logged
    - Only the env var NAME appears in errors (safe — it's config, not secret)

    Args:
        config: ConfigSchema instance with haiku.api_key_env_var field.

    Returns:
        The API key string (stripped of whitespace).

    Raises:
        HaikuApiKeyError: If env var name is missing from config, env var
            is not set, or env var value is empty.
    """
    # --- Step 1: Extract env var name from config ---
    # env_var_name = config.haiku.api_key_env_var
    # If not a non-empty string: raise HaikuApiKeyError("No API key env var configured")
    try:
        env_var_name = config.haiku.api_key_env_var
    except AttributeError:
        raise HaikuApiKeyError("No API key env var configured")
    if not env_var_name or not isinstance(env_var_name, str):
        raise HaikuApiKeyError("No API key env var configured")

    # --- Step 2: Look up env var ---
    # raw_value = os.environ.get(env_var_name)
    # If raw_value is None: raise HaikuApiKeyError(f"Environment variable '{env_var_name}' is not set")
    raw_value = os.environ.get(env_var_name)
    if raw_value is None:
        raise HaikuApiKeyError(f"Environment variable '{env_var_name}' is not set")

    # --- Step 3: Validate non-empty ---
    # key = raw_value.strip()
    # If key == "": raise HaikuApiKeyError(f"Environment variable '{env_var_name}' is empty")
    key = raw_value.strip()
    if key == "":
        raise HaikuApiKeyError(f"Environment variable '{env_var_name}' is empty")

    # --- Step 4: Return key ---
    # return key
    return key
