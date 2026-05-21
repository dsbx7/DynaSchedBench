from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import resource  # type: ignore
except Exception:  # pragma: no cover
    resource = None

from dsbx.Sim.Loader import load_instance_from_events

from .compile import compile_optimized_priority
from . import sandbox_eval


def _apply_resource_limits(payload: Dict[str, Any]) -> None:
    if resource is None:
        return
    cpu_seconds = payload.get("rlimit_cpu_seconds")
    if isinstance(cpu_seconds, (int, float)):
        try:
            cpu = int(math.ceil(float(cpu_seconds)))
            if cpu > 0:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        except Exception:
            pass

    as_bytes = payload.get("rlimit_as_bytes")
    if isinstance(as_bytes, (int, float)):
        try:
            b = int(float(as_bytes))
            if b > 0:
                resource.setrlimit(resource.RLIMIT_AS, (b, b))
        except Exception:
            pass

    nofile = payload.get("rlimit_nofile")
    if isinstance(nofile, (int, float)):
        try:
            n = int(float(nofile))
            if n > 0:
                resource.setrlimit(resource.RLIMIT_NOFILE, (n, n))
        except Exception:
            pass


def _run(payload: Dict[str, Any]) -> Dict[str, Any]:
    events_file = payload.get("events_file")
    if not isinstance(events_file, str) or not events_file:
        return {"ok": False, "error": "missing events_file"}
    code = payload.get("candidate_code")
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "error": "missing candidate_code"}

    max_steps = int(payload.get("max_steps", 1) or 1)
    if max_steps <= 0:
        max_steps = 1
    episode = int(payload.get("episode", 0) or 0)
    seed = int(payload.get("seed", 0) or 0)

    _apply_resource_limits(payload)

    model, events = load_instance_from_events(Path(events_file))
    fn = compile_optimized_priority(code)

    def _rule(obs: Dict[str, Any], action: Dict[str, Any], env: Any) -> float:
        return float(fn(obs, action, env))

    metrics = sandbox_eval._run_single_rollout(
        model,
        events,
        _rule,
        max_steps,
        episode=episode,
        seed=seed,
        rollout_label="candidate_subprocess",
        rule_name=str(payload.get("rule_name") or "candidate"),
        instance_dir=Path(events_file).parent,
    )
    return {"ok": True, "metrics": metrics}


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        out = _run(payload)
    except Exception as exc:
        out = {"ok": False, "error": repr(exc)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
