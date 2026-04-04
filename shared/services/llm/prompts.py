"""Prompt template persistence helpers backed by Jinja2."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError

from shared.config.setting_keys import PromptTemplateKeys
from shared.domain.prompt import PROMPT_SCHEMA_VERSION

PROMPT_KEYS: tuple[str, ...] = PromptTemplateKeys.ALL


def runtime_app_root() -> Path:
    """Return project root in source run and ``_MEIPASS`` for PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[3]


DEFAULT_PROMPTS_FILE = runtime_app_root() / "data" / "prompts" / "defaults.json"
_LEGACY_SLOT_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


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


class PromptTemplateStore:
    """Holds and renders prompt templates with Jinja2."""

    def __init__(self, logger: Any = None, defaults_file: Path = DEFAULT_PROMPTS_FILE):
        self._log = logger
        self._defaults_file = Path(defaults_file)
        self._defaults = self._load_prompt_defaults()
        self._prompts = dict(self._defaults)
        self._jinja = Environment(
            autoescape=False,
            trim_blocks=False,
            lstrip_blocks=False,
            undefined=StrictUndefined,
        )

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
            self._prompts[key] = value

    def render(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> str:
        text = str(self._prompts.get(key, self._defaults.get(key, "")) or "")
        payload = {
            str(name): str(value)
            for name, value in dict(replacements or {}).items()
        }
        # Backward-compatible mode: legacy placeholders used "{name}".
        legacy_normalized = _LEGACY_SLOT_RE.sub(r"{{ \1 }}", text)
        try:
            template = self._jinja.from_string(legacy_normalized)
            return str(template.render(**payload))
        except TemplateError:
            try:
                template = self._jinja.from_string(text)
                return str(template.render(**payload))
            except TemplateError as exc:
                if self._log:
                    self._log.warning(
                        "LLM",
                        f"Prompt render failed for key '{key}': {exc}",
                    )
                return text

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
