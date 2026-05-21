from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from dsbx.Eval import Trajectory
from dsbx.Eval.InstanceChecks import load_events_jsonl
from dsbx.Sim.Events import Event


def _event_to_debug_dict(ev: Event) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "time": float(getattr(ev, "time", 0.0)),
        "type": getattr(ev, "event_type", ""),
    }
    job_id = getattr(ev, "job_id", None)
    if job_id is not None:
        rec["job_id"] = job_id
    machine_id = getattr(ev, "machine_id", None)
    if machine_id is not None:
        rec["machine_id"] = machine_id
    return rec


def _load_env_trajectory(trajectory_path: Path) -> Trajectory:
    if trajectory_path.suffix.lower() == ".jsonl":
        return Trajectory.load_from_disk(trajectory_path)
    raw = trajectory_path.read_text(encoding="utf-8")
    return Trajectory.model_validate_json(raw)


def _load_llmcoder_events(coder_trajectory_path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not coder_trajectory_path.exists():
        logger.warning("LLMCoderDebug: coder trajectory file does not exist: {}", coder_trajectory_path)
        return records
    with coder_trajectory_path.open("r", encoding="utf-8") as f:
        first = f.readline()
        try:
            header = json.loads(first) if first.strip() else None
        except Exception:
            header = None
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                records.append(obj)
    return records


def build_llmcoder_debug(
    *,
    trajectory_path: Path,
    events_path: Path,
    static_jobs_path: Optional[Path] = None,
    static_machines_path: Optional[Path] = None,
    coder_trajectory_path: Path,
    log_path: Path,
    output_path: Path,
) -> None:
    """Build a consolidated debug JSON for an LLMCoder episode.

    This is a first version focusing on wiring together env trajectory,
    events, and LLMCoder internal trajectory. Log file is currently
    only recorded in meta for future use.
    """

    traj = _load_env_trajectory(trajectory_path)

    typed_events: List[Event] = load_events_jsonl(events_path)
    event_records: List[Dict[str, Any]] = [_event_to_debug_dict(ev) for ev in typed_events]
    event_records.sort(key=lambda r: float(r.get("time", 0.0)))

    static_jobs_str = str(static_jobs_path) if static_jobs_path is not None else None
    static_machines_str = str(static_machines_path) if static_machines_path is not None else None

    llmcoder_events = _load_llmcoder_events(coder_trajectory_path)

    meta: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "llmcoder_debug_v1",
        "inputs": {
            "trajectory": str(trajectory_path),
            "events": str(events_path),
            "static_jobs": static_jobs_str,
            "static_machines": static_machines_str,
            "coder_trajectory": str(coder_trajectory_path),
            "log": str(log_path),
        },
    }

    payload: Dict[str, Any] = {
        "meta": meta,
        "env_trajectory_summary": {
            "mode": getattr(traj, "_mode", "full"),
        },
        "events": event_records,
        "llmcoder_events": llmcoder_events,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info(
        "LLMCoderDebug: wrote {} LLMCoder events to {}",
        len(llmcoder_events),
        output_path,
    )
