from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Literal


OperationStatus = Literal["not_arrived", "not_released", "waiting", "processing", "done", "cancelled"]
JobStatus = Literal["not_arrived", "waiting", "processing", "completed", "cancelled"]
MachineStatus = Literal["idle", "busy", "down_pm", "down_breakdown"]


@dataclass
class OperationState:
    """Internal representation of a single operation of a job.

    This is an internal, simulator-owned structure. External consumers should
    only depend on the public Snapshot models.
    """

    op_id: str
    job_id: str
    index: int
    machine_group: str
    candidate_machines: List[str]
    proc_time_nominal: float
    proc_time_realized: float
    status: OperationStatus = "not_arrived"
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    prev_start_time: Optional[float] = None
    prev_machine_id: Optional[str] = None
    rework_count: int = 0


@dataclass
class JobState:
    """Internal representation of a job and its operations."""

    job_id: str
    family: str
    release_time: float
    due_date: float
    initial_due_date: float
    priority: float = 0.0
    weight: float = 1.0
    status: JobStatus = "not_arrived"
    current_op_index: int = 0
    total_ops: int = 0
    total_work_content: float = 0.0
    remaining_work_content: float = 0.0
    completion_time: Optional[float] = None
    lateness: Optional[float] = None
    tardiness: Optional[float] = None
    cancellation_time: Optional[float] = None
    next_available_time: float = 0.0
    ops: List[OperationState] = field(default_factory=list)


@dataclass
class ScheduleSegment:
    """A scheduled processing segment on a machine."""

    start: float
    end: float
    job_id: str
    op_id: str
    is_frozen: bool = False


@dataclass
class MachineState:
    """Internal representation of a single machine."""

    machine_id: str
    group: str
    speed: float
    status: MachineStatus = "idle"
    available_from: float = 0.0
    current_job_id: Optional[str] = None
    current_op_id: Optional[str] = None
    # Queue entries: (job_id, op_id, priority, due_date, arrival_to_queue_time)
    queue: List[Tuple[str, str, float, float, float]] = field(default_factory=list)
    schedule_segments: List[ScheduleSegment] = field(default_factory=list)
    busy_time: float = 0.0
    downtime: float = 0.0


@dataclass
class SystemState:
    """Top-level simulator state container.

    The simulator holds a single SystemState instance and mutates it as time
    progresses and decisions are applied.
    """

    time: float
    prev_decision_time: float
    horizon: float
    lookahead_horizon: float
    jobs: Dict[str, JobState] = field(default_factory=dict)
    machines: Dict[str, MachineState] = field(default_factory=dict)
    # machine_groups[group_id] = {"machine_ids": [...], "total_speed": float}
    machine_groups: Dict[str, Dict[str, object]] = field(default_factory=dict)
    num_reschedules: int = 0
    last_schedule_change_time: float = 0.0

    def reset_counters(self) -> None:
        """Clear counters that are meaningful per-episode but not per-step."""

        self.num_reschedules = 0
        self.last_schedule_change_time = 0.0
        for m in self.machines.values():
            m.busy_time = 0.0
            m.downtime = 0.0
            m.schedule_segments.clear()
            m.queue.clear()
            m.status = "idle"
            m.available_from = 0.0
            m.current_job_id = None
            m.current_op_id = None

        for j in self.jobs.values():
            j.status = "not_arrived"
            j.current_op_index = 0
            j.remaining_work_content = j.total_work_content
            j.completion_time = None
            j.lateness = None
            j.tardiness = None
            j.cancellation_time = None
            j.next_available_time = j.release_time
            for op in j.ops:
                op.status = "not_arrived"
                op.start_time = None
                op.end_time = None
                op.prev_start_time = None
                op.prev_machine_id = None
                op.rework_count = 0
