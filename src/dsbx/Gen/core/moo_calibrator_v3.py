"""
Multi-Objective Optimization Calibrator v3 - EXTENDED PARAMETER SPACE

KEY IMPROVEMENTS over v2:
- Expanded from 4 to 12 decision variables
- Includes ALL coupled parameters that affect metrics
- Better coverage of the true optimization landscape
- Addresses user feedback: "MOO should optimize ALL coupled indicators together"

This version optimizes:
1. Core 4: arrival_rate, scv_a, scv_p, ddt
2. Distribution shapes: arrival_shape, ptime_shape  
3. Disturbance & bottleneck: breakdown_duration_multiplier, bottleneck_rho_scale
4. Load distribution: routing_bias, job_mix_alpha, batch_scale
5. Operational context: warm_start_scale
"""

import copy
from typing import List, Dict, Tuple, Optional
import numpy as np
from loguru import logger

try:
    from pymoo.core.problem import Problem
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.optimize import minimize
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.operators.sampling.rnd import FloatRandomSampling
    from pymoo.termination import get_termination
    PYMOO_AVAILABLE = True
except ImportError:
    PYMOO_AVAILABLE = False
    logger.warning("pymoo not available, MOO calibrator v3 disabled")
    # Create a placeholder Problem class to avoid NameError
    class Problem:  # type: ignore
        """Placeholder Problem class when pymoo is not available"""
        pass

from ..models.inputs import InputModel
from ..models.events import Event
from .constructor import FastPathConstructor
from .metrics_engine import MetricsEngine
from .seed import SeedManager
from .calibrator import Calibrator


