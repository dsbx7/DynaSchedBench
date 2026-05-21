from __future__ import annotations

from typing import Dict, List, Tuple, Optional
import copy
import numpy as np
from loguru import logger

from ..models.inputs import InputModel
from ..models.events import (
    Event,
    ArrivalEvent,
    DueDateEvent,
    BreakdownEvent,
    PreventiveMaintenanceEvent,
    MachineRepairCompletionEvent,
)


# Global RNG registry to preserve determinism while ensuring successive strategy
# invocations explore different samples (important because strategies are
# reinstantiated on every calibration step).
_RNG_COUNTERS: Dict[Tuple[str, int], int] = {}


def _get_rng(label: str, base_seed: int) -> np.random.Generator:
    """Return a reproducible yet stateful RNG for strategy adjustments.

    We key the sequence by (label, base_seed). Each call advances the counter so
    repeated invocations (even across new strategy instances) receive distinct
    streams while remaining reproducible for a fixed test order.
    """

    key = (label, base_seed)
    offset = _RNG_COUNTERS.get(key, 0)
    _RNG_COUNTERS[key] = offset + 1
    return np.random.default_rng(base_seed + offset)


class AdjustmentStrategy:
    """Base interface for calibration strategies."""

    name: str = "base"

    def __init__(self, damping: float = 0.6):
        self.damping = damping

    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        raise NotImplementedError


class ArrivalRateStrategy(AdjustmentStrategy):
    """Jointly adjust inter-arrival times to steer ``rho_global`` and ``scv_a``.

    The current strategy samples multiple candidates for stability, uses
    adaptive damping based on error magnitude, balances utilization and arrival
    variability, and handles fixed-job-count cases explicitly.
    """

    name = "arrival_rate"

    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        rng = _get_rng("arrival_rate", model.meta.seed + 101)
        target_rho = float(targets.get("rho_global", 0.0))
        observed_rho = float(observed.get("rho_global", 0.0))
        target_scv_a = float(targets.get("scv_a", 0.0))
        
        if target_rho <= 0:
            logger.debug(f"ArrivalRateStrategy: target_rho={target_rho} <= 0, skipping adjustment")
            return events
        if observed_rho <= 0:
            return events
        
        if model.scale.jobs_total is not None:
            logger.warning(
                f"jobs_total={model.scale.jobs_total} is set; this prevents rho_global adjustment"
            )
        
        if target_scv_a > 10.0:
            logger.warning(f"ArrivalRateStrategy: extreme target_scv_a={target_scv_a} > 10, capping at 10")
            target_scv_a = 10.0
        
        error_ratio_rho = target_rho / observed_rho
        rho_rel_error = abs(error_ratio_rho - 1.0)

        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if len(arrs) < 2:
            return events
        
        if rho_rel_error > 0.05:
            
            target_n_jobs = int(len(arrs) * (target_rho / observed_rho))
            target_n_jobs = max(5, min(target_n_jobs, int(len(arrs) * 1.5)))
            
            logger.info(
                f"jobs_total fixed scenario: adjusting number of jobs {len(arrs)} -> "
                f"{target_n_jobs} (ratio={error_ratio_rho:.3f})"
            )
            
            if target_n_jobs < len(arrs):
                keep_indices = rng.choice(len(arrs), size=target_n_jobs, replace=False)
                new_arrs = [arrs[i] for i in sorted(keep_indices)]
                
                kept_job_ids = {e.job_id for e in new_arrs}
                events = [
                    e
                    for e in events
                    if (
                        (not isinstance(e, ArrivalEvent))
                        and (
                            (not hasattr(e, "job_id"))
                            or (getattr(e, "job_id") in kept_job_ids)
                        )
                    )
                ]
                events.extend(new_arrs)
                events.sort(key=lambda x: x.time)
                
                logger.info(
                    f"Removed {len(arrs) - target_n_jobs} jobs after adjusting jobs_total"
                )
                return events
                
            elif target_n_jobs > len(arrs):
                n_to_add = target_n_jobs - len(arrs)
                source_indices = rng.choice(len(arrs), size=n_to_add, replace=True)

                def _extract_job_index(jid: object) -> Optional[int]:
                    s = str(jid)
                    if s.startswith("Job-"):
                        core = s[4:]
                        core = core.split("-B", 1)[0]
                        try:
                            return int(core)
                        except ValueError:
                            pass
                    if s.startswith("J_"):
                        try:
                            return int(s[2:])
                        except ValueError:
                            pass
                    if s.startswith("J"):
                        try:
                            return int(s[1:])
                        except ValueError:
                            pass
                    if s.startswith("WIP-"):
                        try:
                            return int(s[4:])
                        except ValueError:
                            pass
                    return None

                existing_ids: List[int] = []
                for e in events:
                    if hasattr(e, "job_id"):
                        idx = _extract_job_index(getattr(e, "job_id"))
                        if idx is not None:
                            existing_ids.append(idx)

                if existing_ids:
                    max_id = max(existing_ids)
                else:
                    max_id = len(arrs)

                existing_job_ids = {str(getattr(e, "job_id")) for e in events if hasattr(e, "job_id")}

                max_time = max(e.time for e in arrs)
                times_array = np.array([e.time for e in arrs])
                mean_ia = float(np.mean(np.diff(np.sort(times_array)))) if len(times_array) > 1 else 10.0

                new_arrivals = []
                new_duedates = []

                next_id = max_id
                for idx in range(n_to_add):
                    source_event = arrs[source_indices[idx]]
                    new_event = copy.deepcopy(source_event)

                    while True:
                        next_id += 1
                        candidate_id = f"Job-{next_id}"
                        if candidate_id not in existing_job_ids:
                            existing_job_ids.add(candidate_id)
                            break

                    new_event.job_id = candidate_id
                    new_event.time = max_time + mean_ia * (idx + 1)
                    new_arrivals.append(new_event)

                    for e in events:
                        if isinstance(e, DueDateEvent) and e.job_id == source_event.job_id:
                            new_due_event = copy.deepcopy(e)
                            new_due_event.job_id = new_event.job_id
                            new_due_event.time = new_event.time
                            slack = e.due_date - source_event.time
                            new_due_event.due_date = new_event.time + slack
                            new_duedates.append(new_due_event)
                            break

                events.extend(new_arrivals)
                events.extend(new_duedates)
                events.sort(key=lambda x: x.time)

                logger.info(
                    f"Added {n_to_add} jobs (arrival + due date events) for jobs_total adjustment"
                )
                return events
            
            non_arr_events = [e for e in events if not isinstance(e, ArrivalEvent)]
            events = non_arr_events + arrs
            events.sort(key=lambda x: x.time)
            
            arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        
        times = np.array([e.time for e in arrs], dtype=float)
        current_mean_ia = float(np.mean(np.diff(times)))
        
        if current_mean_ia <= 0:
            logger.warning(f"ArrivalRateStrategy: current_mean_ia={current_mean_ia} <= 0, skipping adjustment")
            return events
        
        adaptive_damping = self.damping
        if rho_rel_error < 0.15:
            adaptive_damping = max(0.5, self.damping * 0.8)
            logger.debug(
                f"Small error regime: reducing damping to {adaptive_damping:.2f} for higher precision"
            )
        elif rho_rel_error > 0.5:
            adaptive_damping = min(0.95, self.damping * 1.2)
        
        # Damped scaling of mean IA to avoid overshoot
        target_mean_ia = current_mean_ia * (1.0 / (1.0 + (error_ratio_rho - 1.0) * adaptive_damping))
        n_ia = len(arrs) - 1
        
        if target_scv_a == 0.0:
            new_ia = np.full(n_ia, target_mean_ia, dtype=float)
        else:
            shape_k = 1.0 / target_scv_a
            scale_th = target_mean_ia / shape_k
            
            n_candidates = 20
            best_ia = None
            best_score = float('inf')
            best_mean_err = 1.0
            best_scv_err = 1.0
            
            for candidate_idx in range(n_candidates):
                candidate_ia = rng.gamma(shape_k, scale_th, size=n_ia).astype(float)
                
                candidate_mean = np.mean(candidate_ia)
                candidate_std = np.std(candidate_ia)
                candidate_scv = (candidate_std / candidate_mean) ** 2 if candidate_mean > 0 else 0
                
                mean_error = abs(candidate_mean - target_mean_ia) / max(target_mean_ia, 1e-9)
                scv_error = abs(candidate_scv - target_scv_a) / max(target_scv_a, 0.1)
                
                combined_score = mean_error * 3.0 + scv_error * 1.0
                
                if combined_score < best_score:
                    best_score = combined_score
                    best_ia = candidate_ia
                    best_mean_err = mean_error
                    best_scv_err = scv_error
            
            if best_ia is not None:
                actual_mean = np.mean(best_ia)
                if actual_mean > 0:
                    scaling_factor = target_mean_ia / actual_mean
                    new_ia = best_ia * scaling_factor
                    logger.debug(
                        "Dual-objective sampling and normalization: "
                        f"mean_error={best_mean_err:.4f}, scv_error={best_scv_err:.4f}, "
                        f"scaling={scaling_factor:.4f}"
                    )
                else:
                    new_ia = best_ia
            else:
                new_ia = rng.gamma(shape_k, scale_th, size=n_ia).astype(float)
        new_times = np.zeros_like(times)
        new_times[0] = times[0]
        new_times[1:] = np.cumsum(new_ia) + new_times[0]

        horizon_limit = float(model.scale.horizon) * 0.98
        if new_times[-1] > horizon_limit:
            shift = new_times[-1] - horizon_limit
            new_times = np.maximum(new_times - shift, 0.0)
        
        # Apply back to arrival events
        old_to_new_time = {}
        for i, ev in enumerate(arrs):
            old_time = ev.time
            new_time = float(np.round(new_times[i], 4))
            old_to_new_time[ev.job_id] = (old_time, new_time)
            ev.time = new_time
        
        new_mean_ia_actual = float(np.mean(np.diff([e.time for e in arrs]))) if len(arrs) > 1 else 0
        logger.debug(
            f"Adjustment complete: target mean_ia={target_mean_ia:.4f}, "
            f"actual mean_ia={new_mean_ia_actual:.4f}"
        )
        
        # Update corresponding DueDateEvents
        # Need to adjust both the time field and preserve relative slack
        for ev in events:
            if isinstance(ev, DueDateEvent) and ev.job_id in old_to_new_time:
                old_arr, new_arr = old_to_new_time[ev.job_id]
                time_shift = new_arr - old_arr
                
                # Update the time when due date is set
                ev.time = new_arr
                
                # Shift the due_date by the same amount to preserve slack
                ev.due_date = float(np.round(ev.due_date + time_shift, 4))
        
        return events


