from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json


PathLike = Union[str, Path]


@dataclass
class TrajectoryLogger:
    records: List[Dict[str, Any]] = field(default_factory=list)
    file_path: Optional[PathLike] = None

    def __post_init__(self) -> None:
        if self.file_path is None:
            return
        p = Path(self.file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
        self.file_path = p

    def append(self, record: Dict[str, Any]) -> None:
        if self.file_path is not None:
            p = Path(self.file_path)
            with p.open("a", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False)
                f.write("\n")
            return
        self.records.append(record)

    def to_list(self) -> List[Dict[str, Any]]:
        if self.file_path is not None:
            out: List[Dict[str, Any]] = []
            p = Path(self.file_path)
            if not p.is_file():
                return out
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        out.append(obj)
            return out
        return list(self.records)

    def path_str(self) -> Optional[str]:
        if self.file_path is None:
            return None
        return str(Path(self.file_path))

    def dump_jsonl(self, path: PathLike, append: bool = True) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append and p.exists() else "w"
        with p.open(mode, encoding="utf-8") as f:
            for rec in self.records:
                json.dump(rec, f, ensure_ascii=False)
                f.write("\n")

