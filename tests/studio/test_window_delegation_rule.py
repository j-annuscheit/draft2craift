from __future__ import annotations

import ast
from pathlib import Path


def test_window_methods_are_single_statement_outside_setup_and_close_event():
    source = Path("studio/window.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    main_window = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
    )

    violations: list[str] = []
    for node in main_window.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_init_") or node.name == "closeEvent":
            continue
        statements = [
            stmt
            for stmt in node.body
            if not (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            )
        ]
        if len(statements) > 1:
            violations.append(f"{node.name} (line {node.lineno}) has {len(statements)} statements")

    assert not violations, "Window delegation rule violated:\n" + "\n".join(violations)