class DueDateStrategy(AdjustmentStrategy):
    """Adjust due dates multiplicatively to steer DDT (enhanced with progressive constraint relaxation)."""

    name = "due_date"
    
    def __init__(self, damping: float = 0.75):
        super().__init__(damping)
        self.constraint_history: List[Dict[str, int]] = []

    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        t_ddt = float(targets.get("ddt", 0.0))
        o_ddt = float(observed.get("ddt", 0.0))
        
        if t_ddt <= 0:
            logger.warning(f"DueDateStrategy: target_ddt={t_ddt} <= 0, skipping adjustment")
            return events
        if o_ddt == 0:
            return events
        
        ratio = t_ddt / o_ddt
        ddt_rel_error = abs(ratio - 1.0)
        
        arr_map = {e.job_id: e for e in events if isinstance(e, ArrivalEvent)}
        
        if not arr_map:
            logger.warning("DueDateStrategy: no arrival events found, skipping adjustment")
            return events
        
        horizon = float(model.scale.horizon)
        
        adaptive_damping = self.damping
        if ddt_rel_error < 0.12:
            adaptive_damping = max(0.50, self.damping * 0.7)
            logger.debug(
                f"Small error regime: reducing ddt damping to {adaptive_damping:.2f} for higher precision"
            )
        elif ddt_rel_error > 0.30:
            adaptive_damping = min(0.90, self.damping * 1.1)
        
        safety_factor = self._calculate_safety_factor(t_ddt, ratio)
        EXTREME_DDT_ERROR = 0.50
        
        # Track violations for logging
        violations_prevented = 0
        violations_relaxed = 0
        
        for ev in events:
            if isinstance(ev, DueDateEvent):
                arr_ev = arr_map.get(ev.job_id)
                if arr_ev is None:
                    continue
                
                total_work = sum(arr_ev.process_times) if hasattr(arr_ev, 'process_times') else 0.0
                min_slack = max(1.0, total_work * safety_factor)
                
                slack = ev.due_date - arr_ev.time
                if total_work <= 0.0:
                    continue

                if ddt_rel_error > EXTREME_DDT_ERROR:
                    new_slack = t_ddt * total_work
                else:
                    new_slack = slack * (1 + (ratio - 1) * adaptive_damping)
                
                if new_slack < min_slack:
                    if self._can_relax_constraint(t_ddt, violations_relaxed, len(arr_map)):
                        relaxed_min_slack = min_slack * 0.95
                        new_slack = max(new_slack, relaxed_min_slack)
                        violations_relaxed += 1
                        logger.debug(
                            f"Job {ev.job_id}: relaxed min_slack from {min_slack:.2f} "
                            f"to {relaxed_min_slack:.2f}"
                        )
                    else:
                        new_slack = min_slack
                        violations_prevented += 1
                
                new_due = arr_ev.time + new_slack
                
                if new_due <= arr_ev.time:
                    new_due = arr_ev.time + min_slack
                    violations_prevented += 1
                
                max_due = horizon * 0.98
                if new_due > max_due:
                    new_due = max_due
                    violations_prevented += 1
                
                ev.due_date = float(np.round(new_due, 4))
        
        self.constraint_history.append({
            'prevented': violations_prevented,
            'relaxed': violations_relaxed
        })
        
        if violations_prevented > 0 or violations_relaxed > 0:
            logger.debug(f"DueDateStrategy: prevented={violations_prevented}, relaxed={violations_relaxed}")
        
        return events
    
    def _calculate_safety_factor(self, target_ddt: float, ratio: float) -> float:
        """Compute a dynamic safety factor.

        Tight due-date scenarios use a smaller factor to permit more aggressive
        adjustment.

        Args:
            target_ddt: Target DDT value.
            ratio: Target-to-observed ratio.

        Returns:
            Safety factor, usually between 1.03 and 1.10.
        """
        if target_ddt < 1.3:
            base_factor = 1.03
        elif target_ddt < 1.5:
            base_factor = 1.05
        elif target_ddt < 2.0:
            base_factor = 1.08
        else:
            base_factor = 1.1
        
        if abs(ratio - 1.0) > 0.25:
            base_factor *= 0.97
        
        logger.debug(f"Safety factor for ddt={target_ddt:.2f}: {base_factor:.3f}")
        
        return base_factor
    
    def _can_relax_constraint(self, target_ddt: float, current_relaxed: int, total_jobs: int) -> bool:
        """Return whether due-date constraints may be relaxed.

        Relaxation is allowed only for tight due-date scenarios and is capped as
        a fraction of total jobs.

        Args:
            target_ddt: Target DDT value.
            current_relaxed: Number of jobs already relaxed.
            total_jobs: Total number of jobs.

        Returns:
            True if another constraint can be relaxed.
        """
        if target_ddt >= 1.5:
            return False
        
        max_relaxations = max(1, int(total_jobs * 0.1))
        
        return current_relaxed < max_relaxations


