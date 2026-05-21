"""Convergence detector for calibration loops.

The detector combines L2 error checks, per-metric thresholds, and early stopping
when no meaningful improvement is observed for several consecutive steps."""
from typing import Dict, List, Tuple
import numpy as np
from loguru import logger


class ConvergenceDetector:
    """Detect whether calibration has converged and avoid unnecessary iterations."""
    
    def __init__(
        self, 
        l2_threshold: float = 0.05,
        individual_threshold: float = 0.02,
        patience: int = 3,
        min_improvement: float = 0.001,
    ):
        """Initialize the convergence detector.

        Args:
            l2_threshold: L2 error convergence threshold.
            individual_threshold: Per-metric error threshold.
            patience: Number of consecutive non-improving steps for early stop.
            min_improvement: Minimum improvement required to count as progress.
        """
        self.l2_threshold = l2_threshold
        self.individual_threshold = individual_threshold
        self.patience = patience
        self.min_improvement = min_improvement
        self.history: List[Dict[str, Any]] = []
    
    def check_convergence(
        self, 
        targets: Dict[str, float], 
        observed: Dict[str, float],
        step: int,
    ) -> Tuple[bool, str]:
        """Check whether the current calibration step has converged.

        Args:
            targets: Target metric dictionary.
            observed: Observed metric dictionary.
            step: Current step index.

        Returns:
            Tuple of ``(converged, reason)``.
        """
        current_errors = self._calculate_errors(targets, observed)
        self.history.append(current_errors)
        
        l2_error = current_errors['l2']
        if l2_error < self.l2_threshold:
            # Further check single metric
            individual_errors = current_errors['individual']
            max_individual = max(individual_errors.values()) if individual_errors else 0
            
            if max_individual < self.individual_threshold:
                logger.info(
                    f"Convergence detected: L2={l2_error:.4f} < {self.l2_threshold}, "
                    f"max_individual={max_individual:.4f} < {self.individual_threshold}"
                )
                return True, f"converged: L2={l2_error:.4f}, max_individual={max_individual:.4f}"
            else:
                # L2 converged but individual metric still large
                max_metric = max(individual_errors.items(), key=lambda x: x[1])
                logger.debug(
                    f"L2 converged but {max_metric[0]} error {max_metric[1]:.4f} "
                    f"is still greater than {self.individual_threshold}"
                )
        
        # Check 2: Early stopping (consecutive N steps without significant improvement)
        if len(self.history) >= self.patience + 1:
            recent_l2s = [h['l2'] for h in self.history[-(self.patience+1):]]
            
            # Calculate consecutive improvements
            improvements = [recent_l2s[i] - recent_l2s[i+1] 
                          for i in range(len(recent_l2s)-1)]
            
            # If consecutive patience steps improvement are all < min_improvement
            if all(imp < self.min_improvement for imp in improvements):
                avg_improvement = np.mean(improvements)
                logger.info(
                    f"Early stopping: average improvement over {self.patience} steps "
                    f"is {avg_improvement:.5f} < {self.min_improvement}"
                )
                return True, f"early_stop: no improvement for {self.patience} steps (avg_imp={avg_improvement:.5f})"
        
        # Check 3: Perfect convergence (all metric errors are extremely small)
        individual_errors = current_errors['individual']
        if individual_errors and all(err < 0.01 for err in individual_errors.values()):
            logger.info("Perfect convergence: all metric errors are below 1%")
            return True, "perfect_convergence: all metrics < 1%"
        
        return False, "not_converged"
    
    def _calculate_errors(self, targets: Dict[str, float], observed: Dict[str, float]) -> Dict[str, Any]:
        """Calculates various errors
        
        Args:
            targets: Target value dictionary
            observed: Observed value dictionary
            
        Returns:
            Dictionary containing L2 error and individual errors
        """
        individual_errors: Dict[str, float] = {}
        l2_components: List[float] = []
        
        # All possible target metrics
        all_metrics = ['rho_global', 'scv_a', 'scv_p', 'ddt', 'disturbance', 'load_cv']
        
        for key in all_metrics:
            if key not in targets or key not in observed:
                continue
            
            t = float(targets[key])
            o = float(observed[key])
            
            if abs(t) < 1e-6:
                # Use absolute error when target is zero
                err = abs(o)
            else:
                # Relative error
                err = abs(o - t) / abs(t)
            
            individual_errors[key] = err
            l2_components.append(err ** 2)
        
        # rho_bottleneck special handling (already L2 norm)
        if 'rho_bottleneck' in observed:
            bn_err = float(observed['rho_bottleneck'])
            individual_errors['rho_bottleneck'] = bn_err
            l2_components.append(bn_err ** 2)
        
        # Calculate L2 error
        l2_error = float(np.sqrt(np.mean(l2_components))) if l2_components else 0.0
        
        return {
            'l2': l2_error,
            'individual': individual_errors,
            'step': len(self.history)
        }
    
    def get_error_trend(self) -> List[float]:
        """Gets error trend (for visualization)
        
        Returns:
            L2 error history list
        """
        return [h['l2'] for h in self.history]
    
    def get_best_step(self) -> Tuple[int, float]:
        """Gets best step and corresponding L2 error
        
        Returns:
            (Step, L2 error)
        """
        if not self.history:
            return 0, float('inf')
        
        l2_errors = [h['l2'] for h in self.history]
        best_idx = int(np.argmin(l2_errors))
        
        return best_idx, l2_errors[best_idx]
    
    def is_diverging(self, window: int = 3) -> bool:
        """Detects whether divergence is occurring (error is consistently increasing)
        
        Args:
            window: Detection window size
            
        Returns:
            True if divergence is detected
        """
        if len(self.history) < window + 1:
            return False
        
        recent_l2s = [h['l2'] for h in self.history[-window-1:]]
        
        # If consistently increasing
        is_increasing = all(recent_l2s[i] < recent_l2s[i+1] 
                           for i in range(len(recent_l2s)-1))
        
        if is_increasing:
            logger.warning(
                f"Possible divergence detected: L2 error increased for {window} consecutive steps"
            )
            return True
        
        return False













