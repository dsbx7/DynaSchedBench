from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from dsbx.Sim.JMSSim import JMSSim
from dsbx.Sim.Snapshot import (
    EventSnapshot,
    JobOpSnapshot,
    JobSnapshot,
    MachineScheduleSegmentSnapshot,
    MachineSnapshot,
    Snapshot,
    StabilityStats,
    SystemStats,
)

"""Snapshot adapter for JMSSim driven by JMSBench-style JSONL instances.

This module treats JMSBench JSONL files under ``data/jmsbench`` and
``data/genbench`` as the source of truth and defines DynaSchedBench snapshot
semantics without requiring an ``InputModel``. Job and operation structures,
arrivals, emergency jobs, cancellations, and downtime are determined by the
JSONL content plus JMSSim internal state. Due dates are represented by a large
upper bound to indicate that this problem family does not model due-date
constraints explicitly.

Emergency jobs come from ``JMSSim.emergency_jobs`` and are encoded as
``job.priority = -1.0`` while normal jobs use ``0.0``; the adapter also exposes
``dynamic_scenarios["emergency_priority"] = -0.5``. JMSSim has no machine-local
queues, so ``MachineSnapshot.queue`` is always empty, and queue-length or
waiting-time features are reconstructed from the ready set and time data.
Machine utilization statistics are computed from ``schedule_segments`` with the
same formulas used by ``DynaSchedSim``.
"""


@dataclass
class _CachedStaticInfo:
    num_jobs: int
    num_machines: int
    ops_per_job: List[int]
    proc_time_raw: Dict[str, Dict[str, float]]
    job_arrival_map: Dict[int, float]
    horizon: float


