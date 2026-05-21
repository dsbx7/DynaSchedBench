from typing import Dict, Any, List, Optional

import os
from loguru import logger

from .config import OType, SType, SampleConfig, CognitiveConfig, InteractionMode, InfoLevel, RefinementStrategy
from dsbx.Agents.utils import LLMClient
from .sampler import Sampler, choose_by_heuristic
from . import prompts
from .logger import TrajectoryLogger
from .feature_extractor import ObservationEncoder
from .tools import ToolRuntimeContext, execute_tool_call


class LLMPolicy:
    def __init__(
        self,
        o_type: OType,
        s_type: SType,
        llm_client: LLMClient,
        sample_cfg: SampleConfig,
        cognitive_cfg: Optional[CognitiveConfig] = None,
        logger: Optional[TrajectoryLogger] = None,
    ):
        self.o_type = o_type
        self.s_type = s_type
        self.client = llm_client
        self.sample_cfg = sample_cfg
        self.cog_cfg = cognitive_cfg or CognitiveConfig()
        self.sampler = Sampler()
        self.stats: Dict[str, Any] = {
            "fallback_count": 0,
            "invalid_outputs": 0,
            "ties_broken": 0,
            "env_selected_when_tie": 0,
            "llm_total_input_tokens": 0.0,
            "llm_total_output_tokens": 0.0,
        }
        self.history: List[Dict[str, Any]] = []
        self.traj_logger: TrajectoryLogger = logger or TrajectoryLogger()

    def decide(self, obs: Dict[str, Any], legal_actions: List[Dict[str, Any]], env) -> Optional[Dict[str, Any]]:
        if not legal_actions:
            return None
        try:
            setattr(env, "_last_obs", obs)
        except Exception:
            pass

        prompt: str
        outs: List[str]

        mode = getattr(self.cog_cfg, "mode", InteractionMode.DIRECT)

        step_idx = len(self.history) + 1
        info_level = getattr(self.cog_cfg, "info_level", None)
        info_name = info_level.name if isinstance(info_level, InfoLevel) else None
        mode_name = mode.name if isinstance(mode, InteractionMode) else str(mode)
        try:
            from_time = obs.get("time") if isinstance(obs, dict) else None
        except Exception:
            from_time = None
        logger.debug(
            "LLMPolicy.decide: step={} o_type={} s_type={} info_level={} mode={} n_legal_actions={} time={}",
            step_idx,
            self.o_type.value,
            self.s_type.value,
            info_name,
            mode_name,
            len(legal_actions),
            from_time,
        )
        logger.debug(
            "LLMPolicy.decide: step={} legal_actions={}",
            step_idx,
            legal_actions,
        )

        # Fast-path: when there is only a single legal action, skip any LLM
        # invocation and directly execute it while still recording a
        # structured decision log for interpretation.
        if len(legal_actions) == 1:
            act = legal_actions[0]
            self._log_decision(
                obs=obs,
                prompt="<single_action_no_llm>",
                outs=[],
                action=act,
                env=env,
                parsed_action_id=None,
                fallback_triggered=False,
                fallback_type="single_action",
            )
            return act

        prompt, pruned_actions = prompts.build_cognitive_prompt_o1(obs, legal_actions, env, self.cog_cfg)

        base_action: Optional[Dict[str, Any]] = None
        base_meta: Dict[str, Any] = {
            "parsed_action_id": None,
            "fallback_triggered": False,
            "fallback_type": None,
        }
        log_prompt = prompt
        log_outs: List[str] = []

        if mode is InteractionMode.TOOL_USE:
            act, meta, final_prompt, all_outs = self._decide_o1_tool_use(
                prompt,
                pruned_actions,
                legal_actions,
                env,
            )
            base_action = act
            base_meta = meta
            log_prompt = final_prompt
            log_outs = all_outs
        else:
            refinement = getattr(self.cog_cfg, "refinement", None)
            n_samples = self.sample_cfg.n
            temp = self.sample_cfg.temperature
            top_p = self.sample_cfg.top_p
            try:
                if isinstance(refinement, RefinementStrategy) and refinement is RefinementStrategy.BEST_OF_N:
                    v = int(getattr(self.cog_cfg, "voting_n", 5))
                    if v > 0:
                        n_samples = v
                    # BEST_OF_N uses a refinement-specific temperature; fall
                    # back to the global sampling temperature only if that is
                    # explicitly configured.
                    try:
                        best_temp = getattr(self.cog_cfg, "best_of_n_temperature", None)
                    except Exception:
                        best_temp = None
                    if isinstance(best_temp, (int, float)):
                        temp = float(best_temp)
                    elif temp == 0.0:
                        temp = 0.7
                    if top_p == 1.0:
                        top_p = 0.95
            except Exception:
                pass

            max_attempts = 3
            outs: List[str] = []
            for attempt in range(1, max_attempts + 1):
                outs = self.sampler.sample(
                    self.client,
                    prompt,
                    self.s_type,
                    temperature=temp,
                    top_p=top_p,
                    top_k=self.sample_cfg.top_k,
                    n=n_samples,
                    timeout=9999.0,
                )
                if not outs:
                    logger.warning(
                        "LLMPolicy.decide: no responses from LLM on attempt {}/{}; retrying",
                        attempt,
                        max_attempts,
                    )
                    continue

                self._update_llm_token_stats()
                cand_action, cand_meta = self._decide_o1_cognitive(outs, pruned_actions, legal_actions, env)
                fallback_triggered = bool(cand_meta.get("fallback_triggered", False))
                fallback_type = cand_meta.get("fallback_type")
                base_action = cand_action
                base_meta = cand_meta
                log_outs = outs
                if not fallback_triggered or fallback_type not in {"invalid_id", "no_valid_output"}:
                    break
                logger.warning(
                    "LLMPolicy.decide: fallback_type={} on attempt {}/{}; retrying to get direct LLM action",
                    fallback_type,
                    attempt,
                    max_attempts,
                )

            if not outs:
                logger.warning(
                    "LLMPolicy.decide: no responses from LLM after {} attempts; falling back to heuristic decision",
                    max_attempts,
                )
                # Scheme A: do not abort the whole run. Instead, fall back to a
                # heuristic decision so that the environment can continue.
                self.stats["fallback_count"] = self.stats.get("fallback_count", 0) + 1
                fallback_act: Optional[Dict[str, Any]]
                if pruned_actions:
                    fallback_act = pruned_actions[0]
                else:
                    fallback_act = choose_by_heuristic("SPT", legal_actions, env)

                base_action = fallback_act
                base_meta = {
                    "parsed_action_id": None,
                    "fallback_triggered": True,
                    "fallback_type": "no_llm_response",
                }

        act, meta, final_prompt, final_outs = self._refine_decision(
            base_action=base_action,
            base_meta=base_meta,
            obs=obs,
            legal_actions=legal_actions,
            env=env,
            base_prompt=log_prompt,
            base_outs=log_outs,
        )
        self._log_decision(
            obs=obs,
            prompt=final_prompt,
            outs=final_outs,
            action=act,
            env=env,
            parsed_action_id=meta.get("parsed_action_id"),
            fallback_triggered=meta.get("fallback_triggered", False),
            fallback_type=meta.get("fallback_type"),
        )
        return act

    def _is_legal(self, act: Dict[str, Any], legal_actions: List[Dict[str, Any]]) -> bool:
        if not act:
            return False
        act_j = act.get("job_id")
        act_g = act.get("machine_group")
        act_m = act.get("machine_id")
        if act_j is None or act_g is None:
            return False
        match: Optional[Dict[str, Any]] = None
        for a in legal_actions:
            if str(a.get("job_id")) == str(act_j) and str(a.get("machine_group")) == str(act_g):
                match = a
                break

        idx: Optional[int] = None
        try:
            if isinstance(act_j, int):
                idx = act_j
            elif isinstance(act_j, str):
                try:
                    idx = int(act_j)
                except Exception:
                    if "-" in act_j:
                        tail = act_j.rsplit("-", 1)[-1]
                        try:
                            idx = int(tail)
                        except Exception:
                            idx = None
        except Exception:
            idx = None

        if match is None:
            if idx is None:
                return False

            matches: List[Dict[str, Any]] = []
            for a in legal_actions:
                aj = a.get("job_id")
                ag = a.get("machine_group")
                if str(ag) != str(act_g):
                    continue
                sj = str(aj)
                if sj == f"Job-{idx}" or sj == str(idx) or sj.endswith(f"-{idx}"):
                    matches.append(a)

            if len(matches) != 1:
                return False
            match = matches[0]

        act["job_id"] = match.get("job_id")

        cands = match.get("machine_candidates") or []
        if act_m is not None and cands:
            s_mid = str(act_m)
            for m in cands:
                if str(m) == s_mid:
                    return True
            return False

        return True

    def _env_score(self, act: Dict[str, Any], env) -> float:
        try:
            steps = int(getattr(self.sample_cfg, "rollout_steps", 0) or 0)
            if steps and hasattr(env, "quick_rollout_score"):
                return float(env.quick_rollout_score(act, steps=steps))
            return float(env.estimate_action_score(act))
        except Exception:
            return 0.0

    def _log_decision(
        self,
        obs: Dict[str, Any],
        prompt: str,
        outs: List[str],
        action: Optional[Dict[str, Any]],
        env,
        *,
        parsed_action_id: Optional[int],
        fallback_triggered: bool,
        fallback_type: Optional[str],
    ) -> None:
        try:
            info_level = getattr(self.cog_cfg, "info_level", None)
            mode = getattr(self.cog_cfg, "mode", None)
            info_level_name = info_level.name if isinstance(info_level, InfoLevel) else None
            mode_name = mode.name if isinstance(mode, InteractionMode) else None

            reward_signal: Optional[float] = None
            if action is not None:
                reward_signal = self._env_score(action, env)

            # Optional detailed timing diagnostics for the executed action.
            action_timing: Optional[Dict[str, Any]] = None
            if action is not None and hasattr(env, "get_action_timing"):
                try:
                    tdata = env.get_action_timing(action)
                except Exception:
                    tdata = None
                if isinstance(tdata, dict) and tdata:
                    action_timing = dict(tdata)

            record: Dict[str, Any] = {
                "step": len(self.history) + 1,
                "o_type": self.o_type.value,
                "s_type": self.s_type.value,
                "info_level": info_level_name,
                "mode": mode_name,
                "prompt": prompt,
                "raw_responses": list(outs),
                "parsed_action_id": parsed_action_id,
                "executed_action": action,
                "reward_signal": reward_signal,
                "fallback_triggered": bool(fallback_triggered),
                "fallback_type": fallback_type,
            }
            if action_timing is not None:
                record["action_timing"] = action_timing

            try:
                raw_action_ids: List[Any] = []
                raw_job_ids: List[Any] = []
                raw_machine_groups: List[Any] = []
                raw_machine_ids: List[Any] = []
                if isinstance(outs, list):
                    for t in outs[:10]:
                        obj = None
                        try:
                            obj = prompts._safe_json_loads(str(t))
                        except Exception:
                            obj = None
                        if not isinstance(obj, dict):
                            continue
                        if "action_id" in obj:
                            raw_action_ids.append(obj.get("action_id"))
                        if "job_id" in obj:
                            raw_job_ids.append(obj.get("job_id"))
                        if "machine_group" in obj:
                            raw_machine_groups.append(obj.get("machine_group"))
                        if "machine_id" in obj:
                            raw_machine_ids.append(obj.get("machine_id"))
                if raw_action_ids:
                    record["raw_action_ids"] = raw_action_ids
                if raw_job_ids:
                    record["raw_job_ids"] = raw_job_ids
                if raw_machine_groups:
                    record["raw_machine_groups"] = raw_machine_groups
                if raw_machine_ids:
                    record["raw_machine_ids"] = raw_machine_ids
            except Exception:
                pass

            self.history.append(record)
            try:
                self.traj_logger.append(record)
            except Exception:
                pass

            try:
                prompt_snippet = prompt[:512] + "..." if isinstance(prompt, str) and len(prompt) > 512 else prompt
            except Exception:
                prompt_snippet = "<unavailable>"
            try:
                outs_preview = [str(x)[:256] for x in (outs[:3] if isinstance(outs, list) else [])]
            except Exception:
                outs_preview = []

            logger.debug(
                "LLMPolicy debug: step={} prompt_snippet={}",
                record["step"],
                prompt_snippet,
            )
            logger.debug(
                "LLMPolicy debug: step={} raw_responses_preview={}",
                record["step"],
                outs_preview,
            )
            logger.debug(
                "LLMPolicy debug: step={} executed_action={}",
                record["step"],
                action,
            )
            if action_timing is not None:
                logger.debug(
                    "LLMPolicy debug: step={} action_timing={}",
                    record["step"],
                    action_timing,
                )

            try:
                heavy_flag = os.getenv("DYNA_SCHEDBENCH_LLM_DEBUG_FULL", "")
                heavy_on = str(heavy_flag).strip().lower() in {"1", "true", "yes", "on"}
            except Exception:
                heavy_on = False
            if heavy_on:
                logger.debug(
                    "LLMPolicy heavy-debug: step={} full_prompt=\n{}",
                    record["step"],
                    prompt,
                )
                logger.debug(
                    "LLMPolicy heavy-debug: step={} full_raw_responses={}",
                    record["step"],
                    outs,
                )

            try:
                if fallback_triggered:
                    logger.warning(
                        "LLMPolicy decision fallback: step={} o_type={} s_type={} info_level={} mode={} fallback_type={} reward={}",
                        record["step"],
                        record["o_type"],
                        record["s_type"],
                        record["info_level"],
                        record["mode"],
                        record["fallback_type"],
                        record["reward_signal"],
                    )
                else:
                    logger.debug(
                        "LLMPolicy decision: step={} o_type={} s_type={} info_level={} mode={} reward={}",
                        record["step"],
                        record["o_type"],
                        record["s_type"],
                        record["info_level"],
                        record["mode"],
                        record["reward_signal"],
                    )
            except Exception:
                pass

        except Exception:
            pass

    def _decide_o1_tool_use(
        self,
        base_prompt: str,
        pruned_actions: List[Dict[str, Any]],
        legal_actions: List[Dict[str, Any]],
        env,
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any], str, List[str]]:
        info: Dict[str, Any] = {
            "parsed_action_id": None,
            "fallback_triggered": False,
            "fallback_type": None,
        }
        prompt = base_prompt
        all_outs: List[str] = []

        # Hard guard: only LEVEL_1_MYOPIC is allowed to actually use tools.
        # For any other info level, completely ignore tool calls and fall back
        # to the same cognitive sampling path as in the non-TOOL_USE branch.
        try:
            info_level = getattr(self.cog_cfg, "info_level", None)
        except Exception:
            info_level = None
        if not isinstance(info_level, InfoLevel) or info_level is not InfoLevel.LEVEL_1_MYOPIC:
            refinement = getattr(self.cog_cfg, "refinement", None)
            n_samples = self.sample_cfg.n
            try:
                if isinstance(refinement, RefinementStrategy) and refinement is RefinementStrategy.BEST_OF_N:
                    v = int(getattr(self.cog_cfg, "voting_n", 5))
                    if v > 0:
                        n_samples = v
            except Exception:
                pass

            max_attempts = 3
            outs: List[str] = []
            base_action: Optional[Dict[str, Any]] = None
            base_meta: Dict[str, Any] = {
                "parsed_action_id": None,
                "fallback_triggered": False,
                "fallback_type": None,
            }
            for attempt in range(1, max_attempts + 1):
                outs = self.sampler.sample(
                    self.client,
                    prompt,
                    self.s_type,
                    temperature=self.sample_cfg.temperature,
                    top_p=self.sample_cfg.top_p,
                    top_k=self.sample_cfg.top_k,
                    n=n_samples,
                    timeout=9999.0,
                )
                if not outs:
                    logger.warning(
                        "O1 TOOL_USE (no-tools path): no responses from LLM on attempt {}/{}; retrying",
                        attempt,
                        max_attempts,
                    )
                    continue

                self._update_llm_token_stats()
                cand_action, cand_meta = self._decide_o1_cognitive(outs, pruned_actions, legal_actions, env)
                fallback_triggered = bool(cand_meta.get("fallback_triggered", False))
                fallback_type = cand_meta.get("fallback_type")
                base_action = cand_action
                base_meta = cand_meta
                if not fallback_triggered or fallback_type not in {"invalid_id", "no_valid_output"}:
                    break
                logger.warning(
                    "O1 TOOL_USE (no-tools path): fallback_type={} on attempt {}/{}; retrying to get direct LLM action",
                    fallback_type,
                    attempt,
                    max_attempts,
                )

            if not outs:
                logger.warning(
                    "O1 TOOL_USE (no-tools path): no responses from LLM after {} attempts; falling back to heuristic decision",
                    max_attempts,
                )
                self.stats["fallback_count"] = self.stats.get("fallback_count", 0) + 1
                info = dict(base_meta)
                info["fallback_triggered"] = True
                info["fallback_type"] = "no_llm_response"
                if pruned_actions:
                    fallback_act = pruned_actions[0]
                else:
                    fallback_act = choose_by_heuristic("SPT", legal_actions, env)
                return fallback_act, info, prompt, outs

            return base_action, base_meta, prompt, outs
        for turn_idx in range(3):
            try:
                max_attempts = 3
                turn_outs: List[str] = []
                for attempt in range(1, max_attempts + 1):
                    turn_outs = self.client.generate(
                        prompt,
                        n=1,
                        temperature=self.sample_cfg.temperature,
                        top_p=self.sample_cfg.top_p,
                        top_k=self.sample_cfg.top_k,
                        timeout=9999.0,
                    )
                    if isinstance(turn_outs, list) and turn_outs:
                        break
                    logger.warning(
                        "O1 TOOL_USE: no responses from LLM on attempt {}/{} for turn_idx={}; retrying",
                        attempt,
                        max_attempts,
                        turn_idx,
                    )
                if not isinstance(turn_outs, list) or not turn_outs:
                    logger.error(
                        "O1 TOOL_USE: no responses from LLM after {} attempts for turn_idx={}; aborting decision",
                        max_attempts,
                        turn_idx,
                    )
                    raise RuntimeError("LLMScheduler LLM returned no responses in TOOL_USE mode after retries")
            except Exception as exc:
                logger.warning("O1 TOOL_USE: LLM generate failed: {}", exc)
                break
            if not isinstance(turn_outs, list):
                break
            for t in turn_outs:
                all_outs.append(str(t))
            self._update_llm_token_stats()

            found_aid: Optional[int] = None
            for t in turn_outs:
                obj = prompts._safe_json_loads(str(t))
                aid_val: Optional[int] = None
                if isinstance(obj, dict) and "action_id" in obj and obj.get("tool") is None:
                    try:
                        aid_val = int(obj["action_id"])
                    except Exception:
                        aid_val = None
                if aid_val is not None and 1 <= aid_val <= len(pruned_actions):
                    found_aid = aid_val
                    break
            if found_aid is not None:
                info["parsed_action_id"] = found_aid
                return pruned_actions[found_aid - 1], info, prompt, all_outs
            allow_tools = turn_idx < 2
            if not allow_tools:
                break

            simulate_ids: List[int] = []
            inspect_ids: List[int] = []
            for t in turn_outs:
                text = str(t)
                obj = prompts._safe_json_loads(text)
                if isinstance(obj, dict) and "tool" in obj:
                    tool_name = str(obj.get("tool", "")).lower()
                    if tool_name == "simulate_action" and "action_id" in obj:
                        try:
                            aid = int(obj["action_id"])
                        except Exception:
                            aid = None
                        if aid is not None:
                            simulate_ids.append(aid)
                    if tool_name == "inspect_action_details" and "action_id" in obj:
                        try:
                            aid = int(obj["action_id"])
                        except Exception:
                            aid = None
                        if aid is not None:
                            inspect_ids.append(aid)
                if "Tool:" in text:
                    lines = text.splitlines()
                    for line in lines:
                        if "Tool:" not in line:
                            continue
                        part = line.split("Tool:", 1)[1].strip()
                        if "simulate_action" in part and "(" in part and ")" in part:
                            inside = part[part.find("(") + 1 : part.rfind(")")].strip()
                            try:
                                aid = int(inside)
                            except Exception:
                                aid = None
                            if aid is not None:
                                simulate_ids.append(aid)
                        if "inspect_action_details" in part and "(" in part and ")" in part:
                            inside = part[part.find("(") + 1 : part.rfind(")")].strip()
                            try:
                                aid = int(inside)
                            except Exception:
                                aid = None
                            if aid is not None:
                                inspect_ids.append(aid)

            observations: List[str] = []
            ctx = ToolRuntimeContext(env=env, pruned_actions=pruned_actions)
            seen_sim: set[int] = set()
            for aid in simulate_ids:
                if aid in seen_sim:
                    continue
                seen_sim.add(aid)
                if not (1 <= aid <= len(pruned_actions)):
                    continue
                text = execute_tool_call(
                    "simulate_action",
                    {"action_id": aid},
                    ctx,
                )
                if text:
                    observations.append(text)

            seen_inspect: set[int] = set()
            for aid in inspect_ids:
                if aid in seen_inspect:
                    continue
                seen_inspect.add(aid)
                if not (1 <= aid <= len(pruned_actions)):
                    continue
                text = execute_tool_call(
                    "inspect_action_details",
                    {"action_id": aid},
                    ctx,
                )
                if text:
                    observations.append(text)

            if not observations:
                break

            if turn_idx == 0:
                guidance = (
                    "\n\nBased on the observations above, you may call simulate_action(action_id) again or respond with {\"action_id\": <int>} "
                    "to choose from the ActionID column."
                )
            else:
                guidance = (
                    "\n\nBased on the observations above, do not call any tools again. "
                    "Respond with a single final JSON object {\"action_id\": <int>, \"job_id\": <int or string>, "
                    "\"machine_group\": <string>, \"machine_id\": <string or null>} choosing exactly one ActionID."
                )

            # Preserve causal chain across tool-use turns: include the LLM's
            # previous tool call / reasoning output before appending tool
            # observations.
            turn_text = "\n".join(str(x) for x in turn_outs if x is not None)
            if turn_text.strip():
                prompt = prompt + "\n\n" + "Assistant:\n" + turn_text
            prompt = prompt + "\n\n" + "\n".join(observations) + guidance

        info["fallback_triggered"] = True
        info["fallback_type"] = "tool_use_fallback"
        if pruned_actions:
            return pruned_actions[0], info, prompt, all_outs
        self.stats["fallback_count"] = self.stats.get("fallback_count", 0) + 1
        fallback_act = choose_by_heuristic("SPT", legal_actions, env)
        return fallback_act, info, prompt, all_outs

    def _decide_o1_cognitive(
        self,
        outs: List[str],
        pruned_actions: List[Dict[str, Any]],
        legal_actions: List[Dict[str, Any]],
        env,
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        info: Dict[str, Any] = {
            "parsed_action_id": None,
            "fallback_triggered": False,
            "fallback_type": None,
        }
        mode = getattr(self.cog_cfg, "mode", InteractionMode.DIRECT)
        # CoT path: expect {"reasoning": "...", "action_id": <int>}
        if mode is InteractionMode.COT:
            counts: Dict[int, int] = {}
            for t in outs:
                obj = prompts._safe_json_loads(t)
                aid: Optional[int] = None
                if isinstance(obj, dict) and "action_id" in obj:
                    try:
                        aid = int(obj["action_id"])
                    except Exception:
                        aid = None
                if aid is None:
                    continue
                if 1 <= aid <= len(pruned_actions):
                    counts[aid] = counts.get(aid, 0) + 1
            if counts:
                best_id = max(counts.items(), key=lambda kv: kv[1])[0]
                info["parsed_action_id"] = best_id
                return pruned_actions[best_id - 1], info
            # Robust fallback: default to first pruned candidate (SPT-driven)
            info["fallback_triggered"] = True
            info["fallback_type"] = "invalid_id"
            if pruned_actions:
                self.stats["fallback_count"] = self.stats.get("fallback_count", 0) + 1
                return pruned_actions[0], info
            # If pruning somehow produced nothing, fall back to heuristic
            self.stats["fallback_count"] = self.stats.get("fallback_count", 0) + 1
            return choose_by_heuristic("SPT", legal_actions, env), info

        # Direct (non-CoT) cognitive path: reuse legacy O1 voting logic
        # Prefer explicit action_id (index into pruned_actions) when provided by the LLM,
        # and fall back to job_id / machine_group matching via _is_legal otherwise.
        candidates: List[Dict[str, Any]] = []
        for t in outs:
            act = prompts.parse_o1(t)
            aid_val: Optional[int] = None
            try:
                if isinstance(act, dict) and "action_id" in act:
                    aid_val = int(act["action_id"])
            except Exception:
                aid_val = None

            if aid_val is not None and 1 <= aid_val <= len(pruned_actions):
                base_act = pruned_actions[aid_val - 1]
                candidates.append(dict(base_act))
                continue

            if self._is_legal(act, legal_actions):
                candidates.append(act)
            else:
                self.stats["invalid_outputs"] = self.stats.get("invalid_outputs", 0) + 1
        if candidates:
            freq: Dict[str, int] = {}
            uniq: Dict[str, Dict[str, Any]] = {}
            for a in candidates:
                key = f"{a['job_id']}|{a['machine_group']}|{a.get('machine_id','')}"
                freq[key] = freq.get(key, 0) + 1
                uniq[key] = a
            best_keys = [k for k, v in freq.items() if v == max(freq.values())]
            if len(best_keys) == 1:
                return uniq[best_keys[0]], info
            self.stats["ties_broken"] += 1
            scored = [(uniq[k], self._env_score(uniq[k], env)) for k in best_keys]
            scored.sort(key=lambda x: x[1], reverse=True)
            self.stats["env_selected_when_tie"] += 1
            info["fallback_type"] = "tie_broken"
            return scored[0][0], info
        self.stats["fallback_count"] = self.stats.get("fallback_count", 0) + 1
        info["fallback_triggered"] = True
        info["fallback_type"] = "no_valid_output"
        if pruned_actions:
            return pruned_actions[0], info
        return choose_by_heuristic("SPT", legal_actions, env), info

    def _refine_decision(
        self,
        *,
        base_action: Optional[Dict[str, Any]],
        base_meta: Dict[str, Any],
        obs: Dict[str, Any],
        legal_actions: List[Dict[str, Any]],
        env,
        base_prompt: str,
        base_outs: List[str],
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any], str, List[str]]:
        info: Dict[str, Any] = dict(base_meta or {})
        refinement = getattr(self.cog_cfg, "refinement", RefinementStrategy.GREEDY)
        if not isinstance(refinement, RefinementStrategy):
            return base_action, info, base_prompt, base_outs
        if refinement is RefinementStrategy.GREEDY:
            return base_action, info, base_prompt, base_outs
        if base_action is None:
            return base_action, info, base_prompt, base_outs

        if refinement is RefinementStrategy.BEST_OF_N:
            return base_action, info, base_prompt, base_outs

        if refinement is not RefinementStrategy.REFLECTION:
            return base_action, info, base_prompt, base_outs

        try:
            encoder = ObservationEncoder(self.cog_cfg)
            encoded = encoder.encode(obs, legal_actions, env)
            state_table = prompts._render_markdown_table(encoded.headers, encoded.rows)
        except Exception:
            return base_action, info, base_prompt, base_outs

        chosen_id: Optional[int] = None
        try:
            pid = base_meta.get("parsed_action_id") if isinstance(base_meta, dict) else None
            if pid is not None:
                v = int(pid)
                if 1 <= v <= len(encoded.pruned_actions):
                    chosen_id = v
        except Exception:
            chosen_id = None

        if chosen_id is None and base_action is not None:
            try:
                bj = base_action.get("job_id")
                bg = base_action.get("machine_group")
                bm = base_action.get("machine_id")
            except Exception:
                bj = None
                bg = None
                bm = None
            if bj is not None and bg is not None:
                for i, cand in enumerate(encoded.pruned_actions, start=1):
                    cj = cand.get("job_id")
                    cg = cand.get("machine_group")
                    cm = cand.get("machine_id")
                    if str(cj) != str(bj) or str(cg) != str(bg):
                        continue
                    if bm is not None:
                        if str(cm) != str(bm):
                            continue
                    chosen_id = i
                    break

        if chosen_id is None:
            return base_action, info, base_prompt, base_outs

        try:
            prev_resp = base_outs[-1] if base_outs else ""
        except Exception:
            prev_resp = ""

        try:
            ref_prompt = prompts.build_reflection_prompt(
                state_table=state_table,
                previous_response=prev_resp,
                chosen_action_id=chosen_id,
            )
        except Exception:
            return base_action, info, base_prompt, base_outs

        try:
            rounds = int(getattr(self.cog_cfg, "reflection_rounds", 1))
            if rounds <= 0:
                rounds = 1
        except Exception:
            rounds = 1

        ref_outs: List[str] = []
        try:
            ref_temp_cfg = getattr(self.cog_cfg, "reflection_temperature", None)
        except Exception:
            ref_temp_cfg = None
        if isinstance(ref_temp_cfg, (int, float)):
            temp_ref = float(ref_temp_cfg)
        elif self.sample_cfg.temperature != 0.0:
            temp_ref = self.sample_cfg.temperature
        else:
            temp_ref = 0.3

        if self.sample_cfg.top_p != 1.0:
            top_p_ref = self.sample_cfg.top_p
        else:
            top_p_ref = 1.0
        for _ in range(rounds):
            try:
                outs = self.sampler.sample(
                    self.client,
                    ref_prompt,
                    self.s_type,
                    temperature=temp_ref,
                    top_p=top_p_ref,
                    top_k=self.sample_cfg.top_k,
                    n=1,
                    timeout=9999.0,
                )
            except Exception as exc:
                logger.warning("O1 REFLECTION: LLM sample failed: {}", exc)
                break
            self._update_llm_token_stats()
            for t in outs:
                ref_outs.append(str(t))

        if not ref_outs:
            return base_action, info, base_prompt, base_outs

        counts: Dict[int, int] = {}
        for t in ref_outs:
            obj = prompts._safe_json_loads(t)
            if isinstance(obj, dict) and "action_id" in obj:
                try:
                    aid = int(obj["action_id"])
                except Exception:
                    continue
                if 1 <= aid <= len(encoded.pruned_actions):
                    counts[aid] = counts.get(aid, 0) + 1

        if not counts:
            return base_action, info, ref_prompt, base_outs + ref_outs

        best_id = max(counts.items(), key=lambda kv: kv[1])[0]
        info["parsed_action_id"] = best_id
        try:
            final_action = encoded.pruned_actions[best_id - 1]
        except Exception:
            final_action = base_action

        final_prompt = ref_prompt
        final_outs = base_outs + ref_outs
        return final_action, info, final_prompt, final_outs

    def _update_llm_token_stats(self) -> None:
        try:
            client = self.client
            for _ in range(3):
                tin = getattr(client, "total_input_tokens", None)
                tout = getattr(client, "total_output_tokens", None)
                if isinstance(tin, (int, float)) or isinstance(tout, (int, float)):
                    if isinstance(tin, (int, float)):
                        self.stats["llm_total_input_tokens"] = float(tin)
                    if isinstance(tout, (int, float)):
                        self.stats["llm_total_output_tokens"] = float(tout)
                    return
                base = getattr(client, "_base", None)
                if base is None or base is client:
                    break
                client = base
        except Exception:
            pass
