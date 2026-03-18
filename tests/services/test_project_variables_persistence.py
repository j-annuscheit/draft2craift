from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from shared.services.project.project_loader import ProjectLoader
from shared.services.project.project_paths import ProjectPaths
from shared.services.project.project_saver import ProjectSaver


class _BoolCheck:
    def __init__(self, value: bool):
        self._value = bool(value)

    def isChecked(self) -> bool:
        return self._value


class _TextField:
    def __init__(self, value: str):
        self._value = str(value)

    def text(self) -> str:
        return self._value


class _SpinField:
    def __init__(self, value: float):
        self._value = value

    def value(self):
        return self._value


class _ByteBuffer:
    def __init__(self, payload: bytes):
        self._payload = bytes(payload)

    def data(self) -> bytes:
        return self._payload


def _make_main_window_stub():
    model_panel = SimpleNamespace(
        model_path=_TextField(""),
        get_model_backend=lambda: "auto",
        nli_model_id=_TextField(""),
        ctx_spin=_SpinField(4096),
        gpu_spin=_SpinField(0),
        threads_spin=_SpinField(4),
        max_tokens_spin=_SpinField(512),
        temp_spin=_SpinField(0.2),
        top_p_spin=_SpinField(0.95),
        repeat_penalty_spin=_SpinField(1.1),
        forbidden_chars_edit=_TextField(""),
    )
    context_panel = SimpleNamespace(
        get_selection=lambda: (True, False, None),
        _cbs={"Doc A": _BoolCheck(True)},
    )
    chat_dock = SimpleNamespace(
        context_panel=context_panel,
        model_panel=model_panel,
        apply_selection_cb=_BoolCheck(False),
    )
    rag_panel = SimpleNamespace(
        get_debug_history=lambda: [],
        search_input=_TextField(""),
    )
    knowledge_dock = SimpleNamespace(rag_panel=rag_panel)
    canvas = SimpleNamespace(
        tabs=SimpleNamespace(
            tab_widget=SimpleNamespace(currentIndex=lambda: 0),
        )
    )
    rag_system = SimpleNamespace(config=SimpleNamespace(to_dict=lambda: {}))
    llm_manager = SimpleNamespace(get_prompt_set=lambda: {})
    app_logger = SimpleNamespace(enabled=True)
    log_dock = SimpleNamespace(_level_filter="ALL", _cat_filter="ALL")

    return SimpleNamespace(
        chat_dock=chat_dock,
        knowledge_dock=knowledge_dock,
        canvas=canvas,
        rag_system=rag_system,
        llm_manager=llm_manager,
        app_logger=app_logger,
        log_dock=log_dock,
        user_mode="plus",
        get_project_variables=lambda: {"Applicant Name": "Alice"},
        get_speech_settings=lambda: {},
        get_preview_page_margin_settings=lambda: {},
        get_preview_theme_id=lambda: "classic",
        get_theme_id=lambda: "dark",
        saveGeometry=lambda: _ByteBuffer(b"geo"),
        saveState=lambda: _ByteBuffer(b"state"),
    )


def test_project_saver_manifest_includes_project_variables(tmp_path: Path) -> None:
    paths = ProjectPaths(str(tmp_path / "project-vars-save"))
    saver = ProjectSaver(paths=paths, include_st_embeddings=False)
    window = _make_main_window_stub()

    manifest = saver._build_manifest(
        mw=window,
        canvas_tabs_data=[],
        knowledge_files_data=[],
        rag_results=[],
    )
    assert manifest.get("project_variables") == {"Applicant Name": "Alice"}


def test_project_loader_restores_project_variables_with_notify_disabled(tmp_path: Path) -> None:
    paths = ProjectPaths(str(tmp_path / "project-vars-load"))
    loader = ProjectLoader(paths=paths)
    calls: list[tuple[dict[str, str], bool]] = []

    class _Window:
        def set_project_variables(self, variables, *, notify: bool = True):
            calls.append((dict(variables or {}), bool(notify)))

    loader._restore_project_variables(
        _Window(),
        {"project_variables": {"Project Title": "Roadmap"}},
    )

    assert calls == [({"Project Title": "Roadmap"}, False)]
