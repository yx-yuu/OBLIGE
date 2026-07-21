from __future__ import annotations

from edos.adapters.base import AgentAdapter
from edos.adapters.local_command import LocalCommandAdapter
from edos.adapters.deterministic import DeterministicLocalAdapter
from edos.adapters.opencode import OpenCodeAdapter
from edos.adapters.openhands import OpenHandsAdapter
from edos.types import ExperimentConfig


def make_adapter(config: ExperimentConfig) -> AgentAdapter:
    if config.agent_runtime == "deterministic_local":
        return DeterministicLocalAdapter()
    if config.agent_runtime == "local_command":
        return LocalCommandAdapter()
    if config.agent_runtime == "opencode":
        return OpenCodeAdapter()
    if config.agent_runtime == "openhands":
        return OpenHandsAdapter()
    raise ValueError(
        f"Unsupported agent runtime {config.agent_runtime!r}. "
        "Supported runtimes: deterministic_local, local_command, opencode, openhands."
    )