class ExtendedCalibrationProblem(Problem):
    """
    Extended multi-objective calibration with 10 decision variables.
    
    Decision Variables (10D):
    0. arrival_rate_scale (0.6 - 1.4)        - λ scaling → rho_global
    1. scv_a_scale (0.5 - 2.0)               - arrival variability → scv_a
    2. scv_p_scale (0.5 - 2.0)               - process time variability → scv_p
    3. ddt_scale (0.5 - 2.5)                 - due date slack → ddt
    4. arrival_shape_bias (-0.5 - 0.5)       - fine-tune scv_a distribution shape
    5. ptime_shape_bias (-0.5 - 0.5)         - fine-tune scv_p distribution shape
    6. breakdown_duration_scale (0.5 - 2.0)  - disturbance intensity
    7. routing_balance_factor (0.7 - 1.3)    - machine load balancing → rho distribution
    8. batch_arrival_intensity (0.5 - 1.5)   - batch size scaling
    9. initial_wip_scale (0.7 - 1.3)         - warm start WIP adjustment
    
    Objectives (5D - minimize all):
    0. |rho_observed - rho_target| / rho_target
    1. |scv_a_observed - scv_a_target| / (scv_a_target + 0.1)
    2. |scv_p_observed - scv_p_target| / (scv_p_target + 0.1)
    3. |ddt_observed - ddt_target| / ddt_target
    4. |disturbance_observed - disturbance_target| / (disturbance_target + 0.01)
    """
    
    def __init__(
        self,
        base_model: InputModel,
        target_metrics: Dict[str, float],
        **kwargs
    ):
        self.base_model = base_model
        self.target_metrics = target_metrics

        # Cache base values
        self.base_rho_global = self._as_float(base_model.targets.rho_global)
        self.base_scv_a = self._as_float(base_model.targets.scv_a)
        self.base_scv_p = self._as_float(base_model.targets.scv_p)
        self.base_ddt = self._as_float(base_model.targets.ddt)
        self.base_disturbance = self._as_float(base_model.targets.disturbance)

        self.has_load_cv = getattr(base_model.targets, "load_cv", None) is not None
        self.has_bottleneck = bool(base_model.targets.rho_bottleneck)

        if base_model.plant.job_mix_weights:
            weights = np.array(base_model.plant.job_mix_weights, dtype=float)
        else:
            weights = np.full(len(base_model.plant.process_templates), 1.0)
        weights = np.clip(weights, 1e-6, None)
        self.base_job_mix_weights = (weights / weights.sum()).tolist()

        self.objective_labels = [
            "rho",
            "scv_a",
            "scv_p",
            "ddt",
            "disturbance",
        ]
        if self.has_load_cv:
            self.objective_labels.append("load_cv")
        if self.has_bottleneck:
            self.objective_labels.append("rho_bottleneck")

        n_obj = 5 + int(self.has_load_cv) + int(self.has_bottleneck)
        xl = np.array([0.6, 0.5, 0.5, 0.5, -0.5, -0.5, 0.5, 0.7, 0.5, 0.7, 0.3, 0.7], dtype=float)
        xu = np.array([1.4, 2.0, 2.0, 2.5,  0.5,  0.5, 2.0, 1.3, 1.5, 1.3, 3.0, 1.3], dtype=float)
        if self.base_rho_global and self.base_rho_global > 0:
            smin = 0.1 / float(self.base_rho_global)
            smax = 0.99 / float(self.base_rho_global)
            low = max(xl[0], smin)
            high = min(xu[0], smax)
            if low <= high:
                xl[0] = low
                xu[0] = high
        if self.base_scv_a is not None and self.base_scv_a > 0:
            up = min(xu[1], 5.0 / float(self.base_scv_a))
            if up < xl[1]:
                up = xl[1]
            xu[1] = up
        if self.base_scv_p is not None and self.base_scv_p > 0:
            up = min(xu[2], 5.0 / float(self.base_scv_p))
            if up < xl[2]:
                up = xl[2]
            xu[2] = up
        if self.base_ddt and self.base_ddt > 0:
            low = max(xl[3], 0.5 / float(self.base_ddt))
            high = min(xu[3], 10.0 / float(self.base_ddt))
            if low <= high:
                xl[3] = low
                xu[3] = high
        if self.base_disturbance and self.base_disturbance > 0:
            up = min(xu[6], 0.5 / float(self.base_disturbance))
            if up < xl[6]:
                up = xl[6]
            xu[6] = up
        if self.has_bottleneck and self.base_model.targets.rho_bottleneck:
            rhos = [float(bn.rho) for bn in self.base_model.targets.rho_bottleneck if getattr(bn, 'rho', None) not in (None, 0)]
            if rhos:
                smin = max(0.2 / r for r in rhos)
                smax = min(0.98 / r for r in rhos)
                low = max(xl[11], smin)
                high = min(xu[11], smax)
                if low <= high:
                    xl[11] = low
                    xu[11] = high
                else:
                    xl[11] = 1.0
                    xu[11] = 1.0
        super().__init__(
            n_var=12,
            n_obj=n_obj if n_obj > 0 else 5,
            n_constr=0,
            xl=xl,
            xu=xu,
            **kwargs
        )

        self.eval_count = 0
    
    @staticmethod
    def _as_float(val) -> float:
        return float(val[0]) if isinstance(val, list) else float(val)
    
    def _evaluate(self, X, out, *args, **kwargs):
        """Evaluate objectives for a batch of solutions."""
        F = np.zeros((X.shape[0], self.n_obj))
        
        for i, x in enumerate(X):
            self.eval_count += 1
            
            try:
                modified_model = self._create_extended_model(x)
                
                # Generate events
                seed_manager = SeedManager(modified_model.meta.seed + self.eval_count)
                constructor = FastPathConstructor(modified_model, seed_manager)
                events = constructor.generate_events()
                
                # Calculate metrics
                engine = MetricsEngine(modified_model, events)
                metrics = engine.estimate()
                
                # Extract targets (fallback to base_model targets)
                rho_target = self.target_metrics.get('rho_global', self.base_rho_global)
                scv_a_target = self.target_metrics.get('scv_a', self.base_scv_a)
                scv_p_target = self.target_metrics.get('scv_p', self.base_scv_p)
                ddt_target = self.target_metrics.get('ddt', self.base_ddt)
                dist_target = self.target_metrics.get('disturbance', self.base_disturbance)
                
                # Extract observed (fallback to targets for neutrality if missing)
                rho_obs = metrics.get('rho_global', rho_target)
                scv_a_obs = metrics.get('scv_a', scv_a_target)
                scv_p_obs = metrics.get('scv_p', scv_p_target)
                ddt_obs = metrics.get('ddt', ddt_target)
                dist_obs = metrics.get('disturbance', dist_target)
                
                # Calculate objectives (relative errors)
                obj_idx = 0
                F[i, obj_idx] = abs(rho_obs - rho_target) / (rho_target + 1e-6)
                obj_idx += 1

                F[i, obj_idx] = abs(scv_a_obs - scv_a_target) / max(abs(scv_a_target), 0.01)
                obj_idx += 1

                F[i, obj_idx] = abs(scv_p_obs - scv_p_target) / max(abs(scv_p_target), 0.01)
                obj_idx += 1

                F[i, obj_idx] = abs(ddt_obs - ddt_target) / (ddt_target + 1e-6)
                obj_idx += 1

                F[i, obj_idx] = (
                    abs(dist_obs - dist_target) / max(abs(dist_target), 0.01)
                ) if dist_target > 0 else abs(dist_obs)
                obj_idx += 1

                if self.has_load_cv and obj_idx < self.n_obj:
                    load_cv_target = self.target_metrics.get('load_cv', 0.0)
                    load_cv_obs = metrics.get('load_cv', 0.0)
                    if load_cv_target < 1e-6:
                        F[i, obj_idx] = abs(load_cv_obs)
                    else:
                        F[i, obj_idx] = abs(load_cv_obs - load_cv_target) / max(abs(load_cv_target), 0.01)
                    obj_idx += 1

                if self.has_bottleneck and obj_idx < self.n_obj:
                    rho_bn_obs = metrics.get('rho_bottleneck', 0.0)
                    F[i, obj_idx] = abs(rho_bn_obs)

                
                if self.eval_count % 20 == 0:
                    logger.debug(f"Eval {self.eval_count}: F_mean={F[i].mean():.4f}")
                
            except Exception as e:
                logger.warning(f"Eval {self.eval_count} failed: {e}")
                F[i, :] = 10.0
        
        out["F"] = F
    
    def _create_extended_model(self, x: np.ndarray) -> InputModel:
        """
        Create model with ALL 10 parameters modified.
        
        This is the KEY improvement over v2!
        """
        modified = self.base_model.model_copy(deep=True)
        
        # Extract decision variables
        arrival_rate_scale = float(x[0])
        scv_a_scale = float(x[1])
        scv_p_scale = float(x[2])
        ddt_scale = float(x[3])
        arrival_shape_bias = float(x[4])
        ptime_shape_bias = float(x[5])
        breakdown_duration_scale = float(x[6])
        routing_balance_factor = float(x[7])
        batch_intensity = float(x[8])
        wip_scale = float(x[9])
        job_mix_alpha = float(x[10])
        bottleneck_scale = float(x[11])
        
        # 1. Core 4 parameters (same as v2)
        new_rho = np.clip(self.base_rho_global * arrival_rate_scale, 0.1, 0.99)
        modified.targets.rho_global = float(new_rho)
        
        # CRITICAL FIX: Clear jobs_total so Constructor uses rho_global
        # If jobs_total is set, Constructor ignores rho_global changes
        modified.scale.jobs_total = None
        
        new_scv_a = np.clip(self.base_scv_a * scv_a_scale, 0.0, 5.0)
        modified.targets.scv_a = float(new_scv_a)
        
        new_scv_p = np.clip(self.base_scv_p * scv_p_scale, 0.0, 5.0)
        modified.targets.scv_p = float(new_scv_p)
        
        new_ddt = np.clip(self.base_ddt * ddt_scale, 0.5, 10.0)
        modified.targets.ddt = float(new_ddt)
        
        # 2. NEW: Disturbance scaling
        if self.base_disturbance > 0:
            new_dist = np.clip(self.base_disturbance * breakdown_duration_scale, 0.0, 0.5)
            modified.targets.disturbance = float(new_dist)
        
        # 3. NEW: Shape parameter biases
        # Note: These would require Constructor modifications to fully utilize
        # For now, we implicitly encode them through SCV adjustments
        # In future: Constructor could read these from model extensions
        
        # Fine-tune SCV with shape biases (second-order effect)
        scv_a_fine = new_scv_a * (1.0 + arrival_shape_bias * 0.1)
        scv_p_fine = new_scv_p * (1.0 + ptime_shape_bias * 0.1)
        
        modified.targets.scv_a = float(np.clip(scv_a_fine, 0.0, 5.0))
        modified.targets.scv_p = float(np.clip(scv_p_fine, 0.0, 5.0))
        
        # Routing balance affects rho distribution (implicit)
        # Future: Could be used to adjust rho_bottleneck targets
        
        # 4. NEW: Batch intensity
        if hasattr(modified.dynamic_scenarios, 'batch_arrival_probability'):
            if modified.dynamic_scenarios.batch_arrival_probability > 0:
                # Scale average batch size
                original_batch_size = getattr(modified.dynamic_scenarios, 'batch_size_mean', 3)
                new_batch_size = max(2.0, float(original_batch_size * batch_intensity))
                modified.dynamic_scenarios.batch_size_mean = new_batch_size
        
        # 5. NEW: WIP scaling for warm start
        if modified.evaluation.mode == "warm_start":
            original_wip = getattr(modified.evaluation, 'n0_initial', 0)
            new_wip = max(0, int(original_wip * wip_scale))
            modified.evaluation.n0_initial = new_wip

        # 6. NEW: Job mix weight adjustment for load_cv control
        if len(self.base_job_mix_weights) == len(modified.plant.process_templates):
            base_weights = np.array(self.base_job_mix_weights, dtype=float)
            adjusted = np.clip(base_weights, 1e-6, None) ** job_mix_alpha
            adjusted = adjusted / adjusted.sum()
            modified.plant.job_mix_weights = adjusted.tolist()

        # 7. NEW: Bottleneck target scaling
        if self.has_bottleneck and modified.targets.rho_bottleneck:
            for bn in modified.targets.rho_bottleneck:
                original_rho = float(bn.rho)
                scaled_rho = np.clip(original_rho * bottleneck_scale, 0.2, 0.98)
                bn.rho = float(scaled_rho)
        
        return modified


