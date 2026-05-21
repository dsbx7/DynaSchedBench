from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import heapq
import json


PRIORITY: Dict[str, int] = {
    "machine_repair": 0,
    "machine_break": 1,
    "job_emergency": 2,
    "job_cancel": 3,
    "job_arrival": 4,
    "op_complete": 5,
}


@dataclass
class JMSOperation:
    """Single operation of a job in JMS/GEN-Bench style instances.

    Each operation keeps the full candidate-machine set and per-machine
    processing times, without projecting to a single route.
    """

    job_id: int
    op_index: int  # 0-based
    candidates: List[int]
    proc_time: Dict[int, float]
    status: str = "not_arrived"  # not_arrived / waiting / processing / done / cancelled
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    # Machine actually used for this operation when scheduled. This is
    # populated by JMSSim.step_action and used for Gantt reconstruction.
    machine_id: Optional[int] = None
    segments: List[Tuple[float, float, int]] = field(default_factory=list)


@dataclass
class JMSJob:
    """Static + dynamic state of a job (normal or emergency)."""

    job_id: int
    ops: List[JMSOperation]
    release_time: float = 0.0
    status: str = "not_arrived"  # not_arrived / waiting / processing / completed / cancelled
    current_op_index: int = 0
    cancellation_time: Optional[float] = None
    completion_time: Optional[float] = None

    def remaining_ops(self) -> int:
        k = self.current_op_index
        return max(0, len(self.ops) - k)


@dataclass
class JMSMachine:
    """Single machine with explicit down-intervals and availability."""

    machine_id: int  # 0-based index used in static_info
    available_from: float = 0.0
    down_intervals: List[Tuple[float, float]] = field(default_factory=list)
    is_broken: bool = False

    def is_down(self, t: float) -> bool:
        # In EnvState-style semantics, "down" means currently broken.
        # Future breakdowns are handled via events and preemption, not via static intervals.
        return self.is_broken

    def first_non_overlapping_start(self, start: float, duration: float) -> float:
        """Placeholder kept for backward compatibility; dynamic breakdowns are event-driven."""

        return start


@dataclass(order=True)
class _CompletionRecord:
    """Internal completion record for an operation on a machine."""

    time: float
    seq: int
    job_id: int = field(compare=False)
    op_index: int = field(compare=False)
    machine_id: int = field(compare=False)


@dataclass(order=True)
class _ExternalEvent:
    """Externally specified dynamic events from dynamic_events block."""

    time: float
    priority: int
    kind: str = field(compare=False)
    job_id: Optional[int] = field(default=None, compare=False)


def load_jms_like_instance(path: Path | str) -> Dict[str, Any]:
    """Load a single JMS/GEN-Bench style JSONL instance file.

    The current JMSBench/GEN-Bench instances in ``data/jmsbench`` and
    ``data/genbench`` are stored as one JSON object per file (single line).
    This helper reads the first non-empty line and parses it as JSON.
    """

    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        first: str = ""
        for line in f:
            line = line.strip()
            if not line:
                continue
            first = line
            break

    if not first:
        raise ValueError(f"Empty JMS/GEN-Bench instance file: {p}")

    payload = json.loads(first)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected top-level JSON object in {p}, got {type(payload)!r}")
    return payload


