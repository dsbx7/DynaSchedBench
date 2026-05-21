# from typing import List, Dict
# import copy
# from loguru import logger
# import numpy as np

# from ..models.inputs import InputModel
# from ..models.events import Event, ArrivalEvent, DueDateEvent

# class SimpleCalibrator:
#     """
#     A heuristic, multi-metric calibrator that adjusts the event stream
#     based on a vector of metric errors.
#     """

#     def __init__(
#         self,
#         model: InputModel,
#         events: List[Event],
#         targets: Dict[str, float],
#         observed: Dict[str, float],
#     ):
#         self.model = model
#         # Use deepcopy to ensure original events are untouched for multi-step calibration
#         self.events = copy.deepcopy(events)
#         self.targets = targets
#         self.observed = observed
#         self.rng = np.random.default_rng(self.model.meta.seed + 100) # Independent RNG for calibration

#     def calibrate(self) -> List[Event]:
#         """
#         Main calibration dispatcher. It calls specific adjustment methods based on errors.
#         The order of adjustments can matter.
#         """
#         logger.warning("🔬 Calibrator: Attempting multi-metric calibration...")
        
#         # Priority 1: Adjust overall load, as it affects everything else.
#         # self._adjust_rho_global()

#         # Priority 1: A djust arrivals (rho and scv_a together). This is the foundation.
#         self._adjust_arrivals()
        
#         # Priority 2: Adjust due dates, which is largely independent.
#         self._adjust_ddt()

#         # Priority 3 & 4: Adjust variability. These are finer-grained.
#         self._adjust_scv_p()

#         logger.info("✅ Calibrator: Event stream adjustment complete.")
#         return self.events

#     def _adjust_rho_global(self):
#         target = self.targets.get("rho_global")
#         observed = self.observed.get("rho_global")
#         if target is None or observed is None or observed == 0: return

#         error_ratio = target / observed
#         if (1 - self.model.tolerance.l2) < error_ratio < (1 + self.model.tolerance.l2):
#             logger.info(f"rho_global error ({error_ratio:.3f}) is within tolerance ({self.model.tolerance.l2}). Skipping adjustment.")
#             return

#         logger.info(f"Adjusting rho_global (target={target:.3f}, observed={observed:.3f})")
#         scaling_factor = 1.0 / error_ratio
        
#         arrival_events = [e for e in self.events if isinstance(e, ArrivalEvent)]
#         if not arrival_events: return

#         # Re-scale inter-arrival times
#         original_times = np.array([e.time for e in arrival_events])
#         new_times = np.zeros_like(original_times)
#         new_times[0] = original_times[0]
#         inter_arrivals = np.diff(original_times)
#         scaled_inter_arrivals = inter_arrivals * scaling_factor
#         new_times[1:] = np.cumsum(scaled_inter_arrivals) + new_times[0]

#         for i, event in enumerate(arrival_events):
#             event.time = new_times[i]

#     def _adjust_ddt(self):
#         target = self.targets.get("ddt")
#         observed = self.observed.get("ddt")
#         if target is None or observed is None or observed == 0: return

#         error_ratio = target / observed
#         if (1 - self.model.tolerance.l2) < error_ratio < (1 + self.model.tolerance.l2):
#             logger.info(f"DDT error ({error_ratio:.3f}) is within tolerance ({self.model.tolerance.l2}). Skipping adjustment.")
#             return

#         logger.info(f"Adjusting DDT (target={target:.3f}, observed={observed:.3f})")
        
#         arrival_events = {e.job_id: e for e in self.events if isinstance(e, ArrivalEvent)}
        
#         for event in self.events:
#             if isinstance(event, DueDateEvent):
#                 arr_event = arrival_events.get(event.job_id)
#                 if not arr_event: continue
                
#                 old_slack = event.due_date - arr_event.time
#                 new_slack = old_slack * error_ratio
#                 event.due_date = arr_event.time + new_slack

#     def _adjust_scv_p(self):
#         target = self.targets.get("scv_p")
#         observed = self.observed.get("scv_p")
#         if target is None or observed is None: return