class PTimeVariabilityStrategy(AdjustmentStrategy):
    """Regenerate process times with the target SCV while keeping mean stable."""

    name = "ptime_variability"

    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        rng = _get_rng("ptime_variability", model.meta.seed + 102)
        t_scv = float(targets.get("scv_p", 0.0))

        if t_scv > 10.0:
            logger.warning(f"PTimeVariabilityStrategy: extreme target_scv_p={t_scv} > 10, capping at 10")
            t_scv = 10.0

        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if not arrs:
            logger.warning("PTimeVariabilityStrategy: no arrival events found, skipping adjustment")
            return events

        all_pt = [pt for e in arrs for pt in e.process_times]
        if not all_pt:
            return events
        mean_pt = float(np.mean(all_pt))

        if mean_pt <= 0:
            logger.warning(f"PTimeVariabilityStrategy: mean_pt={mean_pt} <= 0, skipping adjustment")
            return events

        # target_scv == 0: fully deterministic processing times at global mean
        if t_scv == 0.0:
            for e in arrs:
                if not e.process_times:
                    continue
                e.process_times = [float(np.round(max(0.001, mean_pt), 4))] * len(e.process_times)
            return events

        # General case: use multi-candidate sampling over the full set of operations
        # to find a configuration whose global SCV is as close as possible to t_scv
        # while keeping the mean close to mean_pt.
        shape = 1.0 / t_scv
        scale = mean_pt / shape

        # Pre-compute per-job operation counts to reconstruct shapes
        job_lengths = [len(e.process_times) for e in arrs]
        total_ops = sum(job_lengths)
        if total_ops == 0:
            return events

        old_blocks: List[np.ndarray] = []
        for e in arrs:
            if not e.process_times:
                old_blocks.append(np.zeros(0, dtype=float))
            else:
                old_blocks.append(np.array(e.process_times, dtype=float))

        current_scv = float(observed.get("scv_p", t_scv)) if observed is not None else t_scv
        rel_error = abs(current_scv - t_scv) / max(t_scv, 0.1) if t_scv > 0 else 0.0
        if rel_error > 0.30:
            n_candidates = 60
            mean_weight = 1.5
            scv_weight = 2.0
        elif rel_error > 0.15:
            n_candidates = 40
            mean_weight = 2.0
            scv_weight = 1.5
        else:
            n_candidates = 20
            mean_weight = 2.5
            scv_weight = 1.0

        ddt_weight = 0.0
        t_ddt = float(targets.get("ddt", 0.0)) if targets is not None else 0.0
        current_ddt = float(observed.get("ddt", t_ddt)) if (observed is not None and t_ddt > 0.0) else t_ddt
        if t_ddt > 0.0 and current_ddt > 0.0:
            ddt_rel_err = abs(current_ddt - t_ddt) / max(t_ddt, 0.1)
            if ddt_rel_err < 0.10:
                ddt_weight = 1.5
            elif ddt_rel_err < 0.30:
                ddt_weight = 1.0
            else:
                ddt_weight = 0.3

        due_by_job: Dict[str, float] = {}
        if ddt_weight > 0.0:
            for ev in events:
                if isinstance(ev, DueDateEvent):
                    due_by_job[ev.job_id] = float(getattr(ev, "due_date", 0.0))
        best_blocks: List[np.ndarray] | None = None
        best_score = float("inf")
        best_mean_err = 1.0
        best_scv_err = 1.0

        for _ in range(n_candidates):
            # Sample a full candidate set of process times for all jobs
            candidate_blocks: List[np.ndarray] = []
            flat_samples: List[float] = []
            for length in job_lengths:
                if length == 0:
                    candidate_blocks.append(np.zeros(0, dtype=float))
                    continue
                block = rng.gamma(shape, scale, size=length).astype(float)
                candidate_blocks.append(block)
                flat_samples.extend(block.tolist())

            flat_arr = np.array(flat_samples, dtype=float)
            cand_mean = float(np.mean(flat_arr)) if flat_arr.size > 0 else 0.0
            cand_std = float(np.std(flat_arr)) if flat_arr.size > 0 else 0.0
            cand_scv = (cand_std / cand_mean) ** 2 if cand_mean > 0 else 0.0

            # Mean error: avoid distorting workload too much (rho_global stability)
            mean_error = abs(cand_mean - mean_pt) / max(mean_pt, 1e-9)
            # SCV error: primary objective for this strategy
            scv_error = abs(cand_scv - t_scv) / max(t_scv, 0.1)

            ddt_error = 0.0
            if ddt_weight > 0.0 and t_ddt > 0.0 and due_by_job:
                ddt_values: List[float] = []
                for arr_ev, block in zip(arrs, candidate_blocks):
                    if block.size == 0:
                        continue
                    due = due_by_job.get(arr_ev.job_id)
                    if due is None:
                        continue
                    total_pt = float(np.sum(block))
                    if total_pt <= 0.0:
                        continue
                    slack = float(due - float(arr_ev.time))
                    if slack <= 0.0:
                        continue
                    ddt_values.append(slack / max(total_pt, 1e-9))
                if ddt_values:
                    cand_ddt = float(np.mean(ddt_values))
                    ddt_error = abs(cand_ddt - t_ddt) / max(t_ddt, 0.1)

            # Combined score: trade off mean stability vs. SCV accuracy and, when appropriate, DDT stability
            combined_score = mean_error * mean_weight + scv_error * scv_weight
            if ddt_weight > 0.0:
                combined_score += ddt_error * ddt_weight

            if combined_score < best_score:
                best_score = combined_score
                best_blocks = candidate_blocks
                best_mean_err = mean_error
                best_scv_err = scv_error

        if best_blocks is None:
            # Fallback: single gamma draw per job (old behavior)
            for e in arrs:
                if not e.process_times:
                    continue
                block = rng.gamma(shape, scale, size=len(e.process_times)).astype(float)
                e.process_times = [float(np.round(max(0.001, pt), 4)) for pt in block]
            return events

        flat_best = np.concatenate(best_blocks) if best_blocks else np.zeros(0, dtype=float)
        if flat_best.size > 0:
            cand_mean = float(np.mean(flat_best))
            cand_std = float(np.std(flat_best))
            cand_scv = (cand_std / cand_mean) ** 2 if cand_mean > 0 else 0.0
            if t_scv > 0.0 and cand_mean > 0.0 and cand_scv > 0.0:
                scale_var = float(np.sqrt(t_scv / max(cand_scv, 1e-9)))
                for i in range(len(best_blocks)):
                    block = best_blocks[i]
                    if block.size == 0:
                        continue
                    best_blocks[i] = (block - cand_mean) * scale_var + cand_mean

        if rel_error > 0.5:
            alpha = 0.7
        elif rel_error > 0.3:
            alpha = 0.5
        elif rel_error > 0.15:
            alpha = 0.35
        else:
            alpha = 0.2

        logger.debug(
            "PTimeVariabilityStrategy: multi-candidate sampling summary: "
            f"rel_error={rel_error:.4f}, candidates={n_candidates}, "
            f"mean_error={best_mean_err:.4f}, scv_error={best_scv_err:.4f}"
        )

        for e, old_block, new_block in zip(arrs, old_blocks, best_blocks):
            if not e.process_times:
                continue
            if new_block.size == 0:
                continue
            if len(old_block) == new_block.size and old_block.size > 0:
                blended = old_block + (new_block - old_block) * alpha
            else:
                blended = new_block
            new_pts = [float(np.round(max(0.001, pt), 4)) for pt in blended]
            e.process_times = new_pts

        return events


