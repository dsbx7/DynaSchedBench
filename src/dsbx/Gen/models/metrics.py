import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class MetricsTrace(BaseModel):
    time: List[float]
    global_utilization: List[float]
    wip: List[int]
    bottleneck_utilization: Dict[str, List[float]]

class FinalReportData(BaseModel):
    input_hash: str
    version: str
    seed_map: Dict[str, int]
    target_metrics: Dict[str, float]
    observed_metrics: Dict[str, float]
    errors: Dict[str, float]
    projections: List[str]
    generation_timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    ssi: Dict[str, float] = Field({}, description="Structural Stress Index (C, P, K, S)")
    ssi_norm: Dict[str, float] = Field({}, description="Normalized SSI in [0,1] for each dimension.")
    difficulty_score: float = Field(0.0, description="Overall instance difficulty score in [0,100].")
    difficulty_category: str = Field("medium", description="Categorical difficulty level: easy/medium/hard.")
    comparison_report: Optional[str] = Field(None, description="Report comparing this run to a previous one.")