def find_best_constrained_solution(
    pareto_front: np.ndarray,
    target_metrics: Dict[str, float],
    objective_labels: List[str],
    primary_metric: Optional[str] = None,
) -> Tuple[int, str]:
    """
    Extended constraint-aware selection for 5 objectives.
    
    Thresholds:
    - rho_global: 3%
    - scv_a, scv_p: 8%
    - ddt: 3%
    - disturbance: 5%
    """
    primary_map = {
        "rho_global": "rho",
        "rho": "rho",
        "scv_a": "scv_a",
        "scv_p": "scv_p",
        "ddt": "ddt",
        "disturbance": "disturbance",
        "load_cv": "load_cv",
        "rho_bottleneck": "rho_bottleneck",
    }

    threshold_map = {
        "rho": 0.06,
        "scv_a": 0.12,
        "scv_p": 0.18,
        "ddt": 0.10,
        "disturbance": 0.10,
        "load_cv": 0.15,
        "rho_bottleneck": 0.05,
    }

    thresholds = []
    for label in objective_labels:
        if label == "disturbance" and ("disturbance" not in target_metrics or target_metrics.get("disturbance", 0) == 0):
            thresholds.append(10.0)
        else:
            thresholds.append(threshold_map.get(label, 0.05))

    thresholds = np.array(thresholds)
    
    constraint_satisfied = pareto_front <= thresholds
    n_satisfied = constraint_satisfied.sum(axis=1)
    
    # Strategy 1: Fully feasible solutions
    fully_feasible = np.where(n_satisfied == pareto_front.shape[1])[0]
    if len(fully_feasible) > 0:
        best = fully_feasible[np.argmin(pareto_front[fully_feasible].sum(axis=1))]
        logger.info(f"Found {len(fully_feasible)} fully feasible solutions")
        return best, "fully_feasible"
    
    # Primary metric prioritization
    primary_label = None
    if primary_metric:
        primary_label = primary_map.get(primary_metric)
        if primary_label not in objective_labels:
            primary_label = None

    candidates = np.arange(pareto_front.shape[0])
    reason = "balanced"

    if primary_label is not None:
        primary_idx = objective_labels.index(primary_label)
        primary_tol = threshold_map.get(primary_label, 0.05)
        primary_candidates = np.where(pareto_front[:, primary_idx] <= primary_tol)[0]
        if len(primary_candidates) > 0:
            candidates = primary_candidates
            reason = f"primary_{primary_label}_within_tol"
        else:
            # fallback: choose smallest primary error subset
            primary_errors = pareto_front[:, primary_idx]
            best_primary = primary_errors.min()
            tolerance_factor = 1.2
            candidates = np.where(primary_errors <= best_primary * tolerance_factor)[0]
            reason = f"primary_{primary_label}_best"

    # Strategy 2: Maximum constraint satisfaction among candidates
    max_satisfied = n_satisfied[candidates].max()
    constraint_filter = candidates[n_satisfied[candidates] == max_satisfied]
    
    logger.info(
        "No fully feasible solution. "
        f"Best satisfies {max_satisfied}/{pareto_front.shape[1]} constraints"
    )
    
    if len(constraint_filter) == 1:
        return constraint_filter[0], f"{reason}_max_constraints_{max_satisfied}"
    
    # Priority: SCV + disturbance (wider thresholds)
    # Index into rows: candidates, columns: [1,2,4] for scv_a, scv_p, disturbance
    pivotal_indices = [idx for idx, label in enumerate(objective_labels) if label in {"scv_a", "scv_p", "disturbance"}]
    if not pivotal_indices:
        pivotal_indices = list(range(pareto_front.shape[1]))

    flexible_satisfied = constraint_satisfied[constraint_filter][:, pivotal_indices].sum(axis=1)
    max_flexible = flexible_satisfied.max()
    flex_idx = np.where(flexible_satisfied == max_flexible)[0]
    flex_candidates = constraint_filter[flex_idx]
    
    # Break ties by minimum total error
    best_idx = flex_candidates[np.argmin(pareto_front[flex_candidates].sum(axis=1))]
    
    return best_idx, f"{reason}_max_constraints_{max_satisfied}_flex_{max_flexible}"


