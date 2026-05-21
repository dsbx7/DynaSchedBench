from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import ast

from loguru import logger

from dsbx.Eval import Trajectory
from dsbx.Eval.InstanceChecks import load_events_jsonl
from dsbx.Sim.Snapshot import Snapshot, JobSnapshot, MachineSnapshot
from dsbx.Sim.Events import Event


def _parse_llm_responses_text(text: str) -> Optional[List[Any]]:
    """Best-effort parse of LLM raw_responses text from logs.

    Expected format is a Python list literal whose elements are JSON strings.
    Returns a list where JSON strings are decoded into dicts when possible.
    """

    text = text.strip()
    if not text:
        return []
    try:
        obj = ast.literal_eval(text)
    except Exception:
        return None
    if not isinstance(obj, list):
        return None

    out: List[Any] = []
    for item in obj:
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
            except Exception:
                out.append(item)
            else:
                out.append(parsed)
        else:
            out.append(item)
    return out


def _event_to_debug_dict(ev: Event) -> Dict[str, Any]:
    """Convert a typed Event model into a compact, JSON-serializable dict.

    This keeps only the most relevant fields for debugging.
    """

    rec: Dict[str, Any] = {
        "time": float(getattr(ev, "time", 0.0)),
        "type": getattr(ev, "event_type", ""),
    }

    # Common optional fields
    job_id = getattr(ev, "job_id", None)
    if job_id is not None:
        rec["job_id"] = job_id
    machine_id = getattr(ev, "machine_id", None)
    if machine_id is not None:
        rec["machine_id"] = machine_id

    etype = rec["type"]

    try:
        if etype == "ARRIVAL":
            rec["job_family"] = getattr(ev, "job_family", None)
            rec["routing"] = list(getattr(ev, "routing", []) or [])
            rec["process_times"] = list(getattr(ev, "process_times", []) or [])
        elif etype == "DUE_DATE_SET":
            rec["due_date"] = float(getattr(ev, "due_date", 0.0))
        elif etype == "PRIORITY_CHANGE":
            rec["new_priority"] = float(getattr(ev, "new_priority", 0.0))
        elif etype == "ORDER_CANCELLATION":
            # job_id already captured above
            pass
        elif etype == "PTIME_CHANGE":
            rec["step_index"] = int(getattr(ev, "step_index", 0))
            rec["new_process_time"] = float(getattr(ev, "new_process_time", 0.0))
        elif etype == "ROUTE_CHANGE":
            rec["new_routing"] = list(getattr(ev, "new_routing", []) or [])
            rec["new_process_times"] = list(getattr(ev, "new_process_times", []) or [])
            rec["from_step"] = int(getattr(ev, "from_step", 0))
        elif etype == "DUE_DATE_CHANGE":
            rec["new_due_date"] = float(getattr(ev, "new_due_date", 0.0))
            rec["reason"] = getattr(ev, "reason", None)
        elif etype == "BREAKDOWN":
            rec["duration"] = float(getattr(ev, "duration", 0.0))
        elif etype == "PREVENTIVE_MAINTENANCE":
            rec["duration"] = float(getattr(ev, "duration", 0.0))
            rec["maintenance_type"] = getattr(ev, "maintenance_type", None)
        elif etype == "REPAIR_COMPLETION":
            # machine_id already captured above
            pass
    except Exception:
        # Best-effort: if some cast fails, we simply skip that extra field.
        logger.debug("EpisodeDebug: failed to convert extra fields for event {}", ev)

    return rec


