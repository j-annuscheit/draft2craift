"""Dialog for configuring agentic workflow runtime behavior."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.services.agentic.settings import AgenticRuntimeSettings

_WORKFLOW_ROWS = (
    ("factcheck", "Faktencheck"),
    ("chat", "Chat (Q&A)"),
    ("canvas", "Canvas Rewrite"),
    ("mindmap", "Mindmap/Graph"),
    ("graph", "Graph (Connected)"),
)
_MAP_RESULT_DETAIL_OPTIONS = (
    ("auto", "Automatisch"),
    ("compact", "Kompakt"),
    ("standard", "Standard"),
    ("detailed", "Detailliert"),
)


class AgenticSettingsDialog(QDialog):
    """Edits persistent runtime settings for agentic workflows."""

    def __init__(
        self,
        settings: AgenticRuntimeSettings,
        *,
        profile_ids_by_workflow: Mapping[str, Sequence[str]] | None = None,
        user_mode: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._base = settings.clone()
        self._profile_ids_by_workflow = {
            str(key): [
                str(item or "").strip()
                for item in list(values or [])
                if str(item or "").strip()
            ]
            for key, values in dict(profile_ids_by_workflow or {}).items()
        }
        self._user_mode = normalize_user_mode(
            default_user_mode() if user_mode is None else user_mode
        )

        self._intro_label: QLabel | None = None
        self._workflow_group: QGroupBox | None = None
        self._runtime_group: QGroupBox | None = None
        self._buttons_box: QDialogButtonBox | None = None

        self._workflow_enabled: dict[str, QCheckBox] = {}
        self._workflow_profiles: dict[str, QComboBox] = {}
        self._workflow_row_labels: dict[str, QLabel] = {}

        self._runtime_row_labels: dict[str, QLabel] = {}
        self._env_name_edit: QLineEdit | None = None
        self._overlay_profiles_edit: QLineEdit | None = None
        self._strict_policy_cb: QCheckBox | None = None
        self._trace_enabled_cb: QCheckBox | None = None
        self._cache_enabled_cb: QCheckBox | None = None
        self._map_result_detail_combo: QComboBox | None = None

        self.resize(760, 500)
        self._build_ui()
        self._load_values()
        self.set_user_mode(self._user_mode)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self._apply_labels()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel("")
        intro.setWordWrap(True)
        self._intro_label = intro
        root.addWidget(intro)

        workflows_group = QGroupBox("")
        self._workflow_group = workflows_group
        workflows_form = QFormLayout(workflows_group)
        workflows_form.setHorizontalSpacing(14)
        workflows_form.setVerticalSpacing(8)
        for workflow_key, fallback_label in _WORKFLOW_ROWS:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            enabled_cb = QCheckBox("")
            enabled_cb.stateChanged.connect(
                lambda _state=0, key=workflow_key: self._sync_row_enabled_state(key)
            )
            combo = self._new_profile_combo(
                self._profile_ids_by_workflow.get(workflow_key, ())
            )
            row_layout.addWidget(enabled_cb)
            row_layout.addWidget(combo, 1)

            row_label = QLabel(fallback_label)
            workflows_form.addRow(row_label, row_widget)
            self._workflow_enabled[workflow_key] = enabled_cb
            self._workflow_profiles[workflow_key] = combo
            self._workflow_row_labels[workflow_key] = row_label

        root.addWidget(workflows_group)

        runtime_group = QGroupBox("")
        self._runtime_group = runtime_group
        runtime_form = QFormLayout(runtime_group)
        runtime_form.setHorizontalSpacing(14)
        runtime_form.setVerticalSpacing(8)

        env_edit = QLineEdit()
        env_edit.setPlaceholderText("dev / stage / prod")
        runtime_env_label = QLabel("Environment Profil")
        runtime_form.addRow(runtime_env_label, env_edit)
        self._runtime_row_labels["env_name"] = runtime_env_label
        self._env_name_edit = env_edit

        overlay_edit = QLineEdit()
        overlay_edit.setPlaceholderText("profil_a,profil_b")
        runtime_overlay_label = QLabel("Overlay Profile")
        runtime_form.addRow(runtime_overlay_label, overlay_edit)
        self._runtime_row_labels["overlay_profiles"] = runtime_overlay_label
        self._overlay_profiles_edit = overlay_edit

        strict_cb = QCheckBox("")
        runtime_strict_label = QLabel("Strict Policy")
        runtime_form.addRow(runtime_strict_label, strict_cb)
        self._runtime_row_labels["strict_policy"] = runtime_strict_label
        self._strict_policy_cb = strict_cb

        trace_cb = QCheckBox("")
        runtime_trace_label = QLabel("Run Tracing")
        runtime_form.addRow(runtime_trace_label, trace_cb)
        self._runtime_row_labels["trace_enabled"] = runtime_trace_label
        self._trace_enabled_cb = trace_cb

        cache_cb = QCheckBox("")
        runtime_cache_label = QLabel("Tool Cache")
        runtime_form.addRow(runtime_cache_label, cache_cb)
        self._runtime_row_labels["cache_enabled"] = runtime_cache_label
        self._cache_enabled_cb = cache_cb

        detail_combo = QComboBox()
        for value, fallback in _MAP_RESULT_DETAIL_OPTIONS:
            detail_combo.addItem(fallback, value)
        runtime_detail_label = QLabel("Mindmap/Graph Ausgabe")
        runtime_form.addRow(runtime_detail_label, detail_combo)
        self._runtime_row_labels["map_result_detail_level"] = runtime_detail_label
        self._map_result_detail_combo = detail_combo

        root.addWidget(runtime_group)
        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons_box = buttons
        root.addWidget(buttons)

    @staticmethod
    def _new_profile_combo(profile_ids: Sequence[str]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        seen: set[str] = set()
        for item in list(profile_ids or []):
            text = str(item or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            combo.addItem(text)
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("profile_id")
        return combo

    def _load_values(self) -> None:
        self._set_row_values(
            "factcheck",
            enabled=bool(self._base.factcheck_enabled),
            profile_id=str(self._base.factcheck_profile_id or ""),
        )
        self._set_row_values(
            "chat",
            enabled=bool(self._base.chat_enabled),
            profile_id=str(self._base.chat_profile_id or ""),
        )
        self._set_row_values(
            "canvas",
            enabled=bool(self._base.canvas_enabled),
            profile_id=str(self._base.canvas_profile_id or ""),
        )
        self._set_row_values(
            "mindmap",
            enabled=bool(self._base.mindmap_enabled),
            profile_id=str(self._base.mindmap_profile_id or ""),
        )
        self._set_row_values(
            "graph",
            enabled=bool(self._base.graph_enabled),
            profile_id=str(self._base.graph_profile_id or ""),
        )

        if self._env_name_edit is not None:
            self._env_name_edit.setText(str(self._base.env_name or ""))
        if self._overlay_profiles_edit is not None:
            self._overlay_profiles_edit.setText(
                str(self._base.overlay_profile_ids_raw or "")
            )
        if self._strict_policy_cb is not None:
            self._strict_policy_cb.setChecked(bool(self._base.strict_policy))
        if self._trace_enabled_cb is not None:
            self._trace_enabled_cb.setChecked(bool(self._base.trace_enabled))
        if self._cache_enabled_cb is not None:
            self._cache_enabled_cb.setChecked(bool(self._base.cache_enabled))
        if self._map_result_detail_combo is not None:
            value = str(self._base.map_result_detail_level or "auto").strip().casefold()
            index = self._map_result_detail_combo.findData(value)
            self._map_result_detail_combo.setCurrentIndex(index if index >= 0 else 0)

        for key, _label in _WORKFLOW_ROWS:
            self._sync_row_enabled_state(key)

    def _set_row_values(self, workflow_key: str, *, enabled: bool, profile_id: str) -> None:
        checkbox = self._workflow_enabled.get(str(workflow_key))
        combo = self._workflow_profiles.get(str(workflow_key))
        if checkbox is None or combo is None:
            return
        checkbox.setChecked(bool(enabled))
        if profile_id:
            index = combo.findText(profile_id)
            if index < 0:
                combo.addItem(profile_id)
                index = combo.findText(profile_id)
            if index >= 0:
                combo.setCurrentIndex(index)
            else:
                combo.setEditText(profile_id)

    def _sync_row_enabled_state(self, workflow_key: str) -> None:
        checkbox = self._workflow_enabled.get(str(workflow_key))
        combo = self._workflow_profiles.get(str(workflow_key))
        if checkbox is None or combo is None:
            return
        combo.setEnabled(bool(checkbox.isChecked()))

    def _apply_labels(self) -> None:
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "agentic.settings.window_title",
                "Agentic Workflow Settings",
            )
        )
        if self._intro_label is not None:
            self._intro_label.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.intro",
                    "Konfiguriert zentrale Agenten-Workflows für Factcheck, Chat, "
                    "Canvas und Mindmap. Änderungen greifen sofort für neue Läufe.",
                )
            )
        if self._workflow_group is not None:
            self._workflow_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.group.workflows",
                    "Workflows",
                )
            )
        if self._runtime_group is not None:
            self._runtime_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.group.runtime",
                    "Runtime / Policy",
                )
            )

        for workflow_key, fallback in _WORKFLOW_ROWS:
            label_widget = self._workflow_row_labels.get(workflow_key)
            enabled_cb = self._workflow_enabled.get(workflow_key)
            combo = self._workflow_profiles.get(workflow_key)
            if label_widget is not None:
                label_widget.setText(
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.workflow.{workflow_key}.row_label",
                        fallback,
                    )
                )
            if enabled_cb is not None:
                enabled_cb.setText(
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.workflow.{workflow_key}.enabled",
                        "Aktiv",
                    )
                )
            if combo is not None:
                combo.setToolTip(
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.workflow.{workflow_key}.profile.tooltip",
                        "Profil-ID für diesen Workflow.",
                    )
                )

        row_defaults = {
            "env_name": "Environment Profil",
            "overlay_profiles": "Overlay Profile",
            "strict_policy": "Strict Policy",
            "trace_enabled": "Run Tracing",
            "cache_enabled": "Tool Cache",
            "map_result_detail_level": "Mindmap/Graph Ausgabe",
        }
        for row_key, label_widget in self._runtime_row_labels.items():
            label_widget.setText(
                resolve_feature_label(
                    self._user_mode,
                    f"agentic.settings.runtime.{row_key}.row_label",
                    row_defaults.get(row_key, row_key),
                )
            )

        if self._strict_policy_cb is not None:
            self._strict_policy_cb.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.strict_policy.value_label",
                    "Unzulässige Tools/Steps strikt blockieren",
                )
            )
        if self._trace_enabled_cb is not None:
            self._trace_enabled_cb.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.trace_enabled.value_label",
                    "Run-Traces unter runs/agentic schreiben",
                )
            )
        if self._cache_enabled_cb is not None:
            self._cache_enabled_cb.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.cache_enabled.value_label",
                    "Tool-Cache aktivieren",
                )
            )
        if self._map_result_detail_combo is not None:
            for idx, (value, fallback) in enumerate(_MAP_RESULT_DETAIL_OPTIONS):
                self._map_result_detail_combo.setItemText(
                    idx,
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.runtime.map_result_detail_level.option.{value}",
                        fallback,
                    ),
                )
            self._map_result_detail_combo.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.map_result_detail_level.tooltip",
                    "Steuert, wie ausfuehrlich Mindmap-/Graph-Ergebnisse im Chat zusammengefasst werden.",
                )
            )
        if self._env_name_edit is not None:
            self._env_name_edit.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.env_name.tooltip",
                    "Optional: lädt zusätzliches Profil _env_<name>.",
                )
            )
        if self._overlay_profiles_edit is not None:
            self._overlay_profiles_edit.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.overlay_profiles.tooltip",
                    "Komma-getrennte zusätzliche Overlay-Profile.",
                )
            )
        if self._buttons_box is not None:
            ok_btn = self._buttons_box.button(QDialogButtonBox.StandardButton.Ok)
            if ok_btn is not None:
                ok_btn.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "agentic.settings.button.ok",
                        "OK",
                    )
                )
            cancel_btn = self._buttons_box.button(
                QDialogButtonBox.StandardButton.Cancel
            )
            if cancel_btn is not None:
                cancel_btn.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "agentic.settings.button.cancel",
                        "Abbrechen",
                    )
                )

    def get_settings(self) -> AgenticRuntimeSettings:
        data = {
            "factcheck_enabled": bool(
                self._workflow_enabled["factcheck"].isChecked()
            ),
            "chat_enabled": bool(self._workflow_enabled["chat"].isChecked()),
            "canvas_enabled": bool(self._workflow_enabled["canvas"].isChecked()),
            "mindmap_enabled": bool(self._workflow_enabled["mindmap"].isChecked()),
            "graph_enabled": bool(self._workflow_enabled["graph"].isChecked()),
            "factcheck_profile_id": str(
                self._workflow_profiles["factcheck"].currentText() or ""
            ).strip(),
            "chat_profile_id": str(
                self._workflow_profiles["chat"].currentText() or ""
            ).strip(),
            "canvas_profile_id": str(
                self._workflow_profiles["canvas"].currentText() or ""
            ).strip(),
            "mindmap_profile_id": str(
                self._workflow_profiles["mindmap"].currentText() or ""
            ).strip(),
            "graph_profile_id": str(
                self._workflow_profiles["graph"].currentText() or ""
            ).strip(),
            "strict_policy": bool(
                self._strict_policy_cb.isChecked() if self._strict_policy_cb else False
            ),
            "trace_enabled": bool(
                self._trace_enabled_cb.isChecked() if self._trace_enabled_cb else False
            ),
            "cache_enabled": bool(
                self._cache_enabled_cb.isChecked() if self._cache_enabled_cb else True
            ),
            "map_result_detail_level": str(
                self._map_result_detail_combo.currentData()
                if self._map_result_detail_combo is not None
                else "auto"
            ).strip()
            or "auto",
            "env_name": str(
                self._env_name_edit.text() if self._env_name_edit else ""
            ).strip(),
            "overlay_profile_ids_raw": str(
                self._overlay_profiles_edit.text()
                if self._overlay_profiles_edit
                else ""
            ).strip(),
        }
        return AgenticRuntimeSettings.from_dict(data)
