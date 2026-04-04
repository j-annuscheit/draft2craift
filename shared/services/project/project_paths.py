"""Filesystem layout for persisted draft2craift projects."""
from __future__ import annotations

from pathlib import Path

from shared.config.paths import app_data_dir


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class ProjectPaths:
    """Resolve all project files and folders relative to one base directory."""

    def __init__(self, folder: str | Path, *, allowed_root: str | Path | None = None):
        root = (
            Path(allowed_root).expanduser().resolve(strict=False)
            if allowed_root is not None
            else None
        )
        self.base = self._resolve_base(folder, allowed_root=root)
        self.canvas = self.base / "canvas"
        self.canvas_assets = self.canvas / "assets"
        self.knowledge = self.base / "knowledge"
        self.knowledge_assets = self.knowledge / "assets"
        self.rag = self.base / "rag"
        self.chat = self.base / "chat"
        self.logs = self.base / "logs"

        self.manifest = self.base / "project.json"
        self.highlights = self.base / "highlights.json"
        self.rag_index = self.rag / "index.pkl"
        self.chat_history = self.chat / "history.json"
        self.chat_chunk_claim_cache = self.chat / "chunk_claim_cache.json"
        self.log_entries = self.logs / "entries.json"

    def ensure_save_dirs(self) -> None:
        self.canvas.mkdir(parents=True, exist_ok=True)
        self.canvas_assets.mkdir(parents=True, exist_ok=True)
        self.knowledge.mkdir(parents=True, exist_ok=True)
        self.knowledge_assets.mkdir(parents=True, exist_ok=True)
        self.rag.mkdir(parents=True, exist_ok=True)
        self.chat.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_base(folder: str | Path, *, allowed_root: Path | None) -> Path:
        folder_text = str(folder or "").strip()
        if not folder_text:
            raise ValueError("Project folder path is empty.")
        raw = Path(folder_text).expanduser()

        if raw.is_absolute():
            resolved = raw.resolve(strict=False)
            if allowed_root is not None and not _is_relative_to(resolved, allowed_root):
                raise ValueError(
                    f"Project folder escapes allowed root: {resolved} not in {allowed_root}"
                )
            return resolved

        anchor = allowed_root or app_data_dir()
        resolved = (anchor / raw).resolve(strict=False)
        if not _is_relative_to(resolved, anchor):
            raise ValueError(
                f"Project folder traversal is not allowed: {raw}"
            )
        return resolved

    @staticmethod
    def _resolve_child(root: Path, relative: str | Path, *, kind: str) -> Path:
        raw = Path(str(relative or "").strip())
        if not str(raw):
            raise ValueError(f"{kind} path is empty.")
        if raw.is_absolute():
            raise ValueError(f"{kind} path must be relative to project folder: {raw}")
        resolved = (root / raw).resolve(strict=False)
        if not _is_relative_to(resolved, root):
            raise ValueError(f"{kind} path escapes project folder: {raw}")
        return resolved

    def resolve_canvas_file(self, relative: str | Path) -> Path:
        return self._resolve_child(self.canvas, relative, kind="canvas_file")

    def resolve_knowledge_file(self, relative: str | Path) -> Path:
        return self._resolve_child(self.knowledge, relative, kind="knowledge_file")