class BottleneckDisturbanceStrategy(AdjustmentStrategy):
    """Adjust breakdown durations within target windows to steer windowed bottleneck rhos."""

    name = "bottleneck_disturbance"
    
    def __init__(self, damping: float = 0.6, allow_injection_when_empty: bool = False):
        super().__init__(damping)
        self.allow_injection_when_empty = allow_injection_when_empty

    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        # Pick the single window with largest absolute error
        if not model.targets.rho_bottleneck:
            return events

        horizon = model.scale.horizon
        rng = _get_rng("bottleneck", model.meta.seed + 103)
        # Precompute per-group workload totals (analytical)
        # Approximate from arrivals
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        
        if not arrs:
            logger.warning("BottleneckDisturbanceStrategy: no arrival events found, skipping adjustment")
            return events
        
        target_dist = float(targets.get("disturbance", 0.0)) if targets is not None else 0.0
        observed_dist = float(observed.get("disturbance", 0.0)) if observed is not None else 0.0
        if target_dist > 0.0:
            dist_signed_err = observed_dist - target_dist
            dist_rel_err = abs(dist_signed_err) / max(target_dist, 1e-6)
        else:
            dist_signed_err = observed_dist
            dist_rel_err = abs(observed_dist)

        workload_per_group: Dict[str, float] = {}
        for a in arrs:
            for i, g in enumerate(a.routing):
                workload_per_group[g] = workload_per_group.get(g, 0.0) + float(a.process_times[i])

        def window_obs_rho(group: str, t0: float, t1: float) -> float:
            length = max(0.0, t1 - t0)
            if length <= 0:
                return 0.0
            w_total = float(workload_per_group.get(group, 0.0))
            w_win = w_total * (length / max(1e-9, horizon))
            sum_speed = sum(getattr(m, "speed", 1.0) for m in model.plant.machines if m.group == group)
            down_cap = 0.0
            for m in model.plant.machines:
                if m.group != group:
                    continue
                for e in events:
                    if isinstance(e, BreakdownEvent) or isinstance(e, PreventiveMaintenanceEvent):
                        if e.machine_id == m.id:
                            s = e.time
                            e1 = e.time + e.duration
                            start = max(s, t0)
                            end = min(e1, t1)
                            if end > start:
                                down_cap += getattr(m, "speed", 1.0) * (end - start)
                    elif isinstance(e, MachineRepairCompletionEvent) and e.machine_id == m.id:
                        pass
            cap_eff = sum_speed * length - down_cap
            return w_win / cap_eff if cap_eff > 1e-12 else 0.0

        # Evaluate errors for each target
        errs: List[Tuple[float, Tuple[str, float, float, float, float]]] = []
        for bn in model.targets.rho_bottleneck:
            t0 = float(bn.time)
            t1 = float(bn.end_time if bn.end_time is not None else horizon)
            if t1 <= t0:
                continue
            obs = window_obs_rho(bn.group, t0, t1)
            target_rho = float(bn.rho)
            err = obs - target_rho
            errs.append((abs(err), (bn.group, t0, t1, err, target_rho)))
        
        if not errs:
            logger.warning("BottleneckDisturbanceStrategy: no valid bottleneck targets found, skipping adjustment")
            return events
        
        _, (group, t0, t1, signed_err, target_rho) = max(errs, key=lambda x: x[0])

        # Collect breakdowns in window for the target group
        group_machines = {m.id for m in model.plant.machines if m.group == group}
        bk: List[BreakdownEvent] = [e for e in events if isinstance(e, BreakdownEvent) and e.machine_id in group_machines and (t0 <= e.time <= t1)]

        # Decide adjustment magnitude relative to window length
        # Positive signed_err => observed > target (too high) -> increase downtime
        # Negative signed_err => observed < target (too low) -> reduce downtime
        adj_strength = min(0.25, 0.05 + 0.2 * (abs(signed_err)))  # cap aggressiveness
        if target_dist > 0.0 or observed_dist > 0.0:
            if (signed_err > 0 and dist_signed_err > 0) or (signed_err < 0 and dist_signed_err < 0):
                if dist_rel_err > 0.1:
                    if abs(signed_err) < 0.05:
                        logger.debug(
                            f"BottleneckDisturbanceStrategy: skipping small bottleneck correction due to large disturbance error "
                            f"(bn_err={signed_err:.3f}, dist_rel_err={dist_rel_err:.3f})"
                        )
                        return events
                    damp_factor = 1.0 / (1.0 + 3.0 * dist_rel_err)
                    adj_strength *= damp_factor
        if signed_err < 0:
            # reduce downtime - safe to reduce without overlap concerns
            if bk:
                for ev in bk:
                    old = ev.duration
                    ev.duration = max(1e-6, float(np.round(old * (1.0 - self.damping * adj_strength), 4)))
            else:
                # No breakdown events strictly inside the window. Try to reduce overlapping downtimes
                # within [t0, t1] by inserting early MachineRepairCompletionEvent(s).
                if group_machines:
                    speed_by_machine: Dict[str, float] = {m.id: getattr(m, "speed", 1.0) for m in model.plant.machines}
                    # Collect overlap segments (capacity-weighted)
                    overlaps: List[Tuple[float, str, float, float, float]] = []
                    # (cap_overlap, machine_id, overlap_start, overlap_end, sp)
                    for e in events:
                        if isinstance(e, BreakdownEvent) or isinstance(e, PreventiveMaintenanceEvent):
                            if e.machine_id in group_machines:
                                sp = max(1e-9, speed_by_machine.get(e.machine_id, 1.0))
                                s = float(e.time)
                                ed = float(e.time + e.duration)
                                ov_start = max(s, t0)
                                ov_end = min(ed, t1)
                                if ov_end > ov_start:
                                    cap_ov = (ov_end - ov_start) * sp
                                    overlaps.append((cap_ov, e.machine_id, ov_start, ov_end, sp))
                    total_cap_overlap = sum(x[0] for x in overlaps)
                    if total_cap_overlap > 0:
                        # Target reduction proportional to error strength (speed-weighted capacity units)
                        reduce_needed_cap = total_cap_overlap * (self.damping * adj_strength)
                        # Largest overlaps first for effective cuts
                        overlaps.sort(reverse=True, key=lambda x: x[0])
                        for cap_ov, mid, ov_start, ov_end, sp in overlaps:
                            if reduce_needed_cap <= 1e-9:
                                break
                            cap_cut = min(cap_ov, reduce_needed_cap)
                            time_cut = cap_cut / sp
                            # Place repair inside the overlap segment, near its end
                            t_repair = max(ov_start, ov_end - time_cut - 1e-6)
                            t_repair = min(t_repair, ov_end)
                            events.append(
                                MachineRepairCompletionEvent(
                                    time=float(np.round(t_repair, 4)),
                                    machine_id=mid,
                                )
                            )
                            reduce_needed_cap -= cap_cut
        else:
            # increase downtime - need to check for overlaps
            if bk:
                # Build a map of all breakdown events by machine for overlap checking
                breakdowns_by_machine: Dict[str, List[BreakdownEvent]] = {}
                for e in events:
                    if isinstance(e, BreakdownEvent) or isinstance(e, PreventiveMaintenanceEvent):
                        if e.machine_id not in breakdowns_by_machine:
                            breakdowns_by_machine[e.machine_id] = []
                        breakdowns_by_machine[e.machine_id].append(e)
                
                # Sort breakdowns by time for each machine
                for machine_id in breakdowns_by_machine:
                    breakdowns_by_machine[machine_id].sort(key=lambda x: x.time)
                
                overlap_prevented_count = 0
                for ev in bk:
                    old_duration = ev.duration
                    new_duration = old_duration * (1.0 + self.damping * adj_strength)
                    
                    # Check if increasing duration would cause overlap
                    machine_breakdowns = breakdowns_by_machine.get(ev.machine_id, [])
                    max_allowed_duration = new_duration
                    
                    # Find the next breakdown on the same machine
                    for other_ev in machine_breakdowns:
                        if other_ev.time > ev.time:
                            # Calculate maximum duration before hitting the next breakdown
                            gap = other_ev.time - ev.time
                            max_allowed_duration = min(max_allowed_duration, gap - 1e-6)  # Small buffer
                            break
                    win_gap = max(0.0, t1 - ev.time - 1e-6)
                    max_allowed_duration = min(max_allowed_duration, win_gap) if win_gap > 0 else max_allowed_duration
                    
                    # Apply the duration increase with overlap constraint
                    if max_allowed_duration < new_duration:
                        ev.duration = float(np.round(max(1e-6, max_allowed_duration), 4))
                        overlap_prevented_count += 1
                    else:
                        ev.duration = float(np.round(new_duration, 4))
                
                if overlap_prevented_count > 0:
                    logger.debug(f"Prevented {overlap_prevented_count} potential breakdown overlaps")
            else:
                # No breakdowns in window: optionally inject small non-overlapping breakdowns
                if self.allow_injection_when_empty and group_machines:
                    # Build speed maps
                    speed_by_machine: Dict[str, float] = {m.id: getattr(m, "speed", 1.0) for m in model.plant.machines}
                    sum_speed_group = float(sum(speed_by_machine[mid] for mid in group_machines))
                    window_len = t1 - t0
                    # Workload and current downtime capacity in window
                    total_w_g = float(workload_per_group.get(group, 0.0))
                    w_window = total_w_g * (window_len / max(1e-9, horizon))
                    # Current downtime capacity
                    down_cap = 0.0
                    breakdowns_by_machine: Dict[str, List[Tuple[float, float]]] = {mid: [] for mid in group_machines}
                    for e in events:
                        if isinstance(e, BreakdownEvent) or isinstance(e, PreventiveMaintenanceEvent):
                            if e.machine_id in breakdowns_by_machine:
                                s = float(e.time)
                                ed = float(e.time + e.duration)
                                # overlap with window
                                st = max(s, t0)
                                en = min(ed, t1)
                                if en > st:
                                    down_cap += speed_by_machine[e.machine_id] * (en - st)
                                    breakdowns_by_machine[e.machine_id].append((s, ed))
                    # Target capacity to remove
                    rho_t = 0.0
                    for bn in model.targets.rho_bottleneck:
                        if bn.group == group and abs(float(bn.time) - t0) < 1e-9 and float(bn.end_time if bn.end_time is not None else horizon) == t1:
                            rho_t = float(bn.rho)
                            break
                    rho_t = float(rho_t) if rho_t > 0 else 0.85  # fallback target if unspecified
                    cap_window = sum_speed_group * window_len
                    required_D = max(0.0, cap_window - (w_window / max(1e-9, rho_t)))
                    delta = max(0.0, required_D - down_cap) * (self.damping * adj_strength)
                    if delta > 1e-6:
                        # Heuristic event sizing akin to constructor
                        # Estimate avg breakdown duration via average work content
                        if arrs:
                            avg_wc = float(np.mean([sum(e.process_times) for e in arrs]))
                        else:
                            avg_wc = max(1.0, window_len * 0.1)
                        avg_breakdown_duration = max(1e-6, avg_wc * 0.5)
                        mean_speed_group = sum_speed_group / max(1, len(group_machines))
                        expected_n = float(delta / max(1e-9, avg_breakdown_duration * max(1e-6, mean_speed_group)))
                        n = max(1, int(rng.poisson(expected_n)))
                        weights_raw = np.maximum(1e-6, rng.exponential(1.0, size=n))
                        cap_amounts = (weights_raw / max(1e-9, float(np.sum(weights_raw)))) * delta
                        # Selection probabilities weighted by speed
                        machines_arr = np.array(sorted(list(group_machines)), dtype=object)
                        w = np.array([max(1e-9, speed_by_machine[mid]) for mid in machines_arr], dtype=float)
                        probs = (w / w.sum()) if w.sum() > 0 else None

                        placed_cap = 0.0
                        for cap_amt in cap_amounts:
                            # Choose machine
                            machine = rng.choice(machines_arr, p=probs) if probs is not None else rng.choice(machines_arr)
                            sp = max(1e-9, speed_by_machine.get(str(machine), 1.0))
                            dur_time = float(cap_amt / sp)
                            # Find a non-overlapping slot within [t0, t1]
                            intervals = sorted([(max(s, t0), min(e, t1)) for (s, e) in breakdowns_by_machine.get(str(machine), []) if min(e, t1) > max(s, t0)])
                            # Add window boundaries
                            cur = t0
                            placed = False
                            # gap before first
                            if not intervals:
                                max_len = max(0.0, t1 - t0)
                                place_len = min(dur_time, max(0.0, max_len - 1e-6))
                                if place_len > 1e-9:
                                    start = t0
                                    events.append(BreakdownEvent(time=float(np.round(start, 4)), machine_id=str(machine), duration=float(np.round(place_len, 4))))
                                    breakdowns_by_machine.setdefault(str(machine), []).append((start, start + place_len))
                                    placed_cap += sp * place_len
                                    placed = True
                            else:
                                # try gaps between intervals
                                for (s_int, e_int) in intervals:
                                    gap_len = max(0.0, s_int - cur)
                                    if gap_len > dur_time + 1e-6:
                                        start = cur
                                        events.append(BreakdownEvent(time=float(np.round(start, 4)), machine_id=str(machine), duration=float(np.round(dur_time, 4))))
                                        breakdowns_by_machine[str(machine)].append((start, start + dur_time))
                                        placed_cap += sp * dur_time
                                        placed = True
                                        break
                                    cur = max(cur, e_int)
                                if not placed:
                                    # try tail gap
                                    tail_gap = max(0.0, t1 - cur)
                                    if tail_gap > 1e-6:
                                        place_len = min(dur_time, max(0.0, tail_gap - 1e-6))
                                        if place_len > 1e-9:
                                            start = cur
                                            events.append(BreakdownEvent(time=float(np.round(start, 4)), machine_id=str(machine), duration=float(np.round(place_len, 4))))
                                            breakdowns_by_machine[str(machine)].append((start, start + place_len))
                                            placed_cap += sp * place_len
                                            placed = True
                            # stop early if enough capacity placed
                            if placed and placed_cap >= delta * 0.98:
                                break
                        if placed_cap > 0:
                            logger.debug(f"Injected breakdowns in empty window: cap={placed_cap:.4f}/{delta:.4f}, n~{n}")

        logger.info(f"Strategy[bottleneck]: adjusted group={group} window=({t0:.2f},{t1:.2f}) err={signed_err:+.3f}")
        return events


