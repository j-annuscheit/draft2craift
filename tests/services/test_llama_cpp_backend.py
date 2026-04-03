from __future__ import annotations

from pathlib import Path

import pytest

from shared.services.llm.backends.llama_cpp_backend import _format_load_failure


def _discover_gguf_models() -> list[Path]:
    models_dir = Path(__file__).resolve().parents[2] / "models"
    return sorted(path for path in models_dir.rglob("*.gguf") if path.is_file())


def _is_qwen35_model(model_path: Path) -> bool:
    lowered = model_path.name.casefold()
    return "qwen3.5" in lowered or "qwen35" in lowered


GGUF_MODELS = _discover_gguf_models()
if not GGUF_MODELS:
    pytest.skip("No GGUF models found in models/", allow_module_level=True)


@pytest.mark.parametrize(
    "model_path",
    [
        pytest.param(path, id=f"model_{index:02d}")
        for index, path in enumerate(GGUF_MODELS, start=1)
    ],
)
def test_format_load_failure_matches_all_models(model_path: Path) -> None:
    message = _format_load_failure(
        str(model_path),
        ValueError("Failed to load model from file"),
    )

    if _is_qwen35_model(model_path):
        assert "Qwen3.5" in message
        assert "qwen35" in message.lower()
        assert "update" in message.lower()
    else:
        assert message == "Load failed: Failed to load model from file"