#         # We need to adjust variance while keeping the mean constant.
#         # Heuristic: Add or subtract zero-mean noise.
#         # If observed SCV is too low, we need to add variance (jitter).
#         if observed < target:
#             logger.info(f"Adjusting scv_p (target={target:.3f}, observed={observed:.3f}) by adding jitter.")
#             # This calculation is a heuristic approximation
#             variance_needed = (target - observed) * (np.mean([pt for e in self.events if isinstance(e, ArrivalEvent) for pt in e.process_times])**2)
#             jitter_std = np.sqrt(variance_needed)
#             if jitter_std == 0: return

#             for event in self.events:
#                 if isinstance(event, ArrivalEvent):
#                     jitter = self.rng.normal(0, jitter_std, len(event.process_times))
#                     event.process_times = [max(0.1, pt + j) for pt, j in zip(event.process_times, jitter)]
#         # Note: Reducing SCV is harder and often requires re-generating numbers from a distribution
#         # with a smaller shape parameter. This simplified version focuses on increasing SCV.

#     def _adjust_arrivals(self):
#         """
#         Adjusts the arrival process by co-calibrating rho_global and scv_a.
#         This method adjusts the mean and variance of inter-arrival times simultaneously.
#         """
#         target_rho = self.targets.get("rho_global")
#         observed_rho = self.observed.get("rho_global")
#         target_scv_a = self.targets.get("scv_a")

#         if target_rho is None or observed_rho is None or target_scv_a is None:
#             return

#         # --- Step 1: Determine the new target mean for inter-arrival times based on rho error ---
#         error_ratio_rho = target_rho / observed_rho if observed_rho > 0 else 1.0

#         arrival_events = [e for e in self.events if isinstance(e, ArrivalEvent)]
#         if not arrival_events: return

#         original_times = np.array([e.time for e in arrival_events])
        
#         # No need to adjust if both rho and scv_a are within tolerance
#         # (A more complex check could be done here, but this is a good heuristic)
#         if (1 - self.model.tolerance.l2) < error_ratio_rho < (1 + self.model.tolerance.l2):
#             logger.info("rho_global error is within tolerance. Skipping arrival adjustment.")
#             return

#         logger.info(f"Adjusting arrival process (target_rho={target_rho:.3f}, obs_rho={observed_rho:.3f})")

#         # Calculate the current mean inter-arrival time
#         current_mean_ia = np.mean(np.diff(original_times)) if len(original_times) > 1 else 1.0
        
#         # The new mean should be scaled by the inverse of the rho error ratio
#         target_mean_ia = current_mean_ia * (1.0 / error_ratio_rho)

#         # --- Step 2: Re-generate all inter-arrival times using a Gamma distribution ---
#         # This allows us to precisely set BOTH the new mean and the target SCV.
        
#         num_inter_arrivals = len(arrival_events) - 1
#         if num_inter_arrivals <= 0: return

#         if target_scv_a == 0: # Handle deterministic case
#             new_inter_arrivals = np.full(num_inter_arrivals, target_mean_ia)
#         else:
#             # Use the Gamma distribution formula: k = 1/SCV, θ = μ/k
#             shape_k = 1 / target_scv_a
#             scale_theta = target_mean_ia / shape_k
            
#             # Generate a new set of random inter-arrival times from the desired distribution
#             new_inter_arrivals = self.rng.gamma(shape_k, scale_theta, size=num_inter_arrivals)

#         # --- Step 3: Reconstruct the arrival timestamps ---
#         new_times = np.zeros_like(original_times)
#         new_times[0] = original_times[0] # Anchor the first arrival
#         new_times[1:] = np.cumsum(new_inter_arrivals) + new_times[0]

#         for i, event in enumerate(arrival_events):
#             event.time = new_times[i]

from __future__ import annotations

from typing import Dict, List, Tuple
import copy
from loguru import logger

from ..models.inputs import InputModel
from ..models.events import Event
from .strategies import (
    AdjustmentStrategy,
    ArrivalRateStrategy,
    DueDateStrategy,
    PTimeVariabilityStrategy,
    BottleneckDisturbanceStrategy,
    LoadBalanceStrategy,
    DisturbanceStrategy,
    LoadCVPerGroupScalingStrategy,
)


