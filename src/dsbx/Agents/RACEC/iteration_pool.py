"""Iteration pool management for evolutionary operations in RACEC.

This module provides functionality to manage the pool of rules available
for parent selection within a single iteration, including newly generated
candidates that can immediately serve as parents.
"""

from __future__ import annotations

import uuid
from typing import Dict, List

from loguru import logger

from .rules import RuleWithMeta


class IterationPool:
    """Manage rules available for parent selection within an iteration.
    
    The iteration pool starts with similar rules from the repository and
    grows as new candidates are generated during the iteration. This allows
    newly generated rules to immediately serve as parents for subsequent
    crossover or mutation operations within the same iteration.
    """
    
    def __init__(self, similar_rules: List[RuleWithMeta]):
        """Initialize with similar rules from repository.
        
        Args:
            similar_rules: List of rules from repository that are similar
                          to the current instance
        """
        # Create a copy of the list to avoid external modifications
        self._pool: List[RuleWithMeta] = list(similar_rules)
        
        # Map temporary IDs to permanent IDs after repository storage
        # temp_id -> permanent_id
        self._temp_id_map: Dict[str, str] = {}
        
        logger.debug(
            "IterationPool initialized with {} similar rules from repository",
            len(self._pool)
        )
    
    def add_candidate(self, rule: RuleWithMeta, temp_id: str) -> None:
        """Add newly generated candidate to pool.
        
        This allows the candidate to be used as a parent for subsequent
        evolutionary operations within the same iteration.
        
        Args:
            rule: The newly generated rule to add
            temp_id: Temporary ID for the rule (will be resolved to permanent ID later)
        """
        if not isinstance(rule, RuleWithMeta):
            logger.warning(
                "IterationPool: attempted to add non-RuleWithMeta object, skipping"
            )
            return
        
        # Add rule to pool
        self._pool.append(rule)
        
        # Store temporary ID for later resolution
        rule_info = getattr(rule, "info", {}) or {}
        rule_id = rule_info.get("rule_id", "")
        if rule_id:
            self._temp_id_map[temp_id] = rule_id
        
        logger.debug(
            "IterationPool: added candidate '{}' with temp_id='{}' (pool size now: {})",
            getattr(rule, "name", "unknown"),
            temp_id,
            len(self._pool)
        )
    
    def get_pool(self) -> List[RuleWithMeta]:
        """Get current pool for parent selection.
        
        Returns:
            List of all rules currently in the pool (repository rules + new candidates)
        """
        return list(self._pool)  # Return a copy to prevent external modifications
    
    def resolve_temp_ids(self, permanent_ids: Dict[str, str]) -> None:
        """Resolve temporary IDs to permanent IDs after repository storage.
        
        This updates the genealogy information in rules that reference
        temporary IDs as parents, replacing them with permanent IDs.
        
        Args:
            permanent_ids: Mapping from temporary IDs to permanent rule IDs
                          {temp_id: permanent_rule_id}
        """
        if not permanent_ids:
            logger.debug("IterationPool: no permanent IDs to resolve")
            return
        
        # Update internal mapping
        self._temp_id_map.update(permanent_ids)
        
        # Update genealogy in all rules that reference temporary IDs
        resolved_count = 0
        for rule in self._pool:
            rule_info = getattr(rule, "info", {})
            if not isinstance(rule_info, dict):
                continue
            
            genealogy = rule_info.get("genealogy", {})
            if not isinstance(genealogy, dict):
                continue
            
            parent_ids = genealogy.get("parent_ids", [])
            if not isinstance(parent_ids, list):
                continue
            
            # Check if any parent IDs need resolution
            updated_parent_ids = []
            has_updates = False
            
            for parent_id in parent_ids:
                if parent_id in permanent_ids:
                    # Replace temporary ID with permanent ID
                    updated_parent_ids.append(permanent_ids[parent_id])
                    has_updates = True
                else:
                    # Keep existing ID
                    updated_parent_ids.append(parent_id)
            
            if has_updates:
                genealogy["parent_ids"] = updated_parent_ids
                resolved_count += 1
                
                logger.debug(
                    "IterationPool: resolved temp IDs in rule '{}': {} -> {}",
                    getattr(rule, "name", "unknown"),
                    parent_ids,
                    updated_parent_ids
                )
        
        logger.info(
            "IterationPool: resolved temporary IDs in {} rules",
            resolved_count
        )
    
    def size(self) -> int:
        """Get current size of the pool.
        
        Returns:
            Number of rules in the pool
        """
        return len(self._pool)
    
    def get_temp_id_map(self) -> Dict[str, str]:
        """Get the temporary ID mapping.
        
        Returns:
            Copy of the temp_id -> permanent_id mapping
        """
        return dict(self._temp_id_map)
    
    @staticmethod
    def generate_temp_id() -> str:
        """Generate a unique temporary ID for a new candidate.
        
        Returns:
            Temporary ID string (UUID-based)
        """
        return f"temp_{uuid.uuid4().hex[:12]}"
