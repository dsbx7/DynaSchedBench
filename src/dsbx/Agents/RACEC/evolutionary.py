"""Evolutionary operators for RACEC: LLM-based crossover and mutation."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from loguru import logger

from dsbx.Agents.utils.llm_client import LLMClient
from .compile import compile_optimized_priority
from .config import LLMCoderConfig
from .population import add_genealogy_to_rule, create_genealogy_info
from .rules import RuleWithMeta


class EvolutionaryOperator:
    """Base class for evolutionary operators."""
    
    def __init__(self, llm_client: LLMClient, cfg: LLMCoderConfig):
        """Initialize evolutionary operator.
        
        Args:
            llm_client: LLM client for generating offspring
            cfg: Configuration for LLM calls and evolutionary parameters
        """
        self._client = llm_client
        self._cfg = cfg
    
    def apply(
        self,
        parents: List[RuleWithMeta],
        context: Dict[str, Any]
    ) -> Optional[RuleWithMeta]:
        """Apply operator and return offspring rule.
        
        Args:
            parents: List of parent rules (1 for mutation, 2 for crossover)
            context: Context dict with model_summary, objective_metric, etc.
        
        Returns:
            Offspring rule or None if generation fails
        """
        raise NotImplementedError("Subclasses must implement apply method")
    
    def _format_evaluation(self, eval_summary: Dict[str, Any]) -> str:
        """Format evaluation summary for prompt.
        
        Args:
            eval_summary: Evaluation summary dict
        
        Returns:
            Formatted string
        """
        if not eval_summary:
            return "No evaluation data"
        
        parts = []
        for key, value in eval_summary.items():
            if isinstance(value, (int, float)) and value is not None:
                parts.append(f"{key}={value:.4f}")
            else:
                parts.append(f"{key}={value}")
        
        return ", ".join(parts) if parts else "No evaluation data"

    def _extract_eval_summary(self, rule: RuleWithMeta) -> Dict[str, Any]:
        """Extract a compact evaluation/performance summary from rule.info.

        Priority:
        - info['eval'] if present (baseline_value/candidate_value/relative_improvement/...)
        - else info['performance'] (mean_fitness/last_fitness/num_evaluations/...)
        """
        try:
            info = getattr(rule, "info", {}) or {}
        except Exception:
            info = {}

        ev = info.get("eval")
        if isinstance(ev, dict) and ev:
            out: Dict[str, Any] = {}
            for k in [
                "baseline_value",
                "candidate_value",
                "relative_improvement",
                "episodes_used",
                "effect_size",
                "accepted",
            ]:
                if k in ev:
                    out[k] = ev.get(k)
            return out if out else dict(ev)

        perf = info.get("performance")
        if isinstance(perf, dict) and perf:
            out2: Dict[str, Any] = {}
            for k in ["mean_fitness", "last_fitness", "num_evaluations", "success_rate"]:
                if k in perf:
                    out2[k] = perf.get(k)
            return out2 if out2 else dict(perf)

        return {}

    def _format_complexity(self, complexity: Any) -> str:
        if complexity is None:
            return "unknown"
        if isinstance(complexity, (int, float)):
            try:
                return f"{float(complexity):.4f}"
            except Exception:
                return str(complexity)
        if isinstance(complexity, dict):
            try:
                return json.dumps(complexity, ensure_ascii=False)
            except Exception:
                return str(complexity)
        return str(complexity)

    def _parse_and_compile_offspring(
        self,
        response: str,
        parents: List[RuleWithMeta],
        context: Dict[str, Any],
        operation: str,
    ) -> Optional[RuleWithMeta]:
        """Parse and compile offspring from LLM response.

        Best-effort: strip markdown fences / stray braces and retry compile once
        on SyntaxError.
        """

        if not response or not response.strip():
            logger.warning("_parse_and_compile_offspring: empty response from LLM")
            return None

        try:
            response_clean = response.strip()

            if "```json" in response_clean:
                start = response_clean.find("```json") + 7
                end = response_clean.find("```", start)
                if end > start:
                    response_clean = response_clean[start:end].strip()
            elif "```" in response_clean:
                start = response_clean.find("```") + 3
                end = response_clean.find("```", start)
                if end > start:
                    response_clean = response_clean[start:end].strip()

            try:
                data = json.loads(response_clean)
            except json.JSONDecodeError as exc:
                data = None
                json_str = _extract_first_json_object(response_clean)
                if json_str:
                    try:
                        data = json.loads(json_str)
                    except Exception:
                        data = None
                if not isinstance(data, dict):
                    logger.debug("_parse_and_compile_offspring: failed to parse JSON: {}", exc)
                    logger.debug("_parse_and_compile_offspring: response was: {}", response_clean[:200])
                    return None

            code = data.get("code")
            if not code:
                logger.debug("_parse_and_compile_offspring: no 'code' field in LLM response")
                return None
            if not isinstance(code, str) or not code.strip():
                logger.debug("_parse_and_compile_offspring: 'code' field is empty or invalid")
                return None

            code = _sanitize_generated_code(code)

            try:
                if "\\\"" in code or "\\\'" in code:
                    code = code.replace("\\\"", "\"").replace("\\\'", "'")
            except Exception:
                pass

            try:
                rule_func = compile_optimized_priority(code)
            except SyntaxError as exc:
                code2 = _sanitize_generated_code(code)
                try:
                    rule_func = compile_optimized_priority(code2)
                    code = code2
                except Exception:
                    logger.warning("_parse_and_compile_offspring: syntax error in generated code: {}", exc)
                    logger.debug("_parse_and_compile_offspring: code was: {}", code[:200])
                    return None
            except Exception as exc:
                logger.error("_parse_and_compile_offspring: compilation error: {}", exc)
                return None

            if rule_func is None:
                logger.warning("_parse_and_compile_offspring: compile_optimized_priority returned None")
                return None

            parent_ids = []
            for p in parents:
                try:
                    pid = p.info.get("genealogy", {}).get("rule_id", "")
                    if pid:
                        parent_ids.append(pid)
                except Exception:
                    pass

            generation = 0
            try:
                generation = max(
                    p.info.get("genealogy", {}).get("generation", 0) for p in parents
                ) + 1
            except Exception:
                generation = 1

            genealogy = create_genealogy_info(
                operation=operation,
                generation=generation,
                parent_ids=parent_ids,
            )

            offspring = RuleWithMeta(
                rule=rule_func,
                name=f"{operation}_offspring",
                version=0,
                info={
                    "code": code,
                    "operation": operation,
                    "parent_ids": parent_ids,
                    "genealogy": genealogy.to_dict(),
                    "strategy_type": operation,
                },
            )

            from .repository import generate_unique_rule_name

            unique_name = generate_unique_rule_name(offspring)
            offspring.name = unique_name
            logger.debug(
                "_parse_and_compile_offspring: generated unique name '{}' for {} offspring",
                unique_name,
                operation,
            )
            return offspring

        except Exception as exc:
            logger.error("_parse_and_compile_offspring: unexpected error: {}", exc)
            return None


def _sanitize_generated_code(code: str) -> str:
    s = str(code or "").strip()
    if s.startswith("```"):
        parts = s.split("\n")
        if parts:
            parts = parts[1:]
        s2 = "\n".join(parts)
        if "```" in s2:
            s2 = s2.rsplit("```", 1)[0]
        s = s2.strip()
    lines = s.splitlines()
    while lines and lines[-1].strip() in ("}", "```"):
        lines.pop()
    return "\n".join(lines).strip()


def _extract_first_json_object(text: str) -> Optional[str]:
    s = str(text or "")
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


CROSSOVER_PROMPT_TEMPLATE = """
You are an expert in evolutionary algorithm design for scheduling systems.

