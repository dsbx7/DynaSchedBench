"""Feasibility projection and conflict resolution for generation inputs."""

from typing import List, Tuple
from ..models.inputs import InputModel
from loguru import logger
import numpy as np
from .load_cv_preprocessor import LoadCVPreprocessor

class FeasibilityProjector:
    """
    Checks input targets for physical and logical feasibility and projects them
    to the nearest feasible boundary if necessary.
    """

    def __init__(self, model: InputModel):
        self.model = model
        self.projections: List[str] = []

    def check_and_project(self) -> Tuple[InputModel, List[str]]:
        """Runs all feasibility checks and returns the (potentially modified) model."""
        # The order of checks can be important.
        self._check_arrival_balance()
        self._check_utilization()
        self._check_variability()
        self._check_due_date_tightness()
        self._check_load_cv_feasibility()
        
        if self.projections:
            logger.warning("Input targets were projected to be feasible. Check report for details.")
        else:
            logger.info("Feasibility Projector: All input targets are physically feasible.")
        
        return self.model, self.projections

    def _avg_work_content_and_machines(self) -> tuple[float, int]:
        """Compute average work content per job and number of machines."""
        templates = self.model.plant.process_templates if self.model.plant and self.model.plant.process_templates else []
        if not templates:
            return 1.0, max(1, len(self.model.plant.machines) if self.model.plant else 1)
        total_work = sum(sum(step.process_time.mean for step in t.route) for t in templates)
        avg_wc = total_work / max(1, len(templates))
        num_m = len(self.model.plant.machines) if self.model.plant and self.model.plant.machines else 1
        return float(avg_wc), int(max(1, num_m))

    def _check_arrival_balance(self) -> None:
        """Balance jobs_total, rho_global, and horizon with minimal changes.

        Policy:
        - If jobs_total is provided: preserve it and project rho_global to the implied value.
        - If jobs_total is missing: derive it from rho_global and horizon.
        - Clip projected rho_global to < 0.98 for feasibility.
        
        Note: in the v2.0 schema, horizon lives in ``Scale`` rather than ``Meta``.
        """
        avg_wc, num_m = self._avg_work_content_and_machines()
        sum_speed = sum(getattr(m, "speed", 1.0) for m in self.model.plant.machines) if self.model.plant and self.model.plant.machines else float(max(1, num_m))
        horizon = float(self.model.scale.horizon)  # v2.0: scale.horizon
        # Resolve scalar rho_global (handles batch inputs too)
        rho_g = float(self.model.targets.rho_global[0]) if isinstance(self.model.targets.rho_global, list) else float(self.model.targets.rho_global)

        if self.model.scale.jobs_total and self.model.scale.jobs_total > 0:
            # Preserve jobs_total and rho_global; adjust horizon to match target rho
            n_total = int(self.model.scale.jobs_total)
            lam = n_total / max(1e-9, horizon)
            implied_rho = lam * avg_wc / max(1e-9, sum_speed)
            # If mismatch > 5%, project horizon to the implied value matching rho_global
            if abs(implied_rho - rho_g) / max(1e-9, rho_g if rho_g != 0 else 1.0) > 0.05:
                # desired lambda from rho_target: lam* = rho_target * M / W
                desired_lambda = (rho_g * sum_speed) / max(1e-9, avg_wc)
                # horizon' = n_total / desired_lambda
                projected_h = n_total / max(1e-9, desired_lambda)
                # keep reasonable positive bound
                projected_h = float(max(1e-6, projected_h))
                self.projections.append(
                    f"E_RATE_MATCH: jobs_total={n_total} with rho_global={rho_g:.3f} suggests horizon≈{projected_h:.3f} (was {horizon:.3f}). Projected horizon to match targets."
                )
                self.model.scale.horizon = projected_h  # v2.0: scale.horizon
        else:
            # Derive jobs_total from rho_global and horizon
            lam_rho = (rho_g * sum_speed) / max(1e-9, avg_wc)
            n_proj = int(max(1, round(lam_rho * horizon)))
            self.model.scale.jobs_total = n_proj
            self.projections.append(
                f"E_FILL_JOBS: jobs_total not provided. Derived jobs_total={n_proj} from rho_global={rho_g:.3f}, horizon={horizon:.3f}."
            )

    def _check_utilization(self) -> None:
        """Ensures all utilization targets are not >= 1.0."""
        # Check global utilization
        # We need to handle both single float and list cases for batch mode
        if isinstance(self.model.targets.rho_global, list):
            # In batch mode, check and project each value in the list
            self.model.targets.rho_global = [self._project_single_rho(v) for v in self.model.targets.rho_global]
        else:
            self.model.targets.rho_global = self._project_single_rho(self.model.targets.rho_global)

        # Check bottleneck utilization
        for bn_target in self.model.targets.rho_bottleneck:
            bn_target.rho = self._project_single_rho(bn_target.rho, is_bottleneck=True, bn_target=bn_target)
    
    def _project_single_rho(self, rho: float, is_bottleneck: bool = False, bn_target: object | None = None) -> float:
        """Helper function to project a single utilization value."""
        if rho >= 1.0:
            new_rho = 0.98
            if is_bottleneck and bn_target is not None and hasattr(bn_target, "group"):
                context = f"bottleneck rho for group '{getattr(bn_target, 'group')}'"
            else:
                context = "global rho"
            self.projections.append(
                f"E_CONS_CAPACITY: Target {context}={rho} is infeasible. Projected to {new_rho}."
            )
            return new_rho
        return rho

    # --- 👇 New Check Method 1 ---
    def _check_variability(self) -> None:
        """Ensures all SCV (Squared Coefficient of Variation) targets are non-negative."""
        # Check scv_a
        if isinstance(self.model.targets.scv_a, list):
            self.model.targets.scv_a = [self._project_single_scv(v, 'scv_a') for v in self.model.targets.scv_a]
        else:
            self.model.targets.scv_a = self._project_single_scv(self.model.targets.scv_a, 'scv_a')

        # Check scv_p
        if isinstance(self.model.targets.scv_p, list):
            self.model.targets.scv_p = [self._project_single_scv(v, 'scv_p') for v in self.model.targets.scv_p]
        else:
            self.model.targets.scv_p = self._project_single_scv(self.model.targets.scv_p, 'scv_p')

    def _project_single_scv(self, scv: float, name: str) -> float:
        """Helper to project a single SCV value."""
        if scv < 0:
            new_scv = 0.0
            self.projections.append(
                f"E_MATH_DOMAIN: Target {name}={scv} is mathematically impossible (variance cannot be negative). Projected to {new_scv}."
            )
            return new_scv
        return scv

    # --- 👇 New Check Method 2 ---
    def _check_due_date_tightness(self) -> None:
        """Ensures DDT is positive to avoid logical errors."""
        min_ddt = 0.1 # A practical lower bound to prevent negative due dates in extreme cases
        if isinstance(self.model.targets.ddt, list):
            self.model.targets.ddt = [self._project_single_ddt(v, min_ddt) for v in self.model.targets.ddt]
        else:
            self.model.targets.ddt = self._project_single_ddt(self.model.targets.ddt, min_ddt)
            
    def _project_single_ddt(self, ddt: float, min_val: float) -> float:
        """Helper to project a single DDT value."""
        if ddt < min_val:
            new_ddt = min_val
            self.projections.append(
                f"E_CONS_SLACK: Target ddt={ddt} is too low and may cause logical errors. Projected to {new_ddt}."
            )
            return new_ddt
        return ddt

    def _check_load_cv_feasibility(self) -> None:
        """Ensure load_cv targets lie within a physically feasible range.

        The check uses ``LoadCVPreprocessor`` diagnostics to estimate an
        achievable interval and clips the target there, avoiding repeated
        out-of-range warnings during preprocessing.
        """
        raw = getattr(self.model.targets, "load_cv", None)
        if raw is None:
            return

        if isinstance(raw, list):
            if not raw:
                return
            target_val = float(raw[0])
        else:
            target_val = float(raw)

        try:
            pre = LoadCVPreprocessor(self.model)
            diag = pre.diagnose_target_feasibility(target_val)
        except Exception as e:
            logger.debug(f"LoadCV feasibility diagnosis failed: {e}")
            return

        if diag.get("status") == "unavailable":
            return

        feasible_min = float(diag.get("feasible_min", 0.0))
        feasible_max = float(diag.get("feasible_max", 0.0))
        clipped = float(diag.get("clipped_target", target_val))

        if clipped < feasible_min or clipped > feasible_max:
            return

        if abs(clipped - target_val) > 1e-6:
            self.projections.append(
                f"E_LOAD_CV_RANGE: Target load_cv={target_val:.3f} outside feasible [{feasible_min:.3f}, {feasible_max:.3f}]. Projected to {clipped:.3f}."
            )
            if isinstance(raw, list):
                self.model.targets.load_cv = [clipped] * len(raw)
            else:
                self.model.targets.load_cv = clipped



