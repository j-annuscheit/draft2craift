from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from shared.services.project.project_loader import ProjectLoader
from shared.services.project.project_paths import ProjectPaths
from shared.services.project.project_saver import ProjectSaver


def _make_window_with_registry_markdown(markdown: str, source_path: str = ""):
    imported_files = SimpleNamespace(get_all_documents=lambda: {})
    context_panel = SimpleNamespace(get_all_documents=lambda: {})
    knowledge_dock = SimpleNamespace(imported_files=imported_files)
    chat_dock = SimpleNamespace(context_panel=context_panel)
    return SimpleNamespace(
        _file_registry={"Doc": (str(source_path or ""), markdown)},
        knowledge_dock=knowledge_dock,
        chat_dock=chat_dock,
    )


class _EditorStub:
    def __init__(self, text: str, *, read_only: bool = False) -> None:
        self._text = str(text)
        self._read_only = bool(read_only)

    def toPlainText(self) -> str:
        return self._text

    def isReadOnly(self) -> bool:
        return self._read_only


class _TabWidgetStub:
    def __init__(self, panel, title: str = "Draft") -> None:
        self._panel = panel
        self._title = str(title)

    def count(self) -> int:
        return 1

    def widget(self, index: int):
        assert index == 0
        return self._panel

    def tabText(self, index: int) -> str:
        assert index == 0
        return self._title


def test_project_saver_materializes_knowledge_images_to_assets(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    paths.ensure_save_dirs()
    saver = ProjectSaver(paths=paths, include_st_embeddings=False)
    window = _make_window_with_registry_markdown(
        "![img](<data:image/png;base64,QUJD>)"
    )

    payload = saver._save_knowledge_files(window)

    assert payload
    markdown = (paths.knowledge / "doc_0000.md").read_text(encoding="utf-8")
    assert "data:image/png;base64" not in markdown
    assert "assets/doc_0000/image_0001.png" in markdown
    image = paths.knowledge / "assets" / "doc_0000" / "image_0001.png"
    assert image.exists()
    assert image.read_bytes() == b"ABC"


def test_project_saver_rewrites_knowledge_original_path_to_project_relative(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    paths.ensure_save_dirs()
    saver = ProjectSaver(paths=paths, include_st_embeddings=False)
    window = _make_window_with_registry_markdown(
        "# Doc",
        source_path="https://example.com/paper.pdf",
    )

    payload = saver._save_knowledge_files(window)

    assert payload
    assert payload[0]["original_path"] == "knowledge/doc_0000.md"


def test_project_saver_rewrites_canvas_file_path_to_project_relative(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    paths.ensure_save_dirs()
    saver = ProjectSaver(paths=paths, include_st_embeddings=False)

    panel = SimpleNamespace(
        editor=_EditorStub("# Draft"),
        file_path="https://example.com/draft.md",
    )
    window = SimpleNamespace(
        canvas=SimpleNamespace(
            tabs=SimpleNamespace(tab_widget=_TabWidgetStub(panel)),
        )
    )

    payload = saver._save_canvas_tabs(window)

    assert payload
    assert payload[0]["file_path"] == "canvas/doc_0000.md"


def test_project_loader_absolutizes_canvas_and_knowledge_image_paths(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    paths.ensure_save_dirs()

    knowledge_image = paths.knowledge / "assets" / "doc_0000" / "image_0001.png"
    knowledge_image.parent.mkdir(parents=True, exist_ok=True)
    knowledge_image.write_bytes(b"k")
    (paths.knowledge / "doc_0000.md").write_text(
        "![k](<assets/doc_0000/image_0001.png>)",
        encoding="utf-8",
    )

    canvas_image = paths.canvas / "assets" / "doc_0000" / "image_0001.png"
    canvas_image.parent.mkdir(parents=True, exist_ok=True)
    canvas_image.write_bytes(b"c")
    (paths.canvas / "doc_0000.md").write_text(
        "![c](<assets/doc_0000/image_0001.png>)",
        encoding="utf-8",
    )

    loader = ProjectLoader(paths=paths)
    loaded_knowledge = loader._read_knowledge_markdown("doc_0000.md")
    loaded_canvas = loader._read_canvas_content("doc_0000.md")

    assert str(knowledge_image.resolve(strict=False)) in loaded_knowledge
    assert str(canvas_image.resolve(strict=False)) in loaded_canvas


def test_project_saver_keeps_canvas_clipboard_images_when_assets_already_exist(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    paths.ensure_save_dirs()
    saver = ProjectSaver(paths=paths, include_st_embeddings=False)

    existing = paths.canvas / "assets" / "clipboard" / "clipboard_1.png"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"\x89PNG\r\n\x1a\nX")

    panel = SimpleNamespace(
        editor=_EditorStub("![clipboard-image](<assets/clipboard/clipboard_1.png>)"),
        file_path="",
    )
    window = SimpleNamespace(
        canvas=SimpleNamespace(
            tabs=SimpleNamespace(tab_widget=_TabWidgetStub(panel)),
        )
    )

    payload = saver._save_canvas_tabs(window)

    assert payload
    markdown = (paths.canvas / "doc_0000.md").read_text(encoding="utf-8")
    assert "assets/doc_0000/image_0001.png" in markdown
    copied = paths.canvas / "assets" / "doc_0000" / "image_0001.png"
    assert copied.exists()
    assert copied.read_bytes() == b"\x89PNG\r\n\x1a\nX"