Your task is to perform CROSSOVER between two parent scheduling rules to create an offspring rule that combines the best features of both parents.

Parent 1: {parent1_name}
Evaluation: {parent1_eval}
Complexity: {parent1_complexity}
Code:
```python
{parent1_code}
```

Parent 2: {parent2_name}
Evaluation: {parent2_eval}
Complexity: {parent2_complexity}
Code:
```python
{parent2_code}
```

Objective: Optimize {objective_metric} (mode: {objective_mode})

Hard Constraints (must follow exactly):
1. Output code must define ONLY: def optimized_priority(obs, action, env) -> float
   - You may optionally include: import math
   - Do not include any other top-level statements.
2. Allowed helpers available at runtime:
   - _safe_float(x, default=0.0)
   - _find_ready_op(obs, job_id, machine_group, allow_fallback_any_group=False)
   - math
3. Allowed builtins:
   abs, min, max, sum, len, ord, chr, float, int, str, range, enumerate, sorted, zip,
   isinstance, set, list, dict, tuple, all, any, bool, round, getattr, hasattr, Exception
4. Forbidden:
   - Any imports except math
   - File/network/system access, subprocess, os, sys, socket
   - eval/exec/compile/open/input/print
   - randomness (random, numpy.random)

Crossover Guidelines:
1. Identify complementary features from both parents
2. Combine features that address different aspects of the scheduling problem
3. Maintain syntactic correctness and the required function signature
4. Aim for a complexity level between the two parents
5. Preserve the best-performing logic from each parent