def _parse_llm_debug_from_log(log_path: Path) -> Dict[int, Dict[str, Any]]:
    """Parse LLM-related debug information from a loguru log file.

    The parser is best-effort and looks for the structured messages emitted
    in LLMPolicy._log_decision, keyed by step index.
    """

    info_by_step: Dict[int, Dict[str, Any]] = {}

    if not log_path.exists():
        logger.warning("EpisodeDebug: log file does not exist: {}", log_path)
        return info_by_step

    def _get_step_dict(step: int) -> Dict[str, Any]:
        if step not in info_by_step:
            info_by_step[step] = {}
        return info_by_step[step]


    def _is_log_header(s: str) -> bool:
        if len(s) < 23:
            return False
        return s[0:4].isdigit() and s[4] == "-" and s[7] == "-" and s[10] == " "

    current_block: Optional[Dict[str, Any]] = None

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            if current_block is not None and _is_log_header(line):
                step_val = current_block["step"]
                kind = current_block["kind"]
                buf = current_block["buf"]
                d = _get_step_dict(step_val)
                text = "\n".join(buf)
                if kind == "full_prompt":
                    d["full_prompt"] = text
                elif kind == "full_raw_responses":
                    parsed = _parse_llm_responses_text(text)
                    if parsed is not None:
                        d["llm_outputs"] = parsed
                    else:
                        d["llm_outputs_raw"] = text
                current_block = None

            if "LLMPolicy debug: step=" in line:
                try:
                    payload = line.split("LLMPolicy debug: ", 1)[1].strip()
                except Exception:
                    continue

                # e.g. "step=12 prompt_snippet=..." or "step=12 raw_responses_preview=..."
                parts = payload.split(" ", 1)
                if not parts or not parts[0].startswith("step="):
                    continue
                try:
                    step_val = int(parts[0].split("=", 1)[1])
                except Exception:
                    continue
                rest = parts[1] if len(parts) > 1 else ""

                if rest.startswith("prompt_snippet="):
                    val = rest.split("=", 1)[1]
                    _get_step_dict(step_val)["prompt_snippet"] = val
                elif rest.startswith("raw_responses_preview="):
                    val = rest.split("=", 1)[1].strip()
                    d = _get_step_dict(step_val)
                    parsed = _parse_llm_responses_text(val)
                    if parsed is not None:
                        d["llm_outputs"] = parsed
                    else:
                        d["llm_outputs_raw"] = val
                elif rest.startswith("executed_action="):
                    val = rest.split("=", 1)[1]
                    _get_step_dict(step_val)["executed_action_str"] = val
                elif rest.startswith("action_timing="):
                    val = rest.split("=", 1)[1]
                    _get_step_dict(step_val)["action_timing_str"] = val

            elif "LLMPolicy heavy-debug: step=" in line:
                try:
                    payload = line.split("LLMPolicy heavy-debug: ", 1)[1].strip()
                except Exception:
                    continue
                parts = payload.split(" ", 1)
                if not parts or not parts[0].startswith("step="):
                    continue
                try:
                    step_val = int(parts[0].split("=", 1)[1])
                except Exception:
                    continue
                rest = parts[1] if len(parts) > 1 else ""

                if "full_prompt=" in rest:
                    after = rest.split("full_prompt=", 1)[1]
                    current_block = {"step": step_val, "kind": "full_prompt", "buf": []}
                    if after:
                        current_block["buf"].append(after)
                elif "full_raw_responses=" in rest:
                    after = rest.split("full_raw_responses=", 1)[1]
                    current_block = {"step": step_val, "kind": "full_raw_responses", "buf": []}
                    if after:
                        current_block["buf"].append(after)

            elif current_block is not None:
                current_block["buf"].append(line)

            elif "LLMPolicy.decide: step=" in line:
                try:
                    payload = line.split("LLMPolicy.decide: ", 1)[1].strip()
                except Exception:
                    continue
                if "legal_actions=" in payload:
                    parts = payload.split(" ", 1)
                    if not parts or not parts[0].startswith("step="):
                        continue
                    try:
                        step_val = int(parts[0].split("=", 1)[1])
                    except Exception:
                        continue
                    rest = parts[1] if len(parts) > 1 else ""
                    idx = rest.find("legal_actions=")
                    if idx != -1:
                        txt = rest[idx + len("legal_actions=") :].strip()
                        d = _get_step_dict(step_val)
                        try:
                            obj = ast.literal_eval(txt)
                        except Exception:
                            obj = None
                        if isinstance(obj, list):
                            d["legal_actions"] = obj
                        else:
                            d["legal_actions_str"] = txt

            elif "LLMPolicy decision fallback: step=" in line:
                # e.g. "LLMPolicy decision fallback: step=12 o_type=... fallback_type=xxx reward=..."
                try:
                    payload = line.split("LLMPolicy decision fallback: ", 1)[1].strip()
                except Exception:
                    continue
                parts = payload.split(" ", 1)
                if not parts or not parts[0].startswith("step="):
                    continue
                try:
                    step_val = int(parts[0].split("=", 1)[1])
                except Exception:
                    continue
                rest = parts[1] if len(parts) > 1 else ""
                fb_type: Optional[str] = None
                idx = rest.find("fallback_type=")
                if idx != -1:
                    after = rest[idx + len("fallback_type=") :]
                    fb_type = after.split(" ", 1)[0]
                d = _get_step_dict(step_val)
                d["fallback_triggered"] = True
                d["fallback_type"] = fb_type

            elif "LLMPolicy decision: step=" in line and "fallback" not in line:
                # Non-fallback decision summary
                try:
                    payload = line.split("LLMPolicy decision: ", 1)[1].strip()
                except Exception:
                    continue
                parts = payload.split(" ", 1)
                if not parts or not parts[0].startswith("step="):
                    continue
                try:
                    step_val = int(parts[0].split("=", 1)[1])
                except Exception:
                    continue
                d = _get_step_dict(step_val)
                d.setdefault("fallback_triggered", False)

        if current_block is not None:
            step_val = current_block["step"]
            kind = current_block["kind"]
            buf = current_block["buf"]
            d = _get_step_dict(step_val)
            text = "\n".join(buf)
            if kind == "full_prompt":
                d["full_prompt"] = text
            elif kind == "full_raw_responses":
                parsed = _parse_llm_responses_text(text)
                if parsed is not None:
                    d["llm_outputs"] = parsed
                else:
                    d["llm_outputs_raw"] = text

    return info_by_step


