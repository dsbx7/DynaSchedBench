"""Feedback loop management for RACEC agentic workflow.

This module provides data structures and utilities for managing feedback
from the Critic Agent to the Planner Agent across iterations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class IterationFeedback:
    """Feedback from a single iteration's candidate evaluation.
    
    Attributes:
        iteration: The iteration number when this feedback was generated
        candidate_name: Name of the candidate rule that was evaluated
        verdict: The critic's verdict ("accept", "reject", or "refine")
        reason: Explanation for the verdict
        suggested_changes: Dictionary of suggested improvements
        metrics: Dictionary of evaluation metrics for this candidate
    """
    iteration: int
    candidate_name: str
    verdict: str
    reason: str = ""
    suggested_changes: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert feedback to dictionary format."""
        return {
            "iteration": self.iteration,
            "candidate_name": self.candidate_name,
            "verdict": self.verdict,
            "reason": self.reason,
            "suggested_changes": dict(self.suggested_changes),
            "metrics": dict(self.metrics),
        }


class FeedbackHistory:
    """Manages feedback history across agentic iterations.
    
    This class stores feedback from the Critic Agent and provides
    methods to retrieve and summarize feedback for inclusion in
    Planner Agent prompts.
    """
    
    def __init__(self, max_history: int = 10):
        """Initialize feedback history.
        
        Args:
            max_history: Maximum number of feedback entries to retain
        """
        self._history: List[IterationFeedback] = []
        self._max_history = max_history
    
    def add_feedback(self, feedback: IterationFeedback) -> None:
        """Add feedback from an iteration.
        
        Args:
            feedback: The feedback entry to add
        """
        if feedback is None:
            logger.warning("FeedbackHistory.add_feedback: received None feedback, skipping")
            return
        
        if not isinstance(feedback, IterationFeedback):
            logger.warning(
                "FeedbackHistory.add_feedback: received invalid feedback type {}, skipping",
                type(feedback).__name__
            )
            return
        
        try:
            self._history.append(feedback)
            logger.debug(
                "FeedbackHistory: added feedback for iteration {} candidate '{}' (verdict={})",
                feedback.iteration,
                feedback.candidate_name,
                feedback.verdict
            )
            # Trim history if it exceeds max size
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
                logger.debug("FeedbackHistory: trimmed history to {} entries", len(self._history))
        except Exception as exc:
            logger.error("FeedbackHistory.add_feedback: failed to add feedback: {}", exc)
    
    def get_recent(self, n: int = 5) -> List[IterationFeedback]:
        """Get n most recent feedback entries.
        
        Args:
            n: Number of recent entries to retrieve
            
        Returns:
            List of up to n most recent feedback entries
        """
        if n <= 0:
            return []
        
        try:
            return self._history[-n:]
        except Exception as exc:
            logger.error("FeedbackHistory.get_recent: failed to retrieve recent feedback: {}", exc)
            return []
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for prompt inclusion.
        
        Returns:
            Dictionary containing:
                - total_count: Total number of feedback entries
                - accept_count: Number of accepted candidates
                - reject_count: Number of rejected candidates
                - refine_count: Number of candidates marked for refinement
                - recent_feedback: List of recent feedback dictionaries
        """
        if not self._history:
            return {
                "total_count": 0,
                "accept_count": 0,
                "reject_count": 0,
                "refine_count": 0,
                "recent_feedback": [],
            }
        
        try:
            accept_count = sum(1 for fb in self._history if fb.verdict and fb.verdict.lower() == "accept")
            reject_count = sum(1 for fb in self._history if fb.verdict and fb.verdict.lower() == "reject")
            refine_count = sum(1 for fb in self._history if fb.verdict and fb.verdict.lower() == "refine")
            
            # Get recent feedback (last 5 by default)
            recent = self.get_recent(5)
            recent_dicts = []
            for fb in recent:
                try:
                    recent_dicts.append(fb.to_dict())
                except Exception as exc:
                    logger.warning("FeedbackHistory.get_summary: failed to convert feedback to dict: {}", exc)
            
            return {
                "total_count": len(self._history),
                "accept_count": accept_count,
                "reject_count": reject_count,
                "refine_count": refine_count,
                "recent_feedback": recent_dicts,
            }
        except Exception as exc:
            logger.error("FeedbackHistory.get_summary: failed to generate summary: {}", exc)
            return {
                "total_count": 0,
                "accept_count": 0,
                "reject_count": 0,
                "refine_count": 0,
                "recent_feedback": [],
            }
    
    def clear(self) -> None:
        """Clear history for new task."""
        self._history.clear()
    
    def __len__(self) -> int:
        """Return number of feedback entries."""
        return len(self._history)
    
    def __bool__(self) -> bool:
        """Return True if history is non-empty."""
        return bool(self._history)