Output Format:
You must reply with a single JSON object:
{{"code": "def optimized_priority(obs, action, env) -> float:\\n    ..."}}

Do NOT include explanations, comments, or markdown fences outside the JSON.
"""


class CrossoverOperator(EvolutionaryOperator):
    """LLM-based crossover between two parent rules."""
    
    def apply(
        self,
        parents: List[RuleWithMeta],
        context: Dict[str, Any]
    ) -> Optional[RuleWithMeta]:
        """Generate offspring by combining features from two parents.
        
        Args:
            parents: List of exactly 2 parent rules
            context: Dict with model_summary, objective_metric, etc.
            
        Returns:
            Offspring rule or None if generation fails
        """
        if len(parents) != 2:
            logger.warning("CrossoverOperator requires exactly 2 parents, got {}", len(parents))
            return None
        
        try:
            # Log parent information
            logger.info(
                "CrossoverOperator: starting crossover between parents '{}' and '{}'",
                parents[0].name,
                parents[1].name
            )
            
            # Log parent codes
            parent1_code = parents[0].info.get("code", "# No code available")
            parent2_code = parents[1].info.get("code", "# No code available")
            
            logger.debug(
                "CrossoverOperator: Parent 1 ('{}') code:\n{}\n<<END_PARENT1_CODE>>",
                parents[0].name,
                parent1_code
            )
            logger.debug(
                "CrossoverOperator: Parent 2 ('{}') code:\n{}\n<<END_PARENT2_CODE>>",
                parents[1].name,
                parent2_code
            )
            
            # Build crossover prompt
            prompt = self._build_crossover_prompt(parents, context)
            
            # Log the prompt
            logger.debug(
                "CrossoverOperator: Crossover prompt:\n{}\n<<END_CROSSOVER_PROMPT>>",
                prompt
            )
            
            # Call LLM with timeout handling
            temperature = getattr(self._cfg, "evolution_temperature", 0.7)
            timeout = getattr(self._cfg, "llm_timeout", 9999.0)
            retries = int(getattr(self._cfg, "evolution_generation_retries", 2) or 2)
            max_attempts = max(1, retries + 1)

            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    responses = self._client.generate(
                        prompt=prompt,
                        n=1,
                        temperature=temperature,
                        timeout=timeout,
                    )
                except TimeoutError as exc:
                    last_exc = exc
                    logger.warning(
                        "CrossoverOperator: LLM call timed out after {}s (attempt {}/{}): {}",
                        timeout,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    continue
                except Exception as exc:
                    last_exc = exc
                    logger.error(
                        "CrossoverOperator: LLM call failed (attempt {}/{}): {}",
                        attempt,
                        max_attempts,
                        exc,
                    )
                    continue

                if not responses:
                    logger.warning(
                        "CrossoverOperator: LLM returned no responses (attempt {}/{})",
                        attempt,
                        max_attempts,
                    )
                    continue

                logger.debug(
                    "CrossoverOperator: LLM response:\n{}\n<<END_CROSSOVER_RESPONSE>>",
                    responses[0],
                )

                offspring = self._parse_and_compile_offspring(
                    responses[0],
                    parents,
                    context,
                    operation="crossover",
                )

                if offspring is None:
                    if attempt < max_attempts:
                        logger.debug(
                            "CrossoverOperator: failed to parse/compile offspring from parents '{}' and '{}' (attempt {}/{})",
                            parents[0].name,
                            parents[1].name,
                            attempt,
                            max_attempts,
                        )
                    else:
                        logger.warning(
                            "CrossoverOperator: failed to parse/compile offspring from parents '{}' and '{}' (attempt {}/{})",
                            parents[0].name,
                            parents[1].name,
                            attempt,
                            max_attempts,
                        )
                    continue

                offspring_code = offspring.info.get("code", "# No code available")
                logger.debug(
                    "CrossoverOperator: Offspring code:\n{}\n<<END_OFFSPRING_CODE>>",
                    offspring_code,
                )
                logger.info(
                    "CrossoverOperator: successfully created offspring from parents '{}' and '{}'",
                    parents[0].name,
                    parents[1].name,
                )
                return offspring

            if last_exc is not None:
                logger.warning(
                    "CrossoverOperator: giving up after {} attempts due to LLM errors (last_error={})",
                    max_attempts,
                    last_exc,
                )
            return None
            
        except Exception as exc:
            logger.error("CrossoverOperator failed with unexpected error: {}", exc)
            return None
    
    def _build_crossover_prompt(
        self,
        parents: List[RuleWithMeta],
        context: Dict[str, Any]
    ) -> str:
        """Build crossover prompt from parents and context.
        
        Args:
            parents: List of 2 parent rules
            context: Context dict
        
        Returns:
            Formatted prompt string
        """
        parent1, parent2 = parents
        
        # Extract parent information
        parent1_code = parent1.info.get("code", "# No code available")
        parent2_code = parent2.info.get("code", "# No code available")
        
        parent1_eval = self._format_evaluation(self._extract_eval_summary(parent1))
        parent2_eval = self._format_evaluation(self._extract_eval_summary(parent2))
        
        parent1_complexity = self._format_complexity(parent1.info.get("complexity", None))
        parent2_complexity = self._format_complexity(parent2.info.get("complexity", None))
        
        # Get objective information
        objective_metric = context.get("objective_metric", "makespan")
        objective_mode = context.get("objective_mode", "min")
        
        # Format prompt
        prompt = CROSSOVER_PROMPT_TEMPLATE.format(
            parent1_name=parent1.name,
            parent1_eval=parent1_eval,
            parent1_complexity=parent1_complexity,
            parent1_code=parent1_code,
            parent2_name=parent2.name,
            parent2_eval=parent2_eval,
            parent2_complexity=parent2_complexity,
            parent2_code=parent2_code,
            objective_metric=objective_metric,
            objective_mode=objective_mode
        )
        
        return prompt


MUTATION_PROMPT_TEMPLATE = """
You are an expert in evolutionary algorithm design for scheduling systems.

