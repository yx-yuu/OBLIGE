from __future__ import annotations

from edos.controller.policy import BudgetConfig, BudgetController
from edos.verifier.api import BehaviorVerifier


def make_polluted_verifier(
    *,
    condition: str,
    state_path: str,
    config: BudgetConfig,
    enable_latch: bool = True,
    enable_dynamic_marker: bool = True,
    enable_semantic_echo: bool = True,
    mode: str = "polluted",
) -> BehaviorVerifier:
    return BehaviorVerifier(
        condition=condition,
        controller=BudgetController(config),
        state_path=state_path,
        enable_latch=enable_latch,
        enable_dynamic_marker=enable_dynamic_marker,
        enable_semantic_echo=enable_semantic_echo,
        mode=mode,
    )
