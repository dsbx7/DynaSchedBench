"""Metric estimation helpers for generated event streams."""

from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
import numpy as np
from loguru import logger

SSI_RHO_MIN = 0.05
SSI_RHO_MAX = 0.98
SSI_SCV_MAX = 10.0
SSI_DDT_MIN = 0.05
SSI_K_MAX = 2000.0
SSI_S_MAX = 0.95
SSI_C_MAX = 500.0
SSI_P_MAX = 20.0
_SSI_LOG1P_C_MAX = float(np.log1p(SSI_C_MAX))
_SSI_LOG1P_P_MAX = float(np.log1p(SSI_P_MAX))

# --- 👇 FIX 1: Import all necessary event types ---
from ..models.events import Event, ArrivalEvent, DueDateEvent
from ..models.inputs import InputModel

class MetricsEngine:
    """
    Estimates metrics using analytical approximations based on queuing theory,
    ensuring the estimation is algorithm-agnostic.
    
    Enhanced with:
    - Caching of base statistics
    - Vectorized numpy operations
    - Pandas acceleration for workload calculations
    """

    def __init__(self, model: InputModel, events: List[Event]):
        self.model = model
        self.events = events
        self.arrival_events = [e for e in self.events if isinstance(e, ArrivalEvent)]
        # --- 👇 FIX 2: Create a mapping for easy lookup ---
        # We need to associate DueDateEvents with their corresponding ArrivalEvents.
        # A dictionary is perfect for this.
        self.due_date_map = {e.job_id: e for e in self.events if isinstance(e, DueDateEvent)}
        
        self._base_stats_cache: Optional[Dict[str, Any]] = None
        self._workload_cache: Optional[Dict[str, float]] = None

    def estimate(self) -> Dict[str, Any]:
        """The main estimation method."""
        logger.info("Metrics Engine: Estimating metrics using analytical (algorithm-agnostic) model...")
        
        if not self.arrival_events:
            return {}
        
        self._base_stats_cache = None
        self._workload_cache = None
        
        base_stats = self._calculate_base_statistics()
        logger.debug(
            "Base stats summary: "
            f"lambda_j={base_stats.get('lambda_j', 0.0):.6f}, "
            f"avg_pt={base_stats.get('avg_pt', 0.0):.6f}, "
            f"avg_ia={base_stats.get('avg_ia', 0.0):.6f}, "
            f"num_machines={base_stats.get('num_machines', len(self.model.plant.machines))}, "
            f"avg_op_count={base_stats.get('avg_op_count', 0.0):.3f}"
        )
        atomic_metrics = self._calculate_atomic_metrics(base_stats)
        ssi_metrics = self._calculate_ssi(atomic_metrics)
        final_metrics = {**atomic_metrics, **ssi_metrics}
        logger.debug(
            "Atomic metrics: "
            f"rho_global={atomic_metrics.get('rho_global', 0.0):.6f}, "
            f"rho_bottleneck={atomic_metrics.get('rho_bottleneck', 0.0):.6f}, "
            f"scv_a={atomic_metrics.get('scv_a', 0.0):.6f}, "
            f"scv_p={atomic_metrics.get('scv_p', 0.0):.6f}, "
            f"ddt={atomic_metrics.get('ddt', 0.0):.6f}, "
            f"load_cv={atomic_metrics.get('load_cv', 0.0):.6f}"
        )
        logger.debug(f"SSI metrics: {ssi_metrics}")
        
        logger.info("Metrics Engine: Analytical estimation complete.")
        return final_metrics

    def _calculate_base_statistics(self) -> Dict[str, Any]:
        """
        Calculates a comprehensive set of fundamental statistics from the event list
        to be used by downstream metric calculations.
        
        Enhanced with caching and vectorization for performance.
        """
        if self._base_stats_cache is not None:
            return self._base_stats_cache
        
        num_arrivals = len(self.arrival_events)
        if num_arrivals == 0: 
            return {}
        
        # --- Arrival Rate Stats ---
        last_arrival_time = self.arrival_events[-1].time
        effective_horizon = max(self.model.scale.horizon, last_arrival_time)
        lambda_j = num_arrivals / effective_horizon if effective_horizon > 0 else 0
        
        # --- Processing Time Stats (Vectorized) ---
        all_ptimes = np.array([pt for e in self.arrival_events for pt in e.process_times])
        avg_pt = float(np.mean(all_ptimes)) if len(all_ptimes) > 0 else 0.0
        std_pt = float(np.std(all_ptimes)) if len(all_ptimes) > 0 else 0.0
        
        # --- Inter-arrival Time Stats (Vectorized) ---
        avg_ia, std_ia = 0.0, 0.0
        if num_arrivals > 1:
            arrival_times = np.array([e.time for e in self.arrival_events])
            inter_arrival_times = np.diff(arrival_times)
            avg_ia = float(np.mean(inter_arrival_times))
            std_ia = float(np.std(inter_arrival_times))
        
        # --- Workload and Capacity Stats (Vectorized with pandas) ---
        workload_per_group = self._calculate_workload_vectorized()
        
        machine_groups = {m.group for m in self.model.plant.machines}
        capacity_per_group = {g: 0.0 for g in machine_groups}
        for machine in self.model.plant.machines:
            sp = getattr(machine, "speed", 1.0)
            capacity_per_group[machine.group] += self.model.scale.horizon * sp
        
        # --- Operation Count Stats (Vectorized) ---
        op_counts = np.array([len(e.process_times) for e in self.arrival_events])
        avg_op_count = float(np.mean(op_counts))
        
        self._base_stats_cache = { 
            "lambda_j": lambda_j, 
            "avg_pt": avg_pt, 
            "std_pt": std_pt,
            "avg_ia": avg_ia, 
            "std_ia": std_ia,
            "num_machines": len(self.model.plant.machines),
            "avg_op_count": avg_op_count,
            "workload_per_group": workload_per_group,
            "capacity_per_group": capacity_per_group,
        }
            
        return self._base_stats_cache
    
    def _calculate_workload_vectorized(self) -> Dict[str, float]:
        """Compute workload with vectorized pandas operations."""
        if self._workload_cache is not None:
            return self._workload_cache
        
        machine_groups = {m.group for m in self.model.plant.machines}
        workload_per_group = {g: 0.0 for g in machine_groups}
        
        try:
            records = []
            for job in self.arrival_events:
                for i, group in enumerate(job.routing):
                    if i < len(job.process_times) and group in workload_per_group:
                        records.append({
                            'group': group,
                            'workload': job.process_times[i]
                        })
            
            if records:
                df = pd.DataFrame(records)
                workload_sum = df.groupby('group')['workload'].sum()
                
                for group, workload in workload_sum.items():
                    workload_per_group[group] = float(workload)
        except Exception as e:
            logger.debug(
                f"Pandas acceleration failed; falling back to loop-based method: {e}"
            )
            for job in self.arrival_events:
                for i, group in enumerate(job.routing):
                    if group in workload_per_group and i < len(job.process_times):
                        workload_per_group[group] += job.process_times[i]
        
        self._workload_cache = workload_per_group
        return workload_per_group

    def _calculate_atomic_metrics(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates high-level atomic metrics using ONLY the pre-calculated statistics.
        This method now contains no loops or direct event access.
        """
        # --- 1. Calculate Rho (Utilization) ---
        workload_per_group = stats.get("workload_per_group", {})
        capacity_per_group = stats.get("capacity_per_group", {})

        rho_per_group: Dict[str, float] = {
            group: workload / capacity_per_group.get(group, 1e-9)
            for group, workload in workload_per_group.items()
        }

        total_workload = sum(workload_per_group.values())
        total_capacity = sum(capacity_per_group.values())
        rho_global_obs = total_workload / total_capacity if total_capacity > 0 else 0.0

        # --- 1.5. Calculate Load CV (coefficient of variation of rho across groups) ---
        rho_values = list(rho_per_group.values())
        if len(rho_values) >= 2:
            mean_rho = float(np.mean(rho_values))
            std_rho = float(np.std(rho_values))
            load_cv_obs = std_rho / mean_rho if mean_rho > 0 else 0.0
        else:
            load_cv_obs = 0.0

        # --- 2. Targeted Bottleneck Rho Calculation (TIME-WINDOWED, MULTI-OBJECTIVE) ---
        # For each BottleneckTarget window, compute the observed rho in that window and
        # return an aggregate scalar equal to the L2 norm of individual errors.
        bn_errors: List[float] = []
        if self.model.targets.rho_bottleneck:
            horizon = self.model.scale.horizon
            # Precompute machine speed and group maps
            machine_speed_map = {m.id: getattr(m, "speed", 1.0) for m in self.model.plant.machines}
            machine_group_map = {m.id: m.group for m in self.model.plant.machines}
            # Build downtime intervals per machine from BREAKDOWN and PREVENTIVE_MAINTENANCE
            downtime_by_machine: Dict[str, List[Tuple[float, float]]] = {}
            for e in self.events:
                if getattr(e, "event_type", None) in ("BREAKDOWN", "PREVENTIVE_MAINTENANCE"):
                    s = float(getattr(e, "time", 0.0))
                    d = float(getattr(e, "duration", 0.0) or 0.0)
                    if d <= 0:
                        continue
                    m_id = getattr(e, "machine_id", None)
                    if not m_id:
                        continue
                    downtime_by_machine.setdefault(m_id, []).append((s, s + d))
            # Apply repair completions to shorten intervals
            for e in self.events:
                if getattr(e, "event_type", None) == "REPAIR_COMPLETION":
                    m_id = getattr(e, "machine_id", None)
                    t_r = float(getattr(e, "time", 0.0))
                    if not m_id or m_id not in downtime_by_machine:
                        continue
                    intervals = downtime_by_machine[m_id]
                    intervals.sort()
                    for i, (s, ed) in enumerate(intervals):
                        if s <= t_r < ed:
                            intervals[i] = (s, t_r)
                            break
            for bn in self.model.targets.rho_bottleneck:
                start = float(bn.time)
                end = float(bn.end_time if bn.end_time is not None else horizon)
                if end <= start:
                    continue
                window_dur = end - start
                group = bn.group
                # Workload proportionally within window
                total_w_g = float(workload_per_group.get(group, 0.0))
                w_window = total_w_g * (window_dur / max(1e-9, horizon))
                # Capacity within window minus downtime capacity
                sum_speed_g = sum(getattr(m, "speed", 1.0) for m in self.model.plant.machines if m.group == group)
                down_cap = 0.0
                for m_id, intervals in downtime_by_machine.items():
                    if machine_group_map.get(m_id) != group:
                        continue
                    sp = float(machine_speed_map.get(m_id, 1.0))
                    for s, ed in intervals:
                        st = max(s, start)
                        en = min(ed, end)
                        if en > st:
                            down_cap += sp * (en - st)
                c_window_eff = sum_speed_g * window_dur - down_cap
                rho_obs_window = w_window / c_window_eff if c_window_eff > 1e-12 else 0.0
                error_val = float(rho_obs_window - float(bn.rho))
                bn_errors.append(error_val)
                logger.debug(
                    "Bottleneck window: "
                    f"group={group}, time=[{start:.3f}, {end:.3f}], "
                    f"rho_obs={rho_obs_window:.6f}, rho_target={float(bn.rho):.6f}, "
                    f"error={error_val:.6f}"
                )
        # L2 norm of errors; if no targets defined, set to 0.0 to indicate perfect match by default
        rho_bottleneck_error_l2 = float(np.sqrt(np.sum(np.square(bn_errors)))) if bn_errors else 0.0

        # --- 2. Other Atomic Metrics (SCV, DDT) ---
        scv_a_obs = (stats.get("std_ia", 0) / stats.get("avg_ia", 1)) ** 2 if stats.get("avg_ia") else 0.0
        scv_p_obs = (stats.get("std_pt", 0) / stats.get("avg_pt", 1)) ** 2 if stats.get("avg_pt") else 0.0
        
        # DDT calculation remains direct event access, as it's a structural property
        # not easily derived from aggregate stats.
        k_factors = [
            (self.due_date_map[e.job_id].due_date - e.time) / sum(e.process_times)
            for e in self.arrival_events if e.job_id in self.due_date_map and sum(e.process_times) > 0
        ]
        ddt_obs = np.mean(k_factors) if k_factors else 0.0
        
        return {
            "rho_global": float(rho_global_obs),
            "rho_bottleneck": rho_bottleneck_error_l2,
            "scv_a": float(scv_a_obs),
            "scv_p": float(scv_p_obs),
            "ddt": float(ddt_obs),
            "load_cv": float(load_cv_obs),
        }
        
    def _calculate_ssi(self, atomic_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates the SSI. For Congestion, it should use the *actual* system bottleneck,
        which might be different from the targeted one. So we need to recalculate max rho here.
        """
        # --- 👇 FIX: For SSI, we still need the NATURAL bottleneck ---
        # This is a subtle but important distinction. SSI describes the actual state of the system.
        stats = self._calculate_base_statistics() # Recalculate stats to get per-group info
        workload_per_group = stats.get("workload_per_group", {})
        capacity_per_group = stats.get("capacity_per_group", {})
        rho_per_group: Dict[str, float] = {
            g: w / capacity_per_group.get(g, 1e-9) for g, w in workload_per_group.items()
        }
        natural_bottleneck_rho = max(rho_per_group.values()) if rho_per_group else atomic_metrics.get("rho_global", 0.0)
        # --- End of FIX ---

        rho_for_congestion = natural_bottleneck_rho
        scv_a = float(atomic_metrics.get("scv_a", 0.0) or 0.0)
        scv_p = float(atomic_metrics.get("scv_p", 0.0) or 0.0)
        ddt = float(atomic_metrics.get("ddt", 1.0) or 1.0)

        rho_clamped = max(SSI_RHO_MIN, min(rho_for_congestion, SSI_RHO_MAX))
        scv_a_clamped = max(0.0, min(scv_a, SSI_SCV_MAX))
        scv_p_clamped = max(0.0, min(scv_p, SSI_SCV_MAX))
        ddt_clamped = max(SSI_DDT_MIN, ddt)

        c_stress = (rho_clamped / (1 - rho_clamped)) * (1.0 + (scv_a_clamped + scv_p_clamped) / 2.0)
        p_stress = 1.0 / ddt_clamped
        
        # Calculate K (Complexity) based on system complexity
        num_machines = float(stats.get("num_machines", len(self.model.plant.machines)))
        avg_operations = float(stats.get("avg_op_count", 1.0))
        k_base = num_machines * avg_operations
        k_stress = k_base / 100.0
        
        downtime_by_machine: Dict[str, List[Tuple[float, float]]] = {}
        for e in self.events:
            if e.event_type == "BREAKDOWN" or e.event_type == "PREVENTIVE_MAINTENANCE":
                downtime_by_machine.setdefault(e.machine_id, []).append((e.time, e.time + e.duration))

        # Apply repair completions to shorten downtime
        for e in self.events:
            if e.event_type == "REPAIR_COMPLETION" and e.machine_id in downtime_by_machine:
                intervals = downtime_by_machine[e.machine_id]
                for i, (start, end) in enumerate(intervals):
                    if start <= e.time < end:
                        intervals[i] = (start, e.time)
                        logger.debug(f"Repair event shortened downtime on {e.machine_id} from {end} to {e.time}")
                        break

        # Merge overlaps and aggregate speed-weighted downtime capacity
        machine_speed_map = {m.id: getattr(m, "speed", 1.0) for m in self.model.plant.machines}
        total_downtime_cap = 0.0
        for machine_id, intervals in downtime_by_machine.items():
            if not intervals:
                continue
            intervals.sort()
            merged: List[Tuple[float, float]] = []
            for start, end in intervals:
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            sp = machine_speed_map.get(machine_id, 1.0)
            total_downtime_cap += sum(end - start for start, end in merged) * sp

        total_capacity = self.model.scale.horizon * sum(getattr(m, "speed", 1.0) for m in self.model.plant.machines)
        observed_disturbance = total_downtime_cap / total_capacity if total_capacity > 0 else 0.0

        raw_disturbance_target = getattr(self.model.targets, "disturbance", 0.0)
        if isinstance(raw_disturbance_target, list):
            s_design = float(raw_disturbance_target[0]) if raw_disturbance_target else 0.0
        else:
            s_design = float(raw_disturbance_target or 0.0)

        c_norm = 0.0
        if c_stress > 0.0 and _SSI_LOG1P_C_MAX > 0.0:
            c_clipped = min(c_stress, SSI_C_MAX)
            c_norm = float(np.log1p(c_clipped) / _SSI_LOG1P_C_MAX)

        p_norm = 0.0
        if p_stress > 0.0 and _SSI_LOG1P_P_MAX > 0.0:
            p_clipped = min(p_stress, SSI_P_MAX)
            p_norm = float(np.log1p(p_clipped) / _SSI_LOG1P_P_MAX)

        k_norm = 0.0
        if SSI_K_MAX > 0.0:
            k_norm = max(0.0, min(k_base / SSI_K_MAX, 1.0))

        s_norm = 0.0
        if SSI_S_MAX > 0.0:
            s_norm = max(0.0, min(s_design / SSI_S_MAX, 1.0))

        total_weight = 4.0
        difficulty_raw = (c_norm + p_norm + k_norm + s_norm) / total_weight if total_weight > 0.0 else 0.0
        difficulty_score = float(max(0.0, min(difficulty_raw, 1.0)) * 100.0)

        if difficulty_raw < 1.0 / 3.0:
            difficulty_category = "easy"
        elif difficulty_raw < 2.0 / 3.0:
            difficulty_category = "medium"
        else:
            difficulty_category = "hard"

        return {
            "SSI": {"C": c_stress, "P": p_stress, "K": k_stress, "S": s_design},
            "SSI_norm": {"C": c_norm, "P": p_norm, "K": k_norm, "S": s_norm},
            "difficulty_score": difficulty_score,
            "difficulty_category": difficulty_category,
            "disturbance": observed_disturbance,
        }
