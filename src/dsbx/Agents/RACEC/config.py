from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


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

    use_planner: bool = True
    use_critic: bool = True

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
    adaptive_acceptance: bool = True
    acceptance_thresholds: Optional[List[float]] = None
    force_exploration: bool = True
    force_exploration_each_iteration: bool = False
    force_exploration_max_degradation: float = 0.02

    # --- Evolutionary Operators Integration ---
    # Whether to enable explicit evolutionary operators (crossover and mutation)
    # When True, Planner can propose crossover/mutation strategies
    # When False, only generate strategies are available
    enable_evolutionary_operators: bool = False

    evolution_allow_crossover: bool = True
    evolution_allow_mutation: bool = True
    
    # Rate at which crossover strategies are proposed (0.0-1.0)
    # This is a suggestion to the Planner, not a hard constraint
    evolution_crossover_rate: float = 0.3
    
    # Rate at which mutation strategies are proposed (0.0-1.0)
    # This is a suggestion to the Planner, not a hard constraint
    evolution_mutation_rate: float = 0.3
    
    # Temperature for evolutionary operator LLM calls
    # Higher values increase diversity of offspring
    evolution_temperature: float = 0.7
    
    # Minimum population size required to enable evolutionary operators
    # If repository has fewer rules, fallback to generate-only
    evolution_min_population_size: int = 2

    # --- Evolutionary computation ---
    # Whether to enable LLM-based evolutionary operations (crossover and mutation)
    # When False, system operates in pure generation mode without evolution
    enable_evolution: bool = True
    
    # Probability of applying crossover operation to generate offspring (0.0-1.0)
    # Crossover combines features from two parent rules
    # Recommended: 0.3-0.5 for exploration, 0.1-0.2 for exploitation
    crossover_probability: float = 0.3
    
    # Probability of applying mutation operation to generate offspring (0.0-1.0)
    # Mutation introduces controlled variations to a single parent rule
    # Recommended: 0.2-0.3 for balanced search, 0.4+ for high exploration
    mutation_probability: float = 0.2
    
    # Temperature parameter for LLM calls during evolutionary operations
    # Higher values (0.8-1.0) increase diversity, lower values (0.5-0.7) increase quality
    # Separate from llm_temperature to allow different exploration strategies
    evolution_temperature: float = 0.7
    
    # Maximum number of rules to maintain in the population
    # Larger populations (80-100) enable more exploration but increase memory usage
    # Smaller populations (20-30) converge faster but may miss optimal solutions
    max_population_size: int = 50
    
    # Minimum diversity threshold for population maintenance (0.0-1.0)
    # When diversity falls below this threshold, mutation probability increases
    # Higher values (0.4-0.5) force diversity, lower values (0.2-0.3) allow convergence
    min_diversity_threshold: float = 0.3

    # --- Parent selection ---
    # Method for selecting parent rules for evolutionary operations
    # Options:
    #   - "tournament": Select best from random subset (balanced exploration/exploitation)
    #   - "roulette": Fitness-proportional selection (favors high fitness)
    #   - "rank": Rank-based selection (reduces selection pressure)
    parent_selection_method: str = "tournament"
    
    # Number of individuals in tournament selection (only used if method="tournament")
    # Larger tournaments (5-7) increase selection pressure
    # Smaller tournaments (2-3) maintain diversity
    tournament_size: int = 3

    # --- Offspring generation ---
    # Maximum number of offspring to generate per iteration
    # Actual number depends on crossover_probability and mutation_probability
    # Higher values increase exploration but also increase LLM token usage
    max_offspring_per_iteration: int = 2

    # --- Feedback loop ---
    # Maximum number of feedback entries to retain in history
    # Larger history (15-20) provides more context but increases prompt size
    # Smaller history (5-10) keeps prompts concise
    feedback_history_size: int = 10
    
    # Whether to include feedback history in Planner prompts
    # When True, Planner receives Critic feedback from previous iterations
    # Enables iterative improvement based on past failures/successes
    include_feedback_in_planning: bool = True

    # --- Baseline heuristics ---
    # Whether to include baseline heuristic implementations in Coder prompts
    # When True, Coder receives Python code for classic scheduling rules (SPT, EDD, ATC, etc.)
    # Provides concrete examples and improves code generation quality
    include_baseline_implementations: bool = True
    
    # Maximum number of baseline heuristic examples to include in prompts
    # More examples (4-5) provide richer context but increase prompt size
    # Fewer examples (2-3) keep prompts concise while still providing guidance
    max_baseline_examples: int = 3

    # --- Repository rule replacement ---
    # Whether to enable automatic repository rule replacement
    # When True, new rules can replace weaker rules when repository is at max size
    enable_repository_replacement: bool = True
    
    # Strategy for selecting which rule to replace
    # Options:
    #   - "lowest_fitness": Replace rule with lowest fitness (performance-based)
    #   - "oldest_first": Replace oldest rule (time-based)
    #   - "none": Disable replacement (repository grows without limit)
    repository_replacement_strategy: str = "lowest_fitness"
    
    # Maximum number of rules to maintain in repository
    # When repository reaches this size, replacement logic is triggered
    # Larger repositories (100-200) provide more diversity but increase memory usage
    # Smaller repositories (20-50) are more focused but may lose good rules
    repository_max_size: int = 100
    
    # Minimum fitness improvement required for replacement
    # New rule must be better than target rule by at least this amount
    # Higher values (0.1-0.2) ensure only significant improvements are kept
    # Lower values (0.01-0.05) allow more incremental improvements
    repository_replacement_min_improvement: float = 0.05
    
    # --- Warm-start evaluation ---
    # Whether to enable direct evaluation-based warm-start
    # When True, all repository rules are evaluated on current instance
    # When False, uses random selection (faster but less accurate)
    enable_warmstart_evaluation: bool = True
    
    # Maximum time budget for warm-start evaluation in seconds
    # Limits total time spent evaluating repository rules at startup
    # Higher values (60-120) allow more thorough evaluation
    # Lower values (10-30) provide faster startup
    warmstart_eval_time_budget: float = 60.0
    
    # Maximum number of rules to evaluate during warm-start
    # Limits number of rules evaluated even if time budget allows more
    # None means evaluate all rules (subject to time budget)
    # Lower values (10-20) focus on top historical performers
    warmstart_eval_max_rules: Optional[int] = 20
    
    # Whether to enable evaluation result caching
    # When True, avoids re-evaluating same rule on same instance
    # Significantly speeds up repeated evaluations
    warmstart_eval_cache_enabled: bool = True
    
    # --- Performance tracking ---
    # Alpha parameter for exponential moving average of fitness
    # Controls weight given to new fitness values vs historical average
    # Higher values (0.5-0.8) adapt quickly to recent performance
    # Lower values (0.1-0.3) maintain stable long-term average
    performance_ema_alpha: float = 0.3
    
    # Fitness threshold for counting as successful evaluation
    # Evaluations with fitness > threshold count toward success rate
    # Typically 0.0 (any improvement) or small positive value
    performance_success_threshold: float = 0.0
    
    # --- Baseline heuristics initialization ---
    # Whether to automatically initialize repository with baseline heuristics
    # When True, adds classic scheduling rules (SPT, EDD, FIFO, etc.) to repository
    # These are marked as protected and will not be replaced
    initialize_baseline_heuristics: bool = True
    
    # List of baseline heuristics to include in repository
    # Available options: SPT, EDD, FIFO, LIFO, LPT, MST, ATC, CR, SRPT, LRPT
    # Empty list means include all available heuristics
    baseline_heuristics_list: Optional[List[str]] = None
