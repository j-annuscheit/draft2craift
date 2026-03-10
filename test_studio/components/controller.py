"""Business logic for Test Studio dashboard state and filtering."""
from __future__ import annotations

import pathlib
import re
import statistics
from dataclasses import dataclass
from typing import Callable

from test_studio.components.data_loader import discover_runs
from test_studio.components.metrics import failure_rate
from test_studio.models import CaseEntry, RunEntry

_CASE_NO_RE = re.compile(r"^case[_:-]?(\d+)$", re.IGNORECASE)
_VALID_TYPES = {"rag", "pdf", "glossary", "factcheck", "judge", "llmcompare"}


@dataclass
class TypeCounts:
    rag: int
    pdf: int
    glossary: int
    factcheck: int
    judge: int
    llmcompare: int


class TestStudioController:
    def __init__(
        self,
        loader: Callable[[pathlib.Path], list[RunEntry]] = discover_runs,
    ) -> None:
        self._loader = loader
        self.all_runs: list[RunEntry] = []
        self.visible_runs: list[RunEntry] = []
        self.runs_by_path: dict[str, RunEntry] = {}

    def reload_runs(self, root_dir: pathlib.Path) -> list[RunEntry]:
        self.all_runs = self._loader(root_dir)
        self.runs_by_path = {str(run.path): run for run in self.all_runs}
        return self.all_runs

    def apply_filter(self, query: str, type_filter: str) -> list[RunEntry]:
        query_norm = query.strip().casefold()
        type_norm = type_filter.strip().casefold()

        if not query_norm:
            visible = list(self.all_runs)
        else:
            visible = [
                run
                for run in self.all_runs
                if (
                    query_norm in run.run_name.casefold()
                    or query_norm in run.suite.casefold()
                    or query_norm in str(run.path).casefold()
                    or query_norm in run.run_type.casefold()
                )
            ]

        if type_norm in _VALID_TYPES:
            visible = [run for run in visible if run.run_type == type_norm]

        self.visible_runs = visible
        return visible

    def selected_runs_from_paths(self, selected_paths: list[str]) -> list[RunEntry]:
        runs: list[RunEntry] = []
        seen: set[str] = set()
        for path in selected_paths:
            if not path or path in seen:
                continue
            run = self.runs_by_path.get(path)
            if run is None:
                continue
            seen.add(path)
            runs.append(run)

        runs.sort(key=lambda item: (item.timestamp, item.run_name), reverse=True)
        return runs

    def runs_for_scope(self, selected_runs: list[RunEntry], use_common_cases: bool) -> list[RunEntry]:
        base = selected_runs if selected_runs else self.visible_runs
        if not use_common_cases or len(base) < 2:
            return base
        return self._filter_runs_common_cases(base)

    @staticmethod
    def runs_mode(runs: list[RunEntry]) -> str:
        kinds = {run.run_type for run in runs}
        if not kinds:
            return "mixed"
        if len(kinds) == 1:
            return next(iter(kinds))
        return "mixed"

    @staticmethod
    def requested_type_mode(type_filter: str) -> str:
        mode = type_filter.strip().casefold()
        if mode in _VALID_TYPES:
            return mode
        return "mixed"

    @staticmethod
    def _case_no(case: CaseEntry) -> int | None:
        case_id = str(case.case_id or "").strip()
        if case_id:
            match = _CASE_NO_RE.match(case_id)
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    return None

        for label in case.labels:
            text = str(label or "").strip()
            if not text.casefold().startswith("case_no:"):
                continue
            raw = text.split(":", 1)[1].strip()
            try:
                return int(raw)
            except Exception:
                continue
        return None

    def _common_case_numbers(self, runs: list[RunEntry]) -> set[int]:
        if len(runs) < 2:
            return set()

        sets: list[set[int]] = []
        for run in runs:
            numbers = {n for n in (self._case_no(case) for case in run.cases) if n is not None}
            if not numbers:
                return set()
            sets.append(numbers)

        return set.intersection(*sets) if sets else set()

    @staticmethod
    def _rebuild_run_for_cases(run: RunEntry, cases: list[CaseEntry]) -> RunEntry:
        if not cases:
            return RunEntry(
                run_type=run.run_type,
                run_name=run.run_name,
                timestamp=run.timestamp,
                suite=run.suite,
                path=run.path,
                cases_count=0,
                micro_f1=0.0,
                macro_f1=0.0,
                hit_at_k=0.0,
                map_value=0.0,
                mrr=0.0,
                ndcg=0.0,
                failure_cases=0,
                cases=[],
            )

        failures = sum(1 for case in cases if case.failed)
        macro_f1 = statistics.fmean(case.f1 for case in cases)
        hit_at_k = statistics.fmean(case.hit_at_k for case in cases)
        precision = statistics.fmean(case.precision for case in cases)
        recall = statistics.fmean(case.recall for case in cases)
        pass_rate = statistics.fmean(0.0 if case.failed else 1.0 for case in cases)

        return RunEntry(
            run_type=run.run_type,
            run_name=run.run_name,
            timestamp=run.timestamp,
            suite=run.suite,
            path=run.path,
            cases_count=len(cases),
            micro_f1=macro_f1,
            macro_f1=macro_f1,
            hit_at_k=hit_at_k,
            map_value=precision,
            mrr=recall,
            ndcg=pass_rate,
            failure_cases=failures,
            cases=cases,
        )

    def _filter_runs_common_cases(self, runs: list[RunEntry]) -> list[RunEntry]:
        common = self._common_case_numbers(runs)
        if not common:
            return []

        filtered_runs: list[RunEntry] = []
        for run in runs:
            filtered_cases = [case for case in run.cases if self._case_no(case) in common]
            filtered_runs.append(self._rebuild_run_for_cases(run, filtered_cases))
        return filtered_runs

    @staticmethod
    def counts_by_type(runs: list[RunEntry]) -> TypeCounts:
        return TypeCounts(
            rag=sum(1 for run in runs if run.run_type == "rag"),
            pdf=sum(1 for run in runs if run.run_type == "pdf"),
            glossary=sum(1 for run in runs if run.run_type == "glossary"),
            factcheck=sum(1 for run in runs if run.run_type == "factcheck"),
            judge=sum(1 for run in runs if run.run_type == "judge"),
            llmcompare=sum(1 for run in runs if run.run_type == "llmcompare"),
        )

    def status_text(
        self,
        *,
        selected_runs: list[RunEntry],
        runs_scope: list[RunEntry],
        requested_type_filter: str,
        use_common_cases: bool,
    ) -> str:
        counts = self.counts_by_type(self.visible_runs)
        common_info = ""
        if use_common_cases:
            base = selected_runs if selected_runs else self.visible_runs
            common_info = f" | CommonCaseNo: {len(self._common_case_numbers(base))}"

        return (
            f"Loaded: {len(self.all_runs)} | Visible: {len(self.visible_runs)} | "
            f"Selected: {len(selected_runs)} | Scope runs: {len(runs_scope)} | "
            f"RAG: {counts.rag} | PDF: {counts.pdf} | Glossary: {counts.glossary} | "
            f"Fact-Check: {counts.factcheck} | Judge: {counts.judge} | "
            f"LLM-Compare: {counts.llmcompare} | "
            f"Type filter: {requested_type_filter.upper()}{common_info}"
        )

    @staticmethod
    def cards_text(
        all_runs: list[RunEntry],
        visible_runs: list[RunEntry],
        selected_runs: list[RunEntry],
        runs_scope: list[RunEntry],
    ) -> dict[str, tuple[str, str]]:
        cards: dict[str, tuple[str, str]] = {
            "loaded": (str(len(all_runs)), "all discovered"),
            "visible": (str(len(visible_runs)), "after run filter"),
            "selected": (str(len(selected_runs)), "manual selection"),
            "macro": ("—", ""),
            "hit": ("—", ""),
            "fail": ("—", ""),
        }

        if runs_scope:
            mean_macro = statistics.fmean(run.macro_f1 for run in runs_scope)
            mean_hit = statistics.fmean(run.hit_at_k for run in runs_scope)
            mean_fail = statistics.fmean(failure_rate(run) for run in runs_scope)
            cards["macro"] = (f"{mean_macro:.3f}", "across scope")
            cards["hit"] = (f"{mean_hit:.3f}", "across scope")
            cards["fail"] = (f"{mean_fail:.1%}", "across scope")

        return cards
