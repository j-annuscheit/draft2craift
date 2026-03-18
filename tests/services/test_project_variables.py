from __future__ import annotations

from shared.services.llm.manager import LLMManager
from shared.services.project.project_variables import (
    canonical_project_variable_key,
    normalize_project_variables,
    resolve_project_variables_from_object,
    resolve_project_variables_text,
)


def test_normalize_project_variables_casts_values_and_skips_blank_keys() -> None:
    normalized = normalize_project_variables(
        {
            " applicant_name ": "Alice",
            "": "ignored",
            "project_id": 42,
        }
    )
    assert normalized == {
        "applicant_name": "Alice",
        "project_id": "42",
    }


def test_canonical_project_variable_key_normalizes_case_and_symbols() -> None:
    assert canonical_project_variable_key("Applicant Name") == "applicant_name"
    assert canonical_project_variable_key("target-audience") == "target_audience"


def test_resolve_project_variables_text_supports_both_placeholder_styles() -> None:
    resolved = resolve_project_variables_text(
        "Hello ${applicant_name} for {{ Applicant Name }}.",
        {"Applicant Name": "Alice"},
    )
    assert resolved.text == "Hello Alice for Alice."
    assert resolved.missing_keys == ()


def test_resolve_project_variables_text_keeps_missing_placeholders() -> None:
    resolved = resolve_project_variables_text(
        "Hi ${known} and ${missing}.",
        {"known": "there"},
    )
    assert resolved.text == "Hi there and ${missing}."
    assert resolved.missing_keys == ("missing",)


def test_resolve_project_variables_from_object_walks_parent_chain() -> None:
    class _Owner:
        def __init__(self, parent=None):
            self._parent = parent

        def parent(self):
            return self._parent

    class _Provider(_Owner):
        def get_project_variables(self):
            return {"x": "1"}

    provider = _Provider(parent=None)
    child = _Owner(parent=provider)
    assert resolve_project_variables_from_object(child) == {"x": "1"}


def test_llm_manager_resolves_project_variables_in_prompt_templates() -> None:
    manager = LLMManager(
        project_variables_getter=lambda: {"Applicant Name": "Alice"},
    )
    manager.set_prompt_set(
        {
            "chat_system": "Hello ${applicant_name} and {{ Applicant Name }}",
        }
    )
    rendered = manager.render_prompt_template("chat_system")
    assert rendered == "Hello Alice and Alice"
