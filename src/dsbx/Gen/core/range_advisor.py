from typing import Dict, Tuple
from loguru import logger
import numpy as np

from ..models.inputs import InputModel

class RangeAdvisor:
    """
    Analyzes the input model to determine the feasible envelope for key metrics
    based on the plant's physical and operational constraints.
    """

    def __init__(self, model: InputModel):
        self.model = model
        self.report: Dict[str, str] = {}
        
        # --- Pre-calculations ---
        self.avg_work_content: float = self._calculate_avg_work_content()
        # For simplicity, assume all machines are available 100% of the time.
        # A full implementation would consider shifts from the DSL.
        self.total_capacity_rate: float = sum(getattr(m, "speed", 1.0) for m in self.model.plant.machines)
        if self.total_capacity_rate == 0:
            raise ValueError("Plant must have at least one machine.")

    def _calculate_avg_work_content(self) -> float:
        """Calculate the average total processing time across all job families."""
        if not self.model.plant.process_templates:
            return 1.0
        total_work = sum(
            sum(step.process_time.mean for step in template.route)
            for template in self.model.plant.process_templates
        )
        return total_work / len(self.model.plant.process_templates)

    def advise(self) -> Dict[str, str]:
        """
        Runs all advisory checks and returns a report dictionary.
        """
        logger.info("🧐 Range Advisor: Analyzing feasible metric envelopes...")
        
        self._advise_rho_global()
        self._advise_ddt()
        self._advise_scv()

        # Log the full report
        logger.info("--- Range Advisor Report ---")
        for metric, advice in self.report.items():
            logger.info(f"  - {metric}: {advice}")
        logger.info("--------------------------")
        
        return self.report

    def _advise_rho_global(self) -> None:
        """Advises on the feasible range for global utilization."""
        # The theoretical max is 1.0, but practically, anything above 0.98 is unstable.
        rho_max_practical = 0.98
        
        # Based on the user's jobs_total, what is the implied rho?
        if self.model.scale.jobs_total:
            # λ_W = (jobs_total * avg_work_content) / horizon
            # ρ = λ_W / A
            implied_rho = (self.model.scale.jobs_total * self.avg_work_content) / \
                          (self.model.scale.horizon * self.total_capacity_rate)
            
            advice = (
                f"Feasible envelope: [0, {rho_max_practical}]. "
                f"Your `jobs_total`={self.model.scale.jobs_total} implies rho≈{implied_rho:.3f}. "
            )
            if implied_rho > rho_max_practical:
                advice += "WARNING: This is likely infeasible and will be projected down."
            else:
                advice += "This seems feasible."
        else:
            advice = (
                f"Feasible envelope: [0, {rho_max_practical}]. "
                f"Your target rho_global={self.model.targets.rho_global} is within this range."
            )
            rho_val = float(self.model.targets.rho_global if not isinstance(self.model.targets.rho_global, list) else self.model.targets.rho_global[0])
            if rho_val > rho_max_practical:
                 advice += " WARNING: This target is high and may lead to instability."

        self.report['rho_global'] = advice

    def _advise_ddt(self) -> None:
        """Advises on the feasible range for Due Date Tightness."""
        # A DDT < 1 means due dates are set *before* the raw processing time is over,
        # which is extremely tight. A reasonable lower bound could be based on
        # an estimated cycle time from queuing theory (Kingman's approximation).
        
        # Simplified Kingman's approximation for CT
        rho = float(self.model.targets.rho_global if not isinstance(self.model.targets.rho_global, list) else self.model.targets.rho_global[0])
        ca2 = float(self.model.targets.scv_a if not isinstance(self.model.targets.scv_a, list) else self.model.targets.scv_a[0])
        cp2 = float(self.model.targets.scv_p if not isinstance(self.model.targets.scv_p, list) else self.model.targets.scv_p[0])
        
        if rho >= 1.0:
            ct_factor_min = 5.0 # If system is overloaded, CT is theoretically infinite, use a large number
        else:
            # CT ≈ PT * (1 + queue_factor)
            queue_factor = (rho / (1 - rho)) * ((ca2 + cp2) / 2)
            ct_factor_min = 1 + queue_factor

        # The minimum DDT should be larger than the cycle time factor.
        # We'll set the advisory minimum slightly below this for some slack.
        ddt_min_advised = max(1.0, ct_factor_min * 0.8)
        
        advice = (
            f"Advisory envelope: [~{ddt_min_advised:.2f}, ∞). "
            f"A value below this suggests most jobs will be late. "
            f"Your target DDT={self.model.targets.ddt} is {'feasible' if (float(self.model.targets.ddt if not isinstance(self.model.targets.ddt, list) else self.model.targets.ddt[0]) >= ddt_min_advised) else 'very tight'}."
        )
        self.report['ddt'] = advice

    def _advise_scv(self) -> None:
        """Advises on SCV ranges."""
        # SCV must be >= 0. For our generator, we can't easily generate very high SCVs
        # without more complex distributions or batch arrivals.
        scv_a_range = "[0, ~2.0]"
        scv_p_range = "[0, ~2.0]"
        
        self.report['scv_a'] = f"Practically generatable range: {scv_a_range}. Your target is {self.model.targets.scv_a}."
        self.report['scv_p'] = f"Practically generatable range: {scv_p_range}. Your target is {self.model.targets.scv_p}."