Your task is to perform MUTATION on a scheduling rule to create a modified version with controlled variations.

Parent Rule: {parent_name}
Evaluation: {parent_eval}
Complexity: {parent_complexity}
Identified Weaknesses: {weaknesses}
Code:
```python
{parent_code}
```

Objective: Optimize {objective_metric} (mode: {objective_mode})

Hard Constraints (must follow exactly):
1. Output code must define ONLY: def optimized_priority(obs, action, env) -> float
   - You may optionally include: import math
   - Do not include any other top-level statements.
2. Allowed helpers available at runtime:
   - _safe_float(x, default=0.0)
   - _find_ready_op(obs, job_id, machine_group, allow_fallback_any_group=False)
   - math
3. Allowed builtins:
   abs, min, max, sum, len, ord, chr, float, int, str, range, enumerate, sorted, zip,
   isinstance, set, list, dict, tuple, all, any, bool, round, getattr, hasattr, Exception
4. Forbidden:
   - Any imports except math
   - File/network/system access, subprocess, os, sys, socket
   - eval/exec/compile/open/input/print
   - randomness (random, numpy.random)

Mutation Guidelines:
1. Introduce meaningful variations that address identified weaknesses
2. Maintain the core structure and logic of the parent
3. Consider adjusting weights, thresholds, or feature combinations
4. Preserve syntactic correctness and the required function signature
5. Aim for similar or slightly lower complexity

