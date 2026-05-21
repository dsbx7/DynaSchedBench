from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

from loguru import logger

from dsbx.Env import DynaSchedEnv, JMSRawEnv
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Sim.Loader import load_instance_from_events
from dsbx.Sim.Events import PriorityChangeEvent

from .agent import PDRAgent


PathLike = Union[str, Path]


def solve(
    instance_dir: PathLike,
    op_rule: str = "SPT",
    machine_rule: str = "LIT",
    max_steps: Optional[int] = None,
    out_dir: Optional[PathLike] = None,
    sim_backend: str = "jmssim",
) -> Dict[str, Any]:
    """Run a PDR agent on a given instance directory and return results."""

    inst_path = Path(instance_dir)

    backend = (sim_backend or "jmssim").lower()

    if backend == "jmssim":
        return _solve_with_jmssim(
            data_path=inst_path,
            op_rule=op_rule,
            machine_rule=machine_rule,
            max_steps=max_steps,
            out_dir=out_dir,
        )

    events_file = inst_path / "events.jsonl"
    if not events_file.is_file():
        raise FileNotFoundError(f"Expected events.jsonl under {inst_path}")

    model, events = load_instance_from_events(events_file)

    if out_dir is not None:
        out_path = Path(out_dir)
    else:
        out_path = inst_path / f"pdr_{op_rule}_{machine_rule}".lower()

    traj_stream_path = out_path / "trajectory_light.jsonl"

    env = DynaSchedEnv(
        model,
        events=events,
        auto_generate_events=False,
        traj_stream_path=traj_stream_path,
    )

    emergency_jobs = set()
    emergency_threshold = getattr(getattr(model, "dynamic_scenarios", None), "emergency_priority", -1)
    from_priority = set()
    for ev in events:
        if isinstance(ev, PriorityChangeEvent):
            new_p = getattr(ev, "new_priority", 0)
            if new_p <= emergency_threshold:
                jid = str(ev.job_id)
                emergency_jobs.add(jid)
                from_priority.add(jid)

    static_jobs_path = inst_path / "static_jobs.json"
    from_static = set()
    if static_jobs_path.exists():
        try:
            raw = static_jobs_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            jobs_info = data.get("jobs", {}) or {}
            for jid, info in jobs_info.items():
                atype = info.get("arrival_type")
                if atype in ("emergency", "dynamic"):
                    jid_str = str(jid)
                    emergency_jobs.add(jid_str)
                    from_static.add(jid_str)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(f"PDR.runner: failed to read static_jobs.json for emergency jobs: {exc}")

    if emergency_jobs:
        try:
            env._static_emergency_jobs = set(emergency_jobs)  # type: ignore[attr-defined]
        except Exception:
            pass

    logger.info(
        "PDR.runner: emergency jobs detected: total={} from_priority={} from_static={} threshold={}",
        len(emergency_jobs),
        len(from_priority),
        len(from_static),
        emergency_threshold,
    )

    scenario_info: Dict[str, Any] = {"events_path": str(events_file)}
    if emergency_jobs:
        scenario_info["emergency_jobs"] = sorted(emergency_jobs)

    agent = PDRAgent(op_rule=op_rule, machine_rule=machine_rule)
    agent.reset(scenario_info=scenario_info)

    obs = env.reset()
    try:
        done = bool(env.done())
    except Exception:
        done = False

    if max_steps is None:
        try:
            max_steps = int(env.total_operations()) * 4 + 1000
        except Exception:
            max_steps = 100000

    steps = 0
    start_time_wall = time.perf_counter()

    while not done and steps < max_steps:
        legal = env.legal_actions()
        if not legal:
            obs = env.advance_if_idle()
            continue

        act = agent.act(obs, legal, env)
        if act is None:
            obs = env.advance_if_idle()
            try:
                done = bool(env.done())
            except Exception:
                done = False
            continue

        obs, _, done, _ = env.step(act)
        steps += 1
        try:
            done = bool(done)
        except Exception:
            done = False

    traj = env.get_trajectory()
    end_time_wall = time.perf_counter()
    runtime_seconds = float(end_time_wall - start_time_wall)
    metrics = evaluate_trajectory(traj)

    if isinstance(metrics, dict):
        try:
            metrics["runtime_seconds"] = float(runtime_seconds)
        except Exception:
            pass

    try:
        sim = getattr(env, "_sim", None)
        if sim is not None and hasattr(sim, "get_gantt"):
            gantt = sim.get_gantt()  # type: ignore[assignment]
        else:
            gantt = []
    except Exception:
        gantt = []

    result: Dict[str, Any] = {
        "algorithm": f"pdr:{op_rule}:{machine_rule}",
        "gantt": gantt,
        "metrics": metrics,
        "steps": steps,
    }

    if out_path is not None:
        try:
            out_path.mkdir(parents=True, exist_ok=True)
            metrics_path = out_path / "metrics.json"
            gantt_path = out_path / "gantt.json"
            metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
            gantt_path.write_text(json.dumps(gantt, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.error("PDR.runner: failed to write outputs to {}: {}", out_path, exc)

    try:
        env.close()
    except Exception:
        pass

    return result


def _group_jms_legal_actions(actions: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Group raw JMS legal actions by job while preserving machine order.

    ``JMSRawEnv.legal_actions()`` returns one (job_id, machine_id) pair per
    ready operation and candidate machine, in a deterministic order derived
    from JMSSim.get_ready_operations() and the static ``candidates`` list in
    the instance. To match EnvState PDR semantics (especially the LIT machine
    rule, where tie-breaking is sensitive to candidate order), we preserve the
    first-seen order of machines per job instead of sorting them.
    """

    grouped: Dict[str, list[int]] = {}
    for a in actions:
        try:
            jid_raw = a.get("job_id")
            mid_raw = a.get("machine_id")
        except Exception:
            continue
        if jid_raw is None or mid_raw is None:
            continue

        try:
            jid = str(int(jid_raw))
        except Exception:
            jid = str(jid_raw)
        try:
            mid = int(mid_raw)
        except Exception:
            continue

        if jid not in grouped:
            grouped[jid] = []
        # Avoid duplicates but keep first-seen order
        if mid not in grouped[jid]:
            grouped[jid].append(mid)

    out: list[Dict[str, Any]] = []
    for jid, mids in grouped.items():
        out.append(
            {
                "job_id": jid,
                "machine_group": "jmssim",
                "machine_candidates": mids,
            }
        )
    return out


def _solve_with_jmssim(
    data_path: PathLike,
    op_rule: str,
    machine_rule: str,
    max_steps: Optional[int] = None,
    out_dir: Optional[PathLike] = None,
) -> Dict[str, Any]:
    """Run JMSSim using the same PDR policy as the EnvState baseline.

    Instead of going through JMSRawEnv + PDRAgent, this routine directly
    reconstructs the conference EnvState + event queue from the same
    GEN-Bench JSONL and uses ``src.utils.PDR_utils.select_operation`` to
    choose (job, op, machine, pt) at each decision point. The same decision
    is then applied to JMSSim via ``JMSSim.step_action``.

    This mirrors the behaviour of:

        - toolsj/run_env_pdr_genbench.py (EnvState+PDR baseline)
        - tools/compare_envstate_jmssim.py (shared PDR driving both sims)

    and guarantees that JMSSim PDR runs use *exactly* the same sequence of
    scheduling decisions as the EnvState baseline, provided the underlying
    simulators remain aligned (which we have already validated with the
    comparison script). This ensures makespan and Gantt semantics match
    across all PDR rule combinations without relying on PDRAgent
    approximations.
    """

    from pathlib import Path as _Path
    import sys as _sys
    import heapq as _heapq
    import random as _random
    from typing import Any as _Any, Dict as _Dict, List as _List, Tuple as _Tuple

    # Ensure we can import conference EnvState and its PDR utilities.
    here = _Path(__file__).resolve()
    root = here.parents[3]
    conference_root = root / "conference"
    if str(conference_root) not in _sys.path:
        _sys.path.insert(0, str(conference_root))
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))

    from src.utils.env_state import EnvState, PRIORITY as REF_PRIORITY  # type: ignore
    from src.utils.all_utils import load_root  # type: ignore
    from src.utils.PDR_utils import select_operation  # type: ignore
    from dsbx.Sim.JMSSim import JMSSim, load_jms_like_instance

    # Use the same deterministic random seed as the EnvState PDR baseline
    # (see toolsj/run_env_pdr_genbench._rollout_env_pdr and
    # tools/compare_envstate_jmssim.run_compare). This ensures that
    # PDR_utils.select_operation makes identical tie-breaking choices
    # across EnvState and JMSSim rollouts.
    _random.seed(0)

    p = _Path(data_path)

    # ------------------------------------------------------------------
    # Rebuild EnvState + initial event queue from the same JSONL.
    # This is identical to tools/compare_envstate_jmssim.build_envstate
    # and toolsj/run_env_pdr_genbench._build_envstate.
    # ------------------------------------------------------------------
    static_info, emergency_static, dynamic_events, t0 = load_root(str(p))
    env = EnvState(static_info, emergency_static, dynamic_events, t0)

    event_q: _List[_Tuple[float, int, str, _Any]] = [
        (float(t), REF_PRIORITY[ev_type], ev_type, ev_id)
        for ev_type, lst in dynamic_events.items()
        for ev_id, t in lst
        if float(t) >= float(t0)
    ]
    _heapq.heapify(event_q)

    # Advance EnvState to initial time.
    env.advance_to(float(t0))

    # ------------------------------------------------------------------
    # Build a fresh JMSSim instance from the same JSONL payload.
    # ------------------------------------------------------------------
    payload: _Dict[str, _Any] = load_jms_like_instance(p)
    sim = JMSSim(payload)
    sim.reset()

    # ------------------------------------------------------------------
    # Rollout with shared EnvState PDR policy.
    # ------------------------------------------------------------------
    tol = 1e-6

    local_max_steps = max_steps
    if local_max_steps is None:
        total_ops: Optional[int] = None
        ops_per_job = static_info.get("ops_per_job")
        if isinstance(ops_per_job, list):
            try:
                total_ops = sum(int(x) for x in ops_per_job)
            except Exception:
                total_ops = None
        if total_ops is None:
            local_max_steps = 100000
        else:
            local_max_steps = int(total_ops) * 4 + 1000

    steps = 0
    start_time_wall = time.perf_counter()

    while steps < (local_max_steps or 0):
        while True:
            while event_q and event_q[0][0] <= float(env.timestamp) + tol:
                t_evt, _prio, ev_type, ev_info = _heapq.heappop(event_q)
                env.advance_to(float(t_evt))
                env.handle_event(ev_type, ev_info, event_q)

            ready_env = env.ready_ops()
            if ready_env:
                break

            if not event_q:
                break

            next_time = event_q[0][0]
            env.advance_to(float(next_time))

        if not ready_env and not event_q:
            break

        j, o, m, pt = select_operation(env, ready_env, op_rule.upper(), machine_rule.upper())

        env.schedule_op(j, o, m, pt, event_q)

        try:
            sim.step_action(j, m)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "PDR.runner (jmssim): JMSSim.step_action({}, {}) raised {}",
                j,
                m,
                exc,
            )
            break
        sim.advance_to_next_decision_point()

        steps += 1

    end_time_wall = time.perf_counter()
    makespan = float(getattr(sim, "time", 0.0))
    runtime_seconds = float(end_time_wall - start_time_wall)

    metrics: Dict[str, Any] = {}

    sim_for_metrics = sim
    if sim_for_metrics is not None:
        try:
            jobs = getattr(sim_for_metrics, "jobs", {}) or {}
            em_static = getattr(sim_for_metrics, "_emergency_static", {}) or {}
            dyn_events = getattr(sim_for_metrics, "_dynamic_events", {}) or {}

            em_ids: set[int] = set()
            for jid in em_static.keys():
                try:
                    em_ids.add(int(jid))
                except Exception:
                    continue
            for jid, _t in dyn_events.get("job_emergency", []):
                try:
                    em_ids.add(int(jid))
                except Exception:
                    continue

            flow_times: list[float] = []
            flow_times_emergency: list[float] = []
            flow_times_normal: list[float] = []
            release_times: list[float] = []

            num_jobs_total = 0.0
            num_jobs_completed = 0.0
            num_jobs_cancelled = 0.0

            final_wip_waiting = 0.0
            final_wip_processing = 0.0

            for jid_raw, job in jobs.items():
                num_jobs_total += 1.0

                status = getattr(job, "status", "not_arrived")
                if status == "completed":
                    num_jobs_completed += 1.0
                if status == "cancelled":
                    num_jobs_cancelled += 1.0
                if status == "waiting":
                    final_wip_waiting += 1.0
                if status == "processing":
                    final_wip_processing += 1.0

                try:
                    r = float(getattr(job, "release_time", 0.0))
                except Exception:
                    r = 0.0

                c_raw = getattr(job, "completion_time", None)
                if c_raw is None:
                    c = makespan
                else:
                    try:
                        c = float(c_raw)
                    except Exception:
                        c = makespan

                release_times.append(r)
                flow = float(c - r)
                flow_times.append(flow)

                try:
                    jid_int = int(jid_raw)
                except Exception:
                    # Fallback: errors here should not break metric computation
                    jid_int = -1

                if jid_int in em_ids:
                    flow_times_emergency.append(flow)
                else:
                    flow_times_normal.append(flow)

            total_flow_time = float(sum(flow_times))
            mean_flow_time = total_flow_time / len(flow_times) if flow_times else 0.0

            avg_flow_time_emergency = (
                float(sum(flow_times_emergency) / len(flow_times_emergency))
                if flow_times_emergency
                else 0.0
            )
            avg_flow_time_normal = (
                float(sum(flow_times_normal) / len(flow_times_normal))
                if flow_times_normal
                else 0.0
            )
            if avg_flow_time_normal > 0.0 and avg_flow_time_emergency > 0.0:
                flow_time_ratio = float(avg_flow_time_emergency / avg_flow_time_normal)
            else:
                flow_time_ratio = 0.0

            if release_times:
                min_release = float(min(release_times))
            else:
                min_release = 0.0
            horizon = max(makespan - min_release, 1e-9)
            throughput = float(num_jobs_completed / horizon) if horizon > 0.0 else 0.0

            final_wip = final_wip_waiting + final_wip_processing

            metrics.update(
                {
                    "makespan": makespan,
                    "total_flow_time": total_flow_time,
                    "mean_flow_time": mean_flow_time,
                    "avg_flow_time_emergency": avg_flow_time_emergency,
                    "avg_flow_time_normal": avg_flow_time_normal,
                    "flow_time_ratio_emergency_vs_normal": flow_time_ratio,
                    "throughput": throughput,
                    "num_jobs_total": num_jobs_total,
                    "num_jobs_completed": num_jobs_completed,
                    "num_jobs_cancelled": num_jobs_cancelled,
                    "job_completion_ratio": num_jobs_completed / max(1.0, num_jobs_total),
                    "job_cancellation_ratio": num_jobs_cancelled / max(1.0, num_jobs_total),
                    "final_wip": final_wip,
                    "final_wip_waiting": final_wip_waiting,
                    "final_wip_processing": final_wip_processing,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive metrics path
            logger.warning("PDR.runner (jmssim): failed to compute extended metrics: {}", exc)

    if "makespan" not in metrics:
        metrics["makespan"] = makespan

    metrics["runtime_seconds"] = runtime_seconds

    from typing import List as _ListDict, Dict as _DictDict

    gantt: _ListDict[_DictDict[str, float | int]] = []
    try:
        for rec in getattr(env, "gantt", []) or []:
            status = rec.get("status")
            if status is not None and status != "completed":
                continue
            try:
                j = int(rec.get("job"))
                o1 = int(rec.get("op"))
                m = int(rec.get("machine"))
                s = float(rec.get("start", 0.0))
                e = float(rec.get("end", 0.0))
            except Exception:
                continue

            gantt.append(
                {
                    "job_id": j,
                    "op_index": o1 - 1,
                    "machine_id": m,
                    "start_time": s,
                    "end_time": e,
                }
            )

        gantt.sort(key=lambda r: (r["job_id"], r["op_index"], r["machine_id"], r["start_time"], r["end_time"]))
    except Exception:
        gantt = []

    result: Dict[str, Any] = {
        "algorithm": f"pdr:{op_rule}:{machine_rule}",
        "gantt": gantt,
        "metrics": metrics,
        "steps": steps,
    }

    if out_dir is not None:
        out_path = _Path(out_dir)
        try:
            out_path.mkdir(parents=True, exist_ok=True)
            metrics_path = out_path / "metrics.json"
            gantt_path = out_path / "gantt.json"
            metrics_path.write_text(
                json.dumps(metrics, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            gantt_path.write_text(
                json.dumps(gantt, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("PDR.runner (jmssim): failed to write outputs to {}: {}", out_path, exc)

    try:
        env.close()
    except Exception:
        pass

    return result


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Run PDR agent via dedicated runner.")
    parser.add_argument("instance_dir", type=str, help="Instance directory containing events.jsonl")
    parser.add_argument("--op-rule", type=str, default="SPT", help="PDR job/operation rule")
    parser.add_argument("--machine-rule", type=str, default="LIT", help="PDR machine selection rule")
    parser.add_argument("--max-steps", type=int, default=None, help="Maximum decision steps (optional)")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory for metrics/gantt (optional)")
    parser.add_argument("--sim-backend", type=str, default="jmssim", help="Simulation backend: 'sim' or 'jmssim'")

    args = parser.parse_args()
    solve(
        instance_dir=args.instance_dir,
        op_rule=args.op_rule,
        machine_rule=args.machine_rule,
        max_steps=args.max_steps,
        out_dir=args.out_dir,
        sim_backend=args.sim_backend,
    )
