# Config & Initialization

Covers: `memory init` command that creates default config and DB, config file at
~/.memory/config.json as root of all settings, config schema (db path, embedding
model settings, search defaults, Haiku API key env var), --config and --db flag
overrides for non-default locations, config loading and validation.

Requirements traced: §7.2 Init & Config.
Dependencies: None (Tier 0). All other specs depend on config being loadable.
