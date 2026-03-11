"""Runner dialog UI for launching eval pipelines."""
from __future__ import annotations

import pathlib
from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from shared.config.paths import app_data_dir
from test_studio.components.runner_fields import RunnerFields


class RunnerDialog(QDialog):
    def __init__(
        self,
        *,
        fields: RunnerFields,
        style_sheet: str,
        callbacks: dict[str, Callable[[], None]],
    ) -> None:
        super().__init__()
        self.setWindowTitle("Run Test Pipelines")
        self.resize(980, 760)
        self.setStyleSheet(style_sheet)

        self.fields = fields
        self.callbacks = callbacks

        self.runner_tabs = QTabWidget()
        self.runner_log = QPlainTextEdit()
        self.runner_log.setReadOnly(True)
        self.runner_log.setPlaceholderText("Runner log output...")

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_runner_tab(), 1)

    def append_log(self, text: str) -> None:
        self.runner_log.appendPlainText(str(text))

    def clear_log(self) -> None:
        self.runner_log.clear()

    def _build_runner_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        top_row = QHBoxLayout()
        run_all_btn = QPushButton(
            "Run All-Tests (Export + RAG + PDF + Glossary + Fact-Check + Judge + LLM-Compare)"
        )
        run_all_btn.clicked.connect(self.callbacks["run_all"])
        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self.callbacks["stop"])
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.clear_log)
        top_row.addWidget(run_all_btn)
        top_row.addWidget(stop_btn)
        top_row.addWidget(clear_log_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        self.runner_tabs.addTab(self._build_feedback_tab(), "Feedback->Suites")
        self.runner_tabs.addTab(self._build_rag_tab(), "RAG")
        self.runner_tabs.addTab(self._build_pdf_tab(), "PDF->Markdown")
        self.runner_tabs.addTab(self._build_glossary_tab(), "Glossary")
        self.runner_tabs.addTab(self._build_factcheck_tab(), "Fact-Check")
        self.runner_tabs.addTab(self._build_judge_tab(), "Judge")
        self.runner_tabs.addTab(self._build_llmcompare_tab(), "LLM-Compare")
        layout.addWidget(self.runner_tabs, 1)

        log_label = QLabel("Runner Output")
        log_label.setStyleSheet("color: #7F849C;")
        layout.addWidget(log_label)
        self.runner_log.setMinimumHeight(220)
        layout.addWidget(self.runner_log, 1)
        return page

    def _build_feedback_tab(self) -> QWidget:
        page, form, layout = self._new_form_page()
        form.addRow("Storage dir", self._with_browse(self.fields.fb_storage_edit, "dir", "Select feedback storage directory"))
        form.addRow("Output dir", self._with_browse(self.fields.fb_out_edit, "dir", "Select generated-suite output directory"))
        form.addRow("Run name", self.fields.fb_run_name_edit)
        form.addRow("Mode", self.fields.fb_include_unaccepted_cb)

        hint = QLabel(
            "Exports accepted testcase registry to six suite files and updates suite paths for the next runs."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #7F849C;")
        form.addRow("", hint)

        row = QHBoxLayout()
        run_btn = QPushButton("Export Feedback->Suites")
        run_btn.clicked.connect(self.callbacks["run_feedback"])
        apply_btn = QPushButton("Apply Suite Paths Only")
        apply_btn.clicked.connect(self.callbacks["apply_feedback_paths"])
        row.addWidget(run_btn)
        row.addWidget(apply_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_rag_tab(self) -> QWidget:
        page, form, layout = self._new_form_page()
        form.addRow("Suite", self._with_browse(self.fields.rag_suite_edit, "file", "Select RAG suite JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Output dir", self._with_browse(self.fields.rag_out_edit, "dir", "Select RAG output directory"))
        form.addRow("Run name", self.fields.rag_name_edit)
        form.addRow("Labels", self.fields.rag_labels_edit)
        form.addRow("Top-K (0=default)", self.fields.rag_topk_spin)
        form.addRow("Config overrides (k=v,...)", self.fields.rag_set_edit)
        form.addRow("LLM model (optional)", self._with_browse(self.fields.rag_model_edit, "file", "Select LLM model", "GGUF model (*.gguf);;All files (*)"))
        form.addRow("LLM n_ctx", self.fields.rag_ctx_spin)
        form.addRow("LLM gpu layers", self.fields.rag_gpu_spin)
        form.addRow("LLM threads (0=auto)", self.fields.rag_threads_spin)
        form.addRow("Log level", self.fields.rag_log_combo)
        layout.addLayout(self._run_button_row("Run RAG Tests", "run_rag"))
        return page

    def _build_pdf_tab(self) -> QWidget:
        page, form, layout = self._new_form_page()
        form.addRow("Suite", self._with_browse(self.fields.pdf_suite_edit, "file", "Select PDF suite JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Output dir", self._with_browse(self.fields.pdf_out_edit, "dir", "Select PDF output directory"))
        form.addRow("Run name", self.fields.pdf_name_edit)
        form.addRow("Labels", self.fields.pdf_labels_edit)
        form.addRow("Max cases (0=all)", self.fields.pdf_max_cases_spin)
        form.addRow("PDF setting overrides (k=v,...)", self.fields.pdf_set_edit)
        form.addRow("Log level", self.fields.pdf_log_combo)
        layout.addLayout(self._run_button_row("Run PDF Tests", "run_pdf"))
        return page

    def _build_glossary_tab(self) -> QWidget:
        page, form, layout = self._new_form_page()
        form.addRow("Suite", self._with_browse(self.fields.gloss_suite_edit, "file", "Select glossary suite JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Output dir", self._with_browse(self.fields.gloss_out_edit, "dir", "Select glossary output directory"))
        form.addRow("Run name", self.fields.gloss_name_edit)
        form.addRow("Labels", self.fields.gloss_labels_edit)
        form.addRow("Max cases (0=all)", self.fields.gloss_max_cases_spin)
        form.addRow("LLM model (required)", self._with_browse(self.fields.gloss_model_edit, "file", "Select glossary LLM model", "GGUF model (*.gguf);;All files (*)"))
        form.addRow("LLM n_ctx", self.fields.gloss_ctx_spin)
        form.addRow("LLM gpu layers", self.fields.gloss_gpu_spin)
        form.addRow("LLM threads (0=auto)", self.fields.gloss_threads_spin)
        form.addRow("Prompt overrides JSON (optional)", self._with_browse(self.fields.gloss_prompts_edit, "file", "Select prompt override JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Override max_terms (0=off)", self.fields.gloss_max_terms_spin)
        form.addRow("Override context chars (0=off)", self.fields.gloss_ctx_chars_spin)
        form.addRow("Override threshold_recall (-1=off)", self.fields.gloss_recall_spin)
        form.addRow("Setting overrides (k=v,...)", self.fields.gloss_set_edit)
        form.addRow("Log level", self.fields.gloss_log_combo)
        layout.addLayout(self._run_button_row("Run Glossary Tests", "run_glossary"))
        return page

    def _build_factcheck_tab(self) -> QWidget:
        page, form, layout = self._new_form_page()
        form.addRow("Suite", self._with_browse(self.fields.fact_suite_edit, "file", "Select fact-check suite JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Output dir", self._with_browse(self.fields.fact_out_edit, "dir", "Select fact-check output directory"))
        form.addRow("Run name", self.fields.fact_name_edit)
        form.addRow("Labels", self.fields.fact_labels_edit)
        form.addRow("Max cases (0=all)", self.fields.fact_max_cases_spin)
        form.addRow("Mode", self.fields.fact_mode_combo)
        form.addRow("LLM model (required)", self._with_browse(self.fields.fact_model_edit, "file", "Select fact-check LLM model", "GGUF model (*.gguf);;All files (*)"))
        form.addRow("LLM n_ctx", self.fields.fact_ctx_spin)
        form.addRow("LLM gpu layers", self.fields.fact_gpu_spin)
        form.addRow("LLM threads (0=auto)", self.fields.fact_threads_spin)
        form.addRow("Prompt overrides JSON (optional)", self._with_browse(self.fields.fact_prompts_edit, "file", "Select prompt override JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Extract threshold (-1=off)", self.fields.fact_extract_thr)
        form.addRow("Verify threshold (-1=off)", self.fields.fact_verify_thr)
        form.addRow("Full F1 threshold (-1=off)", self.fields.fact_full_thr)
        form.addRow("Source chars override (0=off)", self.fields.fact_source_chars_spin)
        form.addRow("Target chars override (0=off)", self.fields.fact_target_chars_spin)
        form.addRow("Max verify facts override (0=off)", self.fields.fact_max_verify_spin)
        form.addRow("Extract max tokens", self.fields.fact_extract_tokens_spin)
        form.addRow("Verify max tokens", self.fields.fact_verify_tokens_spin)
        form.addRow("Temperature", self.fields.fact_temp_spin)
        form.addRow("Setting overrides (k=v,...)", self.fields.fact_set_edit)
        form.addRow("Log level", self.fields.fact_log_combo)
        layout.addLayout(self._run_button_row("Run Fact-Check Tests", "run_factcheck"))
        return page

    def _build_judge_tab(self) -> QWidget:
        page, form, layout = self._new_form_page()
        form.addRow("Suite", self._with_browse(self.fields.judge_suite_edit, "file", "Select judge suite JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Output dir", self._with_browse(self.fields.judge_out_edit, "dir", "Select judge output directory"))
        form.addRow("Run name", self.fields.judge_name_edit)
        form.addRow("Labels", self.fields.judge_labels_edit)
        form.addRow("Max cases (0=all)", self.fields.judge_max_cases_spin)
        form.addRow("LLM model (required)", self._with_browse(self.fields.judge_model_edit, "file", "Select judge LLM model", "GGUF model (*.gguf);;All files (*)"))
        form.addRow("LLM n_ctx", self.fields.judge_ctx_spin)
        form.addRow("LLM gpu layers", self.fields.judge_gpu_spin)
        form.addRow("LLM threads (0=auto)", self.fields.judge_threads_spin)
        form.addRow("Prompt overrides JSON (optional)", self._with_browse(self.fields.judge_prompts_edit, "file", "Select judge prompt JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Judge prompt key", self.fields.judge_prompt_key_edit)
        form.addRow("Judge prompt file (optional)", self._with_browse(self.fields.judge_prompt_file_edit, "file", "Select judge prompt file", "Text files (*.txt *.md);;All files (*)"))
        form.addRow("Judge max tokens", self.fields.judge_max_tokens_spin)
        form.addRow("Temperature", self.fields.judge_temp_spin)
        form.addRow("Top-p", self.fields.judge_top_p_spin)
        form.addRow("Repeat penalty", self.fields.judge_repeat_penalty_spin)
        form.addRow("Seed (-1=off)", self.fields.judge_seed_spin)
        form.addRow("Prompt max chars override (0=off)", self.fields.judge_prompt_chars_spin)
        form.addRow("Answer max chars override (0=off)", self.fields.judge_answer_chars_spin)
        form.addRow("Threshold accuracy override (-1=off)", self.fields.judge_threshold_spin)
        form.addRow("Setting overrides (k=v,...)", self.fields.judge_set_edit)
        form.addRow("Artifacts", self.fields.judge_artifacts_combo)
        form.addRow("Log level", self.fields.judge_log_combo)
        layout.addLayout(self._run_button_row("Run Judge Tests", "run_judge"))
        return page

    def _build_llmcompare_tab(self) -> QWidget:
        page, form, layout = self._new_form_page()
        form.addRow("Suite", self._with_browse(self.fields.cmp_suite_edit, "file", "Select LLM compare suite JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Output dir", self._with_browse(self.fields.cmp_out_edit, "dir", "Select LLM compare output directory"))
        form.addRow("Run name", self.fields.cmp_name_edit)
        form.addRow("Labels", self.fields.cmp_labels_edit)
        form.addRow("Max cases (0=all)", self.fields.cmp_max_cases_spin)
        form.addRow("Prompts JSON (optional)", self._with_browse(self.fields.cmp_prompts_edit, "file", "Select prompt override JSON", "JSON (*.json);;All files (*)"))
        form.addRow("Candidate prompt key", self.fields.cmp_candidate_prompt_key_edit)
        form.addRow("Candidate prompt file (optional)", self._with_browse(self.fields.cmp_candidate_prompt_file_edit, "file", "Select candidate prompt file", "Text files (*.txt *.md);;All files (*)"))
        form.addRow("Judge prompt key", self.fields.cmp_judge_prompt_key_edit)
        form.addRow("Judge prompt file (optional)", self._with_browse(self.fields.cmp_judge_prompt_file_edit, "file", "Select judge prompt file", "Text files (*.txt *.md);;All files (*)"))
        form.addRow("Prompt max chars override (0=off)", self.fields.cmp_prompt_chars_spin)
        form.addRow("Threshold win gap (-1=off)", self.fields.cmp_threshold_gap_spin)
        form.addRow("Swap order", self.fields.cmp_swap_combo)
        form.addRow("A label", self.fields.cmp_a_label_edit)
        form.addRow("A model (required)", self._with_browse(self.fields.cmp_a_model_edit, "file", "Select candidate A model", "GGUF model (*.gguf);;All files (*)"))
        form.addRow("A n_ctx", self.fields.cmp_a_ctx_spin)
        form.addRow("A gpu layers", self.fields.cmp_a_gpu_spin)
        form.addRow("A threads (0=auto)", self.fields.cmp_a_threads_spin)
        form.addRow("A max tokens", self.fields.cmp_a_tokens_spin)
        form.addRow("A temperature", self.fields.cmp_a_temp_spin)
        form.addRow("A top-p", self.fields.cmp_a_top_p_spin)
        form.addRow("A repeat penalty", self.fields.cmp_a_repeat_spin)
        form.addRow("A seed (-1=off)", self.fields.cmp_a_seed_spin)
        form.addRow("B label", self.fields.cmp_b_label_edit)
        form.addRow("B model (required)", self._with_browse(self.fields.cmp_b_model_edit, "file", "Select candidate B model", "GGUF model (*.gguf);;All files (*)"))
        form.addRow("B n_ctx", self.fields.cmp_b_ctx_spin)
        form.addRow("B gpu layers", self.fields.cmp_b_gpu_spin)
        form.addRow("B threads (0=auto)", self.fields.cmp_b_threads_spin)
        form.addRow("B max tokens", self.fields.cmp_b_tokens_spin)
        form.addRow("B temperature", self.fields.cmp_b_temp_spin)
        form.addRow("B top-p", self.fields.cmp_b_top_p_spin)
        form.addRow("B repeat penalty", self.fields.cmp_b_repeat_spin)
        form.addRow("B seed (-1=off)", self.fields.cmp_b_seed_spin)
        form.addRow("Judge model (required)", self._with_browse(self.fields.cmp_j_model_edit, "file", "Select compare judge model", "GGUF model (*.gguf);;All files (*)"))
        form.addRow("Judge n_ctx", self.fields.cmp_j_ctx_spin)
        form.addRow("Judge gpu layers", self.fields.cmp_j_gpu_spin)
        form.addRow("Judge threads (0=auto)", self.fields.cmp_j_threads_spin)
        form.addRow("Judge max tokens", self.fields.cmp_j_tokens_spin)
        form.addRow("Judge temperature", self.fields.cmp_j_temp_spin)
        form.addRow("Judge top-p", self.fields.cmp_j_top_p_spin)
        form.addRow("Judge repeat penalty", self.fields.cmp_j_repeat_spin)
        form.addRow("Judge seed (-1=off)", self.fields.cmp_j_seed_spin)
        form.addRow("Setting overrides (k=v,...)", self.fields.cmp_set_edit)
        form.addRow("Artifacts", self.fields.cmp_artifacts_combo)
        form.addRow("Log level", self.fields.cmp_log_combo)
        layout.addLayout(self._run_button_row("Run LLM-Compare Tests", "run_llmcompare"))
        return page

    def _run_button_row(self, label: str, callback_key: str) -> QHBoxLayout:
        row = QHBoxLayout()
        run_btn = QPushButton(label)
        run_btn.clicked.connect(self.callbacks[callback_key])
        row.addWidget(run_btn)
        row.addStretch()
        return row

    @staticmethod
    def _new_form_page() -> tuple[QWidget, QFormLayout, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        layout.addLayout(form)
        return page, form, layout

    def _with_browse(
        self,
        edit: QLineEdit,
        mode: str,
        caption: str,
        file_filter: str = "All files (*)",
    ) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        button = QPushButton("...")
        button.setMaximumWidth(34)
        button.setToolTip(caption)

        if mode == "dir":
            button.clicked.connect(lambda _=False, e=edit, c=caption: self._choose_dir_for(e, c))
        else:
            button.clicked.connect(
                lambda _=False, e=edit, c=caption, f=file_filter: self._choose_file_for(e, c, f)
            )

        row.addWidget(edit, 1)
        row.addWidget(button)
        return wrap

    @staticmethod
    def _browse_base_dir(current_text: str) -> str:
        base = pathlib.Path(app_data_dir())
        raw = str(current_text or "").strip()
        if not raw:
            return str(base)
        path = pathlib.Path(raw).expanduser()
        if not path.is_absolute():
            path = (base / path).resolve(strict=False)
        if path.exists():
            return str(path if path.is_dir() else path.parent)
        if path.suffix:
            return str(path.parent)
        return str(path)

    def _choose_file_for(self, edit: QLineEdit, caption: str, file_filter: str) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            caption,
            self._browse_base_dir(edit.text()),
            file_filter,
        )
        if selected:
            edit.setText(selected)

    def _choose_dir_for(self, edit: QLineEdit, caption: str) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            caption,
            self._browse_base_dir(edit.text()),
        )
        if selected:
            edit.setText(selected)
