from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _decorator_path(decorator: ast.AST) -> str:
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    if isinstance(decorator, ast.Attribute):
        parts = [decorator.attr]
        value = decorator.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    if isinstance(decorator, ast.Name):
        return decorator.id
    return ""


def _route_path(decorator: ast.AST) -> str:
    if not isinstance(decorator, ast.Call):
        return ""
    if not decorator.args:
        return ""
    first = decorator.args[0]
    return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else ""


def _uses_current_admin(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for arg in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]:
        default = None
        positional = [*fn.args.posonlyargs, *fn.args.args]
        if arg in positional:
            default_index = positional.index(arg) - (len(positional) - len(fn.args.defaults))
            if default_index >= 0:
                default = fn.args.defaults[default_index]
        else:
            idx = fn.args.kwonlyargs.index(arg)
            default = fn.args.kw_defaults[idx]
        if isinstance(default, ast.Call) and getattr(default.func, "id", "") == "Depends":
            if default.args and getattr(default.args[0], "id", "") == "current_admin":
                return True
    return False


def main() -> None:
    tree = ast.parse((PROJECT_ROOT / "app" / "server.py").read_text(encoding="utf-8"))
    unprotected: list[str] = []
    admin_routes = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not _decorator_path(decorator).startswith("app."):
                continue
            path = _route_path(decorator)
            if not path.startswith("/api/admin/"):
                continue
            admin_routes += 1
            if not _uses_current_admin(node):
                unprotected.append(f"{path} -> {node.name}")
    if unprotected:
        raise AssertionError("Unprotected admin routes:\n" + "\n".join(unprotected))
    assert admin_routes > 0
    print(f"Admin protection verification passed ({admin_routes} routes)")


if __name__ == "__main__":
    main()
