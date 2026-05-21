"""
Hybrid Calibrator: Focused MOO for coupled metrics only

Key insight: rho_global and disturbance are deterministically determined by Constructor
based on targets, so they don't need separate calibration. We only need to optimize
the coupled metrics (scv_a, scv_p, ddt) which have complex interactions.

v0.2.0: Added parallel evaluation support for performance boost
"""
import copy
from typing import Dict, Any, Tuple, Optional, List
import numpy as np
from multiprocessing import Pool, cpu_count
import os

from loguru import logger

from ..models.inputs import InputModel
from .constructor import FastPathConstructor
from .calibrator import Calibrator
from .moo_calibrator_v3 import find_best_constrained_solution
from .metrics_engine import MetricsEngine
from .seed import SeedManager

# Try to import pymoo
try:
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import Problem
    from pymoo.optimize import minimize
    from pymoo.termination import get_termination
    PYMOO_AVAILABLE = True
except ImportError:
    PYMOO_AVAILABLE = False
    logger.warning("pymoo not available. Hybrid calibrator will not work without it.")
    # Create a placeholder Problem class to avoid NameError
    class Problem:  # type: ignore
        """Placeholder Problem class when pymoo is not available"""
        pass


def _evaluate_single_worker(
    base_model: InputModel,
    target_metrics: Dict[str, float],
    has_bottleneck: bool,
    has_load_cv: bool,
    x_i: np.ndarray,
    eval_id: int
) -> np.ndarray:
    """Worker function for parallel evaluation.

    The function must remain module-level so multiprocessing can pickle it.

    Args:
        base_model: Base input model.
        target_metrics: Target metrics.
        has_bottleneck: Whether bottleneck targets are active.
        has_load_cv: Whether a load-CV target is active.
        x_i: Decision vector.
        eval_id: Evaluation identifier.

    Returns:
        Objective-value array.
    """
    try:
        modified = copy.deepcopy(base_model)
        
        scv_a_scale = x_i[0]
        scv_p_scale = x_i[1]
        ddt_scale = x_i[2]
        bottleneck_rho_scale = x_i[3]
        load_cv_scale = x_i[4]
        
        # Modify targets
        base_scv_a = float(modified.targets.scv_a)
        if base_scv_a < 0.01:
            modified.targets.scv_a = 0.0
        else:
            modified.targets.scv_a = base_scv_a * scv_a_scale
        
        base_scv_p = float(modified.targets.scv_p)
        if base_scv_p < 0.01:
            modified.targets.scv_p = 0.0
        else:
            modified.targets.scv_p = base_scv_p * scv_p_scale
        
        base_ddt = float(modified.targets.ddt)
        modified.targets.ddt = base_ddt * ddt_scale
        
        if has_bottleneck and modified.targets.rho_bottleneck:
            for bn in modified.targets.rho_bottleneck:
                original_rho = float(bn.rho)
                scaled_rho = original_rho * bottleneck_rho_scale
                bn.rho = float(np.clip(scaled_rho, 0.3, 0.95))
        
        if has_load_cv and modified.targets.load_cv is not None:
            if base_model.plant.job_mix_weights:
                base_weights = np.array(base_model.plant.job_mix_weights, dtype=float)
            else:
                base_weights = np.ones(len(base_model.plant.process_templates), dtype=float)
            base_weights = np.clip(base_weights, 1e-6, None)
            alpha = np.interp(load_cv_scale, [0.7, 1.4], [0.3, 3.0])
            adjusted = base_weights ** alpha
            adjusted = adjusted / adjusted.sum()
            modified.plant.job_mix_weights = adjusted.tolist()
        
        seed_mgr = SeedManager(modified.meta.seed + eval_id)
        constructor = FastPathConstructor(modified, seed_mgr)
        events = constructor.generate_events()
        
        metrics_engine = MetricsEngine(modified, events)
        observed = metrics_engine.estimate()
        
        n_obj = 3 + int(has_bottleneck) + int(has_load_cv)
        F = np.zeros(n_obj)
        
        scv_a_target = target_metrics.get("scv_a", 1.0)
        scv_p_target = target_metrics.get("scv_p", 1.0)
        ddt_target = target_metrics.get("ddt", 2.0)
        load_cv_target = target_metrics.get("load_cv", 0.2)
        
        scv_a_obs = observed.get("scv_a", 0.0)
        scv_p_obs = observed.get("scv_p", 0.0)
        ddt_obs = observed.get("ddt", 0.0)
        rho_bn_obs = observed.get("rho_bottleneck", 0.0)
        load_cv_obs = observed.get("load_cv", 0.0)
        
        if scv_a_target < 0.01:
            F[0] = abs(scv_a_obs)
        else:
            F[0] = abs(scv_a_obs - scv_a_target) / (scv_a_target + 0.1)
        
        if scv_p_target < 0.01:
            F[1] = abs(scv_p_obs)
        else:
            F[1] = abs(scv_p_obs - scv_p_target) / (scv_p_target + 0.1)
        
        F[2] = abs(ddt_obs - ddt_target) / (ddt_target + 1e-6)
        
        obj_idx = 3
        if has_bottleneck and obj_idx < n_obj:
            F[obj_idx] = abs(rho_bn_obs) / 0.8
            obj_idx += 1

        if has_load_cv and obj_idx < n_obj:
            if load_cv_target < 1e-6:
                F[obj_idx] = abs(load_cv_obs)
            else:
                F[obj_idx] = abs(load_cv_obs - load_cv_target) / (load_cv_target + 0.01)
        
        return F
        
    except Exception as e:
        n_obj = 3 + int(has_bottleneck) + int(has_load_cv)
        return np.full(n_obj, 10.0)


