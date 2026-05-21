"""
Impact Analysis with LLM
Analyzes how modifying metrics affects instance difficulty
"""

import json
import os
import time
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path
from openai import OpenAI
from loguru import logger


def _build_impact_prompt(
    baseline_info: Dict[str, Any],
    modifications: Dict[str, float],
    original_metrics: Dict[str, float],
    modified_metrics: Dict[str, float]
) -> list:
    """
    Build prompt for LLM to analyze impact of metric modifications.
    """
    # System prompt
    system_prompt = """You are an expert advisor for dynamic job shop scheduling (DJSS) systems.

Your task is to analyze the user's modifications to a benchmark configuration and
predict how these changes will affect system performance and scheduling difficulty.

Key metric definitions:
- rho_global: overall machine utilization (0–1); higher values mean more congestion
- scv_a: squared coefficient of variation of inter-arrival times; reflects arrival irregularity
- scv_p: squared coefficient of variation of processing times; reflects processing uncertainty
- ddt: due-date tightness (>1); smaller values mean tighter due dates
- disturbance: proportion of machine downtime disturbances (0–1)
- rho_bottleneck: target utilization of bottleneck operations

Analysis focus:
1. Direction of change: does each metric increase or decrease?
2. Difficulty impact: will the change make scheduling harder or easier?
3. Metric coupling: how might the modifications affect other metrics?
4. Practical meaning: what does this imply for a real production system?
5. Recommendations: are the changes reasonable, and what risks exist?

Output requirements:
- Use English.
- Provide in-depth yet easy-to-understand analysis.
- Give concrete predictions of the impact.
- Clearly call out any risks.
- Keep the length around 300–500 words."""

    # Build user prompt
    config_name = baseline_info.get('name', 'Unknown configuration')
    config_desc = baseline_info.get('description', '')
    original_vals = baseline_info.get('metrics', original_metrics)
    
    user_prompt = f"""# Baseline configuration

**Configuration name**: {config_name}
**Description**: {config_desc}

**Original metrics**:
"""
    
    for metric, value in sorted(original_vals.items()):
        user_prompt += f"\n- {metric}: {value}"
    
    user_prompt += "\n\n---\n\n# User modifications\n\n"
    
    for metric, new_value in sorted(modifications.items()):
        old_value = original_vals.get(metric, "N/A")
        if isinstance(old_value, (int, float)):
            change = new_value - old_value
            pct_change = (change / old_value * 100) if old_value > 0 else 0
            direction = "increase" if change > 0 else "decrease"
            user_prompt += (
                f"- **{metric}**: {old_value} → {new_value} "
                f"({direction} {abs(pct_change):.1f}%)\n"
            )
        else:
            user_prompt += f"- **{metric}**: {old_value} → {new_value}\n"
    
    # Add baseline calibration info if available
    if 'calibration_results' in baseline_info:
        calib = baseline_info['calibration_results']
        user_prompt += "\n\n**Baseline calibration results**:\n"
        user_prompt += (
            "- Convergence status: "
            f"{'converged' if calib.get('converged') else 'reached maximum iterations'}\n"
        )
        user_prompt += f"- Mean error: {calib.get('mean_error', 0):.2f}%\n"
        user_prompt += (
            f"- Pareto front size: {calib.get('pareto_front_size', 0)} solutions\n"
        )
    
    user_prompt += (
        "\n\n---\n\nPlease analyze the impact of these modifications on "
        "system performance and scheduling difficulty."
    )
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def _call_llm_chatanywhere(messages: list) -> str:
    """
    Call ChatAnywhere GPT-4o-mini API with simple retry logic.
    """
    api_key = os.getenv("OPENAI_API_KEY", "sk-y0MnhSWH7QZTgOB2uwjMTd3FnS1jSxeqlKEz2TdWeo8c6QGJ")
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
                timeout=120
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
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"All {max_retries} LLM call attempts failed")
                raise


def generate_impact_analysis(
    baseline_info: Dict[str, Any],
    modifications: Dict[str, float],
    original_metrics: Dict[str, float],
    modified_metrics: Optional[Dict[str, float]] = None
) -> str:
    """
    Generate natural language impact analysis using LLM.
    
    Args:
        baseline_info: Information about the baseline configuration
        modifications: Dict of metric modifications {metric_name: new_value}
        original_metrics: Original metric values
        modified_metrics: Observed metrics after modification (optional)
        
    Returns:
        Natural language impact analysis in Chinese
    """
    # Build prompt
    messages = _build_impact_prompt(
        baseline_info,
        modifications,
        original_metrics,
        modified_metrics or {}
    )
    
    # Log prompt for debugging
    logger.debug("=" * 80)
    logger.debug("LLM Prompt:")
    logger.debug(json.dumps(messages, ensure_ascii=False, indent=2))
    logger.debug("=" * 80)
    
    # Call LLM
    try:
        analysis_text = _call_llm_chatanywhere(messages)
        return analysis_text
    except Exception as e:
        logger.warning(f"LLM call failed, using fallback: {e}")
        return _generate_fallback_analysis(baseline_info, modifications, original_metrics)


def _generate_fallback_analysis(
    baseline_info: Dict[str, Any],
    modifications: Dict[str, float],
    original_metrics: Dict[str, float]
) -> str:
    """
    Generate rule-based analysis when LLM is unavailable.
    """
    lines = ["# Impact analysis (rule based)", ""]
    
    config_name = baseline_info.get('name', 'Unknown configuration')
    lines.append(f"## Baseline configuration: {config_name}")
    lines.append("")
    
    lines.append("## Modifications:")
    for metric, new_value in sorted(modifications.items()):
        old_value = original_metrics.get(metric, 0)
        change = new_value - old_value
        if abs(change) > 0.001:
            direction = "increase" if change > 0 else "decrease"
            lines.append(f"- {metric}: {old_value} → {new_value} ({direction})")
            
            # Simple rule-based analysis
            if metric == "rho_global":
                if change > 0:
                    lines.append(
                        "  → Higher utilization increases congestion and "
                        "scheduling difficulty."
                    )
                else:
                    lines.append(
                        "  → Lower utilization reduces system pressure and "
                        "scheduling difficulty."
                    )
            elif metric in ["scv_a", "scv_p"]:
                if change > 0:
                    lines.append(
                        "  → Higher variability increases uncertainty and "
                        "scheduling difficulty."
                    )
                else:
                    lines.append(
                        "  → Lower variability reduces uncertainty and "
                        "scheduling difficulty."
                    )
            elif metric == "ddt":
                if change < 0:
                    lines.append(
                        "  → Tighter due dates increase time pressure and "
                        "scheduling difficulty."
                    )
                else:
                    lines.append(
                        "  → Looser due dates reduce time pressure and "
                        "scheduling difficulty."
                    )
            elif metric == "disturbance":
                if change > 0:
                    lines.append(
                        "  → Higher disturbance rates increase dynamism and "
                        "scheduling difficulty."
                    )
                else:
                    lines.append(
                        "  → Lower disturbance rates reduce disruptions and "
                        "scheduling difficulty."
                    )
    
    return "\n".join(lines)

