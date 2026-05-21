"""Priority dispatching rules for job and machine selection.

This module implements the core logic for computing job priorities and selecting
machines based on various heuristic rules.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import random


class JobSelectionRule(str, Enum):
    """Supported job selection rules."""
    SPT = "SPT"      # Shortest Processing Time
    LPT = "LPT"      # Longest Processing Time
    MWKR = "MWKR"    # Most Work Remaining
    LWKR = "LWKR"    # Least Work Remaining
    MOPNR = "MOPNR"  # Most Operations Remaining
    LOPNR = "LOPNR"  # Least Operations Remaining
    FIFO = "FIFO"    # First In First Out
    LIFO = "LIFO"    # Last In First Out


class MachineSelectionRule(str, Enum):
    """Supported machine selection rules."""
    LIT = "LIT"  # Least Idle Time (earliest available)
    LWL = "LWL"  # Least Workload
    SPT = "SPT"  # Shortest Processing Time


def precompute_remaining_work(
    jobs: Dict[str, Any]
) -> Dict[Tuple[str, int], float]:
    """Precompute remaining work for all (job_id, op_index) pairs.
    
    Args:
        jobs: Dictionary of job states from observation
        
    Returns:
        Dictionary mapping (job_id, op_index) to remaining work after that operation
    """
    cache: Dict[Tuple[str, int], float] = {}
    
    for job_id, job in jobs.items():
        ops = job.get("ops", [])
        n_ops = len(ops)
        
        # Compute suffix sums (remaining work after each op)
        suffix = [0.0] * (n_ops + 1)
        for i in range(n_ops - 1, -1, -1):
            op = ops[i]
            proc_time = float(op.get("proc_time_realized", op.get("proc_time_nominal", 0.0)))
            suffix[i] = suffix[i + 1] + proc_time
        
        # Cache remaining work after each operation
        for op_idx in range(n_ops):
            cache[(job_id, op_idx)] = suffix[op_idx + 1]
    
    return cache


def compute_job_priority(
    rule: str,
    job_id: str,
    op_index: int,
    proc_time: float,
    obs: Dict[str, Any],
    remain_work_cache: Optional[Dict[Tuple[str, int], float]] = None,
    is_emergency: bool = False,
) -> float:
    """Compute priority value for a job-operation pair.
    
    Lower values have higher priority.
    
    Args:
        rule: Job selection rule name
        job_id: Job identifier
        op_index: Operation index within job
        proc_time: Processing time of the operation
        obs: Current observation from environment
        remain_work_cache: Precomputed remaining work cache
        is_emergency: Whether this is an emergency job
        
    Returns:
        Priority value (lower is better)
    """
    rule = rule.upper()
    
    # Emergency jobs get extremely high priority
    if is_emergency:
        base_emergency_priority = -1e9
        
        # Still apply internal ordering among emergency jobs
        if rule == "SPT":
            internal_priority = proc_time
        elif rule == "LPT":
            internal_priority = -proc_time
        elif rule == "MWKR":
            rem_work = remain_work_cache.get((job_id, op_index), 0.0) if remain_work_cache else 0.0
            internal_priority = -rem_work
        elif rule == "LWKR":
            rem_work = remain_work_cache.get((job_id, op_index), 0.0) if remain_work_cache else 0.0
            internal_priority = rem_work
        elif rule == "MOPNR":
            jobs = obs.get("jobs", {})
            job_info = jobs.get(job_id, {})
            total_ops = job_info.get("total_ops", op_index + 1)
            rem_ops = max(0, int(total_ops) - (op_index + 1))
            internal_priority = -rem_ops
        elif rule == "LOPNR":
            jobs = obs.get("jobs", {})
            job_info = jobs.get(job_id, {})
            total_ops = job_info.get("total_ops", op_index + 1)
            rem_ops = max(0, int(total_ops) - (op_index + 1))
            internal_priority = rem_ops
        elif rule == "FIFO":
            jobs = obs.get("jobs", {})
            job_info = jobs.get(job_id, {})
            arrival_time = job_info.get("release_time", 0.0)
            internal_priority = arrival_time
        elif rule == "LIFO":
            jobs = obs.get("jobs", {})
            job_info = jobs.get(job_id, {})
            arrival_time = job_info.get("release_time", 0.0)
            internal_priority = -arrival_time
        else:
            internal_priority = proc_time
        
        # Normalize to avoid extreme values
        normalized_priority = max(-1000, min(1000, internal_priority))
        return base_emergency_priority + normalized_priority
    
    # Normal job priority
    if rule == "SPT":
        return proc_time
    
    if rule == "LPT":
        return -proc_time
    
    if rule == "MWKR":
        rem_work = remain_work_cache.get((job_id, op_index), 0.0) if remain_work_cache else 0.0
        return -rem_work
    
    if rule == "LWKR":
        rem_work = remain_work_cache.get((job_id, op_index), 0.0) if remain_work_cache else 0.0
        return rem_work
    
    if rule == "MOPNR":
        jobs = obs.get("jobs", {})
        job_info = jobs.get(job_id, {})
        total_ops = job_info.get("total_ops", op_index + 1)
        rem_ops = max(0, int(total_ops) - (op_index + 1))
        return -rem_ops
    
    if rule == "LOPNR":
        jobs = obs.get("jobs", {})
        job_info = jobs.get(job_id, {})
        total_ops = job_info.get("total_ops", op_index + 1)
        rem_ops = max(0, int(total_ops) - (op_index + 1))
        return rem_ops
    
    if rule == "FIFO":
        jobs = obs.get("jobs", {})
        job_info = jobs.get(job_id, {})
        arrival_time = job_info.get("release_time", 0.0)
        return arrival_time
    
    if rule == "LIFO":
        jobs = obs.get("jobs", {})
        job_info = jobs.get(job_id, {})
        arrival_time = job_info.get("release_time", 0.0)
        return -arrival_time
    
    # Default: SPT
    return proc_time


def select_best_machine(
    rule: str,
    candidates: List[Dict[str, Any]],
    proc_time: float,
    obs: Dict[str, Any],
) -> Optional[str]:
    """Select the best machine according to the given rule.
    
    Args:
        rule: Machine selection rule name
        candidates: List of candidate machine info dicts
        proc_time: Processing time of the operation
        obs: Current observation from environment
        
    Returns:
        Selected machine ID, or None if no valid candidate
    """
    if not candidates:
        return None
    
    rule = rule.upper()
    machines = obs.get("machines", {})
    
    best_machine_id: Optional[str] = None
    best_value = float("inf")
    tied_candidates: List[str] = []
    
    for cand in candidates:
        machine_id = cand.get("machine_id")
        if not machine_id:
            continue
        
        machine_info = machines.get(machine_id, {})

        if rule == "LIT":
            # Least Idle Time = earliest available time
            value = machine_info.get("available_from", 0.0)
        elif rule == "LWL":
            # Least Workload = minimum total busy time or queue length
            value = machine_info.get("busy_time", 0.0)
        elif rule == "SPT":
            # Shortest Processing Time on this machine.
            # If the candidate dict carries a per-machine processing time,
            # prefer that (used by JMSRawEnv to match EnvState semantics);
            # otherwise fall back to proc_time/speed.
            cand_pt = cand.get("proc_time")
            if cand_pt is not None:
                try:
                    value = float(cand_pt)
                except Exception:
                    speed = machine_info.get("speed", 1.0)
                    value = proc_time / max(1e-9, speed)
            else:
                speed = machine_info.get("speed", 1.0)
                value = proc_time / max(1e-9, speed)
        else:
            # Default: LIT
            value = machine_info.get("available_from", 0.0)
        
        if value < best_value:
            best_value = value
            tied_candidates = [machine_id]
        elif value == best_value:
            tied_candidates.append(machine_id)
    
    # Break ties randomly
    if tied_candidates:
        return random.choice(tied_candidates)
    
    return best_machine_id
