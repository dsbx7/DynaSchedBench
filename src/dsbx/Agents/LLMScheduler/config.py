from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class OType(Enum):
    O1 = "O1"


class SType(Enum):
    S1 = "S1"


class InfoLevel(Enum):
    LEVEL_1_MYOPIC = 1
    LEVEL_2_STATISTICAL = 2
    LEVEL_3_STRUCTURAL = 3


class InteractionMode(Enum):
    DIRECT = "direct"
    COT = "cot"
    TOOL_USE = "tool"


class RefinementStrategy(Enum):
    GREEDY = "GREEDY"
    REFLECTION = "REFLECTION"
    BEST_OF_N = "BEST_OF_N"


@dataclass
class CognitiveConfig:
    info_level: InfoLevel = InfoLevel.LEVEL_3_STRUCTURAL
    mode: InteractionMode = InteractionMode.DIRECT
    select_machine: bool = True
    strict_features: bool = True
    prompt_variant: str = ""
    refinement: RefinementStrategy = RefinementStrategy.GREEDY
    reflection_rounds: int = 1
    voting_n: int = 5
    # Refinement-specific temperatures
    # REFLECTION uses a dedicated temperature (default 0.3) to allow
    # small adjustments without affecting the base sampling config.
    reflection_temperature: float = 0.3
    # BEST_OF_N uses a slightly higher default temperature (0.7) to
    # encourage diversity when doing best-of-n voting.
    best_of_n_temperature: float = 0.7
    # Few-Shot Settings
    use_few_shot: bool = True
    max_examples: int = 2
    max_candidate_actions: int = 40


@dataclass
class ModelConfig:
    provider: str = "none"
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 16384
    request_timeout: float = 30.0


@dataclass
class SampleConfig:
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    n: int = 1
    rollout_steps: int = 0
    # Optional cognitive configuration, typically parsed from JSON/YAML.
    # When provided as a dict, runner.solve will convert it into a CognitiveConfig.
    cognitive: Optional[Dict[str, Any]] = None


def algorithm_name(o: OType, s: SType) -> str:
    return f"LLMScheduler-{o.value}-{s.value}"
