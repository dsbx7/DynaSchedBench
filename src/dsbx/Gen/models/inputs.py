"""Input schema for DynaSchedBench generation configurations."""

from pathlib import Path
from typing import List, Optional, Literal, Dict, Any, Union, Set
from pydantic import BaseModel, Field, model_validator
from loguru import logger
from dsbx.Gen.core.seed import SeedManager

# A type hint for fields that can be expanded in batch mode.
Batchable = Union[float, List[float]]

# ===== Supporting Classes =====

class Machine(BaseModel):
    id: str = Field(..., min_length=1, description="Unique machine identifier.")
    group: str = Field(..., min_length=1, description="Machine-group identifier.")
    speed: float = Field(1.0, gt=0, description="Processing speed multiplier relative to the standard speed of 1.0.")

class ProcessTime(BaseModel):
    dist: Literal["const", "norm", "exp"] = "const"
    mean: float = Field(..., gt=0)
    scv: float = Field(0.0, ge=0)

class ProcessStep(BaseModel):
    machine_group: str = Field(..., min_length=1, description="Machine group required by this operation.")
    process_time: ProcessTime

class ProcessTemplate(BaseModel):
    family: str
    route: List[ProcessStep]

    @model_validator(mode="after")
    def validate_route(self) -> "ProcessTemplate":
        if not self.route:
            raise ValueError("process_templates.route cannot be empty")
        return self

class BottleneckTarget(BaseModel):
    """Defines a target for a bottleneck within a time window.

    Note: `end_time` defaults to the model's horizon at runtime if not provided.
    """
    time: float = Field(..., description="Start time of the bottleneck window.")
    end_time: Optional[float] = Field(
        None, description="End time of the bottleneck window (inclusive)."
    )
    rho: float = Field(..., gt=0, lt=1, description="Target utilization for the bottleneck group during the window.")
    group: str = Field(..., description="The machine group to target for the bottleneck.")

    @model_validator(mode="after")
    def validate_time_window(self) -> "BottleneckTarget":
        if self.end_time is not None and self.end_time < self.time:
            raise ValueError("BottleneckTarget.end_time must be greater than or equal to time")
        if not self.group:
            raise ValueError("BottleneckTarget.group cannot be empty")
        return self

# ===== Layer 1: Static Structure (Plant) =====

class Plant(BaseModel):
    """Static plant structure.

    Defines machines, process routes, and other static resource information.
    """
    machines: List[Machine] = Field(..., min_length=1, description="All machines in the shop.")
    process_templates: List[ProcessTemplate] = Field(..., min_length=1, description="Available job-family process templates.")
    
    job_mix_weights: Optional[List[float]] = Field(
        None,
        description="Job-family mix weights in process_templates order. None means uniform sampling. Values must sum to 1.0."
    )
    
    @model_validator(mode='after')
    def validate_job_mix(self) -> 'Plant':
        """Validate job-family mix weights."""
        if self.job_mix_weights is not None:
            if len(self.job_mix_weights) != len(self.process_templates):
                raise ValueError(
                    f"job_mix_weights length ({len(self.job_mix_weights)}) "
                    f"must equal number of process_templates ({len(self.process_templates)})"
                )
            if abs(sum(self.job_mix_weights) - 1.0) > 0.01:
                raise ValueError(
                    f"job_mix_weights sum must be 1.0, got {sum(self.job_mix_weights):.4f}"
                )
            if any(w < 0 for w in self.job_mix_weights):
                raise ValueError("All job_mix_weights values must be non-negative")
        return self

    @model_validator(mode='after')
    def validate_structure(self) -> 'Plant':
        machine_ids = [machine.id for machine in self.machines]
        duplicates = {m_id for m_id in machine_ids if machine_ids.count(m_id) > 1}
        if duplicates:
            raise ValueError(
                "Machine IDs must be unique; duplicates detected: "
                + ", ".join(sorted(duplicates))
            )

        machine_groups: Set[str] = {machine.group for machine in self.machines}
        if not machine_groups:
            raise ValueError("At least one machine group must be defined")

        unknown_groups: Set[str] = set()
        for template in self.process_templates:
            for step in template.route:
                if step.machine_group not in machine_groups:
                    unknown_groups.add(step.machine_group)
        if unknown_groups:
            raise ValueError(
                "Process routes reference undefined machine groups: "
                + ", ".join(sorted(unknown_groups))
            )

        return self

# ===== Layer 2: Problem Scale =====