from typing import Optional, Dict


class ConflictResolver:
    """Detect parameter conflicts and optionally resolve them interactively.

    The resolver checks jobs-total/utilization consistency, job-mix length, DDT
    feasibility, load-CV reachability, declared machine and family counts, and
    arrival-amplitude stability constraints.
    """
    
    def __init__(self, model: InputModel):
        self.model = model
        self.conflicts: List[Dict] = []
    
    def detect_conflicts(self) -> List[Dict]:
        """Detect all parameter conflicts."""
        conflicts = []
        
        conflict = self._check_jobs_total_conflict()
        if conflict:
            conflicts.append(conflict)
        
        conflict = self._check_job_mix_conflict()
        if conflict:
            conflicts.append(conflict)
        
        conflict = self._check_ddt_feasibility()
        if conflict:
            conflicts.append(conflict)
        
        conflict = self._check_num_machines_consistency()
        if conflict:
            conflicts.append(conflict)
        
        conflict = self._check_num_families_consistency()
        if conflict:
            conflicts.append(conflict)
        
        conflict = self._check_amplitude_feasibility()
        if conflict:
            conflicts.append(conflict)
        
        self.conflicts = conflicts
        return conflicts
    
    def _calculate_avg_work(self) -> tuple[float, int]:
        """Compute average work content and machine count."""
        templates = self.model.plant.process_templates
        if not templates:
            return 1.0, max(1, len(self.model.plant.machines))
        
        if self.model.plant.job_mix_weights:
            weights = self.model.plant.job_mix_weights
            weighted_work = sum(
                weights[i] * sum(step.process_time.mean for step in t.route)
                for i, t in enumerate(templates)
            )
            avg_wc = weighted_work
        else:
            total_work = sum(sum(step.process_time.mean for step in t.route) for t in templates)
            avg_wc = total_work / len(templates)
        
        num_m = len(self.model.plant.machines)
        return float(avg_wc), int(max(1, num_m))
    
    def _check_jobs_total_conflict(self) -> Optional[Dict]:
        """Check consistency between jobs_total and rho_global."""
        if not self.model.scale.jobs_total:
            return None
        
        avg_wc, num_m = self._calculate_avg_work()
        sum_speed = sum(getattr(m, "speed", 1.0) for m in self.model.plant.machines)
        horizon = self.model.scale.horizon  # v2.0: scale.horizon
        jobs_total = self.model.scale.jobs_total
        rho_target = float(self.model.targets.rho_global if not isinstance(self.model.targets.rho_global, list) else self.model.targets.rho_global[0])
        
        lambda_implied = jobs_total / horizon
        rho_implied = lambda_implied * avg_wc / max(1e-9, sum_speed)
        
        if abs(rho_implied - rho_target) / rho_target > 0.05:
            jobs_from_rho = int((rho_target * sum_speed * horizon) / max(1e-9, avg_wc))
            horizon_from_both = (jobs_total * avg_wc) / max(1e-9, (rho_target * sum_speed))
            
            return {
                'type': 'jobs_total_rho_mismatch',
                'severity': 'warning',
                'description': f'jobs_total={jobs_total} is inconsistent with rho_global={rho_target:.3f} (deviation {abs(rho_implied - rho_target) / rho_target * 100:.1f}%)',
                'details': {
                    'jobs_total': jobs_total,
                    'horizon': horizon,
                    'rho_target': rho_target,
                    'rho_implied': rho_implied,
                    'deviation_pct': abs(rho_implied - rho_target) / rho_target * 100,
                    'avg_work_content': avg_wc,
                    'num_machines': num_m
                },
                'suggestions': [
                    {
                        'option': 1,
                        'description': f'Adjust jobs_total to match rho_global={rho_target:.3f}',
                        'action': 'adjust_jobs_total',
                        'new_value': jobs_from_rho,
                        'feasible': True
                    },
                    {
                        'option': 2,
                        'description': f'Adjust horizon to match jobs_total={jobs_total} and rho_global={rho_target:.3f}',
                        'action': 'adjust_horizon',
                        'new_value': horizon_from_both,
                        'feasible': horizon_from_both > 0 and horizon_from_both < 1e6
                    },
                    {
                        'option': 3,
                        'description': f'Accept current values (actual rho≈{rho_implied:.3f}, deviation {abs(rho_implied - rho_target) / rho_target * 100:.1f}%)',
                        'action': 'accept_as_is',
                        'new_value': None,
                        'feasible': True
                    }
                ]
            }
        return None
    
    def _check_job_mix_conflict(self) -> Optional[Dict]:
        """Check consistency between job_mix_weights and process_templates."""
        if self.model.plant.job_mix_weights is None:
            return None
        
        weights = self.model.plant.job_mix_weights
        templates = self.model.plant.process_templates
        
        if len(weights) != len(templates):
            return {
                'type': 'job_mix_length_mismatch',
                'severity': 'error',
                'description': f'job_mix_weights length ({len(weights)}) does not match process_templates count ({len(templates)})',
                'details': {
                    'weights_length': len(weights),
                    'templates_length': len(templates),
                    'weights': weights,
                    'template_families': [t.family for t in templates]
                },
                'suggestions': [
                    {
                        'option': 1,
                        'description': 'Remove job_mix_weights and use a uniform distribution',
                        'action': 'remove_job_mix',
                        'new_value': None,
                        'feasible': True
                    },
                    {
                        'option': 2,
                        'description': f'Adjust job_mix_weights length to {len(templates)} with uniform fill/truncation',
                        'action': 'adjust_job_mix_length',
                        'new_value': [1.0 / len(templates)] * len(templates),
                        'feasible': True
                    }
                ]
            }
        return None
    
    def _check_ddt_feasibility(self) -> Optional[Dict]:
        """Check whether DDT is feasible under rho, scv_a, and scv_p."""
        rho = float(self.model.targets.rho_global if not isinstance(self.model.targets.rho_global, list) else self.model.targets.rho_global[0])
        scv_a = float(self.model.targets.scv_a if not isinstance(self.model.targets.scv_a, list) else self.model.targets.scv_a[0])
        scv_p = float(self.model.targets.scv_p if not isinstance(self.model.targets.scv_p, list) else self.model.targets.scv_p[0])
        ddt = float(self.model.targets.ddt if not isinstance(self.model.targets.ddt, list) else self.model.targets.ddt[0])
        
        if rho >= 1.0:
            ddt_min = 10.0
        else:
            queue_factor = (rho / (1 - rho)) * ((scv_a + scv_p) / 2)
            ct_factor = 1 + queue_factor
            ddt_min = max(1.0, ct_factor * 0.8)
        
        if ddt < ddt_min:
            ddt_suggested = max(ddt_min, 1.2)
            
            return {
                'type': 'ddt_too_tight',
                'severity': 'warning',
                'description': f'DDT={ddt:.2f} may be too tight; current parameters suggest a minimum around {ddt_min:.2f}',
                'details': {
                    'ddt_current': ddt,
                    'ddt_min_advised': ddt_min,
                    'rho_global': rho,
                    'scv_a': scv_a,
                    'scv_p': scv_p,
                    'queue_factor': queue_factor,
                    'ct_factor': ct_factor,
                    'tardiness_risk': 'most jobs may become tardy'
                },
                'suggestions': [
                    {
                        'option': 1,
                        'description': f'Adjust DDT to suggested value {ddt_suggested:.2f}',
                        'action': 'adjust_ddt',
                        'new_value': ddt_suggested,
                        'feasible': True
                    },
                    {
                        'option': 2,
                        'description': f'Reduce rho_global to lower system load',
                        'action': 'reduce_rho',
                        'new_value': max(0.5, rho * 0.9),
                        'feasible': True
                    },
                    {
                        'option': 3,
                        'description': f'Reduce scv_a and scv_p to lower variability',
                        'action': 'reduce_scv',
                        'new_value': {'scv_a': max(0, scv_a * 0.7), 'scv_p': max(0, scv_p * 0.7)},
                        'feasible': True
                    },
                    {
                        'option': 4,
                        'description': f'Accept current values and allow a high tardiness rate',
                        'action': 'accept_tight_ddt',
                        'new_value': None,
                        'feasible': True
                    }
                ]
            }
        return None
    
    def _check_num_machines_consistency(self) -> Optional[Dict]:
        """Check consistency between num_machines and actual machines."""
        if self.model.scale.num_machines is None:
            return None
        
        actual_num = len(self.model.plant.machines)
        if self.model.scale.num_machines != actual_num:
            return {
                'type': 'num_machines_mismatch',
                'severity': 'error',
                'description': f'Scale.num_machines ({self.model.scale.num_machines}) does not match len(Plant.machines) ({actual_num})',
                'details': {
                    'scale_num_machines': self.model.scale.num_machines,
                    'actual_num_machines': actual_num
                },
                'suggestions': [
                    {
                        'option': 1,
                        'description': f'Remove Scale.num_machines and use actual value {actual_num}',
                        'action': 'remove_num_machines',
                        'new_value': None,
                        'feasible': True
                    },
                    {
                        'option': 2,
                        'description': f'Set Scale.num_machines to {actual_num}',
                        'action': 'correct_num_machines',
                        'new_value': actual_num,
                        'feasible': True
                    }
                ]
            }
        return None
    
    def _check_num_families_consistency(self) -> Optional[Dict]:
        """Check consistency between num_job_families and actual job families."""
        if self.model.scale.num_job_families is None:
            return None
        
        actual_num = len(self.model.plant.process_templates)
        if self.model.scale.num_job_families != actual_num:
            return {
                'type': 'num_families_mismatch',
                'severity': 'error',
                'description': f'Scale.num_job_families ({self.model.scale.num_job_families}) does not match len(Plant.process_templates) ({actual_num})',
                'details': {
                    'scale_num_families': self.model.scale.num_job_families,
                    'actual_num_families': actual_num
                },
                'suggestions': [
                    {
                        'option': 1,
                        'description': f'Remove Scale.num_job_families and use actual value {actual_num}',
                        'action': 'remove_num_families',
                        'new_value': None,
                        'feasible': True
                    },
                    {
                        'option': 2,
                        'description': f'Set Scale.num_job_families to {actual_num}',
                        'action': 'correct_num_families',
                        'new_value': actual_num,
                        'feasible': True
                    }
                ]
            }
        return None
    
    def _check_amplitude_feasibility(self) -> Optional[Dict]:
        """Check whether arrival_amplitude violates steady-state constraints."""
        if self.model.dynamics.arrival_pattern == "constant":
            return None
        
        amplitude = self.model.dynamics.arrival_amplitude
        if amplitude == 0:
            return None
        
        rho = float(self.model.targets.rho_global if not isinstance(self.model.targets.rho_global, list) else self.model.targets.rho_global[0])
        
        rho_max = rho * (1 + amplitude)
        
        if rho_max >= 1.0:
            amplitude_max = (0.98 - rho) / rho
            
            return {
                'type': 'amplitude_instability',
                'severity': 'error',
                'description': f'arrival_amplitude={amplitude:.2f} causes peak utilization {rho_max:.3f} >= 1.0, making the system unstable',
                'details': {
                    'amplitude_current': amplitude,
                    'rho_global': rho,
                    'rho_peak': rho_max,
                    'amplitude_max_feasible': amplitude_max
                },
                'suggestions': [
                    {
                        'option': 1,
                        'description': f'Adjust arrival_amplitude to maximum feasible value {amplitude_max:.3f}',
                        'action': 'adjust_amplitude',
                        'new_value': amplitude_max,
                        'feasible': True
                    },
                    {
                        'option': 2,
                        'description': f'Reduce rho_global to allow larger fluctuations',
                        'action': 'reduce_rho_for_amplitude',
                        'new_value': 0.98 / (1 + amplitude),
                        'feasible': True
                    },
                    {
                        'option': 3,
                        'description': 'Use constant mode with no fluctuation',
                        'action': 'use_constant_pattern',
                        'new_value': 'constant',
                        'feasible': True
                    }
                ]
            }
        return None
    
    def resolve_interactively(self, non_interactive: bool = False) -> InputModel:
        """Resolve detected conflicts interactively or automatically.

        Args:
            non_interactive: If True, automatically choose the first feasible
                suggestion; otherwise prompt the user.

        Returns:
            Corrected model.
        """
        if not self.conflicts:
            return self.model
        
        logger.warning(f"Detected {len(self.conflicts)} parameter conflicts")
        
        for i, conflict in enumerate(self.conflicts, 1):
            logger.warning(f"\n{'='*70}")
            logger.warning(f"Conflict {i}/{len(self.conflicts)}: {conflict['description']}")
            logger.warning(f"Severity: {conflict['severity']}")
            logger.warning(f"{'='*70}")
            
            if 'details' in conflict:
                logger.info("\nDetails:")
                for key, val in conflict['details'].items():
                    logger.info(f"  {key}: {val}")
            
            logger.info("\nAvailable resolutions:")
            for sug in conflict['suggestions']:
                feasible_mark = "OK" if sug.get('feasible', True) else "X"
                logger.info(f"  {feasible_mark} option {sug['option']}: {sug['description']}")
                if sug['new_value'] is not None:
                    logger.info(f"      new value: {sug['new_value']}")
            
            if non_interactive:
                choice = None
                for sug in conflict['suggestions']:
                    if sug.get('feasible', True):
                        choice = sug
                        break
                
                if choice is None:
                    choice = conflict['suggestions'][0]
                
                logger.warning(f"Non-interactive mode: automatically selected option {choice['option']}")
            else:
                choice = None
                while True:
                    try:
                        user_input = input(
                            f"\nSelect resolution (1-{len(conflict['suggestions'])}), or enter 's' to skip: "
                        ).strip()
                        if user_input.lower() == 's':
                            logger.info("User chose to skip this conflict")
                            break
                        choice_idx = int(user_input) - 1
                        if 0 <= choice_idx < len(conflict['suggestions']):
                            choice = conflict['suggestions'][choice_idx]
                            if not choice.get('feasible', True):
                                print(
                                    f"Warning: option {choice_idx + 1} may be infeasible. "
                                    "Confirm? (y/n)"
                                )
                                confirm = input().strip().lower()
                                if confirm != 'y':
                                    continue
                            break
                        else:
                            print(f"Invalid choice, please enter 1-{len(conflict['suggestions'])}")
                    except (ValueError, KeyboardInterrupt):
                        print("Invalid input, please enter a number or 's'")
                        continue
                
                if choice is None:
                    continue
            
            if choice:
                self._apply_resolution(conflict['type'], choice)
        
        logger.info("\n" + "="*70)
        logger.info("Conflict resolution complete")
        logger.info("="*70 + "\n")
        return self.model
    
    def _apply_resolution(self, conflict_type: str, choice: Dict):
        """Apply the selected resolution."""
        action = choice['action']
        new_value = choice['new_value']
        
        if action == 'adjust_jobs_total':
            self.model.scale.jobs_total = new_value
            logger.info(f"jobs_total updated to {new_value}")
        
        elif action == 'adjust_horizon':
            self.model.scale.horizon = new_value
            logger.info(f"horizon updated to {new_value:.2f}")
        
        elif action == 'accept_as_is':
            logger.info("Keeping current values unchanged")
        
        elif action == 'adjust_ddt':
            if isinstance(self.model.targets.ddt, list):
                self.model.targets.ddt = [new_value] * len(self.model.targets.ddt)
            else:
                self.model.targets.ddt = new_value
            logger.info(f"DDT updated to {new_value:.2f}")
        
        elif action == 'reduce_rho':
            if isinstance(self.model.targets.rho_global, list):
                self.model.targets.rho_global = [new_value] * len(self.model.targets.rho_global)
            else:
                self.model.targets.rho_global = new_value
            logger.info(f"rho_global updated to {new_value:.3f}")
        
        elif action == 'reduce_scv':
            scv_values = new_value
            if isinstance(self.model.targets.scv_a, list):
                self.model.targets.scv_a = [scv_values['scv_a']] * len(self.model.targets.scv_a)
            else:
                self.model.targets.scv_a = scv_values['scv_a']
            
            if isinstance(self.model.targets.scv_p, list):
                self.model.targets.scv_p = [scv_values['scv_p']] * len(self.model.targets.scv_p)
            else:
                self.model.targets.scv_p = scv_values['scv_p']
            logger.info(
                f"scv_a updated to {scv_values['scv_a']:.2f}, "
                f"scv_p updated to {scv_values['scv_p']:.2f}"
            )
        
        elif action == 'accept_tight_ddt':
            logger.info(
                "Accepted tight DDT setting (this may lead to a high tardiness rate)"
            )
        
        elif action == 'remove_job_mix':
            self.model.plant.job_mix_weights = None
            logger.info("job_mix_weights removed; uniform distribution will be used")
        
        elif action == 'adjust_job_mix_length':
            self.model.plant.job_mix_weights = new_value
            logger.info(f"job_mix_weights adjusted to uniform distribution: {new_value}")
        
        elif action == 'remove_num_machines':
            self.model.scale.num_machines = None
            logger.info("Scale.num_machines removed")
        
        elif action == 'correct_num_machines':
            self.model.scale.num_machines = new_value
            logger.info(f"Scale.num_machines updated to {new_value}")
        
        elif action == 'remove_num_families':
            self.model.scale.num_job_families = None
            logger.info("Scale.num_job_families removed")
        
        elif action == 'correct_num_families':
            self.model.scale.num_job_families = new_value
            logger.info(f"Scale.num_job_families updated to {new_value}")
        
        elif action == 'adjust_amplitude':
            self.model.dynamics.arrival_amplitude = new_value
            logger.info(f"arrival_amplitude updated to {new_value:.3f}")
        
        elif action == 'reduce_rho_for_amplitude':
            if isinstance(self.model.targets.rho_global, list):
                self.model.targets.rho_global = [new_value] * len(self.model.targets.rho_global)
            else:
                self.model.targets.rho_global = new_value
            logger.info(
                f"rho_global reduced to {new_value:.3f} to accommodate arrival amplitude"
            )
        
        elif action == 'use_constant_pattern':
            self.model.dynamics.arrival_pattern = 'constant'
            self.model.dynamics.arrival_amplitude = 0.0
            logger.info("arrival_pattern set to 'constant' (no fluctuation)")
        
        else:
            logger.warning(f"Unknown resolution action: {action}")