class Calibrator:
    """Strategy manager that applies exactly one targeted adjustment per step.
    
    Enhanced with:
    - Strategy impact matrix for synergy analysis
    - Smart strategy selection considering side effects
    """
    
    STRATEGY_IMPACT_MATRIX = {
        ("rho_global", "rho_global"): 0.95,
        ("rho_global", "scv_a"): 0.15,
        ("rho_global", "scv_p"): 0.0,
        ("rho_global", "ddt"): -0.15,
        ("rho_global", "load_cv"): 0.10,
        ("rho_global", "disturbance"): 0.0,
        ("rho_global", "rho_bottleneck"): 0.05,
        
        ("scv_a", "scv_a"): 0.95,
        ("scv_a", "rho_global"): 0.10,
        ("scv_a", "scv_p"): 0.0,
        ("scv_a", "ddt"): 0.0,
        ("scv_a", "load_cv"): 0.0,
        ("scv_a", "disturbance"): 0.0,
        ("scv_a", "rho_bottleneck"): 0.0,
        
        ("ddt", "ddt"): 0.95,
        ("ddt", "rho_global"): 0.0,
        ("ddt", "scv_a"): 0.0,
        ("ddt", "scv_p"): 0.0,
        ("ddt", "load_cv"): 0.0,
        ("ddt", "disturbance"): 0.0,
        ("ddt", "rho_bottleneck"): 0.0,
        
        ("scv_p", "scv_p"): 0.95,
        ("scv_p", "rho_global"): 0.05,
        ("scv_p", "scv_a"): 0.0,
        ("scv_p", "ddt"): -0.10,
        ("scv_p", "load_cv"): 0.0,
        ("scv_p", "disturbance"): 0.0,
        ("scv_p", "rho_bottleneck"): 0.0,
        
        ("load_cv", "load_cv"): 0.90,
        ("load_cv", "rho_global"): -0.10,
        ("load_cv", "scv_a"): 0.0,
        ("load_cv", "scv_p"): 0.0,
        ("load_cv", "ddt"): 0.0,
        ("load_cv", "disturbance"): 0.0,
        ("load_cv", "rho_bottleneck"): 0.0,
        
        ("rho_bottleneck", "rho_bottleneck"): 0.95,
        ("rho_bottleneck", "disturbance"): 0.25,
        ("rho_bottleneck", "rho_global"): -0.05,
        ("rho_bottleneck", "scv_a"): 0.0,
        ("rho_bottleneck", "scv_p"): 0.0,
        ("rho_bottleneck", "ddt"): 0.0,
        ("rho_bottleneck", "load_cv"): 0.0,
        
        ("disturbance", "disturbance"): 0.95,
        ("disturbance", "rho_global"): -0.15,
        ("disturbance", "scv_a"): 0.0,
        ("disturbance", "scv_p"): 0.0,
        ("disturbance", "ddt"): 0.0,
        ("disturbance", "load_cv"): 0.0,
        ("disturbance", "rho_bottleneck"): 0.10,
    }

    def __init__(
        self,
        model: InputModel,
        events: List[Event],
        targets: Dict[str, float],
        observed: Dict[str, float],
        use_synergy: bool = True,
    ) -> None:
        self.model = model
        self.events = copy.deepcopy(events)
        self.targets = targets
        self.observed = observed
        self.use_synergy = use_synergy
        # Instantiate strategies with per-strategy damping factors
        self.strategies: Dict[str, AdjustmentStrategy] = {
            "rho_global": ArrivalRateStrategy(damping=0.75),
            "scv_a": ArrivalRateStrategy(damping=0.50),
            "ddt": DueDateStrategy(damping=0.75),
            "scv_p": PTimeVariabilityStrategy(damping=0.0),
            "rho_bottleneck": BottleneckDisturbanceStrategy(damping=0.5),
            "load_cv": LoadCVPerGroupScalingStrategy(damping=0.25),
            "disturbance": DisturbanceStrategy(damping=0.7),
        }

    def _relative_error(self, metric: str, t: float, o: float) -> float:
        if metric == "rho_bottleneck":
            # L2 error is absolute; target is 0
            return abs(o)
        # For zero targets (e.g., scv_a=0, scv_p=0, disturbance=0), use absolute error
        # to stay consistent with tolerance checks in the CLI.
        if t == 0.0:
            return abs(o - t)
        denom = max(1e-9, abs(t))
        return abs(o - t) / denom

    def calibrate(self) -> List[Event]:
        logger.warning("Calibrator: selecting strategy...")
        
        # Compute error magnitudes per tracked metric
        # Filter out None targets; allow zero targets (e.g., scv_a=0) so they can still be calibrated
        metric_candidates = [
            m for m in ["rho_global", "scv_a", "ddt", "scv_p", "rho_bottleneck", "load_cv", "disturbance"]
            if self.targets.get(m) is not None
        ]
        errors: List[Tuple[float, str]] = []
        for m in metric_candidates:
            t = float(self.targets.get(m, 0.0))
            o = float(self.observed.get(m, 0.0))
            rel_error = self._relative_error(m, t, o)
            
            if m == "load_cv" and rel_error > 0.15:
                weighted_error = rel_error * 1.5
                logger.debug(f"load_cv has high error ({rel_error:.3f}), boosting priority (weighted={weighted_error:.3f})")
                errors.append((weighted_error, m))
            else:
                errors.append((rel_error, m))
        
        if self.use_synergy:
            chosen_strategy_name = self._select_strategy_with_synergy(errors)
        else:
            errors.sort(reverse=True)
            _, chosen_metric = errors[0]
            chosen_strategy_name = chosen_metric
        
        if chosen_strategy_name == "load_cv":
            t = float(self.targets.get("load_cv", 0.0))
            o = float(self.observed.get("load_cv", 0.0))
            denom = max(1e-9, abs(t))
            rel_error = abs(o - t) / denom
            if rel_error > 0.20:
                strategy = LoadBalanceStrategy(damping=0.9)
            else:
                strategy = self.strategies.get("load_cv")
            logger.info(f"Applying strategy 'load_cv' -> {strategy.name} (rel_error={rel_error:.3f})")
            self.events = strategy.adjust(self.events, self.model, self.targets, self.observed)
            return self.events

        strategy = self.strategies.get(chosen_strategy_name)
        if strategy is None:
            logger.info("No applicable strategy found; returning events unchanged.")
            return self.events
        
        logger.info(f"Applying strategy '{chosen_strategy_name}' -> {strategy.name}")
        self.events = strategy.adjust(self.events, self.model, self.targets, self.observed)
        return self.events
    
    def _select_strategy_with_synergy(self, metric_errors: List[Tuple[float, str]]) -> str:
        """Select a strategy while accounting for synergy and side effects.

        Each strategy receives a score based on metric error magnitude and the
        strategy impact matrix. Positive impacts add score, while negative
        impacts penalize strategies when the affected metric has a large error.

        Args:
            metric_errors: List of ``(error_magnitude, metric_name)`` pairs.

        Returns:
            Selected strategy name.
        """
        strategy_scores: Dict[str, float] = {}
        
        for strategy_name in self.strategies.keys():
            score = 0.0
            
            for error_magnitude, metric_name in metric_errors:
                impact_key = (strategy_name, metric_name)
                impact = self.STRATEGY_IMPACT_MATRIX.get(impact_key, 0.0)
                
                if impact > 0:
                    score += error_magnitude * impact
                elif impact < 0:
                    if error_magnitude < 0.05:
                        score += error_magnitude * abs(impact) * 0.3
                    else:
                        score -= error_magnitude * abs(impact) * 2.0
            
            strategy_scores[strategy_name] = score
        
        best_strategy = max(strategy_scores.items(), key=lambda x: x[1])
        
        logger.debug(
            f"Strategy scores: "
            f"{[(k, f'{v:.3f}') for k, v in sorted(strategy_scores.items(), key=lambda x: x[1], reverse=True)]}"
        )
        logger.info(f"Synergy-based strategy selection: '{best_strategy[0]}' (score={best_strategy[1]:.3f})")
        
        return best_strategy[0]
