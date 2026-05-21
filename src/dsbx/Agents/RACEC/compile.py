from __future__ import annotations

import ast
import builtins
import importlib.util
import math
import sysconfig
from typing import Any, Callable, Dict


def _safe_float(x: Any, default: float = 0.0) -> float:
    if x is None:
        try:
            return float(default) if default is not None else 0.0
        except Exception:
            return 0.0
    try:
        return float(x)
    except Exception:
        try:
            return float(default) if default is not None else 0.0
        except Exception:
            return 0.0


def _find_ready_op(
    obs: Dict[str, Any],
    job_id: str,
    machine_group: str,
    allow_fallback_any_group: bool = False,
) -> Any:
    ready_ops = obs.get("ready_ops", []) or []
    ready_op = None
    for ro in ready_ops:
        if str(ro.get("job_id")) != str(job_id):
            continue
        if not machine_group or str(ro.get("machine_group")) == str(machine_group):
            return ro
        if allow_fallback_any_group and ready_op is None:
            ready_op = ro
    return ready_op


def _validate_rule_code(code: str, *, base_allowed_names: set[str]) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        raise

    module_defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            module_defined.add(node.name)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if str(alias.name) != "math":
                    raise ValueError("only 'import math' is allowed")
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level not in (0, None):
                raise ValueError("relative imports are not allowed")
            if str(node.module or "") != "math":
                raise ValueError("only imports from 'math' are allowed")
            continue
        raise ValueError("only function definitions and 'import math' are allowed at module level")

    defined: set[str] = set(base_allowed_names) | set(module_defined)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            if isinstance(node.name, str):
                defined.add(node.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in defined:
                raise ValueError(f"name '{node.id}' is not allowed")


def compile_optimized_priority(code: str) -> Callable[[Dict[str, Any], Dict[str, Any], Any], float]:
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")

    def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        mod = str(name or "")
        root = mod.split(".")[0]
        deny_prefixes = {
            "os",
            "sys",
            "subprocess",
            "socket",
            "pathlib",
            "io",
            "tempfile",
            "shutil",
            "glob",
            "zipfile",
            "tarfile",
            "gzip",
            "bz2",
            "lzma",
            "importlib",
            "builtins",
            "inspect",
            "ctypes",
            "multiprocessing",
            "threading",
            "asyncio",
            "signal",
            "selectors",
            "ssl",
            "http",
            "urllib",
            "ftplib",
            "telnetlib",
            "webbrowser",
            "random",
            "pickle",
        }
        if root in deny_prefixes:
            raise ImportError(f"import of '{mod}' is not allowed")

        spec = None
        try:
            spec = importlib.util.find_spec(mod)
        except Exception:
            spec = None
        if spec is None:
            raise ImportError(f"import of '{mod}' is not allowed")

        origin = getattr(spec, "origin", None)
        if origin is None:
            raise ImportError(f"import of '{mod}' is not allowed")
        if origin == "built-in":
            return builtins.__import__(mod, globals, locals, fromlist, level)
        if origin == "frozen":
            return builtins.__import__(mod, globals, locals, fromlist, level)

        try:
            stdlib = sysconfig.get_paths().get("stdlib")
        except Exception:
            stdlib = None
        if not isinstance(stdlib, str) or not stdlib:
            raise ImportError(f"import of '{mod}' is not allowed")
        stdlib_norm = stdlib.rstrip("/") + "/"
        origin_norm = str(origin).replace("\\", "/")
        if not origin_norm.startswith(stdlib_norm):
            raise ImportError(f"import of '{mod}' is not allowed")

        return builtins.__import__(mod, globals, locals, fromlist, level)

    safe_builtins = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "len": len,
        "ord": ord,
        "chr": chr,
        "float": float,
        "int": int,
        "str": str,
        "range": range,
        "enumerate": enumerate,
        "sorted": sorted,
        "zip": zip,
        "isinstance": isinstance,
        "set": set,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "all": all,
        "any": any,
        "bool": bool,
        "round": round,
        "getattr": getattr,
        "hasattr": hasattr,
        "Exception": Exception,
        "__import__": _restricted_import,
    }

    global_ns: Dict[str, Any] = {
        "__builtins__": safe_builtins,
        "math": math,
        "_safe_float": _safe_float,
        "_find_ready_op": _find_ready_op,
    }

    _validate_rule_code(code, base_allowed_names=set(safe_builtins.keys()) | set(global_ns.keys()))
    exec(code, global_ns, global_ns)

    fn = global_ns.get("optimized_priority")
    if not callable(fn):
        raise ValueError("optimized_priority function not found after exec")

    return fn
