from __future__ import annotations

import json
import math
import time
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .rules import RuleWithMeta
from .compile import compile_optimized_priority
from .population import GenealogyInfo, generate_rule_id
from .diversity import compute_combined_diversity
from .baseline_heuristics import BaselineHeuristicLibrary


# Global counter for ensuring unique rule names
_rule_name_counter = 0
_rule_name_counter_lock = threading.Lock()

def _get_next_rule_counter():
    """Get next unique counter value for rule naming."""
    global _rule_name_counter
    with _rule_name_counter_lock:
        _rule_name_counter += 1
        return _rule_name_counter


@dataclass
class PerformanceStats:
    """Performance statistics for a rule.
    
    Tracks fitness metrics using exponential moving average to give
    more weight to recent performance.
    """
    mean_fitness: float = 0.0
    std_fitness: float = 0.0
    num_evaluations: int = 0
    success_rate: float = 0.0
    last_fitness: float = 0.0
    last_evaluated: Optional[str] = None
    
    def update(self, new_fitness: float, alpha: float = 0.3) -> None:
        """Update statistics using exponential moving average.
        
        Args:
            new_fitness: New fitness value to incorporate
            alpha: Weight for new value in EMA (0 < alpha <= 1)
                  Higher alpha gives more weight to recent values
        """
        if self.num_evaluations == 0:
            # First evaluation
            self.mean_fitness = new_fitness
            self.std_fitness = 0.0
        else:
            # Exponential moving average for mean
            old_mean = self.mean_fitness
            self.mean_fitness = alpha * new_fitness + (1 - alpha) * self.mean_fitness
            
            # Update std using Welford's online algorithm adapted for EMA
            delta = new_fitness - old_mean
            delta2 = new_fitness - self.mean_fitness
            self.std_fitness = math.sqrt(
                (1 - alpha) * (self.std_fitness ** 2) + alpha * delta * delta2
            )
        
        self.num_evaluations += 1
        self.last_fitness = new_fitness
        self.last_evaluated = datetime.now().isoformat()
        
        # Update success rate (fitness > 0.0 counts as success)
        if new_fitness > 0.0:
            self.success_rate = (
                (self.success_rate * (self.num_evaluations - 1) + 1.0) 
                / self.num_evaluations
            )
        else:
            self.success_rate = (
                self.success_rate * (self.num_evaluations - 1) 
                / self.num_evaluations
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "mean_fitness": self.mean_fitness,
            "std_fitness": self.std_fitness,
            "num_evaluations": self.num_evaluations,
            "success_rate": self.success_rate,
            "last_fitness": self.last_fitness,
            "last_evaluated": self.last_evaluated,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PerformanceStats":
        """Create from dictionary."""
        return cls(
            mean_fitness=data.get("mean_fitness", 0.0),
            std_fitness=data.get("std_fitness", 0.0),
            num_evaluations=data.get("num_evaluations", 0),
            success_rate=data.get("success_rate", 0.0),
            last_fitness=data.get("last_fitness", 0.0),
            last_evaluated=data.get("last_evaluated"),
        )


@dataclass
class RuleRecord:
    """Simplified rule record for repository storage.
    
    This is the new v2 format that removes instance-specific metadata
    and focuses on essential rule information and performance tracking.
    """
    rule_id: str
    name: str
    code: str
    source: str  # "llm_generated", "crossover", "mutation", "baseline_heuristic"
    genealogy: Dict[str, Any] = field(default_factory=dict)
    performance: PerformanceStats = field(default_factory=PerformanceStats)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "code": self.code,
            "source": self.source,
            "genealogy": self.genealogy,
            "performance": self.performance.to_dict(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleRecord":
        """Create from dictionary."""
        return cls(
            rule_id=data.get("rule_id", ""),
            name=data.get("name", ""),
            code=data.get("code", ""),
            source=data.get("source", "unknown"),
            genealogy=data.get("genealogy", {}),
            performance=PerformanceStats.from_dict(data.get("performance", {})),
            metadata=data.get("metadata", {}),
        )



def generate_unique_rule_name(rule: RuleWithMeta) -> str:
    """Generate unique name based on strategy type and timestamp.
    
    Args:
        rule: Rule to generate name for
    
    Returns:
        Unique name in format "{strategy_type}_{timestamp}"
    """
    # Get strategy type from rule info
    strategy_type = "rule"  # default
    
    if hasattr(rule, "info") and isinstance(rule.info, dict):
        # Try to get from plan
        plan = rule.info.get("plan", {})
        if isinstance(plan, dict):
            st = plan.get("strategy_type")
            if st and isinstance(st, str):
                strategy_type = st.strip().lower()
        
        # Try to get from direct field (overrides plan)
        if "strategy_type" in rule.info:
            st = rule.info["strategy_type"]
            if st and isinstance(st, str):
                strategy_type = st.strip().lower()
        
        # Try to get from genealogy operation
        if strategy_type == "rule":
            genealogy = rule.info.get("genealogy", {})
            if isinstance(genealogy, dict):
                operation = genealogy.get("operation")
                if operation and isinstance(operation, str):
                    op = operation.strip().lower()
                    if op in ["crossover", "mutation", "generated"]:
                        strategy_type = "generated" if op == "generated" else op
    
    # Generate timestamp with milliseconds and counter for uniqueness
    timestamp = int(time.time() * 1000)
    counter = _get_next_rule_counter()
    
    # Format name with both timestamp and counter to ensure uniqueness
    name = f"{strategy_type}_{timestamp}_{counter}"
    
    logger.debug(
        "generate_unique_rule_name: generated name '{}' for rule with strategy_type='{}'",
        name,
        strategy_type
    )
    
    return name


class _RepoFunctionPriorityRule:
    def __init__(self, fn):
        self._fn = fn

    def __call__(self, obs: Dict[str, Any], action: Dict[str, Any], env: Any) -> float:
        try:
            v = self._fn(obs, action, env)
            if v is None:
                return 0.0
            return float(v)
        except Exception as e:  # pragma: no cover - defensive path
            logger.error(f"Repo priority function raised error: {e}")
            return 0.0


class _EnsemblePriorityRule:
    def __init__(self, members: List[Tuple[_RepoFunctionPriorityRule, float]]) -> None:
        self._members = []
        total = 0.0
        for fn, w in members:
            try:
                ww = float(w)
            except Exception:
                ww = 0.0
            if ww <= 0.0:
                continue
            self._members.append((fn, ww))
            total += ww
        self._norm = total if total > 0.0 else 0.0

    def __call__(self, obs: Dict[str, Any], action: Dict[str, Any], env: Any) -> float:
        if not self._members:
            return 0.0
        num = 0.0
        den = 0.0
        for fn, w in self._members:
            try:
                v = float(fn(obs, action, env))
            except Exception:
                continue
            num += w * v
            den += w
        if den <= 0.0:
            return 0.0
        return num / den


class RuleRepository:
    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            base = Path.cwd() / ".dyna_schedbench"
            base.mkdir(parents=True, exist_ok=True)
            self._path = base / "racec_rules.json"
        else:
            self._path = Path(path)
            if not self._path.parent.exists():
                self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[Dict[str, Any]] = []
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._load()

    def seed_baselines_if_empty(self, model_summary: Optional[Dict[str, Any]] = None) -> bool:
        """Seed baseline heuristic rules into an empty repository.

        Returns:
            True if baselines were seeded, False otherwise.
        """
        with self._lock:
            if self._records:
                return False

            baseline_names = ["ATC", "CR", "EDD", "FIFO", "LIFO", "LPT", "MST", "SPT"]
            seeded = 0
            for name in baseline_names:
                code = BaselineHeuristicLibrary.get_heuristic_code(name)
                if not isinstance(code, str) or not code.strip():
                    continue
                rid = generate_rule_id()
                ts = time.time()
                record: Dict[str, Any] = {
                    "id": rid,
                    "name": str(name),
                    "code": code,
                    "model_summary": dict(model_summary) if isinstance(model_summary, dict) else {},
                    "info": {
                        "source": "baseline_heuristic",
                        "description": f"Classic {name} scheduling heuristic",
                        "performance": {
                            "mean_fitness": 0.0,
                            "std_fitness": 0.0,
                            "num_evaluations": 0,
                            "success_rate": 0.0,
                            "last_fitness": 0.0,
                            "last_evaluated": None,
                        },
                    },
                    "genealogy": {
                        "rule_id": rid,
                        "parent_ids": [],
                        "operation": "baseline_heuristic",
                        "generation": 0,
                        "timestamp": ts,
                    },
                    "version": 0,
                    "timestamp": ts,
                }
                self._records.append(record)
                seeded += 1

            if seeded:
                self._save()
                logger.info(
                    "RuleRepository: seeded {} baseline heuristic rule(s) into empty repository '{}'",
                    seeded,
                    str(self._path),
                )
                return True
            return False

    def _load(self) -> None:
        """Load repository from disk with thread safety."""
        with self._lock:
            try:
                if self._path.is_file():
                    data = self._path.read_text(encoding="utf-8")
                    obj = json.loads(data)
                    if isinstance(obj, list):
                        self._records = obj
                    else:
                        self._records = []
                else:
                    self._records = []
            except Exception:
                self._records = []

        self._normalize_record_code_fields(prefer_top_level=True)

    def _normalize_record_code_fields(self, *, prefer_top_level: bool = True) -> None:
        """Ensure record['code'] and record['info']['code'] are consistent.

        By convention, record['code'] is treated as authoritative.
        """
        changed = 0
        for rec in self._records:
            if not isinstance(rec, dict):
                continue
            top_code = rec.get("code")
            info = rec.get("info")
            info_code = info.get("code") if isinstance(info, dict) else None

            # If top-level code is missing but info.code exists, fill top-level.
            if (not isinstance(top_code, str) or not top_code.strip()) and isinstance(info_code, str) and info_code.strip():
                rec["code"] = info_code
                top_code = info_code
                changed += 1

            # If both exist and differ, prefer top-level by default.
            if (
                isinstance(top_code, str)
                and isinstance(info, dict)
                and isinstance(info_code, str)
                and top_code.strip()
                and info_code.strip()
                and top_code != info_code
            ):
                if prefer_top_level:
                    info["code"] = top_code
                else:
                    rec["code"] = info_code
                changed += 1

            # If top-level exists but info.code missing, populate it for compatibility.
            if isinstance(top_code, str) and top_code.strip() and isinstance(info, dict):
                if not isinstance(info_code, str) or not info_code.strip():
                    info["code"] = top_code
                    changed += 1

        if changed:
            logger.debug("RuleRepository: normalized code fields for {} record(s)", changed)

    def _save(self) -> None:
        """Save repository to disk with thread safety."""
        with self._lock:
            try:
                self._normalize_record_code_fields(prefer_top_level=True)
                data = json.dumps(self._records, ensure_ascii=False, indent=2)
                self._path.write_text(data, encoding="utf-8")
            except Exception:
                logger.exception(
                    "RuleRepository: failed to save repository to '{}'",
                    str(self._path),
                )

    def add_from_rule(self, rule: RuleWithMeta, model_summary: Dict[str, Any]) -> None:
        info = getattr(rule, "info", {}) or {}
        logger.debug(
            "RuleRepository: add_from_rule called for '%s' with info_keys=%s",
            getattr(rule, "name", None),
            sorted(list(info.keys())) if isinstance(info, dict) else type(info),
        )
        if not isinstance(info, dict):
            logger.warning("RuleRepository: rule info is not a dict; skipping")
            return

        code = info.get("code")
        if not isinstance(code, str) or not code.strip():
            logger.warning(
                "RuleRepository: rule '%s' has no valid code string; skipping",
                getattr(rule, "name", None),
            )
            return

        # record['code'] is authoritative; keep info['code'] in sync.
        info["code"] = code
        
        # Generate unique name for the rule
        unique_name = generate_unique_rule_name(rule)
        
        record: Dict[str, Any] = {
            "name": unique_name,  # Use unique name
            "code": code,
            "model_summary": dict(model_summary) if isinstance(model_summary, dict) else {},
            "info": info,
            "version": getattr(rule, "version", 0),
            "timestamp": time.time(),
        }
        self._records.append(record)
        self._save()
        logger.info(
            "RuleRepository: stored rule '{}' (original name: '{}', version={}) with summary keys={}",
            unique_name,
            getattr(rule, "name", None),
            record.get("version"),
            list(record.get("model_summary", {}).keys()),
        )

    def add_from_rule_with_genealogy(
        self,
        rule: RuleWithMeta,
        model_summary: Dict[str, Any],
        parent_ids: Optional[List[str]] = None,
        operation: str = "generated",
        generation: int = 0
    ) -> str:
        """Add rule with genealogy information (thread-safe).
        
        Args:
            rule: The rule to add
            model_summary: Model summary information
            parent_ids: List of parent rule IDs
            operation: Operation type ("generated", "crossover", "mutation", "repository")
            generation: Generation number
        
        Returns:
            Unique rule ID for genealogy tracking
        """
        with self._lock:
            info = getattr(rule, "info", {}) or {}
            logger.debug(
                "RuleRepository: add_from_rule_with_genealogy called for '%s' with operation=%s, generation=%d",
                getattr(rule, "name", None),
                operation,
                generation,
            )
            
            if not isinstance(info, dict):
                logger.warning("RuleRepository: rule info is not a dict; skipping")
                return ""
            
            code = info.get("code")
            if not isinstance(code, str) or not code.strip():
                logger.warning(
                    "RuleRepository: rule '%s' has no valid code string; skipping",
                    getattr(rule, "name", None),
                )
                return ""

            # record['code'] is authoritative; keep info['code'] in sync.
            info["code"] = code
            
            # Get or create genealogy info
            genealogy = info.get("genealogy")
            if genealogy and isinstance(genealogy, dict):
                rule_id = genealogy.get("rule_id")
                if not rule_id:
                    rule_id = generate_rule_id()
                    genealogy["rule_id"] = rule_id
            else:
                rule_id = generate_rule_id()
                genealogy = GenealogyInfo(
                    rule_id=rule_id,
                    parent_ids=parent_ids or [],
                    operation=operation,
                    generation=generation,
                    timestamp=time.time()
                ).to_dict()
                info["genealogy"] = genealogy
            
            # Compute diversity score against existing population
            diversity_score = self._compute_diversity_for_new_rule(rule)
            info["diversity_score"] = diversity_score
            
            # Generate unique name for the rule
            unique_name = generate_unique_rule_name(rule)
            
            # Create record with genealogy
            record: Dict[str, Any] = {
                "id": rule_id,
                "name": unique_name,  # Use unique name
                "code": code,
                "model_summary": dict(model_summary) if isinstance(model_summary, dict) else {},
                "info": info,
                "genealogy": genealogy,
                "diversity_score": diversity_score,
                "version": getattr(rule, "version", 0),
                "timestamp": time.time(),
            }
            
            self._records.append(record)
            self._save()
            
            logger.info(
                "RuleRepository: stored rule '{}' (original name: '{}', id={}, operation={}, generation={}, diversity={:.3f}) with summary keys={}",
                unique_name,
                getattr(rule, "name", None),
                rule_id,
                operation,
                generation,
                diversity_score,
                list(record.get("model_summary", {}).keys()),
            )
            
            return rule_id

    def get_by_id(self, rule_id: str) -> Optional[RuleWithMeta]:
        """Retrieve rule by unique ID.
        
        Args:
            rule_id: The unique rule identifier
        
        Returns:
            RuleWithMeta if found, None otherwise
        """
        for record in self._records:
            rec_id = record.get("id")
            if rec_id == rule_id:
                return self._compile_record(record)
            
            # Also check genealogy for backward compatibility
            genealogy = record.get("genealogy") or record.get("info", {}).get("genealogy")
            if isinstance(genealogy, dict) and genealogy.get("rule_id") == rule_id:
                return self._compile_record(record)
        
        return None

    def get_descendants(self, rule_id: str) -> List[RuleWithMeta]:
        """Get all descendant rules.
        
        Args:
            rule_id: The parent rule ID
        
        Returns:
            List of descendant rules
        """
        descendants = []
        
        for record in self._records:
            genealogy = record.get("genealogy") or record.get("info", {}).get("genealogy")
            if not isinstance(genealogy, dict):
                continue
            
            parent_ids = genealogy.get("parent_ids", [])
            if rule_id in parent_ids:
                rule = self._compile_record(record)
                if rule is not None:
                    descendants.append(rule)
        
        return descendants

    def get_population(
        self,
        max_size: int = 50,
        min_fitness: Optional[float] = None
    ) -> List[RuleWithMeta]:
        """Get current population for evolutionary operations.
        
        Args:
            max_size: Maximum number of rules to return
            min_fitness: Minimum fitness threshold (optional)
        
        Returns:
            List of rules from repository
        """
        rules = []
        
        for record in self._records:
            rule = self._compile_record(record)
            if rule is None:
                continue
            
            # Apply fitness filter if specified
            if min_fitness is not None:
                info = record.get("info") or {}
                eval_info = info.get("eval") or {}
                rel_improve = float(eval_info.get("relative_improvement", 0.0) or 0.0)
                if rel_improve < min_fitness:
                    continue
            
            rules.append(rule)
        
        # Sort by fitness (relative improvement) and take top max_size
        def get_fitness(r: RuleWithMeta) -> float:
            info = r.info or {}
            eval_info = info.get("eval") or {}
            return float(eval_info.get("relative_improvement", 0.0) or 0.0)
        
        rules.sort(key=get_fitness, reverse=True)
        
        return rules[:max_size]

    def compute_population_diversity(self) -> float:
        """Compute average diversity in repository.
        
        Returns:
            Average diversity score (0.0 if no diversity scores available)
        """
        diversity_scores = []
        
        for record in self._records:
            div_score = record.get("diversity_score")
            if div_score is not None:
                try:
                    diversity_scores.append(float(div_score))
                except (ValueError, TypeError):
                    pass
        
        if not diversity_scores:
            return 0.0
        
        return sum(diversity_scores) / len(diversity_scores)

    def find_best_for(self, model_summary: Dict[str, Any]) -> Optional[RuleWithMeta]:
        if not self._records:
            return None
        target = dict(model_summary) if isinstance(model_summary, dict) else {}
        target_jobs = float(target.get("num_jobs", 0.0) or 0.0)
        target_machines = float(target.get("num_machines", 0.0) or 0.0)
        target_cfg = target.get("config_path")
        best_record: Optional[Dict[str, Any]] = None
        best_score = float("-inf")
        for rec in self._records:
            rec_ms = rec.get("model_summary") or {}
            if not isinstance(rec_ms, dict):
                rec_ms = {}
            rec_jobs = float(rec_ms.get("num_jobs", 0.0) or 0.0)
            rec_machines = float(rec_ms.get("num_machines", 0.0) or 0.0)
            rec_cfg = rec_ms.get("config_path")
            cfg_match = 0.0
            if isinstance(target_cfg, str) and isinstance(rec_cfg, str) and target_cfg == rec_cfg:
                cfg_match = 1.0
            jobs_diff = abs(rec_jobs - target_jobs)
            machines_diff = abs(rec_machines - target_machines)
            scale_jobs = max(target_jobs, 1.0)
            scale_machines = max(target_machines, 1.0)
            dist = jobs_diff / scale_jobs + machines_diff / scale_machines
            info = rec.get("info") or {}
            if not isinstance(info, dict):
                info = {}
            eval_info = info.get("eval") or {}
            if not isinstance(eval_info, dict):
                eval_info = {}
            rel_improve = float(eval_info.get("relative_improvement", 0.0) or 0.0)
            cplx = 0.0
            complexity = info.get("complexity")
            if isinstance(complexity, dict):
                try:
                    cplx = float(complexity.get("complexity_score", 0.0))
                except Exception:
                    cplx = 0.0
            norm_cplx = math.log1p(max(cplx, 0.0))
            score = rel_improve - 0.05 * norm_cplx - dist + 0.5 * cfg_match
            if score > best_score:
                best_score = score
                best_record = rec
        if best_record is None:
            return None
        rule = self._compile_record(best_record)
        return rule

    def build_ensemble_for(self, model_summary: Dict[str, Any], max_members: int = 3) -> Optional[RuleWithMeta]:
        if not self._records:
            return None
        target = dict(model_summary) if isinstance(model_summary, dict) else {}
        target_jobs = float(target.get("num_jobs", 0.0) or 0.0)
        target_machines = float(target.get("num_machines", 0.0) or 0.0)
        target_cfg = target.get("config_path")
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for rec in self._records:
            rec_ms = rec.get("model_summary") or {}
            if not isinstance(rec_ms, dict):
                rec_ms = {}
            rec_jobs = float(rec_ms.get("num_jobs", 0.0) or 0.0)
            rec_machines = float(rec_ms.get("num_machines", 0.0) or 0.0)
            rec_cfg = rec_ms.get("config_path")
            cfg_match = 0.0
            if isinstance(target_cfg, str) and isinstance(rec_cfg, str) and target_cfg == rec_cfg:
                cfg_match = 1.0
            jobs_diff = abs(rec_jobs - target_jobs)
            machines_diff = abs(rec_machines - target_machines)
            scale_jobs = max(target_jobs, 1.0)
            scale_machines = max(target_machines, 1.0)
            dist = jobs_diff / scale_jobs + machines_diff / scale_machines
            info = rec.get("info") or {}
            if not isinstance(info, dict):
                info = {}
            eval_info = info.get("eval") or {}
            if not isinstance(eval_info, dict):
                eval_info = {}
            rel_improve = float(eval_info.get("relative_improvement", 0.0) or 0.0)
            cplx = 0.0
            complexity = info.get("complexity")
            if isinstance(complexity, dict):
                try:
                    cplx = float(complexity.get("complexity_score", 0.0))
                except Exception:
                    cplx = 0.0
            norm_cplx = math.log1p(max(cplx, 0.0))
            score = rel_improve - 0.05 * norm_cplx - dist + 0.5 * cfg_match
            scored.append((score, rec))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        k = min(max_members, len(scored))
        members: List[Tuple[_RepoFunctionPriorityRule, float]] = []
        member_meta: List[Dict[str, Any]] = []
        for i in range(k):
            score, rec = scored[i]
            compiled = self._compile_record(rec)
            if compiled is None:
                continue
            weight = max(score, 0.0)
            members.append((compiled.rule, weight if weight > 0.0 else 1.0))
            meta: Dict[str, Any] = {
                "name": rec.get("name"),
                "score": score,
                "weight": weight if weight > 0.0 else 1.0,
                "model_summary": rec.get("model_summary") or {},
            }
            info = rec.get("info") or {}
            if isinstance(info, dict):
                meta["eval"] = info.get("eval")
                meta["complexity"] = info.get("complexity")
            member_meta.append(meta)
        if not members:
            return None
        ensemble_rule = _EnsemblePriorityRule(members)
        name = "ensemble_portfolio"
        info: Dict[str, Any] = {
            "source": "repository_ensemble",
            "members": member_meta,
        }
        logger.info(
            "RuleRepository: built ensemble of {} members for warm-start",
            len(member_meta),
        )
        return RuleWithMeta(rule=ensemble_rule, name=name, info=info)

    def _compute_diversity_for_new_rule(self, new_rule: RuleWithMeta) -> float:
        """Compute diversity score for a new rule against existing population.
        
        Computes the average diversity of the new rule compared to all existing
        rules in the repository. Returns 0.0 if repository is empty.
        
        Args:
            new_rule: The new rule to compute diversity for
        
        Returns:
            Average diversity score (0.0 to 1.0)
        """
        if not self._records:
            # Empty repository, return default diversity
            return 0.5
        
        # Get existing rules
        existing_rules = []
        for record in self._records:
            rule = self._compile_record(record)
            if rule is not None:
                existing_rules.append(rule)
        
        if not existing_rules:
            return 0.5
        
        # Compute diversity against each existing rule
        diversity_scores = []
        for existing_rule in existing_rules:
            try:
                metrics = compute_combined_diversity(
                    new_rule,
                    existing_rule,
                    test_scenarios=None,  # Will generate default scenarios
                    model_summary=None,
                    structural_weight=0.7,  # Favor structural diversity
                    behavioral_weight=0.3
                )
                diversity_scores.append(metrics.combined_diversity)
            except Exception as exc:
                logger.debug(
                    "Failed to compute diversity for rule pair: {}",
                    exc
                )
                continue
        
        if not diversity_scores:
            return 0.5
        
        # Return average diversity
        return sum(diversity_scores) / len(diversity_scores)

    def _compile_record(self, record: Dict[str, Any]) -> Optional[RuleWithMeta]:
        code = record.get("code")
        if not isinstance(code, str) or not code.strip():
            return None
        max_chars = 65536
        if len(code) > max_chars:
            code = code[:max_chars]
        try:
            fn = compile_optimized_priority(code)
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"RuleRepository: failed to exec stored code: {e}")
            return None
        rule = _RepoFunctionPriorityRule(fn)
        name = str(record.get("name") or "repo_optimized_priority")
        
        # Get original info from record
        original_info = record.get("info") or {}
        
        # Preserve genealogy and diversity information
        info = {
            "code": code,
            "source": original_info.get("source", "repository"),  # Preserve original source
            "model_summary": record.get("model_summary") or {},
            "eval": original_info.get("eval"),
            "complexity": original_info.get("complexity"),
            "performance": original_info.get("performance"),
        }
        
        # Preserve description if present (for baseline heuristics)
        if "description" in original_info:
            info["description"] = original_info["description"]
        
        # Add genealogy if present
        genealogy = record.get("genealogy")
        if not genealogy:
            # Check in info for backward compatibility
            genealogy = original_info.get("genealogy")
        if genealogy:
            info["genealogy"] = genealogy
        
        # Add diversity score if present
        diversity_score = record.get("diversity_score")
        if diversity_score is not None:
            info["diversity_score"] = diversity_score
        
        return RuleWithMeta(rule=rule, name=name, info=info)

    def update_performance(
        self,
        rule_id: str,
        fitness: float,
        alpha: float = 0.3,
    ) -> bool:
        """Update performance statistics for a rule.
        
        Updates the rule's performance statistics using exponential moving average.
        
        Args:
            rule_id: Unique rule identifier
            fitness: New fitness value to incorporate
            alpha: Weight for new value in EMA (0 < alpha <= 1)
        
        Returns:
            True if update succeeded, False if rule not found
        """
        # Find rule by ID
        target_record = None
        for record in self._records:
            rec_id = record.get("id")
            if rec_id == rule_id:
                target_record = record
                break
            
            # Also check genealogy for backward compatibility
            genealogy = record.get("genealogy") or record.get("info", {}).get("genealogy")
            if isinstance(genealogy, dict) and genealogy.get("rule_id") == rule_id:
                target_record = record
                break
        
        if target_record is None:
            logger.warning(
                "RuleRepository: cannot update performance, rule not found (rule_id='{}')",
                rule_id
            )
            return False
        
        # Get or create performance stats
        info = target_record.get("info", {})
        if not isinstance(info, dict):
            info = {}
            target_record["info"] = info
        
        # Get existing performance stats or create new
        perf_data = info.get("performance")
        if isinstance(perf_data, dict):
            perf_stats = PerformanceStats.from_dict(perf_data)
        else:
            perf_stats = PerformanceStats()
        
        # Update statistics
        perf_stats.update(fitness, alpha=alpha)
        
        # Save back to record
        info["performance"] = perf_stats.to_dict()
        
        # Persist to disk
        self._save()
        
        logger.debug(
            "RuleRepository: updated performance for rule '{}' (fitness={:.4f}, mean={:.4f}, num_evals={})",
            target_record.get("name", "unknown"),
            fitness,
            perf_stats.mean_fitness,
            perf_stats.num_evaluations
        )
        
        return True

    def replace_if_better(
        self,
        new_rule: RuleWithMeta,
        new_fitness: float,
        model_summary: Dict[str, Any],
        strategy: str = "lowest_fitness",
        max_size: int = 100,
        min_improvement: float = 0.05,
    ) -> Tuple[bool, Optional[str]]:
        """Replace a rule in repository if conditions are met (thread-safe).
        
        This method implements automatic repository rule replacement when:
        1. Repository is at max size
        2. New rule is better than target rule by min_improvement threshold
        3. Target rule is not protected (baseline heuristics)
        
        Args:
            new_rule: New rule to potentially add
            new_fitness: Fitness of new rule (relative improvement)
            model_summary: Model summary for the new rule
            strategy: Replacement strategy ("lowest_fitness", "oldest_first", "none")
            max_size: Maximum repository size
            min_improvement: Minimum fitness improvement required
        
        Returns:
            Tuple of (replaced, reason):
                - replaced: True if replacement occurred
                - reason: Explanation of outcome
        """
        with self._lock:
            logger.info(
                "RuleRepository: replace_if_better called (new_rule='{}', new_fitness={:.4f}, strategy='{}', repo_size={}, max_size={})",
                new_rule.name,
                new_fitness,
                strategy,
                len(self._records),
                max_size
            )
            
            # Log replacement attempted event
            logger.info(
                "RuleRepository: replacement_attempted (new_rule='{}', new_fitness={:.4f}, strategy='{}', repo_size={}, max_size={})",
                new_rule.name,
                new_fitness,
                strategy,
                len(self._records),
                max_size
            )
            
            # Check if replacement is disabled
            if strategy == "none":
                logger.info("RuleRepository: replacement disabled (strategy='none')")
                return (False, "replacement_disabled")
            
            # Check if repository is at max size
            if len(self._records) < max_size:
                # Repository not full, just add the rule
                rule_id = self.add_from_rule_with_genealogy(
                    rule=new_rule,
                    model_summary=model_summary,
                    parent_ids=None,
                    operation="generated",
                    generation=0
                )
                logger.info(
                    "RuleRepository: added new rule without replacement (repo not full: {}/{})",
                    len(self._records),
                    max_size
                )
                return (False, "repository_not_full")
            
            # Repository is full, need to find replacement target
            target_record = None
            target_fitness = None
            
            if strategy == "lowest_fitness":
                # Find rule with lowest fitness
                for record in self._records:
                    # Skip protected rules (baseline heuristics)
                    info = record.get("info", {})
                    if isinstance(info, dict) and info.get("source") == "baseline_heuristic":
                        continue
                    
                    # Get fitness from record
                    eval_info = info.get("eval", {})
                    if isinstance(eval_info, dict):
                        fitness = float(eval_info.get("relative_improvement", 0.0) or 0.0)
                    else:
                        fitness = 0.0
                    
                    # Track lowest fitness
                    if target_fitness is None or fitness < target_fitness:
                        target_fitness = fitness
                        target_record = record
            
            elif strategy == "oldest_first":
                # Find oldest rule (earliest timestamp)
                oldest_timestamp = None
                for record in self._records:
                    # Skip protected rules (baseline heuristics)
                    info = record.get("info", {})
                    if isinstance(info, dict) and info.get("source") == "baseline_heuristic":
                        continue
                    
                    timestamp = record.get("timestamp", 0.0)
                    
                    # Track oldest
                    if oldest_timestamp is None or timestamp < oldest_timestamp:
                        oldest_timestamp = timestamp
                        target_record = record
                        # Get fitness for logging
                        eval_info = info.get("eval", {})
                        if isinstance(eval_info, dict):
                            target_fitness = float(eval_info.get("relative_improvement", 0.0) or 0.0)
                        else:
                            target_fitness = 0.0
            
            else:
                logger.error(
                    "RuleRepository: unknown replacement strategy '{}'",
                    strategy
                )
                return (False, "unknown_strategy")
            
            # Check if we found a target
            if target_record is None:
                logger.warning(
                    "RuleRepository: no replacement target found (all rules protected?)"
                )
                return (False, "no_target_found")
            
            # Check if new rule is better than target
            if target_fitness is None:
                target_fitness = 0.0
            
            fitness_diff = new_fitness - target_fitness
            
            if fitness_diff < min_improvement:
                logger.info(
                    "RuleRepository: new rule not better enough (fitness_diff={:.4f} < min_improvement={:.4f})",
                    fitness_diff,
                    min_improvement
                )
                return (False, "insufficient_improvement")
            
            # Perform replacement
            target_name = target_record.get("name", "unknown")
            target_id = target_record.get("id", "unknown")
            
            # Log replacement target selected event
            logger.info(
                "RuleRepository: replacement_target_selected (target_rule='{}', target_fitness={:.4f}, strategy='{}')",
                target_name,
                target_fitness,
                strategy
            )
            
            logger.info(
                "RuleRepository: replacing rule '{}' (fitness={:.4f}) with '{}' (fitness={:.4f}, improvement={:.4f})",
                target_name,
                target_fitness,
                new_rule.name,
                new_fitness,
                fitness_diff
            )
            
            # Remove target rule
            self._records.remove(target_record)
            
            # Add new rule
            new_rule_id = self.add_from_rule_with_genealogy(
                rule=new_rule,
                model_summary=model_summary,
                parent_ids=None,
                operation="generated",
                generation=0
            )
            
            logger.info(
                "RuleRepository: replacement complete (replaced_rule='{}', new_rule='{}', new_rule_id='{}')",
                target_name,
                new_rule.name,
                new_rule_id
            )
            
            # Log replacement completed event
            logger.info(
                "RuleRepository: replacement_completed (replaced_rule='{}', new_rule='{}', new_rule_id='{}', fitness_improvement={:.4f})",
                target_name,
                new_rule.name,
                new_rule_id,
                fitness_diff
            )
            
            return (True, f"replaced_{target_name}")

    def evaluate_all_for_warmstart(
        self,
        eval_pool,  # EvalEventsPool | JMSEvalPool
        objective_metric: str,
        time_budget: float = 30.0,
        max_rules: Optional[int] = None,
    ) -> List[Tuple[RuleWithMeta, float]]:
        """Evaluate all repository rules for warm-start baseline selection.
        
        Evaluates all rules on the same eval pool and returns them sorted by fitness.
        This provides direct evaluation-based warm-start without similarity assumptions.
        
        Args:
            eval_pool: Evaluation pool (EvalEventsPool or JMSEvalPool)
            baseline_rule: Baseline rule for comparison
            objective_metric: Metric to optimize
            time_budget: Maximum time budget in seconds
            max_rules: Maximum number of rules to evaluate (None = all)
        
        Returns:
            List of (rule, fitness) tuples sorted by fitness (highest first)
        """
        from .rule_evaluator import RuleEvaluator
        from .config import LLMCoderConfig
        
        # Get all rules from repository
        all_rules = []
        for record in self._records:
            rule = self._compile_record(record)
            if rule is not None:
                all_rules.append(rule)
        
        if not all_rules:
            logger.warning(
                "RuleRepository: no rules available for warm-start evaluation"
            )
            return []
        
        logger.info(
            "RuleRepository: starting warm-start evaluation of {} rules (time_budget={:.1f}s, max_rules={})",
            len(all_rules),
            time_budget,
            max_rules
        )
        
        # Create a minimal config for evaluation
        # We'll use the eval pool's configuration if available
        cfg = LLMCoderConfig()
        cfg.enable_eval = True
        
        # Create evaluator
        evaluator = RuleEvaluator(cfg)
        
        # Evaluate all rules (absolute metric mean; lower is better for makespan)
        fitness_dict = evaluator.batch_evaluate_absolute(
            rules=all_rules,
            eval_pool=eval_pool,
            objective_metric=objective_metric,
            time_budget=time_budget,
            max_rules=max_rules,
        )
        
        # Build result list with rules and their fitness
        results: List[Tuple[RuleWithMeta, float]] = []
        for rule in all_rules:
            rule_id = evaluator._get_rule_id(rule)
            if rule_id in fitness_dict:
                fitness = fitness_dict[rule_id]
                results.append((rule, fitness))
        
        # Sort by metric mean (lowest first)
        results.sort(key=lambda x: x[1])
        
        logger.info(
            "RuleRepository: warm-start evaluation complete, evaluated {} rules",
            len(results)
        )
        
        return results

    def initialize_baseline_heuristics(self) -> None:
        """Initialize repository with baseline heuristics.
        
        Adds classic scheduling heuristics (SPT, EDD, FIFO, LIFO, etc.) to the
        repository. These are marked as protected and will not be replaced.
        
        This method is idempotent - it will not add duplicates if baseline
        heuristics already exist in the repository.
        """
        # Get all available baseline heuristics
        heuristic_names = BaselineHeuristicLibrary.get_all_heuristic_names()
        
        # Check which heuristics are already in repository
        existing_baseline_names = set()
        for record in self._records:
            info = record.get("info", {})
            if isinstance(info, dict) and info.get("source") == "baseline_heuristic":
                name = record.get("name", "")
                existing_baseline_names.add(name)
        
        # Add missing baseline heuristics
        added_count = 0
        for heuristic_name in heuristic_names:
            # Skip if already exists
            if heuristic_name in existing_baseline_names:
                logger.debug(
                    "RuleRepository: baseline heuristic '{}' already exists, skipping",
                    heuristic_name
                )
                continue
            
            # Get heuristic code
            code = BaselineHeuristicLibrary.get_heuristic_code(heuristic_name)
            if not code:
                logger.warning(
                    "RuleRepository: failed to get code for baseline heuristic '{}'",
                    heuristic_name
                )
                continue
            
            # Generate unique rule ID
            rule_id = generate_rule_id()
            
            # Create record for baseline heuristic
            record = {
                "id": rule_id,
                "name": heuristic_name,
                "code": code,
                "model_summary": {},
                "info": {
                    "code": code,
                    "source": "baseline_heuristic",
                    "description": f"Classic {heuristic_name} scheduling heuristic",
                },
                "genealogy": {
                    "rule_id": rule_id,
                    "parent_ids": [],
                    "operation": "baseline_heuristic",
                    "generation": 0,
                    "timestamp": time.time(),
                },
                "version": 0,
                "timestamp": time.time(),
            }
            
            self._records.append(record)
            added_count += 1
            
            logger.info(
                "RuleRepository: added baseline heuristic '{}' (id={})",
                heuristic_name,
                rule_id
            )
        
        # Save if any heuristics were added
        if added_count > 0:
            self._save()
            logger.info(
                "RuleRepository: initialized {} baseline heuristics (total rules: {})",
                added_count,
                len(self._records)
            )
        else:
            logger.info(
                "RuleRepository: all baseline heuristics already initialized"
            )

    def backup(self, backup_path: Optional[str] = None) -> str:
        """Create timestamped backup of repository.
        
        Args:
            backup_path: Optional custom backup path. If None, creates timestamped backup
                        in same directory as repository.
        
        Returns:
            Path to created backup file
        """
        if backup_path is None:
            # Create timestamped backup in same directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = str(self._path.parent / f"{self._path.stem}_backup_{timestamp}{self._path.suffix}")
        else:
            backup_path = str(Path(backup_path))
        
        # Check if backup file already exists, append suffix if needed
        backup_file = Path(backup_path)
        if backup_file.exists():
            counter = 1
            while backup_file.exists():
                backup_path = str(backup_file.parent / f"{backup_file.stem}_{counter}{backup_file.suffix}")
                backup_file = Path(backup_path)
                counter += 1
        
        try:
            # Copy current repository file to backup
            if self._path.exists():
                shutil.copy2(self._path, backup_path)
                logger.info(
                    "RuleRepository: created backup at '{}' with {} rules",
                    backup_path,
                    len(self._records)
                )
            else:
                # Repository doesn't exist yet, create empty backup
                Path(backup_path).write_text("[]", encoding="utf-8")
                logger.info(
                    "RuleRepository: created empty backup at '{}' (repository doesn't exist yet)",
                    backup_path
                )
            
            return backup_path
        except Exception as e:
            logger.error(
                "RuleRepository: failed to create backup at '{}': {}",
                backup_path,
                e
            )
            raise
    
    def restore(self, backup_path: str) -> None:
        """Restore repository from backup file.
        
        Args:
            backup_path: Path to backup file to restore from
        
        Raises:
            FileNotFoundError: If backup file doesn't exist
            ValueError: If backup file is corrupted or invalid
        """
        backup_file = Path(backup_path)
        
        if not backup_file.exists():
            logger.error(
                "RuleRepository: backup file not found: '{}'",
                backup_path
            )
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
        
        try:
            # Load and validate backup data
            data = backup_file.read_text(encoding="utf-8")
            obj = json.loads(data)
            
            if not isinstance(obj, list):
                raise ValueError("Backup file does not contain a valid list of rules")
            
            # Validate each record has required fields
            for record in obj:
                if not isinstance(record, dict):
                    raise ValueError("Backup contains invalid record (not a dict)")
                if "code" not in record or not isinstance(record["code"], str):
                    raise ValueError("Backup contains record without valid code")
            
            # Backup is valid, restore it
            self._records = obj
            self._save()
            
            logger.info(
                "RuleRepository: restored from backup '{}' with {} rules",
                backup_path,
                len(self._records)
            )
        except json.JSONDecodeError as e:
            logger.error(
                "RuleRepository: backup file is corrupted (invalid JSON): '{}'",
                backup_path
            )
            raise ValueError(f"Backup file is corrupted: {e}")
        except Exception as e:
            logger.error(
                "RuleRepository: failed to restore from backup '{}': {}",
                backup_path,
                e
            )
            raise
    
    def reset(self, keep_baseline_heuristics: bool = True) -> str:
        """Reset repository, optionally keeping baseline heuristics.
        
        Creates automatic backup before resetting.
        
        Args:
            keep_baseline_heuristics: If True, keeps rules marked as baseline heuristics
        
        Returns:
            Path to automatic backup created before reset
        """
        # Create automatic backup before reset
        backup_path = self.backup()
        logger.info(
            "RuleRepository: created automatic backup before reset at '{}'",
            backup_path
        )
        
        # Count rules before reset
        rules_before = len(self._records)

        if keep_baseline_heuristics:
            self._records = []
            self.initialize_baseline_heuristics()
            rules_remaining = len(self._records)
        else:
            # Clear all rules
            self._records = []
            rules_remaining = 0
        
        self._save()

        removed_count = rules_before - rules_remaining
        if keep_baseline_heuristics:
            removed_count = rules_before
        
        logger.info(
            "RuleRepository: reset complete (keep_baseline_heuristics={}), removed {} rules, {} remaining",
            keep_baseline_heuristics,
            removed_count,
            rules_remaining
        )
        
        return backup_path

    def migrate_from_v1(self, old_repo_path: str) -> None:
        """Migrate from v1 repository format to current format.
        
        The current format is already quite complete, so this method mainly:
        1. Validates and cleans up data
        2. Ensures all required fields are present
        3. Removes unnecessary fields (model_summary will be removed in future)
        
        Args:
            old_repo_path: Path to old repository file
        
        Raises:
            FileNotFoundError: If old repository file doesn't exist
            ValueError: If old repository is invalid
        """
        old_file = Path(old_repo_path)
        
        if not old_file.exists():
            logger.error(
                "RuleRepository: old repository file not found: '{}'",
                old_repo_path
            )
            raise FileNotFoundError(f"Old repository file not found: {old_repo_path}")
        
        # Create backup of old repository
        backup_path = self.backup()
        logger.info(
            "RuleRepository: created backup of current repository before migration at '{}'",
            backup_path
        )
        
        # Also backup old repository
        old_backup_path = str(old_file.parent / f"{old_file.stem}_pre_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}{old_file.suffix}")
        try:
            shutil.copy2(old_file, old_backup_path)
            logger.info(
                "RuleRepository: created backup of old repository at '{}'",
                old_backup_path
            )
        except Exception as e:
            logger.warning(
                "RuleRepository: failed to backup old repository: {}",
                e
            )
        
        try:
            # Load old repository
            data = old_file.read_text(encoding="utf-8")
            old_records = json.loads(data)
            
            if not isinstance(old_records, list):
                raise ValueError("Old repository does not contain a valid list of rules")
            
            # Migrate each record
            migrated_records = []
            skipped_count = 0
            
            for i, old_record in enumerate(old_records):
                try:
                    # Validate required fields
                    if not isinstance(old_record, dict):
                        logger.warning(
                            "RuleRepository: skipping record {} (not a dict)",
                            i
                        )
                        skipped_count += 1
                        continue
                    
                    code = old_record.get("code")
                    if not isinstance(code, str) or not code.strip():
                        logger.warning(
                            "RuleRepository: skipping record {} (no valid code)",
                            i
                        )
                        skipped_count += 1
                        continue
                    
                    # Create migrated record with cleaned data
                    migrated_record = {
                        "name": old_record.get("name", f"migrated_rule_{i}"),
                        "code": code,
                        "model_summary": old_record.get("model_summary", {}),
                        "info": old_record.get("info", {}),
                        "version": old_record.get("version", 0),
                        "timestamp": old_record.get("timestamp", time.time()),
                    }
                    
                    # Preserve genealogy if present
                    if "genealogy" in old_record:
                        migrated_record["genealogy"] = old_record["genealogy"]
                    
                    # Preserve diversity score if present
                    if "diversity_score" in old_record:
                        migrated_record["diversity_score"] = old_record["diversity_score"]
                    
                    migrated_records.append(migrated_record)
                    
                except Exception as e:
                    logger.warning(
                        "RuleRepository: error migrating record {}: {}",
                        i,
                        e
                    )
                    skipped_count += 1
                    continue
            
            # Update repository with migrated records
            self._records = migrated_records
            self._save()
            
            logger.info(
                "RuleRepository: migration complete, migrated {} rules, skipped {} invalid rules",
                len(migrated_records),
                skipped_count
            )
            
        except json.JSONDecodeError as e:
            logger.error(
                "RuleRepository: old repository file is corrupted (invalid JSON): '{}'",
                old_repo_path
            )
            raise ValueError(f"Old repository file is corrupted: {e}")
        except Exception as e:
            logger.error(
                "RuleRepository: migration failed: {}",
                e
            )
            raise
