from __future__ import annotations

from shared.domain.user_mode import USER_MODE_EXPERT, USER_MODE_PLUS
from shared.services.llm.backends import (
    BACKEND_AUTO,
    BACKEND_LLAMA_CPP,
    BACKEND_LITELLM,
)
from studio.chat.model_panel import ModelLoadPanel


def _row_hidden(panel: ModelLoadPanel, field) -> bool:
    label = panel._model_form.labelForField(field)
    return bool(field.isHidden()) or bool(label is not None and label.isHidden())


def _gen_row_hidden(panel: ModelLoadPanel, field) -> bool:
    label = panel._gen_form.labelForField(field)
    return bool(field.isHidden()) or bool(label is not None and label.isHidden())


def test_backend_switch_updates_hint_placeholder_and_gpu_visibility(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()
    panel.set_user_mode(USER_MODE_PLUS)

    panel.set_model_backend(BACKEND_LITELLM)
    assert panel.get_model_backend() == BACKEND_LITELLM
    assert any(
        token in panel.model_path.placeholderText()
        for token in ("LiteLLM", "model id", "ollama")
    )
    assert any(
        token in panel.model_hint.text()
        for token in ("LiteLLM", "local")
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


def test_browse_skips_dialog_for_litellm_backend(qt_app, monkeypatch):
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

    panel.set_model_backend(BACKEND_LITELLM)
    panel.model_path.setText("ollama/llama3")
    panel._browse()

    assert calls["directory"] == 0
    assert calls["file"] == 0
    assert panel.model_path.text() == "ollama/llama3"


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


def test_request_load_switches_to_llama_for_local_gguf_file(qt_app, monkeypatch):
    _ = qt_app
    panel = ModelLoadPanel()
    panel.set_model_backend(BACKEND_LITELLM)
    panel.model_path.setText("/home/be/Downloads/model.gguf")

    monkeypatch.setattr("studio.chat.model_panel.os.path.isfile", lambda _path: True)

    calls: list[tuple[str, dict]] = []
    panel.load_requested.connect(lambda path, params: calls.append((path, dict(params))))

    panel._request_load()

    assert panel.get_model_backend() == BACKEND_LLAMA_CPP
    assert calls
    path, params = calls[-1]
    assert path == "/home/be/Downloads/model.gguf"
    assert params["backend"] == BACKEND_LLAMA_CPP


def test_trust_remote_code_visibility_depends_on_mode_and_backend(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.set_user_mode(USER_MODE_PLUS)
    panel.set_model_backend(BACKEND_LITELLM)
    assert _row_hidden(panel, panel.trust_remote_code_cb) is True

    panel.set_user_mode(USER_MODE_EXPERT)
    panel.set_model_backend(BACKEND_LLAMA_CPP)
    assert _row_hidden(panel, panel.trust_remote_code_cb) is True

    panel.set_model_backend(BACKEND_LITELLM)
    assert _row_hidden(panel, panel.trust_remote_code_cb) is True


def test_request_load_emits_trust_remote_code_flag(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()
    panel.set_user_mode(USER_MODE_EXPERT)
    panel.set_model_backend(BACKEND_LITELLM)
    panel.model_path.setText("ollama/llama3")
    panel.trust_remote_code_cb.setChecked(True)

    calls: list[tuple[str, dict]] = []
    panel.load_requested.connect(lambda path, params: calls.append((path, dict(params))))

    panel._request_load()

    assert calls
    path, params = calls[-1]
    assert path == "ollama/llama3"
    assert params["trust_remote_code"] is True


def test_generation_style_slider_applies_sampling_presets(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.generation_style_slider.setValue(0)
    assert panel.temp_spin.value() == 0.20
    assert panel.top_p_spin.value() == 0.85
    assert panel.repeat_penalty_spin.value() == 1.15

    panel.generation_style_slider.setValue(2)
    assert panel.temp_spin.value() == 1.00
    assert panel.top_p_spin.value() == 0.98
    assert panel.repeat_penalty_spin.value() == 1.00


def test_generation_style_slider_syncs_from_manual_sampling_values(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.temp_spin.setValue(1.00)
    panel.top_p_spin.setValue(0.98)
    panel.repeat_penalty_spin.setValue(1.00)
    assert panel.generation_style_slider.value() == 2

    panel.temp_spin.setValue(0.20)
    panel.top_p_spin.setValue(0.85)
    panel.repeat_penalty_spin.setValue(1.15)
    assert panel.generation_style_slider.value() == 0


def test_generation_style_visibility_is_user_mode_driven(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.set_user_mode("easy_eng")
    assert _gen_row_hidden(panel, panel.generation_style_widget) is False
    assert _gen_row_hidden(panel, panel.temp_spin) is True

    panel.set_user_mode(USER_MODE_EXPERT)
    assert _gen_row_hidden(panel, panel.generation_style_widget) is False
    assert _gen_row_hidden(panel, panel.temp_spin) is False


def test_max_tokens_profile_slider_applies_presets(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.max_tokens_profile_slider.setValue(0)
    assert panel.max_tokens_spin.value() == 512

    panel.max_tokens_profile_slider.setValue(1)
    assert panel.max_tokens_spin.value() == 1024

    panel.max_tokens_profile_slider.setValue(2)
    assert panel.max_tokens_spin.value() == 2048


def test_max_tokens_profile_slider_syncs_from_manual_value(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.max_tokens_spin.setValue(2048)
    assert panel.max_tokens_profile_slider.value() == 2

    panel.max_tokens_spin.setValue(512)
    assert panel.max_tokens_profile_slider.value() == 0


def test_context_tokens_visibility_is_user_mode_driven(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.set_user_mode("easy_eng")
    assert _row_hidden(panel, panel.ctx_spin) is True

    panel.set_user_mode(USER_MODE_EXPERT)
    assert _row_hidden(panel, panel.ctx_spin) is False


def test_max_tokens_profile_visibility_is_user_mode_driven(qt_app):
    _ = qt_app
    panel = ModelLoadPanel()

    panel.set_user_mode("easy_eng")
    assert _gen_row_hidden(panel, panel.max_tokens_profile_widget) is False

    panel.set_user_mode(USER_MODE_EXPERT)
    assert _gen_row_hidden(panel, panel.max_tokens_profile_widget) is False