class LoadCVAdjustmentHistory:
    """Track load-CV adjustment history for divergence checks and fallback.

    The history records observed CV and action descriptions, detects consecutive
    worsening or oscillation, and tracks the best state for rollback.
    """
    
    def __init__(self, window_size: int = 5):
        """Initialize the history buffer.

        Args:
            window_size: History-window size used for divergence detection.
        """
        self.history: List[Tuple[float, str]] = []  # [(observed_cv, action_taken), ...]
        self.window_size = window_size
        self.best_cv: Optional[float] = None
        self.best_state_idx: Optional[int] = None
    
    def add(self, observed_cv: float, action: str) -> None:
        """Add one history record.

        Args:
            observed_cv: Observed load-CV value.
            action: Description of the action taken.
        """
        self.history.append((observed_cv, action))
        
        if len(self.history) > self.window_size:
            self.history.pop(0)
            if self.best_state_idx is not None and self.best_state_idx == 0:
                self.best_state_idx = None
                self.best_cv = None
    
    def is_diverging(self, current_cv: float, target_cv: float) -> bool:
        """Return whether the load-CV sequence appears to diverge.

        Args:
            current_cv: Current load-CV value.
            target_cv: Target load-CV value.

        Returns:
            True if divergence is detected.
        """
        if len(self.history) < 3:
            return False
        
        errors = [abs(cv - target_cv) for cv, _ in self.history[-3:]]
        errors.append(abs(current_cv - target_cv))
        
        if len(errors) >= 3:
            consecutive_increases = 0
            for i in range(len(errors) - 1):
                if errors[i+1] > errors[i] * 1.05:
                    consecutive_increases += 1
            
            if consecutive_increases >= 2:
                logger.debug(
                    f"Divergence check: error increased for {consecutive_increases} consecutive steps"
                )
                return True
        
        if len(self.history) >= 4:
            recent_errors = [abs(cv - target_cv) for cv, _ in self.history[-4:]]
            e1, e2, e3, e4 = recent_errors
            
            if (abs(e1 - e3) < 0.02 and abs(e2 - e4) < 0.02 and abs(e1 - e2) > 0.05):
                logger.debug(
                    "Divergence check: oscillation pattern detected "
                    f"(errors {e1:.3f} ↔ {e2:.3f})"
                )
                return True
        
        return False
    
    def update_best(self, cv: float, target_cv: float) -> None:
        """Update the best-state record.

        Args:
            cv: Current load-CV value.
            target_cv: Target load-CV value.
        """
        error = abs(cv - target_cv)
        if self.best_cv is None or error < abs(self.best_cv - target_cv):
            self.best_cv = cv
            self.best_state_idx = len(self.history) - 1
            logger.debug(f"Updated best state: cv={cv:.3f}, error={error:.3f}")
    
    def get_best_error(self, target_cv: float) -> Optional[float]:
        """Return the best historical load-CV error.

        Args:
            target_cv: Target load-CV value.

        Returns:
            Best error value, or ``None`` when no best state exists.
        """
        if self.best_cv is None:
            return None
        return abs(self.best_cv - target_cv)
    
    def reset(self) -> None:
        """Reset the history buffer."""
        self.history.clear()
        self.best_cv = None
        self.best_state_idx = None