class Scale(BaseModel):
    """Problem-scale parameters.

    Some parameters may overlap with other configuration sections, such as
    ``jobs_total`` and ``Targets.rho_global``. Explicit values in ``Scale`` take
    precedence.
    """
    horizon: float = Field(
        1000.0, gt=0,
        description="Simulation horizon in time units."
    )
    
    jobs_total: Optional[int] = Field(
        None, gt=0,
        description="Total number of jobs. When set, this takes precedence over derivation from Targets.rho_global and may conflict with rho, horizon, capacity, or expected processing time."
    )
    
    num_machines: Optional[int] = Field(
        None, gt=0,
        description="Total number of machines. If set, it must match len(Plant.machines); used for validation only."
    )
    
    num_job_families: Optional[int] = Field(
        None, gt=0,
        description="Number of job families. If set, it must match len(Plant.process_templates); used for validation only."
    )


class Dynamics(BaseModel):
    """Configuration for time-varying dynamic behavior.

    This section describes temporal patterns rather than static target values.
    """
    arrival_pattern: Literal["constant", "periodic", "linear_trend"] = Field(
        "constant",
        description="Temporal pattern for the arrival rate."
    )
    
    arrival_amplitude: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Arrival-rate fluctuation amplitude for periodic or trend modes. 0 means no fluctuation; 1 means 100% fluctuation."
    )
    
    arrival_period: Optional[float] = Field(
        None, gt=0,
        description="Arrival-rate period in time units for periodic mode. None defaults to horizon/3."
    )
    
    @model_validator(mode='after')
    def validate_pattern_params(self) -> 'Dynamics':
        """Validate consistency among dynamic-pattern parameters."""
        if self.arrival_pattern == "constant" and self.arrival_amplitude > 0:
            logger.warning(
                "arrival_pattern='constant': arrival_amplitude will be ignored"
            )
        if self.arrival_pattern == "periodic" and self.arrival_period is None:
            logger.info(
                "arrival_pattern='periodic' without arrival_period; "
                "defaulting arrival_period to horizon/3"
            )
        if self.arrival_pattern == "linear_trend" and self.arrival_amplitude <= 0:
            raise ValueError(
                "arrival_pattern='linear_trend' requires arrival_amplitude > 0"
            )
        return self

# ===== Layer 4: Performance Targets =====

class Targets(BaseModel):
    """Target performance characteristics.

    This section defines desired metric values rather than structural settings
    or generation strategies.
    """
    
    rho_global: Batchable = Field(
        0.8,
        description="Global target utilization (0.1-0.99). Lists enable batch generation."
    )
    
    rho_bottleneck: List[BottleneckTarget] = Field(
        [],
        description="Target utilization for bottleneck machine groups in specific time windows."
    )
    
    load_cv: Optional[float] = Field(
        None, ge=0.0, le=2.0,
        description="Target coefficient of variation of load across machine groups. None keeps the natural distribution, 0 enforces balance, and values above 0 request imbalance."
    )
    
    ddt: Batchable = Field(
        1.2,
        description="Due Date Tightness factor (0.1-50.0). Lists enable batch generation."
    )
    
    scv_a: Batchable = Field(
        0.0,
        description="Squared coefficient of variation for arrival times (0.0-10.0). Lists enable batch generation."
    )
    
    scv_p: Batchable = Field(
        0.0,
        description="Squared coefficient of variation for processing times (0.0-10.0). Lists enable batch generation."
    )
    
    disturbance: Batchable = Field(
        0.0,
        description="System disturbance factor, such as downtime share caused by machine breakdowns (0.0-0.95). Lists enable batch generation."
    )

    availability: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="System availability in [0, 1]. Mutually exclusive with disturbance."
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> "Targets":
        def _values(value: Batchable) -> List[float]:
            return list(value) if isinstance(value, list) else [value]

        def _check(
            field_name: str,
            value: Batchable,
            *,
            lower: Optional[float] = None,
            upper: Optional[float] = None,
            lower_inclusive: bool = True,
            upper_inclusive: bool = True,
        ) -> None:
            if value is None:
                return
            for item in _values(value):
                if lower is not None:
                    if lower_inclusive:
                        if item < lower:
                            raise ValueError(
                                f"{field_name} must be >= {lower}, got {item}"
                            )
                    else:
                        if item <= lower:
                            raise ValueError(
                                f"{field_name} must be > {lower}, got {item}"
                            )
                if upper is not None:
                    if upper_inclusive:
                        if item > upper:
                            raise ValueError(
                                f"{field_name} must be <= {upper}, got {item}"
                            )
                    else:
                        if item >= upper:
                            raise ValueError(
                                f"{field_name} must be < {upper}, got {item}"
                            )

        _check("rho_global", self.rho_global, lower=0.1, upper=0.99)
        _check(
            "ddt",
            self.ddt,
            lower=0.1,
            upper=50.0,
            lower_inclusive=False,
            upper_inclusive=False,
        )
        _check("scv_a", self.scv_a, lower=0.0, upper=10.0)
        _check("scv_p", self.scv_p, lower=0.0, upper=10.0)
        _check("disturbance", self.disturbance, lower=0.0, upper=0.95)
        if self.availability is not None:
            if not 0.0 <= self.availability <= 1.0:
                raise ValueError(
                    f"availability must be between 0 and 1, got {self.availability}"
                )

        return self


