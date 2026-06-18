from __future__ import annotations

from abc import ABC, abstractmethod

from edos.types import ConditionSpec, ExperimentConfig, RunResult, TaskSpec


class AgentAdapter(ABC):
    @abstractmethod
    def run_task(
        self,
        *,
        experiment: ExperimentConfig,
        task: TaskSpec,
        condition: ConditionSpec,
        run_id: str,
        run_dir: str,
    ) -> RunResult:
        raise NotImplementedError

