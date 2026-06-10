# =============================================================================
# test_central_model_resolution.py — Central model resolution tests (MEM-FIX-0003)
# =============================================================================
# Purpose:     Verify resolution order in get_model():
#              1. Explicit config path + file exists → use it
#              2. Explicit config path + file absent → fall through to central
#              3. Central ~/.memory/models/default.gguf exists → use it
#              4. No model anywhere → FileNotFoundError
# =============================================================================

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from memory_cli.embedding.model_loader_lazy_singleton import get_model, reset_model


# --- Config stubs ---
@dataclass
class _Emb:
    model_path: object  # str or None
    n_ctx: int = 2048
    n_batch: int = 512


@dataclass
class _Cfg:
    embedding: _Emb = None

    def __post_init__(self):
        if self.embedding is None:
            self.embedding = _Emb(model_path=None)


@pytest.fixture(autouse=True)
def _reset():
    reset_model()
    yield
    reset_model()


def test_central_fallback_when_local_model_absent(tmp_path, monkeypatch):
    """Local store config has NO model_path override (or points to absent file).
    Central ~/.memory/models/default.gguf exists.
    Loader must resolve to central and return a model (not raise FileNotFoundError).
    """
    # Central model exists
    central_dir = tmp_path / ".memory" / "models"
    central_dir.mkdir(parents=True)
    central_model = central_dir / "default.gguf"
    central_model.write_bytes(b"fake-central-model")
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)

    # Local config has absent model_path (what `memory init` bakes in today)
    cfg = _Cfg()
    cfg.embedding = _Emb(
        model_path=str(tmp_path / "emails" / ".memory" / "models" / "default.gguf")  # absent
    )

    mock_llama = MagicMock()
    with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=MagicMock(return_value=mock_llama))}):
        result = get_model(cfg)  # must NOT raise

    assert result is mock_llama  # resolved to central, loaded fine


def test_explicit_model_path_wins_when_file_exists(tmp_path, monkeypatch):
    """Explicit config path pointing to an existing file → use it (step 1 wins)."""
    # Central exists too — but explicit should win
    central_dir = tmp_path / ".memory" / "models"
    central_dir.mkdir(parents=True)
    (central_dir / "default.gguf").write_bytes(b"central-model")
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)

    # Explicit model file
    explicit = tmp_path / "custom" / "model.gguf"
    explicit.parent.mkdir(parents=True)
    explicit.write_bytes(b"explicit-model")

    cfg = _Cfg()
    cfg.embedding = _Emb(model_path=str(explicit))

    mock_llama = MagicMock()
    mock_llama_class = MagicMock(return_value=mock_llama)
    with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=mock_llama_class)}):
        result = get_model(cfg)

    assert result is mock_llama
    # Llama called with the explicit path, not central
    call_kwargs = mock_llama_class.call_args
    passed_path = call_kwargs.kwargs.get("model_path") or call_kwargs.args[0]
    assert passed_path == str(explicit)


def test_explicit_path_absent_falls_through_to_central(tmp_path, monkeypatch):
    """Explicit config path absent → fall through to central (step 2 → 3)."""
    central_dir = tmp_path / ".memory" / "models"
    central_dir.mkdir(parents=True)
    central_model = central_dir / "default.gguf"
    central_model.write_bytes(b"central-model")
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)

    cfg = _Cfg()
    cfg.embedding = _Emb(model_path=str(tmp_path / "absent" / "model.gguf"))  # absent

    mock_llama = MagicMock()
    mock_llama_class = MagicMock(return_value=mock_llama)
    with patch.dict("sys.modules", {"llama_cpp": MagicMock(Llama=mock_llama_class)}):
        result = get_model(cfg)

    assert result is mock_llama
    # Llama called with central path
    call_kwargs = mock_llama_class.call_args
    passed_path = call_kwargs.kwargs.get("model_path") or call_kwargs.args[0]
    assert passed_path == str(central_model)


def test_no_model_anywhere_raises_file_not_found(tmp_path, monkeypatch):
    """No explicit path, no central model → FileNotFoundError."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    # Neither central nor explicit exists

    cfg = _Cfg()
    cfg.embedding = _Emb(model_path=None)

    with pytest.raises(FileNotFoundError, match="No embedding model found"):
        get_model(cfg)
