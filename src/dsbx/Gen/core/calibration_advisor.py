"""
Calibration-based Parameter Advisor with LLM
Generates natural language advice based on actual calibration results

Also provides intelligent suggestions for calibration parameters
"""

import json
import os
import time
from typing import Dict, Any, Union, List
from openai import OpenAI
from loguru import logger
from ..models.inputs import InputModel


def _build_advice_prompt(advice_data: Dict[str, Any]) -> list:
    """
    Build prompt for LLM to generate parameter advice based on calibration results.
    """
    # Extract data
    config = advice_data["user_config"]
    results = advice_data["calibration_results"]
    achieved = advice_data["achieved_metrics"]
    errors = advice_data["metric_errors"]
    diversity = advice_data["pareto_diversity"]
    
    # Build system prompt
    system_prompt = """You are an expert advisor for dynamic job shop scheduling (DJSS) systems.

Your task is to analyze the user's configured benchmark instance generation parameters and provide professional advice based on the actual calibration results.

Key metric definitions:
- rho_global: overall machine utilization (0–1); values close to 1 indicate congestion
- scv_a: squared coefficient of variation of inter-arrival times; reflects irregularity of arrivals
- scv_p: squared coefficient of variation of processing times; reflects processing-time uncertainty
- ddt: due-date tightness (>1); smaller values mean tighter due dates
- disturbance: proportion of machine downtime disturbances (0–1)
- rho_bottleneck: target utilization of bottleneck operations

Analysis focus:
1. Achievability of the configuration: are average errors within an acceptable range?
2. Diagnosis: which metrics have large errors and why?
3. Parameter trade-offs: relationships and compromises between metrics.
4. Concrete recommendations: how to adjust parameters to improve results.

Output requirements:
- Use English.
- Provide a clear structure with bullet points or sections.
- Provide concrete numerical suggestions (for example, "reduce rho_global from 0.80 to 0.75").
- Explain the technical reasoning while remaining user friendly.
- Keep the length around 300–500 words."""
    
    # Build user prompt with calibration data
    user_prompt = f"""# User configuration

**System size**:
- Horizon: {config['horizon']:.0f} time units
- Number of machines: {config['num_machines']}
- Number of job families: {config['num_job_families']}
- Total jobs: {config['jobs_total']}

**Target metrics**:
- rho_global (overall utilization): {config['targets']['rho_global']}
- scv_a (arrival variability): {config['targets']['scv_a']}
- scv_p (processing-time variability): {config['targets']['scv_p']}
- ddt (due-date tightness): {config['targets']['ddt']}
- disturbance (disturbance level): {config['targets']['disturbance']}
{f"- rho_bottleneck: {config['targets']['rho_bottleneck']}" if config['targets']['rho_bottleneck'] else ""}

---

# Calibration results

**Optimization process**:
- Generations used: {results['generations_used']}/{results['max_generations']}
- Status: {"early convergence" if results['converged'] else "reached maximum generations"}
- Pareto front size: {results['pareto_front_size']} solutions
- Pareto diversity:
  - Total error range: [{diversity['total_error_range'][0]:.4f}, {diversity['total_error_range'][1]:.4f}]
  - Maximum error range: [{diversity['max_error_range'][0]:.4f}, {diversity['max_error_range'][1]:.4f}]

**Metric errors for the selected solution**:
"""
    
    # Add metric-level errors
    for metric, error in sorted(errors.items()):
        target = config['targets'].get(metric, "N/A")
        observed = achieved.get(metric, "N/A")
        # Format observed value
        observed_str = f"{observed:.4f}" if isinstance(observed, (int, float)) else str(observed)
        user_prompt += (
            f"\n- {metric}: target={target}, "
            f"observed={observed_str}, error={error:.2f}%"
        )
    
    user_prompt += (
        f"\n\n**Overall assessment**:"
        f"\n- Mean error: {results['mean_error']:.2f}%"
        f"\n- Total error: {results['total_error']:.4f}"
    )
    
    user_prompt += (
        "\n\n---\n\nPlease provide professional calibration-parameter advice "
        "based on the data above."
    )
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def _call_llm_chatanywhere(messages: list) -> str:
    """
    Call ChatAnywhere GPT-4o-mini API with simple retry logic.
    
    Uses environment variable OPENAI_API_KEY or falls back to a default key for testing.
    """
    # Testing / offline mode: use a deterministic dummy response instead of
    # calling any external LLM API. This is controlled by the
    # DYNASCHEDBENCH_DUMMY_LLM flag, or by the absence of OPENAI_API_KEY.
    dummy_flag = os.getenv("DYNASCHEDBENCH_DUMMY_LLM", "").lower()
    use_dummy = dummy_flag in {"1", "true", "yes"} or not os.getenv("OPENAI_API_KEY")
    if use_dummy:
        logger.info("Using dummy LLM backend for calibration advice (no external API call).")
        return (
            "[DUMMY LLM] This placeholder recommendation was generated in test mode; no external LLM was called.\n"
            "Please use the numeric results and error statistics for further analysis."
        )

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = "https://api.chatanywhere.tech/v1"
    model = "gpt-4o-mini-ca"
    
    logger.info(f"Calling ChatAnywhere API (model: {model})...")
    
    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=2000,
                temperature=0.7,
                top_p=0.9,
                timeout=120  # 2 minute timeout
            )
            
            content = response.choices[0].message.content
            
            logger.info(
                f"LLM call successful. Tokens: {response.usage.prompt_tokens} in, "
                f"{response.usage.completion_tokens} out"
            )
            
            return content
            
        except Exception as e:
            logger.warning(f"LLM call attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"All {max_retries} LLM call attempts failed")
                raise


def generate_llm_advice(advice_data: Dict[str, Any]) -> str:
    """
    Generate natural language advice using LLM based on calibration results.
    
    Args:
        advice_data: Dictionary containing user config, calibration results, and metrics
        
    Returns:
        Natural language advice text in English
    """
    # Build prompt
    messages = _build_advice_prompt(advice_data)
    
    # Log prompt for debugging
    logger.debug("=" * 80)
    logger.debug("LLM Prompt:")
    logger.debug(json.dumps(messages, ensure_ascii=False, indent=2))
    logger.debug("=" * 80)
    
    # Call LLM
    try:
        advice_text = _call_llm_chatanywhere(messages)
        return advice_text
    except Exception as e:
        # Fallback to rule-based advice
        logger.warning(f"LLM call failed, using fallback: {e}")
        return _generate_fallback_advice(advice_data)


def _generate_fallback_advice(advice_data: Dict[str, Any]) -> str:
    """
    Generate rule-based advice when LLM is unavailable.
    """
    results = advice_data["calibration_results"]
    errors = advice_data["metric_errors"]
    config = advice_data["user_config"]["targets"]
    
    lines = ["# Parameter recommendations (rule based)", ""]
    
    # Overall assessment
    mean_error = results['mean_error']
    if mean_error < 5:
        lines.append("## Overall assessment: excellent")
        lines.append(
            "Your configuration parameters are very well chosen and the system "
            "can closely achieve the targets."
        )
    elif mean_error < 10:
        lines.append("## Overall assessment: good")
        lines.append(
            "Your configuration parameters are generally reasonable and the "
            "system can get close to the targets."
        )
    elif mean_error < 20:
        lines.append("## Overall assessment: challenging")
        lines.append(
            "Some metric targets are hard to achieve; consider relaxing some "
            "of them."
        )
    else:
        lines.append("## Overall assessment: potentially infeasible")
        lines.append(
            "The current configuration may be physically infeasible; consider "
            "significantly adjusting the targets."
        )
    
    lines.append("")
    lines.append("## Detailed analysis")
    
    # Analyze each metric
    for metric, error in sorted(errors.items(), key=lambda x: x[1], reverse=True):
        if error > 15:
            lines.append(f"\n### {metric} (error {error:.1f}%)")
            if metric == "scv_p" and errors.get("disturbance", 0) > 10:
                lines.append(
                    "- The processing-variability target is hard to achieve and "
                    "may conflict with the disturbance target."
                )
                lines.append(
                    f"- Recommendation: relax scv_p to around "
                    f"{config.get('scv_p', 1) * 1.1:.2f} or lower the "
                    "disturbance target."
                )
            elif metric == "rho_global" and error > 15:
                lines.append("- Global utilization error is large.")
                lines.append(
                    "- Recommendation: adjust jobs_total or horizon to make "
                    "the target more achievable."
                )
            else:
                lines.append(
                    f"- Recommendation: change the target from "
                    f"{config.get(metric, 'N/A')} to about "
                    f"{float(config.get(metric, 1)) * 0.9:.2f}"
                )
    
    return "\n".join(lines)


class CalibrationAdvisor:
    """Advisor for calibration-parameter defaults.

    Provides calibration-step suggestions, calibration-mode recommendations, and
    target-combination-aware decisions.
    """
    
    @staticmethod
    def _extract_scalar(value: Union[float, List[float]]) -> Union[float, None]:
        """Extract a scalar from a batchable value."""
        if isinstance(value, list):
            return float(value[0]) if value else None
        return float(value) if value is not None else None
    
    def suggest_calibration_steps(self, model: InputModel) -> int:
        """Suggest the number of calibration steps from the target combination.

        The heuristic starts from a base budget, adds steps for difficult
        individual targets, and then accounts for coupling between targets.

        Args:
            model: Input configuration model.

        Returns:
            Suggested number of calibration steps.
        """
        base_steps = 5
        extra_steps = 0
        
        targets = model.targets
        
        if targets.load_cv is not None:
            load_cv = float(targets.load_cv)
            if load_cv < 0.08 or load_cv > 0.35:
                extra_steps += 6
                logger.debug("Extreme load_cv target detected: +6 steps")
            elif load_cv < 0.12 or load_cv > 0.25:
                extra_steps += 4
                logger.debug("Challenging load_cv target detected: +4 steps")
            else:
                extra_steps += 2
                logger.debug("load_cv target detected: +2 steps")
        
        ddt = self._extract_scalar(targets.ddt)
        if ddt is not None:
            if ddt < 1.3:
                extra_steps += 5
                logger.debug("Extremely tight due dates detected: +5 steps")
            elif ddt < 1.5:
                extra_steps += 3
                logger.debug("Tight due dates detected: +3 steps")
            elif ddt > 5.0:
                extra_steps += 2
                logger.debug("Very loose due dates detected: +2 steps")
        
        rho = self._extract_scalar(targets.rho_global)
        if rho is not None:
            if rho > 0.90:
                extra_steps += 4
                logger.debug("Extremely high utilization target detected: +4 steps")
            elif rho > 0.85:
                extra_steps += 2
                logger.debug("High utilization target detected: +2 steps")
            elif rho < 0.3:
                extra_steps += 2
                logger.debug("Extremely low utilization target detected: +2 steps")
        
        if targets.rho_bottleneck:
            n_bottlenecks = len(targets.rho_bottleneck)
            extra = min(n_bottlenecks * 2, 6)
            extra_steps += extra
            logger.debug(
                f"Detected {n_bottlenecks} bottleneck targets: +{extra} steps"
            )
        
        scv_a = self._extract_scalar(targets.scv_a)
        scv_p = self._extract_scalar(targets.scv_p)
        if (scv_a and scv_a > 2.0) or (scv_p and scv_p > 2.0):
            extra_steps += 2
            logger.debug("High variability detected: +2 steps")
        
        if (scv_a is not None and scv_a < 0.1) or (scv_p is not None and scv_p < 0.1):
            extra_steps += 2
            logger.debug("Near-zero variability detected: +2 steps")
        
        difficult_targets = sum([
            targets.load_cv is not None,
            len(targets.rho_bottleneck) > 0,
            ddt is not None and ddt < 1.5,
            rho is not None and rho > 0.85,
        ])
        if difficult_targets >= 3:
            extra_steps += 3
            logger.debug(
                f"{difficult_targets} difficult target combinations detected: +3 steps"
            )
        elif difficult_targets >= 2:
            extra_steps += 1
        
        total_steps = base_steps + extra_steps

        if total_steps < 1:
            total_steps = 1

        logger.info(
            f"Suggested calibration steps: {total_steps} "
            f"(base={base_steps}, extra={extra_steps})"
        )
        
        return total_steps
    
    def suggest_calibration_mode(self, model: InputModel) -> str:
        """Recommend a calibration mode.

        Args:
            model: Input configuration model.

        Returns:
            One of 'sequential', 'hybrid', or 'moo'.
        """
        targets = model.targets
        
        coupled_targets = [
            self._extract_scalar(targets.scv_a) is not None,
            self._extract_scalar(targets.scv_p) is not None,
            self._extract_scalar(targets.ddt) is not None,
            len(targets.rho_bottleneck) > 0,
            targets.load_cv is not None,
        ]
        
        n_coupled = sum(coupled_targets)
        
        has_difficult = any([
            targets.load_cv is not None and (targets.load_cv < 0.1 or targets.load_cv > 0.3),
            self._extract_scalar(targets.ddt) is not None and self._extract_scalar(targets.ddt) < 1.3,
            self._extract_scalar(targets.rho_global) is not None and self._extract_scalar(targets.rho_global) > 0.88,
            len(targets.rho_bottleneck) > 1,
        ])
        
        if n_coupled >= 4:
            mode = 'hybrid'
            reason = f"{n_coupled} coupled targets; Hybrid mode recommended"
        elif n_coupled >= 3 and has_difficult:
            mode = 'hybrid'
            reason = "Multiple coupled targets with difficult settings; Hybrid mode recommended"
        elif has_difficult:
            mode = 'hybrid'
            reason = "Difficult targets detected; Hybrid mode recommended"
        elif n_coupled >= 2:
            mode = 'sequential'
            reason = "Moderate complexity; Sequential mode is sufficient"
        else:
            mode = 'sequential'
            reason = "Simple configuration; Sequential mode is sufficient"
        
        logger.info(f"Suggested calibration mode: {mode} ({reason})")
        
        return mode
    
    def suggest_hybrid_params(self, model: InputModel) -> Dict[str, int]:
        """Recommend parameter defaults for hybrid calibration.

        Args:
            model: Input configuration model.

        Returns:
            Parameter dictionary with ``population_size`` and ``n_generations``.
        """
        targets = model.targets
        
        base_pop = 80
        base_gen = 100
        
        if targets.load_cv is not None:
            base_pop += 20
            base_gen += 20
        
        if targets.rho_bottleneck:
            n_bn = len(targets.rho_bottleneck)
            base_pop += n_bn * 10
            base_gen += n_bn * 10
        
        pop_size = min(base_pop, 120)
        n_gen = min(base_gen, 150)
        
        logger.info(
            f"Suggested Hybrid parameters: population={pop_size}, generations={n_gen}"
        )
        
        return {
            'population_size': pop_size,
            'n_generations': n_gen
        }
