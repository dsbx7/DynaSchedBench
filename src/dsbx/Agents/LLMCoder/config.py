from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMCoderConfig:
    """Configuration for the asynchronous LLM coder.
    
    These parameters control rule-update cadence and triggers, sandbox
    evaluation budget and target metric, and LLM sampling and timeout settings.
    """

    max_steps_between_updates: int = 500
    force_sync_codegen_interval: int = 0
    force_sync_codegen_timeout: float = 600.0
    force_sync_codegen_min_step: int = 0

    min_relative_improvement: float = 0.0

    eval_max_steps: int = 500
    eval_episodes: int = 1

    objective_metric: str = "makespan"
    objective_mode: str = "min"
    objective_metrics: Optional[str] = None

    llm_temperature: float = 0.0
    llm_top_p: float = 1.0
    llm_top_k: int = 0
    llm_timeout: float = 9999.0

    enable_codegen: bool = True
    enable_eval: bool = True

    log_candidate_actions: bool = False
    log_candidate_actions_max: int = 50

    n_candidates: int = 3
    max_code_chars: int = 16000
    eval_min_episodes: int = 3
    eval_max_episodes: int = 20
    eval_pool_size: int = 32
    eval_pool_refresh_per_eval: int = 4
    eval_max_parallel_candidates: int = 0
    eval_significance_level: float = 0.05
    eval_min_effect_size: float = 0.0
    eval_fail_fast: bool = False
    eval_use_subprocess_sandbox: bool = False
    eval_subprocess_timeout: float = 120.0
    state_profile_window_size: int = 200
    complexity_weight: float = 0.1
    perf_trigger_window: int = 100
    perf_trigger_min_relative_change: float = 0.2
    use_performance_trigger: bool = True
    debug_always_accept: bool = False

    use_meta_advisor: bool = True
    use_repository: bool = True
    repository_path: Optional[str] = None

    agentic_max_iterations: int = 2
    agentic_max_plans: int = 2
    agentic_min_relative_improvement: float = 0.02
    planner_temperature: float = 0.3
    critic_temperature: float = 0.0
