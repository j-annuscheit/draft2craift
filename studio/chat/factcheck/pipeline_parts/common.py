"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@classmethod
def _collapse_ws(cls, value: object) -> str:
    return cls._WS_RE.sub(" ", str(value or "")).strip()

def _fact_log_debug(self, message: str):
    logger = getattr(self.llm, "_log", None)
    if logger is not None and hasattr(logger, "debug"):
        try:
            logger.debug("LLM", f"[FACTCHECK] {message}")
        except Exception:
            pass

def _fact_log_info(self, message: str):
    logger = getattr(self.llm, "_log", None)
    if logger is not None and hasattr(logger, "info"):
        try:
            logger.info("LLM", f"[FACTCHECK] {message}")
        except Exception:
            pass

def _nli_prompt_workflow_preview(self) -> str:
    render = getattr(self.llm, "render_prompt_template", None)
    system_block = ""
    user_block = ""
    if callable(render):
        try:
            system_block = str(render("nli_verify_system") or "").strip()
        except Exception:
            system_block = ""
        try:
            user_block = str(
                render(
                    "nli_verify_user",
                    {
                        "premise": "<Chunk-Text>",
                        "hypothesis": "<Fakt/Claim>",
                    },
                )
                or ""
            ).strip()
        except Exception:
            user_block = ""
    if not system_block:
        system_block = (
            "Transformers NLI Workflow: tokenize(premise,hypothesis) -> "
            "logits -> softmax -> label entailment|neutral|contradiction."
        )
    if not user_block:
        user_block = "premise=<Chunk-Text>\nhypothesis=<Fakt/Claim>"
    return (
        "ℹ NLI-Workflow (Debug-Template):\n"
        "[backend=transformers-cross-encoder]\n"
        "<|workflow|>\n"
        f"{system_block}\n"
        "<|input|>\n"
        f"{user_block}\n"
    )

@classmethod
def _normalize_factcheck_mode(cls, mode: str) -> str:
    value = str(mode or "").strip().casefold()
    if value == "nli":
        return "nli"
    if value in {"llm", "llm_chunk", "chunk", "chunkwise"}:
        return "llm_chunk"
    if value in {"llm_global", "global", "all", "all_sources"}:
        return "llm_global"
    if value in {
        "llm_claim_nli",
        "claim_nli",
        "claims",
        "claims_nli",
        "llm_claims_nli",
        "two_phase",
    }:
        return "llm_claim_nli"
    if value == "both":
        return "both"
    return ""

@classmethod
def _normalize_factcheck_selection(
    cls,
    raw_selection: object,
) -> list[str]:
    seen: set[str] = set()

    def add_mode(raw_mode: object):
        normalized = cls._normalize_factcheck_mode(str(raw_mode or ""))
        if not normalized:
            return
        if normalized == "both":
            for expanded in ("nli", "llm_chunk"):
                seen.add(expanded)
            return
        seen.add(normalized)

    if isinstance(raw_selection, (list, tuple, set)):
        for item in raw_selection:
            add_mode(item)
    else:
        add_mode(raw_selection)

    if not seen:
        seen = {"nli"}
    return [mode for mode in cls._FACTCHECK_METHOD_ORDER if mode in seen]

def _select_factcheck_modes(self) -> list[str] | None:
    default_pref = getattr(
        self,
        "_factcheck_modes_pref",
        getattr(self, "_factcheck_mode_pref", "nli"),
    )
    default_modes = self._normalize_factcheck_selection(default_pref)
    if not isinstance(self, QObject):
        return default_modes

    checkboxes: dict[str, QCheckBox] = {}
    try:
        dialog = QDialog(self)
        dialog.setWindowTitle("Faktencheck-Methoden")

        layout = QVBoxLayout(dialog)
        header = QLabel("Wähle eine oder mehrere Faktencheck-Methoden:")
        header.setWordWrap(True)
        layout.addWidget(header)

        warning = QLabel(
            "⚠ Hinweis: LLM (Chunk-weise) ist sehr langsam, weil jeder Fakt "
            "gegen jeden Chunk geprüft wird."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        for mode in self._FACTCHECK_METHOD_ORDER:
            label = self._FACTCHECK_MODE_LABELS.get(mode, mode)
            cb = QCheckBox(label)
            cb.setChecked(mode in default_modes)
            if mode == "llm_chunk":
                cb.setToolTip(
                    "Sehr langsam: pro Fakt werden alle Chunks einzeln vom LLM geprüft."
                )
            elif mode == "llm_claim_nli":
                cb.setToolTip(
                    "Zweistufig: zuerst Claim-Extraktion pro Chunk (mit Cache), danach NLI-Abgleich."
                )
            checkboxes[mode] = cb
            layout.addWidget(cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
    except Exception:
        return default_modes

    selected = [
        mode
        for mode in self._FACTCHECK_METHOD_ORDER
        if checkboxes.get(mode) is not None and checkboxes[mode].isChecked()
    ]
    normalized = self._normalize_factcheck_selection(selected) if selected else []
    if normalized:
        setattr(self, "_factcheck_modes_pref", normalized)
        setattr(self, "_factcheck_mode_pref", normalized[0])
    return normalized

def _select_factcheck_mode(self) -> str:
    selected = self._select_factcheck_modes()
    if not selected:
        return ""
    return selected[0]

__all__ = [
    "_collapse_ws",
    "_fact_log_debug",
    "_fact_log_info",
    "_nli_prompt_workflow_preview",
    "_normalize_factcheck_mode",
    "_normalize_factcheck_selection",
    "_select_factcheck_modes",
    "_select_factcheck_mode",
]