class CoupledMetricsProblem(Problem):
    """
    MOO problem for coupled metrics: scv_a, scv_p, ddt, rho_bottleneck, load_cv
    
    Decision variables (5D):
        x[0]: scv_a_scale ∈ [0.5, 1.6]
        x[1]: scv_p_scale ∈ [0.5, 1.6]
        x[2]: ddt_scale ∈ [0.6, 1.5]
        x[3]: bottleneck_rho_scale ∈ [0.7, 1.3] (only active if rho_bottleneck targets exist)
        x[4]: load_cv_scale ∈ [0.7, 1.4] (only active if load_cv target exists)
    
    Objectives (5D - all minimize):
        f[0]: |scv_a_obs - scv_a_target| / (scv_a_target + 0.1)
        f[1]: |scv_p_obs - scv_p_target| / (scv_p_target + 0.1)
        f[2]: |ddt_obs - ddt_target| / ddt_target
        f[3]: rho_bottleneck_error (L2 norm from metrics)
        f[4]: |load_cv_obs - load_cv_target| / (load_cv_target + 0.01)
    """
    
    def __init__(
        self,
        base_model: InputModel,
        target_metrics: Dict[str, float],
        n_workers: Optional[int] = None,
        **kwargs
    ):
        # Check if bottleneck and load_cv targets exist
        has_bottleneck = bool(base_model.targets.rho_bottleneck)
        has_load_cv = base_model.targets.load_cv is not None

        n_obj = 3 + int(has_bottleneck) + int(has_load_cv)
        n_obj = max(n_obj, 3)

        super().__init__(
            n_var=5,  # Decision variables defined above
            n_obj=n_obj,
            n_constr=0,
            xl=np.array([0.5, 0.5, 0.6, 0.7, 0.7]),  # Lower bounds
            xu=np.array([1.6, 1.6, 1.5, 1.3, 1.4]),  # Upper bounds
            **kwargs
        )
        self.base_model = base_model
        self.target_metrics = target_metrics
        self.evaluation_count = 0
        self.has_bottleneck = has_bottleneck
        self.has_load_cv = has_load_cv

        if base_model.plant.job_mix_weights:
            job_mix = np.array(base_model.plant.job_mix_weights, dtype=float)
        else:
            job_mix = np.ones(len(base_model.plant.process_templates), dtype=float)
        job_mix = np.clip(job_mix, 1e-6, None)
        self.base_job_mix_weights = (job_mix / job_mix.sum()).tolist()
        self.objective_labels = ["scv_a", "scv_p", "ddt"]
        if has_bottleneck:
            self.objective_labels.append("rho_bottleneck")
        if has_load_cv:
            self.objective_labels.append("load_cv")
        
        self.n_workers = n_workers or max(1, cpu_count() - 1)
        self.use_parallel = False  # v3: prefer determinism over parallel speed
        
        if self.use_parallel:
            logger.info(f"Enabling parallel evaluation with {self.n_workers} worker processes")
        else:
            logger.debug("Using serial evaluation mode")
    
    def _evaluate(self, x, out, *args, **kwargs):
        """
        Evaluate a population of decision variables.
        
        Supports parallel evaluation for performance boost.
        
        Args:
            x: 2D array of shape (population_size, n_var)
        """
        n_samples = x.shape[0]
        
        if self.use_parallel and n_samples >= 4:
            F = self._evaluate_parallel(x)
        else:
            F = self._evaluate_serial(x)
        
        out["F"] = F
    
    def _evaluate_serial(self, x: np.ndarray) -> np.ndarray:
        """Evaluate the population serially."""
        n_samples = x.shape[0]
        F = np.zeros((n_samples, self.n_obj))
        
        for i in range(n_samples):
            self.evaluation_count += 1
            F[i, :] = self._evaluate_single_solution(x[i], self.evaluation_count)
        
        return F
    
    def _evaluate_parallel(self, x: np.ndarray) -> np.ndarray:
        """Evaluate the population with multiprocessing."""
        n_samples = x.shape[0]
        
        args_list = [(x[i], self.evaluation_count + i + 1) for i in range(n_samples)]
        
        try:
            with Pool(processes=self.n_workers) as pool:
                results = pool.starmap(_evaluate_single_worker, 
                                      [(self.base_model, self.target_metrics, 
                                        self.has_bottleneck, self.has_load_cv, 
                                        xi, eval_id) 
                                       for xi, eval_id in args_list])
            
            self.evaluation_count += n_samples
            F = np.array(results)
            
            return F
        except Exception as e:
            logger.warning(f"Parallel evaluation failed: {e}; falling back to serial mode")
            return self._evaluate_serial(x)
    
    def _evaluate_single_solution(self, x_i: np.ndarray, eval_id: int) -> np.ndarray:
        """Evaluate one solution in serial mode."""
        # Create modified model
        modified_model = self._create_modified_model(x_i)
        
        # Generate events
        try:
            seed_mgr = SeedManager(modified_model.meta.seed + eval_id)
            constructor = FastPathConstructor(modified_model, seed_mgr)
            events = constructor.generate_events()
            
            # Estimate metrics
            metrics_engine = MetricsEngine(modified_model, events)
            observed = metrics_engine.estimate()
            
            # Calculate objectives
            return self._calculate_objectives(observed)
            
        except Exception as e:
            logger.warning(f"Evaluation {eval_id} failed: {e}")
            # Penalize failed evaluations
            return np.full(self.n_obj, 10.0)
    
    def _calculate_objectives(self, observed: Dict[str, Any]) -> np.ndarray:
        """Compute objective values."""
        F = np.zeros(self.n_obj)
        
        # Extract targets
        scv_a_target = self.target_metrics.get("scv_a", 1.0)
        scv_p_target = self.target_metrics.get("scv_p", 1.0)
        ddt_target = self.target_metrics.get("ddt", 2.0)
        load_cv_target = self.target_metrics.get("load_cv", 0.2)
        
        # Extract observed
        scv_a_obs = observed.get("scv_a", 0.0)
        scv_p_obs = observed.get("scv_p", 0.0)
        ddt_obs = observed.get("ddt", 0.0)
        rho_bn_obs = observed.get("rho_bottleneck", 0.0)
        load_cv_obs = observed.get("load_cv", 0.0)
        
        # Calculate normalized errors
        if scv_a_target < 0.01:
            F[0] = abs(scv_a_obs)
        else:
            F[0] = abs(scv_a_obs - scv_a_target) / (scv_a_target + 0.1)
        
        if scv_p_target < 0.01:
            F[1] = abs(scv_p_obs)
        else:
            F[1] = abs(scv_p_obs - scv_p_target) / (scv_p_target + 0.1)
        
        F[2] = abs(ddt_obs - ddt_target) / (ddt_target + 1e-6)
        
        obj_idx = 3
        if self.has_bottleneck and obj_idx < self.n_obj:
            F[obj_idx] = abs(rho_bn_obs) / 0.8
            obj_idx += 1

        if self.has_load_cv and obj_idx < self.n_obj:
            if load_cv_target < 1e-6:
                F[obj_idx] = abs(load_cv_obs)
            else:
                F[obj_idx] = abs(load_cv_obs - load_cv_target) / (load_cv_target + 0.01)
            obj_idx += 1
        
        return F
    
    def _create_modified_model(self, x: np.ndarray) -> InputModel:
        """
        Create a modified model based on decision variables.
        
        Args:
            x: Array of shape (5,) with [scv_a_scale, scv_p_scale, ddt_scale, bottleneck_rho_scale, load_cv_scale]
        """
        modified = copy.deepcopy(self.base_model)
        
        scv_a_scale = x[0]
        scv_p_scale = x[1]
        ddt_scale = x[2]
        bottleneck_rho_scale = x[3]
        load_cv_scale = x[4]
        
        # Modify arrival SCV (special handling for zero-variation)
        base_scv_a = float(modified.targets.scv_a)
        if base_scv_a < 0.01:  # Zero or near-zero - don't scale, keep at 0
            modified.targets.scv_a = 0.0
        else:
            modified.targets.scv_a = base_scv_a * scv_a_scale
        
        # Modify process SCV (special handling for zero-variation)
        base_scv_p = float(modified.targets.scv_p)
        if base_scv_p < 0.01:  # Zero or near-zero - don't scale, keep at 0
            modified.targets.scv_p = 0.0
        else:
            modified.targets.scv_p = base_scv_p * scv_p_scale
        
        # Modify DDT
        base_ddt = float(modified.targets.ddt)
        modified.targets.ddt = base_ddt * ddt_scale
        
        # CRITICAL FIX: Clear jobs_total so Constructor respects target changes
        # MOO modifies targets, but if jobs_total is fixed, Constructor ignores them
        modified.scale.jobs_total = None
        
        # Modify bottleneck rho targets if they exist
        if self.has_bottleneck and modified.targets.rho_bottleneck:
            for bn in modified.targets.rho_bottleneck:
                # Scale the target rho with bounds checking
                # Keep within physically feasible range [0.3, 0.95]
                original_rho = float(bn.rho)
                scaled_rho = original_rho * bottleneck_rho_scale
                bn.rho = float(np.clip(scaled_rho, 0.3, 0.95))
        
        # NEW: Load_cv control via job mix weighting
        if self.has_load_cv and modified.targets.load_cv is not None:
            if len(self.base_job_mix_weights) == len(modified.plant.process_templates):
                base_weights = np.array(self.base_job_mix_weights, dtype=float)
                alpha = np.interp(load_cv_scale, [0.7, 1.4], [0.3, 3.0])
                adjusted = np.clip(base_weights, 1e-6, None) ** alpha
                adjusted = adjusted / adjusted.sum()
                modified.plant.job_mix_weights = adjusted.tolist()
        
        return modified


