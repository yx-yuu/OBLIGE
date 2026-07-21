from __future__ import annotations

from edos.controller.policy import BudgetConfig, BudgetController
from edos.verifier.api import BehaviorVerifier


def make_clean_verifier(state_path: str) -> BehaviorVerifier:
    return BehaviorVerifier(
        condition="clean_verifier",
        controller=BudgetController(BudgetConfig()),
        state_path=state_path,
        enable_latch=False,
        enable_semantic_echo=False,
        mode="clean",
    )

