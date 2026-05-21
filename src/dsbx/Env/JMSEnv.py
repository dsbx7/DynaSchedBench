from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dsbx.Sim.JMSSim import JMSSim, JMSOperation, load_jms_like_instance

PathLike = Union[str, Path]


class JMSRawEnv:
    """Environment wrapper around :class:`JMSSim`.

    This environment is dedicated to raw JMS/GEN-Bench JSONL instances
    under ``data/jms`` and ``data/genbench``. It does **not** use
    :class:`dsbx.Gen.InputModel` or ``runs/*`` directories and is
    therefore semantically separated from :class:`DynaSchedEnv`.
    """

    def __init__(self, sim: JMSSim) -> None:
        self._sim = sim

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_jsonl(cls, path: PathLike) -> "JMSRawEnv":
        """Build an environment directly from a JMS/GEN-Bench JSONL file."""

        p = Path(path)
        payload = load_jms_like_instance(p)
        sim = JMSSim(payload)
        return cls(sim)

    # ------------------------------------------------------------------
    # Core API (reset / step / legal_actions)
    # ------------------------------------------------------------------
    def reset(self) -> Dict[str, Any]:
        """Reset simulator and return initial observation."""

        self._sim.reset()
        return self._build_observation()

    def step(self, action: Dict[str, Any]) -> tuple[Dict[str, Any], float, bool, Dict[str, Any]]:
        """Apply a scheduling action and return (obs, reward, done, info).

        The action format is::

            {"job_id": int | str, "machine_id": int}

        Reward is zero by default; downstream code can compute metrics from
        the final trajectory if needed.
        """

        job_id_raw = action.get("job_id")
        if job_id_raw is None:
            raise ValueError("Action must contain 'job_id'")
        try:
            job_id = int(job_id_raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid job_id in action: {job_id_raw!r}") from exc

        machine_id_raw = action.get("machine_id")
        if machine_id_raw is None:
            raise ValueError("Action must contain 'machine_id'")
        try:
            machine_id = int(machine_id_raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid machine_id in action: {machine_id_raw!r}") from exc

        self._sim.step_action(job_id=job_id, machine_id=machine_id)
        self._sim.advance_to_next_decision_point()

        obs = self._build_observation()
        done = self._sim.is_finished()
        reward = 0.0
        info: Dict[str, Any] = {}
        return obs, reward, done, info

    def legal_actions(self) -> List[Dict[str, Any]]:
        """Return all currently legal (job, machine) assignments."""

        t = self._sim.time
        ready_ops = self._sim.get_ready_operations()
        actions: List[Dict[str, Any]] = []

        for op in ready_ops:
            assert isinstance(op, JMSOperation)
            for m_id in op.candidates:
                try:
                    mid = int(m_id)
                except Exception:
                    continue

                # EnvState-style availability: machine must not be broken and
                # must not be busy past current time.
                try:
                    available = self._sim._machine_available(mid, float(t))  # type: ignore[attr-defined]
                except Exception:
                    # Fallback: if helper is not available for some reason,
                    # fall back to a simple non-broken check.
                    m = self._sim.machines.get(mid)
                    available = bool(m is not None and not m.is_down(float(t)))

                if not available:
                    continue

                actions.append({"job_id": op.job_id, "machine_id": mid})

        return actions

    def advance_if_idle(self) -> Dict[str, Any]:
        """Advance time to the next decision point when no ops are ready."""

        self._sim.advance_to_next_decision_point()
        return self._build_observation()

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    @property
    def time(self) -> float:
        return float(self._sim.time)

    def done(self) -> bool:
        return self._sim.is_finished()

    def get_light_state(self) -> Dict[str, Any]:
        sim = self._sim
        if sim is None:
            raise RuntimeError("Environment must be reset() before calling get_light_state().")

        t = float(sim.time)

        jobs_out: Dict[str, Any] = {}
        for job_id, job in sim.jobs.items():
            jid_str = str(job_id)

            ops_info: List[Dict[str, Any]] = []
            total_work = 0.0
            for op in job.ops:
                if op.proc_time:
                    base_pt = float(min(op.proc_time.values()))
                else:
                    base_pt = 0.0
                total_work += base_pt
                ops_info.append(
                    {
                        "index": int(op.op_index),
                        "machine_group": str(op.op_index),
                        "proc_time_nominal": base_pt,
                        "proc_time_realized": base_pt,
                    }
                )

            k = int(job.current_op_index)
            remaining_work = 0.0
            if 0 <= k <= len(job.ops):
                for op in job.ops[k:]:
                    if op.proc_time and op.status not in ("done", "cancelled"):
                        remaining_work += float(min(op.proc_time.values()))

            jobs_out[jid_str] = {
                "release_time": float(job.release_time),
                "due_date": 0.0,
                "total_ops": len(job.ops),
                "total_work_content": total_work,
                "remaining_work_content": remaining_work,
                "priority": 0.0,
                "ops": ops_info,
                "current_op_index": k,
            }

        machines_out: Dict[str, Any] = {}
        for m_id, m in sim.machines.items():
            mid = int(m_id)
            if 0 <= mid < len(sim.machine_busy_until):
                available_from = float(sim.machine_busy_until[mid])
            else:
                available_from = float(m.available_from)

            # EnvState-style workload: prefer JMSSim.machine_workload if present,
            # which tracks total assigned processing time per machine. This
            # matches EnvState.work_load semantics used by the LWL rule.
            busy_time: float
            try:
                mw = getattr(sim, "machine_workload", None)
                if isinstance(mw, list) and 0 <= mid < len(mw):
                    busy_time = float(mw[mid])
                else:
                    # Fallback: approximate by remaining busy horizon.
                    busy_time = max(0.0, available_from - t)
            except Exception:
                busy_time = max(0.0, available_from - t)

            machines_out[str(mid)] = {
                "available_from": available_from,
                "speed": 1.0,
                "busy_time": busy_time,
            }

        return {
            "time": t,
            "jobs": jobs_out,
            "machines": machines_out,
        }

    def get_gantt(self) -> List[Dict[str, Any]]:
        """Return a simple Gantt-like schedule from the underlying simulator.

        If the wrapped JMSSim does not implement ``get_gantt``, an empty
        list is returned.
        """

        sim = self._sim
        if sim is None or not hasattr(sim, "get_gantt"):
            return []
        try:
            return sim.get_gantt()  # type: ignore[no-any-return]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Observation construction
    # ------------------------------------------------------------------
    def _build_observation(self) -> Dict[str, Any]:
        """Build a lightweight observation dict for upstream algorithms."""

        t = float(self._sim.time)
        ready_ops = self._sim.get_ready_operations()

        ready: List[Dict[str, Any]] = []
        for op in ready_ops:
            assert isinstance(op, JMSOperation)
            job = self._sim.jobs.get(op.job_id)
            remaining_ops = 0
            remaining_work = 0.0
            if job is not None:
                if job.current_op_index < len(job.ops):
                    remaining_ops = max(0, len(job.ops) - job.current_op_index)
                    for k in range(job.current_op_index, len(job.ops)):
                        op_k = job.ops[k]
                        if not op_k.proc_time:
                            continue
                        remaining_work += float(min(op_k.proc_time.values()))

            ready.append(
                {
                    "job_id": op.job_id,
                    "operation": op.op_index,
                    "candidate_machines": list(op.candidates),
                    "proc_times": {int(m): float(pt) for m, pt in op.proc_time.items()},
                    "remaining_ops": remaining_ops,
                    "remaining_work": remaining_work,
                }
            )

        machines_obs: Dict[str, Any] = {}
        for m_id, m in self._sim.machines.items():
            machines_obs[str(m_id)] = {
                "available_from": float(m.available_from),
                "down": bool(m.is_down(t)),
            }

        return {
            "time": t,
            "ready_ops": ready,
            "machines": machines_obs,
        }
