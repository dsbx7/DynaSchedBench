from __future__ import annotations

import ast
import json
from typing import Any, Dict, Optional, Set

from loguru import logger

from dsbx.Agents.utils import LLMClient

from .config import LLMCoderConfig
from .rules import RuleWithMeta


class _FeatureVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: Set[str] = set()
        self.attrs: Set[str] = set()
        self.obs_keys: Set[str] = set()
        self.env_attrs: Set[str] = set()

    def visit_Name(self, node: ast.Name) -> Any:  # pragma: no cover - simple visitor
        try:
            self.names.add(str(node.id))
        except Exception:
            pass
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:  # pragma: no cover - simple visitor
        try:
            attr = str(node.attr)
            self.attrs.add(attr)
            if isinstance(node.value, ast.Name) and node.value.id == "env":
                self.env_attrs.add(attr)
        except Exception:
            pass
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> Any:  # pragma: no cover - simple visitor
        try:
            if isinstance(node.value, ast.Name) and node.value.id == "obs":
                key = None
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    key = node.slice.value
                elif isinstance(node.slice, ast.Index):  # type: ignore[attr-defined]
                    sl = node.slice.value
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        key = sl.value
                if key is not None:
                    self.obs_keys.add(str(key))
        except Exception:
            pass
        self.generic_visit(node)


def build_rule_explanation(rule: RuleWithMeta) -> Dict[str, Any]:
    info = getattr(rule, "info", {}) or {}
    if not isinstance(info, dict):
        info = {}
    code = info.get("code")
    if not isinstance(code, str) or not code.strip():
        return {}
    try:
        tree = ast.parse(code)
    except Exception as e:  # pragma: no cover - defensive
        logger.error(
            "build_rule_explanation: failed to parse code for rule '{}' with error: {}",
            getattr(rule, "name", None),
            e,
        )
        return {"parse_error": str(e)}
    visitor = _FeatureVisitor()
    visitor.visit(tree)
    names = {n.lower() for n in visitor.names}
    attrs = {a.lower() for a in visitor.attrs}
    obs_keys = {k.lower() for k in visitor.obs_keys}
    env_attrs = {a.lower() for a in visitor.env_attrs}
    uses_process_time = "process_time" in names or "process_time" in obs_keys
    uses_due_date = "due_date" in names or "due_date" in obs_keys or "tardiness" in names or "lateness" in names
    uses_remaining_ops = "remaining_ops" in names or "remaining" in names
    uses_machines = "machines" in names or "machines" in obs_keys or "machine_group" in names or "machine_candidates" in names
    uses_env_score = any(a in {"estimate_action_score", "quick_rollout_score"} for a in env_attrs)
    family = "custom"
    if uses_process_time and not uses_due_date and not uses_env_score:
        family = "SPT_like"
    elif uses_due_date and not uses_process_time and not uses_env_score:
        family = "EDD_like"
    elif uses_due_date and uses_process_time:
        family = "slack_or_ATC_like"
    elif uses_env_score:
        family = "lookahead_or_rollout_based"
    explanation: Dict[str, Any] = {
        "family": family,
        "uses_process_time": uses_process_time,
        "uses_due_date": uses_due_date,
        "uses_remaining_ops": uses_remaining_ops,
        "uses_machines": uses_machines,
        "uses_env_score": uses_env_score,
        "obs_keys": sorted(obs_keys),
        "names": sorted(names),
        "env_attrs": sorted(env_attrs),
    }
    return explanation


class RefactorAgent:
    """Refactor/explanation agent for accepted rules.
    
    The agent leaves the executable rule path untouched, generates a natural
    language explanation after a rule is accepted, and can optionally produce a
    human-readable simplified code view for presentation only.
    """

    def __init__(self, llm_client: LLMClient, cfg: LLMCoderConfig) -> None:
        self._client = llm_client
        self._cfg = cfg

    def explain(self, rule: RuleWithMeta, eval_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        info = getattr(rule, "info", {}) or {}
        if not isinstance(info, dict):
            info = {}
        code = info.get("code")
        if not isinstance(code, str) or not code.strip():
            return {}

        static_features = build_rule_explanation(rule)

        try:
            prompt = self._build_prompt(code, static_features, eval_info)
        except Exception:
            return {"static": static_features}

        try:
            outs = self._client.generate(
                prompt,
                n=1,
                temperature=float(getattr(self._cfg, "critic_temperature", 0.0) or 0.0),
                top_p=self._cfg.llm_top_p,
                top_k=self._cfg.llm_top_k,
                timeout=self._cfg.llm_timeout,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("RefactorAgent: LLM generate failed for rule '{}' with error: {}", getattr(rule, "name", None), e)
            return {"static": static_features, "llm_error": str(e)}

        if not outs:
            return {"static": static_features}

        raw = outs[0]
        try:
            obj = json.loads(raw)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "RefactorAgent: failed to parse JSON from LLM output for rule '{}' with error: {}",
                getattr(rule, "name", None),
                e,
            )
            return {"static": static_features, "llm_parse_error": str(e)}

        if not isinstance(obj, dict):
            return {"static": static_features, "llm_invalid": True}

        summary = obj.get("summary") or obj.get("explanation")
        refactored_code = obj.get("refactored_code")
        notes = obj.get("notes")

        result: Dict[str, Any] = {"static": static_features}
        if isinstance(summary, str) and summary.strip():
            result["summary"] = summary.strip()
        if isinstance(refactored_code, str) and refactored_code.strip():
            result["refactored_code"] = refactored_code
        if isinstance(notes, str) and notes.strip():
            result["notes"] = notes.strip()
        return result

    def _build_prompt(
        self,
        code: str,
        static_features: Dict[str, Any],
        eval_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        features_json = json.dumps(static_features, ensure_ascii=False)
        eval_json = json.dumps(eval_info or {}, ensure_ascii=False)
        return (
            "You are an expert production scheduling researcher and Python engineer.\n"
            "You are given a Python priority function optimized_priority(obs, action, env) that has been accepted by a sandbox evaluation.\n\n"
            "Your goals:\n"
            "- Explain in natural language how this rule tends to prioritize operations and machines.\n"
            "- Optionally provide a refactored version of the function that is easier to read, while keeping the same interface.\n"
            "- The refactored code is for human understanding only and will NOT be executed directly.\n\n"
            "Context features (static analysis of the code):\n"
            f"STATIC_FEATURES = {features_json}\n\n"
            "Sandbox evaluation summary (optional):\n"
            f"EVAL_INFO = {eval_json}\n\n"
            "Original code (do not modify this block):\n"
            "ORIGINAL_CODE_BEGIN\n"
            f"{code}\n"
            "ORIGINAL_CODE_END\n\n"
            "Output requirements:\n"
            "- Respond with a single JSON object only.\n"
            "- JSON keys: 'summary' (string, 3-8 sentences), 'refactored_code' (string, optional), 'notes' (string, optional).\n"
            "- 'summary' should describe which features of obs/action/env are used (e.g., process_time, due_date, remaining_ops, machine load).\n"
            "- 'refactored_code' must be a complete Python function definition with the SAME signature.\n"
            "- Do NOT include any Markdown fences or extra text outside the JSON object.\n"
        )