class JMSSimSnapshotAdapter:
    """Build DynaSchedBench Snapshot from a JMSSim instance."""

    def __init__(self, sim: JMSSim) -> None:
        self._sim = sim
        self._static = self._build_static_cache(sim)
        self._prev_snapshot: Optional[Snapshot] = None

    def export_snapshot(self) -> Snapshot:
        sim = self._sim
        st = self._static
        t = float(sim.time)
        prev_t = self._prev_snapshot.time if self._prev_snapshot is not None else t

        # ---------------- Jobs & operations ----------------
        job_snaps: List[JobSnapshot] = []
        segments_by_machine: Dict[int, List[MachineScheduleSegmentSnapshot]] = {}
        emergency_now = set(getattr(sim, "emergency_jobs", set()))

        for jid in sorted(sim.jobs.keys()):
            job = sim.jobs[jid]
            jid_str = str(job.job_id)

            op_snaps: List[JobOpSnapshot] = []
            total_work = 0.0
            remaining_work = 0.0

            for op in job.ops:
                if op.proc_time:
                    base_pt = float(min(op.proc_time.values()))
                else:
                    base_pt = 0.0
                total_work += base_pt

                remaining_time = 0.0
                if getattr(op, "status", None) not in ("done", "cancelled"):
                    rem_running: Optional[float] = None
                    for m_id, (j_run, o_run, e_run) in getattr(sim, "machine_status", {}).items():
                        if int(j_run) == int(job.job_id) and int(o_run) == int(op.op_index) and float(e_run) > t + 1e-9:
                            rem_running = max(0.0, float(e_run) - t)
                            break

                    rem_interrupted: Optional[float] = None
                    if rem_running is None:
                        for j0, o0, cand in getattr(sim, "interrupted_ops", []):
                            if int(j0) == int(job.job_id) and int(o0) == int(op.op_index):
                                vals = [float(rt) for (_m, rt) in cand]
                                if vals:
                                    rem_interrupted = min(vals)
                                break

                    if rem_running is not None:
                        remaining_time = rem_running
                    elif rem_interrupted is not None:
                        remaining_time = rem_interrupted
                    else:
                        remaining_time = base_pt

                    remaining_work += remaining_time

                op_snaps.append(
                    JobOpSnapshot(
                        op_id=f"{job.job_id}-op{op.op_index}",
                        job_id=jid_str,
                        index=int(op.op_index),
                        machine_group=str(op.op_index),
                        candidate_machines=[str(int(m)) for m in op.candidates],
                        proc_time_nominal=float(base_pt),
                        proc_time_realized=float(base_pt),
                        status=str(getattr(op, "status", "not_arrived")),
                        start_time=float(op.start_time) if op.start_time is not None else None,
                        end_time=float(op.end_time) if op.end_time is not None else None,
                        remaining_time=float(remaining_time),
                        prev_start_time=None,
                        prev_machine_id=None,
                        rework_count=0,
                    )
                )

                mid = getattr(op, "machine_id", None)
                if (
                    mid is not None
                    and getattr(op, "status", None) in ("processing", "done")
                    and op.start_time is not None
                    and op.end_time is not None
                ):
                    m_int = int(mid)
                    seg_list = segments_by_machine.setdefault(m_int, [])
                    seg_list.append(
                        MachineScheduleSegmentSnapshot(
                            start=float(op.start_time),
                            end=float(op.end_time),
                            job_id=jid_str,
                            op_id=f"{job.job_id}-op{op.op_index}",
                            is_frozen=False,
                        )
                    )

            pr_val = -1.0 if job.job_id in emergency_now else 0.0

            job_snaps.append(
                JobSnapshot(
                    job_id=jid_str,
                    family=jid_str,
                    release_time=float(job.release_time),
                    due_date=float(st.horizon),
                    initial_due_date=float(st.horizon),
                    priority=float(pr_val),
                    weight=1.0,
                    status=str(getattr(job, "status", "not_arrived")),
                    current_op_index=int(getattr(job, "current_op_index", 0)),
                    total_ops=len(job.ops),
                    total_work_content=float(total_work),
                    remaining_work_content=float(remaining_work),
                    completion_time=float(job.completion_time) if job.completion_time is not None else None,
                    lateness=None,
                    tardiness=None,
                    cancellation_time=float(job.cancellation_time) if job.cancellation_time is not None else None,
                    ops=op_snaps,
                )
            )

        # ---------------- Machines ----------------
        machine_snaps: List[MachineSnapshot] = []
        broken = set(getattr(sim, "broken_machines", set()))
        ready_ops = sim.get_ready_operations()

        # map for current job/op on each machine
        cur_map: Dict[int, Tuple[int, int]] = {}
        for m_id, (j_run, o_run, e_run) in getattr(sim, "machine_status", {}).items():
            if float(e_run) > t + 1e-9:
                cur_map[int(m_id)] = (int(j_run), int(o_run))

        for m_id in sorted(sim.machines.keys()):
            mch = sim.machines[m_id]
            mid_int = int(getattr(mch, "machine_id", m_id))

            available_from = float(getattr(mch, "available_from", 0.0))
            mbu = getattr(sim, "machine_busy_until", None)
            if isinstance(mbu, list) and 0 <= mid_int < len(mbu):
                try:
                    available_from = float(mbu[mid_int])
                except Exception:
                    pass

            if mid_int in broken:
                status = "down_breakdown"
            else:
                try:
                    busy_now = not sim._machine_available(mid_int, float(t))  # type: ignore[attr-defined]
                except Exception:
                    busy_now = False
                status = "busy" if busy_now else "idle"

            cur_job_id: Optional[str] = None
            cur_op_id: Optional[str] = None
            if mid_int in cur_map:
                j_run, o_run = cur_map[mid_int]
                cur_job_id = str(j_run)
                cur_op_id = f"{j_run}-op{o_run}"

            segs = segments_by_machine.get(mid_int, [])

            machine_snaps.append(
                MachineSnapshot(
                    machine_id=str(mid_int),
                    group=str(mid_int),
                    speed=1.0,
                    status=status,
                    available_from=available_from,
                    current_job_id=cur_job_id,
                    current_op_id=cur_op_id,
                    queue=[],
                    schedule_segments=segs,
                )
            )

        # ---------------- Pending events (none for JMSSim) ----------------
        pending: List[EventSnapshot] = []

        # ---------------- SystemStats ----------------
        num_jobs_total = len(sim.jobs)
        num_jobs_arrived = 0
        num_jobs_completed = 0
        num_jobs_cancelled = 0
        wip_count = 0

        for job in sim.jobs.values():
            if float(getattr(job, "release_time", 0.0)) <= t + 1e-9:
                num_jobs_arrived += 1
            status = str(getattr(job, "status", "not_arrived"))
            if status == "completed":
                num_jobs_completed += 1
            if status == "cancelled":
                num_jobs_cancelled += 1
            if status in ("waiting", "processing", "not_arrived"):
                wip_count += 1

        queue_length_by_machine: Dict[str, int] = {}
        for op in ready_ops:
            for m in op.candidates:
                mid = str(int(m))
                queue_length_by_machine[mid] = queue_length_by_machine.get(mid, 0) + 1
        queue_length_by_group: Dict[str, int] = dict(queue_length_by_machine)

        utilization_by_machine: Dict[str, float] = {}
        if t > 0.0:
            busy_by_machine: Dict[int, float] = {}
            for mid_int, segs in segments_by_machine.items():
                busy = 0.0
                for seg in segs:
                    try:
                        s_start = float(seg.start)
                        s_end = float(seg.end)
                    except Exception:
                        continue
                    if s_end > s_start:
                        busy += s_end - s_start
                busy_by_machine[mid_int] = busy

            for mid_int in sim.machines.keys():
                busy = float(busy_by_machine.get(int(mid_int), 0.0))
                utilization_by_machine[str(int(mid_int))] = busy / float(t)
        else:
            for mid_int in sim.machines.keys():
                utilization_by_machine[str(int(mid_int))] = 0.0
        utilization_by_group: Dict[str, float] = dict(utilization_by_machine)

        system_stats = SystemStats(
            num_jobs_total=num_jobs_total,
            num_jobs_arrived=num_jobs_arrived,
            num_jobs_completed=num_jobs_completed,
            num_jobs_cancelled=num_jobs_cancelled,
            wip_count=wip_count,
            queue_length_by_machine=queue_length_by_machine,
            queue_length_by_group=queue_length_by_group,
            utilization_by_machine=utilization_by_machine,
            utilization_by_group=utilization_by_group,
            num_reschedules=0,
            last_schedule_change_time=float(prev_t),
            event_counters={},
        )

        stability_stats = self._compute_stability_stats(self._prev_snapshot, job_snaps)

        snap = Snapshot(
            time=t,
            prev_decision_time=float(prev_t),
            horizon=float(st.horizon),
            lookahead_horizon=float(st.horizon),
            scenario_id=None,
            seed=None,
            config_hash=None,
            plant={"num_jobs": st.num_jobs, "num_machines": st.num_machines},
            scale={"horizon": float(st.horizon)},
            targets={},
            dynamics={},
            dynamic_scenarios={"emergency_priority": -0.5},
            jobs=job_snaps,
            machines=machine_snaps,
            pending_events=pending,
            system_stats=system_stats,
            stability_stats=stability_stats,
        )

        self._prev_snapshot = snap
        return snap

    @staticmethod
    def _build_static_cache(sim: JMSSim) -> _CachedStaticInfo:
        static = getattr(sim, "_static_info")  # type: ignore[attr-defined]
        dyn = getattr(sim, "_dynamic_events")  # type: ignore[attr-defined]

        num_jobs = int(static["num_jobs"])
        num_machines = int(static["num_machines"])
        ops_per_job = list(static["ops_per_job"])
        proc_time_raw: Dict[str, Dict[str, float]] = static["proc_time"]

        job_arrival_map: Dict[int, float] = {
            int(j): float(t) for j, t in dyn.get("job_arrival", [])
        }

        # Horizon estimation should mirror the JMSBench generator logic so that
        # time scales for JMSSim-based instances are comparable to those used
        # when constructing data/jmsbench. In particular, we approximate a
        # conservative lower bound based on per-job minimal work and the
        # aggregate minimal work across all jobs:
        #
        #   - total_min_work: sum of minimal proc_time for every operation
        #   - job_work[j]:    minimal total work content of job j
        #   - lb = max(max(job_work), total_min_work / num_machines)
        #   - horizon = factor * lb  (with factor ~= 1.2 as in the generator)
        #
        # This prevents snapshot.horizon from becoming unrealistically large
        # on JMSSim backends (which would otherwise make DAN's per-episode
        # hard_time_limit extremely loose and lead to very long episodes).

        total_min_work = 0.0
        job_work: List[float] = []

        for j in range(1, num_jobs + 1):
            jw = 0.0
            n_ops = int(ops_per_job[j - 1])
            for o in range(1, n_ops + 1):
                key = f"({j},{o})"
                pt_map = proc_time_raw.get(key, {})
                if not pt_map:
                    continue
                jw += float(min(pt_map.values()))
            job_work.append(jw)
            total_min_work += jw

        if job_work:
            num_machines_f = float(max(1, num_machines))
            lb = max(max(job_work), total_min_work / num_machines_f)
        else:
            # Fallback: no explicit jobs/ops; keep the original total_min_work
            lb = float(total_min_work)

        # Mirror the 1.2 factor used in the JMS-like instance generator so that
        # horizon represents a modest multiple of the theoretical lower bound.
        factor = 1.2
        horizon = max(factor * lb, 1.0)

        return _CachedStaticInfo(
            num_jobs=num_jobs,
            num_machines=num_machines,
            ops_per_job=ops_per_job,
            proc_time_raw=proc_time_raw,
            job_arrival_map=job_arrival_map,
            horizon=float(horizon),
        )

    @staticmethod
    def _compute_stability_stats(
        prev_snapshot: Optional[Snapshot], current_jobs: List[JobSnapshot]
    ) -> StabilityStats:
        if prev_snapshot is None:
            return StabilityStats(
                changed_ops_ratio=0.0,
                avg_start_time_shift=0.0,
                max_start_time_shift=0.0,
            )

        prev_map: Dict[Tuple[str, int], Optional[float]] = {}
        for j in prev_snapshot.jobs:
            for op in j.ops:
                prev_map[(op.job_id, op.index)] = op.start_time

        diffs: List[float] = []
        changed = 0
        total = 0
        for j in current_jobs:
            for op in j.ops:
                key = (op.job_id, op.index)
                if key not in prev_map:
                    continue
                total += 1
                prev_start = prev_map[key]
                curr_start = op.start_time
                if prev_start is None or curr_start is None:
                    continue
                dt = abs(curr_start - prev_start)
                if dt > 1e-9:
                    changed += 1
                    diffs.append(dt)

        if not diffs or total == 0:
            return StabilityStats(
                changed_ops_ratio=0.0,
                avg_start_time_shift=0.0,
                max_start_time_shift=0.0,
            )

        return StabilityStats(
            changed_ops_ratio=changed / max(1, total),
            avg_start_time_shift=sum(diffs) / len(diffs),
            max_start_time_shift=max(diffs),
        )


