"""Business/controller layer for Testcase Studio."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from testcase_studio.storage import (
    case_id_from_no,
    now_iso,
    read_cases,
    read_events,
    reserve_case_no,
    write_cases,
    write_events,
)
from testcase_studio.text_utils import case_title, coerce_int_list, coerce_labels, safe_str


class TestcaseStudioController:
    def __init__(self, storage_dir: str | Path | None = None) -> None:
        base = Path(storage_dir).expanduser() if storage_dir else Path("runs/feedback")
        if not base.is_absolute():
            base = (Path.cwd() / base).resolve()
        self.storage_dir = base
        self.events: list[dict[str, Any]] = []
        self.cases: list[dict[str, Any]] = []

    def reload(self) -> None:
        self.events = read_events(self.storage_dir)
        self.cases = read_cases(self.storage_dir)

    def find_event(self, event_id: str) -> dict[str, Any] | None:
        for event in self.events:
            if safe_str(event.get("event_id")) == event_id:
                return event
        return None

    def find_case(self, case_no: int) -> dict[str, Any] | None:
        for case in self.cases:
            if int(case.get("case_no", 0) or 0) == int(case_no):
                return case
        return None

    def known_labels(self) -> list[str]:
        labels: list[str] = []
        for entry in self.cases:
            payload = entry.get("case")
            if isinstance(payload, dict):
                labels.extend(coerce_labels(payload.get("labels")))
        return coerce_labels(labels)

    def filtered_events(self, query: str, sentiment: str) -> list[dict[str, Any]]:
        query_norm = query.strip().casefold()
        sentiment_norm = sentiment.strip().casefold()

        visible: list[dict[str, Any]] = []
        for event in reversed(self.events):
            event_sent = safe_str(event.get("sentiment")).lower()
            if sentiment_norm != "all" and event_sent != sentiment_norm:
                continue

            if query_norm:
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                rag = payload.get("rag_search") if isinstance(payload.get("rag_search"), dict) else {}
                hay = " ".join(
                    [
                        safe_str(event.get("event_id")),
                        safe_str(event.get("use_case")),
                        safe_str(event.get("note")),
                        safe_str(payload.get("last_user_message")),
                        safe_str(rag.get("query")),
                    ]
                ).casefold()
                if query_norm not in hay:
                    continue

            visible.append(event)
        return visible

    def filtered_cases(self, query: str, suite_filter: str, status_filter: str) -> list[dict[str, Any]]:
        query_norm = query.strip().casefold()
        suite_filter = suite_filter.strip().lower()
        status_filter = status_filter.strip().lower()

        visible: list[dict[str, Any]] = []
        for entry in self.cases:
            suite_id = safe_str(entry.get("suite_type"))
            accepted = bool(entry.get("accepted", False))
            if suite_filter != "all" and suite_id != suite_filter:
                continue
            if status_filter == "accepted" and not accepted:
                continue
            if status_filter == "draft" and accepted:
                continue

            if query_norm:
                hay = " ".join(
                    [
                        safe_str(entry.get("case_id")),
                        safe_str(entry.get("source_event_id")),
                        safe_str(entry.get("title")),
                        safe_str(entry.get("suite_type")),
                    ]
                ).casefold()
                if query_norm not in hay:
                    continue

            visible.append(entry)
        return visible

    def create_case_from_feedback(
        self,
        *,
        event_id: str,
        suite_id: str,
        payload: dict[str, Any],
        accepted: bool,
    ) -> dict[str, Any]:
        case_no = reserve_case_no(self.storage_dir)
        case_id = case_id_from_no(case_no)
        payload = dict(payload)
        payload["id"] = case_id

        entry = {
            "case_no": case_no,
            "case_id": case_id,
            "suite_type": suite_id,
            "accepted": bool(accepted),
            "source_event_id": event_id,
            "source_event_ids": [event_id],
            "title": case_title(payload),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "case": payload,
        }
        self.cases.append(entry)
        write_cases(self.storage_dir, self.cases)

        self._link_event_case(event_id, case_no)
        write_events(self.storage_dir, self.events)
        return entry

    def create_manual_case(self, *, suite_id: str, payload: dict[str, Any], accepted: bool) -> dict[str, Any]:
        case_no = reserve_case_no(self.storage_dir)
        case_id = case_id_from_no(case_no)
        payload = dict(payload)
        payload["id"] = case_id

        entry = {
            "case_no": case_no,
            "case_id": case_id,
            "suite_type": suite_id,
            "accepted": bool(accepted),
            "source_event_id": "",
            "source_event_ids": [],
            "title": case_title(payload),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "case": payload,
        }
        self.cases.append(entry)
        write_cases(self.storage_dir, self.cases)
        return entry

    def update_case(
        self,
        *,
        case_no: int,
        suite_id: str,
        payload: dict[str, Any],
        accepted: bool,
    ) -> dict[str, Any] | None:
        entry = self.find_case(case_no)
        if entry is None:
            return None

        payload = dict(payload)
        payload["id"] = case_id_from_no(case_no)
        entry["suite_type"] = suite_id
        entry["accepted"] = bool(accepted)
        entry["title"] = case_title(payload)
        entry["updated_at"] = now_iso()
        entry["case"] = payload
        write_cases(self.storage_dir, self.cases)
        return entry

    def delete_case(self, case_no: int) -> bool:
        before = len(self.cases)
        self.cases = [entry for entry in self.cases if int(entry.get("case_no", 0) or 0) != case_no]
        if len(self.cases) == before:
            return False

        write_cases(self.storage_dir, self.cases)
        for event in self.events:
            linked = event.get("linked_testcases")
            if not isinstance(linked, list):
                continue
            event["linked_testcases"] = [num for num in coerce_int_list(linked) if num != case_no]
        write_events(self.storage_dir, self.events)
        return True

    def delete_feedback(self, event_id: str) -> bool:
        before = len(self.events)
        self.events = [event for event in self.events if safe_str(event.get("event_id")) != event_id]
        if len(self.events) == before:
            return False
        write_events(self.storage_dir, self.events)
        return True

    def export_suites(
        self,
        *,
        output_dir: Path,
        run_name: str,
        include_drafts: bool,
    ) -> tuple[dict[str, Any], list[str]]:
        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from eval.feedback_generate_tests import export_from_storage  # type: ignore

        summary, written = export_from_storage(
            storage_dir=self.storage_dir,
            output_dir=output_dir,
            run_name=run_name,
            include_unaccepted=include_drafts,
        )
        return summary, written

    def _link_event_case(self, event_id: str, case_no: int) -> None:
        for event in self.events:
            if safe_str(event.get("event_id")) != event_id:
                continue
            linked = coerce_int_list(event.get("linked_testcases"))
            if case_no not in linked:
                linked.append(case_no)
            event["linked_testcases"] = sorted(set(linked))
            break
