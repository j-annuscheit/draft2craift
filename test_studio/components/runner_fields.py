"""Widget registry for test pipeline runner configuration."""
from __future__ import annotations

import pathlib

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox


class RunnerFields:
    def __init__(self, project_root: pathlib.Path) -> None:
        self.project_root = project_root

        self.fb_storage_edit = QLineEdit("runs/feedback")
        self.fb_out_edit = QLineEdit("runs/feedback/generated")
        self.fb_run_name_edit = QLineEdit("")
        self.fb_include_unaccepted_cb = QCheckBox("Entwürfe mit exportieren")
        self.fb_include_unaccepted_cb.setChecked(False)

        self.rag_suite_edit = QLineEdit("eval/examples/rag_suite.example.json")
        self.rag_out_edit = QLineEdit("runs/rag_eval")
        self.rag_name_edit = QLineEdit("gui_rag")
        self.rag_labels_edit = QLineEdit("")
        self.rag_topk_spin = self._spin(0, 200, 0)
        self.rag_set_edit = QLineEdit("")
        self.rag_model_edit = QLineEdit("")
        self.rag_ctx_spin = self._spin(256, 65536, 4096)
        self.rag_gpu_spin = self._spin(-1, 1024, 0)
        self.rag_threads_spin = self._spin(0, 256, 0)
        self.rag_log_combo = self._combo(["INFO", "DEBUG", "WARNING", "ERROR"])

        self.pdf_suite_edit = QLineEdit("eval/examples/pdf_suite.example.json")
        self.pdf_out_edit = QLineEdit("runs/pdf_eval")
        self.pdf_name_edit = QLineEdit("gui_pdf")
        self.pdf_labels_edit = QLineEdit("")
        self.pdf_max_cases_spin = self._spin(0, 10000, 0)
        self.pdf_set_edit = QLineEdit("")
        self.pdf_log_combo = self._combo(["INFO", "DEBUG", "WARNING", "ERROR"])

        self.gloss_suite_edit = QLineEdit("eval/examples/glossary_suite.example.json")
        self.gloss_out_edit = QLineEdit("runs/glossary_eval")
        self.gloss_name_edit = QLineEdit("gui_glossary")
        self.gloss_labels_edit = QLineEdit("")
        self.gloss_max_cases_spin = self._spin(0, 10000, 0)
        self.gloss_model_edit = QLineEdit("")
        self.gloss_ctx_spin = self._spin(256, 65536, 4096)
        self.gloss_gpu_spin = self._spin(-1, 1024, 0)
        self.gloss_threads_spin = self._spin(0, 256, 0)
        self.gloss_max_terms_spin = self._spin(0, 512, 0)
        self.gloss_ctx_chars_spin = self._spin(0, 500000, 0)
        self.gloss_recall_spin = self._double_spin(-1.0, 1.0, -1.0, 0.05, 2)
        self.gloss_set_edit = QLineEdit("")
        self.gloss_prompts_edit = QLineEdit("")
        self.gloss_log_combo = self._combo(["INFO", "DEBUG", "WARNING", "ERROR"])

        self.fact_suite_edit = QLineEdit("eval/examples/factcheck_suite.3stage.json")
        self.fact_out_edit = QLineEdit("runs/factcheck_eval")
        self.fact_name_edit = QLineEdit("gui_factcheck")
        self.fact_labels_edit = QLineEdit("")
        self.fact_max_cases_spin = self._spin(0, 10000, 0)
        self.fact_mode_combo = self._combo(["all", "extract", "verify", "full"])
        self.fact_model_edit = QLineEdit("")
        self.fact_ctx_spin = self._spin(256, 65536, 4096)
        self.fact_gpu_spin = self._spin(-1, 1024, 0)
        self.fact_threads_spin = self._spin(0, 256, 0)
        self.fact_prompts_edit = QLineEdit("")
        self.fact_extract_thr = self._double_spin(-1.0, 1.0, -1.0, 0.05, 2)
        self.fact_verify_thr = self._double_spin(-1.0, 1.0, -1.0, 0.05, 2)
        self.fact_full_thr = self._double_spin(-1.0, 1.0, -1.0, 0.05, 2)
        self.fact_source_chars_spin = self._spin(0, 500000, 0)
        self.fact_target_chars_spin = self._spin(0, 500000, 0)
        self.fact_max_verify_spin = self._spin(0, 10000, 0)
        self.fact_extract_tokens_spin = self._spin(64, 8192, 1024)
        self.fact_verify_tokens_spin = self._spin(64, 2048, 220)
        self.fact_temp_spin = self._double_spin(0.0, 2.0, 0.70, 0.05, 2)
        self.fact_set_edit = QLineEdit("")
        self.fact_log_combo = self._combo(["INFO", "DEBUG", "WARNING", "ERROR"])

        self.judge_suite_edit = QLineEdit("eval/examples/judge_suite.example.json")
        self.judge_out_edit = QLineEdit("runs/judge_eval")
        self.judge_name_edit = QLineEdit("gui_judge")
        self.judge_labels_edit = QLineEdit("")
        self.judge_max_cases_spin = self._spin(0, 10000, 0)
        self.judge_model_edit = QLineEdit("")
        self.judge_ctx_spin = self._spin(256, 65536, 4096)
        self.judge_gpu_spin = self._spin(-1, 1024, 0)
        self.judge_threads_spin = self._spin(0, 256, 0)
        self.judge_prompts_edit = QLineEdit(self._defaults_prompt_path())
        self.judge_prompt_key_edit = QLineEdit("judge_pairwise_system")
        self.judge_prompt_file_edit = QLineEdit("")
        self.judge_max_tokens_spin = self._spin(32, 8192, 192)
        self.judge_temp_spin = self._double_spin(0.0, 2.0, 0.0, 0.05, 2)
        self.judge_top_p_spin = self._double_spin(0.0, 1.0, 1.0, 0.05, 2)
        self.judge_repeat_penalty_spin = self._double_spin(0.5, 2.0, 1.05, 0.01, 2)
        self.judge_seed_spin = self._spin(-1, 2147483647, -1)
        self.judge_prompt_chars_spin = self._spin(0, 500000, 0)
        self.judge_answer_chars_spin = self._spin(0, 500000, 0)
        self.judge_threshold_spin = self._double_spin(-1.0, 1.0, -1.0, 0.05, 2)
        self.judge_set_edit = QLineEdit("")
        self.judge_artifacts_combo = QComboBox()
        self.judge_artifacts_combo.addItem("Default", "default")
        self.judge_artifacts_combo.addItem("Write artifacts", "on")
        self.judge_artifacts_combo.addItem("No artifacts", "off")
        self.judge_log_combo = self._combo(["INFO", "DEBUG", "WARNING", "ERROR"])

        self.cmp_suite_edit = QLineEdit("eval/examples/llm_compare_suite.example.json")
        self.cmp_out_edit = QLineEdit("runs/llm_compare_eval")
        self.cmp_name_edit = QLineEdit("gui_llm_compare")
        self.cmp_labels_edit = QLineEdit("")
        self.cmp_max_cases_spin = self._spin(0, 10000, 0)
        self.cmp_prompts_edit = QLineEdit(self._defaults_prompt_path())
        self.cmp_candidate_prompt_key_edit = QLineEdit("llm_compare_candidate_system")
        self.cmp_candidate_prompt_file_edit = QLineEdit("")
        self.cmp_judge_prompt_key_edit = QLineEdit("judge_pairwise_system")
        self.cmp_judge_prompt_file_edit = QLineEdit("")
        self.cmp_prompt_chars_spin = self._spin(0, 500000, 0)
        self.cmp_threshold_gap_spin = self._double_spin(-1.0, 1.0, -1.0, 0.01, 2)
        self.cmp_swap_combo = QComboBox()
        self.cmp_swap_combo.addItem("Swap order enabled", "on")
        self.cmp_swap_combo.addItem("Swap order disabled", "off")

        self.cmp_a_label_edit = QLineEdit("A")
        self.cmp_a_model_edit = QLineEdit("")
        self.cmp_a_ctx_spin = self._spin(256, 65536, 4096)
        self.cmp_a_gpu_spin = self._spin(-1, 1024, 0)
        self.cmp_a_threads_spin = self._spin(0, 256, 0)
        self.cmp_a_tokens_spin = self._spin(32, 8192, 512)
        self.cmp_a_temp_spin = self._double_spin(0.0, 2.0, 0.20, 0.05, 2)
        self.cmp_a_top_p_spin = self._double_spin(0.0, 1.0, 0.95, 0.05, 2)
        self.cmp_a_repeat_spin = self._double_spin(0.5, 2.0, 1.05, 0.01, 2)
        self.cmp_a_seed_spin = self._spin(-1, 2147483647, -1)

        self.cmp_b_label_edit = QLineEdit("B")
        self.cmp_b_model_edit = QLineEdit("")
        self.cmp_b_ctx_spin = self._spin(256, 65536, 4096)
        self.cmp_b_gpu_spin = self._spin(-1, 1024, 0)
        self.cmp_b_threads_spin = self._spin(0, 256, 0)
        self.cmp_b_tokens_spin = self._spin(32, 8192, 512)
        self.cmp_b_temp_spin = self._double_spin(0.0, 2.0, 0.20, 0.05, 2)
        self.cmp_b_top_p_spin = self._double_spin(0.0, 1.0, 0.95, 0.05, 2)
        self.cmp_b_repeat_spin = self._double_spin(0.5, 2.0, 1.05, 0.01, 2)
        self.cmp_b_seed_spin = self._spin(-1, 2147483647, -1)

        self.cmp_j_model_edit = QLineEdit("")
        self.cmp_j_ctx_spin = self._spin(256, 65536, 4096)
        self.cmp_j_gpu_spin = self._spin(-1, 1024, 0)
        self.cmp_j_threads_spin = self._spin(0, 256, 0)
        self.cmp_j_tokens_spin = self._spin(32, 8192, 192)
        self.cmp_j_temp_spin = self._double_spin(0.0, 2.0, 0.0, 0.05, 2)
        self.cmp_j_top_p_spin = self._double_spin(0.0, 1.0, 1.0, 0.05, 2)
        self.cmp_j_repeat_spin = self._double_spin(0.5, 2.0, 1.05, 0.01, 2)
        self.cmp_j_seed_spin = self._spin(-1, 2147483647, -1)

        self.cmp_set_edit = QLineEdit("")
        self.cmp_artifacts_combo = QComboBox()
        self.cmp_artifacts_combo.addItem("Default", "default")
        self.cmp_artifacts_combo.addItem("Write artifacts", "on")
        self.cmp_artifacts_combo.addItem("No artifacts", "off")
        self.cmp_log_combo = self._combo(["INFO", "DEBUG", "WARNING", "ERROR"])

    def _defaults_prompt_path(self) -> str:
        rel = "data/prompts/defaults.json"
        return rel if (self.project_root / rel).exists() else ""

    @staticmethod
    def _combo(values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        return combo

    @staticmethod
    def _spin(min_value: int, max_value: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(min_value, max_value)
        spin.setValue(value)
        return spin

    @staticmethod
    def _double_spin(
        min_value: float,
        max_value: float,
        value: float,
        step: float,
        decimals: int,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(min_value, max_value)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setValue(value)
        return spin
