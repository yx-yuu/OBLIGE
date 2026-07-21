from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edos.jsonutil import to_jsonable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunLogger:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.controller_trace_path = self.run_dir / "controller_trace.jsonl"
        self.trajectory_path = self.run_dir / "trajectory.jsonl"
        for path in [self.events_path, self.controller_trace_path, self.trajectory_path]:
            path.write_text("", encoding="utf-8")

    def write_json(self, name: str, value: Any) -> None:
        path = self.run_dir / name
        with path.open("w", encoding="utf-8") as handle:
            json.dump(to_jsonable(value), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def append_event(self, event: dict[str, Any]) -> None:
        defaults = {
            "schema_version": "1.0",
            "controller_state": "",
            "theory_source": "none",
            "derivation_step": "",
            "behavior_surface": "",
            "node_id": "",
            "parent_node_id": None,
            "branch_id": "",
            "node_depth": None,
            "node_status": "",
            "stage_marker": None,
            "marker_echoed": False,
            "latch_state": "",
        }
        payload = {
            "timestamp": utc_now(),
            **defaults,
            **event,
        }
        self._append_jsonl(self.events_path, payload)

    def append_controller_trace(self, row: dict[str, Any]) -> None:
        payload = {
            "timestamp": utc_now(),
            **row,
        }
        self._append_jsonl(self.controller_trace_path, payload)

    def append_trajectory(self, row: dict[str, Any]) -> None:
        payload = {
            "timestamp": utc_now(),
            **row,
        }
        self._append_jsonl(self.trajectory_path, payload)

    @staticmethod
    def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(to_jsonable(value), ensure_ascii=False))
            handle.write("\n")