class JMSSim:
    """Event-driven simulator for raw JMS/GEN-Bench JSONL instances.

    This simulator operates *directly* on the original instance format
    (data/jms/* and data/genbench/*), keeping the full candidates and
    per-machine processing times. It does **not** depend on InputModel
    and is intentionally separate from :class:`DynaSchedSim`.
    """

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

        self.jobs: Dict[int, JMSJob] = {}
        self.machines: Dict[int, JMSMachine] = {}

        # Cached original structures
        self._static_info: Dict[str, Any] = self._payload["static_info"]
        self._dynamic_events: Dict[str, List[List[Any]]] = self._payload.get("dynamic_events") or {}
        self._emergency_static: Dict[str, Any] = self._payload.get("emergency_static") or {}
        self._initial_time: float = float(self._payload.get("timestamp", 0.0))

        # Dynamic state (EnvState-style)
        self.time: float = self._initial_time
        self._event_heap: List[Tuple[float, int, str, Any]] = []

        self.machine_busy_until: List[float] = []
        # Total assigned processing time per machine (EnvState-style workload).
        # This is incremented every time we schedule an operation on a machine
        # and is never decremented, even if operations are preempted or
        # cancelled, matching EnvState.work_load semantics.
        self.machine_workload: List[float] = []
        self.machine_status: Dict[int, Tuple[int, int, float]] = {}
        self.job_progress: Dict[int, int] = {}
        self.job_arrival_map: Dict[int, float] = {}
        self.job_busy_until: Dict[int, float] = {}
        self.interrupted_ops: List[Tuple[int, int, List[Tuple[int, float]]]] = []
        self.broken_machines: set[int] = set()
        self.emergency_jobs: set[int] = set()
        self._generated_emg_static: set[int] = set()

        # Legacy completion heap (will be unused once event semantics are fully unified)
        self._completion_heap: List[_CompletionRecord] = []
        self._completion_seq: int = 0

        self._build_static()
        self._build_events()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    def _build_static(self) -> None:
        static = self._static_info
        num_jobs = int(static["num_jobs"])
        num_machines = int(static["num_machines"])
        ops_per_job: List[int] = list(static["ops_per_job"])
        candidates_raw: Dict[str, List[int]] = static["candidates"]
        proc_time_raw: Dict[str, Dict[str, float]] = static["proc_time"]

        # Normal jobs
        for j in range(1, num_jobs + 1):
            n_ops = int(ops_per_job[j - 1])
            ops: List[JMSOperation] = []
            for o in range(1, n_ops + 1):
                key = f"({j},{o})"
                cand = list(candidates_raw.get(key, []))
                pt_map_raw = proc_time_raw.get(key, {})
                pt_map: Dict[int, float] = {int(m): float(t) for m, t in pt_map_raw.items()}
                ops.append(
                    JMSOperation(
                        job_id=j,
                        op_index=o - 1,
                        candidates=cand,
                        proc_time=pt_map,
                    )
                )
            self.jobs[j] = JMSJob(job_id=j, ops=ops)

        # Emergency jobs (if any).
        #
        # IMPORTANT: To match EnvState semantics, we intentionally treat each
        # emergency job as a *single-operation* job, even if emergency_static
        # declares multiple operations. EnvState._add_emergency_job_static
        # always sets ops_per_job[jid-1] = 1, effectively ignoring any
        # additional operations in emergency_static.
        em_static = self._payload.get("emergency_static") or {}
        for em_jid_str, info in em_static.items():
            try:
                em_jid = int(em_jid_str)
            except ValueError:
                continue

            cand_raw = info.get("candidates", {})
            pt_raw = info.get("proc_time", {})

            key = f"({em_jid},1)"
            cand = list(cand_raw.get(key, []))
            pt_map_raw = pt_raw.get(key, {})
            pt_map: Dict[int, float] = {int(m): float(t) for m, t in pt_map_raw.items()}

            ops: List[JMSOperation] = [
                JMSOperation(
                    job_id=em_jid,
                    op_index=0,
                    candidates=cand,
                    proc_time=pt_map,
                )
            ]
            self.jobs[em_jid] = JMSJob(job_id=em_jid, ops=ops)

        # Machines and downtime intervals (from machine_break/repair)
        for m in range(num_machines):
            self.machines[m] = JMSMachine(machine_id=m)

        # EnvState-style initial availability: all machines idle at initial time,
        # jobs become available according to job_arrival events.
        self.machine_busy_until = [self.time] * num_machines
        # EnvState-style workload per machine: total busy time assigned so far.
        self.machine_workload = [0.0] * num_machines
        self.job_arrival_map = {
            int(jid): float(t) for jid, t in self._dynamic_events.get("job_arrival", [])
        }
        self.job_busy_until = {jid: t for jid, t in self.job_arrival_map.items()}

    def _build_events(self) -> None:
        """Initialise the external dynamic event heap from dynamic_events."""

        self._event_heap.clear()
        dyn = self._dynamic_events

        for ev_type, lst in dyn.items():
            if ev_type not in PRIORITY:
                # Ignore unsupported event types (e.g., due date changes)
                continue
            prio = PRIORITY[ev_type]
            for ev_id, t in lst:
                tt = float(t)
                if tt < self._initial_time:
                    continue
                self._event_heap.append((tt, prio, ev_type, ev_id))

        heapq.heapify(self._event_heap)

    # ------------------------------------------------------------------
    # Core simulation API
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Reset simulation time and dynamic state.

        Static structures (jobs/machines) remain, but all per-episode
        fields such as status/timestamps are cleared.
        """

        self.time = self._initial_time
        self._completion_heap.clear()
        self._completion_seq = 0
        self._build_events()

        static = self._static_info
        num_machines = int(static["num_machines"])

        self.machine_busy_until = [self.time] * num_machines
        self.machine_workload = [0.0] * num_machines
        self.machine_status.clear()
        self.job_progress.clear()
        self.job_arrival_map = {
            int(jid): float(t) for jid, t in self._dynamic_events.get("job_arrival", [])
        }
        self.job_busy_until = {jid: t for jid, t in self.job_arrival_map.items()}
        self.interrupted_ops = []
        self.broken_machines.clear()
        self.emergency_jobs.clear()
        self._generated_emg_static.clear()

        for job in self.jobs.values():
            job.status = "not_arrived"
            job.current_op_index = 0
            job.cancellation_time = None
            job.completion_time = None
            if str(job.job_id) in self._emergency_static:
                job.release_time = float("inf")
            else:
                job.release_time = self.job_arrival_map.get(job.job_id, self.time)
            for op in job.ops:
                op.status = "not_arrived"
                op.start_time = None
                op.end_time = None
                op.machine_id = None
                op.segments.clear()

        for m in self.machines.values():
            m.available_from = self.time

        # Apply any events at time 0 and advance to first decision point
        self._process_until(self.time)
        self.advance_to_next_decision_point()

    # ------------------------------------------------------------------
    # External event injection (for non-stationary experiments)
    # ------------------------------------------------------------------
    def add_external_event(self, *, kind: str, ev_id: Any, time: Optional[float] = None) -> None:
        """Inject a dynamic event into the simulator.

        This is a lightweight hook intended for non-stationary experiments.
        The injected event is appended to the internal event heap and will
        take effect when simulation time advances to the event timestamp.

        Parameters
        ----------
        kind:
            One of keys in PRIORITY (e.g. job_emergency, job_cancel,
            machine_break, machine_repair, job_arrival).
        ev_id:
            Job/machine id associated with the event.
        time:
            Event time. If None, uses current sim.time.
        """

        k = str(kind)
        if k not in PRIORITY:
            raise ValueError(f"Unsupported external event kind: {k}")
        t = float(self.time if time is None else time)
        prio = int(PRIORITY[k])
        heapq.heappush(self._event_heap, (t, prio, k, ev_id))

    def add_external_events(self, events: List[Dict[str, Any]]) -> None:
        """Batch injection wrapper for add_external_event."""

        for ev in events:
            if not isinstance(ev, dict):
                continue
            kind = ev.get("kind")
            ev_id = ev.get("id")
            t = ev.get("time")
            self.add_external_event(kind=str(kind), ev_id=ev_id, time=(float(t) if t is not None else None))

    # Public helpers ----------------------------------------------------
    def is_finished(self) -> bool:
        """Return True if all jobs are completed or cancelled and no events remain."""

        if self._event_heap or self._completion_heap:
            return False
        for job in self.jobs.values():
            if job.status not in ("completed", "cancelled"):
                return False
        return True

    def get_ready_operations(self) -> List[JMSOperation]:
        """Return operations that are ready to be scheduled at current time."""

        self._update_job_readiness()
        ready: List[JMSOperation] = []
        for job in self.jobs.values():
            if job.status == "cancelled":
                continue
            if job.current_op_index >= len(job.ops):
                continue
            if job.release_time > self.time:
                continue
            op = job.ops[job.current_op_index]
            if op.status != "waiting":
                continue
            ready.append(op)
        return ready

    # Scheduling --------------------------------------------------------
    def step_action(self, job_id: int, machine_id: int) -> None:
        """Schedule the next operation of job_id on the given machine.

        This does **not** advance time to the next decision point; callers
        should invoke :meth:`advance_to_next_decision_point` afterwards.
        """

        job_id = int(job_id)
        machine_id = int(machine_id)

        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status == "cancelled":
            raise ValueError(f"Cannot schedule cancelled job {job_id}")

        # EnvState-style semantics: if this is an emergency job, mark it as
        # no longer pending in emergency_jobs when we schedule it.
        if job_id in self.emergency_jobs:
            self.emergency_jobs.discard(job_id)

        self._update_job_readiness()
        if job.current_op_index >= len(job.ops):
            raise ValueError(f"Job {job_id} has no remaining operations")

        op = job.ops[job.current_op_index]
        if machine_id not in op.candidates:
            raise ValueError(
                f"Machine {machine_id} is not a candidate for job {job_id} op {op.op_index}"
            )

        machine = self.machines.get(machine_id)
        if machine is None:
            raise ValueError(f"Unknown machine_id: {machine_id}")

        if not self._machine_available(machine_id, self.time):
            busy_until = None
            if 0 <= machine_id < len(self.machine_busy_until):
                try:
                    busy_until = float(self.machine_busy_until[machine_id])
                except Exception:
                    busy_until = self.machine_busy_until[machine_id]
            raise ValueError(
                f"Machine {machine_id} is not available at time {float(self.time):.9f} "
                f"(busy_until={busy_until}, broken={machine_id in self.broken_machines})"
            )

        base_start = max(self.time, job.release_time, machine.available_from)

        # Base processing time from static proc_time map
        base_pt = float(op.proc_time.get(int(machine_id), min(op.proc_time.values() or [1.0])))

        # If this (job, op, machine) appears in interrupted_ops, use the
        # recorded remaining time instead and drop the corresponding
        # interrupted entry entirely, matching EnvState.schedule_op
        # semantics (which remove the whole (job, op) record once it is
        # scheduled on any machine).
        remaining_pt: Optional[float] = None
        if self.interrupted_ops:
            new_interrupted = []
            for j0, o0, cand in self.interrupted_ops:
                if j0 == job_id and o0 == op.op_index:
                    # Extract remaining processing time for the scheduled
                    # machine if present, but always drop the entire record
                    # to mirror EnvState behaviour.
                    for m0, rt in cand:
                        if m0 == machine_id and remaining_pt is None:
                            remaining_pt = float(rt)
                    # Do NOT append this (j0, o0, cand) back into
                    # new_interrupted, even if other machines remain.
                    continue

                new_interrupted.append((j0, o0, cand))
            self.interrupted_ops = new_interrupted

        p = remaining_pt if remaining_pt is not None else base_pt
        start = machine.first_non_overlapping_start(base_start, p)
        end = start + p

        # Update operation
        op.status = "processing"
        if op.start_time is None:
            op.start_time = start
        op.end_time = end
        op.machine_id = machine.machine_id
        op.segments.append((float(start), float(end), int(machine.machine_id)))

        # Update job
        job.status = "processing"

        # Update machine
        machine.available_from = end

        mid = machine.machine_id
        if 0 <= mid < len(self.machine_busy_until):
            self.machine_busy_until[mid] = end
        if 0 <= mid < len(self.machine_workload):
            # Accumulate total assigned processing time (EnvState.work_load)
            self.machine_workload[mid] += float(p)
        self.job_busy_until[job.job_id] = end
        self.machine_status[mid] = (job.job_id, op.op_index, end)

        # Push unified op_complete event into the event heap
        heapq.heappush(
            self._event_heap,
            (end, PRIORITY["op_complete"], "op_complete", (job.job_id, op.op_index, machine.machine_id)),
        )

    # Time advancement --------------------------------------------------
    def advance_to_next_decision_point(self) -> None:
        """Advance time until at least one operation becomes ready or the sim ends."""

        # If already have ready ops, stay at current time
        if self.get_ready_operations():
            return

        while True:
            if not self._event_heap:
                # Nothing left to happen
                return

            next_event_time = self._event_heap[0][0]
            self.time = max(self.time, next_event_time)

            # Process all events (including op_complete) up to this time
            self._process_until(self.time)

            # Update readiness and break if any op is ready
            if self.get_ready_operations():
                return

            # Otherwise continue to the next event

    # Internal helpers --------------------------------------------------
    def _machine_available(self, m_id: int, t: float) -> bool:
        """Return True if machine m_id is available at time t (EnvState-style)."""

        if m_id in self.broken_machines:
            return False
        if 0 <= m_id < len(self.machine_busy_until):
            return self.machine_busy_until[m_id] <= t + 1e-9
        return True

    def _process_until(self, t: float) -> None:
        """Process all external events with time <= t."""

        while self._event_heap and self._event_heap[0][0] <= t + 1e-9:
            ev_time, _prio, ev_type, ev_info = heapq.heappop(self._event_heap)
            if ev_type == "job_arrival":
                job_id = int(ev_info)
                job = self.jobs.get(job_id)
                if job is None:
                    continue
                # Record (latest) release time; status will be updated lazily
                job.release_time = float(ev_time)
            elif ev_type == "job_emergency":
                job_id = int(ev_info)
                job = self.jobs.get(job_id)
                if job is None:
                    continue
                job.release_time = float(ev_time)
                self.emergency_jobs.add(job_id)
                
                # Add to job_arrival_map so emergency jobs become ready
                # through the normal path once machines are available.
                # This prevents emergency jobs from getting stuck when
                # all candidate machines are broken/busy at arrival time.
                self.job_arrival_map[job_id] = float(ev_time)

                # EnvState-style preemption for emergency jobs: try to free
                # a candidate machine by preempting the earliest-finishing
                # running operation, then register the emergency op as
                # interrupted/ready on any available machines.
                if job.ops:
                    first_op_idx = 0
                    first_op = job.ops[first_op_idx]
                    cand_machines = list(first_op.candidates)

                    # Find running operations on candidate machines
                    running: List[Tuple[int, float]] = []
                    for m_id, (_j_r, _o_r, e_r) in self.machine_status.items():
                        if m_id in cand_machines and e_r > t:
                            running.append((m_id, float(e_r)))

                    if running:
                        m_sel, e_sel = min(running, key=lambda x: x[1])
                        j_r, o_r, e_r = self.machine_status[m_sel]
                        rem = max(0.0, float(e_r) - float(t))

                        # Record interrupted remaining time for the preempted op
                        self.interrupted_ops.append((j_r, o_r, [(m_sel, rem)]))

                        # Mark the preempted operation as waiting again
                        job_r = self.jobs.get(j_r)
                        if job_r is not None and 0 <= o_r < len(job_r.ops):
                            op_r = job_r.ops[o_r]
                            if op_r.status == "processing":
                                op_r.status = "waiting"
                                job_r.current_op_index = min(job_r.current_op_index, o_r)
                                if job_r.status != "cancelled":
                                    job_r.status = "waiting"

                        # Cancel it on the machine and remove its completion
                        self._cancel_operation_on_machine(m_sel, t)

                        if self._completion_heap:
                            self._completion_heap = [
                                rec
                                for rec in self._completion_heap
                                if not (
                                    rec.job_id == j_r
                                    and rec.op_index == o_r
                                    and rec.machine_id == m_sel
                                )
                            ]
                            heapq.heapify(self._completion_heap)

                        if self._event_heap:
                            self._event_heap = [
                                ev
                                for ev in self._event_heap
                                if not (
                                    ev[2] == "op_complete" and ev[3] == (j_r, o_r, m_sel)
                                )
                            ]
                            heapq.heapify(self._event_heap)

                    # Register the emergency job's first operation as an
                    # interrupted candidate on any available machines.
                    valid: List[Tuple[int, float]] = []
                    for m_id in cand_machines:
                        m = self.machines.get(int(m_id))
                        if m is None:
                            continue
                        mid = int(m_id)
                        if mid in self.broken_machines:
                            continue
                        if 0 <= mid < len(self.machine_busy_until) and self.machine_busy_until[mid] > t + 1e-9:
                            continue
                        pt = first_op.proc_time.get(mid)
                        if pt is None:
                            continue
                        valid.append((mid, float(pt)))

                    if valid:
                        self.interrupted_ops.append((job_id, first_op_idx, valid))
            elif ev_type == "job_cancel":
                job_id = int(ev_info)
                job = self.jobs.get(job_id)
                if job is None:
                    continue
                # Preempt any running operations of this job on machines
                # and record remaining processing time.
                for m_id, (j_r, o_r, e_r) in list(self.machine_status.items()):
                    if j_r != job_id or e_r <= t:
                        continue
                    rem = max(0.0, float(e_r) - float(t))
                    self.interrupted_ops.append((j_r, o_r, [(m_id, rem)]))
                    self._cancel_operation_on_machine(m_id, t)

                    # Remove the corresponding op_complete event(s)
                    if self._event_heap:
                        self._event_heap = [
                            ev
                            for ev in self._event_heap
                            if not (
                                ev[2] == "op_complete" and ev[3] == (j_r, o_r, m_id)
                            )
                        ]
                        heapq.heapify(self._event_heap)

                job.status = "cancelled"
                job.cancellation_time = float(ev_time)
                for op in job.ops:
                    if op.status not in ("done", "cancelled"):
                        op.status = "cancelled"
            elif ev_type == "machine_break":
                m_id = int(ev_info)
                self.broken_machines.add(m_id)
                machine = self.machines.get(m_id)
                if machine is not None:
                    machine.is_broken = True

                current = self.machine_status.get(m_id)
                if current is not None:
                    j_r, o_r, e_r = current
                    if e_r > t:
                        rem = max(0.0, float(e_r) - float(t))
                        self.interrupted_ops.append((j_r, o_r, [(m_id, rem)]))

                        # Mark the operation as waiting again so it can be rescheduled later.
                        job_r = self.jobs.get(j_r)
                        if job_r is not None and 0 <= o_r < len(job_r.ops):
                            op_r = job_r.ops[o_r]
                            if op_r.status == "processing":
                                op_r.status = "waiting"
                                job_r.current_op_index = min(job_r.current_op_index, o_r)
                                if job_r.status != "cancelled":
                                    job_r.status = "waiting"

                        self._cancel_operation_on_machine(m_id, t)

                        # Remove any op_complete event for this (job, op, machine)
                        if self._event_heap:
                            self._event_heap = [
                                ev
                                for ev in self._event_heap
                                if not (
                                    ev[2] == "op_complete" and ev[3] == (j_r, o_r, m_id)
                                )
                            ]
                            heapq.heapify(self._event_heap)
            elif ev_type == "machine_repair":
                m_id = int(ev_info)
                self.broken_machines.discard(m_id)
                machine = self.machines.get(m_id)
                if machine is not None:
                    machine.is_broken = False
            elif ev_type == "op_complete":
                jid, op_idx, m_id = ev_info
                jid = int(jid)
                m_id = int(m_id)

                job = self.jobs.get(jid)
                if job is None:
                    continue
                if op_idx < 0 or op_idx >= len(job.ops):
                    continue
                op = job.ops[op_idx]
                if op.status != "processing":
                    continue

                op.status = "done"
                op.end_time = float(ev_time)

                # Update job progress and free the machine
                self.job_progress[jid] = op_idx + 1

                current = self.machine_status.get(m_id)
                if current is not None and current[0] == jid and current[1] == op_idx:
                    self.machine_status.pop(m_id, None)

                # Move job pointer to next unfinished & not-cancelled op
                k = 0
                while k < len(job.ops) and job.ops[k].status in ("done", "cancelled"):
                    k += 1
                job.current_op_index = k

                if k >= len(job.ops):
                    job.status = "completed" if job.status != "cancelled" else "cancelled"
                    job.completion_time = float(ev_time)
                else:
                    job.status = "waiting" if job.status != "cancelled" else "cancelled"

    def _cancel_operation_on_machine(self, machine_id: int, t: float) -> None:
        """Cancel the current operation on the given machine at time t.

        This updates machine and job busy times and clears machine_status
        for that machine. Operation/job status changes are handled by the
        caller (e.g., job_cancel, machine_break).
        """

        machine = self.machines.get(int(machine_id))
        if machine is None:
            return

        current = self.machine_status.pop(int(machine_id), None)
        if current is not None:
            job_id, op_index, end_time = current
            self.job_busy_until[job_id] = float(t)

            job = self.jobs.get(job_id)
            if job is not None and 0 <= op_index < len(job.ops):
                op = job.ops[op_index]
                segs = getattr(op, "segments", None)
                if segs:
                    for idx in range(len(segs) - 1, -1, -1):
                        s, e, m = segs[idx]
                        try:
                            s_f = float(s)
                            e_f = float(e)
                            m_int = int(m)
                        except Exception:
                            continue
                        if m_int != int(machine_id):
                            continue
                        if abs(e_f - float(end_time)) > 1e-9:
                            continue
                        new_end = float(t)
                        if new_end < s_f:
                            new_end = s_f
                        segs[idx] = (s_f, new_end, m_int)
                        break

        machine.available_from = float(t)
        mid = machine.machine_id
        if 0 <= mid < len(self.machine_busy_until):
            self.machine_busy_until[mid] = float(t)

    def _process_completions_until(self, t: float) -> None:
        """Finalize any operations whose completion time <= t."""

        while self._completion_heap and self._completion_heap[0].time <= t + 1e-9:
            rec = heapq.heappop(self._completion_heap)
            job = self.jobs.get(rec.job_id)
            if job is None:
                continue
            if rec.op_index >= len(job.ops):
                continue
            op = job.ops[rec.op_index]
            if op.status != "processing":
                continue
            op.status = "done"
            op.end_time = float(rec.time)

            self.job_progress[rec.job_id] = rec.op_index + 1

            m_id = rec.machine_id
            current = self.machine_status.get(m_id)
            if current is not None and current[0] == rec.job_id and current[1] == rec.op_index:
                self.machine_status.pop(m_id, None)

            # Move job pointer to next unfinished & not-cancelled op
            k = 0
            while k < len(job.ops) and job.ops[k].status in ("done", "cancelled"):
                k += 1
            job.current_op_index = k

            if k >= len(job.ops):
                job.status = "completed" if job.status != "cancelled" else "cancelled"
                job.completion_time = float(rec.time)
            else:
                job.status = "waiting" if job.status != "cancelled" else "cancelled"

    def _update_job_readiness(self) -> None:
        """Update job.current_op_index and mark ready operations as waiting."""

        for job in self.jobs.values():
            if job.status == "cancelled":
                continue
            if job.release_time > self.time:
                continue

            # Find first unfinished op
            k = 0
            while k < len(job.ops) and job.ops[k].status in ("done", "cancelled"):
                k += 1
            job.current_op_index = k

            if k >= len(job.ops):
                # All operations finished or cancelled
                if job.status not in ("completed", "cancelled"):
                    job.status = "completed"
                continue

            op = job.ops[k]
            if op.status in ("not_arrived", "waiting"):
                op.status = "waiting"
                if job.status not in ("processing", "completed"):
                    job.status = "waiting"

    def get_ready_operations(self) -> List[JMSOperation]:
        """Return operations that are ready to be scheduled at current time.

        This follows EnvState-style semantics:
        - interrupted_ops are treated as high-priority ready candidates when
          at least one of their recorded machines is currently available;
        - normal jobs become ready when they have arrived, are not cancelled
          or busy, and have at least one available candidate machine.
        """

        t = self.time
        self._update_job_readiness()

        ready: List[JMSOperation] = []
        seen: set[Tuple[int, int]] = set()

        # 1) Operations resumed from interruptions
        for j, o, cand in self.interrupted_ops:
            job = self.jobs.get(j)
            if job is None or job.status == "cancelled":
                continue
            if job.release_time > t:
                continue
            if self.job_busy_until.get(j, job.release_time) > t + 1e-9:
                continue
            if o < 0 or o >= len(job.ops):
                continue

            # Mark this (job, op) as "seen" regardless of whether it has
            # an available machine at this moment. This mirrors EnvState,
            # where any (job, op) present in interrupted_ops is excluded
            # from the normal-arrived-jobs branch, even if its current
            # candidate set is empty.
            seen.add((j, o))

            # Require at least one available machine among the recorded
            # candidates for this interrupted operation to be considered
            # actually ready.
            if not any(self._machine_available(int(m), t) for m, _ in cand):
                continue

            op = job.ops[o]
            if op.status in ("done", "cancelled"):
                continue
            ready.append(op)

        # 2) Normal next operations for arrived, non-busy jobs.
        #
        # IMPORTANT: EnvState.ready_ops only considers jobs that appear in
        # dynamic_events["job_arrival"]. Emergency-only jobs that are
        # introduced via job_emergency + emergency_static (and thus have no
        # job_arrival entry) become ready *only* via the interrupted_ops
        # mechanism. To match that behaviour, we restrict this loop to jobs
        # present in job_arrival_map. This prevents emergency-only jobs like
        # job 6 in GEN-Bench-Small/instance_20 from appearing as normal
        # ready operations after machines are repaired, which would diverge
        # from EnvState semantics.
        for job in self.jobs.values():
            j = job.job_id

            # Skip jobs that never had a dynamic job_arrival event. These
            # include emergency-only jobs; they are handled via
            # interrupted_ops instead.
            if j not in self.job_arrival_map:
                continue
            if job.status == "cancelled":
                continue
            if job.release_time > t:
                continue
            if self.job_busy_until.get(j, job.release_time) > t + 1e-9:
                continue

            o = job.current_op_index
            if o >= len(job.ops):
                continue
            if (j, o) in seen:
                # This (job, op) is already represented via interrupted_ops
                # above; do not add it again as a normal ready operation.
                continue

            op = job.ops[o]
            if op.status in ("done", "cancelled"):
                continue

            # Require at least one available candidate machine
            if not op.candidates:
                continue
            if not any(self._machine_available(int(m), t) for m in op.candidates):
                continue

            if op.status in ("not_arrived", "waiting"):
                op.status = "waiting"
                if job.status not in ("processing", "completed"):
                    job.status = "waiting"

            ready.append(op)

        return ready

    # ------------------------------------------------------------------
    # Gantt reconstruction
    # ------------------------------------------------------------------
    def get_gantt(self) -> List[Dict[str, Any]]:
        """Return a simple Gantt-like list of scheduled operations.

        Each record contains:

        - job_id: int
        - op_index: int (0-based, matching JMSOperation.op_index)
        - machine_id: int
        - start_time: float
        - end_time: float
        """

        records: List[Dict[str, Any]] = []
        for job in self.jobs.values():
            jid = int(getattr(job, "job_id", 0))
            for op in job.ops:
                # Only include fully completed operations. EnvState-side
                # Gantt comparisons filter to segments with status
                # "completed"; here the equivalent terminal state is
                # JMSOperation.status == "done". This avoids counting
                # partially executed but later cancelled/preempted ops.
                if getattr(op, "status", None) != "done":
                    continue
                segments = getattr(op, "segments", None)
                if segments:
                    for seg_start, seg_end, seg_mid in segments:
                        try:
                            s = float(seg_start)
                            e = float(seg_end)
                            m_id = int(seg_mid)
                        except Exception:
                            continue
                        if e <= s:
                            continue
                        rec = {
                            "job_id": jid,
                            "op_index": int(op.op_index),
                            "machine_id": m_id,
                            "start_time": s,
                            "end_time": e,
                        }
                        records.append(rec)
                else:
                    if op.start_time is None or op.end_time is None:
                        continue
                    mid = getattr(op, "machine_id", None)
                    if mid is None:
                        continue
                    try:
                        rec = {
                            "job_id": jid,
                            "op_index": int(op.op_index),
                            "machine_id": int(mid),
                            "start_time": float(op.start_time),
                            "end_time": float(op.end_time),
                        }
                    except Exception:
                        continue
                    records.append(rec)

        records.sort(key=lambda r: (r["start_time"], r["job_id"], r["op_index"]))
        return records


def load_jms_like_instance(path: Path) -> Dict[str, Any]:
    """Load a single-line JMS/GEN-Bench-style JSONL instance from disk."""

    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty instance file: {path}")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JMS/GEN-Bench JSON from {path}: {exc}") from exc
    return obj
