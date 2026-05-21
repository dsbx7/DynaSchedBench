"""Shared utility helpers for generator calibration and validation."""
from typing import List, Dict, Union
import numpy as np
from ..models.events import Event


def calculate_relative_error(
    target: float, 
    observed: float, 
    zero_threshold: float = 1e-6
) -> float:
    """Compute relative error with robust handling for zero targets.
    
    Args:
        target: Target value.
        observed: Observed value.
        zero_threshold: Absolute threshold used to treat the target as zero.
    
    Returns:
        Relative error as a ratio, or absolute observed error for near-zero
        targets.
    
    Examples:
        >>> calculate_relative_error(10.0, 10.5)
        0.05
        >>> calculate_relative_error(0.0, 0.1)
        0.1
    """
    if abs(target) < zero_threshold:
        return abs(observed)
    else:
        return abs(observed - target) / abs(target)


def calculate_absolute_error(target: float, observed: float) -> float:
    """Compute absolute error.
    
    Args:
        target: Target value.
        observed: Observed value.
        
    Returns:
        Absolute error.
    """
    return abs(observed - target)


def apply_damping(current: float, target: float, damping: float) -> float:
    """Move a value toward a target with damping.
    
    Args:
        current: Current value.
        target: Target value.
        damping: Damping coefficient in [0, 1], where 0 means no adjustment and
            1 means moving directly to the target.
    
    Returns:
        Adjusted value.
        
    Examples:
        >>> apply_damping(10.0, 20.0, 0.5)
        15.0
        >>> apply_damping(10.0, 20.0, 1.0)
        20.0
    """
    delta = target - current
    damped_delta = delta * damping
    return current + damped_delta


def apply_ratio_with_damping(current: float, ratio: float, damping: float) -> float:
    """Apply a multiplicative ratio with damping.
    
    Args:
        current: Current value.
        ratio: Target multiplicative ratio.
        damping: Damping coefficient.
        
    Returns:
        Adjusted value.
        
    Examples:
        >>> apply_ratio_with_damping(10.0, 2.0, 0.5)
        15.0  # 10 * (1 + (2.0 - 1.0) * 0.5)
    """
    return current * (1.0 + (ratio - 1.0) * damping)


def sort_events_by_time(events: List[Event]) -> List[Event]:
    """Sort events by time while preserving deterministic tie behavior.
    
    Args:
        events: Event list.
        
    Returns:
        Sorted event list.
        
    Note:
        ``heapq.nsmallest`` is used as a stable deterministic ordering helper.
    """
    import heapq
    indexed_events = [(e.time, e.event_type, idx, e) for idx, e in enumerate(events)]
    sorted_indexed = heapq.nsmallest(len(indexed_events), indexed_events, key=lambda x: (x[0], x[1], x[2]))
    return [item[3] for item in sorted_indexed]


def clip_to_range(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value to an inclusive range.
    
    Args:
        value: Value to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.
        
    Returns:
        Clamped value.
        
    Examples:
        >>> clip_to_range(15.0, 10.0, 20.0)
        15.0
        >>> clip_to_range(5.0, 10.0, 20.0)
        10.0
    """
    return max(min_val, min(max_val, value))


def validate_weights(weights: List[float], tolerance: float = 0.01) -> bool:
    """Validate a list of non-negative weights that should sum to one.
    
    Args:
        weights: Weight list.
        tolerance: Allowed absolute error in the weight sum.
        
    Returns:
        True if the weights are valid.
        
    Examples:
        >>> validate_weights([0.3, 0.7])
        True
        >>> validate_weights([0.3, 0.8])
        False
    """
    if not weights:
        return False
    if any(w < 0 for w in weights):
        return False
    if abs(sum(weights) - 1.0) > tolerance:
        return False
    return True


def normalize_weights(weights: List[float]) -> List[float]:
    """Normalize weights so they sum to one.
    
    Args:
        weights: Raw weight list.
        
    Returns:
        Normalized weight list.
        
    Examples:
        >>> normalize_weights([1, 2, 3])
        [0.1667, 0.3333, 0.5]
    """
    total = sum(weights)
    if total == 0:
        n = len(weights)
        return [1.0 / n] * n if n > 0 else []
    return [w / total for w in weights]


def calculate_cv(values: List[float]) -> float:
    """Compute the coefficient of variation.
    
    CV = std / mean
    
    Args:
        values: Numeric values.
        
    Returns:
        Coefficient of variation.
    """
    if len(values) < 2:
        return 0.0
    
    mean_val = np.mean(values)
    std_val = np.std(values)
    
    if abs(mean_val) < 1e-9:
        return 0.0
    
    return float(std_val / mean_val)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide safely, returning a default value for near-zero denominators.
    
    Args:
        numerator: Numerator.
        denominator: Denominator.
        default: Value returned when the denominator is near zero.
        
    Returns:
        Division result or default value.
    """
    if abs(denominator) < 1e-9:
        return default
    return numerator / denominator


def round_value(value: float, precision: int = 4) -> float:
    """Round a numeric value to a fixed precision.
    
    Args:
        value: Value to round.
        precision: Number of decimal places.
        
    Returns:
        Rounded value.
    """
    return float(np.round(value, precision))


def calculate_l2_norm(errors: List[float]) -> float:
    """Compute the root-mean-square L2 norm of errors.
    
    Args:
        errors: Error values.
        
    Returns:
        L2 norm.
    """
    if not errors:
        return 0.0
    return float(np.sqrt(np.mean([e ** 2 for e in errors])))


def calculate_mean_error(errors: Dict[str, float]) -> float:
    """Compute the mean error across metrics.
    
    Args:
        errors: Mapping from metric name to error value.
        
    Returns:
        Mean error.
    """
    if not errors:
        return 0.0
    return float(np.mean(list(errors.values())))


def extract_scalar_from_batchable(value: Union[float, List[float]]) -> float:
    """Extract a scalar from a batchable float or float list.
    
    Args:
        value: Single float or list of floats.
        
    Returns:
        Scalar float.
    """
    if isinstance(value, list):
        return float(value[0]) if value else 0.0
    return float(value)


def is_zero_target(value: float, threshold: float = 1e-6) -> bool:
    """Return whether a target value should be treated as zero.
    
    Args:
        value: Target value.
        threshold: Absolute threshold.
        
    Returns:
        True if the value is near zero.
    """
    return abs(value) < threshold


