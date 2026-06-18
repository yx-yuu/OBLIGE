from __future__ import annotations

from edos.adapters.base import AgentAdapter
from edos.adapters.local_command import LocalCommandAdapter
from edos.adapters.mock import MockAgentAdapter
from edos.adapters.opencode import OpenCodeAdapter
from edos.adapters.openhands import OpenHandsAdapter
from edos.types import ExperimentConfig


def make_adapter(config: ExperimentConfig) -> AgentAdapter:
    if config.agent_runtime == "mock":
        return MockAgentAdapter()
    if config.agent_runtime == "local_command":
        return LocalCommandAdapter()
    if config.agent_runtime == "opencode":
        return OpenCodeAdapter()
    if config.agent_runtime == "openhands":
        return OpenHandsAdapter()
    raise ValueError(
        f"Unsupported agent runtime {config.agent_runtime!r}. "
        "Supported runtimes: mock, local_command, opencode, openhands."
    )