Mutation Strategies:
- Adjust numerical constants (weights, thresholds)
- Add or remove minor features
- Change operator precedence or combinations
- Modify conditional logic slightly

Output Format:
You must reply with a single JSON object:
{{"code": "def optimized_priority(obs, action, env) -> float:\\n    ..."}}

Do NOT include explanations, comments, or markdown fences outside the JSON.
"""


class MutationOperator(EvolutionaryOperator):
    """LLM-based mutation of a single rule."""
    
    def apply(
        self,
        parents: List[RuleWithMeta],
        context: Dict[str, Any]
    ) -> Optional[RuleWithMeta]:
        """Generate mutated version of parent rule.
        
        Args:
            parents: List of exactly 1 parent rule
            context: Dict with model_summary, objective_metric, etc.
            
        Returns:
            Mutated rule or None if generation fails
        """
        if len(parents) != 1:
            logger.warning("MutationOperator requires exactly 1 parent, got {}", len(parents))
            return None
        
        try:
            # Log parent information
            logger.info(
                "MutationOperator: starting mutation of parent '{}'",
                parents[0].name
            )
            
            # Log parent code
            parent_code = parents[0].info.get("code", "# No code available")
            logger.debug(
                "MutationOperator: Parent ('{}') code:\n{}\n<<END_PARENT_CODE>>",
                parents[0].name,
                parent_code
            )
            
            # Build mutation prompt
            prompt = self._build_mutation_prompt(parents[0], context)
            
            # Log the prompt
            logger.debug(
                "MutationOperator: Mutation prompt:\n{}\n<<END_MUTATION_PROMPT>>",
                prompt
            )
            
            # Call LLM with timeout handling
            temperature = getattr(self._cfg, "evolution_temperature", 0.7)
            timeout = getattr(self._cfg, "llm_timeout", 9999.0)
            retries = int(getattr(self._cfg, "evolution_generation_retries", 2) or 2)
            max_attempts = max(1, retries + 1)

            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    responses = self._client.generate(
                        prompt=prompt,
                        n=1,
                        temperature=temperature,
                        timeout=timeout,
                    )
                except TimeoutError as exc:
                    last_exc = exc
                    logger.warning(
                        "MutationOperator: LLM call timed out after {}s (attempt {}/{}): {}",
                        timeout,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    continue
                except Exception as exc:
                    last_exc = exc
                    logger.error(
                        "MutationOperator: LLM call failed (attempt {}/{}): {}",
                        attempt,
                        max_attempts,
                        exc,
                    )
                    continue

                if not responses:
                    logger.warning(
                        "MutationOperator: LLM returned no responses (attempt {}/{})",
                        attempt,
                        max_attempts,
                    )
                    continue

                logger.debug(
                    "MutationOperator: LLM response:\n{}\n<<END_MUTATION_RESPONSE>>",
                    responses[0],
                )

                offspring = self._parse_and_compile_offspring(
                    responses[0],
                    parents,
                    context,
                    operation="mutation",
                )

                if offspring is None:
                    if attempt < max_attempts:
                        logger.debug(
                            "MutationOperator: failed to parse/compile offspring from parent '{}' (attempt {}/{})",
                            parents[0].name,
                            attempt,
                            max_attempts,
                        )
                    else:
                        logger.warning(
                            "MutationOperator: failed to parse/compile offspring from parent '{}' (attempt {}/{})",
                            parents[0].name,
                            attempt,
                            max_attempts,
                        )
                    continue

                offspring_code = offspring.info.get("code", "# No code available")
                logger.debug(
                    "MutationOperator: Offspring code:\n{}\n<<END_OFFSPRING_CODE>>",
                    offspring_code,
                )
                logger.info(
                    "MutationOperator: successfully created offspring from parent '{}'",
                    parents[0].name,
                )
                return offspring

            if last_exc is not None:
                logger.warning(
                    "MutationOperator: giving up after {} attempts due to LLM errors (last_error={})",
                    max_attempts,
                    last_exc,
                )
            return None
            
        except Exception as exc:
            logger.error("MutationOperator failed with unexpected error: {}", exc)
            return None
    
    def _build_mutation_prompt(
        self,
        parent: RuleWithMeta,
        context: Dict[str, Any]
    ) -> str:
        """Build mutation prompt from parent and context.
        
        Args:
            parent: Parent rule
            context: Context dict
        
        Returns:
            Formatted prompt string
        """
        # Extract parent information
        parent_code = parent.info.get("code", "# No code available")
        parent_eval = self._format_evaluation(self._extract_eval_summary(parent))
        parent_complexity = self._format_complexity(parent.info.get("complexity", None))
        
        # Get objective information
        objective_metric = context.get("objective_metric", "makespan")
        objective_mode = context.get("objective_mode", "min")
        
        # Identify weaknesses
        weaknesses = context.get("weaknesses", "No specific weaknesses identified")
        if not weaknesses or weaknesses == "No specific weaknesses identified":
            weaknesses = self._identify_weaknesses(parent, context)
        
        # Format prompt
        prompt = MUTATION_PROMPT_TEMPLATE.format(
            parent_name=parent.name,
            parent_eval=parent_eval,
            parent_complexity=parent_complexity,
            weaknesses=weaknesses,
            parent_code=parent_code,
            objective_metric=objective_metric,
            objective_mode=objective_mode
        )
        
        return prompt
    
    def _identify_weaknesses(
        self,
        parent: RuleWithMeta,
        context: Dict[str, Any]
    ) -> str:
        """Identify weaknesses in parent rule for mutation guidance.
        
        Args:
            parent: Parent rule
            context: Context dict
        
        Returns:
            String describing weaknesses
        """
        weaknesses = []
        
        # Check evaluation metrics
        eval_summary = self._extract_eval_summary(parent)
        if eval_summary:
            # If we have a relative improvement and it's non-positive, mark as weakness.
            try:
                ri = eval_summary.get("relative_improvement", None)
                if ri is not None and float(ri) <= 0.0:
                    weaknesses.append("Observed relative_improvement is non-positive")
            except Exception:
                pass
            # If we only have performance stats, we can still nudge exploration.
            if "mean_fitness" in eval_summary and "relative_improvement" not in eval_summary:
                weaknesses.append("No direct eval summary; consider re-evaluating on current instance")
        
        # Check complexity
        complexity = parent.info.get("complexity", 0)
        if isinstance(complexity, dict):
            complexity_val = complexity.get("complexity_score")
        else:
            complexity_val = complexity
        try:
            if isinstance(complexity_val, (int, float)) and float(complexity_val) > 50:
                weaknesses.append("High complexity may impact runtime performance")
        except Exception:
            pass
        
        # Generic weakness if none identified
        if not weaknesses:
            weaknesses.append("Consider exploring alternative feature combinations")
        
        return "; ".join(weaknesses)
