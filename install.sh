#!/usr/bin/env bash
# =============================================================================
# Purpose: One-liner installer for memory-cli
# Usage:   curl -fsSL https://raw.githubusercontent.com/ai-janitor/memory-cli/master/install.sh | bash
# Rationale: Self-bootstrapping — installs pipx if needed, clones repo,
#   installs via pipx, creates config dir. Idempotent — safe to re-run.
# =============================================================================
set -e

REPO="https://github.com/ai-janitor/memory-cli.git"
INSTALL_DIR="${MEMORY_INSTALL_DIR:-$HOME/.local/share/memory-cli}"

echo "Installing memory-cli..."

# --- Check for pipx, install if missing ---
if ! command -v pipx &> /dev/null; then
    if command -v brew &> /dev/null; then
        echo "Installing pipx via brew..."
        brew install pipx --quiet
    elif command -v apt-get &> /dev/null; then
        echo "Installing pipx via apt..."
        sudo apt-get install -y pipx --quiet
    else
        echo "Error: pipx not found. Install it first: https://pipx.pypa.io"
        exit 1
    fi
    pipx ensurepath --quiet 2>/dev/null || true
fi

# --- Clone or update ---
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing install..."
    git -C "$INSTALL_DIR" pull --quiet
else
    echo "Cloning memory-cli..."
    git clone --quiet "$REPO" "$INSTALL_DIR"
fi

# --- Install via pipx ---
pipx install "$INSTALL_DIR" --force --quiet
echo ""
echo "Installed memory-cli to ~/.local/bin/memory"

# --- Config dir (first install only) ---
CONFIG_DIR="$HOME/.config/memory-cli"
if [ ! -d "$CONFIG_DIR" ]; then
    mkdir -p "$CONFIG_DIR"
    echo "Created config dir: $CONFIG_DIR"
fi

echo ""
echo "Run:"
echo "  memory neuron create \"your first memory\""
echo "  memory neuron search \"test\""
echo "  memory --help"