class Meta(BaseModel):
    """Metadata and run configuration, excluding business parameters."""
    grid: float = Field(1.0, gt=0.0, description="Time grid used for reports and segment definitions.")
    seed: int = Field(42, description="Random seed for reproducibility.")
    version: str = Field("2.0", min_length=1, description="Configuration-file version; v2.0 uses the layered schema.")


class EvaluationConfig(BaseModel):
    """Evaluation-mode configuration."""
    mode: Literal["cold_start", "warm_start"] = Field(
        "cold_start",
        description="Evaluation mode: 'cold_start' or 'warm_start'."
    )
    initial_wip_method: Literal["auto", "manual"] = Field(
        "auto",
        description="Initial WIP method: 'auto' derives from rho, while 'manual' uses n0_initial."
    )
    
    n0_initial: int = Field(
        0, ge=0,
        description="Initial work-in-process count, used only when mode='warm_start' and initial_wip_method='manual'."
    )

    @model_validator(mode='after')
    def validate_mode_dependencies(self) -> 'EvaluationConfig':
        if self.initial_wip_method == "manual" and self.mode != "warm_start":
            raise ValueError("initial_wip_method='manual' is only allowed when mode='warm_start'")

        if self.initial_wip_method == "auto" and self.n0_initial > 0:
            logger.info(
                "initial_wip_method='auto': n0_initial will be ignored; consider setting it to 0"
            )

        return self


class DynamicScenarios(BaseModel):
    """Parameters for generating advanced dynamic events."""
    cancellation_rate: float = Field(0.0, ge=0, le=1, description="Probability that an arrived job will be cancelled later.")
    priority_change_rate: float = Field(0.0, ge=0, le=1, description="Probability that a job will have its priority changed (non-emergency change).")
    emergency_job_ratio: float = Field(0.0, ge=0, le=1, description="Fraction of jobs that will become emergency jobs (high-priority) via dynamic events.")
    emergency_priority: int = Field(-1, description="Priority value assigned to emergency jobs (lower number = higher priority).")
    normal_priority_change_value: int = Field(0, description="Priority value used for non-emergency PriorityChangeEvent (should be >= emergency_priority).")
    rework_probability: float = Field(0.0, ge=0, le=1, description="Probability that a completed operation needs to be reworked.")
    ptime_change_rate: float = Field(0.0, ge=0, le=1, description="Probability that a job's operation time will be dynamically changed.")
    # Support either a single multiplier or a list of multipliers (one will be chosen randomly per event)
    ptime_change_multiplier: Union[float, List[float]] = Field(
        1.0,
        description="Single multiplier or a list of multipliers to sample from (e.g., [0.8, 0.9, 1.2, 1.5]).",
    )
    # Preventive maintenance parameters
    pm_interval: float = Field(0.0, ge=0, description="Preventive maintenance interval in time units (0 = disabled).")
    pm_duration_mean: float = Field(10.0, gt=0, description="Mean duration of preventive maintenance.")
    pm_duration_std: float = Field(2.0, ge=0, description="Standard deviation of preventive maintenance duration.")
    
    # Batch arrival parameters
    batch_arrival_probability: float = Field(0.0, ge=0, le=1, description="Probability that an arrival is a batch (multiple jobs at once).")
    batch_size_mean: float = Field(3.0, ge=2.0, description="Mean batch size when batch arrival occurs (must be >= 2 for meaningful batches).")
    batch_size_std: float = Field(1.0, ge=0, description="Standard deviation of batch size.")
    
    # Route change parameters
    route_change_probability: float = Field(0.0, ge=0, le=1, description="Probability that a job's route will be changed mid-production.")
    
    # Due date change parameters
    due_date_change_probability: float = Field(0.0, ge=0, le=1, description="Probability that a job's due date will be changed.")
    due_date_tightening_ratio: float = Field(0.5, ge=0, le=1, description="Probability that due date change is tightening (vs relaxing).")
    due_date_change_factor: float = Field(0.3, gt=0, le=1, description="Maximum relative change in due date (as fraction of original slack).")

    @model_validator(mode="after")
    def validate_multipliers(self) -> "DynamicScenarios":
        multiplier = self.ptime_change_multiplier
        if isinstance(multiplier, list):
            if not multiplier:
                raise ValueError("ptime_change_multiplier list cannot be empty")
            if any(m <= 0 for m in multiplier):
                raise ValueError("All ptime_change_multiplier values must be positive")

        # Lower number means higher priority; emergency should not be less urgent than normal change
        if self.emergency_priority > self.normal_priority_change_value:
            raise ValueError(
                "DynamicScenarios.emergency_priority should be <= normal_priority_change_value "
                "(lower number = higher priority)."
            )

        return self

