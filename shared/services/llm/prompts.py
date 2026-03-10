"""Prompt template persistence and migration helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from shared.config.setting_keys import PromptTemplateKeys
from shared.domain.prompt import PROMPT_SCHEMA_VERSION

PROMPT_KEYS: tuple[str, ...] = PromptTemplateKeys.ALL


def runtime_app_root() -> Path:
    """Return project root in source run and ``_MEIPASS`` for PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[3]


DEFAULT_PROMPTS_FILE = runtime_app_root() / "data" / "prompts" / "defaults.json"


def load_prompt_templates(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Prompt template file must contain a JSON object.")
    schema = int(data.get("schema_version", PROMPT_SCHEMA_VERSION))
    if schema != PROMPT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported prompt schema version: {schema}")
    return {
        key: str(value)
        for key, value in data.items()
        if isinstance(key, str) and key != "schema_version"
    }


def dump_prompt_templates(path: Path, templates: dict[str, str]) -> None:
    payload = {"schema_version": PROMPT_SCHEMA_VERSION, **templates}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class PromptTemplateRegistry:
    """Holds default/custom prompt templates and applies legacy migrations."""

    def __init__(self, logger: Any = None, defaults_file: Path = DEFAULT_PROMPTS_FILE):
        self._log = logger
        self._defaults_file = Path(defaults_file)
        self._defaults = self._load_prompt_defaults()
        self._prompts = dict(self._defaults)

    @property
    def prompts(self) -> dict[str, str]:
        return self._prompts

    @property
    def defaults(self) -> dict[str, str]:
        return self._defaults

    def set_system_prompt(self, text: str) -> str:
        value = str(text or "").strip()
        if not value:
            value = self._defaults["chat_system"]
        self._prompts["chat_system"] = value
        return value

    def get_prompt_set(self) -> dict[str, str]:
        return dict(self._prompts)

    def get_prompt_defaults(self) -> dict[str, str]:
        return dict(self._defaults)

    def set_prompt_set(self, prompts: dict[str, str]) -> None:
        if not isinstance(prompts, dict):
            return
        for key in PROMPT_KEYS:
            if key not in prompts:
                continue
            value = str(prompts.get(key, "") or "").strip()
            if not value:
                value = self._defaults[key]
            else:
                value = self._migrate_legacy_prompt_value(key, value)
            self._prompts[key] = value

    def render(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> str:
        text = str(self._prompts.get(key, self._defaults.get(key, "")) or "")
        out = text
        for name, value in (replacements or {}).items():
            out = out.replace("{" + str(name) + "}", str(value))
        return out

    def _load_prompt_defaults(self) -> dict[str, str]:
        defaults: dict[str, str] = {}
        try:
            with self._defaults_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                for key in PROMPT_KEYS:
                    value = data.get(key, "")
                    if isinstance(value, str):
                        defaults[key] = value
        except Exception as exc:
            if self._log:
                self._log.error(
                    "LLM",
                    (
                        "Prompt-Defaults konnten nicht geladen werden "
                        f"({self._defaults_file}): {exc}"
                    ),
                )

        for key in PROMPT_KEYS:
            defaults.setdefault(key, "")
        if not defaults.get("chat_system", "").strip():
            defaults["chat_system"] = "Du bist ein hilfreicher Schreibassistent."
        return defaults

    def _migrate_legacy_prompt_value(self, key: str, value: str) -> str:
        candidate = str(value or "").strip()
        if self._is_legacy_prompt_value(key, candidate):
            upgraded = str(self._defaults.get(key, candidate) or "").strip()
            if upgraded and upgraded != candidate:
                if self._log:
                    self._log.info(
                        "LLM",
                        f"Prompt-Migration: '{key}' wurde auf aktuellen Default angehoben.",
                    )
                return upgraded
        return candidate

    @staticmethod
    def _is_legacy_prompt_value(key: str, candidate: str) -> bool:
        text = str(candidate or "").strip()
        if not text:
            return False

        if key == "mindmap_system":
            return (
                text.startswith("Du erstellst eine MindMap aus Kontext.")
                and "Verbindliche Regeln:" not in text
            )
        if key == "mindmap_user":
            return (
                "Erstelle eine MindMap zur Frage: {query}" in text
                and "Nutze nur diesen Kontext:" in text
                and "Ausgabeformat streng:" in text
                and "Arbeite intern in 3 Schritten:" not in text
            )
        if key == "graph_system":
            return (
                text.startswith("Du erstellst einen Wissensgraphen aus Kontext.")
                and "Verbindliche Regeln:" not in text
            )
        if key == "graph_user":
            return (
                "Erstelle einen Wissensgraphen zur Frage: {query}" in text
                and "Nutze nur diesen Kontext:" in text
                and "Ausgabeformat" in text
                and "Arbeite intern in 4 Schritten:" not in text
            )
        return False
