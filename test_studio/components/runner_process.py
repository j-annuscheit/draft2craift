"""Process queue execution for test pipeline runner."""
from __future__ import annotations

import pathlib
from collections.abc import Callable

from PySide6.QtCore import QProcess


class RunnerProcessQueue:
    def __init__(
        self,
        *,
        project_root: pathlib.Path,
        on_log: Callable[[str], None],
        on_all_done: Callable[[], None],
    ) -> None:
        self._project_root = project_root
        self._on_log = on_log
        self._on_all_done = on_all_done
        self._process: QProcess | None = None
        self._queue: list[tuple[str, list[str]]] = []
        self._active_name = ""

    @property
    def busy(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    def start(self, queue: list[tuple[str, list[str]]], *, clear_log: Callable[[], None] | None = None) -> None:
        if self.busy:
            self._on_log("Runner busy. Stop current process first.")
            return

        if clear_log is not None:
            clear_log()

        self._queue = list(queue)
        self._start_next()

    def stop(self) -> None:
        proc = self._process
        if proc is None:
            return
        if proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._on_log("Stopping current runner process...")
        proc.kill()
        proc.waitForFinished(2000)

    def _start_next(self) -> None:
        if not self._queue:
            self._on_log("All queued tests finished.")
            self._on_all_done()
            return

        name, cmd = self._queue.pop(0)
        self._active_name = name
        self._on_log(f"\n>>> START [{name}] {' '.join(cmd)}")

        proc = QProcess()
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.setWorkingDirectory(str(self._project_root))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        self._process = proc

        proc.start()
        if not proc.waitForStarted(3000):
            self._on_log(f"ERROR: could not start process for [{name}]")
            self._process = None
            self._start_next()

    def _on_stdout(self) -> None:
        proc = self._process
        if proc is None:
            return
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self._on_log(data.rstrip("\n"))

    def _on_stderr(self) -> None:
        proc = self._process
        if proc is None:
            return
        data = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace")
        if data:
            self._on_log(data.rstrip("\n"))

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._on_log(f"<<< DONE [{self._active_name}] exit={exit_code}")
        self._process = None
        self._active_name = ""
        self._on_all_done()
        self._start_next()
