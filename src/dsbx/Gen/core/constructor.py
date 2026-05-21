"""Fast-path event constructor for DynaSchedBench instances."""

import numpy as np
import random
from typing import List, Dict, Tuple
from ..models.inputs import InputModel
from ..models.events import (
    ArrivalEvent, DueDateEvent, BreakdownEvent, Event,
    PriorityChangeEvent, OrderCancellationEvent,
    MachineRepairCompletionEvent, ProcessTimeChangeEvent,
    PreventiveMaintenanceEvent, RouteChangeEvent, DueDateChangeEvent
)
from .seed import SeedManager
from .load_cv_preprocessor import LoadCVPreprocessor
from loguru import logger

class FastPathConstructor:
    """
    Generates an event sequence, now including advanced dynamic events.
    """
    def __init__(self, model: InputModel, seed_manager: SeedManager):
        self.model = model
        self.sm = seed_manager
        self.arrival_rng = self.sm.get_rng("arrivals")
        self.ptime_rng = self.sm.get_rng("ptimes")
        self.routing_rng = self.sm.get_rng("routing")
        self.disturbance_rng = self.sm.get_rng("disturbances")
        # Add a new RNG for dynamic world events
        self.dynamic_rng = self.sm.get_rng("dynamic_world")

        self._apply_load_cv_preprocessing()

        self.avg_work_content = self._calculate_avg_work_content()
        self.num_machines = len(self.model.plant.machines)
        self.total_speed = sum(getattr(m, "speed", 1.0) for m in self.model.plant.machines)
        
        # Prepare job_mix_weights for template selection
        self.job_mix_weights = self.model.plant.job_mix_weights
        if self.job_mix_weights and len(self.job_mix_weights) != len(self.model.plant.process_templates):
            logger.warning(
                "job_mix_weights length does not match number of process templates; "
                "falling back to uniform distribution"
            )
            self.job_mix_weights = None
    
    def _apply_load_cv_preprocessing(self) -> None:
        """Apply load-CV preprocessing."""
        preprocessor = LoadCVPreprocessor(self.model)
        
        if preprocessor.should_preprocess():
            target_load_cv = float(self.model.targets.load_cv)
            logger.info(
                f"Starting Load CV preprocessing: target_load_cv={target_load_cv:.3f}"
            )
            
            optimal_weights = preprocessor.calculate_optimal_weights(target_load_cv)
            preprocessor.apply_optimal_weights(optimal_weights)

    @staticmethod
    def _as_float(val: float | List[float]) -> float:
        """Utility to coerce batchable values (float | List[float]) to a single float.
        If a list is provided, takes the first element.
        """
        if isinstance(val, list):
            return float(val[0]) if val else 0.0
        return float(val)
    
    def _select_template(self):
        """Select a job template while respecting job_mix_weights."""
        templates_arr = np.array(self.model.plant.process_templates, dtype=object)
        if self.job_mix_weights:
            return self.routing_rng.choice(templates_arr, p=self.job_mix_weights)
        else:
            return self.routing_rng.choice(templates_arr)

    def _calculate_avg_work_content(self) -> float:
        if not self.model.plant.process_templates: return 1.0
        
        if self.model.plant.job_mix_weights:
            weights = self.model.plant.job_mix_weights
            weighted_work = sum(
                weights[i] * sum(s.process_time.mean for s in t.route)
                for i, t in enumerate(self.model.plant.process_templates)
            )
            return weighted_work
        else:
            total_work = sum(sum(s.process_time.mean for s in t.route) for t in self.model.plant.process_templates)
            return total_work / len(self.model.plant.process_templates)
        
    def _resolve_arrival_rate(self) -> Tuple[float, int]:
        logger.info("FastPath Constructor: resolving arrival rate from current model...")
        horizon = float(self.model.scale.horizon)
        rho_g = self._as_float(self.model.targets.rho_global)
        lambda_rho = (rho_g * self.total_speed) / max(1e-9, self.avg_work_content)
        if self.model.scale.jobs_total:
            n_total = int(self.model.scale.jobs_total)
            lambda_n = n_total / max(1e-9, horizon)
            logger.debug(
                "Arrival rate (jobs_total-driven): "
                f"horizon={horizon:.3f}, rho_global={rho_g:.6f}, "
                f"avg_work_content={self.avg_work_content:.6f}, total_speed={self.total_speed:.6f}, "
                f"lambda_from_jobs={lambda_n:.6f}, n_total={n_total}"
            )
            return float(lambda_n), n_total
        else:
            n_total = int(max(1, round(lambda_rho * horizon)))
            logger.debug(
                "Arrival rate (rho-driven): "
                f"horizon={horizon:.3f}, rho_global={rho_g:.6f}, "
                f"avg_work_content={self.avg_work_content:.6f}, total_speed={self.total_speed:.6f}, "
                f"lambda_from_rho={lambda_rho:.6f}, n_total={n_total}"
            )
            return float(lambda_rho), n_total

    def _round_event_values(self, events: List[Event], precision: int = 4) -> List[Event]:
        """Rounds all float values within a list of events to a specified precision."""
        for event in events:
            # Round common time attributes
            event.time = round(event.time, precision)
            if hasattr(event, 'duration') and event.duration is not None:
                event.duration = round(event.duration, precision)
            if hasattr(event, 'due_date') and event.due_date is not None:
                event.due_date = round(event.due_date, precision)
            
            # Round list attributes like process_times
            if hasattr(event, 'process_times') and event.process_times is not None:
                event.process_times = [round(pt, precision) for pt in event.process_times]
        return events

    def generate_events(self) -> List[Event]:
        """Main method to generate the full event list using the new refactored flow."""
        events: List[Event] = []
        lambda_eff, n_total = self._resolve_arrival_rate()
        
        # Generate initial WIP jobs if warm start mode
        if self.model.evaluation.mode == "warm_start":
            logger.info("Warm start mode: generating initial WIP jobs...")
            initial_wip_events = self._generate_initial_wip_jobs()
            events.extend(initial_wip_events)
            logger.info(f"Generated {len(initial_wip_events)} initial WIP jobs")
        
        arrival_events = self._generate_arrival_events(lambda_eff, n_total)
        events.extend(arrival_events)
        events.extend(self._generate_due_date_events(arrival_events))
        
        health_events = self._generate_machine_health_events(arrival_events)
        events.extend(health_events)
        
        events.extend(self._generate_pm_events(events))
        
        events.extend(self._generate_dynamic_world_events(arrival_events))
        
        events = self._round_event_values(events)
        from .utils import sort_events_by_time
        events = sort_events_by_time(events)
        logger.info(f"FastPath Constructor: generated {len(events)} total events.")
        return events

    def _generate_machine_health_events(self, arrival_events: List[ArrivalEvent]) -> List[Event]:
        """Generate health events honoring global disturbance and time-windowed bottleneck targets.

        - Distribute global disturbance downtime across the full horizon.
        - For each BottleneckTarget window, add or reduce downtime in that window for the target group only.
        - All bottleneck-related events lie strictly within their windows.
        """
        health_events: List[Event] = []

        # Baseline stats
        horizon = self.model.scale.horizon
        workload_per_group = self._calculate_workload_per_group(arrival_events)
        groups = {m.group for m in self.model.plant.machines}
        machines_by_group: Dict[str, List[str]] = {g: [m.id for m in self.model.plant.machines if m.group == g] for g in groups}
        num_machines_by_group = {g: len(machines) for g, machines in machines_by_group.items()}
        speed_by_machine: Dict[str, float] = {m.id: getattr(m, "speed", 1.0) for m in self.model.plant.machines}
        sum_speed_by_group: Dict[str, float] = {g: sum(speed_by_machine[mid] for mid in machines) for g, machines in machines_by_group.items()}

        # Track breakdown intervals per machine for later window accounting
        breakdowns_by_machine: Dict[str, List[Tuple[float, float]]] = {m.id: [] for m in self.model.plant.machines}

        def _interval_overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
            """Return the length of overlap between intervals [a_start,a_end] and [b_start,b_end]."""
            start = max(a_start, b_start)
            end = min(a_end, b_end)
            return max(0.0, end - start)

        def _place_breakdown(machine_id: str, start: float, dur: float) -> None:
            """Record a breakdown interval and add the event to health_events."""
            end = start + dur
            breakdowns_by_machine[machine_id].append((start, end))
            health_events.append(BreakdownEvent(time=start, machine_id=machine_id, duration=dur))

        # 1) Global disturbance across the horizon
        disturbance = self._as_float(self.model.targets.disturbance)
        if disturbance > 0:
            # Calculate total downtime needed across ALL machines
            # disturbance = total_downtime / total_capacity
            # total_capacity = horizon * sum_speed_all
            # So: total_downtime = disturbance * horizon * sum_speed_all
            total_speed_all = sum(sum_speed_by_group.values()) or 1.0
            total_disturbance_downtime = horizon * total_speed_all * disturbance
            
            logger.info(
                f"Global disturbance target: {disturbance:.3f} -> "
                f"{total_disturbance_downtime:.2f} total downtime"
            )
            
            # NOTE: Global disturbance and bottleneck adjustments are handled independently:
            # - Global disturbance represents baseline system-wide failures
            # - Bottleneck adjustments are calibrated separately to achieve target utilization
            # This separation ensures both metrics can be met without interference
            if self.model.targets.rho_bottleneck:
                logger.info(
                    "Bottleneck targets detected. Calibration will adjust downtime "
                    "separately."
                )
                logger.info(
                    "Global disturbance events serve as the baseline for calibration."
                )
            
            # Distribute proportionally by number of machines per group
            # Use smaller breakdown duration to generate more frequent but shorter breakdowns
            # This ensures we have enough events to meet the disturbance target
            avg_breakdown_duration = max(1e-6, self.avg_work_content * 0.5)

            for group in groups:
                portion_cap = (sum_speed_by_group.get(group, 0.0) / total_speed_all) * total_disturbance_downtime
                if portion_cap <= 0:
                    continue
                target_machines = machines_by_group[group]
                if not target_machines:
                    continue
                # number of events heuristic using mean group speed
                mean_speed_group = sum_speed_by_group.get(group, 0.0) / max(1, len(target_machines))
                expected_n = portion_cap / max(1e-9, avg_breakdown_duration * max(1e-6, mean_speed_group))
                n = int(max(1, self.disturbance_rng.poisson(expected_n)))
                # Sample positive weights and scale to capacity amounts that sum to portion_cap
                weights_raw = np.maximum(1e-6, self.disturbance_rng.exponential(1.0, size=n))
                cap_amounts = (weights_raw / max(1e-9, np.sum(weights_raw))) * portion_cap
                # select machines weighted by speed
                probs = None
                if target_machines:
                    w = np.array([max(1e-9, speed_by_machine[mid]) for mid in target_machines], dtype=float)
                    probs = w / w.sum()
                for cap_amt in cap_amounts:
                    machine = self.disturbance_rng.choice(np.array(target_machines, dtype=object), p=probs if probs is not None else None)
                    sp = max(1e-9, speed_by_machine.get(machine, 1.0))
                    dur_time = float(cap_amt / sp)
                    # Sample a non-overlapping start when possible
                    max_tries = 20
                    for _ in range(max_tries):
                        t0 = float(self.disturbance_rng.uniform(0.0, max(1e-9, horizon - dur_time)))
                        has_overlap = any(_interval_overlaps(t0, t0 + dur_time, s, e) > 0 for s, e in breakdowns_by_machine[machine])
                        if not has_overlap:
                            _place_breakdown(machine, t0, dur_time)
                            break
                    else:
                        # Fallback: place even if overlapping
                        t0 = float(self.disturbance_rng.uniform(0.0, max(1e-9, horizon - dur_time)))
                        _place_breakdown(machine, t0, dur_time)

        # 2) Time-windowed bottleneck adjustments per target
        # Sort by start time to make sequential windows natural
        import heapq
        bn_targets = list(self.model.targets.rho_bottleneck)
        bn_targets = heapq.nsmallest(len(bn_targets), bn_targets, key=lambda t: t.time)
        # Use smaller breakdown duration for bottleneck adjustments too
        avg_breakdown_duration = max(1e-6, self.avg_work_content * 0.5)

        for bn in bn_targets:
            group = bn.group
            if group not in machines_by_group:
                continue
            start_t = float(bn.time)
            end_t = float(bn.end_time if bn.end_time is not None else horizon)
            if end_t <= start_t:
                continue
            window = (start_t, end_t)
            window_len = end_t - start_t

            # Workload and capacity in the window (assume stationary workloads)
            total_workload_g = float(workload_per_group.get(group, 0.0))
            workload_window = total_workload_g * (window_len / max(1e-9, horizon))
            cap_window = sum_speed_by_group.get(group, 0.0) * window_len

            # Required downtime to hit rho target in the window: D = S - W/rho
            rho_t = float(bn.rho)
            required_D = max(0.0, cap_window - (workload_window / max(1e-9, rho_t)))

            # Current downtime capacity in window from existing breakdowns
            current_D = 0.0
            for mid in machines_by_group[group]:
                sp_mid = max(1e-9, speed_by_machine.get(mid, 1.0))
                for s, e in breakdowns_by_machine[mid]:
                    ov = _interval_overlaps(s, e, start_t, end_t)
                    current_D += ov * sp_mid

            delta = required_D - current_D
            if delta > 1e-6:
                # Add breakdowns within [start_t, end_t] using capacity amounts
                target_machines = machines_by_group[group]
                if target_machines:
                    mean_speed_group = sum_speed_by_group.get(group, 0.0) / max(1, len(target_machines))
                else:
                    mean_speed_group = 1.0
                expected_n = delta / max(1e-9, avg_breakdown_duration * max(1e-6, mean_speed_group))
                n = max(1, int(self.disturbance_rng.poisson(expected_n)))
                w_raw = np.maximum(1e-6, self.disturbance_rng.exponential(1.0, size=n))
                cap_amounts = (w_raw / max(1e-9, np.sum(w_raw))) * delta
                probs = None
                if target_machines:
                    weights = np.array([max(1e-9, speed_by_machine[mid]) for mid in target_machines], dtype=float)
                    probs = weights / weights.sum()
                for cap_amt in cap_amounts:
                    machine = self.disturbance_rng.choice(np.array(target_machines, dtype=object), p=probs if probs is not None else None)
                    sp = max(1e-9, speed_by_machine.get(machine, 1.0))
                    dur_time = float(cap_amt / sp)
                    max_tries = 25
                    for _ in range(max_tries):
                        t0 = float(self.disturbance_rng.uniform(start_t, max(start_t, end_t - dur_time)))
                        # ensure non-overlap on the same machine inside the window
                        has_overlap = any(_interval_overlaps(t0, t0 + dur_time, s, e) > 0 for s, e in breakdowns_by_machine[machine])
                        if not has_overlap:
                            _place_breakdown(machine, t0, dur_time)
                            break
                    else:
                        t0 = float(self.disturbance_rng.uniform(start_t, max(start_t, end_t - dur_time)))
                        _place_breakdown(machine, t0, dur_time)
            elif delta < -1e-6:
                # Reduce downtime by adding early repair completions inside the window
                # Work in capacity units; convert to time per machine via speed
                reduce_needed_cap = -delta
                for mid in machines_by_group[group]:
                    if reduce_needed_cap <= 1e-9:
                        break
                    sp_mid = max(1e-9, speed_by_machine.get(mid, 1.0))
                    # Sort breakdowns by overlap length descending
                    overlap_list: List[Tuple[float, float, float]] = []
                    for (s, e) in breakdowns_by_machine[mid]:
                        ov_time = _interval_overlaps(s, e, start_t, end_t)
                        if ov_time > 0:
                            overlap_list.append((ov_time, s, e))
                    overlap_list.sort(reverse=True)
                    for ov_time, s, e in overlap_list:
                        if reduce_needed_cap <= 1e-9:
                            break
                        cap_overlap = ov_time * sp_mid
                        cap_cut = float(min(cap_overlap, reduce_needed_cap))
                        time_cut = cap_cut / sp_mid
                        # schedule repair inside overlap segment
                        overlap_start = max(s, start_t)
                        t_repair = min(e, overlap_start + time_cut - 1e-6)
                        new_end = min(e, t_repair)
                        try:
                            breakdowns_by_machine[mid].remove((s, e))
                        except ValueError:
                            pass
                        breakdowns_by_machine[mid].append((s, new_end))
                        health_events.append(MachineRepairCompletionEvent(time=float(t_repair), machine_id=mid))
                        reduce_needed_cap -= cap_cut

        # Done
        return health_events


    def _calculate_workload_per_group(self, arrival_events: List[ArrivalEvent]) -> Dict[str, float]:
        workload = {g: 0.0 for g in {m.group for m in self.model.plant.machines}}
        for job in arrival_events:
            for i, group in enumerate(job.routing):
                if group in workload:
                    workload[group] += job.process_times[i]
        return workload

    def _calculate_capacity_per_group(self) -> Dict[str, float]:
        capacity = {g: 0.0 for g in {m.group for m in self.model.plant.machines}}
        for machine in self.model.plant.machines:
            sp = getattr(machine, "speed", 1.0)
            capacity[machine.group] += self.model.scale.horizon * sp
        return capacity

    def _generate_arrival_events(self, arrival_rate: float, n_total: int) -> List[ArrivalEvent]:
        logger.info(f"FastPath Constructor: generating {n_total} arrival events...")
        events: List[ArrivalEvent] = []
        horizon = float(self.model.scale.horizon)
        
        effective_horizon = horizon * 0.98
        logger.debug(f"Using effective_horizon={effective_horizon:.2f} (98% of {horizon:.2f}) to prevent calibration overflow")
        
        mean_inter_arrival = 1.0 / max(1e-9, arrival_rate)

        scv_a = self._as_float(self.model.targets.scv_a)
        scv_p = self._as_float(self.model.targets.scv_p)

        # 1) Sample all inter-arrivals, then scale cumulative times to fit within [0, effective_horizon]
        inter_arrivals: List[float] = []
        if scv_a == 0:
            inter_arrivals = [mean_inter_arrival] * n_total
        else:
            shape = 1 / max(1e-9, scv_a)
            scale = mean_inter_arrival / shape
            inter_arrivals = list(self.arrival_rng.gamma(shape, scale, size=n_total).astype(float))

        cum_times = np.cumsum(inter_arrivals).astype(float)
        if len(cum_times) == 0:
            return events
        last_t = float(cum_times[-1])
        if last_t <= 0:
            # fallback safeguard
            cum_times = np.linspace(0.0, max(1e-6, effective_horizon), num=n_total, endpoint=True)
        else:
            # If the last arrival time overshoots effective_horizon, compress the time scale
            if last_t > effective_horizon:
                scale_factor = effective_horizon / last_t
                cum_times = cum_times * scale_factor

        # Ensure strictly increasing and clipped into [0, effective_horizon]
        cum_times = np.clip(cum_times, 0.0, effective_horizon)
        
        # Apply time-varying arrival pattern (v2.0 feature)
        cum_times = self._apply_arrival_pattern(cum_times, effective_horizon)

        for i, t in enumerate(cum_times, start=1):
            template = self._select_template()
            job_id = f"Job-{i}"
            process_times: List[float] = []
            for step in template.route:
                mean_pt = float(step.process_time.mean)
                if scv_p == 0:
                    pt = mean_pt
                else:
                    shape_p = 1 / max(1e-9, scv_p)
                    scale_p = mean_pt / shape_p
                    pt = float(self.ptime_rng.gamma(shape_p, scale_p))
                pt = max(0.001, pt)
                process_times.append(float(np.round(pt, 4)))

            events.append(
                ArrivalEvent(
                    time=float(np.round(t, 4)),
                    job_id=job_id,
                    job_family=template.family,
                    routing=[s.machine_group for s in template.route],
                    process_times=process_times,
                    batch_id=None,  # Will be set if expanded to batch
                    arrival_type="planned",
                )
            )
        
        # Note: Batch expansion is done AFTER calibration in cli.py
        # to avoid breaking calibration loops
        
        return events
    
    def _apply_arrival_pattern(self, arrival_times: np.ndarray, horizon: float) -> np.ndarray:
        """Apply the v2.0 Dynamics time-varying arrival pattern.

        Arrival times are modulated according to ``Dynamics.arrival_pattern`` so
        the effective arrival rate changes over time.

        Args:
            arrival_times: Raw arrival-time array.
            horizon: Simulation horizon.

        Returns:
            Modulated arrival-time array.
        """
        pattern = self.model.dynamics.arrival_pattern
        
        if pattern == "constant":
            return arrival_times
        
        amplitude = self.model.dynamics.arrival_amplitude
        if amplitude == 0:
            return arrival_times
        
        if pattern == "periodic":
            period = self.model.dynamics.arrival_period
            if period is None or period <= 0:
                period = horizon / 3
            
            logger.info(
                "Applying periodic arrival pattern: "
                f"amplitude={amplitude:.2f}, period={period:.1f}"
            )
            
            modulated_times = []
            for t in arrival_times:
                # rate_factor = 1 + A * sin(2πt/T)
                rate_factor = 1 + amplitude * np.sin(2 * np.pi * t / period)
                
                time_factor = 1.0 / rate_factor if rate_factor > 0.1 else 10.0
                
                modulated_t = t * time_factor
                modulated_times.append(modulated_t)
            
            modulated_times = np.array(modulated_times)
            if len(modulated_times) > 0 and modulated_times[-1] > 0:
                scale_factor = horizon / modulated_times[-1]
                modulated_times = modulated_times * scale_factor
            
            return np.clip(modulated_times, 0.0, horizon)
        
        elif pattern == "linear_trend":
            # t=0: λ = λ_base × (1-A)
            # t=horizon/2: λ = λ_base
            # t=horizon: λ = λ_base × (1+A)
            
            logger.info(
                "Applying linear-trend arrival pattern: "
                f"amplitude={amplitude:.2f} "
                f"({'increasing' if amplitude > 0 else 'decreasing'})"
            )
            
            modulated_times = []
            for t in arrival_times:
                trend_factor = 1 + amplitude * (2 * t / horizon - 1)
                
                time_factor = 1.0 / trend_factor if trend_factor > 0.1 else 10.0
                
                modulated_t = t * time_factor
                modulated_times.append(modulated_t)
            
            modulated_times = np.array(modulated_times)
            if len(modulated_times) > 0 and modulated_times[-1] > 0:
                scale_factor = horizon / modulated_times[-1]
                modulated_times = modulated_times * scale_factor
            
            return np.clip(modulated_times, 0.0, horizon)
        
        else:
            logger.warning(
                f"Unknown arrival_pattern: {pattern}; using 'constant' instead"
            )
            return arrival_times
    
    def _expand_batch_arrivals(self, arrivals: List[ArrivalEvent]) -> List[ArrivalEvent]:
        """Expand some single arrivals into batch arrivals.
        
        For each arrival, with probability batch_arrival_probability, 
        expand it into a batch of size ~ Normal(batch_size_mean, batch_size_std).
        """
        scenarios = self.model.dynamic_scenarios
        
        if scenarios.batch_arrival_probability <= 0:
            return arrivals
        
        logger.info(
            "FastPath Constructor: expanding batch arrivals "
            f"(prob={scenarios.batch_arrival_probability:.2f})..."
        )
        
        expanded_events: List[ArrivalEvent] = []
        batch_counter = 0
        scv_p = self._as_float(self.model.targets.scv_p)
        templates_arr = np.array(self.model.plant.process_templates, dtype=object)
        
        for arrival in arrivals:
            # Decide if this arrival becomes a batch
            if self.dynamic_rng.random() < scenarios.batch_arrival_probability:
                batch_counter += 1
                batch_id = f"Batch-{batch_counter}"
                
                # Sample batch size from normal distribution, minimum 2
                batch_size = max(2, int(round(self.dynamic_rng.normal(
                    scenarios.batch_size_mean,
                    scenarios.batch_size_std
                ))))
                
                # Add the original job with batch_id
                arrival.batch_id = batch_id
                expanded_events.append(arrival)
                
                # Generate additional jobs in the batch
                for j in range(1, batch_size):
                    # Use same or different template (randomly chosen)
                    template = self._select_template()
                    
                    # Generate process times
                    process_times: List[float] = []
                    for step in template.route:
                        mean_pt = float(step.process_time.mean)
                        if scv_p == 0:
                            pt = mean_pt
                        else:
                            shape_p = 1 / max(1e-9, scv_p)
                            scale_p = mean_pt / shape_p
                            pt = float(self.ptime_rng.gamma(shape_p, scale_p))
                        pt = max(0.001, pt)
                        process_times.append(float(np.round(pt, 4)))
                    
                    # Create additional job in batch
                    batch_job = ArrivalEvent(
                        time=arrival.time,  # Same arrival time
                        job_id=f"{arrival.job_id}-B{j}",
                        job_family=template.family,
                        routing=[s.machine_group for s in template.route],
                        process_times=process_times,
                        batch_id=batch_id,
                        arrival_type=arrival.arrival_type,
                    )
                    expanded_events.append(batch_job)
            else:
                # Not a batch, keep as single arrival
                expanded_events.append(arrival)
        
        added_jobs = len(expanded_events) - len(arrivals)
        if added_jobs > 0:
            logger.info(
                f"Expanded {batch_counter} arrivals into batches, added {added_jobs} jobs"
            )
        
        return expanded_events
        
    def _generate_due_date_events(self, arrivals: List[ArrivalEvent]) -> List[DueDateEvent]:
        logger.info("FastPath Constructor: generating due date events...")
        ddt = self._as_float(self.model.targets.ddt)
        horizon = float(self.model.scale.horizon)
        due_events: List[DueDateEvent] = []
        clamped_count = 0
        
        for a in arrivals:
            total_work = sum(a.process_times)
            
            theoretical_slack = ddt * total_work
            
            max_possible_slack = horizon * 0.98 - a.time
            
            actual_slack = min(theoretical_slack, max(0, max_possible_slack))
            
            min_slack = total_work * 1.05
            if actual_slack < min_slack:
                actual_slack = min_slack
            
            due_date = float(a.time + actual_slack)
            
            if due_date > horizon:
                due_date = horizon
                clamped_count += 1
        
            due_events.append(DueDateEvent(time=a.time, job_id=a.job_id, due_date=float(np.round(due_date, 4))))
        
        if clamped_count > 0:
            logger.debug(f"{clamped_count} due dates clamped to horizon")
        
        return due_events

    # 👇 --- New method to generate advanced dynamic events ---
    def _generate_dynamic_world_events(self, arrival_events: List[ArrivalEvent]) -> List[Event]:
        """Generates events like cancellations and priority changes."""
        dynamic_events: List[Event] = []
        scenarios = self.model.dynamic_scenarios

        # Select a subset of jobs that will become emergency jobs
        emergency_ids: set[str] = set()
        if getattr(scenarios, "emergency_job_ratio", 0.0) > 0 and arrival_events:
            ratio = float(scenarios.emergency_job_ratio)
            n_total = len(arrival_events)
            n_emergency = int(round(ratio * n_total))
            if n_emergency > 0:
                n_emergency = min(n_emergency, n_total)
                indices = self.dynamic_rng.choice(
                    np.arange(n_emergency + (n_total - n_emergency), dtype=int),
                    size=n_emergency,
                    replace=False,
                )
                for idx in indices:
                    a = arrival_events[int(idx)]
                    a.arrival_type = "emergency"
                    emergency_ids.add(a.job_id)

        if scenarios.cancellation_rate > 0 or scenarios.priority_change_rate > 0 or getattr(scenarios, "emergency_job_ratio", 0.0) > 0:
            logger.info(
                "FastPath Constructor: injecting dynamic world events "
                "(cancellations, priority changes)..."
            )
        
        for job_arrival in arrival_events:
            # Estimate time to finish for this job
            time_to_finish_est = sum(job_arrival.process_times) * 1.5  # Rough estimate
            
            # Decide if this job gets cancelled
            if self.dynamic_rng.random() < scenarios.cancellation_rate:
                # Cancellation happens some time after arrival but before it's likely finished
                cancellation_time = job_arrival.time + self.dynamic_rng.uniform(0, time_to_finish_est)
                if cancellation_time < self.model.scale.horizon:
                    dynamic_events.append(OrderCancellationEvent(
                        time=cancellation_time,
                        job_id=job_arrival.job_id
                    ))

            # Decide if this job gets a priority change (emergency or normal)
            time_remaining = self.model.scale.horizon - job_arrival.time
            if time_remaining > time_to_finish_est:  # Only if there's enough time
                if job_arrival.job_id in emergency_ids:
                    # Always create an emergency priority change for selected jobs
                    change_time = job_arrival.time + self.dynamic_rng.uniform(0, time_remaining)
                    if change_time < self.model.scale.horizon:
                        dynamic_events.append(PriorityChangeEvent(
                            time=change_time,
                            job_id=job_arrival.job_id,
                            new_priority=getattr(scenarios, "emergency_priority", -1),
                        ))
                else:
                    # Non-emergency jobs get a normal priority change with given probability
                    if self.dynamic_rng.random() < scenarios.priority_change_rate:
                        change_time = job_arrival.time + self.dynamic_rng.uniform(0, time_remaining)
                        if change_time < self.model.scale.horizon:
                            dynamic_events.append(PriorityChangeEvent(
                                time=change_time,
                                job_id=job_arrival.job_id,
                                new_priority=getattr(scenarios, "normal_priority_change_value", 0),
                            ))

        if scenarios.ptime_change_rate > 0:
            logger.info(
                "FastPath Constructor: injecting process time change events..."
            )
            for job_arrival in arrival_events:
                if self.dynamic_rng.random() < scenarios.ptime_change_rate:
                    # Pick a random step in the job's route to modify
                    if not job_arrival.process_times: continue
                    step_to_change = self.dynamic_rng.integers(0, len(job_arrival.process_times))
                    original_pt = job_arrival.process_times[step_to_change]
                    # Choose a multiplier: if a list is provided, sample randomly; otherwise use the single value
                    mult = getattr(scenarios, "ptime_change_multiplier", 1.0)
                    if isinstance(mult, list) and len(mult) > 0:
                        chosen = float(self.dynamic_rng.choice(np.array(mult, dtype=float)))
                    else:
                        chosen = float(mult)
                    new_pt = float(original_pt * chosen)

                    # The change happens some time after arrival, before the step is likely to start
                    change_time = job_arrival.time + self.dynamic_rng.uniform(0, sum(job_arrival.process_times[:step_to_change]) + original_pt/2)
                    
                    if change_time < self.model.scale.horizon:
                        dynamic_events.append(ProcessTimeChangeEvent(
                            time=change_time,
                            job_id=job_arrival.job_id,
                            step_index=step_to_change,
                            new_process_time=new_pt
                        ))
        
        # Generate route change events
        if scenarios.route_change_probability > 0:
            logger.info("FastPath Constructor: injecting route change events...")
            templates_arr = np.array(self.model.plant.process_templates, dtype=object)
            scv_p = self._as_float(self.model.targets.scv_p)
            
            for job_arrival in arrival_events:
                if self.dynamic_rng.random() < scenarios.route_change_probability:
                    # Select a different template for the new route
                    new_template = self._select_template()
                    
                    # Generate new process times
                    new_process_times: List[float] = []
                    for step in new_template.route:
                        mean_pt = float(step.process_time.mean)
                        if scv_p == 0:
                            pt = mean_pt
                        else:
                            shape_p = 1 / max(1e-9, scv_p)
                            scale_p = mean_pt / shape_p
                            pt = float(self.ptime_rng.gamma(shape_p, scale_p))
                        pt = max(0.001, pt)
                        new_process_times.append(float(np.round(pt, 4)))
                    
                    # Route change happens some time after arrival
                    # (after processing has started but before completion)
                    work_content = sum(job_arrival.process_times)
                    change_time = job_arrival.time + self.dynamic_rng.uniform(0, work_content * 0.5)
                    
                    if change_time < self.model.scale.horizon:
                        dynamic_events.append(RouteChangeEvent(
                            time=change_time,
                            job_id=job_arrival.job_id,
                            new_routing=[s.machine_group for s in new_template.route],
                            new_process_times=new_process_times,
                            from_step=0  # Replace all remaining steps
                        ))
        
        # Generate due date change events
        if scenarios.due_date_change_probability > 0:
            logger.info("FastPath Constructor: injecting due date change events...")
            ddt = self._as_float(self.model.targets.ddt)

            base_due_by_job: Dict[str, float] = {}
            horizon = float(self.model.scale.horizon)
            for job_arrival in arrival_events:
                work_content = sum(job_arrival.process_times)
                theoretical_slack = ddt * work_content
                max_possible_slack = horizon * 0.98 - float(job_arrival.time)
                actual_slack = min(theoretical_slack, max(0.0, max_possible_slack))
                min_slack = work_content * 1.05
                if actual_slack < min_slack:
                    actual_slack = min_slack
                due_date = float(job_arrival.time + actual_slack)
                if due_date > horizon:
                    due_date = horizon
                base_due_by_job[str(job_arrival.job_id)] = float(np.round(due_date, 4))
            
            for job_arrival in arrival_events:
                if self.dynamic_rng.random() < scenarios.due_date_change_probability:
                    work_content = sum(job_arrival.process_times)
                    original_due = float(base_due_by_job.get(str(job_arrival.job_id), job_arrival.time + ddt * work_content))
                    
                    # Determine if tightening or relaxing
                    is_tightening = self.dynamic_rng.random() < scenarios.due_date_tightening_ratio
                    
                    # Calculate slack
                    slack = ddt * work_content
                    max_change = slack * scenarios.due_date_change_factor
                    
                    # Apply change
                    if is_tightening:
                        # Make due date earlier (tighten)
                        change = self.dynamic_rng.uniform(0, max_change)
                        new_due_date = original_due - change
                        reason = "urgent"
                    else:
                        # Make due date later (relax)
                        change = self.dynamic_rng.uniform(0, max_change)
                        new_due_date = original_due + change
                        reason = "relaxed"
                    
                    lb = float(job_arrival.time + work_content * 0.5)
                    if reason == "urgent":
                        new_due_date = max(lb, min(float(new_due_date), float(original_due)))
                    else:
                        new_due_date = max(lb, max(float(new_due_date), float(original_due)))
                    new_due_date = min(float(new_due_date), float(self.model.scale.horizon))
                    
                    # Due date change happens some time after arrival
                    change_time = job_arrival.time + self.dynamic_rng.uniform(0, work_content * 0.3)
                    
                    if change_time < self.model.scale.horizon:
                        dynamic_events.append(DueDateChangeEvent(
                            time=change_time,
                            job_id=job_arrival.job_id,
                            new_due_date=new_due_date,
                            reason=reason
                        ))

        return dynamic_events
    
    def _generate_pm_events(self, existing_events: List[Event]) -> List[Event]:
        """Generate scheduled preventive maintenance events.
        
        PM events are time-based and scheduled at regular intervals for each machine.
        Unlike random breakdowns, they are predictable.
        """
        pm_events: List[Event] = []
        scenarios = self.model.dynamic_scenarios

        if scenarios.pm_interval <= 0:
            return pm_events

        logger.info(
            f"FastPath Constructor: generating preventive maintenance "
            f"(interval={scenarios.pm_interval})..."
        )

        horizon = float(self.model.scale.horizon)

        downtime_by_machine: Dict[str, List[Tuple[float, float]]] = {}
        for ev in existing_events:
            if isinstance(ev, (BreakdownEvent, PreventiveMaintenanceEvent)):
                mid = getattr(ev, "machine_id", None)
                if mid is None:
                    continue
                start = float(ev.time)
                duration = getattr(ev, "duration", 0.0) or 0.0
                end = float(start + duration)
                if mid not in downtime_by_machine:
                    downtime_by_machine[mid] = []
                downtime_by_machine[mid].append((start, end))

        for mid in downtime_by_machine:
            downtime_by_machine[mid].sort(key=lambda x: x[0])

        for machine in self.model.plant.machines:
            machine_id = machine.id
            intervals = downtime_by_machine.get(machine_id, [])
            current_time = scenarios.pm_interval
            while current_time < horizon:
                pm_duration = max(0.1, self.disturbance_rng.normal(
                    scenarios.pm_duration_mean,
                    scenarios.pm_duration_std
                ))

                base_time = float(current_time)
                candidate = base_time
                max_shift = scenarios.pm_interval * 0.5
                found_slot = False

                for _ in range(20):
                    has_overlap = False
                    end_time = candidate + pm_duration
                    for s, e in intervals:
                        if candidate < e and end_time > s:
                            has_overlap = True
                            candidate = e + 1e-3
                            break
                    if not has_overlap:
                        found_slot = True
                        break
                    if candidate > horizon or candidate - base_time > max_shift:
                        break

                if not found_slot or candidate >= horizon:
                    current_time += scenarios.pm_interval
                    continue

                pm_event = PreventiveMaintenanceEvent(
                    time=candidate,
                    machine_id=machine_id,
                    duration=pm_duration,
                    maintenance_type="time_based"
                )
                pm_events.append(pm_event)

                intervals.append((candidate, candidate + pm_duration))
                intervals.sort(key=lambda x: x[0])
                downtime_by_machine[machine_id] = intervals

                current_time += scenarios.pm_interval

        logger.info(f"Generated {len(pm_events)} preventive maintenance events")
        return pm_events
    
    def _calculate_initial_wip_count(self) -> int:
        """Calculate initial WIP count based on Little's Law and target utilization.
        
        L = λ * W
        where W ≈ work_content / (1 - rho) (G/G/m queue approximation)
        """
        if self.model.evaluation.mode != "warm_start":
            return 0
        
        if self.model.evaluation.initial_wip_method == "manual":
            return int(self.model.evaluation.n0_initial)
        
        # Auto calculation using Little's Law
        rho_g = self._as_float(self.model.targets.rho_global)
        if rho_g >= 0.95:  # Too high, use conservative estimate
            rho_g = 0.85
        
        # Calculate arrival rate
        lambda_eff, _ = self._resolve_arrival_rate()
        
        # Estimate mean flow time: W ≈ work_content / (1 - rho)
        avg_flow_time = self.avg_work_content / max(0.01, 1 - rho_g)
        
        # Little's Law: L = λ * W
        expected_wip = lambda_eff * avg_flow_time
        
        # Round to integer, with minimum of 1
        wip_count = max(1, int(round(expected_wip)))
        
        logger.info(
            f"Calculated initial WIP: {wip_count} jobs ("
            f"λ={lambda_eff:.4f}, W≈{avg_flow_time:.2f}, L≈{expected_wip:.2f})"
        )
        
        return wip_count
    
    def _generate_initial_wip_jobs(self) -> List[Event]:
        """Generate initial WIP jobs at time 0 for warm start.
        
        These jobs arrive at t=0 and represent the initial state of the system.
        """
        wip_count = self._calculate_initial_wip_count()
        if wip_count <= 0:
            return []
        
        initial_events: List[Event] = []
        scv_p = self._as_float(self.model.targets.scv_p)
        for i in range(wip_count):
            template = self._select_template()
            job_id = f"WIP-{i+1}"
            
            # Generate process times
            process_times: List[float] = []
            for step in template.route:
                mean_pt = float(step.process_time.mean)
                if scv_p == 0:
                    pt = mean_pt
                else:
                    shape_p = 1 / max(1e-9, scv_p)
                    scale_p = mean_pt / shape_p
                    pt = float(self.ptime_rng.gamma(shape_p, scale_p))
                pt = max(0.001, pt)
                process_times.append(float(np.round(pt, 4)))
            
            # Create arrival event at time 0
            arrival = ArrivalEvent(
                time=0.0,
                job_id=job_id,
                job_family=template.family,
                routing=[s.machine_group for s in template.route],
                process_times=process_times,
                arrival_type="initial_wip",
            )
            initial_events.append(arrival)
            
            # Create due date event
            work_content = sum(process_times)
            ddt = self._as_float(self.model.targets.ddt)
            due_date = min(0.0 + ddt * work_content, self.model.scale.horizon)
            
            due_date_event = DueDateEvent(
                time=0.0,
                job_id=job_id,
                due_date=due_date
            )
            initial_events.append(due_date_event)
        
        return initial_events
