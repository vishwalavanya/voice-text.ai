from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field


logger = logging.getLogger("voice_agent_latency")


@dataclass
class LatencyTracker:
    session_id: str
    turn_id: str
    started_at: float = field(default_factory=time.perf_counter)
    stages_ms: dict[str, float] = field(default_factory=dict)

    def start_stage(self) -> float:
        return time.perf_counter()

    def end_stage(self, stage_name: str, stage_started_at: float) -> float:
        value = round((time.perf_counter() - stage_started_at) * 1000, 2)
        self.stages_ms[stage_name] = value
        return value

    def total_ms(self) -> float:
        return round((time.perf_counter() - self.started_at) * 1000, 2)

    def log_summary(self, extra: dict[str, str] | None = None) -> None:
        payload: dict[str, object] = {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "latency_ms": self.stages_ms,
            "total_pipeline_latency_ms": self.total_ms(),
        }
        if extra:
            payload.update(extra)
        logger.info(json.dumps(payload, ensure_ascii=True))

