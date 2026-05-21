from pathlib import Path
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter, AdapterConfig
from .events_parser import EventsParser
from .output_formatter import OutputFormatter


class LLMAdapter(BaseAdapter):
    def __init__(self, config: AdapterConfig, o_type: str = "O1", s_type: str = "S1",
                 provider: str = "none", model_name: Optional[str] = None, base_url: Optional[str] = None,
                 temperature: float = 0.0, top_p: float = 1.0, top_k: int = 0, n: int = 1):
        super().__init__(config)
        self._events_path: Optional[Path] = None
        self._parser: Optional[EventsParser] = None
        self.o_type = o_type
        self.s_type = s_type
        self.provider = provider
        self.model_name = model_name
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.n = n

    def load_events(self, events_path: Path) -> None:
        super().load_events(events_path)
        self._events_path = Path(events_path)
        self._parser = EventsParser(self._events_path)

    def to_algorithm_format(self) -> Dict[str, Any]:
        return {
            "events_path": str(self._events_path) if self._events_path else None,
            "o_type": self.o_type,
            "s_type": self.s_type,
            "provider": self.provider,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "n": self.n,
        }

    def run(self, output_path: Optional[Path] = None) -> Dict[str, Any]:
        from algorithms.llm_scheduler import solve, OType, SType, ModelConfig, SampleConfig
        if not self._events_path:
            raise RuntimeError("events not loaded")
        o = OType[self.o_type]
        s = SType[self.s_type]
        mc = ModelConfig(provider=self.provider, model_name=self.model_name, base_url=self.base_url)
        sc = SampleConfig(temperature=self.temperature, top_p=self.top_p, top_k=self.top_k, n=self.n)
        return solve(self._events_path, o, s, model_cfg=mc, sample_cfg=sc, output_path=output_path)

    def from_algorithm_output(self, output: Any) -> Dict[str, Any]:
        algo = self.config.algorithm_name
        fmt = OutputFormatter(algo)
        if isinstance(output, dict) and "gantt" in output and "metrics" in output:
            return {
                "gantt": fmt.format_gantt(output["gantt"]),
                "metrics": output["metrics"],
                "algorithm": algo,
            }
        gantt = []
        if isinstance(output, list):
            gantt = output
        jobs_info = self._parser.get_jobs_info() if self._parser else {}
        gantt_f = fmt.format_gantt(gantt)
        metrics = fmt.format_metrics(gantt_f, jobs_info)
        return {"gantt": gantt_f, "metrics": metrics, "algorithm": algo}