# ===== Supporting Classes =====

class CalibrationConfig(BaseModel):
    """Calibration configuration.

    These parameters define calibration strategies and budgets during instance
    generation. They directly affect outputs and should be recorded for
    reproducibility.
    """
    
    mode: Literal["sequential", "moo", "hybrid", "auto"] = Field(
        "sequential",
        description="Calibration mode: sequential, moo, hybrid, or auto."
    )
    max_steps: int = Field(
        25, ge=1, le=1000,
        description="Maximum calibration steps for sequential mode."
    )
    
    moo_population_size: int = Field(
        60, ge=10, le=500,
        description="Population size for the MOO calibrator."
    )
    moo_n_generations: int = Field(
        40, ge=10, le=500,
        description="Maximum number of generations for the MOO calibrator."
    )
    
    hybrid_population_size: int = Field(
        80, ge=10, le=500,
        description="Population size for the hybrid calibrator."
    )
    hybrid_n_generations: int = Field(
        100, ge=10, le=1000,
        description="Maximum number of generations for the hybrid calibrator."
    )
    hybrid_convergence_window: int = Field(
        10, ge=1, le=100,
        description="Convergence window in generations for hybrid termination."
    )
    hybrid_convergence_tol: float = Field(
        0.0005, gt=0, le=0.1,
        description="Relative-improvement tolerance for hybrid termination."
    )
    hybrid_max_sequential_steps: int = Field(
        7, ge=1, le=50,
        description="Maximum number of internal sequential-optimization steps for the hybrid calibrator."
    )
    
    seq_early_stop_no_improve_steps: int = Field(
        3, ge=1, le=20,
        description="Sequential mode: consecutive non-improving steps before early stopping."
    )
    seq_early_stop_relax_factor: float = Field(
        2.0, ge=1.0, le=10.0,
        description="Sequential mode: per-metric tolerance relaxation factor used for early stopping."
    )
    seq_min_relative_improvement: float = Field(
        0.005, ge=0.0, le=0.1,
        description="Sequential mode: minimum relative L2 improvement between steps to count as progress."
    )
    
    seq_tol_rho_global: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Sequential mode: per-metric tolerance for rho_global. None uses min(0.06, base_tol * 0.6)."
    )
    seq_tol_scv_a: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Sequential mode: per-metric tolerance for scv_a. None uses min(0.12, base_tol * 1.2)."
    )
    seq_tol_scv_p: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Sequential mode: per-metric tolerance for scv_p. None uses a dynamically computed value."
    )
    seq_tol_ddt: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Sequential mode: per-metric tolerance for ddt. None uses min(0.10, base_tol * 1.0)."
    )
    seq_tol_disturbance: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Sequential mode: per-metric tolerance for disturbance. None uses min(0.10, base_tol * 1.0)."
    )
    seq_tol_load_cv: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Sequential mode: per-metric tolerance for load_cv. None uses min(0.15, base_tol * 1.5)."
    )

class Tolerance(BaseModel):
    l2: float = Field(0.1, ge=0.0, description="L2 norm tolerance for metric deviation.")
    tv: float = Field(0.1, ge=0.0, description="Total Variation tolerance.")

class Outputs(BaseModel):
    path: str = Field("runs/default", min_length=1, description="Path to store output artifacts.")

    @model_validator(mode='after')
    def validate_path(self) -> 'Outputs':
        if not self.path.strip():
            raise ValueError("outputs.path cannot be an empty string")
        illegal_chars = '<>:"|?*'
        if any(char in self.path for char in illegal_chars):
            raise ValueError(
                "outputs.path cannot contain illegal characters <>:\"|?*"
            )
        return self


