"""Validation helpers for generated DynaSchedBench instances."""

from typing import List, Tuple, Dict, Set
from ..models.events import Event, ArrivalEvent, DueDateEvent, BreakdownEvent, PreventiveMaintenanceEvent
from ..models.inputs import InputModel
from loguru import logger


class InstanceValidator:
    """Validate generated instances for structural and temporal consistency."""
    
    def __init__(self, model: InputModel, events: List[Event]):
        self.model = model
        # Keep a reference to the original event ordering for diagnostics,
        # but use a canonically sorted view (time, priority) for checks that
        # rely on temporal semantics.
        self._original_events = list(events)
        self.events = sorted(
            events,
            key=lambda e: (float(e.time), getattr(e, "priority", 100)),
        )
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def validate(self) -> Tuple[bool, List[str], List[str]]:
        """Validate instance completeness and consistency.
        
        Returns:
            (is_valid, errors, warnings)
        """
        self._check_event_times()
        self._check_job_routing()
        self._check_machine_ids()
        self._check_due_dates()
        self._check_event_ordering()
        self._check_downtime_events()
        
        is_valid = len(self.errors) == 0
        
        if not is_valid:
            logger.error(f"Instance validation FAILED with {len(self.errors)} errors:")
            for err in self.errors[:10]:  # Show first 10 errors
                logger.error(f"   • {err}")
            if len(self.errors) > 10:
                logger.error(f"   ... and {len(self.errors) - 10} more errors")
        else:
            logger.info("Instance validation passed")
        
        if self.warnings:
            logger.warning(f"Instance validation found {len(self.warnings)} warnings:")
            for warn in self.warnings[:5]:  # Show first 5 warnings
                logger.warning(f"   • {warn}")
            if len(self.warnings) > 5:
                logger.warning(f"   ... and {len(self.warnings) - 5} more warnings")
        
        return is_valid, self.errors, self.warnings
    
    def _check_event_times(self):
        """Check whether event times and durations are reasonable."""
        horizon = self.model.scale.horizon
        
        for event in self.events:
            if event.time < 0:
                self.errors.append(f"Event {event.event_type} has negative time: {event.time:.4f}")
            
            if event.time > horizon * 1.01:
                self.warnings.append(
                    f"Event {event.event_type} at time {event.time:.2f} exceeds horizon {horizon:.2f}"
                )
            
            if hasattr(event, 'duration'):
                if event.duration < 0:
                    self.errors.append(
                        f"Event {event.event_type} at time {event.time:.4f} has negative duration: {event.duration:.4f}"
                    )
                elif event.duration == 0:
                    self.warnings.append(
                        f"Event {event.event_type} at time {event.time:.4f} has zero duration"
                    )
    
    def _check_job_routing(self):
        """Check whether job routes and processing times are valid."""
        arrivals = [e for e in self.events if isinstance(e, ArrivalEvent)]
        
        valid_groups = {m.group for m in self.model.plant.machines}
        
        for arr in arrivals:
            if not arr.routing:
                self.errors.append(f"Job {arr.job_id} has empty routing")
                continue
            
            if not arr.process_times:
                self.errors.append(f"Job {arr.job_id} has empty process_times")
                continue
            
            if len(arr.routing) != len(arr.process_times):
                self.errors.append(
                    f"Job {arr.job_id} routing/process_times length mismatch: "
                    f"{len(arr.routing)} vs {len(arr.process_times)}"
                )
            
            for i, pt in enumerate(arr.process_times):
                if pt <= 0:
                    self.errors.append(
                        f"Job {arr.job_id} step {i} has non-positive process time: {pt:.4f}"
                    )
                elif pt > 10000:
                    self.warnings.append(
                        f"Job {arr.job_id} step {i} has unusually large process time: {pt:.2f}"
                    )
            
            for i, group in enumerate(arr.routing):
                if group not in valid_groups:
                    self.errors.append(
                        f"Job {arr.job_id} step {i} references non-existent machine group: '{group}'"
                    )
    
    def _check_machine_ids(self):
        """Check whether events reference existing machine IDs."""
        valid_machine_ids = {m.id for m in self.model.plant.machines}
        
        for event in self.events:
            if hasattr(event, 'machine_id') and event.machine_id is not None:
                if event.machine_id not in valid_machine_ids:
                    self.errors.append(
                        f"Event {event.event_type} at time {event.time:.2f} references "
                        f"non-existent machine: '{event.machine_id}'"
                    )
    
    def _check_due_dates(self):
        """Check whether due dates are causally and numerically reasonable."""
        arrivals_dict = {e.job_id: e for e in self.events if isinstance(e, ArrivalEvent)}
        due_dates = [e for e in self.events if isinstance(e, DueDateEvent)]
        
        violation_count = 0
        tight_count = 0
        
        for dd in due_dates:
            if dd.job_id not in arrivals_dict:
                self.warnings.append(f"Due date event for non-existent job: {dd.job_id}")
                continue
            
            arrival = arrivals_dict[dd.job_id]
            total_process_time = sum(arrival.process_times) if arrival.process_times else 0.0
            slack = dd.due_date - arrival.time
            
            if dd.due_date < arrival.time:
                self.errors.append(
                    f"Job {dd.job_id} due date {dd.due_date:.2f} is before arrival time {arrival.time:.2f}"
                )
                violation_count += 1
                continue
            
            min_required_slack = total_process_time * 1.05
            eps = max(1e-6, total_process_time * 1e-6)
            if slack < total_process_time - eps:
                self.errors.append(
                    f"Job {dd.job_id} slack ({slack:.2f}) is less than total process time ({total_process_time:.2f})"
                )
                violation_count += 1
            elif slack < min_required_slack:
                self.warnings.append(
                    f"Job {dd.job_id} has very tight due date: slack={slack:.2f}, "
                    f"total_process_time={total_process_time:.2f} (min recommended: {min_required_slack:.2f})"
                )
                tight_count += 1
            
            horizon = self.model.scale.horizon
            if dd.due_date > horizon * 1.5:
                self.warnings.append(
                    f"Job {dd.job_id} due date {dd.due_date:.2f} is far beyond horizon {horizon:.2f}"
                )
            
            if abs(dd.due_date - arrival.time) < 1e-6:
                self.errors.append(
                    f"Job {dd.job_id} due date equals arrival time (zero slack)"
                )
                violation_count += 1
        
        if violation_count > 0:
            logger.debug(f"Due date validation: found {violation_count} critical violations")
        if tight_count > 0:
            logger.debug(f"Due date validation: found {tight_count} tight but acceptable due dates")
    
    def _check_event_ordering(self):
        """Check event ordering.

        Two levels are checked: non-decreasing time and canonical ordering by
        ``(time, priority)``.
        """
        prev_time = -float("inf")
        out_of_order_count = 0

        for event in self._original_events:
            if event.time < prev_time:
                out_of_order_count += 1
                if out_of_order_count <= 3:  # Only report first 3
                    self.warnings.append(
                        f"Events not sorted by time: {event.event_type} at {event.time:.4f} "
                        f"after event at {prev_time:.4f}"
                    )
            prev_time = event.time

        if out_of_order_count > 3:
            self.warnings.append(
                f"... and {out_of_order_count - 3} more out-of-order events"
            )

        sorted_by_key = sorted(
            self._original_events,
            key=lambda e: (float(e.time), getattr(e, "priority", 100)),
        )
        if sorted_by_key != self._original_events:
            self.warnings.append(
                "Events are not sorted by (time, priority); the simulator will internally "
                "reorder them to obtain deterministic semantics for simultaneous events."
            )
    
    def _check_downtime_events(self):
        """Check whether breakdown and maintenance events are reasonable."""
        downtime_by_machine: Dict[str, List[Tuple[float, float, str]]] = {}
        
        for event in self.events:
            if isinstance(event, (BreakdownEvent, PreventiveMaintenanceEvent)):
                machine_id = event.machine_id
                if machine_id not in downtime_by_machine:
                    downtime_by_machine[machine_id] = []
                
                end_time = event.time + event.duration
                event_type = "BD" if isinstance(event, BreakdownEvent) else "PM"
                downtime_by_machine[machine_id].append((event.time, end_time, event_type))
        
        for machine_id, intervals in downtime_by_machine.items():
            sorted_intervals = sorted(intervals, key=lambda x: x[0])
            
            for i in range(len(sorted_intervals) - 1):
                curr_start, curr_end, curr_type = sorted_intervals[i]
                next_start, next_end, next_type = sorted_intervals[i + 1]
                
                if next_start < curr_end:
                    overlap = curr_end - next_start
                    self.warnings.append(
                        f"Machine {machine_id} has overlapping downtime: "
                        f"{curr_type}[{curr_start:.2f}-{curr_end:.2f}] overlaps with "
                        f"{next_type}[{next_start:.2f}-{next_end:.2f}] by {overlap:.2f} time units"
                    )
        
        horizon = self.model.scale.horizon
        for machine_id, intervals in downtime_by_machine.items():
            if not intervals:
                continue
            
            sorted_intervals = sorted(intervals, key=lambda x: x[0])
            merged = []
            for start, end, _ in sorted_intervals:
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            
            total_downtime = sum(end - start for start, end in merged)
            downtime_ratio = total_downtime / horizon
            
            if downtime_ratio > 0.9:
                self.warnings.append(
                    f"Machine {machine_id} has excessive downtime: {downtime_ratio:.1%} of horizon"
                )
