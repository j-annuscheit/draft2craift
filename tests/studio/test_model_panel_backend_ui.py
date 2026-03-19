from __future__ import annotations

from shared.domain.user_mode import USER_MODE_EXPERT, USER_MODE_PLUS
from shared.services.llm.backends import (
    BACKEND_AUTO,
    BACKEND_LLAMA_CPP,
    BACKEND_TRANSFORMERS,
)
from studio.chat.model_panel import ModelLoadPanel


def _row_hidden(panel: ModelLoadPanel, field) -> bool:
    label = panel._model_form.labelForField(field)
    return bool(field.isHidden()) or bool(label is not None and label.isHidden())


def test_backend_switch_updates_hint_placeholder_and_gpu_visibility(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()
    panel.set_user_mode(USER_MODE_PLUS)

    panel.set_model_backend(BACKEND_TRANSFORMERS)
    assert panel.get_model_backend() == BACKEND_TRANSFORMERS
    assert any(
        token in panel.model_path.placeholderText()
        for token in ("Hugging Face", "HF", "model id", "Modell-ID")
    )
    assert any(
        token in panel.model_hint.text()
        for token in ("Hugging Face", "HF")
    )
    assert _row_hidden(panel, panel.gpu_spin) is True

    panel.set_model_backend(BACKEND_LLAMA_CPP)
    assert panel.get_model_backend() == BACKEND_LLAMA_CPP
    assert "GGUF" in panel.model_path.placeholderText()
    assert "GGUF" in panel.model_hint.text()
    assert _row_hidden(panel, panel.gpu_spin) is False

    panel.set_model_backend(BACKEND_AUTO)
    assert panel.get_model_backend() == BACKEND_AUTO
    assert ".gguf" in panel.model_path.placeholderText().lower()
    assert _row_hidden(panel, panel.gpu_spin) is False


def test_browse_uses_directory_dialog_for_transformers_backend(qt_app, monkeypatch):
    _ = qt_app
    panel = ModelLoadPanel()
    calls = {"directory": 0, "file": 0}

    def _fake_directory(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        calls["directory"] += 1
        return "/tmp/hf-model-dir"

    def _fake_file(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        calls["file"] += 1
        return "/tmp/model.gguf", "GGUF Models (*.gguf *.bin)"

    monkeypatch.setattr(
        "studio.chat.model_panel.QFileDialog.getExistingDirectory",
        _fake_directory,
    )
    monkeypatch.setattr(
        "studio.chat.model_panel.QFileDialog.getOpenFileName",
        _fake_file,
    )

    panel.set_model_backend(BACKEND_TRANSFORMERS)
    panel._browse()

    assert calls["directory"] == 1
    assert calls["file"] == 0
    assert panel.model_path.text() == "/tmp/hf-model-dir"


def test_browse_uses_file_dialog_for_llama_backend(qt_app, monkeypatch):
    _ = qt_app
    panel = ModelLoadPanel()
    calls = {"directory": 0, "file": 0}

    def _fake_directory(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        calls["directory"] += 1
        return "/tmp/hf-model-dir"

    def _fake_file(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        calls["file"] += 1
        return "/tmp/model.gguf", "GGUF Models (*.gguf *.bin)"

    monkeypatch.setattr(
        "studio.chat.model_panel.QFileDialog.getExistingDirectory",
        _fake_directory,
    )
    monkeypatch.setattr(
        "studio.chat.model_panel.QFileDialog.getOpenFileName",
        _fake_file,
    )

    panel.set_model_backend(BACKEND_LLAMA_CPP)
    panel._browse()

    assert calls["directory"] == 0
    assert calls["file"] == 1
    assert panel.model_path.text() == "/tmp/model.gguf"


def test_trust_remote_code_visibility_depends_on_mode_and_backend(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.set_user_mode(USER_MODE_PLUS)
    panel.set_model_backend(BACKEND_TRANSFORMERS)
    assert _row_hidden(panel, panel.trust_remote_code_cb) is True

    panel.set_user_mode(USER_MODE_EXPERT)
    panel.set_model_backend(BACKEND_LLAMA_CPP)
    assert _row_hidden(panel, panel.trust_remote_code_cb) is True

    panel.set_model_backend(BACKEND_TRANSFORMERS)
    assert _row_hidden(panel, panel.trust_remote_code_cb) is False


def test_request_load_emits_trust_remote_code_flag(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()
    panel.set_user_mode(USER_MODE_EXPERT)
    panel.set_model_backend(BACKEND_TRANSFORMERS)
    panel.model_path.setText("distilgpt2")
    panel.trust_remote_code_cb.setChecked(True)

    calls: list[tuple[str, dict]] = []
    panel.load_requested.connect(lambda path, params: calls.append((path, dict(params))))

    panel._request_load()

    assert calls
    path, params = calls[-1]
    assert path == "distilgpt2"
    assert params["trust_remote_code"] is True
