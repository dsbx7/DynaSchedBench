"""Baseline heuristic implementations for scheduling rule generation.

This module provides concrete implementations of classic scheduling heuristics
that can be included in LLM prompts to provide context and examples for
code generation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class BaselineHeuristicLibrary:
    """Library of classic scheduling heuristic implementations.
    
    This class provides access to well-known scheduling heuristics that can be
    used as reference implementations in LLM prompts for rule generation.
    """
    
    # Dictionary mapping heuristic names to their implementations
    _HEURISTICS: Dict[str, str] = {}
    
    @classmethod
    def get_heuristic_code(cls, name: str) -> Optional[str]:
        """Get Python code for a named heuristic.
        
        Args:
            name: Name of the heuristic (e.g., "SPT", "EDD", "FIFO")
            
        Returns:
            Python code string for the heuristic, or None if not found
        """
        return cls._HEURISTICS.get(name.upper())
    
    @classmethod
    def get_relevant_heuristics(
        cls,
        baseline_name: str,
        max_count: int = 3
    ) -> List[Tuple[str, str]]:
        """Get relevant heuristics based on baseline name.
        
        This method returns heuristics that are most relevant to the given
        baseline name. If the baseline name matches a known heuristic, that
        heuristic is returned first, followed by related heuristics.
        
        Args:
            baseline_name: Name of the baseline rule being used
            max_count: Maximum number of heuristics to return
            
        Returns:
            List of (name, code) tuples for relevant heuristics
        """
        baseline_upper = baseline_name.upper()
        results: List[Tuple[str, str]] = []
        
        # First, check if baseline name directly matches a heuristic
        if baseline_upper in cls._HEURISTICS:
            results.append((baseline_upper, cls._HEURISTICS[baseline_upper]))
        
        # Define relevance groups - heuristics that work well together
        relevance_groups = {
            "SPT": ["SPT", "LPT", "FIFO"],
            "LPT": ["LPT", "SPT", "LIFO"],
            "FIFO": ["FIFO", "SPT", "EDD"],
            "LIFO": ["LIFO", "LPT", "EDD"],
            "EDD": ["EDD", "MST", "CR"],
            "MST": ["MST", "EDD", "CR"],
            "ATC": ["ATC", "CR", "EDD"],
            "CR": ["CR", "ATC", "MST"],
        }
        
        # Get related heuristics
        related = relevance_groups.get(baseline_upper, ["SPT", "FIFO", "EDD"])
        
        # Add related heuristics that aren't already in results
        for heuristic_name in related:
            if len(results) >= max_count:
                break
            if heuristic_name in cls._HEURISTICS:
                # Check if not already added
                if not any(name == heuristic_name for name, _ in results):
                    results.append((heuristic_name, cls._HEURISTICS[heuristic_name]))
        
        # If we still need more, add any remaining heuristics
        if len(results) < max_count:
            for name, code in cls._HEURISTICS.items():
                if len(results) >= max_count:
                    break
                if not any(n == name for n, _ in results):
                    results.append((name, code))
        
        return results[:max_count]
    
    @classmethod
    def get_all_heuristic_names(cls) -> List[str]:
        """Get names of all available heuristics.
        
        Returns:
            List of heuristic names
        """
        return sorted(cls._HEURISTICS.keys())


# Register heuristic implementations
# Each implementation is a complete Python function that can be used as a priority rule

_COMMON_HELPERS = '''def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return float(default)


def _find_ready_op(obs, job_id: str, machine_group: str, *, allow_fallback_any_group: bool = False):
    ready_ops = obs.get("ready_ops", []) or []
    ready_op = None
    for ro in ready_ops:
        if str(ro.get("job_id")) != str(job_id):
            continue
        if not machine_group or str(ro.get("machine_group")) == str(machine_group):
            return ro
        if allow_fallback_any_group and ready_op is None:
            ready_op = ro
    return ready_op
'''

BaselineHeuristicLibrary._HEURISTICS["SPT"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """Shortest Processing Time (SPT) heuristic.
    
    Prioritizes operations with shorter processing times.
    This heuristic minimizes average flow time and is optimal for
    minimizing mean completion time in single-machine scheduling.
    """
    # Extract identifiers from action
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))
    machine_id = str(action.get("machine_id", ""))
    
    ready_op = _find_ready_op(obs, job_id, machine_group)
    
    if ready_op is None:
        return 0.0
    
    # Get processing time (machine-specific if available)
    proc_time_by_machine = ready_op.get("proc_time_by_machine", {})
    if machine_id and machine_id in proc_time_by_machine:
        processing_time = _safe_float(proc_time_by_machine[machine_id], 0.0)
    else:
        processing_time = _safe_float(ready_op.get("process_time", 0.0), 0.0)
    
    # Return negative processing time (shorter times get higher priority)
    return -processing_time
'''

BaselineHeuristicLibrary._HEURISTICS["LPT"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """Longest Processing Time (LPT) heuristic.
    
    Prioritizes operations with longer processing times.
    This heuristic is useful for load balancing in parallel machine
    scheduling and can minimize makespan in some scenarios.
    """
    # Extract identifiers from action
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))
    machine_id = str(action.get("machine_id", ""))

    ready_op = _find_ready_op(obs, job_id, machine_group)
    
    if ready_op is None:
        return 0.0
    
    # Get processing time (machine-specific if available)
    proc_time_by_machine = ready_op.get("proc_time_by_machine", {})
    if machine_id and machine_id in proc_time_by_machine:
        processing_time = _safe_float(proc_time_by_machine[machine_id], 0.0)
    else:
        processing_time = _safe_float(ready_op.get("process_time", 0.0), 0.0)
    
    # Return processing time directly (longer times get higher priority)
    return processing_time
'''

BaselineHeuristicLibrary._HEURISTICS["FIFO"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """First In First Out (FIFO) heuristic.
    
    Prioritizes jobs based on their arrival order.
    Uses job release/arrival time from obs.ready_ops when available.
    """
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))

    ready_op = _find_ready_op(obs, job_id, machine_group, allow_fallback_any_group=True)

    arrival = None
    if isinstance(ready_op, dict):
        arrival = ready_op.get("release_time", None)
        if arrival is None:
            arrival = ready_op.get("arrival_time", None)

    if arrival is None:
        arrival = action.get("arrival_time", None)
    if arrival is None:
        arrival = action.get("release_time", None)
    if arrival is None:
        arrival = action.get("job_id", 0)

    arrival_t = _safe_float(arrival, 0.0)

    # Earlier arrival -> higher priority => return negative time
    return -arrival_t
'''

BaselineHeuristicLibrary._HEURISTICS["LIFO"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """Last In First Out (LIFO) heuristic.
    
    Prioritizes jobs that arrived most recently.
    Uses job release/arrival time from obs.ready_ops when available.
    """
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))

    ready_op = _find_ready_op(obs, job_id, machine_group, allow_fallback_any_group=True)

    arrival = None
    if isinstance(ready_op, dict):
        arrival = ready_op.get("release_time", None)
        if arrival is None:
            arrival = ready_op.get("arrival_time", None)

    if arrival is None:
        arrival = action.get("arrival_time", None)
    if arrival is None:
        arrival = action.get("release_time", None)
    if arrival is None:
        arrival = action.get("job_id", 0)

    arrival_t = _safe_float(arrival, 0.0)

    # Later arrival -> higher priority
    return arrival_t
'''

BaselineHeuristicLibrary._HEURISTICS["EDD"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """Earliest Due Date (EDD) heuristic.
    
    Prioritizes jobs with earlier due dates.
    Falls back to remaining work if due dates are not available.
    """
    # Extract identifiers from action
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))

    ready_op = _find_ready_op(obs, job_id, machine_group)
    
    if ready_op is None:
        return 0.0
    
    # Try to get due date from ready_op or job info
    due_date = ready_op.get("due_date", None)
    if due_date is None:
        # Fallback: use remaining work as proxy (less remaining work = higher priority)
        remaining_work = _safe_float(ready_op.get("remaining_work", 0.0), 0.0)
        return -remaining_work
    
    # Return negative due date (earlier due dates get higher priority)
    return -_safe_float(due_date, 0.0)
'''

BaselineHeuristicLibrary._HEURISTICS["MST"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """Minimum Slack Time (MST) heuristic.
    
    Prioritizes jobs with the least slack time.
    Falls back to remaining work if due dates are not available.
    """
    # Extract identifiers from action
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))
    
    current_time = obs.get("time", 0.0)

    ready_op = _find_ready_op(obs, job_id, machine_group)
    
    if ready_op is None:
        return 0.0
    
    # Get remaining work
    remaining_work = _safe_float(ready_op.get("remaining_work", 0.0), 0.0)
    
    # Try to get due date
    due_date = ready_op.get("due_date", None)
    if due_date is None:
        # Fallback: use remaining work (less remaining work = higher priority)
        return -remaining_work
    
    # Calculate slack time: time until due date minus remaining work
    slack_time = _safe_float(due_date, 0.0) - _safe_float(current_time, 0.0) - remaining_work
    
    # Return negative slack (less slack = higher priority)
    return -slack_time
'''

BaselineHeuristicLibrary._HEURISTICS["ATC"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """Apparent Tardiness Cost (ATC) heuristic.
    
    A sophisticated heuristic that balances processing time and due date urgency.
    Falls back to SPT if due dates are not available.
    """
    import math
    
    # Extract identifiers from action
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))
    machine_id = str(action.get("machine_id", ""))
    
    # Get current time
    current_time = obs.get("time", 0.0)

    ready_op = _find_ready_op(obs, job_id, machine_group)
    
    if ready_op is None:
        return 0.0
    
    # Get processing time (machine-specific if available)
    proc_time_by_machine = ready_op.get("proc_time_by_machine", {})
    if machine_id and machine_id in proc_time_by_machine:
        processing_time = _safe_float(proc_time_by_machine[machine_id], 1.0)
    else:
        processing_time = _safe_float(ready_op.get("process_time", 1.0), 1.0)
    
    # Get priority/weight
    weight = _safe_float(ready_op.get("priority", 1.0), 1.0)
    if weight == 0.0:
        weight = 1.0
    
    # Try to get due date
    due_date = ready_op.get("due_date", None)
    if due_date is None:
        # Fallback to SPT if no due date
        if processing_time > 0:
            return weight / processing_time
        return weight
    
    # Calculate slack time
    slack = max(_safe_float(due_date, 0.0) - _safe_float(current_time, 0.0) - processing_time, 0.0)
    
    # ATC look-ahead parameter
    k = 2.0
    avg_processing_time = processing_time  # Simplified
    
    # Calculate ATC priority
    if processing_time > 0 and avg_processing_time > 0:
        priority = (weight / processing_time) * math.exp(-slack / (k * avg_processing_time))
    else:
        priority = weight
    
    return priority
'''

BaselineHeuristicLibrary._HEURISTICS["CR"] = _COMMON_HELPERS + '''def optimized_priority(obs, action, env) -> float:
    """Critical Ratio (CR) heuristic.
    
    Prioritizes jobs based on the ratio of time remaining until due date
    to the remaining processing time. Falls back to remaining work if no due dates.
    """
    # Extract identifiers from action
    job_id = str(action.get("job_id", ""))
    machine_group = str(action.get("machine_group", ""))
    
    # Get current time
    current_time = obs.get("time", 0.0)

    ready_op = _find_ready_op(obs, job_id, machine_group)
    
    if ready_op is None:
        return 0.0
    
    # Get remaining work
    remaining_work = _safe_float(ready_op.get("remaining_work", 1.0), 1.0)
    if remaining_work <= 0:
        remaining_work = 1.0
    
    # Try to get due date
    due_date = ready_op.get("due_date", None)
    if due_date is None:
        # Fallback: use remaining work (less remaining work = higher priority)
        return -remaining_work
    
    # Calculate time remaining until due date
    time_until_due = _safe_float(due_date, 0.0) - _safe_float(current_time, 0.0)
    
    # Calculate critical ratio
    critical_ratio = time_until_due / remaining_work
    
    # Return negative critical ratio (lower ratio = higher priority)
    return -critical_ratio
'''
