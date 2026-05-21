"""PDR (Priority Dispatching Rules) solver for dynamic job shop scheduling.

This package implements various priority-based heuristic rules for scheduling,
compatible with the DynaSchedBench framework.

Supported job selection rules:
- SPT: Shortest Processing Time
- LPT: Longest Processing Time  
- MWKR: Most Work Remaining
- LWKR: Least Work Remaining
- MOPNR: Most Operations Remaining  
- LOPNR: Least Operations Remaining
- FIFO: First In First Out
- LIFO: Last In First Out

Supported machine selection rules:
- LIT: Least Idle Time (earliest available)
- LWL: Least Workload
- SPT: Shortest Processing Time on machine
"""

from .agent import PDRAgent
from .rules import (
    JobSelectionRule,
    MachineSelectionRule,
    compute_job_priority,
    select_best_machine,
)

__all__ = [
    "PDRAgent",
    "JobSelectionRule",
    "MachineSelectionRule",
    "compute_job_priority",
    "select_best_machine",
]
