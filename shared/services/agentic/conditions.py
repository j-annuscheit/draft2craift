"""Safe-ish condition evaluation for workflow edges."""
from __future__ import annotations

import ast
from typing import Any


_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Subscript,
    ast.Constant,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)


class _DotAccess(dict):
    def __getattr__(self, name: str) -> Any:
        value = self.get(name)
        if isinstance(value, dict):
            return _DotAccess(value)
        if isinstance(value, list):
            return [(_DotAccess(v) if isinstance(v, dict) else v) for v in value]
        return value


def _validate_tree(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"Unsupported expression node: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("Dunder names are not allowed.")


def eval_condition(
    expr: str,
    *,
    request: dict[str, Any],
    state: dict[str, Any],
    policy: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    text = str(expr or "").strip()
    if not text:
        return True
    text = text.replace(" true", " True").replace(" false", " False")
    text = text.replace(" null", " None")
    tree = ast.parse(text, mode="eval")
    _validate_tree(tree)
    namespace = {
        "request": _DotAccess(request),
        "state": _DotAccess(state),
        "policy": _DotAccess(policy),
        "result": _DotAccess(result),
        "True": True,
        "False": False,
        "None": None,
    }
    value = eval(compile(tree, "<condition>", "eval"), {"__builtins__": {}}, namespace)
    return bool(value)

