"""Rule summarization for evolutionary operators in RACEC.

This module provides functionality to create concise summaries of scheduling rules
for use in Planner prompts, enabling informed decisions about crossover and mutation
without overwhelming the context window.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from .rules import RuleWithMeta


def extract_fitness_from_info(info: Any) -> Optional[float]:
    if not isinstance(info, dict):
        return None

    eval_info = info.get("eval")
    if isinstance(eval_info, dict) and eval_info:
        v = eval_info.get("relative_improvement")
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    perf = info.get("performance")
    if isinstance(perf, dict) and perf:
        for k in ("mean_fitness", "last_fitness"):
            v = perf.get(k)
            try:
                if v is None:
                    continue
                return float(v)
            except Exception:
                continue

    v = info.get("fitness")
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def extract_strategy_features(code: str) -> List[str]:
    """Extract high-level strategy features from rule code.
    
    Analyzes the code to identify key scheduling concepts and approaches.
    
    Args:
        code: Python code string for the rule
        
    Returns:
        List of feature tags describing the strategy
    """
    features = []
    
    if not code or not isinstance(code, str):
        return features
    
    code_lower = code.lower()
    
    # Time-based features
    if 'remaining_work' in code_lower or 'rem_work' in code_lower:
        features.append('remaining-work-aware')
    if 'remaining_ops' in code_lower or 'rem_ops' in code_lower:
        features.append('remaining-ops-aware')
    if 'process_time' in code_lower or 'proc_time' in code_lower:
        features.append('process-time-based')
    if 'slack' in code_lower:
        features.append('slack-time-aware')
    if 'due' in code_lower or 'deadline' in code_lower:
        features.append('due-date-aware')
    
    # Machine-based features
    if 'machine' in code_lower and ('available' in code_lower or 'idle' in code_lower):
        features.append('machine-availability-aware')
    if 'utilization' in code_lower or 'load' in code_lower:
        features.append('load-balancing')
    if 'bottleneck' in code_lower:
        features.append('bottleneck-aware')
    
    # Job-based features
    if 'priority' in code_lower:
        features.append('priority-based')
    if 'emergency' in code_lower:
        features.append('emergency-handling')
    if 'flexibility' in code_lower or 'flex' in code_lower:
        features.append('flexibility-aware')
    if 'critical' in code_lower:
        features.append('critical-path-based')
    
    # Queue-based features
    if 'queue' in code_lower or 'wip' in code_lower:
        features.append('queue-aware')
    if 'waiting' in code_lower:
        features.append('waiting-time-aware')
    
    # Advanced features
    if 'lookahead' in code_lower or 'future' in code_lower:
        features.append('lookahead')
    if 'balance' in code_lower:
        features.append('balanced-approach')
    if 'weighted' in code_lower or 'weight' in code_lower:
        features.append('weighted-combination')
    
    # Heuristic patterns
    if 'spt' in code_lower or 'shortest' in code_lower:
        features.append('SPT-like')
    if 'lpt' in code_lower or 'longest' in code_lower:
        features.append('LPT-like')
    if 'edd' in code_lower or 'earliest' in code_lower:
        features.append('EDD-like')
    if 'fifo' in code_lower or 'first' in code_lower:
        features.append('FIFO-like')
    
    return features


def extract_core_logic(code: str, max_lines: int = 10) -> str:
    """Extract the core priority computation logic from rule code.
    
    Attempts to find and extract the main priority calculation,
    typically in a function like compute_priority or similar.
    
    Args:
        code: Python code string for the rule
        max_lines: Maximum number of lines to extract
        
    Returns:
        Extracted core logic as a string
    """
    if not code or not isinstance(code, str):
        return ""
    
    try:
        # Try to parse as AST
        tree = ast.parse(code)
        
        # Look for priority computation function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_name = node.name.lower()
                if 'priority' in func_name or 'score' in func_name or 'compute' in func_name:
                    # Extract function body
                    lines = code.split('\n')
                    start_line = node.lineno - 1
                    end_line = min(start_line + max_lines, node.end_lineno if hasattr(node, 'end_lineno') else len(lines))
                    
                    extracted = '\n'.join(lines[start_line:end_line])
                    if len(lines[start_line:end_line]) < (node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else max_lines):
                        extracted += '\n    # ... (truncated)'
                    
                    return extracted
    except Exception as exc:
        logger.debug("extract_core_logic: failed to parse AST: {}", exc)
    
    # Fallback: extract first few lines that look like computation
    lines = code.split('\n')
    core_lines = []
    in_function = False
    
    for line in lines:
        stripped = line.strip()
        
        # Start of function
        if stripped.startswith('def ') and ('priority' in stripped.lower() or 'score' in stripped.lower()):
            in_function = True
            core_lines.append(line)
            continue
        
        # Inside function
        if in_function:
            core_lines.append(line)
            if len(core_lines) >= max_lines:
                core_lines.append('    # ... (truncated)')
                break
            
            # End of function (dedent)
            if stripped and not line.startswith(' ') and not line.startswith('\t'):
                break
    
    return '\n'.join(core_lines) if core_lines else code[:500]


def summarize_rule(rule: RuleWithMeta, include_code_snippet: bool = False) -> Dict[str, Any]:
    """Create a concise summary of a scheduling rule.
    
    Args:
        rule: Rule with metadata to summarize
        include_code_snippet: Whether to include a code snippet (increases token usage)
        
    Returns:
        Dictionary containing rule summary
    """
    summary = {
        "name": rule.name,
        "rule_id": None,
        "fitness": None,
        "relative_improvement": None,
        "features": [],
        "description": None,
        "generation": 0,
        "operation": "unknown",
    }
    
    try:
        info = getattr(rule, "info", {}) or {}
        
        # Extract rule ID
        genealogy = info.get("genealogy", {})
        if isinstance(genealogy, dict):
            summary["rule_id"] = genealogy.get("rule_id", rule.name)
            summary["generation"] = genealogy.get("generation", 0)
            summary["operation"] = genealogy.get("operation", "unknown")
        
        eval_info = info.get("eval", {})
        if isinstance(eval_info, dict) and eval_info:
            summary["relative_improvement"] = eval_info.get("relative_improvement")
        summary["fitness"] = extract_fitness_from_info(info)
        
        # Extract code and features
        code = info.get("code", "")
        if code:
            summary["features"] = extract_strategy_features(code)
            
            if include_code_snippet:
                summary["code_snippet"] = extract_core_logic(code, max_lines=8)
        
        # Extract or generate description
        plan_info = info.get("plan", {})
        if isinstance(plan_info, dict):
            summary["description"] = plan_info.get("description")
        
        if not summary["description"] and summary["features"]:
            # Generate description from features
            summary["description"] = f"Strategy using: {', '.join(summary['features'][:3])}"
    
    except Exception as exc:
        logger.warning("summarize_rule: error summarizing rule '{}': {}", rule.name, exc)
    
    return summary


def format_rules_for_prompt(
    rules: List[RuleWithMeta],
    max_rules: int = 10,
    include_code_snippets: bool = False,
    sort_by_fitness: bool = True
) -> str:
    """Format a list of rules as a concise text summary for LLM prompts.
    
    Args:
        rules: List of rules to summarize
        max_rules: Maximum number of rules to include
        include_code_snippets: Whether to include code snippets (increases token usage)
        sort_by_fitness: Whether to sort by fitness (best first)
        
    Returns:
        Formatted string suitable for inclusion in prompts
    """
    if not rules:
        return "No rules available in repository."
    
    # Summarize all rules
    summaries = [summarize_rule(rule, include_code_snippet=include_code_snippets) for rule in rules]
    
    # Sort by fitness if requested
    if sort_by_fitness:
        def _fitness_key(s: Dict[str, Any]) -> float:
            v = s.get("fitness")
            try:
                if v is None:
                    return float("-inf")
                return float(v)
            except Exception:
                return float("-inf")

        summaries.sort(key=_fitness_key, reverse=True)
    
    # Limit to max_rules
    summaries = summaries[:max_rules]
    
    # Format as text
    lines = []
    for i, summary in enumerate(summaries, 1):
        name = summary.get("name", "Unknown")
        rule_id = summary.get("rule_id", "N/A")
        fitness = summary.get("fitness")
        features = summary.get("features", [])
        description = summary.get("description", "No description")
        generation = summary.get("generation", 0)
        operation = summary.get("operation", "unknown")
        
        # Format fitness
        fitness_str = f"{fitness:.4f}" if fitness is not None else "N/A"
        
        # Format features (limit to top 5)
        features_str = ", ".join(features[:5]) if features else "none identified"
        
        # Build rule entry
        lines.append(f"{i}. Rule: '{name}' (ID: {rule_id})")
        lines.append(f"   Fitness: {fitness_str} | Generation: {generation} | Origin: {operation}")
        lines.append(f"   Features: {features_str}")
        if description:
            lines.append(f"   Description: {description}")
        
        # Add code snippet if requested
        if include_code_snippets and summary.get("code_snippet"):
            lines.append(f"   Core Logic:")
            for code_line in summary["code_snippet"].split('\n'):
                lines.append(f"     {code_line}")
        
        lines.append("")  # Empty line between rules
    
    return "\n".join(lines)


def create_parent_selection_guidance(
    rules: List[RuleWithMeta],
    max_suggestions: int = 3
) -> str:
    """Create guidance text for parent selection in crossover/mutation.
    
    Analyzes the rule population and suggests good parent selection strategies.
    
    Args:
        rules: List of available rules
        max_suggestions: Maximum number of suggestions to provide
        
    Returns:
        Formatted guidance text
    """
    if not rules or len(rules) < 2:
        return "Insufficient rules for crossover. Consider using 'generate' or 'mutation' strategies."
    
    # Summarize rules
    summaries = [summarize_rule(rule, include_code_snippet=False) for rule in rules]
    
    # Collect all features
    all_features = []
    for summary in summaries:
        all_features.extend(summary.get("features", []))
    
    # Count feature frequency
    from collections import Counter
    feature_counts = Counter(all_features)
    common_features = [f for f, _ in feature_counts.most_common(5)]
    
    # Find complementary pairs
    suggestions = []
    
    # Suggestion 1: High fitness + High diversity
    sorted_by_fitness = sorted(summaries, key=lambda s: s.get("fitness") or float("-inf"), reverse=True)
    if len(sorted_by_fitness) >= 2:
        best = sorted_by_fitness[0]
        best_fitness = best.get('fitness', 0)
        fitness_str = f"{best_fitness:.4f}" if best_fitness is not None else "N/A"
        suggestions.append(
            f"High-performing rules: Consider crossover between '{best['name']}' (fitness: {fitness_str}) "
            f"and other top performers to combine successful strategies."
        )
    
    # Suggestion 2: Complementary features
    if len(common_features) >= 2:
        suggestions.append(
            f"Complementary strategies: Look for rules with different feature sets. "
            f"Common features in population: {', '.join(common_features[:3])}. "
            f"Consider combining rules that balance these features differently."
        )
    
    # Suggestion 3: Mutation targets
    if sorted_by_fitness:
        best = sorted_by_fitness[0]
        suggestions.append(
            f"Mutation target: '{best['name']}' shows good performance. "
            f"Consider mutating it to explore nearby variations."
        )
    
    return "\n".join(f"- {s}" for s in suggestions[:max_suggestions])