class LoadBalanceStrategy(AdjustmentStrategy):
    """Adjust workload distribution to reach the target ``load_cv``.

    The strategy combines preprocessing, gradient optimization, and heuristic
    fine tuning. It also detects divergence, keeps the best known state, and can
    adjust job mix, routing, capacity exposure, and operation times.
    """
    
    name = "load_balance"
    
    def __init__(self, damping: float = 0.9):
        super().__init__(damping)
        self.sensitivity_cache: Dict[str, Dict[str, float]] = {}
        
        self.history = LoadCVAdjustmentHistory(window_size=5)
        self.best_events: Optional[List[Event]] = None
        self.best_cv: Optional[float] = None
        
        self._cv_cache: Dict[int, float] = {}  # events_hash -> cv
    
    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        """Adjust events with a three-stage strategy and divergence checks.

        Large errors use ``LoadCVPreprocessor`` for direction, medium errors use
        gradient optimization, and small errors use heuristic fine tuning. When
        consecutive worsening or oscillation is detected, the strategy can fall
        back to the best historical state.
        """
        target_cv = targets.get("load_cv")
        observed_cv = float(observed.get("load_cv", 0.0))
        
        if target_cv is None or target_cv < 0:
            logger.debug(f"LoadBalanceStrategy: target_cv={target_cv}, skipping adjustment")
            return events
        
        target_cv = float(target_cv)
        error = abs(observed_cv - target_cv)
        rel_error = error / max(target_cv, 0.05)
        
        if rel_error <= 0.08:
            logger.info(
                f"load_cv converged: {observed_cv:.3f} ≈ {target_cv:.3f} "
                f"(relative_error={rel_error:.1%})"
            )
            return events
        
        self.history.add(observed_cv, "before_adjustment")
        
        if self.history.is_diverging(observed_cv, target_cv):
            logger.warning(
                f"Detected divergence in load_cv adjustment "
                f"(current={observed_cv:.3f}, target={target_cv:.3f})"
            )
            
            if self.best_events is not None:
                best_error = abs(self.best_cv - target_cv) if self.best_cv is not None else float('inf')
                logger.warning(
                    f"Reverting to best historical state (cv={self.best_cv:.3f}, "
                    f"error={best_error:.3f})"
                )
                return self.best_events
            else:
                logger.error("No best historical state available; keeping current events unchanged")
                return events
        
        logger.info(
            f"Strategy[load_balance v3]: adjusting load_cv from {observed_cv:.3f} "
            f"to {target_cv:.3f} (relative_error={rel_error:.1%})"
        )
        
        if rel_error > 0.5:
            logger.info("Using level-1 strategy: preprocessor (error > 50%)")
            adjusted_events = self._use_preprocessor(events, model, target_cv)
        elif rel_error > 0.2:
            logger.info("Using level-2 strategy: gradient optimization (error 20–50%)")
            adjusted_events = self._gradient_based_optimization(events, model, target_cv)
        else:
            logger.info("Using level-3 strategy: heuristic fine-tuning (error < 20%)")
            adjusted_events = self._heuristic_fine_tuning(events, model, target_cv, observed_cv)
        
        new_cv = self._quick_estimate_load_cv(adjusted_events, model)
        new_error = abs(new_cv - target_cv)
        
        logger.info(
            f"After adjustment: cv={new_cv:.3f}, error={new_error:.3f} "
            f"(improvement={error-new_error:+.3f})"
        )
        
        if self.best_cv is None or new_error < abs(self.best_cv - target_cv):
            self.best_cv = new_cv
            self.best_events = copy.deepcopy(adjusted_events)
            self.history.update_best(new_cv, target_cv)
        
        return adjusted_events
    
    # def _internal_iteration_refinement(
    #     self,
    #     events: List[Event],
    #     model: InputModel,
    #     target_cv: float,
    # ) -> List[Event]:
        
    #     """
        
    #     for iteration in range(3):
    #         current_cv = self._quick_estimate_load_cv(events, model)
            
    #         error = abs(current_cv - target_cv)
    #         rel_error = error / max(target_cv, 0.05)

    #         stop_abs = max(0.005, target_cv * 0.2)
    #         stop_rel = 0.08
    #             logger.debug(
    #                     iteration + 1, current_cv, error, rel_error
    #                 )
    #             )
    #             break
            
    #         logger.debug(
    #                 iteration + 1, current_cv, target_cv, error, rel_error
    #             )
    #         )
            
    #         micro_damping = 0.3
    #         events = self._micro_adjust_routing(events, model, target_cv, current_cv, micro_damping)
        
    #     return events
    
    def _quick_estimate_load_cv(self, events: List[Event], model: InputModel) -> float:
        """Quickly estimate current load-CV without the full MetricsEngine.

        A small cache avoids repeated work for similar event states.
        """
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if not arrs:
            return 0.0
        
        try:
            events_hash = hash(tuple((e.job_id, e.time, tuple(e.routing)) for e in arrs[:min(len(arrs), 20)]))
            if events_hash in self._cv_cache:
                return self._cv_cache[events_hash]
        except (TypeError, AttributeError):
            events_hash = None
        
        workload_per_group: Dict[str, float] = {}
        for e in arrs:
            for i, group in enumerate(e.routing):
                if i < len(e.process_times):
                    workload_per_group[group] = workload_per_group.get(group, 0.0) + e.process_times[i]
        
        capacity_per_group: Dict[str, float] = {}
        for machine in model.plant.machines:
            capacity_per_group[machine.group] = capacity_per_group.get(machine.group, 0.0) + model.scale.horizon * getattr(machine, "speed", 1.0)
        
        rho_values = []
        for group in workload_per_group:
            if group in capacity_per_group and capacity_per_group[group] > 0:
                rho = workload_per_group[group] / capacity_per_group[group]
                rho_values.append(rho)
        
        if len(rho_values) < 2:
            cv = 0.0
        else:
            mean_rho = float(np.mean(rho_values))
            std_rho = float(np.std(rho_values))
            cv = std_rho / mean_rho if mean_rho > 0 else 0.0
        
        if events_hash is not None:
            self._cv_cache[events_hash] = cv
            if len(self._cv_cache) > 100:
                self._cv_cache.pop(next(iter(self._cv_cache)))
        
        return cv
    
    # def _micro_adjust_routing(
    #     self,
    #     events: List[Event],
    #     model: InputModel,
    #     target_cv: float,
    #     current_cv: float,
    #     micro_damping: float,
    # ) -> List[Event]:
    #     arrs = [e for e in events if isinstance(e, ArrivalEvent)]
    #     if not arrs:
    #         return events
        
    #     workload_per_group: Dict[str, float] = {}
    #     for e in arrs:
    #         for i, group in enumerate(e.routing):
    #             if i < len(e.process_times):
    #                 workload_per_group[group] = workload_per_group.get(group, 0.0) + e.process_times[i]
        
    #     if len(workload_per_group) < 2:
    #         return events
        
    #     sorted_groups = sorted(workload_per_group.items(), key=lambda x: x[1])
    #     if len(sorted_groups) < 2:
    #         return events
        
    #     low_load_group = sorted_groups[0][0]
    #     high_load_group = sorted_groups[-1][0]
        
    #     adjustment_prob = min(0.05, abs(current_cv - target_cv) * micro_damping)
        
    #     rng = _get_rng("load_micro", model.meta.seed + 202)
        
    #     for e in arrs:
    #         if rng.random() < adjustment_prob:
    #             new_routing = list(e.routing)
    #             modified = False
                
    #             if target_cv > current_cv:
    #                 for idx, group in enumerate(new_routing):
    #                     if group == low_load_group:
    #                         new_routing[idx] = high_load_group
    #                         modified = True
    #                         break
    #             else:
    #                 for idx, group in enumerate(new_routing):
    #                     if group == high_load_group:
    #                         new_routing[idx] = low_load_group
    #                         modified = True
    #                         break
                
    #             if modified:
    #                 e.routing = new_routing
        
    #     return events
    
    def _calculate_sensitivities(
        self,
        events: List[Event],
        model: InputModel,
    ) -> Dict[str, float]:
        """Estimate each job family's sensitivity to load-CV.

        Returns a normalized mapping such as ``{"F1": 0.35, "F2": 0.65}``,
        where values indicate relative influence on load-CV.
        """
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if not arrs:
            return {}
        
        current_cv = self._quick_estimate_load_cv(events, model)
        
        families = list(set(e.job_family for e in arrs))
        if len(families) < 2:
            return {families[0]: 1.0} if families else {}
        
        sensitivities = {}
        
        for family in families:
            family_arrs = [e for e in arrs if e.job_family == family]
            if not family_arrs:
                sensitivities[family] = 0.0
                continue
            
            modified_cv = self._estimate_cv_without_family_portion(arrs, model, family, ratio=0.1)
            
            sensitivity = abs(current_cv - modified_cv) / 0.1
            sensitivities[family] = sensitivity
        
        total = sum(sensitivities.values())
        if total > 0:
            sensitivities = {k: v / total for k, v in sensitivities.items()}
        else:
            sensitivities = {k: 1.0 / len(families) for k in families}
        
        logger.debug(f"Job family sensitivities: {sensitivities}")
        
        return sensitivities
    
    def _estimate_cv_without_family_portion(
        self,
        arrs: List[ArrivalEvent],
        model: InputModel,
        family: str,
        ratio: float,
    ) -> float:
        """Estimate load-CV after removing part of one family workload."""
        workload_per_group: Dict[str, float] = {}
        
        for e in arrs:
            scale = (1.0 - ratio) if e.job_family == family else 1.0
            for i, group in enumerate(e.routing):
                if i < len(e.process_times):
                    workload_per_group[group] = workload_per_group.get(group, 0.0) + e.process_times[i] * scale
        
        capacity_per_group: Dict[str, float] = {}
        for machine in model.plant.machines:
            capacity_per_group[machine.group] = capacity_per_group.get(machine.group, 0.0) + model.scale.horizon * getattr(machine, "speed", 1.0)
        
        rho_values = []
        for group in workload_per_group:
            if group in capacity_per_group and capacity_per_group[group] > 0:
                rho = workload_per_group[group] / capacity_per_group[group]
                rho_values.append(rho)
        
        if len(rho_values) < 2:
            return 0.0
        
        mean_rho = float(np.mean(rho_values))
        std_rho = float(np.std(rho_values))
        
        return std_rho / mean_rho if mean_rho > 0 else 0.0
    
    def _adjust_via_job_mix(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
        observed_cv: float,
    ) -> List[Event]:
        """Change load distribution by adjusting job-family mix using sensitivities."""
        if not model.plant.job_mix_weights or len(model.plant.process_templates) < 2:
            return events
        
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if not arrs:
            return events
        
        sensitivities = self._calculate_sensitivities(events, model)
        if not sensitivities:
            return events
        
        sorted_families = sorted(sensitivities.items(), key=lambda x: x[1], reverse=True)
        
        logger.debug(
            "Job families sorted by sensitivity: "
            f"{[(f, f'{s:.3f}') for f, s in sorted_families]}"
        )
        
        family_workload_per_group: Dict[str, Dict[str, float]] = {}
        for e in arrs:
            family = e.job_family
            if family not in family_workload_per_group:
                family_workload_per_group[family] = {}
            for i, group in enumerate(e.routing):
                if i < len(e.process_times):
                    family_workload_per_group[family][group] = \
                        family_workload_per_group[family].get(group, 0.0) + e.process_times[i]
        
        family_concentration: Dict[str, float] = {}
        for family, workload_dict in family_workload_per_group.items():
            if len(workload_dict) < 2:
                family_concentration[family] = 0.0
                continue
            loads = list(workload_dict.values())
            mean_load = float(np.mean(loads))
            std_load = float(np.std(loads))
            family_concentration[family] = std_load / mean_load if mean_load > 0 else 0.0
        
        base_adjustment_ratio = 0.12
        
        for family, sensitivity in sorted_families[:2]:
            if sensitivity < 0.1:
                continue
            
            family_arrs = [e for e in arrs if e.job_family == family]
            adjustment_count = int(len(family_arrs) * base_adjustment_ratio * sensitivity * self.damping)
            
            if adjustment_count == 0:
                continue
            
            concentration = family_concentration.get(family, 0.0)
            
            other_families = [f for f, _ in sorted_families if f != family]
            if not other_families:
                continue
            
            logger.debug(
                f"Adjusting family {family} (sensitivity={sensitivity:.3f}, "
                f"concentration={concentration:.3f}): {adjustment_count} jobs"
            )
            
            adjusted = 0
            for e in arrs:
                if adjusted >= adjustment_count:
                    break
                
                if e.job_family == family:
                    if target_cv < observed_cv:
                        if concentration > 0.15:
                            target_family = self._select_low_concentration_family(other_families, family_concentration)
                            if target_family:
                                e.job_family = target_family
                                adjusted += 1
                    else:
                        if concentration < 0.25:
                            target_family = self._select_high_concentration_family(other_families, family_concentration)
                            if target_family:
                                e.job_family = target_family
                                adjusted += 1
        
        return events
    
    def _select_low_concentration_family(
        self,
        candidates: List[str],
        concentration_map: Dict[str, float],
    ) -> Optional[str]:
        """Select a low-concentration family."""
        if not candidates:
            return None
        sorted_candidates = sorted(candidates, key=lambda f: concentration_map.get(f, 0.0))
        return sorted_candidates[0] if sorted_candidates else None
    
    def _select_high_concentration_family(
        self,
        candidates: List[str],
        concentration_map: Dict[str, float],
    ) -> Optional[str]:
        """Select a high-concentration family."""
        if not candidates:
            return None
        sorted_candidates = sorted(candidates, key=lambda f: concentration_map.get(f, 0.0), reverse=True)
        return sorted_candidates[0] if sorted_candidates else None
    
    def _adjust_via_routing(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
        observed_cv: float,
    ) -> List[Event]:
        """Balance load by rerouting operations across machine groups."""
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if not arrs:
            return events
        
        workload_per_group: Dict[str, float] = {}
        for e in arrs:
            for i, group in enumerate(e.routing):
                if i < len(e.process_times):
                    workload_per_group[group] = workload_per_group.get(group, 0.0) + e.process_times[i]
        
        if len(workload_per_group) < 2:
            return events
        
        capacity_per_group: Dict[str, float] = {}
        for m in model.plant.machines:
            capacity_per_group[m.group] = capacity_per_group.get(m.group, 0.0) + model.scale.horizon * getattr(m, "speed", 1.0)
        
        rho_per_group: Dict[str, float] = {
            g: (workload_per_group.get(g, 0.0) / capacity_per_group[g])
            for g in capacity_per_group if capacity_per_group[g] > 0
        }
        if len(rho_per_group) < 2:
            return events
        
        sorted_groups = sorted(rho_per_group.items(), key=lambda x: x[1])
        low_load_groups = [g for g, _ in sorted_groups[:len(sorted_groups)//2]]
        high_load_groups = [g for g, _ in sorted_groups[len(sorted_groups)//2:]]
        
        if not low_load_groups or not high_load_groups:
            return events
        
        rng = _get_rng("load_routing", model.meta.seed + 200)
        
        if target_cv > observed_cv:
            logger.debug(f"Increasing imbalance: redirecting work from {low_load_groups} to {high_load_groups}")
            adjustment_prob = min(0.15, (target_cv - observed_cv) * self.damping)
        else:
            logger.debug(f"Decreasing imbalance: redistributing work from {high_load_groups} to {low_load_groups}")
            adjustment_prob = min(0.15, (observed_cv - target_cv) * self.damping)
        
        for e in arrs:
            if rng.random() < adjustment_prob:
                new_routing = list(e.routing)
                modified = False
                
                if target_cv > observed_cv:
                    for idx, group in enumerate(new_routing):
                        if group in low_load_groups and high_load_groups:
                            new_routing[idx] = rng.choice(high_load_groups)
                            modified = True
                            break
                else:
                    for idx, group in enumerate(new_routing):
                        if group in high_load_groups and low_load_groups:
                            new_routing[idx] = rng.choice(low_load_groups)
                            modified = True
                            break
                
                if modified:
                    e.routing = new_routing
        
        return events
    
    def _adjust_via_arrival_distribution(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
        observed_cv: float,
    ) -> List[Event]:
        """Fine-tune load by changing arrival-time distributions across families."""
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if len(arrs) < 2:
            return events
        
        arrivals_by_family: Dict[str, List[ArrivalEvent]] = {}
        for e in arrs:
            if e.job_family not in arrivals_by_family:
                arrivals_by_family[e.job_family] = []
            arrivals_by_family[e.job_family].append(e)
        
        if len(arrivals_by_family) < 2:
            return events
        
        due_date_map: Dict[str, DueDateEvent] = {
            ev.job_id: ev for ev in events if isinstance(ev, DueDateEvent)
        }
        rng = _get_rng("load_arrival_dist", model.meta.seed + 201)
        horizon_limit = float(model.scale.horizon) * 0.98
        
        for family, family_arrs in arrivals_by_family.items():
            if len(family_arrs) < 2:
                continue
            
            times = np.array([e.time for e in family_arrs])
            
            if target_cv > observed_cv:
                adjustment_factor = 0.95
            else:
                adjustment_factor = 1.05
            
            mean_time = float(np.mean(times))
            for e, t in zip(family_arrs, times):
                delta = t - mean_time
                new_delta = delta * adjustment_factor
                new_time = float(np.round(min(horizon_limit, max(0.0, mean_time + new_delta)), 4))
                time_shift = new_time - e.time
                e.time = new_time

                due_event = due_date_map.get(e.job_id)
                if due_event is not None:
                    updated_time = float(np.round(max(0.0, due_event.time + time_shift), 4))
                    desired_due = due_event.due_date + time_shift
                    total_pt = sum(e.process_times) if e.process_times else 0.0
                    min_slack = max(0.5, total_pt * 0.1)
                    min_due = updated_time + min_slack
                    capped_due = min(desired_due, model.scale.horizon * 0.99)
                    if capped_due < min_due:
                        capped_due = min_due
                    due_event.time = updated_time
                    due_event.due_date = float(np.round(capped_due, 4))
        
        events.sort(key=lambda x: x.time)
        
        return events
    
    
    def _use_preprocessor(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
    ) -> List[Event]:
        """Stage 1: use ``LoadCVPreprocessor`` for directional guidance.

        The suggested weights are not applied directly because that can distort
        the distribution; they seed later gradient adjustment instead.
        """
        try:
            from ..core.load_cv_preprocessor import LoadCVPreprocessor
            
            preprocessor = LoadCVPreprocessor(model)
            optimal_weights = preprocessor.calculate_optimal_weights(target_cv)
            
            logger.debug(f"Preprocessor suggested weights: {optimal_weights}")
            
            logger.info(
                "Using preprocessor weights as the initial point; "
                "switching to gradient-based optimization"
            )
            return self._gradient_based_optimization(events, model, target_cv, initial_weights=optimal_weights)
        
        except Exception as e:
            logger.warning(
                f"Preprocessor failed: {e}, falling back to heuristic method"
            )
            # Fallback to heuristic
            return self._heuristic_fine_tuning(events, model, target_cv, self._quick_estimate_load_cv(events, model))
    
    def _gradient_based_optimization(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
        max_iter: int = 10,
        initial_weights: Optional[List[float]] = None,
    ) -> List[Event]:
        """Stage 2: optimize load-CV with numerical gradients.

        This stage is intended for medium errors. It optimizes job-mix
        proportions with an SLSQP objective based on squared load-CV error.
        """
        try:
            from scipy.optimize import minimize
            
            n_families = len(model.plant.process_templates)
            if n_families < 2:
                logger.debug(
                    "Only one job family; cannot optimize, falling back to heuristic method"
                )
                return self._heuristic_fine_tuning(events, model, target_cv, self._quick_estimate_load_cv(events, model))
            
            if initial_weights is not None and len(initial_weights) == n_families:
                current_weights = np.array(initial_weights, dtype=float)
                logger.debug(
                    f"Using preprocessor-provided initial weights: {current_weights}"
                )
            elif model.plant.job_mix_weights:
                current_weights = np.array(model.plant.job_mix_weights, dtype=float)
            else:
                current_weights = np.ones(n_families, dtype=float) / n_families
            
            best_eval_events = None
            best_eval_cv = float('inf')
            
            def objective(weights):
                nonlocal best_eval_events, best_eval_cv
                
                temp_events = self._apply_weights_to_events(events, model, target_cv, weights.tolist())
                cv = self._quick_estimate_load_cv(temp_events, model)
                
                error = abs(cv - target_cv)
                if error < abs(best_eval_cv - target_cv):
                    best_eval_cv = cv
                    best_eval_events = copy.deepcopy(temp_events)
                
                return (cv - target_cv) ** 2
            
            constraints = [
                {'type': 'eq', 'fun': lambda x: np.sum(x) - 1.0}
            ]
            
            bounds = [(0.01, 0.99) for _ in range(n_families)]
            
            logger.debug(
                "Starting gradient optimization: "
                f"initial_weights={current_weights}, target_cv={target_cv:.3f}"
            )
            
            result = minimize(
                objective,
                current_weights,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': max_iter, 'ftol': 1e-6, 'disp': False}
            )
            
            if result.success and best_eval_events is not None:
                logger.debug(
                    "Optimization succeeded: returning best evaluated result "
                    f"(cv={best_eval_cv:.4f})"
                )
                return best_eval_events
            else:
                logger.warning(
                    f"Optimization did not converge: {result.message}; "
                    "falling back to heuristic method"
                )
                return self._heuristic_fine_tuning(events, model, target_cv, self._quick_estimate_load_cv(events, model))
        
        except Exception as e:
            logger.warning(
                f"Gradient optimization failed: {e}; falling back to heuristic method"
            )
            return self._heuristic_fine_tuning(events, model, target_cv, self._quick_estimate_load_cv(events, model))
    
    def _heuristic_fine_tuning(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
        observed_cv: float,
    ) -> List[Event]:
        """Stage 3: perform heuristic fine tuning for small errors."""
        logger.debug("Using heuristic fine-tuning")
        
        original_damping = self.damping
        
        error = abs(observed_cv - target_cv)
        rel_error = error / max(target_cv, 0.05)
        
        if rel_error > 0.15:
            self.damping = min(0.95, self.damping * 1.1)
        
        events = self._adjust_via_job_mix(events, model, target_cv, observed_cv)
        events = self._adjust_via_routing(events, model, target_cv, observed_cv)
        events = self._adjust_via_arrival_distribution(events, model, target_cv, observed_cv)
        
        self.damping = original_damping
        
        for iteration in range(2):
            current_cv = self._quick_estimate_load_cv(events, model)
            prev_err = abs(current_cv - target_cv)
            if prev_err / max(target_cv, 0.05) < 0.05:
                break
            e1 = self._adjust_via_job_mix(events, model, target_cv, current_cv)
            cv1 = self._quick_estimate_load_cv(e1, model)
            err1 = abs(cv1 - target_cv)
            if err1 < prev_err * 0.995:
                events = e1
                continue
            d0 = self.damping
            self.damping = d0 * 0.5
            e2 = self._adjust_via_routing(e1, model, target_cv, cv1)
            cv2 = self._quick_estimate_load_cv(e2, model)
            err2 = abs(cv2 - target_cv)
            self.damping = d0
            if err2 < err1 * 0.995:
                events = e2
                continue
            self.damping = d0 * 0.5
            e3 = self._adjust_via_ptime_scaling(e2, model, target_cv, cv2)
            cv3 = self._quick_estimate_load_cv(e3, model)
            err3 = abs(cv3 - target_cv)
            self.damping = d0
            if err3 <= min(err1, err2):
                events = e3
            elif err2 <= min(err1, err3):
                events = e2
            else:
                events = e1
        
        return events
    
    def _apply_weights_to_events(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
        weights: List[float],
    ) -> List[Event]:
        """Use weights as directional guidance and adjust via process_time scaling (v3)."""
        logger.debug("Applying weight direction via process_time fine-tuning")
        
        current_cv = self._quick_estimate_load_cv(events, model)
        
        adjusted_events = self._adjust_via_ptime_scaling(events, model, float(target_cv), current_cv)
        
        return adjusted_events
    
    def _adjust_via_ptime_scaling(
        self,
        events: List[Event],
        model: InputModel,
        target_cv: float,
        observed_cv: float,
    ) -> List[Event]:
        """Change load distribution by fine-tuning process times.

        To reduce load-CV, increase process times on low-load groups and reduce
        them on high-load groups. To increase load-CV, apply the opposite move.
        """
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if not arrs:
            return events
        
        workload_per_group: Dict[str, float] = {}
        for e in arrs:
            for i, group in enumerate(e.routing):
                if i < len(e.process_times):
                    workload_per_group[group] = workload_per_group.get(group, 0.0) + e.process_times[i]
        
        if len(workload_per_group) < 2:
            return events
        
        capacity_per_group: Dict[str, float] = {}
        for m in model.plant.machines:
            capacity_per_group[m.group] = capacity_per_group.get(m.group, 0.0) + model.scale.horizon * getattr(m, "speed", 1.0)
        
        rho_per_group = {g: workload_per_group.get(g, 0) / capacity_per_group[g] 
                        for g in capacity_per_group if capacity_per_group[g] > 0}
        
        if not rho_per_group:
            return events
        
        mean_rho = np.mean(list(rho_per_group.values()))
        
        high_load_groups = [g for g, rho in rho_per_group.items() if rho > mean_rho]
        low_load_groups = [g for g, rho in rho_per_group.items() if rho <= mean_rho]
        
        logger.debug(
            f"High-load groups: {high_load_groups}, low-load groups: {low_load_groups}"
        )
        
        error = abs(observed_cv - target_cv)
        rel_error = error / max(target_cv, 0.05)
        
        if rel_error > 1.0:
            adjustment_magnitude = 0.05
        elif rel_error > 0.5:
            adjustment_magnitude = 0.08
        elif rel_error > 0.2:
            adjustment_magnitude = 0.12
        else:
            adjustment_magnitude = 0.15
        
        adjustment_magnitude *= self.damping
        
        if observed_cv > target_cv:
            scale_high = 1.0 - adjustment_magnitude * 0.5
            scale_low = 1.0 + adjustment_magnitude * 0.5
            logger.debug(
                "Reducing CV: high-load groups×"
                f"{scale_high:.3f}, low-load groups×{scale_low:.3f}, "
                f"magnitude={adjustment_magnitude:.3f}"
            )
        else:
            scale_high = 1.0 + adjustment_magnitude * 0.5
            scale_low = 1.0 - adjustment_magnitude * 0.3
            logger.debug(
                "Increasing CV: high-load groups×"
                f"{scale_high:.3f}, low-load groups×{scale_low:.3f}, "
                f"magnitude={adjustment_magnitude:.3f}"
            )
        
        n_adjusted = 0
        for e in arrs:
            for i, group in enumerate(e.routing):
                if i < len(e.process_times):
                    if group in high_load_groups:
                        new_val = float(np.round(max(0.001, e.process_times[i] * scale_high), 4))
                        e.process_times[i] = new_val
                        n_adjusted += 1
                    elif group in low_load_groups:
                        new_val = float(np.round(max(0.001, e.process_times[i] * scale_low), 4))
                        e.process_times[i] = new_val
                        n_adjusted += 1
        
        logger.debug(
            f"Adjusted process_time for {n_adjusted} operations across groups"
        )
        
        return events


class LoadCVPerGroupScalingStrategy(AdjustmentStrategy):
    """Scale operation times by machine group to reduce load-CV.

    This gentle fallback is useful when a single or very small number of process
    templates leaves too little freedom in job mix or routing. It estimates each
    group utilization, computes a damped scale factor around the mean, clips the
    factor to a conservative range, and applies it to operation times belonging
    to that group.
    """
    name = "load_cv_ptime_scale"

    def __init__(self, damping: float = 0.25):
        super().__init__(damping)

    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        arrs = [e for e in events if isinstance(e, ArrivalEvent)]
        if not arrs:
            return events
        workload_per_group: Dict[str, float] = {}
        for a in arrs:
            for i, g in enumerate(a.routing):
                if i < len(a.process_times):
                    workload_per_group[g] = workload_per_group.get(g, 0.0) + float(a.process_times[i])
        if not workload_per_group:
            return events
        horizon = float(model.scale.horizon)
        cap_per_group: Dict[str, float] = {}
        for m in model.plant.machines:
            cap_per_group[m.group] = cap_per_group.get(m.group, 0.0) + horizon * getattr(m, "speed", 1.0)
        rho_per_group: Dict[str, float] = {
            g: (workload_per_group.get(g, 0.0) / cap_per_group.get(g, 1e-9)) for g in workload_per_group.keys()
        }
        if not rho_per_group:
            return events
        rho_vals = list(rho_per_group.values())
        rho_mean = float(np.mean(rho_vals)) if rho_vals else 0.0
        if rho_mean <= 0:
            return events
        scale_per_group: Dict[str, float] = {}
        for g, rho_g in rho_per_group.items():
            diff = float(rho_g - rho_mean)
            rel = min(abs(diff) / max(rho_mean, 1e-9), 0.3)
            direction = -1.0 if diff > 0 else (1.0 if diff < 0 else 0.0)
            s_g = 1.0 + direction * self.damping * rel
            s_g = float(np.clip(s_g, 0.7, 1.3))
            scale_per_group[g] = s_g
        n_adjust = 0
        for a in arrs:
            for i, g in enumerate(a.routing):
                if i < len(a.process_times):
                    s = float(scale_per_group.get(g, 1.0))
                    new_pt = float(np.round(max(0.001, a.process_times[i] * s), 4))
                    a.process_times[i] = new_pt
                    n_adjust += 1
        logger.info(f"LoadCVPerGroupScaling: applied per-group scaling with damping={self.damping}, ops={n_adjust}")
        return events
class DisturbanceStrategy(AdjustmentStrategy):
    """Adjust machine breakdown rate independently to reach target disturbance."""
    
    name = "disturbance"
    
    def adjust(
        self,
        events: List[Event],
        model: InputModel,
        targets: Dict[str, float],
        observed: Dict[str, float],
    ) -> List[Event]:
        target_dist = float(targets.get("disturbance", 0.0))
        observed_dist = float(observed.get("disturbance", 0.0))
        
        if target_dist < 0:
            logger.warning(f"DisturbanceStrategy: negative target_dist={target_dist}, skipping adjustment")
            return events
        
        if target_dist > 0.5:
            logger.warning(f"DisturbanceStrategy: extreme target_dist={target_dist} > 0.5, system may be unstable")
        
        if target_dist == 0 and observed_dist == 0:
            return events
        
        breakdowns = [e for e in events if isinstance(e, BreakdownEvent)]
        pm_events = [e for e in events if e.event_type == "PREVENTIVE_MAINTENANCE"]
        
        if not breakdowns and not pm_events:
            if target_dist > 0:
                logger.warning(f"Cannot adjust disturbance: no breakdown events exist")
            return events
        
        if observed_dist > 0:
            ratio = target_dist / observed_dist
        else:
            ratio = 2.0 if target_dist > 0 else 1.0

        if target_dist > 0:
            dist_rel_err = abs(observed_dist - target_dist) / max(target_dist, 1e-6)
        else:
            dist_rel_err = abs(observed_dist)

        base_damping = float(self.damping)
        eff_damping = base_damping

        if dist_rel_err > 2.0:
            eff_damping *= 2.0
        elif dist_rel_err > 1.0:
            eff_damping *= 1.5
        elif dist_rel_err < 0.2:
            eff_damping *= 0.5

        eff_damping = float(np.clip(eff_damping, 0.2, 1.0))

        adj_factor = 1.0 + (ratio - 1.0) * eff_damping
        adj_factor = float(np.clip(adj_factor, 0.3, 1.7))

        logger.info(
            f"Strategy[disturbance]: adjusting durations by {adj_factor:.3f}x "
            f"(target={target_dist:.3f}, obs={observed_dist:.3f}, "
            f"rel_err={dist_rel_err:.3f}, base_damp={base_damping:.3f}, eff_damp={eff_damping:.3f})"
        )
        
        for ev in breakdowns:
            old_dur = ev.duration
            ev.duration = float(np.round(max(0.001, ev.duration * adj_factor), 4))
        
        for ev in pm_events:
            if hasattr(ev, 'duration'):
                ev.duration = float(np.round(max(0.001, ev.duration * adj_factor), 4))
        
        return events