class InputModel(BaseModel):
    """Top-level input model for the v2.0 layered schema.

    The schema includes metadata, plant structure, problem scale, dynamic
    behavior, target metrics, dynamic-event settings, evaluation mode,
    calibration strategy, tolerances, and output settings.
    """
    meta: Meta = Meta()  # type: ignore[call-arg]
    plant: Plant
    scale: Scale = Scale()  # type: ignore[call-arg]
    dynamics: Dynamics = Dynamics()
    targets: Targets = Targets()  # type: ignore[call-arg]
    dynamic_scenarios: DynamicScenarios = DynamicScenarios()  # type: ignore[call-arg]
    evaluation: EvaluationConfig = EvaluationConfig()  # type: ignore[call-arg]
    calibration: CalibrationConfig = CalibrationConfig()  # type: ignore[call-arg]
    tolerance: Tolerance = Tolerance()  # type: ignore[call-arg]
    outputs: Outputs = Outputs()  # type: ignore[call-arg]

    @model_validator(mode='after')
    def validate_cross_layer_constraints(self) -> 'InputModel':
        plant = self.plant
        scale = self.scale
        targets = self.targets

        machine_count = len(plant.machines)
        template_count = len(plant.process_templates)

        if scale.num_machines is not None and scale.num_machines != machine_count:
            raise ValueError(
                f"scale.num_machines={scale.num_machines} must equal number of "
                f"plant.machines {machine_count}"
            )

        if scale.num_job_families is not None and scale.num_job_families != template_count:
            raise ValueError(
                f"scale.num_job_families={scale.num_job_families} must equal number of "
                f"plant.process_templates {template_count}"
            )

        if (
            plant.job_mix_weights is not None
            and len(plant.job_mix_weights) != template_count
        ):
            raise ValueError(
                "plant.job_mix_weights length must equal number of process_templates"
            )

        machine_groups: Set[str] = {machine.group for machine in plant.machines}
        if targets.load_cv is not None and targets.load_cv > 0 and len(machine_groups) < 2:
            raise ValueError(
                "When Targets.load_cv>0, Plant.machines must contain at least two "
                "distinct machine groups"
            )

        if targets.rho_bottleneck:
            unknown_groups = sorted({item.group for item in targets.rho_bottleneck} - machine_groups)
            if unknown_groups:
                raise ValueError(
                    "rho_bottleneck references undefined machine groups: "
                    + ", ".join(unknown_groups)
                )

        batch_fields: Dict[str, Any] = {
            "rho_global": targets.rho_global,
            "ddt": targets.ddt,
            "scv_a": targets.scv_a,
            "scv_p": targets.scv_p,
            "disturbance": targets.disturbance,
        }

        list_lengths: Dict[str, int] = {}
        for name, value in batch_fields.items():
            if isinstance(value, list):
                if len(value) == 0:
                    raise ValueError(f"{name} list cannot be empty")
                list_lengths[name] = len(value)

        if len(set(list_lengths.values())) > 1:
            detail = ", ".join(f"{key}={length}" for key, length in list_lengths.items())
            raise ValueError(
                "When Batchable fields are provided as lists, all list lengths must "
                "be equal: " + detail
            )

        if scale.jobs_total is not None and any(length > 1 for length in list_lengths.values()):
            raise ValueError(
                "scale.jobs_total only supports single-scenario Targets; "
                "please reduce batch list lengths"
            )

        disturbance_set = "disturbance" in targets.model_fields_set
        if targets.availability is not None and disturbance_set and targets.disturbance is not None:
            raise ValueError(
                "targets.availability and targets.disturbance cannot both be set"
            )

        if (
            self.dynamics.arrival_pattern == "periodic"
            and self.dynamics.arrival_period is None
        ):
            self.dynamics.arrival_period = self.scale.horizon / 3.0

        if self.dynamics.arrival_pattern == "periodic" and self.dynamics.arrival_period is not None:
            threshold = max(self.scale.horizon * 0.01, 1e-9)
            if self.dynamics.arrival_period < threshold:
                logger.warning(
                    "arrival_period=%.6f is very small relative to horizon and may "
                    "cause high-frequency oscillations",
                    self.dynamics.arrival_period,
                )

        # Removed the line that creates the output directory
        # output_path = Path(self.outputs.path)
        # output_path.mkdir(parents=True, exist_ok=True)

        return self

    @property
    def seed_manager(self) -> SeedManager:
        if not hasattr(self, "_seed_manager"):
            self._seed_manager = SeedManager(self.meta.seed)
        return self._seed_manager