class HybridCalibrator:
    """
    Hybrid calibration strategy (5D MOO):
    
    Use MOO to optimize coupled metrics (scv_a, scv_p, ddt, rho_bottleneck, load_cv).
    rho_global and disturbance are automatically handled by Constructor based on targets.
    
    Features:
    - 5D decision space with load_cv scaling
    - 5D objective space with all coupled metrics
    - Convergence detection for early stopping
    - Intelligent load_cv preprocessing
    """
    
    def __init__(
        self,
        model: InputModel,
        target_metrics: Dict[str, float],
        population_size: int = 100,      # Increased for 5D space
        n_generations: int = 120,        # Large max, prefer convergence-based stopping
        convergence_window: int = 15,    # Check last N generations
        convergence_tol: float = 0.0003, # 0.03% improvement threshold (stricter)
        max_sequential_steps: int = 10,
        primary_metric: Optional[str] = None,
    ):
        self.base_model = model
        self.target_metrics = target_metrics
        self.population_size = population_size
        self.n_generations = n_generations
        self.convergence_window = convergence_window
        self.convergence_tol = convergence_tol
        self.generation_history = []  # Track best error per generation
        self.max_sequential_steps = max_sequential_steps
        self.has_load_cv = getattr(model.targets, "load_cv", None) is not None
        self.has_bottleneck = bool(model.targets.rho_bottleneck)
        self.primary_metric = primary_metric
        
    def _check_convergence(self, algorithm) -> bool:
        """
        Check if optimization has converged by tracking improvement over last N generations.
        
        Returns:
            True if converged (no significant improvement), False otherwise
        """
        if algorithm.n_gen < self.convergence_window:
            return False  # Not enough history yet
        
        # Get current best total error (sum of objectives)
        current_best_f = algorithm.pop.get("F").min(axis=0).sum()
        self.generation_history.append(current_best_f)
        
        # Check last convergence_window generations
        if len(self.generation_history) < self.convergence_window:
            return False
        
        recent_errors = self.generation_history[-self.convergence_window:]
        oldest_error = recent_errors[0]
        newest_error = recent_errors[-1]
        
        # Check if improvement is less than tolerance
        improvement = oldest_error - newest_error
        relative_improvement = improvement / (oldest_error + 1e-9)
        
        if relative_improvement < self.convergence_tol:
            logger.info(f"Convergence detected at generation {algorithm.n_gen}")
            logger.info(f"   Improvement over last {self.convergence_window} gens: {relative_improvement*100:.3f}% < {self.convergence_tol*100:.3f}%")
            return True
        
        return False
        
    def calibrate(self) -> Tuple[list, Optional[Dict[str, Any]]]:
        """
        Run hybrid calibration (4D MOO with convergence detection).
        
        Returns:
            events: Generated events
            info: Calibration info including pareto front data
        """
        logger.info("=" * 80)
        logger.info("Starting HYBRID calibration (coupled metrics MOO)")
        logger.info("=" * 80)
        logger.info("Strategy: Optimize coupled metrics (scv_a, scv_p, ddt, rho_bottleneck, load_cv)")
        logger.info("rho_global & disturbance are auto-calculated by Constructor")
        logger.info("=" * 80)
        
        if not PYMOO_AVAILABLE:
            logger.error("pymoo not available; cannot run Hybrid calibration")
            logger.info("Falling back to basic generation...")
            # Fallback: just generate events with original model
            seed_mgr = SeedManager(self.base_model.meta.seed)
            constructor = FastPathConstructor(self.base_model, seed_mgr)
            events = constructor.generate_events()
            return events, None
        
        # Create MOO problem
        problem = CoupledMetricsProblem(
            base_model=self.base_model,
            target_metrics=self.target_metrics
        )
        
        # Setup NSGA-II
        algorithm = NSGA2(pop_size=self.population_size)
        
        logger.info("Running NSGA-II with adaptive termination:")
        logger.info(f"   Population size: {self.population_size}")
        logger.info(f"   Max generations: {self.n_generations} (prefer early convergence)")
        logger.info(f"   Decision space: 5D (scv_a_scale, scv_p_scale, ddt_scale, bottleneck_rho_scale, load_cv_shape)")
        logger.info(f"   Objective space: {problem.n_obj}D")
        logger.info(f"   Convergence window: {self.convergence_window} generations")
        logger.info(f"   Convergence tolerance: {self.convergence_tol*100:.3f}% improvement")
        
        # Custom termination with convergence check
        from pymoo.termination.default import DefaultMultiObjectiveTermination
        from pymoo.termination.max_gen import MaximumGenerationTermination
        
        # Combine default multi-objective termination with max generation limit
        # This will stop early if objectives converge
        termination = DefaultMultiObjectiveTermination(
            xtol=1e-5,
            cvtol=1e-6,
            ftol=self.convergence_tol,
            period=self.convergence_window,
            n_max_gen=self.n_generations
        )
        
        # Run optimization
        res = minimize(
            problem,
            algorithm,
            termination,
            seed=int(self.base_model.meta.seed),
            verbose=False
        )
        
        actual_generations = res.algorithm.n_gen
        logger.info(
            f"Optimization complete: {actual_generations}/{self.n_generations} generations"
        )
        
        # Extract Pareto front
        pareto_F = res.F  # Objective values
        pareto_X = res.X  # Decision variables
        
        logger.info(f"Pareto front size: {len(pareto_F)}")
        
        # Find best solution
        objective_labels = problem.objective_labels
        best_idx, selection_method = self._find_best_solution(pareto_F, objective_labels)
        best_x = pareto_X[best_idx]
        best_f = pareto_F[best_idx]
        
        logger.info(f"Selected solution (method: {selection_method}):")
        decision_parts = [
            f"scv_a_scale={best_x[0]:.3f}",
            f"scv_p_scale={best_x[1]:.3f}",
            f"ddt_scale={best_x[2]:.3f}",
        ]
        if problem.has_bottleneck:
            decision_parts.append(f"bn_rho_scale={best_x[3]:.3f}")
        if problem.has_load_cv:
            load_idx = 4 if problem.has_bottleneck else 3
            decision_parts.append(f"job_mix_alpha={best_x[load_idx]:.3f}")
        logger.info("   " + ", ".join(decision_parts))

        error_parts = [
            f"scv_a_error={best_f[0]*100:.2f}%",
            f"scv_p_error={best_f[1]*100:.2f}%",
            f"ddt_error={best_f[2]*100:.2f}%",
        ]
        obj_idx = 3
        if problem.has_bottleneck and obj_idx < len(best_f):
            error_parts.append(f"rho_bn_error={best_f[obj_idx]*100:.2f}%")
            obj_idx += 1
        if problem.has_load_cv and obj_idx < len(best_f):
            error_parts.append(f"load_cv_error={best_f[obj_idx]*100:.2f}%")
        logger.info("   " + ", ".join(error_parts))
        
        # Deterministic evaluation for each Pareto solution (for exact replay)
        base_seed = int(self.base_model.meta.seed)
        det_F_list: List[np.ndarray] = []
        det_seeds: List[int] = []
        for idx, x in enumerate(pareto_X):
            det_seed = base_seed + 10000 + int(idx)
            det_seeds.append(det_seed)
            try:
                det_model = problem._create_modified_model(x)
                seed_mgr = SeedManager(det_seed)
                constructor_det = FastPathConstructor(det_model, seed_mgr)
                det_events = constructor_det.generate_events()

                det_engine = MetricsEngine(det_model, det_events)
                det_metrics = det_engine.estimate()

                # Reuse the same objective definitions as in CoupledMetricsProblem._calculate_objectives
                det_F = problem._calculate_objectives(det_metrics)
                det_F_list.append(np.asarray(det_F, dtype=float))
            except Exception as det_exc:
                logger.warning(f"Deterministic evaluation failed for Pareto idx {idx}: {det_exc}")
                det_F_list.append(np.full(problem.n_obj, 10.0, dtype=float))

        det_pareto_F = np.vstack(det_F_list) if det_F_list else pareto_F
        best_det_f = det_pareto_F[best_idx]

        # Apply best solution to model and generate final events
        final_model = problem._create_modified_model(best_x)
        seed_mgr = SeedManager(final_model.meta.seed)
        constructor = FastPathConstructor(final_model, seed_mgr)
        events = constructor.generate_events()

        # Sequential refinement for main metrics
        refined_events = events
        tolerances = {
            "rho_global": 0.05,
            "scv_a": 0.08,
            "scv_p": 0.08,
            "ddt": 0.04,
            "load_cv": 0.05,
            "rho_bottleneck": 0.05,
            "disturbance": 0.03,
        }

        if self.max_sequential_steps > 0:
            logger.info(
                f"Sequential refinement: up to {self.max_sequential_steps} steps"
            )

            focus_metrics = []
            if "rho_global" in self.target_metrics and self.target_metrics["rho_global"] is not None:
                focus_metrics.append("rho_global")
            if "load_cv" in self.target_metrics and self.target_metrics["load_cv"] is not None:
                focus_metrics.append("load_cv")
            focus_metrics.extend(["ddt", "scv_a", "scv_p"])
            if self.base_model.targets.rho_bottleneck:
                focus_metrics.append("rho_bottleneck")
            if "disturbance" in self.target_metrics and self.target_metrics["disturbance"] is not None and self.target_metrics["disturbance"] > 0:
                focus_metrics.append("disturbance")

            best_events = copy.deepcopy(refined_events)
            best_primary_error = float("inf")
            best_total_error = float("inf")

            for step in range(self.max_sequential_steps):
                metrics_engine = MetricsEngine(final_model, refined_events)
                observed_metrics = metrics_engine.estimate()

                def _metric_error(metric: str) -> float:
                    target = self.target_metrics.get(metric, 0.0)
                    observed = observed_metrics.get(metric, 0.0)
                    if metric == "rho_bottleneck":
                        return abs(observed)
                    if target < 1e-6:
                        return abs(observed)
                    return abs(observed - target) / (abs(target) + 1e-6)

                errors = {
                    metric: _metric_error(metric)
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

                if "rho_global" in errors and errors["rho_global"] > 0.08:
                    errors["rho_global"] *= 1.3
                
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
                    logger.info("Sequential refinement converged early")
                    break

                logger.info(
                    f"   Step {step+1}: refining {metric} (error={error_value*100:.1f}%, tol={tolerance*100:.1f}%)"
                )

                seq_targets: Dict[str, float] = {"rho_bottleneck": 0.0}
                if "rho_global" in self.target_metrics:
                    seq_targets["rho_global"] = self.target_metrics["rho_global"]
                if "scv_a" in self.target_metrics:
                    seq_targets["scv_a"] = self.target_metrics["scv_a"]
                if "scv_p" in self.target_metrics:
                    seq_targets["scv_p"] = self.target_metrics["scv_p"]
                if "ddt" in self.target_metrics:
                    seq_targets["ddt"] = self.target_metrics["ddt"]
                if "load_cv" in self.target_metrics and self.target_metrics["load_cv"] is not None:
                    seq_targets["load_cv"] = self.target_metrics["load_cv"]
                if "disturbance" in self.target_metrics:
                    seq_targets["disturbance"] = self.target_metrics["disturbance"]

                observed_subset = {k: observed_metrics.get(k, 0.0) for k in seq_targets}

                calibrator = Calibrator(final_model, refined_events, seq_targets, observed_subset)
                refined_events = calibrator.calibrate()

            refined_events = best_events
            events = refined_events

        if self.primary_metric and self.primary_metric in self.target_metrics:
            prev_error = None
            best_events = copy.deepcopy(events)
            best_primary_error = float("inf")
            for _ in range(20):
                metrics_engine = MetricsEngine(final_model, events)
                observed_metrics = metrics_engine.estimate()

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
                    best_events = copy.deepcopy(events)

                if primary_error <= tolerances.get(self.primary_metric, 0.05) / 2:
                    break
                if prev_error is not None and prev_error - primary_error < 1e-3:
                    break
                prev_error = primary_error

                primary_targets = {"rho_bottleneck": 0.0, self.primary_metric: target_val}
                observed_subset = {k: observed_metrics.get(k, 0.0) for k in primary_targets}
                calibrator = Calibrator(
                    final_model,
                    events,
                    primary_targets,
                    observed_subset,
                    use_synergy=False,
                )
                events = calibrator.calibrate()

            events = best_events

        # Calculate all final metrics (including rho and disturbance)
        metrics_engine = MetricsEngine(final_model, events)
        final_metrics = metrics_engine.estimate()
        
        logger.info("\n" + "=" * 80)
        logger.info("Hybrid calibration complete")
        logger.info("=" * 80)
        logger.info("Final metrics summary:")
        
        # Collect all errors for total calculation
        all_errors = []
        
        for k in ["rho_global", "scv_a", "scv_p", "ddt", "disturbance", "rho_bottleneck", "load_cv"]:
            target_val = self.target_metrics.get(k, 0.0)
            observed_val = final_metrics.get(k, 0.0)
            
            # Special handling for rho_bottleneck (it's already an error L2 norm)
            if k == "rho_bottleneck":
                if self.base_model.targets.rho_bottleneck:
                    target_rhos = [float(getattr(bn, "rho", 0.0)) for bn in self.base_model.targets.rho_bottleneck]
                    denom = float(np.linalg.norm(np.array(target_rhos, dtype=float)))
                    error = (observed_val / denom) * 100 if denom > 1e-9 else (observed_val * 100)
                    logger.info(f"  {k:15s}: Error_L2={observed_val:.4f}, Relative={error:.2f}%")
                    all_errors.append(error / 100.0)  # Normalize to [0,1] scale
                else:
                    logger.info(f"  {k:15s}: No target specified")
            else:
                # Calculate error with proper handling for zero targets
                absolute_error = abs(observed_val - target_val)
                
                if target_val < 1e-6:  # Target is zero or near-zero
                    # Use absolute error directly (as percentage of a nominal value)
                    error = absolute_error * 100  # Treat as percentage
                    logger.info(f"  {k:15s}: Target={target_val:.3f}, Observed={observed_val:.3f}, AbsError={absolute_error:.4f} ({error:.2f}%)")
                    all_errors.append(absolute_error)  # Use absolute error for near-zero targets
                else:
                    # Use relative error
                    error = (absolute_error / target_val) * 100
                    logger.info(f"  {k:15s}: Target={target_val:.3f}, Observed={observed_val:.3f}, Error={error:.2f}%")
                    all_errors.append(error / 100.0)  # Normalize to [0,1] scale
        
        # Calculate total error
        total_error = sum(all_errors)
        mean_error = total_error / len(all_errors) * 100
        logger.info(f"\n  {'Total Error':15s}: {total_error:.4f} (sum of normalized errors)")
        logger.info(f"  {'Mean Error':15s}: {mean_error:.2f}% (average across all metrics)")
        
        # Prepare pareto info with extended data for advise-params and replay UX
        objective_labels = problem.objective_labels

        # Combine id, deterministic objectives, and decision variables per solution for better UX
        pareto_points = []
        for idx in range(len(det_pareto_F)):
            pareto_points.append(
                {
                    "id": int(idx),
                    "objectives": det_pareto_F[idx].tolist(),
                    "decision_vars": pareto_X[idx].tolist(),
                    "deterministic_seed": int(det_seeds[idx]),
                }
            )

        pareto_info = {
            "pareto_front_size": len(det_pareto_F),
            "best_index": int(best_idx),
            "best_decision_vars": best_x.tolist(),
            "best_objectives": best_det_f.tolist(),
            "selection_method": selection_method,
            "objective_labels": objective_labels,
            "pareto_points": pareto_points,
            "calibration_mode": "hybrid_5d_moo",
            "actual_generations": actual_generations,
            "max_generations": self.n_generations,
            "converged_early": actual_generations < self.n_generations,
            # Extended data for advise-params
            "total_error": float(total_error),
            "mean_error": float(mean_error),
            "target_metrics": self.target_metrics,
            "final_metrics": {k: float(v) if isinstance(v, (int, float)) else v 
                            for k, v in final_metrics.items() if k != "SSI"},
            "metric_errors": self._compute_metric_errors(final_metrics),
            "pareto_diversity": {
                "total_error_range": [float(det_pareto_F.sum(axis=1).min()), float(det_pareto_F.sum(axis=1).max())],
                "max_error_range": [float(det_pareto_F.max(axis=1).min()), float(det_pareto_F.max(axis=1).max())],
            }
        }
        
        return events, pareto_info
    
    def _compute_metric_errors(self, final_metrics: Dict[str, float]) -> Dict[str, float]:
        errors: Dict[str, float] = {}

        if "rho_global" in self.target_metrics:
            errors["rho_global"] = abs(final_metrics.get("rho_global", 0.0) - self.target_metrics["rho_global"]) / (self.target_metrics["rho_global"] + 1e-6) * 100

        if "scv_a" in self.target_metrics:
            errors["scv_a"] = abs(final_metrics.get("scv_a", 0.0) - self.target_metrics["scv_a"]) / (self.target_metrics["scv_a"] + 0.1) * 100

        if "scv_p" in self.target_metrics:
            errors["scv_p"] = abs(final_metrics.get("scv_p", 0.0) - self.target_metrics["scv_p"]) / (self.target_metrics["scv_p"] + 0.1) * 100

        if "ddt" in self.target_metrics:
            errors["ddt"] = abs(final_metrics.get("ddt", 0.0) - self.target_metrics["ddt"]) / (self.target_metrics["ddt"] + 1e-6) * 100

        if "disturbance" in self.target_metrics:
            dist_target = self.target_metrics["disturbance"]
            if dist_target > 1e-6:
                errors["disturbance"] = abs(final_metrics.get("disturbance", 0.0) - dist_target) / (dist_target + 1e-6) * 100
            else:
                errors["disturbance"] = abs(final_metrics.get("disturbance", 0.0)) * 100

        if self.has_load_cv and "load_cv" in self.target_metrics and self.target_metrics["load_cv"] is not None:
            load_target = self.target_metrics["load_cv"]
            if load_target < 1e-6:
                errors["load_cv"] = abs(final_metrics.get("load_cv", 0.0)) * 100
            else:
                errors["load_cv"] = abs(final_metrics.get("load_cv", 0.0) - load_target) / (load_target + 0.01) * 100

        if self.has_bottleneck:
            errors["rho_bottleneck"] = abs(final_metrics.get("rho_bottleneck", 0.0)) / 0.8 * 100

        return errors

    def _find_best_solution(
        self,
        pareto_F: np.ndarray,
        objective_labels: List[str],
    ) -> Tuple[int, str]:
        primary_metric = self.primary_metric
        if primary_metric is None:
            if "load_cv" in self.target_metrics and self.target_metrics["load_cv"] is not None:
                primary_metric = "load_cv"
            else:
                primary_metric = "ddt"

        best_idx, reason = find_best_constrained_solution(
            pareto_F,
            self.target_metrics,
            objective_labels,
            primary_metric,
        )

        total_errors = pareto_F.sum(axis=1)
        max_errors = pareto_F.max(axis=1)
        logger.info("   Pareto front analysis:")
        logger.info(f"     Total error range: [{total_errors.min():.4f}, {total_errors.max():.4f}]")
        logger.info(f"     Max error range: [{max_errors.min():.4f}, {max_errors.max():.4f}]")
        logger.info(f"   Selection reason: {reason}")
        logger.info(f"     Selected solution index: {best_idx}")

        return best_idx, reason