@dataclass
class _ReadyOpView:
    job_id: str
    machine_group: str
    candidate_machines: List[str]


class JMSSimBackend:
    def __init__(self, sim: JMSSim) -> None:
        self._sim = sim
        self._adapter = JMSSimSnapshotAdapter(sim)

    def reset(self) -> Snapshot:
        self._sim.reset()
        return self._adapter.export_snapshot()

    def step_action(self, action: Dict[str, Any]) -> Snapshot:
        job_id_raw = action.get("job_id")
        if job_id_raw is None:
            raise ValueError("Action must contain 'job_id'")

        machine_id_raw = action.get("machine_id")
        if machine_id_raw is None:
            candidates = action.get("machine_candidates") or []
            if not candidates:
                raise ValueError("Action must contain 'machine_id' or 'machine_candidates'")
            machine_id_raw = candidates[0]

        try:
            job_id = int(job_id_raw)
            machine_id = int(machine_id_raw)
        except Exception as exc:
            raise ValueError(f"Invalid job_id/machine_id in action: {action!r}") from exc

        self._sim.step_action(job_id=job_id, machine_id=machine_id)
        return self._adapter.export_snapshot()

    def advance_to_next_decision_point(self) -> Snapshot:
        self._sim.advance_to_next_decision_point()
        return self._adapter.export_snapshot()

    def get_ready_operations(self) -> List[_ReadyOpView]:
        ready: List[_ReadyOpView] = []
        sim = self._sim
        t_now = float(getattr(sim, "time", 0.0))

        for op in sim.get_ready_operations():
            jid_str = str(getattr(op, "job_id", ""))
            group = str(getattr(op, "op_index", 0))

            raw_cands = list(getattr(op, "candidates", []) or [])
            filtered: List[str] = []
            for m in raw_cands:
                try:
                    mid = int(m)
                except Exception:
                    continue

                available = True
                try:
                    available = bool(sim._machine_available(mid, t_now))  # type: ignore[attr-defined]
                except Exception:
                    try:
                        broken = getattr(sim, "broken_machines", set())
                        if isinstance(broken, set) and mid in broken:
                            available = False
                        else:
                            mbu = getattr(sim, "machine_busy_until", None)
                            if isinstance(mbu, list) and 0 <= mid < len(mbu):
                                try:
                                    available = float(mbu[mid]) <= t_now + 1e-9
                                except Exception:
                                    available = True
                    except Exception:
                        available = True

                if not available:
                    continue
                filtered.append(str(mid))

            if not filtered:
                continue

            ready.append(
                _ReadyOpView(
                    job_id=jid_str,
                    machine_group=group,
                    candidate_machines=filtered,
                )
            )

        return ready

    def export_snapshot(self) -> Snapshot:
        return self._adapter.export_snapshot()

    def inject_external_event(self, *, kind: str, ev_id: Any, time: Optional[float] = None) -> None:
        try:
            self._sim.add_external_event(kind=str(kind), ev_id=ev_id, time=time)
        except Exception as exc:
            raise

    def inject_external_events(self, events: List[Dict[str, Any]]) -> None:
        self._sim.add_external_events(events)

    def export_light_state(self) -> Dict[str, Any]:
        try:
            from dsbx.Env.JMSEnv import JMSRawEnv  # type: ignore
        except Exception:
            return {}

        env = JMSRawEnv(self._sim)  # type: ignore[call-arg]
        try:
            state = env.get_light_state()
        except Exception:
            return {}
        if isinstance(state, dict):
            return state
        return {}

    def get_gantt(self) -> List[Dict[str, Any]]:
        """Return a simple Gantt-like view delegated to the underlying JMSSim.

        This exposes JMSSim.get_gantt() to callers that only see the
        JMSSimBackend (e.g., DynaSchedEnv and LLMCoder runners).
        """

        sim = self._sim
        try:
            data = sim.get_gantt()  # type: ignore[assignment]
        except Exception:
            return []
        if isinstance(data, list):
            return list(data)
        return []

    def get_action_timing(self, action: Dict[str, Any]) -> Dict[str, Any]:
        job_id_raw = action.get("job_id")
        machine_id_raw = action.get("machine_id")
        if job_id_raw is None or machine_id_raw is None:
            return {}

        try:
            job_id = int(job_id_raw)
            machine_id = int(machine_id_raw)
        except Exception:
            return {}

        sim = self._sim
        job = sim.jobs.get(job_id)
        machine = sim.machines.get(machine_id)
        if job is None or machine is None:
            return {}

        t_now = float(sim.time)
        base_start = max(t_now, float(job.release_time), float(machine.available_from))

        k = int(getattr(job, "current_op_index", 0))
        if k < 0 or k >= len(job.ops):
            return {}
        op = job.ops[k]

        pt_val = op.proc_time.get(int(machine_id))
        if pt_val is None:
            if op.proc_time:
                pt_val = min(op.proc_time.values())
            else:
                pt_val = 0.0
        base_pt = float(pt_val)

        remaining_pt: Optional[float] = None
        for j0, o0, cand in getattr(sim, "interrupted_ops", []):
            if int(j0) == job_id and int(o0) == op.op_index:
                for m0, rt in cand:
                    if int(m0) == machine_id and remaining_pt is None:
                        remaining_pt = float(rt)
                break

        p = remaining_pt if remaining_pt is not None else base_pt
        start = machine.first_non_overlapping_start(base_start, p)
        end = start + p

        return {
            "job_id": job_id,
            "op_index": int(op.op_index),
            "machine_id": machine_id,
            "start_time": float(start),
            "end_time": float(end),
            "proc_time_raw": float(base_pt),
            "machine_speed": 1.0,
            "proc_time_effective": float(p),
        }

    def estimate_action_score(self, action: Dict[str, Any]) -> float:
        info = self.get_action_timing(action)
        try:
            end_t = float(info.get("end_time", 0.0))
        except Exception:
            end_t = 0.0
        return -end_t

    def quick_rollout_score(self, action: Dict[str, Any], steps: int = 1) -> float:
        return self.estimate_action_score(action)
