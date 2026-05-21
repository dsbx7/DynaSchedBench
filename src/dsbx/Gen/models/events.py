"""Event models used by the DynaSchedBench generator."""

from typing import Literal, List, Optional, Union
from pydantic import BaseModel, Field


# Event priority mapping for deterministic ordering of simultaneous events.
# Lower numbers are processed earlier when sorting by (time, priority).
_EVENT_PRIORITY = {
    "REPAIR_COMPLETION": 0,
    "ARRIVAL": 1,
    "PTIME_CHANGE": 2,
    "ROUTE_CHANGE": 3,
    "PRIORITY_CHANGE": 4,
    "DUE_DATE_SET": 5,
    "DUE_DATE_CHANGE": 6,
    "ORDER_CANCELLATION": 7,
    "PREVENTIVE_MAINTENANCE": 8,
    "BREAKDOWN": 9,
}


class BaseEvent(BaseModel):
    """The base model for any event, ensuring it has a time and a type."""
    time: float = Field(..., description="Timestamp of the event.")
    event_type: str

    @property
    def priority(self) -> int:
        """Priority used for tie-breaking when multiple events share the same time.

        This is not serialized; it is purely for simulator/validator internal logic.
        """
        return _EVENT_PRIORITY.get(self.event_type, 100)


class ArrivalEvent(BaseEvent):
    """Event representing the arrival of a new job."""
    event_type: Literal["ARRIVAL"] = "ARRIVAL"
    job_id: str
    job_family: str
    routing: List[str]
    process_times: List[float]
    batch_id: Optional[str] = None  # Batch identifier for batch arrivals
    arrival_type: Literal["planned", "initial_wip", "emergency", "dynamic"] = "planned"

class DueDateEvent(BaseEvent):
    """Event for setting a job's due date, known at arrival time."""
    event_type: Literal["DUE_DATE_SET"] = "DUE_DATE_SET"
    job_id: str
    due_date: float

class BreakdownEvent(BaseEvent):
    """Event representing a machine breakdown."""
    event_type: Literal["BREAKDOWN"] = "BREAKDOWN"
    machine_id: str
    duration: float

# class CapacityEditEvent(BaseEvent):
#     """Event to change the capacity of a resource (e.g., add/remove workers)."""
#     event_type: Literal["CAPACITY_EDIT"] = "CAPACITY_EDIT"
#     machine_id: str
#     new_capacity: int

# --- 👇 New Dynamic Event Models ---

class PriorityChangeEvent(BaseEvent):
    """Event to dynamically change the priority of a job."""
    event_type: Literal["PRIORITY_CHANGE"] = "PRIORITY_CHANGE"
    job_id: str
    new_priority: int  # Lower number means higher priority

class OrderCancellationEvent(BaseEvent):
    """Event representing the cancellation of an already arrived job."""
    event_type: Literal["ORDER_CANCELLATION"] = "ORDER_CANCELLATION"
    job_id: str

class MachineRepairCompletionEvent(BaseEvent):
    """
    Represents an event where a machine that is currently down for a random
    breakdown is repaired *earlier* than expected, effectively reducing its downtime.
    """
    event_type: Literal["REPAIR_COMPLETION"] = "REPAIR_COMPLETION"
    machine_id: str

class ProcessTimeChangeEvent(BaseEvent):
    """
    Represents a sudden change to the processing time of a specific operation
    for a job that is already in the system.
    """
    event_type: Literal["PTIME_CHANGE"] = "PTIME_CHANGE"
    job_id: str
    step_index: int # The index of the operation in the job's route
    new_process_time: float

class PreventiveMaintenanceEvent(BaseEvent):
    """
    Event representing scheduled preventive maintenance on a machine.
    Unlike random breakdowns, preventive maintenance is predictable and scheduled.
    """
    event_type: Literal["PREVENTIVE_MAINTENANCE"] = "PREVENTIVE_MAINTENANCE"
    machine_id: str
    duration: float
    maintenance_type: Literal["time_based", "usage_based"] = "time_based"

class RouteChangeEvent(BaseEvent):
    """
    Event representing a change in a job's routing (process plan).
    This can happen due to machine unavailability, rush orders, or quality issues.
    """
    event_type: Literal["ROUTE_CHANGE"] = "ROUTE_CHANGE"
    job_id: str
    new_routing: List[str]  # New machine group sequence
    new_process_times: List[float]  # New processing times
    from_step: int = 0  # From which step to apply the new route (0 = replace all remaining)

class DueDateChangeEvent(BaseEvent):
    """
    Event representing a change in a job's due date.
    This can happen due to customer requests, urgent orders, or schedule changes.
    """
    event_type: Literal["DUE_DATE_CHANGE"] = "DUE_DATE_CHANGE"
    job_id: str
    new_due_date: float
    reason: str = "customer_request"  # customer_request, urgent, relaxed, etc.

# Note: Rework is not modeled as an externally injected event.
# It is a probabilistic outcome of a process, so it will be handled
# inside the simulator's logic, triggered by a process completion.

# The Union of all possible events that the system can handle.
Event = Union[
    ArrivalEvent,
    DueDateEvent,
    BreakdownEvent,
    # CapacityEditEvent,
    PriorityChangeEvent,
    OrderCancellationEvent,
    MachineRepairCompletionEvent,
    ProcessTimeChangeEvent,
    PreventiveMaintenanceEvent,
    RouteChangeEvent,
    DueDateChangeEvent,
]
