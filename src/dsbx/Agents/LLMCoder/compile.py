from __future__ import annotations

import builtins
import importlib.util
import math
import sysconfig
from typing import Any, Callable, Dict


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

    global_ns: Dict[str, Any] = {"__builtins__": safe_builtins, "math": math}
    local_ns: Dict[str, Any] = {}
    exec(code, global_ns, local_ns)

    fn = local_ns.get("optimized_priority") or global_ns.get("optimized_priority")
    if not callable(fn):
        raise ValueError("optimized_priority function not found after exec")

    return fn
