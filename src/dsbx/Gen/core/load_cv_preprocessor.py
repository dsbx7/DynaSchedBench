"""Load-CV preprocessor for computing job-mix weights before calibration.

The preprocessor estimates job-family weights that move predicted ``load_cv``
toward the target, reducing the number of calibration iterations required."""
from typing import List, Dict, Optional, Tuple
import numpy as np
from scipy.optimize import minimize
from loguru import logger

from ..models.inputs import InputModel


class LoadCVPreprocessor:
    """Preprocessor for load-CV target matching.

    It estimates each process template's contribution to machine-group load,
    solves for job-mix weights, and makes the predicted ``load_cv`` closer to
    the requested target.
    """
    
    def __init__(self, model: InputModel):
        """Initialize the preprocessor.

        Args:
            model: Input configuration model.
        """
        self.model = model
        self.machine_groups = self._extract_machine_groups()
        self.templates = model.plant.process_templates
        
        self.machines_per_group = self._count_machines_per_group()
        self.speed_per_group = self._sum_speed_per_group()
        self.last_diagnostics: Optional[Dict[str, float]] = None
        
    def calculate_optimal_weights(self, target_load_cv: float) -> List[float]:
        """Compute job-mix weights that make predicted load-CV approach the target.

        The routine builds a template-by-machine-group workload matrix and uses
        SLSQP to minimize ``abs(predicted_load_cv - target_load_cv)`` subject to
        weights summing to one and remaining non-negative.

        Args:
            target_load_cv: Target load coefficient of variation.

        Returns:
            Optimized ``job_mix_weights`` list.
        """
        n_templates = len(self.templates)
        
        if n_templates == 1:
            logger.info("Only one process template, using weight=1.0")
            return [1.0]
        
        workload_matrix = self._calculate_workload_matrix()
        
        if workload_matrix is None or workload_matrix.size == 0:
            logger.warning("Failed to calculate workload matrix; using uniform weights")
            return [1.0 / n_templates] * n_templates
        
        feasible_min, feasible_max = self._estimate_feasible_range(workload_matrix)
        target_opt = float(np.clip(target_load_cv, feasible_min, feasible_max))
        if abs(target_opt - target_load_cv) > 1e-6:
            logger.warning(
                "load_cv target %.3f is outside feasible range [%.3f, %.3f]; "
                "clipped to %.3f",
                target_load_cv,
                feasible_min,
                feasible_max,
                target_opt,
            )

        def objective(weights):
            """Objective: minimize abs(predicted_load_cv - target_opt)."""
            predicted_cv = self._predict_load_cv(weights, workload_matrix)
            return abs(predicted_cv - target_opt)
        
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},
        ]
        
        bounds = [(0.0, 1.0) for _ in range(n_templates)]
        
        x0 = np.ones(n_templates) / n_templates
        
        try:
            result = minimize(
                objective,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 200, 'ftol': 1e-6}
            )
            
            if result.success:
                optimal_weights = result.x.tolist()
                predicted_cv = self._predict_load_cv(result.x, workload_matrix)

                logger.info(
                    "Successfully found optimal job_mix_weights: "
                    f"{[f'{w:.3f}' for w in optimal_weights]}"
                )
                logger.info(
                    f"Predicted load_cv: {predicted_cv:.3f}, "
                    f"target: {target_load_cv:.3f}, "
                    f"error: {abs(predicted_cv - target_load_cv):.3f}"
                )

                diagnostics = {
                    "target": float(target_load_cv),
                    "clipped_target": target_opt,
                    "predicted_cv": float(predicted_cv),
                    "feasible_min": feasible_min,
                    "feasible_max": feasible_max,
                    "error": abs(predicted_cv - target_load_cv),
                }
                self.last_diagnostics = diagnostics

                if abs(predicted_cv - target_load_cv) > 0.05:
                    logger.info(
                        "Optimal result still deviates from target "
                        f"(error={abs(predicted_cv - target_load_cv):.3f}), "
                        "but using optimized weights (more accurate than heuristic)"
                    )

                return optimal_weights
            else:
                logger.warning(
                    f"Optimization failed: {result.message}; using uniform weights"
                )
                fallback = self._approximate_weights(target_load_cv, workload_matrix, feasible_min, feasible_max)
                self.last_diagnostics = {
                    "target": float(target_load_cv),
                    "clipped_target": target_opt,
                    "predicted_cv": float(self._predict_load_cv(fallback, workload_matrix)),
                    "feasible_min": feasible_min,
                    "feasible_max": feasible_max,
                    "error": abs(self._predict_load_cv(fallback, workload_matrix) - target_load_cv),
                }
                return fallback
                
        except Exception as e:
            logger.error(
                f"Error during optimization: {e}; using uniform weights"
            )
            fallback = self._approximate_weights(target_load_cv, workload_matrix, feasible_min, feasible_max)
            self.last_diagnostics = {
                "target": float(target_load_cv),
                "clipped_target": target_opt,
                "predicted_cv": float(self._predict_load_cv(fallback, workload_matrix)),
                "feasible_min": feasible_min,
                "feasible_max": feasible_max,
                "error": abs(self._predict_load_cv(fallback, workload_matrix) - target_load_cv),
            }
            return fallback
    
    def _calculate_workload_matrix(self) -> Optional[np.ndarray]:
        """Compute each template's workload contribution to each machine group.

        Returns:
            Matrix of shape ``(n_templates, n_groups)`` where ``matrix[i][j]``
            is the per-job load contribution from template ``i`` to group ``j``.
        """
        n_templates = len(self.templates)
        n_groups = len(self.machine_groups)
        
        if n_groups == 0:
            logger.warning("No machine groups found")
            return None
        
        matrix = np.zeros((n_templates, n_groups))
        
        for i, template in enumerate(self.templates):
            for step in template.route:
                group_name = step.machine_group
                
                if group_name not in self.machine_groups:
                    logger.warning(f"Group {group_name} in template {template.family} not found in machines")
                    continue
                
                group_idx = self.machine_groups.index(group_name)
                
                workload = step.process_time.mean
                
                sum_speed = self.speed_per_group.get(group_name, None)
                if sum_speed is None or sum_speed <= 0:
                    sum_speed = max(1.0, float(self.machines_per_group.get(group_name, 1)))
                matrix[i, group_idx] += workload / float(sum_speed)
        
        return matrix
    
    def _predict_load_cv(self, weights: np.ndarray, workload_matrix: np.ndarray) -> float:
        """Predict load-CV under a given job-mix vector.

        Args:
            weights: Job-mix weights.
            workload_matrix: Workload contribution matrix.

        Returns:
            Predicted load-CV value.
        """
        # group_loads[j] = Σ(weights[i] * workload_matrix[i][j])
        group_loads = np.dot(weights, workload_matrix)
        
        non_zero_loads = group_loads[group_loads > 1e-9]
        
        if len(non_zero_loads) < 2:
            return 0.0
        
        mean_load = np.mean(non_zero_loads)
        std_load = np.std(non_zero_loads)
        
        if mean_load < 1e-9:
            return 0.0
        
        cv = std_load / mean_load
        return float(cv)

    def _estimate_feasible_range(self, workload_matrix: np.ndarray) -> Tuple[float, float]:
        """Estimate the achievable load-CV range."""
        n_templates = workload_matrix.shape[0]
        uniform = np.ones(n_templates) / n_templates
        min_cv = self._predict_load_cv(uniform, workload_matrix)

        extreme_values = []
        for idx in range(n_templates):
            weights = np.zeros(n_templates)
            weights[idx] = 1.0
            extreme_values.append(self._predict_load_cv(weights, workload_matrix))

        max_cv = max(extreme_values) if extreme_values else min_cv
        return float(min_cv), float(max_cv)

    def _approximate_weights(
        self,
        target_load_cv: float,
        workload_matrix: np.ndarray,
        feasible_min: float,
        feasible_max: float,
    ) -> List[float]:
        n_templates = workload_matrix.shape[0]
        if n_templates == 0:
            return []

        uniform = np.ones(n_templates) / n_templates
        if feasible_max - feasible_min < 1e-6:
            return uniform.tolist()

        extreme_scores = []
        for idx in range(n_templates):
            weights = np.zeros(n_templates)
            weights[idx] = 1.0
            extreme_scores.append(self._predict_load_cv(weights, workload_matrix))
        extreme_idx = int(np.argmax(extreme_scores)) if extreme_scores else 0
        extreme = np.zeros(n_templates)
        extreme[extreme_idx] = 1.0

        mix = (target_load_cv - feasible_min) / max(feasible_max - feasible_min, 1e-6)
        mix = float(np.clip(mix, 0.0, 1.0))
        blended = (1 - mix) * uniform + mix * extreme
        blended = np.clip(blended, 1e-6, None)
        blended /= blended.sum()
        logger.info(
            "Using heuristic approximate weights: mix=%.2f -> %s",
            mix,
            [f"{w:.3f}" for w in blended],
        )
        return blended.tolist()

    def diagnose_target_feasibility(self, target_load_cv: float) -> Dict[str, float]:
        """Return feasibility diagnostics for a load-CV target."""
        matrix = self._calculate_workload_matrix()
        if matrix is None:
            return {
                "target": target_load_cv,
                "status": "unavailable",
            }

        feasible_min, feasible_max = self._estimate_feasible_range(matrix)
        clipped = float(np.clip(target_load_cv, feasible_min, feasible_max))
        return {
            "target": float(target_load_cv),
            "feasible_min": feasible_min,
            "feasible_max": feasible_max,
            "clipped_target": clipped,
        }
    
    def _extract_machine_groups(self) -> List[str]:
        """Extract machine-group names while preserving order."""
        groups = []
        seen = set()
        
        for machine in self.model.plant.machines:
            if machine.group not in seen:
                groups.append(machine.group)
                seen.add(machine.group)
        
        return groups
    
    def _count_machines_per_group(self) -> Dict[str, int]:
        """Count machines in each machine group."""
        counts = {}
        
        for machine in self.model.plant.machines:
            counts[machine.group] = counts.get(machine.group, 0) + 1
        
        return counts

    def _sum_speed_per_group(self) -> Dict[str, float]:
        speeds = {}
        for machine in self.model.plant.machines:
            sp = getattr(machine, "speed", 1.0)
            speeds[machine.group] = speeds.get(machine.group, 0.0) + float(sp)
        return speeds
    
    def should_preprocess(self) -> bool:
        """Return whether load-CV preprocessing should run.

        Returns:
            True when preprocessing is applicable.
        """
        if self.model.targets.load_cv is None:
            return False
        
        if self.model.plant.job_mix_weights is not None:
            logger.info("User has specified job_mix_weights; skipping preprocessing")
            return False
        
        if len(self.model.plant.process_templates) < 2:
            logger.info("Only one process template; no need for preprocessing")
            return False
        
        if len(self.machine_groups) < 2:
            logger.info("Only one machine group; cannot adjust load_cv")
            return False
        
        return True
    
    def apply_optimal_weights(self, optimal_weights: List[float]) -> None:
        """Apply optimized weights to the input model.

        Args:
            optimal_weights: Computed optimal weights.
        """
        self.model.plant.job_mix_weights = optimal_weights
        logger.info(
            f"Applied optimal job_mix_weights to model: "
            f"{[f'{w:.3f}' for w in optimal_weights]}"
        )





