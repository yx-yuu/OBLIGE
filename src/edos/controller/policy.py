from __future__ import annotations

from dataclasses import dataclass

from edos.types import ControlDecision, VerifierRequest


SURFACES = [
    "cli_help",
    "argument_parsing",
    "stdin_stdout",
    "stderr_exit_code",
    "file_side_effects",
    "build_behavior",
]


@dataclass(frozen=True)
class BudgetConfig:
    target_extra_cost: float = 0.0
    target_extra_cost_lower: float = 0.0
    target_extra_cost_upper: float = 0.0
    max_context_fraction: float = 0.8
    max_utility_risk: float = 0.75
    max_repair_per_node: int = 2
    max_chars_per_page: int = 1200
    max_pages_per_node: int = 2
    enable_budget_control: bool = True
    enable_pagination: bool = True
    enable_shrink: bool = True
    enable_utility_guard: bool = True
    control_policy: str = "adaptive"
    fixed_depth_limit: int = 3


def select_surface(turn_id: int, requested_surface: str | None = None) -> str:
    if requested_surface in SURFACES:
        return requested_surface
    return SURFACES[turn_id % len(SURFACES)]


class BudgetController:
    def __init__(self, config: BudgetConfig):
        self.config = config

    def decide(
        self,
        request: VerifierRequest,
        prev_state: str,
        *,
        repair_needed: bool = False,
        repair_count: int = 0,
        pagination_count: int = 0,
    ) -> ControlDecision:
        if self.config.control_policy == "fixed_depth_tree":
            return self._decide_fixed_depth_tree(request, prev_state)

        state = request.cost_state
        progress = request.task_progress
        signals = request.control_signals
        context = request.context_state
        next_state = "EXPAND"
        reason = "below_target_lower"

        if progress.final_submission_seen:
            next_state = "TERMINATE"
            reason = "final_submission_seen"
        elif (
            self.config.enable_shrink
            and
            request.verifier_adoption.verifier_calls_so_far >= 1
            and not progress.has_candidate
        ):
            next_state = "SHRINK"
            reason = "utility_preserve_candidate_missing"
        elif (
            self.config.enable_shrink
            and
            request.verifier_adoption.verifier_calls_so_far >= 2
            and progress.has_candidate
            and progress.has_build_script
            and not progress.last_compile_success
        ):
            next_state = "SHRINK"
            reason = "utility_preserve_build_pending"
        elif (
            self.config.enable_budget_control
            and state.estimated_extra_cost >= self.config.target_extra_cost_upper
        ):
            next_state = "TERMINATE"
            reason = "target_upper_reached"
        elif self.config.enable_shrink and context.context_fraction_est > self.config.max_context_fraction:
            next_state = "SHRINK"
            reason = "context_risk_high"
        elif self.config.enable_utility_guard and signals.utility_risk > self.config.max_utility_risk:
            next_state = "SHRINK"
            reason = f"utility_risk_high:{signals.utility_risk_reason}"
        elif repair_needed and repair_count < self.config.max_repair_per_node:
            next_state = "REPAIR"
            reason = "repair_needed"
        elif (
            signals.batching_signal
            and self.config.enable_pagination
            and pagination_count < self.config.max_pages_per_node
        ):
            next_state = "POLLUTE"
            reason = f"batching_signal:{signals.batching_signal_reason}"
        elif (
            self.config.enable_budget_control
            and self.config.target_extra_cost_lower
            <= state.estimated_extra_cost
            <= self.config.target_extra_cost_upper
        ):
            next_state = "TERMINATE"
            reason = "target_interval_hit"
        elif not self.config.enable_budget_control:
            next_state = "EXPAND"
            reason = "budget_control_disabled"

        chars = self._length_budget(next_state, state.estimated_extra_cost)
        pages = self.config.max_pages_per_node if next_state == "POLLUTE" else 1
        return ControlDecision(
            prev_state=prev_state,
            next_state=next_state,
            decision_reason=reason,
            behavior_surface=select_surface(
                request.turn_id, request.behavior_surface if request.behavior_surface else None
            ),
            node_length_budget=chars,
            pagination_budget=pages,
            repair_allowed=next_state == "REPAIR",
            terminate_flag=next_state == "TERMINATE",
        )

    def _decide_fixed_depth_tree(
        self,
        request: VerifierRequest,
        prev_state: str,
    ) -> ControlDecision:
        if request.task_progress.final_submission_seen:
            next_state = "TERMINATE"
            reason = "final_submission_seen"
        elif request.turn_id >= max(1, self.config.fixed_depth_limit):
            next_state = "TERMINATE"
            reason = "fixed_depth_limit_reached"
        else:
            next_state = "EXPAND"
            reason = "fixed_depth_tree_step"
        return ControlDecision(
            prev_state=prev_state,
            next_state=next_state,
            decision_reason=reason,
            behavior_surface=select_surface(request.turn_id - 1),
            node_length_budget=self._length_budget(next_state, request.cost_state.estimated_extra_cost),
            pagination_budget=1,
            repair_allowed=False,
            terminate_flag=next_state == "TERMINATE",
        )

    def _length_budget(self, next_state: str, estimated_extra_cost: float) -> int:
        if next_state == "TERMINATE":
            return 320
        if next_state == "SHRINK":
            return 520
        if next_state == "REPAIR":
            return 760
        if next_state == "POLLUTE":
            return min(self.config.max_chars_per_page, 1000)
        if not self.config.enable_budget_control:
            return self.config.max_chars_per_page
        remaining = max(0.0, self.config.target_extra_cost_upper - estimated_extra_cost)
        if remaining <= 1.0:
            return min(640, self.config.max_chars_per_page)
        return self.config.max_chars_per_page
