"""Coordinator for runner dialog, command building, and process execution."""
from __future__ import annotations

import pathlib

from test_studio.components.runner_commands import RunnerCommandBuilder
from test_studio.components.runner_fields import RunnerFields
from test_studio.components.runner_process import RunnerProcessQueue
from test_studio.view.runner_dialog import RunnerDialog


class RunnerController:
    def __init__(
        self,
        *,
        project_root: pathlib.Path,
        style_sheet: str,
        on_runs_changed,
    ) -> None:
        self._project_root = project_root
        self._on_runs_changed = on_runs_changed

        self.fields = RunnerFields(project_root)
        self.dialog = RunnerDialog(
            fields=self.fields,
            style_sheet=style_sheet,
            callbacks={
                "run_all": self.run_all_tests,
                "stop": self.stop,
                "run_feedback": self.run_feedback_export,
                "apply_feedback_paths": self.apply_feedback_suite_paths,
                "run_rag": self.run_rag,
                "run_pdf": self.run_pdf,
                "run_glossary": self.run_glossary,
                "run_factcheck": self.run_factcheck,
                "run_judge": self.run_judge,
                "run_llmcompare": self.run_llmcompare,
            },
        )

        self.builder = RunnerCommandBuilder(
            fields=self.fields,
            project_root=project_root,
            log=self.append_log,
        )
        self.process = RunnerProcessQueue(
            project_root=project_root,
            on_log=self.append_log,
            on_all_done=on_runs_changed,
        )

    def open_dialog(self) -> None:
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_and_run_all(self) -> None:
        self.open_dialog()
        self.run_all_tests()

    def append_log(self, text: str) -> None:
        self.dialog.append_log(text)

    def stop(self) -> None:
        self.process.stop()

    def apply_feedback_suite_paths(self) -> None:
        run_name = self.builder.feedback_run_name()
        out_dir = self.fields.fb_out_edit.text().strip()
        self.builder.apply_feedback_suite_paths(run_name, out_dir)

    def run_feedback_export(self) -> None:
        run_name = self.builder.feedback_run_name()
        self.builder.apply_feedback_suite_paths(run_name, self.fields.fb_out_edit.text().strip())
        self._start_queue(
            [("Feedback->Suites", self.builder.build_feedback_export_command(run_name=run_name))],
            clear_log=False,
        )

    def run_rag(self) -> None:
        self._start_queue([("RAG", self.builder.build_rag_command())], clear_log=False)

    def run_pdf(self) -> None:
        self._start_queue([("PDF", self.builder.build_pdf_command())], clear_log=False)

    def run_glossary(self) -> None:
        cmd = self.builder.build_glossary_command()
        if "--llm-model" not in cmd:
            self.append_log("ERROR: Glossary test requires --llm-model")
            return
        self._start_queue([("Glossary", cmd)], clear_log=False)

    def run_factcheck(self) -> None:
        cmd = self.builder.build_factcheck_command()
        if "--llm-model" not in cmd:
            self.append_log("ERROR: Fact-Check test requires --llm-model")
            return
        self._start_queue([("Fact-Check", cmd)], clear_log=False)

    def run_judge(self) -> None:
        cmd = self.builder.build_judge_command()
        if "--llm-model" not in cmd:
            self.append_log("ERROR: Judge test requires --llm-model")
            return
        self._start_queue([("Judge", cmd)], clear_log=False)

    def run_llmcompare(self) -> None:
        cmd = self.builder.build_llmcompare_command()
        required = ("--a-llm-model", "--b-llm-model", "--judge-llm-model")
        if not all(flag in cmd for flag in required):
            self.append_log(f"ERROR: LLM-Compare test requires {', '.join(required)}")
            return
        self._start_queue([("LLM-Compare", cmd)], clear_log=False)

    def run_all_tests(self) -> None:
        run_name = self.builder.feedback_run_name()
        out_dir = self.fields.fb_out_edit.text().strip()
        self.builder.apply_feedback_suite_paths(run_name, out_dir)
        counts = self.builder.feedback_case_counts()

        queue: list[tuple[str, list[str]]] = [
            ("Feedback->Suites", self.builder.build_feedback_export_command(run_name=run_name)),
        ]

        if counts.get("rag", 0) > 0:
            queue.append(("RAG", self.builder.build_rag_command()))
        else:
            self.append_log("INFO: RAG skipped in Run All-Tests (no testcase entries)")

        if counts.get("pdf", 0) > 0:
            queue.append(("PDF", self.builder.build_pdf_command()))
        else:
            self.append_log("INFO: PDF skipped in Run All-Tests (no testcase entries)")

        gloss_cmd = self.builder.build_glossary_command()
        if counts.get("glossary", 0) <= 0:
            self.append_log("INFO: Glossary skipped in Run All-Tests (no testcase entries)")
        elif "--llm-model" in gloss_cmd:
            queue.append(("Glossary", gloss_cmd))
        else:
            self.append_log("INFO: Glossary skipped in Run All-Tests (LLM model missing)")

        fact_cmd = self.builder.build_factcheck_command()
        if counts.get("factcheck", 0) <= 0:
            self.append_log("INFO: Fact-Check skipped in Run All-Tests (no testcase entries)")
        elif "--llm-model" in fact_cmd:
            queue.append(("Fact-Check", fact_cmd))
        else:
            self.append_log("INFO: Fact-Check skipped in Run All-Tests (LLM model missing)")

        judge_cmd = self.builder.build_judge_command()
        if counts.get("judge", 0) <= 0:
            self.append_log("INFO: Judge skipped in Run All-Tests (no testcase entries)")
        elif "--llm-model" in judge_cmd:
            queue.append(("Judge", judge_cmd))
        else:
            self.append_log("INFO: Judge skipped in Run All-Tests (LLM model missing)")

        cmp_cmd = self.builder.build_llmcompare_command()
        required = ("--a-llm-model", "--b-llm-model", "--judge-llm-model")
        if counts.get("llmcompare", 0) <= 0:
            self.append_log("INFO: LLM-Compare skipped in Run All-Tests (no testcase entries)")
        elif all(flag in cmp_cmd for flag in required):
            queue.append(("LLM-Compare", cmp_cmd))
        else:
            self.append_log("INFO: LLM-Compare skipped in Run All-Tests (A/B/Judge model missing)")

        self._start_queue(queue, clear_log=True)

    def _start_queue(self, queue: list[tuple[str, list[str]]], *, clear_log: bool) -> None:
        self.process.start(queue, clear_log=self.dialog.clear_log if clear_log else None)
