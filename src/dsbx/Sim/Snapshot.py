from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobOpSnapshot(BaseModel):
    """Snapshot view of a single operation.

    This is the external, read-only representation derived from the
    simulator's internal OperationState.
    """

    op_id: str
    job_id: str
    index: int
    machine_group: str
    candidate_machines: List[str]
    proc_time_nominal: float
    proc_time_realized: float
    status: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    remaining_time: float
    prev_start_time: Optional[float] = None
    prev_machine_id: Optional[str] = None
    rework_count: int = 0


class JobSnapshot(BaseModel):
    """Snapshot view of a job and all its operations."""

    job_id: str
    family: str
    release_time: float
    due_date: float
    initial_due_date: float
    priority: float
    weight: float
    status: str
    current_op_index: int
    total_ops: int
    total_work_content: float
    remaining_work_content: float
    completion_time: Optional[float] = None
    lateness: Optional[float] = None
    tardiness: Optional[float] = None
    cancellation_time: Optional[float] = None
    ops: List[JobOpSnapshot]


class MachineScheduleSegmentSnapshot(BaseModel):
    """Snapshot view of a scheduled segment on a machine."""

    start: float
    end: float
    job_id: str
    op_id: str
    is_frozen: bool = False


class MachineSnapshot(BaseModel):
    """Snapshot view of a machine, its availability, and its queue."""

    machine_id: str
    group: str
    speed: float
    status: str
    available_from: float
    current_job_id: Optional[str] = None
    current_op_id: Optional[str] = None
    # queue entries: {job_id, op_id, priority, due_date, arrival_to_queue_time}
    queue: List[Dict[str, float]]
    schedule_segments: List[MachineScheduleSegmentSnapshot]


class EventSnapshot(BaseModel):
    """Minimal snapshot view of a pending event."""

    time: float
    event_type: str
    payload: Dict[str, Any]


class SystemStats(BaseModel):
    """Aggregated system-level statistics at a decision point."""

    num_jobs_total: int
    num_jobs_arrived: int
    num_jobs_completed: int
    num_jobs_cancelled: int
    wip_count: int
    queue_length_by_machine: Dict[str, int]
    queue_length_by_group: Dict[str, int]
    utilization_by_machine: Dict[str, float]
    utilization_by_group: Dict[str, float]
    num_reschedules: int
    last_schedule_change_time: float
    # Aggregated counts of key dynamic events that have occurred up to the
    # current decision time. Keys follow a stable naming convention such as
    # "arrival", "cancellation", "breakdown", "pm", "priority_change",
    # "ptime_change", "route_change", "due_date_change".
    event_counters: Dict[str, int] = Field(default_factory=dict)


class StabilityStats(BaseModel):
    """Schedule stability metrics between consecutive decision points."""

    changed_ops_ratio: float
    avg_start_time_shift: float
    max_start_time_shift: float


class Snapshot(BaseModel):
    """Top-level snapshot returned by the simulator.

    It aims to be sufficiently rich for OR/MILP, RL, and LLM-based agents,
    while remaining serialization-friendly (JSON-compatible).
    """

    # Time and identification
    time: float
    prev_decision_time: float
    horizon: float
    lookahead_horizon: float
    scenario_id: Optional[str] = None
    seed: Optional[int] = None
    config_hash: Optional[str] = None

    # Static configuration (embedded from InputModel for convenience)
    plant: Optional[Dict[str, Any]] = None
    scale: Optional[Dict[str, Any]] = None
    targets: Optional[Dict[str, Any]] = None
    dynamics: Optional[Dict[str, Any]] = None
    dynamic_scenarios: Optional[Dict[str, Any]] = None

    # Dynamic state
    jobs: List[JobSnapshot]
    machines: List[MachineSnapshot]
    pending_events: List[EventSnapshot]

    # Aggregated views
    system_stats: SystemStats
    stability_stats: StabilityStats