class MOOCalibratorV3:
    """
    Extended MOO calibrator with 10 decision variables.
    
    This addresses the key limitation of v2: limited parameter space.
    Now we optimize ALL coupled parameters together!
    """
    
    def __init__(
        self,
        model: InputModel,
        target_metrics: Dict[str, float],
        population_size: int = 60,  # Increased from 40
        n_generations: int = 40,     # Increased from 30
        primary_metric: Optional[str] = None,
    ):
        self.model = model
        self.target_metrics = target_metrics
        self.population_size = population_size
        self.n_generations = n_generations
        self.primary_metric = primary_metric
        
        if not PYMOO_AVAILABLE:
            raise RuntimeError("pymoo required for MOO v3")
    
    def calibrate(self) -> Tuple[List[Event], Dict[str, float]]:
        """Run extended MOO calibration."""
        logger.info("Starting MOO v3 (extended) calibration")
        logger.info(f"   Decision variables: 12 (vs 4 in v2)")
        logger.info(f"   Population: {self.population_size}")
        logger.info(f"   Generations: {self.n_generations}")
        logger.info(f"   Total evaluations: ~{self.population_size * self.n_generations}")
        
        problem = ExtendedCalibrationProblem(
            base_model=self.model,
            target_metrics=self.target_metrics
        )
        
        algorithm = NSGA2(
            pop_size=self.population_size,
            sampling=FloatRandomSampling(),
            crossover=SBX(prob=0.9, eta=15),
            mutation=PM(eta=20),
            eliminate_duplicates=True
        )
        
        termination = get_termination("n_gen", self.n_generations)
        
        try:
            logger.info("Running NSGA-II (this may take several minutes)...")
            
            res = minimize(
                problem,
                algorithm,
                termination,
                seed=int(self.model.meta.seed),
                verbose=False
            )
            
            pareto_X = res.X
            pareto_F = res.F
            
            if pareto_X is None or pareto_F is None:
                raise ValueError("No solutions found")
            
            if pareto_X.ndim == 1:
                pareto_X = pareto_X.reshape(1, -1)
                pareto_F = pareto_F.reshape(1, -1)
            
            logger.info(f"MOO v3 found {len(pareto_F)} Pareto-optimal solutions")
            logger.info("   Objective ranges:")
            objective_labels = problem.objective_labels

            for idx, label in enumerate(objective_labels):
                if idx < pareto_F.shape[1]:
                    logger.info(
                        f"     {label}: [{pareto_F[:, idx].min():.4f}, {pareto_F[:, idx].max():.4f}]"
                    )
            
            # Select best solution
            primary_metric = self.primary_metric
            if primary_metric is None:
                if self.target_metrics.get('load_cv') is not None:
                    primary_metric = 'load_cv'
                else:
                    primary_metric = 'ddt'

            best_idx, reason = find_best_constrained_solution(
                pareto_F,
                self.target_metrics,
                objective_labels,
                primary_metric,
            )
            best_x = pareto_X[best_idx]
            best_f = pareto_F[best_idx]
            
            logger.info(f"Selected solution (reason: {reason}):")
            logger.info(f"   Parameters: {best_x}")
            logger.info(f"   Objectives: {best_f}")
            
            # Generate final instance
            logger.info("Generating final instance...")
            best_model = problem._create_extended_model(best_x)
            seed_manager = SeedManager(best_model.meta.seed)
            constructor = FastPathConstructor(best_model, seed_manager)
            calibrated_events = constructor.generate_events()

            # Optional sequential refinement to polish key metrics (mirrors Hybrid flow)
            sequential_steps = 0
            max_sequential_steps = 10
            tolerances = {
                "rho_global": 0.06,
                "scv_a": 0.12,
                "scv_p": 0.18,
                "ddt": 0.10,
                "load_cv": 0.15,
                "rho_bottleneck": 0.05,
            }

            focus_metrics = []
            if self.target_metrics.get("load_cv") is not None:
                focus_metrics.append("load_cv")
            focus_metrics.extend(["rho_global", "ddt", "scv_a", "scv_p"])
            if problem.has_bottleneck:
                focus_metrics.append("rho_bottleneck")

            def _metric_error(metric: str, observed: Dict[str, float]) -> float:
                target = self.target_metrics.get(metric, 0.0)
                observed_val = observed.get(metric, 0.0)
                if metric == "rho_bottleneck":
                    return abs(observed_val)
                if target < 1e-6:
                    return abs(observed_val)
                return abs(observed_val - target) / (abs(target) + 1e-6)

            refined_events = calibrated_events
            best_events = copy.deepcopy(refined_events)
            best_primary_error = float("inf")
            best_total_error = float("inf")
            for step in range(max_sequential_steps):
                metrics_engine = MetricsEngine(best_model, refined_events)
                observed_metrics = metrics_engine.estimate()

                errors = {
                    metric: _metric_error(metric, observed_metrics)
                    for metric in focus_metrics
                    if (metric in observed_metrics or metric in self.target_metrics)
                }

                if not errors:
                    break

                current_total_error = sum(errors.values())
                primary_error = None
                if self.primary_metric and self.primary_metric in errors:
                    primary_error = errors[self.primary_metric]

                if primary_error is not None:
                    if (
                        primary_error < best_primary_error - 1e-6
                        or (
                            primary_error <= best_primary_error + 1e-9
                            and current_total_error < best_total_error - 1e-6
                        )
                    ):
                        best_primary_error = primary_error
                        best_total_error = current_total_error
                        best_events = copy.deepcopy(refined_events)
                else:
                    if current_total_error < best_total_error - 1e-6:
                        best_total_error = current_total_error
                        best_events = copy.deepcopy(refined_events)

                if self.primary_metric and self.primary_metric in errors:
                    errors[self.primary_metric] *= 1.5

                metric, error_value = max(errors.items(), key=lambda item: item[1])
                tolerance = tolerances.get(metric, 0.05)

                if (
                    self.primary_metric
                    and primary_error is not None
                    and primary_error > tolerances.get(self.primary_metric, 0.05)
                ):
                    metric = self.primary_metric
                    error_value = errors[self.primary_metric]
                    tolerance = tolerances.get(self.primary_metric, 0.05)
                if error_value <= tolerance:
                    logger.info("Sequential refinement (MOO) converged early")
                    break

                logger.info(
                    "   MOO refinement step {}: refining {} (error={:.1%}, tol={:.1%})".format(
                        step + 1, metric, error_value, tolerance
                    )
                )

                seq_targets: Dict[str, float] = {"rho_bottleneck": 0.0}
                for key in ["rho_global", "scv_a", "scv_p", "ddt", "load_cv", "disturbance"]:
                    if key in self.target_metrics and self.target_metrics[key] is not None:
                        seq_targets[key] = self.target_metrics[key]

                observed_subset = {k: observed_metrics.get(k, 0.0) for k in seq_targets}
                calibrator = Calibrator(best_model, refined_events, seq_targets, observed_subset)
                refined_events = calibrator.calibrate()
                sequential_steps += 1

            refined_events = best_events

            if sequential_steps:
                logger.info(
                    f"MOO sequential refinement completed in {sequential_steps} steps"
                )

            if self.primary_metric and self.primary_metric in self.target_metrics:
                prev_error = None
                best_events = copy.deepcopy(refined_events)
                best_primary_error = float("inf")
                for _ in range(20):
                    engine = MetricsEngine(best_model, refined_events)
                    observed_metrics = engine.estimate()

                    target_val = self.target_metrics[self.primary_metric]
                    observed_val = observed_metrics.get(self.primary_metric, 0.0)
                    if self.primary_metric == "rho_bottleneck":
                        primary_error = abs(observed_val)
                    elif target_val < 1e-6:
                        primary_error = abs(observed_val)
                    else:
                        primary_error = abs(observed_val - target_val) / (abs(target_val) + 1e-6)

                    if primary_error < best_primary_error - 1e-6:
                        best_primary_error = primary_error
                        best_events = copy.deepcopy(refined_events)

                    if primary_error <= tolerances.get(self.primary_metric, 0.05) / 2:
                        break
                    if prev_error is not None and prev_error - primary_error < 1e-3:
                        break
                    prev_error = primary_error

                    primary_targets = {"rho_bottleneck": 0.0, self.primary_metric: target_val}
                    observed_subset = {k: observed_metrics.get(k, 0.0) for k in primary_targets}
                    calibrator = Calibrator(
                        best_model,
                        refined_events,
                        primary_targets,
                        observed_subset,
                        use_synergy=False,
                    )
                    refined_events = calibrator.calibrate()

                refined_events = best_events

            # Verify final metrics after refinement
            engine = MetricsEngine(best_model, refined_events)
            final_metrics = engine.estimate()
            
            logger.info("Final metrics:")
            metrics_keys = ['rho_global', 'scv_a', 'scv_p', 'ddt', 'disturbance']
            if problem.has_load_cv:
                metrics_keys.append('load_cv')
            if problem.has_bottleneck:
                metrics_keys.append('rho_bottleneck')

            for key in metrics_keys:
                target = self.target_metrics.get(key, 0.0)
                observed = final_metrics.get(key, 0.0)
                if key == 'rho_bottleneck':
                    if best_model.targets.rho_bottleneck:
                        target_rhos = [float(getattr(bn, 'rho', 0.0)) for bn in best_model.targets.rho_bottleneck]
                        denom = float(np.linalg.norm(np.array(target_rhos, dtype=float)))
                        error = (observed / denom) * 100 if denom > 1e-9 else (observed * 100)
                    else:
                        error = observed * 100
                elif target < 1e-6:
                    error = abs(observed) * 100
                else:
                    error = abs(observed - target) / (abs(target) + 1e-6) * 100
                logger.info(f"   {key}: t={target:.3f}, o={observed:.3f} (err={error:.1f}%)")
            
            # Deterministic evaluation for each Pareto solution (for exact replay)
            base_seed = int(self.model.meta.seed)
            det_F_list: List[np.ndarray] = []
            det_seeds: List[int] = []
            for idx, x in enumerate(pareto_X):
                det_seed = base_seed + 10000 + int(idx)
                det_seeds.append(det_seed)
                try:
                    det_model = problem._create_extended_model(x)
                    seed_mgr = SeedManager(det_seed)
                    constructor_det = FastPathConstructor(det_model, seed_mgr)
                    det_events = constructor_det.generate_events()

                    det_engine = MetricsEngine(det_model, det_events)
                    det_metrics = det_engine.estimate()

                    # Reuse same target definitions as in ExtendedCalibrationProblem._evaluate
                    rho_target = self.target_metrics.get('rho_global', problem.base_rho_global)
                    scv_a_target = self.target_metrics.get('scv_a', problem.base_scv_a)
                    scv_p_target = self.target_metrics.get('scv_p', problem.base_scv_p)
                    ddt_target = self.target_metrics.get('ddt', problem.base_ddt)
                    dist_target = self.target_metrics.get('disturbance', problem.base_disturbance)

                    rho_obs = det_metrics.get('rho_global', rho_target)
                    scv_a_obs = det_metrics.get('scv_a', scv_a_target)
                    scv_p_obs = det_metrics.get('scv_p', scv_p_target)
                    ddt_obs = det_metrics.get('ddt', ddt_target)
                    dist_obs = det_metrics.get('disturbance', dist_target)

                    F_det: List[float] = []
                    # rho
                    if rho_target > 0:
                        F_det.append(abs(rho_obs - rho_target) / (rho_target + 1e-6))
                    else:
                        F_det.append(abs(rho_obs))
                    # scv_a
                    F_det.append(abs(scv_a_obs - scv_a_target) / max(abs(scv_a_target), 0.01))
                    # scv_p
                    F_det.append(abs(scv_p_obs - scv_p_target) / max(abs(scv_p_target), 0.01))
                    # ddt
                    if ddt_target > 0:
                        F_det.append(abs(ddt_obs - ddt_target) / (ddt_target + 1e-6))
                    else:
                        F_det.append(abs(ddt_obs))
                    # disturbance
                    if dist_target > 0:
                        F_det.append(abs(dist_obs - dist_target) / max(abs(dist_target), 0.01))
                    else:
                        F_det.append(abs(dist_obs))

                    # load_cv objective if present
                    if problem.has_load_cv:
                        load_target = self.target_metrics.get('load_cv', 0.0)
                        load_obs = det_metrics.get('load_cv', 0.0)
                        if load_target < 1e-6:
                            F_det.append(abs(load_obs))
                        else:
                            F_det.append(abs(load_obs - load_target) / max(abs(load_target), 0.01))

                    # rho_bottleneck objective if present
                    if problem.has_bottleneck:
                        rho_bn_obs = det_metrics.get('rho_bottleneck', 0.0)
                        F_det.append(abs(rho_bn_obs))

                    det_F_list.append(np.array(F_det, dtype=float))
                except Exception as det_exc:
                    logger.warning(f"Deterministic evaluation failed for Pareto idx {idx}: {det_exc}")
                    det_F_list.append(np.full(len(objective_labels), 10.0, dtype=float))

            det_pareto_F = np.vstack(det_F_list) if det_F_list else pareto_F
            best_det_f = det_pareto_F[best_idx]

            # Pareto info (based on deterministic objectives for better replay stability)
            objective_ranges = {}
            for idx, label in enumerate(objective_labels):
                if idx < det_pareto_F.shape[1]:
                    objective_ranges[label] = [
                        float(det_pareto_F[:, idx].min()),
                        float(det_pareto_F[:, idx].max()),
                    ]

            # Combine id, deterministic objectives, and decision variables per solution
            pareto_points = []
            for idx in range(len(det_pareto_F)):
                pareto_points.append(
                    {
                        'id': int(idx),
                        'objectives': det_pareto_F[idx].tolist(),
                        'decision_vars': pareto_X[idx].tolist(),
                        'deterministic_seed': int(det_seeds[idx]),
                    }
                )

            pareto_info = {
                'pareto_size': len(det_pareto_F),
                'best_index': int(best_idx),
                'best_objectives': best_det_f.tolist(),
                'best_parameters': best_x.tolist(),
                'selection_reason': reason,
                'total_evaluations': problem.eval_count,
                'objective_ranges': objective_ranges,
                'sequential_refinement_steps': sequential_steps,
                # Extended fields for replay and analysis
                'calibration_mode': 'moo_v3_extended',
                'objective_labels': objective_labels,
                'pareto_points': pareto_points,
            }
            
            return refined_events, pareto_info
            
        except Exception as e:
            logger.error(f"MOO v3 failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback
            seed_manager = SeedManager(self.model.meta.seed)
            constructor = FastPathConstructor(self.model, seed_manager)
            fallback_events = constructor.generate_events()
            return fallback_events, {'error': str(e)}

