"""Command construction for Test Studio pipeline runner."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime
from typing import Callable

from test_studio.components.runner_fields import RunnerFields

class RunnerCommandBuilder:
    def __init__(
        self,
        *,
        fields: RunnerFields,
        project_root: pathlib.Path,
        log: Callable[[str], None],
    ) -> None:
        self.fields = fields
        self.project_root = project_root
        self.log = log
    def feedback_run_name(self) -> str:
        raw = self.fields.fb_run_name_edit.text().strip()
        if raw:
            return raw
        return "testcase_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def feedback_suite_path(output_dir: str, run_name: str, suite_id: str) -> str:
        suffix = {
            "rag": ".rag_suite.generated.json",
            "pdf": ".pdf_suite.generated.json",
            "glossary": ".glossary_suite.generated.json",
            "factcheck": ".factcheck_suite.generated.json",
            "judge": ".judge_suite.generated.json",
            "llmcompare": ".llm_compare_suite.generated.json",
        }[suite_id]
        return str((pathlib.Path(output_dir) / f"{run_name}{suffix}").resolve())

    def apply_feedback_suite_paths(self, run_name: str, output_dir: str) -> None:
        self.fields.rag_suite_edit.setText(self.feedback_suite_path(output_dir, run_name, "rag"))
        self.fields.pdf_suite_edit.setText(self.feedback_suite_path(output_dir, run_name, "pdf"))
        self.fields.gloss_suite_edit.setText(
            self.feedback_suite_path(output_dir, run_name, "glossary")
        )
        self.fields.fact_suite_edit.setText(
            self.feedback_suite_path(output_dir, run_name, "factcheck")
        )
        self.fields.judge_suite_edit.setText(
            self.feedback_suite_path(output_dir, run_name, "judge")
        )
        self.fields.cmp_suite_edit.setText(
            self.feedback_suite_path(output_dir, run_name, "llmcompare")
        )

    def feedback_case_counts(self) -> dict[str, int]:
        counts = {"rag": 0, "pdf": 0, "glossary": 0, "factcheck": 0, "judge": 0, "llmcompare": 0}
        storage = pathlib.Path(self.fields.fb_storage_edit.text().strip()).expanduser()
        path = storage / "test_cases.jsonl"
        if not path.exists():
            return counts

        include_unaccepted = self.fields.fb_include_unaccepted_cb.isChecked()
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if not include_unaccepted and not bool(row.get("accepted", False)):
                continue
            suite_id = str(row.get("suite_type", "")).strip().lower()
            if suite_id in counts:
                counts[suite_id] += 1
        return counts

    @staticmethod
    def parse_overrides_csv(text: str) -> list[str]:
        items: list[str] = []
        for part in str(text or "").replace("\n", ",").split(","):
            token = part.strip()
            if token:
                items.append(token)
        return items

    def resolve_judge_model_path(self) -> str:
        direct = self.fields.judge_model_edit.text().strip()
        if direct:
            return direct

        fallbacks = [
            self.fields.fact_model_edit.text().strip(),
            self.fields.gloss_model_edit.text().strip(),
            self.fields.rag_model_edit.text().strip(),
        ]
        for candidate in fallbacks:
            if candidate:
                return candidate

        models_dir = (self.project_root / "models").resolve()
        if models_dir.exists():
            for candidate in sorted(models_dir.rglob("*.gguf")):
                return str(candidate)
        return ""

    def build_feedback_export_command(self, *, run_name: str) -> list[str]:
        return [
            sys.executable,
            str((self.project_root / "eval" / "feedback_generate_tests.py").resolve()),
            "--storage-dir",
            self.fields.fb_storage_edit.text().strip(),
            "--output-dir",
            self.fields.fb_out_edit.text().strip(),
            "--run-name",
            run_name,
            "--include-unaccepted"
            if self.fields.fb_include_unaccepted_cb.isChecked()
            else "--no-include-unaccepted",
        ]

    def build_rag_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((self.project_root / "eval" / "rag_eval.py").resolve()),
            "--suite",
            self.fields.rag_suite_edit.text().strip(),
            "--output-dir",
            self.fields.rag_out_edit.text().strip(),
            "--log-level",
            self.fields.rag_log_combo.currentText().strip(),
        ]
        self._extend_if_text(cmd, "--run-name", self.fields.rag_name_edit.text())
        self._extend_if_text(cmd, "--labels", self.fields.rag_labels_edit.text())
        if int(self.fields.rag_topk_spin.value()) > 0:
            cmd.extend(["--top-k", str(int(self.fields.rag_topk_spin.value()))])
        self._extend_set_overrides(cmd, self.fields.rag_set_edit.text())

        llm_model = self.fields.rag_model_edit.text().strip()
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self.fields.rag_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self.fields.rag_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self.fields.rag_threads_spin.value()))])
        return cmd

    def build_pdf_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((self.project_root / "eval" / "pdf_eval.py").resolve()),
            "--suite",
            self.fields.pdf_suite_edit.text().strip(),
            "--output-dir",
            self.fields.pdf_out_edit.text().strip(),
            "--log-level",
            self.fields.pdf_log_combo.currentText().strip(),
        ]
        self._extend_if_text(cmd, "--run-name", self.fields.pdf_name_edit.text())
        self._extend_if_text(cmd, "--labels", self.fields.pdf_labels_edit.text())
        if int(self.fields.pdf_max_cases_spin.value()) > 0:
            cmd.extend(["--max-cases", str(int(self.fields.pdf_max_cases_spin.value()))])
        self._extend_set_overrides(cmd, self.fields.pdf_set_edit.text())
        return cmd

    def build_glossary_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((self.project_root / "eval" / "glossary_eval.py").resolve()),
            "--suite",
            self.fields.gloss_suite_edit.text().strip(),
            "--output-dir",
            self.fields.gloss_out_edit.text().strip(),
            "--log-level",
            self.fields.gloss_log_combo.currentText().strip(),
        ]
        self._extend_if_text(cmd, "--run-name", self.fields.gloss_name_edit.text())
        self._extend_if_text(cmd, "--labels", self.fields.gloss_labels_edit.text())
        if int(self.fields.gloss_max_cases_spin.value()) > 0:
            cmd.extend(["--max-cases", str(int(self.fields.gloss_max_cases_spin.value()))])

        llm_model = self.fields.gloss_model_edit.text().strip()
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self.fields.gloss_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self.fields.gloss_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self.fields.gloss_threads_spin.value()))])

        self._extend_if_text(cmd, "--prompts-json", self.fields.gloss_prompts_edit.text())
        if int(self.fields.gloss_max_terms_spin.value()) > 0:
            cmd.extend(["--max-terms", str(int(self.fields.gloss_max_terms_spin.value()))])
        if int(self.fields.gloss_ctx_chars_spin.value()) > 0:
            cmd.extend(["--context-max-chars", str(int(self.fields.gloss_ctx_chars_spin.value()))])
        if float(self.fields.gloss_recall_spin.value()) >= 0.0:
            cmd.extend(["--threshold-recall", f"{float(self.fields.gloss_recall_spin.value()):.2f}"])

        self._extend_set_overrides(cmd, self.fields.gloss_set_edit.text())
        return cmd

    def build_factcheck_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((self.project_root / "eval" / "factcheck_eval.py").resolve()),
            "--suite",
            self.fields.fact_suite_edit.text().strip(),
            "--output-dir",
            self.fields.fact_out_edit.text().strip(),
            "--log-level",
            self.fields.fact_log_combo.currentText().strip(),
            "--mode",
            self.fields.fact_mode_combo.currentText().strip(),
            "--extract-max-tokens",
            str(int(self.fields.fact_extract_tokens_spin.value())),
            "--verify-max-tokens",
            str(int(self.fields.fact_verify_tokens_spin.value())),
            "--temperature",
            f"{float(self.fields.fact_temp_spin.value()):.2f}",
        ]
        self._extend_if_text(cmd, "--run-name", self.fields.fact_name_edit.text())
        self._extend_if_text(cmd, "--labels", self.fields.fact_labels_edit.text())
        if int(self.fields.fact_max_cases_spin.value()) > 0:
            cmd.extend(["--max-cases", str(int(self.fields.fact_max_cases_spin.value()))])

        llm_model = self.fields.fact_model_edit.text().strip()
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self.fields.fact_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self.fields.fact_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self.fields.fact_threads_spin.value()))])

        self._extend_if_text(cmd, "--prompts-json", self.fields.fact_prompts_edit.text())
        if float(self.fields.fact_extract_thr.value()) >= 0.0:
            cmd.extend(["--threshold-extract-recall", f"{float(self.fields.fact_extract_thr.value()):.2f}"])
        if float(self.fields.fact_verify_thr.value()) >= 0.0:
            cmd.extend(["--threshold-verify-status", f"{float(self.fields.fact_verify_thr.value()):.2f}"])
        if float(self.fields.fact_full_thr.value()) >= 0.0:
            cmd.extend(["--threshold-full-f1", f"{float(self.fields.fact_full_thr.value()):.2f}"])
        if int(self.fields.fact_source_chars_spin.value()) > 0:
            cmd.extend(["--source-max-chars", str(int(self.fields.fact_source_chars_spin.value()))])
        if int(self.fields.fact_target_chars_spin.value()) > 0:
            cmd.extend(["--target-max-chars", str(int(self.fields.fact_target_chars_spin.value()))])
        if int(self.fields.fact_max_verify_spin.value()) > 0:
            cmd.extend(["--max-verify-facts", str(int(self.fields.fact_max_verify_spin.value()))])

        self._extend_set_overrides(cmd, self.fields.fact_set_edit.text())
        return cmd

    def build_judge_command(self) -> list[str]:
        llm_model = self.resolve_judge_model_path()
        if llm_model and not self.fields.judge_model_edit.text().strip():
            self.fields.judge_model_edit.setText(llm_model)

        cmd = [
            sys.executable,
            str((self.project_root / "eval" / "judge_eval.py").resolve()),
            "--suite",
            self.fields.judge_suite_edit.text().strip(),
            "--output-dir",
            self.fields.judge_out_edit.text().strip(),
            "--log-level",
            self.fields.judge_log_combo.currentText().strip(),
            "--judge-max-tokens",
            str(int(self.fields.judge_max_tokens_spin.value())),
            "--temperature",
            f"{float(self.fields.judge_temp_spin.value()):.2f}",
            "--top-p",
            f"{float(self.fields.judge_top_p_spin.value()):.2f}",
            "--repeat-penalty",
            f"{float(self.fields.judge_repeat_penalty_spin.value()):.2f}",
            "--seed",
            str(int(self.fields.judge_seed_spin.value())),
        ]
        self._extend_if_text(cmd, "--run-name", self.fields.judge_name_edit.text())
        self._extend_if_text(cmd, "--labels", self.fields.judge_labels_edit.text())
        if int(self.fields.judge_max_cases_spin.value()) > 0:
            cmd.extend(["--max-cases", str(int(self.fields.judge_max_cases_spin.value()))])
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self.fields.judge_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self.fields.judge_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self.fields.judge_threads_spin.value()))])

        self._extend_if_text(cmd, "--prompts-json", self.fields.judge_prompts_edit.text())
        self._extend_if_text(cmd, "--judge-prompt-key", self.fields.judge_prompt_key_edit.text())
        self._extend_if_text(cmd, "--judge-prompt-file", self.fields.judge_prompt_file_edit.text())
        if int(self.fields.judge_prompt_chars_spin.value()) > 0:
            cmd.extend(["--prompt-max-chars", str(int(self.fields.judge_prompt_chars_spin.value()))])
        if int(self.fields.judge_answer_chars_spin.value()) > 0:
            cmd.extend(["--answer-max-chars", str(int(self.fields.judge_answer_chars_spin.value()))])
        if float(self.fields.judge_threshold_spin.value()) >= 0.0:
            cmd.extend(["--threshold-accuracy", f"{float(self.fields.judge_threshold_spin.value()):.2f}"])

        self._extend_set_overrides(cmd, self.fields.judge_set_edit.text())
        artifacts_mode = str(self.fields.judge_artifacts_combo.currentData() or "default")
        if artifacts_mode == "on":
            cmd.append("--write-artifacts")
        elif artifacts_mode == "off":
            cmd.append("--no-write-artifacts")
        return cmd

    def build_llmcompare_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((self.project_root / "eval" / "llm_compare_eval.py").resolve()),
            "--suite",
            self.fields.cmp_suite_edit.text().strip(),
            "--output-dir",
            self.fields.cmp_out_edit.text().strip(),
            "--log-level",
            self.fields.cmp_log_combo.currentText().strip(),
            "--a-label",
            self.fields.cmp_a_label_edit.text().strip() or "A",
            "--a-max-tokens",
            str(int(self.fields.cmp_a_tokens_spin.value())),
            "--a-temperature",
            f"{float(self.fields.cmp_a_temp_spin.value()):.2f}",
            "--a-top-p",
            f"{float(self.fields.cmp_a_top_p_spin.value()):.2f}",
            "--a-repeat-penalty",
            f"{float(self.fields.cmp_a_repeat_spin.value()):.2f}",
            "--a-seed",
            str(int(self.fields.cmp_a_seed_spin.value())),
            "--b-label",
            self.fields.cmp_b_label_edit.text().strip() or "B",
            "--b-max-tokens",
            str(int(self.fields.cmp_b_tokens_spin.value())),
            "--b-temperature",
            f"{float(self.fields.cmp_b_temp_spin.value()):.2f}",
            "--b-top-p",
            f"{float(self.fields.cmp_b_top_p_spin.value()):.2f}",
            "--b-repeat-penalty",
            f"{float(self.fields.cmp_b_repeat_spin.value()):.2f}",
            "--b-seed",
            str(int(self.fields.cmp_b_seed_spin.value())),
            "--judge-max-tokens",
            str(int(self.fields.cmp_j_tokens_spin.value())),
            "--judge-temperature",
            f"{float(self.fields.cmp_j_temp_spin.value()):.2f}",
            "--judge-top-p",
            f"{float(self.fields.cmp_j_top_p_spin.value()):.2f}",
            "--judge-repeat-penalty",
            f"{float(self.fields.cmp_j_repeat_spin.value()):.2f}",
            "--judge-seed",
            str(int(self.fields.cmp_j_seed_spin.value())),
        ]
        self._extend_if_text(cmd, "--run-name", self.fields.cmp_name_edit.text())
        self._extend_if_text(cmd, "--labels", self.fields.cmp_labels_edit.text())
        if int(self.fields.cmp_max_cases_spin.value()) > 0:
            cmd.extend(["--max-cases", str(int(self.fields.cmp_max_cases_spin.value()))])

        self._extend_if_text(cmd, "--a-llm-model", self.fields.cmp_a_model_edit.text())
        if self.fields.cmp_a_model_edit.text().strip():
            cmd.extend(["--a-llm-n-ctx", str(int(self.fields.cmp_a_ctx_spin.value()))])
            cmd.extend(["--a-llm-gpu-layers", str(int(self.fields.cmp_a_gpu_spin.value()))])
            cmd.extend(["--a-llm-threads", str(int(self.fields.cmp_a_threads_spin.value()))])

        self._extend_if_text(cmd, "--b-llm-model", self.fields.cmp_b_model_edit.text())
        if self.fields.cmp_b_model_edit.text().strip():
            cmd.extend(["--b-llm-n-ctx", str(int(self.fields.cmp_b_ctx_spin.value()))])
            cmd.extend(["--b-llm-gpu-layers", str(int(self.fields.cmp_b_gpu_spin.value()))])
            cmd.extend(["--b-llm-threads", str(int(self.fields.cmp_b_threads_spin.value()))])

        self._extend_if_text(cmd, "--judge-llm-model", self.fields.cmp_j_model_edit.text())
        if self.fields.cmp_j_model_edit.text().strip():
            cmd.extend(["--judge-llm-n-ctx", str(int(self.fields.cmp_j_ctx_spin.value()))])
            cmd.extend(["--judge-llm-gpu-layers", str(int(self.fields.cmp_j_gpu_spin.value()))])
            cmd.extend(["--judge-llm-threads", str(int(self.fields.cmp_j_threads_spin.value()))])

        self._extend_if_text(cmd, "--prompts-json", self.fields.cmp_prompts_edit.text())
        self._extend_if_text(cmd, "--candidate-prompt-key", self.fields.cmp_candidate_prompt_key_edit.text())
        self._extend_if_text(cmd, "--candidate-prompt-file", self.fields.cmp_candidate_prompt_file_edit.text())
        self._extend_if_text(cmd, "--judge-prompt-key", self.fields.cmp_judge_prompt_key_edit.text())
        self._extend_if_text(cmd, "--judge-prompt-file", self.fields.cmp_judge_prompt_file_edit.text())
        if int(self.fields.cmp_prompt_chars_spin.value()) > 0:
            cmd.extend(["--prompt-max-chars", str(int(self.fields.cmp_prompt_chars_spin.value()))])
        if float(self.fields.cmp_threshold_gap_spin.value()) >= 0.0:
            cmd.extend(["--threshold-win-gap", f"{float(self.fields.cmp_threshold_gap_spin.value()):.2f}"])

        cmd.append("--swap-order" if str(self.fields.cmp_swap_combo.currentData() or "on") == "on" else "--no-swap-order")

        self._extend_set_overrides(cmd, self.fields.cmp_set_edit.text())
        artifacts_mode = str(self.fields.cmp_artifacts_combo.currentData() or "default")
        if artifacts_mode == "on":
            cmd.append("--write-artifacts")
        elif artifacts_mode == "off":
            cmd.append("--no-write-artifacts")
        return cmd

    @staticmethod
    def _extend_if_text(cmd: list[str], flag: str, raw_text: str) -> None:
        text = raw_text.strip()
        if text:
            cmd.extend([flag, text])

    def _extend_set_overrides(self, cmd: list[str], raw_text: str) -> None:
        for item in self.parse_overrides_csv(raw_text):
            cmd.extend(["--set", item])
