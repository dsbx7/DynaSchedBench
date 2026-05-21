from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .rules import RuleWithMeta
from .compile import compile_optimized_priority


class _RepoFunctionPriorityRule:
    def __init__(self, fn):
        self._fn = fn

    def __call__(self, obs: Dict[str, Any], action: Dict[str, Any], env: Any) -> float:
        try:
            v = self._fn(obs, action, env)
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
            self._path = base / "llmcoder_rules.json"
        else:
            self._path = Path(path)
            if not self._path.parent.exists():
                self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
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

    def _save(self) -> None:
        try:
            data = json.dumps(self._records, ensure_ascii=False, indent=2)
            self._path.write_text(data, encoding="utf-8")
        except Exception:
            pass

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
        record: Dict[str, Any] = {
            "name": rule.name,
            "code": code,
            "model_summary": dict(model_summary) if isinstance(model_summary, dict) else {},
            "info": info,
            "version": getattr(rule, "version", 0),
            "timestamp": time.time(),
        }
        self._records.append(record)
        self._save()
        logger.info(
            "RuleRepository: stored rule '{}' (version={}) with summary keys={}",
            record["name"],
            record.get("version"),
            list(record.get("model_summary", {}).keys()),
        )

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
        info = {
            "code": code,
            "source": "repository",
            "model_summary": record.get("model_summary") or {},
            "eval": (record.get("info") or {}).get("eval"),
            "complexity": (record.get("info") or {}).get("complexity"),
        }
        return RuleWithMeta(rule=rule, name=name, info=info)
