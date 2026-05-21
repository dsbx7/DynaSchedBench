"""PDR-based Agent implementation for dsbx.

This agent uses priority dispatching rules to make scheduling decisions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import random

from loguru import logger
from dsbx.Agents.Base import BaseAgent
from .rules import (
    JobSelectionRule,
    MachineSelectionRule,
    precompute_remaining_work,
    compute_job_priority,
    select_best_machine,
)


class PDRAgent(BaseAgent):
    """Priority Dispatching Rule agent.
    
    This agent selects jobs and machines using configurable heuristic rules.
    
    Args:
        op_rule: Job/operation selection rule (default: SPT)
        machine_rule: Machine selection rule (default: LIT)
        random_seed: Random seed for tie-breaking (optional)
    """
    
    def __init__(
        self,
        op_rule: str = "SPT",
        machine_rule: str = "LIT",
        random_seed: Optional[int] = None,
    ):
        self.op_rule = op_rule.upper()
        self.machine_rule = machine_rule.upper()
        
        # Validate rules
        try:
            JobSelectionRule(self.op_rule)
        except ValueError:
            raise ValueError(
                f"Unknown job selection rule: {op_rule}. "
                f"Supported: {[r.value for r in JobSelectionRule]}"
            )
        
        try:
            MachineSelectionRule(self.machine_rule)
        except ValueError:
            raise ValueError(
                f"Unknown machine selection rule: {machine_rule}. "
                f"Supported: {[r.value for r in MachineSelectionRule]}"
            )
        
        if random_seed is not None:
            random.seed(random_seed)
        
        self._remain_work_cache: Optional[Dict] = None
        self._emergency_jobs: set = set()
        self._step: int = 0
        self._last_action: Optional[Dict[str, Any]] = None
        logger.info(
            "PDRAgent initialized with op_rule={}, machine_rule={}, random_seed={}",
            self.op_rule,
            self.machine_rule,
            random_seed,
        )
    
    def reset(self, scenario_info: Dict[str, Any] | None = None) -> None:
        """Reset agent state for a new episode."""
        self._remain_work_cache = None
        self._emergency_jobs = set()
        self._step = 0
        self._last_action = None
        
        # Check if scenario defines emergency jobs
        if scenario_info:
            self._emergency_jobs = set(scenario_info.get("emergency_jobs", []))
        try:
            keys = list((scenario_info or {}).keys())[:10]
        except Exception:
            keys = []
        logger.info(
            "PDRAgent reset: emergency_jobs={} scenario_info_keys={} (truncated)",
            len(self._emergency_jobs),
            keys,
        )
        if self._emergency_jobs:
            logger.trace(
                "PDRAgent emergency_jobs sample (up to 10): {}",
                sorted(list(self._emergency_jobs))[:10],
            )
    
    def act(
        self,
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env: Any,
    ) -> Optional[Dict[str, Any]]:
        """Select an action using PDR.
        
        Args:
            obs: Current observation (only lightly used; main state is read from env snapshot).
            legal_actions: List of legal action dictionaries
            env: Environment reference, expected to expose ``get_snapshot`` or ``get_light_state``.
            
        Returns:
            Selected action dict, or None if no legal action
        """
        if not legal_actions:
            logger.trace("PDRAgent.act called with no legal actions")
            return None

        try:
            self._step += 1
        except Exception:
            self._step = 1

        snap = None
        jobs_dict: Dict[str, Any] = {}
        machines_dict: Dict[str, Any] = {}
        job_snap_by_id: Dict[str, Any] = {}
        obs_ext: Dict[str, Any] = {}
        current_time: Optional[float] = None

        use_light_state = False
        light_state: Optional[Dict[str, Any]] = None

        # Fast-path: use lightweight dict state if the environment exposes it.
        if hasattr(env, "get_light_state") and callable(getattr(env, "get_light_state", None)):
            try:
                light_state_obj = env.get_light_state()
                if isinstance(light_state_obj, dict):
                    light_state = light_state_obj
                    jobs_dict = dict(light_state.get("jobs", {}) or {})
                    machines_dict = dict(light_state.get("machines", {}) or {})
                    obs_ext = light_state
                    try:
                        current_time = float(light_state.get("time", 0.0))
                    except Exception:
                        current_time = None
                    use_light_state = True
            except Exception as exc:
                logger.warning(
                    "PDRAgent.act failed to get_light_state; falling back to snapshot. Error: {}",
                    exc,
                )
                use_light_state = False

        if not use_light_state:
            # Obtain rich snapshot from environment (fallback path)
            try:
                snap = env.get_snapshot()
            except Exception as exc:
                logger.warning(
                    "PDRAgent.act failed to get snapshot; falling back to simple SPT. Error: {}",
                    exc,
                )
                # Fallback: simple SPT on legal_actions if snapshot is unavailable
                best_action: Optional[Dict[str, Any]] = None
                best_pt = float("inf")
                for a in legal_actions:
                    pt = float(a.get("process_time", 0.0))
                    if pt < best_pt:
                        best_pt = pt
                        best_action = a
                try:
                    jid = str((best_action or legal_actions[0]).get("job_id"))
                except Exception:
                    jid = "<unknown>"
                logger.info(
                    "PDRAgent.act: step={} fallback_mode=simple_spt selected_job_id={} best_pt={}",
                    self._step,
                    jid,
                    best_pt,
                )
                return best_action or legal_actions[0]

            # Build job snapshots map for quick lookup
            job_snap_by_id = {str(j.job_id): j for j in getattr(snap, "jobs", [])}

            # Build jobs dict for PDR rules
            jobs_dict = {}
            for jid, j in job_snap_by_id.items():
                ops_info: List[Dict[str, Any]] = []
                for op in j.ops:
                    ops_info.append(
                        {
                            "index": op.index,
                            "machine_group": op.machine_group,
                            "proc_time_nominal": float(op.proc_time_nominal),
                            "proc_time_realized": float(op.proc_time_realized),
                        }
                    )
                jobs_dict[jid] = {
                    "release_time": float(j.release_time),
                    "due_date": float(j.due_date),
                    "total_ops": int(j.total_ops),
                    "total_work_content": float(j.total_work_content),
                    "remaining_work_content": float(j.remaining_work_content),
                    "priority": float(getattr(j, "priority", 0.0)),
                    "ops": ops_info,
                    "current_op_index": int(getattr(j, "current_op_index", 0)),
                }

            # Build machines dict for machine selection rules
            machines_dict = {}
            for m in getattr(snap, "machines", []):
                busy_time = 0.0
                for seg in m.schedule_segments:
                    busy_time += float(seg.end - seg.start)
                machines_dict[str(m.machine_id)] = {
                    "available_from": float(m.available_from),
                    "speed": float(getattr(m, "speed", 1.0)),
                    "busy_time": busy_time,
                }

            obs_ext = {
                "jobs": jobs_dict,
                "machines": machines_dict,
            }
            current_time = getattr(snap, "time", None)

        logger.trace(
            "PDRAgent.act: step={} time={} jobs={} machines={} legal_actions={} use_light_state={}",
            self._step,
            current_time,
            len(jobs_dict),
            len(machines_dict),
            len(legal_actions),
            use_light_state,
        )

        # Precompute remaining work if not cached
        if self._remain_work_cache is None:
            if jobs_dict:
                self._remain_work_cache = precompute_remaining_work(jobs_dict)
            else:
                self._remain_work_cache = {}

        # Step 1: Compute priority for each job in legal_actions
        op_priorities: List[Any] = []
        candidate_summaries: List[str] = []

        for action in legal_actions:
            job_id = str(action.get("job_id"))
            is_emergency = job_id in self._emergency_jobs

            # For environments that expose a JMSSim backend via
            # get_light_state (i.e., JMSRawEnv), the set of *currently*
            # emergency jobs is maintained dynamically on the simulator as
            # ``sim.emergency_jobs`` and updated when job_emergency events
            # fire and when an emergency job is first scheduled. EnvState
            # priority_value uses this dynamic set, not a static list of
            # jobs that will ever become emergency. To match that timing
            # semantics, we override is_emergency here based on the
            # underlying JMSSim state instead of relying solely on the
            # scenario_info-based _emergency_jobs.
            if use_light_state:
                sim = getattr(env, "_sim", None)
                if sim is not None:
                    try:
                        jid_int = int(job_id)
                    except Exception:
                        jid_int = -1
                    if jid_int != -1:
                        try:
                            em_set = getattr(sim, "emergency_jobs", set())
                        except Exception:
                            em_set = set()
                        try:
                            is_emergency = jid_int in em_set
                        except Exception:
                            # Fall back to scenario_info-based flag on error
                            pass

            if use_light_state:
                job_info = jobs_dict.get(job_id)
                if not isinstance(job_info, dict):
                    continue
                try:
                    op_index = int(job_info.get("current_op_index", 0))
                except Exception:
                    op_index = 0
                total_ops = int(job_info.get("total_ops", 0))
                if op_index >= total_ops:
                    continue
                ops_list = job_info.get("ops", [])
                if not (0 <= op_index < len(ops_list)):
                    continue
                op_info = ops_list[op_index]
                proc_time = float(
                    op_info.get(
                        "proc_time_realized",
                        op_info.get("proc_time_nominal", 0.0),
                    )
                )

                if self.op_rule in ("SPT", "LPT"):
                    mc = action.get("machine_candidates") or []
                    if mc:
                        sim = getattr(env, "_sim", None)
                        if sim is not None:
                            try:
                                jid_int = int(job_id)
                            except Exception:
                                jid_int = -1

                            if jid_int != -1:
                                try:
                                    jobs_map = getattr(sim, "jobs", {}) or {}
                                except Exception:
                                    jobs_map = {}

                                job_obj = jobs_map.get(jid_int)
                                if job_obj is not None and 0 <= op_index < len(job_obj.ops):
                                    try:
                                        op_obj = job_obj.ops[op_index]
                                        pt_map = getattr(op_obj, "proc_time", {}) or {}
                                    except Exception:
                                        pt_map = {}

                                    if pt_map:
                                        pts: list[float] = []
                                        for m_raw in mc:
                                            try:
                                                m_int = int(m_raw)
                                            except Exception:
                                                continue
                                            if m_int in pt_map:
                                                try:
                                                    pts.append(float(pt_map[m_int]))
                                                except Exception:
                                                    continue
                                        if pts:
                                            proc_time = min(pts)
            else:
                job_snap = job_snap_by_id.get(job_id)
                if job_snap is None:
                    continue

                op_index = int(job_snap.current_op_index)
                if op_index >= job_snap.total_ops:
                    continue

                op_snap = job_snap.ops[op_index]
                proc_time = float(op_snap.proc_time_realized)

            priority = compute_job_priority(
                rule=self.op_rule,
                job_id=job_id,
                op_index=op_index,
                proc_time=proc_time,
                obs=obs_ext,
                remain_work_cache=self._remain_work_cache,
                is_emergency=is_emergency,
            )

            op_priorities.append((priority, job_id, op_index, action, proc_time))

            # Collect a compact summary string for this candidate; we'll log all
            # candidates for the step in a single debug line to avoid flooding
            # the logs with one line per candidate.
            try:
                pri_str = f"{priority:.4g}"
            except Exception:
                pri_str = str(priority)
            try:
                pt_str = f"{proc_time:.4g}"
            except Exception:
                pt_str = str(proc_time)
            flag = "E" if is_emergency else "N"
            candidate_summaries.append(
                f"{job_id}@{op_index}[{flag}] p={pri_str} t={pt_str}"
            )

        if candidate_summaries:
            logger.trace(
                "PDRAgent candidates: step={} count={} {}",
                self._step,
                len(candidate_summaries),
                "; ".join(candidate_summaries),
            )

        if not op_priorities:
            # Fallback: pick the first legal action
            logger.warning(
                "PDRAgent: step={} no valid op priorities; returning first legal action",
                self._step,
            )
            return legal_actions[0]

        # Step 2: Select the job-operation with best priority
        op_priorities.sort(key=lambda x: x[0])
        best_priority = op_priorities[0][0]
        best_ops = [op for op in op_priorities if op[0] == best_priority]

        logger.trace(
            "PDRAgent: best_priority={} num_best={}",
            best_priority,
            len(best_ops),
        )

        # Random tie-breaking among best candidates
        _, selected_job_id, selected_op_index, base_action, proc_time = random.choice(best_ops)

        logger.trace(
            "PDRAgent selected operation: job_id={} op_index={} is_emergency={} priority={}",
            selected_job_id,
            selected_op_index,
            selected_job_id in self._emergency_jobs,
            best_priority,
        )

        # Step 3: Find matching legal action(s) for the selected job
        matching_actions = [
            a for a in legal_actions if str(a.get("job_id")) == selected_job_id
        ]
        if not matching_actions:
            logger.warning(
                "PDRAgent: step={} no matching legal action found for selected_job_id={}, falling back to first legal action",
                self._step,
                selected_job_id,
            )
            return legal_actions[0]

        selected_action = matching_actions[0]

        # Step 4: Select machine using machine rule from candidate machines
        machine_candidates = selected_action.get("machine_candidates") or []
        if not machine_candidates:
            # No explicit machine choices; let simulator decide
            logger.trace(
                "PDRAgent: no machine_candidates for job_id={}, letting simulator decide",
                selected_job_id,
            )
            return selected_action

        logger.debug(
            "PDRAgent: candidate machines for job_id={} op_index={}: {}",
            selected_job_id,
            selected_op_index,
            machine_candidates,
        )

        # Build candidate machine infos. For environments that expose a
        # JMSSim backend via ``env._sim`` (i.e., JMSRawEnv using
        # get_light_state), we attach per-machine processing times for the
        # selected job/operation so that the SPT machine rule matches
        # EnvState semantics.
        cand_infos: List[Dict[str, Any]] = []
        per_machine_pt: Dict[int, float] = {}

        if use_light_state:
            sim = getattr(env, "_sim", None)
            if sim is not None:
                try:
                    jid_int = int(selected_job_id)
                except Exception:
                    jid_int = -1

                if jid_int != -1:
                    try:
                        jobs_map = getattr(sim, "jobs", {}) or {}
                    except Exception:
                        jobs_map = {}

                    job_obj = jobs_map.get(jid_int)
                    if job_obj is not None:
                        try:
                            op_idx = int(selected_op_index)
                        except Exception:
                            op_idx = -1

                        if 0 <= op_idx < len(job_obj.ops):
                            try:
                                op_obj = job_obj.ops[op_idx]
                                per_machine_pt = {
                                    int(m): float(pt) for m, pt in getattr(op_obj, "proc_time", {}).items()
                                }
                            except Exception:
                                per_machine_pt = {}

        for mid in machine_candidates:
            mid_int: Optional[int]
            if isinstance(mid, (int, float)):
                try:
                    mid_int = int(mid)
                except Exception:
                    mid_int = None
            else:
                try:
                    mid_int = int(str(mid))
                except Exception:
                    mid_int = None

            machine_id_str = str(mid_int if mid_int is not None else mid)
            info: Dict[str, Any] = {"machine_id": machine_id_str}

            if per_machine_pt and mid_int is not None and mid_int in per_machine_pt:
                info["proc_time"] = per_machine_pt[mid_int]

            cand_infos.append(info)

        best_machine_id = select_best_machine(
            rule=self.machine_rule,
            candidates=cand_infos,
            proc_time=float(proc_time),
            obs=obs_ext,
        )

        if best_machine_id is None:
            logger.trace(
                "PDRAgent: no best_machine_id found for job_id={}, returning base action",
                selected_job_id,
            )
            return selected_action

        # Step 5: Return a copy of the selected action with explicit machine_id
        action_out = dict(selected_action)
        action_out["machine_id"] = best_machine_id
        logger.trace(
            "PDRAgent final action: step={} job_id={} op_index={} machine_id={}",
            self._step,
            selected_job_id,
            selected_op_index,
            best_machine_id,
        )
        self._last_action = action_out
        return action_out
