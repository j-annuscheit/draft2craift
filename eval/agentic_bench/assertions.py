"""Assertion evaluation for agentic benchmark cases."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import AssertionSpec


@dataclass(slots=True)
class AssertionResult:
    path: str
    op: str
    expected: Any
    actual: Any
    passed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "op": self.op,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "message": self.message,
        }


def evaluate_assertions(payload: dict[str, Any], assertions: list[AssertionSpec]) -> list[AssertionResult]:
    out: list[AssertionResult] = []
    for item in list(assertions or []):
        actual = _extract_path(payload, item.path)
        passed, message = _eval_op(op=item.op, actual=actual, expected=item.value)
        out.append(
            AssertionResult(
                path=item.path,
                op=item.op,
                expected=item.value,
                actual=actual,
                passed=passed,
                message=message,
            )
        )
    return out


def _eval_op(*, op: str, actual: Any, expected: Any) -> tuple[bool, str]:
    name = str(op or "").strip().casefold()
    if name == "exists":
        ok = actual is not None
        return ok, "exists" if ok else "missing"
    if name == "equals":
        ok = actual == expected
        return ok, "equals" if ok else f"expected={expected!r} got={actual!r}"
    if name == "not_equals":
        ok = actual != expected
        return ok, "not_equals" if ok else f"value unexpectedly equals {expected!r}"
    if name == "contains":
        if isinstance(actual, str):
            ok = str(expected or "") in actual
            return ok, "contains" if ok else f"substring {expected!r} not found"
        if isinstance(actual, list):
            ok = expected in actual
            return ok, "contains" if ok else f"item {expected!r} not found"
        return False, f"contains unsupported actual type: {type(actual).__name__}"
    if name in {"len_gte", "len_lte"}:
        size = len(actual) if isinstance(actual, (list, dict, str, tuple, set)) else -1
        try:
            target = int(expected)
        except Exception:
            return False, f"invalid len target: {expected!r}"
        ok = (size >= target) if name == "len_gte" else (size <= target)
        relation = ">=" if name == "len_gte" else "<="
        return ok, f"len={size} {relation} {target}"
    if name in {"gte", "lte"}:
        try:
            lhs = float(actual)
            rhs = float(expected)
        except Exception:
            return False, f"numeric compare failed: actual={actual!r} expected={expected!r}"
        ok = lhs >= rhs if name == "gte" else lhs <= rhs
        relation = ">=" if name == "gte" else "<="
        return ok, f"{lhs} {relation} {rhs}"
    return False, f"unknown op: {op}"


def _extract_path(root: Any, path: str) -> Any:
    parts = [part for part in str(path or "").split(".") if part]
    return _walk(root, parts)


def _walk(cur: Any, parts: list[str]) -> Any:
    if not parts:
        return cur
    head = parts[0]
    tail = parts[1:]

    if head.endswith("[*]"):
        key = head[:-3]
        base = _get_child(cur, key)
        if not isinstance(base, list):
            return []
        return [_walk(item, tail) for item in base]

    if "[" in head and head.endswith("]"):
        key, idx_raw = head[:-1].split("[", 1)
        base = _get_child(cur, key)
        if not isinstance(base, list):
            return None
        try:
            idx = int(idx_raw)
        except Exception:
            return None
        if idx < 0 or idx >= len(base):
            return None
        return _walk(base[idx], tail)

    nxt = _get_child(cur, head)
    return _walk(nxt, tail)


def _get_child(cur: Any, key: str) -> Any:
    if isinstance(cur, dict):
        return cur.get(key)
    if isinstance(cur, list):
        try:
            idx = int(key)
        except Exception:
            return None
        if idx < 0 or idx >= len(cur):
            return None
        return cur[idx]
    return None