def _collect_events_between(
    events: List[Dict[str, Any]],
    prev_time: float,
    cur_time: float,
    start_index: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """Collect events in (prev_time, cur_time] starting from start_index.

    Returns the slice of events and the new index to resume from.
    """

    selected: List[Dict[str, Any]] = []
    i = start_index
    n = len(events)
    eps = 1e-9

    # Skip events at or before prev_time
    while i < n and events[i]["time"] <= prev_time + eps:
        i += 1

    # Collect events up to and including cur_time
    while i < n and events[i]["time"] <= cur_time + eps:
        selected.append(events[i])
        i += 1

    return selected, i


def _build_affected_jobs(events_window: List[Dict[str, Any]], snap: Snapshot) -> Dict[str, Any]:
    job_ids: set[str] = set()
    for e in events_window:
        jid = e.get("job_id")
        if isinstance(jid, str):
            job_ids.add(jid)

    if not job_ids:
        return {}

    result: Dict[str, Any] = {}
    for j in snap.jobs:
        if j.job_id not in job_ids:
            continue
        try:
            info: Dict[str, Any] = {
                "job_id": j.job_id,
                "priority": float(getattr(j, "priority", 0.0)),
                "release_time": float(j.release_time),
                "due_date": float(j.due_date),
                "initial_due_date": float(getattr(j, "initial_due_date", j.due_date)),
                "status": j.status,
                "current_op_index": int(getattr(j, "current_op_index", 0)),
                "total_ops": int(getattr(j, "total_ops", len(j.ops))),
                "total_work_content": float(getattr(j, "total_work_content", 0.0)),
                "remaining_work_content": float(getattr(j, "remaining_work_content", 0.0)),
            }
        except Exception:
            continue

        # Route and processing times
        route: List[str] = []
        pt_nominal: List[float] = []
        pt_realized: List[float] = []
        try:
            for op in j.ops:
                route.append(getattr(op, "machine_group", ""))
                try:
                    pt_nominal.append(float(getattr(op, "proc_time_nominal", 0.0)))
                except Exception:
                    pt_nominal.append(0.0)
                try:
                    pt_realized.append(float(getattr(op, "proc_time_realized", 0.0)))
                except Exception:
                    pt_realized.append(0.0)
        except Exception:
            route = []
            pt_nominal = []
            pt_realized = []

        if route:
            info["route"] = route
        if pt_nominal:
            info["proc_times_nominal"] = pt_nominal
        if pt_realized:
            info["proc_times_realized"] = pt_realized

        result[j.job_id] = info

    return result


def _build_affected_machines(events_window: List[Dict[str, Any]], snap: Snapshot) -> Dict[str, Any]:
    machine_ids: set[str] = set()
    for e in events_window:
        mid = e.get("machine_id")
        if isinstance(mid, str):
            machine_ids.add(mid)

    if not machine_ids:
        return {}

    result: Dict[str, Any] = {}
    for m in snap.machines:
        if m.machine_id not in machine_ids:
            continue
        try:
            info: Dict[str, Any] = {
                "machine_id": m.machine_id,
                "group": m.group,
                "status": m.status,
                "available_from": float(m.available_from),
                "queue_len": int(len(m.queue)),
            }
        except Exception:
            continue
        result[m.machine_id] = info

    return result


def build_episode_debug(
    *,
    trajectory_path: Path,
    events_path: Path,
    static_jobs_path: Optional[Path] = None,
    static_machines_path: Optional[Path] = None,
    log_path: Path,
    output_path: Path,
) -> None:
    """Build a compact per-step debug JSON file for a single episode.

    The output is a single JSON object with two top-level keys:

    - ``meta``: run-level metadata and input paths.
    - ``steps``: a list of per-decision records in temporal order.
    """

    # Load trajectory (JSONL expected). This may be either a full trajectory
    # (with per-step snapshots) or a lightweight "summary" trajectory.
    traj = Trajectory.load_from_disk(trajectory_path)

    # Load events and convert to compact dicts, sorted by time.
    typed_events: List[Event] = load_events_jsonl(events_path)
    event_records: List[Dict[str, Any]] = [_event_to_debug_dict(ev) for ev in typed_events]
    event_records.sort(key=lambda r: float(r.get("time", 0.0)))

    # Static files are currently only recorded in meta; they may be used in
    # future for richer diffs against the original configuration.
    static_jobs_str = str(static_jobs_path) if static_jobs_path is not None else None
    static_machines_str = str(static_machines_path) if static_machines_path is not None else None

    # Parse LLM-related information from the log file (best-effort).
    llm_info_by_step = _parse_llm_debug_from_log(log_path)

    # --- Meta record ---
    meta: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "episode_debug_v1",
        "inputs": {
            "trajectory": str(trajectory_path),
            "events": str(events_path),
            "static_jobs": static_jobs_str,
            "static_machines": static_machines_str,
            "log": str(log_path),
        },
    }

    # --- Step records (in-memory) ---
    steps: List[Dict[str, Any]] = []
    ev_idx = 0
    num_steps = 0

    mode = getattr(traj, "_mode", "full")

    if mode != "summary":
        # Full trajectory: iterate over StepRecord objects with full snapshots.
        for step_idx, step in enumerate(traj.iter_steps(), start=1):
            num_steps += 1
            snap: Snapshot = step.snapshot
            cur_time = float(getattr(snap, "time", step.time))
            prev_time = float(getattr(snap, "prev_decision_time", 0.0))

            # Collect events that happened in (prev_time, cur_time].
            events_window, ev_idx = _collect_events_between(event_records, prev_time, cur_time, ev_idx)

            # Executed action and timing (from trajectory step info).
            executed_action = step.action
            action_timing: Optional[Dict[str, Any]] = None
            if isinstance(step.info, dict):
                at = step.info.get("action_timing")
                if isinstance(at, dict):
                    action_timing = at

            gantt_segment: Optional[Dict[str, Any]] = None
            if isinstance(action_timing, dict):
                try:
                    gantt_segment = {
                        "machine_id": action_timing.get("machine_id"),
                        "job_id": action_timing.get("job_id"),
                        "op_index": action_timing.get("op_index"),
                        "start": float(action_timing.get("start_time", 0.0)),
                        "end": float(action_timing.get("end_time", 0.0)),
                    }
                except Exception:
                    gantt_segment = None

            # Affected jobs/machines based on events in this window.
            affected_jobs = _build_affected_jobs(events_window, snap)
            affected_machines = _build_affected_machines(events_window, snap)

            # LLM-side debug info from logs.
            llm_info = llm_info_by_step.get(step_idx, {})
            prompt = llm_info.get("full_prompt") or llm_info.get("prompt_snippet")
            llm_outputs = llm_info.get("llm_outputs")
            if llm_outputs is None:
                raw_txt = llm_info.get("full_raw_responses_str") or llm_info.get("raw_responses_preview")
                if isinstance(raw_txt, str):
                    parsed = _parse_llm_responses_text(raw_txt)
                    llm_outputs = parsed if parsed is not None else raw_txt
            legal_actions = llm_info.get("legal_actions") or llm_info.get("legal_actions_str")
            fallback_triggered = bool(llm_info.get("fallback_triggered", False))
            fallback_type = llm_info.get("fallback_type")

            record: Dict[str, Any] = {
                "step": step_idx,
                "time": cur_time,
                "prev_time": prev_time,
                "events": events_window,
                "executed_action": executed_action,
            }

            if legal_actions is not None:
                record["legal_actions"] = legal_actions
            if isinstance(prompt, str):
                record["prompt_lines"] = prompt.splitlines()
            elif prompt is not None:
                record["prompt"] = prompt
            if llm_outputs is not None:
                record["llm_outputs"] = llm_outputs
            if action_timing is not None:
                record["action_timing"] = action_timing
            if gantt_segment is not None:
                record["gantt_segment"] = gantt_segment

            record["fallback"] = {
                "triggered": fallback_triggered,
                "type": fallback_type,
            }

            if affected_jobs:
                record["affected_jobs"] = affected_jobs
            if affected_machines:
                record["affected_machines"] = affected_machines

            steps.append(record)
    else:
        # Summary trajectory: the JSONL only contains header + summary
        # records, without full snapshots. We treat each decision
        # summary (has_decision == True) as a step.
        try:
            with trajectory_path.open("r", encoding="utf-8") as tf:
                # Skip header line
                first = tf.readline()
                _ = first
                prev_decision_time = 0.0
                for line in tf:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("type") != "summary":
                        continue

                    cur_time = float(obj.get("time", 0.0))
                    has_decision = bool(obj.get("has_decision", False))
                    if not has_decision:
                        continue

                    # This is a decision summary; treat it as a step.
                    num_steps += 1
                    step_idx = num_steps

                    events_window, ev_idx = _collect_events_between(
                        event_records,
                        prev_decision_time,
                        cur_time,
                        ev_idx,
                    )

                    executed_action = obj.get("action")
                    info = obj.get("info") or {}
                    action_timing = None
                    if isinstance(info, dict):
                        at = info.get("action_timing")
                        if isinstance(at, dict):
                            action_timing = at

                    gantt_segment: Optional[Dict[str, Any]] = None
                    if isinstance(action_timing, dict):
                        try:
                            gantt_segment = {
                                "machine_id": action_timing.get("machine_id"),
                                "job_id": action_timing.get("job_id"),
                                "op_index": action_timing.get("op_index"),
                                "start": float(action_timing.get("start_time", 0.0)),
                                "end": float(action_timing.get("end_time", 0.0)),
                            }
                        except Exception:
                            gantt_segment = None

                    llm_info = llm_info_by_step.get(step_idx, {})
                    prompt = llm_info.get("full_prompt") or llm_info.get("prompt_snippet")
                    llm_outputs = llm_info.get("llm_outputs")
                    if llm_outputs is None:
                        raw_txt = llm_info.get("full_raw_responses_str") or llm_info.get("raw_responses_preview")
                        if isinstance(raw_txt, str):
                            parsed = _parse_llm_responses_text(raw_txt)
                            llm_outputs = parsed if parsed is not None else raw_txt
                    legal_actions = llm_info.get("legal_actions") or llm_info.get("legal_actions_str")
                    fallback_triggered = bool(llm_info.get("fallback_triggered", False))
                    fallback_type = llm_info.get("fallback_type")

                    record = {
                        "step": step_idx,
                        "time": cur_time,
                        "prev_time": prev_decision_time,
                        "events": events_window,
                        "executed_action": executed_action,
                    }

                    if legal_actions is not None:
                        record["legal_actions"] = legal_actions
                    if isinstance(prompt, str):
                        record["prompt_lines"] = prompt.splitlines()
                    elif prompt is not None:
                        record["prompt"] = prompt
                    if llm_outputs is not None:
                        record["llm_outputs"] = llm_outputs
                    if action_timing is not None:
                        record["action_timing"] = action_timing
                    if gantt_segment is not None:
                        record["gantt_segment"] = gantt_segment

                    record["fallback"] = {
                        "triggered": fallback_triggered,
                        "type": fallback_type,
                    }

                    steps.append(record)

                    prev_decision_time = cur_time
        except Exception as exc:
            logger.error("EpisodeDebug: failed to iterate summary trajectory: {}", exc)

    # Prepare output path and write a single JSON object.
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "steps": steps,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info(
        "EpisodeDebug: wrote {} step records to {}",
        num_steps,
        output_path,
    )
