from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
from typing import Any, Dict, Optional, Union
import json
import time

from .config import OType, SType, ModelConfig, SampleConfig, CognitiveConfig, InfoLevel, InteractionMode, algorithm_name
from dsbx.Agents.utils import LLMClient, NullLLMClient, OpenAICompatClient
from .policy import LLMPolicy
from .sampler import choose_by_env_score
from .logger import TrajectoryLogger
from dsbx.Agents.utils import RetryingLLMClient, resolve_llm_endpoint
from dsbx.Env import DynaSchedEnv
from dsbx.Eval.Metrics import evaluate_trajectory
from dsbx.Sim.Loader import load_instance_from_events


def _get_client(cfg: ModelConfig) -> LLMClient:
    import os

    provider = (
        str(
            cfg.provider
            or os.getenv("DYNA_SCHEDBENCH_LLM_PROVIDER")
            or "openai"
        )
    ).lower()
    model = cfg.model_name or os.getenv("DYNA_SCHEDBENCH_LLM_MODEL")

    api_key, base_url = resolve_llm_endpoint(provider, cfg.base_url)
    timeout = float(getattr(cfg, "request_timeout", 30.0) or 30.0)
    max_tokens = int(getattr(cfg, "max_tokens", 512) or 512)

    if not api_key or not model:
        return NullLLMClient()

    base_client = OpenAICompatClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return RetryingLLMClient(base_client)


def solve(
    events_path: Union[str, Path],
    o_type: OType,
    s_type: SType,
    model_cfg: Optional[ModelConfig] = None,
    sample_cfg: Optional[SampleConfig] = None,
    output_path: Optional[Union[str, Path]] = None,
    cognitive_cfg: Optional[CognitiveConfig] = None,
    trajectory_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    model_cfg = model_cfg or ModelConfig()
    sample_cfg = sample_cfg or SampleConfig()
    client = _get_client(model_cfg)

    # Derive cognitive configuration: explicit argument wins; otherwise try SampleConfig.cognitive dict; fallback to default.
    if cognitive_cfg is None:
        raw = getattr(sample_cfg, "cognitive", None)
        if isinstance(raw, dict):
            cfg = CognitiveConfig()
            iv = raw.get("info_level")
            if iv is not None:
                if isinstance(iv, str):
                    # Prefer enum name like "LEVEL_3_STRUCTURAL"; fall back to numeric value.
                    try:
                        cfg.info_level = InfoLevel[iv]
                    except KeyError:
                        try:
                            cfg.info_level = InfoLevel(int(iv))
                        except Exception:
                            pass
                elif isinstance(iv, int):
                    try:
                        cfg.info_level = InfoLevel(iv)
                    except Exception:
                        pass
            md = raw.get("mode")
            if md is not None:
                if isinstance(md, str):
                    try:
                        cfg.mode = InteractionMode[md]
                    except KeyError:
                        try:
                            cfg.mode = InteractionMode(md)
                        except Exception:
                            pass
            if "max_examples" in raw:
                try:
                    cfg.max_examples = int(raw["max_examples"])
                except Exception:
                    pass
            if "max_candidate_actions" in raw:
                try:
                    cfg.max_candidate_actions = int(raw["max_candidate_actions"])
                except Exception:
                    pass
            if "strict_features" in raw:
                try:
                    cfg.strict_features = bool(raw["strict_features"])
                except Exception:
                    pass
            if "use_few_shot" in raw:
                try:
                    cfg.use_few_shot = bool(raw["use_few_shot"])
                except Exception:
                    pass
            if "select_machine" in raw:
                try:
                    cfg.select_machine = bool(raw["select_machine"])
                except Exception:
                    pass
            cognitive_cfg = cfg
        else:
            cognitive_cfg = CognitiveConfig()

    traj_logger = TrajectoryLogger()
    policy = LLMPolicy(o_type, s_type, client, sample_cfg, cognitive_cfg=cognitive_cfg, logger=traj_logger)

    events_path = Path(events_path)
    if events_path.is_dir():
        events_file = events_path / "events.jsonl"
    else:
        events_file = events_path

    if not events_file.exists():
        raise FileNotFoundError(f"Expected 'events.jsonl' at {events_file}, but it does not exist.")

    model, events = load_instance_from_events(events_file)
    env = DynaSchedEnv(model, events=list(events), auto_generate_events=False)

    obs = env.reset()
    steps = 0
    max_steps = env.total_operations() * 4 + 1000
    start_time_wall = time.perf_counter()

    done = env.done()
    while not done and steps < max_steps:
        legal = env.legal_actions()
        if not legal:
            obs = env.advance_if_idle()
            done = env.done()
            continue
        act = policy.decide(obs, legal, env)
        if act is None:
            act = choose_by_env_score(legal, env, rollout_steps=sample_cfg.rollout_steps)
            if act is None:
                obs = env.advance_if_idle()
                done = env.done()
                continue
        obs, _, done, _ = env.step(act)
        steps += 1

    algo = algorithm_name(o_type, s_type)
    traj = env.get_trajectory()
    end_time_wall = time.perf_counter()
    runtime_seconds = float(end_time_wall - start_time_wall)
    metrics = evaluate_trajectory(traj)

    try:
        if isinstance(metrics, dict):
            metrics["runtime_seconds"] = float(runtime_seconds)
    except Exception:
        pass

    try:
        sim = getattr(env, "_sim", None)
        if sim is not None and hasattr(sim, "get_gantt"):
            gantt = sim.get_gantt()  # type: ignore[assignment]
        else:
            gantt = []
    except Exception:
        gantt = []

    result: Dict[str, Any] = {
        "algorithm": algo,
        "gantt": gantt,
        "metrics": metrics,
        "o_type": o_type.value,
        "s_type": s_type.value,
        "policy_stats": policy.stats,
    }

    if trajectory_path is not None:
        try:
            traj_logger.dump_jsonl(trajectory_path)
            result["trajectory_log_path"] = str(trajectory_path)
        except Exception:
            result["trajectory_log_path"] = None

    if output_path is not None:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    return result
