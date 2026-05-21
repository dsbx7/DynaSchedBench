from __future__ import annotations

import json

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, TextIO

from loguru import logger

from dsbx.Gen import (
    InputModel,
    load_input_model,
    SeedManager,
    FastPathConstructor,
)
from dsbx.Sim.Simulator import DynaSchedSim
from dsbx.Sim.JMSSim import JMSSim, load_jms_like_instance
from dsbx.Sim.JMSSnapshotAdapter import JMSSimBackend
from dsbx.Sim.Events import Event, ArrivalEvent
from dsbx.Sim.Snapshot import Snapshot
from dsbx.Eval import StepRecord, Trajectory
from dsbx.Eval.Trajectory import StaticContext


PathLike = Union[str, Path]


class DynaSchedEnv:
    """Single-agent environment wrapper around :class:`DynaSchedSim`.
    
    The wrapper exposes an observation/action interface compatible with the
    scheduler stack: observations contain ``time``, ``ready_ops``, and
    ``machines``; legal actions contain ``job_id``, ``machine_group``, and
    ``machine_candidates`` and may include a concrete ``machine_id`` at
    execution time. Heuristic, RL, and LLM schedulers can run directly on this
    environment, while the environment records a :class:`Trajectory` for later
    evaluation and visualization.
    """

    def __init__(
        self,
        model: Optional[InputModel] = None,
        *,
        events: Optional[List[Event]] = None,
        auto_generate_events: bool = True,
        track_trajectory: bool = True,
        traj_stream_path: Optional[PathLike] = None,
        sim_backend: Optional[Any] = None,
    ) -> None:
        """Construct a DynaSchedEnv.

        By default, the environment requires ``model`` plus ``events`` and uses
        :class:`DynaSchedSim` as the backend. When ``sim_backend`` is provided,
        the environment uses that external backend directly, such as
        :class:`JMSSimBackend`; in that case ``model`` may be ``None`` and no
        event-generation logic is invoked.
        """

        if sim_backend is None and model is None:
            raise ValueError("DynaSchedEnv: model must be provided when sim_backend is None.")

        self.model = model
        self._events: Optional[List[Event]] = list(events) if events is not None else None
        self.auto_generate_events = auto_generate_events

        # When sim_backend is provided, we treat it as an already-constructed
        # simulator backend (e.g. JMSSimBackend) and never overwrite it inside
        # reset(); otherwise we lazily construct DynaSchedSim on each reset.
        self._sim = sim_backend  # type: ignore[assignment]
        self._use_external_backend: bool = sim_backend is not None
        self._track_trajectory: bool = bool(track_trajectory)
        self._trajectory: Trajectory = Trajectory(steps=[])
        self._traj_stream_path: Optional[Path] = Path(traj_stream_path) if traj_stream_path is not None else None
        self._traj_stream_fp: Optional[TextIO] = None
        self._traj_buffer: List[Dict[str, Any]] = []
        self._traj_buffer_limit: int = 500
        self._traj_step_count: int = 0
        self._traj_flush_count: int = 0
        self._traj_final_written: bool = False
        self._last_time: float = 0.0
        self._routing: Dict[Any, Any] = {}
        self._static_emergency_jobs: set[str] = set()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_json(cls, path: PathLike, *, auto_generate_events: bool = True) -> "DynaSchedEnv":
        """Build an environment from a JSON configuration file.

        This mirrors the DynaSchedBench generation workflow, but keeps
        everything in memory instead of writing artifacts to disk.
        """

        model = load_input_model(Path(path))
        return cls(model, events=None, auto_generate_events=auto_generate_events)

    @classmethod
    def from_jms_jsonl(
        cls,
        path: PathLike,
        *,
        track_trajectory: bool = True,
        traj_stream_path: Optional[PathLike] = None,
    ) -> "DynaSchedEnv":
        """Build an environment backed by JMSSim from a JMS/GEN-Bench JSONL file.

        This constructor reads a JMSBench/GEN-Bench-style JSONL instance with
        ``static_info`` and ``dynamic_events``, builds :class:`JMSSim`, and
        exposes DynaSchedSim-compatible snapshots and legal actions through
        :class:`JMSSimBackend`. This path does not depend on ``InputModel``.
        """

        p = Path(path)
        payload = load_jms_like_instance(p)
        sim = JMSSim(payload)
        backend = JMSSimBackend(sim)

        return cls(
            model=None,
            events=None,
            auto_generate_events=False,
            track_trajectory=track_trajectory,
            traj_stream_path=traj_stream_path,
            sim_backend=backend,
        )

    # ------------------------------------------------------------------
    # Core Env API
    # ------------------------------------------------------------------
    def reset(self) -> Dict[str, Any]:
        """Reset the environment and return the initial observation.

        If no event list has been provided, this will generate one using the
        same generator that backs the CLI (FastPathConstructor), but **without**
        running calibration or exporting artifacts.
        """

        if not getattr(self, "_use_external_backend", False):
            events = self._ensure_events()
            if self.model is None:
                raise RuntimeError("DynaSchedEnv.reset: model is None for DynaSchedSim backend.")
            self._sim = DynaSchedSim(self.model, events)
            snap = self._sim.reset()
        else:
            if self._sim is None:
                raise RuntimeError("DynaSchedEnv.reset: external simulator backend is not initialized.")
            snap = self._sim.reset()  # type: ignore[assignment]

        # Track the last decision time as a scalar to avoid exporting
        # duplicate snapshots purely for reward computation.
        self._last_time = float(getattr(snap, "time", 0.0))

        # Reset in-memory buffer for disk-backed trajectory steps
        self._traj_buffer = []

        # Build static context from the initial snapshot; this will be written
        # once as a header line in the JSONL trajectory file.
        static_ctx = StaticContext(
            scenario_id=getattr(snap, "scenario_id", None),
            seed=getattr(snap, "seed", None),
            config_hash=getattr(snap, "config_hash", None),
            plant=getattr(snap, "plant", None),
            scale=getattr(snap, "scale", None),
            targets=getattr(snap, "targets", None),
            dynamics=getattr(snap, "dynamics", None),
            dynamic_scenarios=getattr(snap, "dynamic_scenarios", None),
        )

        self._trajectory = Trajectory(
            steps=[],
            scenario_id=static_ctx.scenario_id,
            seed=static_ctx.seed,
            config={},
            static_context=static_ctx,
        )
        self._traj_final_written = False

        # If a stream path is configured, write the header and prepare for
        # disk-backed step streaming. Otherwise, fall back to legacy
        # in-memory-only behaviour.
        if self._track_trajectory and self._traj_stream_path is not None:
            # Reset any existing stream file handle
            if self._traj_stream_fp is not None:
                try:
                    self._traj_stream_fp.close()
                except Exception:
                    logger.exception(
                        "Failed to close previous trajectory stream file: {}",
                        self._traj_stream_path,
                    )
                self._traj_stream_fp = None

            self._open_traj_stream_if_needed()
            if self._traj_stream_fp is not None:
                header = {
                    "type": "header",
                    "static_context": static_ctx.model_dump(),
                }
                self._traj_stream_fp.write(
                    json.dumps(header, ensure_ascii=False, indent=None, separators=(",", ":"))
                )
                self._traj_stream_fp.write("\n")
                self._traj_stream_fp.flush()
                # Point the trajectory handle to the backing JSONL file
                self._trajectory._file_path = self._traj_stream_path
                # Mark streamed trajectories as summary-mode so that
                # Trajectory.last_snapshot reads the final_snapshot record
                # instead of attempting to stream full steps.
                self._trajectory._mode = "summary"

        obs_dict = self._snapshot_to_observation(snap)

        # Strip static fields from the in-memory snapshot before recording it
        # as a step; static context is now stored once in the header.
        snap.plant = None
        snap.scale = None
        snap.targets = None
        snap.dynamics = None
        snap.dynamic_scenarios = None

        self._append_traj_step(snap, action=None, info={"type": "reset"})

        return obs_dict

    def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool, Dict[str, Any]]:
        """Apply a scheduling action and return (obs, reward, done, info)."""

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling step().")

        prev_time = float(self._last_time)

        timing_summary: Dict[str, Any] = {}
        try:
            timing_raw = self._sim.get_action_timing(action)
        except Exception:
            timing_raw = None
        if isinstance(timing_raw, dict):
            try:
                timing_summary = {
                    "job_id": timing_raw.get("job_id"),
                    "op_index": timing_raw.get("op_index"),
                    "machine_id": timing_raw.get("machine_id"),
                    "start_time": float(timing_raw.get("start_time", 0.0)),
                    "end_time": float(timing_raw.get("end_time", 0.0)),
                    "proc_time_raw": float(timing_raw.get("proc_time_raw", 0.0)),
                    "machine_speed": float(timing_raw.get("machine_speed", 0.0)),
                    "proc_time_effective": float(timing_raw.get("proc_time_effective", 0.0)),
                }
            except Exception:
                timing_summary = {}

        snap_after_action = self._sim.step_action(action)
        try:
            snap = self._sim.advance_to_next_decision_point()
        except Exception:
            snap = snap_after_action

        curr_time_env = float(getattr(snap, "time", 0.0))
        curr_time_reward = curr_time_env
        if timing_summary:
            try:
                end_t = float(timing_summary.get("end_time", curr_time_env))
                if end_t >= prev_time:
                    curr_time_reward = end_t
            except Exception:
                curr_time_reward = curr_time_env

        self._last_time = curr_time_reward

        obs = self._snapshot_to_observation(snap)
        reward = self._compute_reward(prev_time, curr_time_reward, action)
        done = self._check_done(snap)
        info: Dict[str, Any] = {"snapshot": snap}

        if timing_summary:
            logger.debug(
                "DynaSchedEnv.step: time={} action_timing={} action={}",
                curr_time_env,
                timing_summary,
                action,
            )

        # Strip static fields before recording this step for disk-backed
        # trajectories; the static context is stored once in the header.
        snap.plant = None
        snap.scale = None
        snap.targets = None
        snap.dynamics = None
        snap.dynamic_scenarios = None

        summary_info: Dict[str, Any] = {"reward": reward}
        if timing_summary:
            summary_info["action_timing"] = timing_summary

        self._append_traj_step(snap, action=action, info=summary_info)
        return obs, reward, done, info

    def legal_actions(self) -> List[Dict[str, Any]]:
        """Return all currently legal actions.

        Each action has the form::

            {"job_id": str, "machine_group": str, "machine_candidates": List[str]}

        When executing an action via :meth:`step`, callers may optionally add
        a specific machine choice:

            {"machine_id": str}
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before querying legal_actions().")

        acts: List[Dict[str, Any]] = []
        for op in self._sim.get_ready_operations():
            acts.append(
                {
                    "job_id": op.job_id,
                    "machine_group": op.machine_group,
                    "machine_candidates": list(op.candidate_machines),
                }
            )
        return acts

    def advance_if_idle(self) -> Dict[str, Any]:
        """Advance time to the next decision point when there is no ready op.

        This mirrors `LLMEnv.advance_time_if_idle` behavior and is useful for
        simulators that want to automatically skip idle periods.
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling advance_if_idle().")

        snap = self._sim.advance_to_next_decision_point()

        curr_time = float(getattr(snap, "time", 0.0))
        self._last_time = curr_time

        obs_dict = self._snapshot_to_observation(snap)

        # Strip static fields before recording this step; static context is
        # stored in the header for disk-backed trajectories.
        snap.plant = None
        snap.scale = None
        snap.targets = None
        snap.dynamics = None
        snap.dynamic_scenarios = None

        self._append_traj_step(snap, action=None, info={"type": "advance"})
        return obs_dict

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def get_snapshot(self) -> Snapshot:
        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling get_snapshot().")
        return self._sim.export_snapshot()

    def get_light_state(self) -> Dict[str, Any]:
        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling get_light_state().")
        return self._sim.export_light_state()

    # ------------------------------------------------------------------
    # External event injection (optional; supported by some backends)
    # ------------------------------------------------------------------
    def inject_external_event(self, *, kind: str, ev_id: Any, time: Optional[float] = None) -> None:
        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling inject_external_event().")
        fn = getattr(self._sim, "inject_external_event", None)
        if fn is None:
            raise RuntimeError("Underlying simulator backend does not support external event injection")
        fn(kind=str(kind), ev_id=ev_id, time=time)

    def inject_external_events(self, events: List[Dict[str, Any]]) -> None:
        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling inject_external_events().")
        fn = getattr(self._sim, "inject_external_events", None)
        if fn is not None:
            fn(events)
            return
        for ev in events:
            if not isinstance(ev, dict):
                continue
            self.inject_external_event(kind=str(ev.get("kind")), ev_id=ev.get("id"), time=ev.get("time"))

    def get_trajectory(self) -> Trajectory:
        # Ensure any buffered steps are flushed to disk before returning the
        # trajectory handle. This is a no-op when no stream path is
        # configured.
        try:
            self._flush_traj_buffer()
            self._write_traj_final_snapshot()
        except Exception:
            logger.exception("Failed to finalize trajectory before get_trajectory")
        return self._trajectory

    @property
    def routing(self) -> Dict[Any, Any]:
        try:
            events = self._ensure_events()
        except Exception:
            return self._routing
        mapping: Dict[Any, Any] = {}
        for ev in events:
            if isinstance(ev, ArrivalEvent):
                jid = ev.job_id
                key_str = str(jid)
                mapping[key_str] = list(getattr(ev, "routing", []) or [])
                try:
                    key_int = int(jid)
                    mapping[key_int] = mapping[key_str]
                except Exception:
                    pass
        self._routing = mapping
        return self._routing

    def total_operations(self) -> int:
        """Return the total number of operations across all jobs.

        This helper preserves the ``LLMEnv.total_operations`` semantics so
        upper-level algorithms can estimate an upper bound on scheduling steps
        without inspecting snapshot internals.
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling total_operations().")
        snap = self._sim.export_snapshot()
        return sum(int(j.total_ops) for j in snap.jobs)

    def done(self) -> bool:
        """Check whether the environment has finished all jobs.

        The behavior matches ``LLMEnv.done`` and the internal ``_check_done``:
        all jobs must be completed or cancelled, and no future
        ``ArrivalEvent`` may remain.
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling done().")
        snap = self._sim.export_snapshot()
        return self._check_done(snap)

    def get_next_process_time(self, job_id: str) -> Optional[float]:
        """Return the processing time of the next operation for a given job.

        This method preserves ``LLMEnv.get_next_process_time`` semantics. It is
        mainly used by heuristics such as SPT to rank jobs without modifying
        the underlying state.
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling get_next_process_time().")
        snap = self._sim.export_snapshot()
        for j in snap.jobs:
            if str(j.job_id) != str(job_id):
                continue
            k = int(getattr(j, "current_op_index", 0))
            if k >= int(getattr(j, "total_ops", 0)):
                return None
            try:
                op = j.ops[k]
            except Exception:
                return None
            try:
                return float(getattr(op, "proc_time_realized", op.proc_time_nominal))  # type: ignore[attr-defined]
            except Exception:
                try:
                    return float(getattr(op, "proc_time_nominal", 0.0))
                except Exception:
                    return None
        return None

    def get_remaining_work(self, job_id: str) -> float:
        """Return the remaining work content for a given job.

        This aligns with ``LLMEnv.get_remaining_work`` by returning the total
        processing time of unfinished operations. When available, the method
        prefers ``remaining_work_content`` from the snapshot.
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling get_remaining_work().")
        snap = self._sim.export_snapshot()
        for j in snap.jobs:
            if str(j.job_id) != str(job_id):
                continue
            try:
                return float(getattr(j, "remaining_work_content", 0.0))
            except Exception:
                pass
            try:
                k = int(getattr(j, "current_op_index", 0))
                total = 0.0
                for op in j.ops[k:]:
                    try:
                        pt = float(getattr(op, "proc_time_realized", getattr(op, "proc_time_nominal", 0.0)))
                    except Exception:
                        pt = 0.0
                    total += pt
                return total
            except Exception:
                return 0.0
        return 0.0

    def get_machine_queue_length(self, target: str) -> int:
        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling get_machine_queue_length().")
        snap = self._sim.export_snapshot()
        stats = snap.system_stats
        key = str(target)
        by_m = getattr(stats, "queue_length_by_machine", None) or {}
        if isinstance(by_m, dict) and key in by_m:
            try:
                return int(by_m[key])
            except Exception:
                return 0
        by_g = getattr(stats, "queue_length_by_group", None) or {}
        if isinstance(by_g, dict) and key in by_g:
            try:
                return int(by_g[key])
            except Exception:
                return 0
        return 0

    def get_action_timing(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling get_action_timing().")
        try:
            data = self._sim.get_action_timing(action)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return {}
        return dict(data)

    def estimate_action_score(self, action: Dict[str, Any]) -> float:
        """Delegate to the underlying simulator's estimate_action_score.

        This provides an ``LLMEnv.estimate_action_score``-compatible interface
        so ``LLMPolicy`` can run on the new environment.
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling estimate_action_score().")
        return float(self._sim.estimate_action_score(action))

    def quick_rollout_score(self, action: Dict[str, Any], steps: int = 1) -> float:
        """Delegate to the underlying simulator's quick_rollout_score.

        This matches ``LLMEnv.quick_rollout_score`` semantics: perform a short
        rollout on a local copy and return the negative estimated completion
        time.
        """

        if self._sim is None:
            raise RuntimeError("Environment must be reset() before calling quick_rollout_score().")
        return float(self._sim.quick_rollout_score(action, steps=steps))

    @property
    def static_bottlenecks(self) -> Dict[str, float]:
        if self._sim is None:
            return {}
        try:
            snap = self._sim.export_snapshot()
            stats = snap.system_stats
            data = getattr(stats, "utilization_by_group", None)
            if isinstance(data, dict):
                out: Dict[str, float] = {}
                for k, v in data.items():
                    try:
                        out[str(k)] = float(v)
                    except Exception:
                        continue
                return out
            return {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------
    def _ensure_events(self) -> List[Event]:
        """Generate events if needed and return the in-memory event list."""

        if self._events is not None:
            return list(self._events)

        if not self.auto_generate_events:
            raise RuntimeError("No events provided and auto_generate_events=False.")

        logger.info("DynaSchedEnv: auto-generating events using FastPathConstructor (no calibration).")
        sm = SeedManager(self.model.meta.seed)
        constructor = FastPathConstructor(self.model, sm)
        events = constructor.generate_events()
        self._events = list(events)
        return events

    def _open_traj_stream_if_needed(self) -> None:
        """Lazily open the trajectory stream file if configured."""

        if self._traj_stream_path is None or self._traj_stream_fp is not None:
            return
        try:
            self._traj_stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._traj_stream_fp = self._traj_stream_path.open("w", encoding="utf-8")
        except Exception:
            logger.exception("Failed to open trajectory stream file: {}", self._traj_stream_path)
            self._traj_stream_fp = None

    def _flush_traj_buffer(self) -> None:
        """Flush buffered trajectory steps to the JSONL stream file."""

        if not self._traj_buffer:
            return
        if self._traj_stream_path is None:
            # No disk-backed stream; nothing to flush.
            self._traj_buffer = []
            return

        self._open_traj_stream_if_needed()
        if self._traj_stream_fp is None:
            self._traj_buffer = []
            return

        self._traj_flush_count += 1
        try:
            for rec in self._traj_buffer:
                line = json.dumps(
                    rec,
                    ensure_ascii=False,
                    indent=None,
                    separators=(",", ":"),
                )
                self._traj_stream_fp.write(line)
                self._traj_stream_fp.write("\n")
            self._traj_stream_fp.flush()
        finally:
            self._traj_buffer = []
            if self._traj_stream_path is not None:
                try:
                    size_bytes = self._traj_stream_path.stat().st_size
                    size_mb = float(size_bytes) / (1024.0 * 1024.0)
                    logger.info(
                        "DynaSchedEnv: flushed trajectory buffer #{}; file size ~{:.1f} MB (steps={})",
                        self._traj_flush_count,
                        size_mb,
                        self._traj_step_count,
                    )
                except Exception:
                    logger.exception(
                        "DynaSchedEnv: failed to stat trajectory stream file: {}",
                        self._traj_stream_path,
                    )

    def _write_traj_final_snapshot(self) -> None:
        if self._traj_stream_path is None or self._sim is None or self._traj_final_written:
            return
        self._open_traj_stream_if_needed()
        if self._traj_stream_fp is None:
            return
        snap_final = self._sim.export_snapshot()
        try:
            sys_stats = getattr(snap_final, "system_stats", None)
            num_jobs_total = getattr(sys_stats, "num_jobs_total", None) if sys_stats is not None else None
            num_jobs_completed = getattr(sys_stats, "num_jobs_completed", None) if sys_stats is not None else None
            num_jobs_cancelled = getattr(sys_stats, "num_jobs_cancelled", None) if sys_stats is not None else None
            logger.info(
                "DynaSchedEnv: writing final_snapshot at time={} jobs_total={} completed={} cancelled={}",
                float(getattr(snap_final, "time", 0.0)),
                num_jobs_total,
                num_jobs_completed,
                num_jobs_cancelled,
            )
        except Exception:
            logger.exception("DynaSchedEnv: failed to log final_snapshot summary")
        rec: Dict[str, Any] = {
            "type": "final_snapshot",
            "snapshot": snap_final.model_dump(),
        }
        line = json.dumps(
            rec,
            ensure_ascii=False,
            indent=None,
            separators=(",", ":"),
        )
        self._traj_stream_fp.write(line)
        self._traj_stream_fp.write("\n")
        self._traj_stream_fp.flush()
        self._traj_final_written = True

    def _build_traj_step_summary(
        self,
        snap: Snapshot,
        action: Optional[Dict[str, Any]],
        info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a lightweight per-step summary for streaming to disk."""

        wip_waiting = sum(1 for j in snap.jobs if j.status == "waiting")
        wip_processing = sum(1 for j in snap.jobs if j.status == "processing")
        queue_total = sum(len(m.queue) for m in snap.machines)

        st = getattr(snap, "stability_stats", None)
        changed_ops_ratio = float(getattr(st, "changed_ops_ratio", 0.0)) if st is not None else 0.0
        avg_start_time_shift = float(getattr(st, "avg_start_time_shift", 0.0)) if st is not None else 0.0
        max_start_time_shift = float(getattr(st, "max_start_time_shift", 0.0)) if st is not None else 0.0

        sys_stats = getattr(snap, "system_stats", None)
        num_jobs_total = int(getattr(sys_stats, "num_jobs_total", 0)) if sys_stats is not None else 0
        num_jobs_completed = int(getattr(sys_stats, "num_jobs_completed", 0)) if sys_stats is not None else 0
        num_jobs_cancelled = int(getattr(sys_stats, "num_jobs_cancelled", 0)) if sys_stats is not None else 0

        act_summary: Optional[Dict[str, Any]] = None
        if action is not None:
            act_summary = {
                "job_id": action.get("job_id"),
                "machine_group": action.get("machine_group"),
                "machine_id": action.get("machine_id"),
            }

        safe_info: Dict[str, Any] = {}
        if isinstance(info, dict):
            for k, v in info.items():
                if k in {"reward", "type"}:
                    safe_info[k] = v
                elif k == "action_timing" and isinstance(v, dict):
                    safe_info["action_timing"] = v

        return {
            "time": float(getattr(snap, "time", 0.0)),
            "action": act_summary,
            "has_decision": bool(action is not None),
            "wip_waiting": int(wip_waiting),
            "wip_processing": int(wip_processing),
            "queue_total": int(queue_total),
            "num_jobs_total": num_jobs_total,
            "num_jobs_completed": num_jobs_completed,
            "num_jobs_cancelled": num_jobs_cancelled,
            "changed_ops_ratio": changed_ops_ratio,
            "avg_start_time_shift": avg_start_time_shift,
            "max_start_time_shift": max_start_time_shift,
            "info": safe_info,
        }

    def _append_traj_step(
        self,
        snap: Snapshot,
        action: Optional[Dict[str, Any]],
        info: Dict[str, Any],
    ) -> None:
        """Append a step to the in-memory trajectory and/or stream summary to disk."""
        # When no stream path is configured, fall back to legacy in-memory
        # behaviour to avoid breaking lightweight usages.
        if not self._track_trajectory:
            return

        self._traj_step_count += 1
        if self._traj_step_count % 5000 == 0:
            logger.info(
                "DynaSchedEnv: recorded {} trajectory steps (stream={}, buffer_size={})",
                self._traj_step_count,
                self._traj_stream_path is not None,
                len(self._traj_buffer),
            )

        if self._traj_stream_path is None:
            # Legacy path: keep full in-memory trajectory for small-scale
            # experiments where disk streaming is not requested.
            self._trajectory.append_step(
                StepRecord(time=snap.time, snapshot=snap, action=action, info=info)
            )
            return

        # Disk-backed path: record only dynamic data and buffer before
        # flushing to disk. Static fields in ``snap`` are expected to have
        # been cleared by the caller (reset/step/advance).
        summary = self._build_traj_step_summary(snap, action, info)
        rec: Dict[str, Any] = {"type": "summary"}
        rec.update(summary)

        self._traj_buffer.append(rec)
        if len(self._traj_buffer) >= self._traj_buffer_limit:
            self._flush_traj_buffer()

    def close(self) -> None:
        """Close any resources held by the environment (e.g., trajectory streams)."""

        try:
            self._flush_traj_buffer()
            self._write_traj_final_snapshot()
        except Exception:
            logger.exception("Failed to finalize trajectory on close")

        if self._traj_stream_fp is not None:
            try:
                self._traj_stream_fp.close()
            except Exception:
                logger.exception("Failed to close trajectory stream file: {}", self._traj_stream_path)
            self._traj_stream_fp = None

    def _get_machine_proc_time_dict(self, job_id: str, op_index: int) -> Dict[str, float]:
        """Return machine-specific processing times for an operation from JMSSim.
        
        Args:
            job_id: Job identifier as a string.
            op_index: Zero-based operation index.
            
        Returns:
            Mapping from machine ID to processing time, or an empty mapping if
            the data is unavailable.
        """
        if self._sim is None:
            logger.debug(
                "_get_machine_proc_time_dict: _sim is None for job_id={} op_index={}",
                job_id,
                op_index,
            )
            return {}
        
        if not hasattr(self._sim, "_sim"):
            logger.debug(
                "_get_machine_proc_time_dict: _sim does not have _sim attribute (not JMSSimBackend?)"
            )
            return {}
        
        jms_sim = self._sim._sim
        if not hasattr(jms_sim, "jobs"):
            logger.debug(
                "_get_machine_proc_time_dict: jms_sim does not have jobs attribute"
            )
            return {}
        
        try:
            job_id_int = int(job_id)
            job = jms_sim.jobs.get(job_id_int)
            if job is None:
                logger.debug(
                    "_get_machine_proc_time_dict: job {} not found in jms_sim.jobs",
                    job_id_int,
                )
                return {}
            
            if op_index < 0 or op_index >= len(job.ops):
                logger.debug(
                    "_get_machine_proc_time_dict: op_index {} out of range for job {} (has {} ops)",
                    op_index,
                    job_id_int,
                    len(job.ops),
                )
                return {}
            
            op = job.ops[op_index]
            proc_time_dict = {str(m): float(pt) for m, pt in op.proc_time.items()}
            
            logger.debug(
                "_get_machine_proc_time_dict: job_id={} op_index={} proc_time={}",
                job_id,
                op_index,
                proc_time_dict,
            )
            
            return proc_time_dict
            
        except ValueError as e:
            logger.warning(
                "_get_machine_proc_time_dict: failed to convert job_id '{}' to int: {}",
                job_id,
                e,
            )
            return {}
        except Exception as e:
            logger.exception(
                "_get_machine_proc_time_dict: unexpected error for job_id={} op_index={}: {}",
                job_id,
                op_index,
                e,
            )
            return {}

    def _snapshot_to_observation(self, snap: Snapshot) -> Dict[str, Any]:
        """Convert a rich Snapshot into a compact observation dict.

        For compatibility with the current `LLMEnv`, this only exposes:
        - `time`: current decision time
        - `ready_ops`: list of {job_id, operation, machine_group, process_time}
        - `machines`: {machine_id: available_from}
        """

        ready_ops: List[Dict[str, Any]] = []
        total_ops = 0
        completed_ops = 0
        for j in snap.jobs:
            total_ops += j.total_ops
            completed_ops += min(j.current_op_index, j.total_ops)
            k = j.current_op_index
            if k >= j.total_ops or j.status in ("completed", "cancelled"):
                continue
            op = j.ops[k]
            if j.release_time > snap.time:
                continue
            remaining_ops = max(0, j.total_ops - (k + 1))
            
            proc_time_by_machine: Dict[str, float] = self._get_machine_proc_time_dict(j.job_id, k)
            
            if not proc_time_by_machine:
                fallback_pt = float(op.proc_time_realized)
                proc_time_by_machine = {m_id: fallback_pt for m_id in op.candidate_machines}
                logger.debug(
                    "_snapshot_to_observation: using fallback proc_time={} for job_id={} op_index={} machines={}",
                    fallback_pt,
                    j.job_id,
                    k,
                    op.candidate_machines,
                )
            
            ready_info: Dict[str, Any] = {
                "job_id": j.job_id,
                "operation": k,
                "machine_group": op.machine_group,
                "process_time": op.proc_time_realized,
                "proc_time_by_machine": proc_time_by_machine,
                "remaining_work": float(j.remaining_work_content),
                "remaining_ops": remaining_ops,
                "flexibility": len(op.candidate_machines),
                "priority": float(j.priority),
                "release_time": float(getattr(j, "release_time", 0.0) or 0.0),
                "arrival_time": float(getattr(j, "release_time", 0.0) or 0.0),
            }
            ready_ops.append(ready_info)

        machines: Dict[str, float] = {}
        down_machines: List[str] = []

        t_now = float(getattr(snap, "time", 0.0))
        sim = getattr(self, "_sim", None)

        for m in snap.machines:
            machines[m.machine_id] = float(m.available_from)

            is_down = False
            has_block = False
            if sim is not None and hasattr(sim, "_machine_block_until"):
                try:
                    block = float(sim._machine_block_until(m.machine_id, m.group))  # type: ignore[attr-defined]
                    has_block = True
                except Exception:
                    has_block = False

            if has_block:
                if block > t_now + 1e-9:
                    is_down = True
            else:
                status = str(m.status)
                if status.startswith("down"):
                    is_down = True

            if is_down:
                down_machines.append(m.machine_id)

        sys_stats = snap.system_stats
        num_jobs = sys_stats.num_jobs_total
        avg_ops = float(total_ops) / float(num_jobs) if num_jobs > 0 else 0.0

        dynamic_cfg = getattr(snap, "dynamic_scenarios", {}) or {}
        emergency_jobs: List[str] = []
        threshold = None
        val = dynamic_cfg.get("emergency_priority") if isinstance(dynamic_cfg, dict) else None
        if val is not None:
            try:
                threshold = float(val)
            except Exception:
                threshold = None
        if threshold is not None:
            for j in snap.jobs:
                if j.status not in ("completed", "cancelled") and float(j.priority) <= threshold:
                    emergency_jobs.append(j.job_id)

        try:
            static_emergency = getattr(self, "_static_emergency_jobs", None)
        except Exception:
            static_emergency = None
        if static_emergency:
            current_ids = {str(j.job_id) for j in snap.jobs if j.status not in ("completed", "cancelled")}
            for jid in static_emergency:
                s_jid = str(jid)
                if s_jid in current_ids and s_jid not in emergency_jobs:
                    emergency_jobs.append(s_jid)

        # Base scenario/profile information, kept compatible with existing
        # prompt formatting while allowing future extensions.
        scale_cfg = getattr(snap, "scale", {}) or {}
        targets_cfg = getattr(snap, "targets", {}) or {}
        dynamics_cfg = getattr(snap, "dynamics", {}) or {}
        scenario_info: Dict[str, Any] = {
            "num_jobs_total": num_jobs,
            "num_machines": len(snap.machines),
            "avg_ops_per_job": avg_ops,
            "horizon": float(snap.horizon),
            "dynamic_scenarios": dynamic_cfg,
            "scale": scale_cfg,
            "targets": targets_cfg,
            "dynamics": dynamics_cfg,
        }

        # Progress statistics at the current decision time.
        progress_info: Dict[str, Any] = {
            "time": float(snap.time),
            "num_jobs_total": num_jobs,
            "num_jobs_arrived": sys_stats.num_jobs_arrived,
            "num_jobs_completed": sys_stats.num_jobs_completed,
            "num_jobs_cancelled": sys_stats.num_jobs_cancelled,
            "total_ops": total_ops,
            "completed_ops": completed_ops,
        }

        # Event counters maintained by the simulator (may be absent on older
        # snapshots or non-standard simulators, so we guard accesses).
        events_info: Dict[str, Any] = {}
        try:
            events_raw = getattr(sys_stats, "event_counters", {})
            if isinstance(events_raw, dict):
                events_info = dict(events_raw)
        except Exception:
            events_info = {}

        dynamic_summary: Dict[str, Any] = {
            "scenario": scenario_info,
            "progress": progress_info,
            "events": events_info,
            "emergency_jobs": emergency_jobs,
            "down_machines": down_machines,
        }

        return {
            "time": float(snap.time),
            "ready_ops": ready_ops,
            "machines": machines,
            "dynamic_summary": dynamic_summary,
        }

    def _compute_reward(self, prev_time: float, curr_time: float, action: Dict[str, Any]) -> float:
        """Compute a simple, well-defined reward.

        The current reward is intentionally conservative and easy to interpret:
        it is the negative time delta between consecutive decision points, so
        faster progress receives a higher value. More complex measures such as
        tardiness deltas or stability penalties can be computed later from the
        full trajectory in ``dsbx.Eval``.
        """

        dt = float(curr_time - prev_time)
        return -dt

    def _check_done(self, snap: Snapshot) -> bool:
        for j in snap.jobs:
            if j.status not in ("completed", "cancelled"):
                return False

        if self._sim is None:
            return True

        events = getattr(self._sim, "_events", None)
        idx = getattr(self._sim, "_event_index", None)
        if events is None or idx is None:
            return True

        for ev in events[idx:]:
            if isinstance(ev, ArrivalEvent):
                return False

        return True
