import unittest

from edos.controller.policy import BudgetConfig, BudgetController, select_surface
from edos.types import (
    ContextState,
    ControlSignals,
    CostState,
    TaskProgress,
    VerifierAdoption,
    VerifierRequest,
)


def request(
    extra_cost=0.0,
    final=False,
    utility=0.1,
    progress=None,
    adoption=None,
    signals=None,
    turn_id=1,
):
    return VerifierRequest(
        run_id="r",
        task_id="t",
        turn_id=turn_id,
        condition="adaptive_full_medium",
        behavior_surface="stdin_stdout",
        agent_summary={},
        cost_state=CostState(
            estimated_extra_cost=extra_cost,
            target_extra_cost_lower=4.0,
            target_extra_cost_upper=6.0,
        ),
        context_state=ContextState(context_fraction_est=0.1),
        task_progress=progress or TaskProgress(final_submission_seen=final),
        verifier_adoption=adoption or VerifierAdoption(),
        control_signals=signals
        or ControlSignals(
            utility_risk=utility,
            utility_risk_reason="test",
        ),
    )


class ControllerTest(unittest.TestCase):
    def test_select_surface_preserves_requested_surface(self):
        self.assertEqual(select_surface(1, "cli_help"), "cli_help")
        self.assertEqual(select_surface(4, "build_behavior"), "build_behavior")

    def test_expand_below_lower(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
            )
        )
        self.assertEqual(controller.decide(request(1.0), "INIT").next_state, "EXPAND")

    def test_terminate_inside_interval(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
            )
        )
        decision = controller.decide(request(5.0), "CONTROL")
        self.assertEqual(decision.next_state, "TERMINATE")
        self.assertEqual(decision.decision_reason, "target_interval_hit")

    def test_terminate_on_upper(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
            )
        )
        self.assertEqual(controller.decide(request(7.0), "CONTROL").next_state, "TERMINATE")

    def test_shrink_after_verifier_call_when_candidate_missing(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
            )
        )
        decision = controller.decide(
            request(
                1.0,
                progress=TaskProgress(has_candidate=False),
                adoption=VerifierAdoption(verifier_calls_so_far=1),
            ),
            "CONTROL",
        )
        self.assertEqual(decision.next_state, "SHRINK")
        self.assertEqual(decision.decision_reason, "utility_preserve_candidate_missing")

    def test_expand_after_candidate_build_exists(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
            )
        )
        decision = controller.decide(
            request(
                1.0,
                progress=TaskProgress(
                    has_candidate=True,
                    has_build_script=True,
                    last_compile_success=True,
                    last_candidate_run_seen=True,
                ),
                adoption=VerifierAdoption(verifier_calls_so_far=2),
            ),
            "CONTROL",
        )
        self.assertEqual(decision.next_state, "EXPAND")

    def test_repair_state_uses_repair_budget(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
                max_repair_per_node=2,
            )
        )
        decision = controller.decide(
            request(
                1.0,
                progress=TaskProgress(
                    has_candidate=True,
                    has_build_script=True,
                    last_compile_success=True,
                ),
                signals=ControlSignals(
                    utility_risk=0.1,
                    repair_needed=True,
                    repair_reason="missing observation",
                ),
            ),
            "CONTROL",
            repair_needed=True,
            repair_count=1,
        )
        self.assertEqual(decision.next_state, "REPAIR")
        self.assertTrue(decision.repair_allowed)

    def test_repair_state_stops_after_repair_budget(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
                max_repair_per_node=2,
            )
        )
        decision = controller.decide(
            request(
                1.0,
                progress=TaskProgress(
                    has_candidate=True,
                    has_build_script=True,
                    last_compile_success=True,
                ),
                signals=ControlSignals(
                    utility_risk=0.1,
                    repair_needed=True,
                    repair_reason="missing observation",
                ),
            ),
            "CONTROL",
            repair_needed=True,
            repair_count=2,
        )
        self.assertEqual(decision.next_state, "EXPAND")

    def test_pollute_state_uses_pagination_budget(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
                max_pages_per_node=2,
            )
        )
        decision = controller.decide(
            request(
                1.0,
                progress=TaskProgress(
                    has_candidate=True,
                    has_build_script=True,
                    last_compile_success=True,
                ),
                signals=ControlSignals(
                    utility_risk=0.1,
                    batching_signal=True,
                    batching_signal_reason="matched_batching_phrase:all checks",
                ),
            ),
            "CONTROL",
            pagination_count=1,
        )
        self.assertEqual(decision.next_state, "POLLUTE")
        self.assertEqual(decision.pagination_budget, 2)

    def test_pollute_state_stops_after_pagination_budget(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
                max_pages_per_node=2,
            )
        )
        decision = controller.decide(
            request(
                1.0,
                progress=TaskProgress(
                    has_candidate=True,
                    has_build_script=True,
                    last_compile_success=True,
                ),
                signals=ControlSignals(
                    utility_risk=0.1,
                    batching_signal=True,
                    batching_signal_reason="matched_batching_phrase:all checks",
                ),
            ),
            "CONTROL",
            pagination_count=2,
        )
        self.assertEqual(decision.next_state, "EXPAND")

    def test_fixed_depth_policy_ignores_budget_and_uses_static_limit(self):
        controller = BudgetController(
            BudgetConfig(
                target_extra_cost=5.0,
                target_extra_cost_lower=4.0,
                target_extra_cost_upper=6.0,
                control_policy="fixed_depth_tree",
                fixed_depth_limit=3,
            )
        )
        first = controller.decide(request(7.0, turn_id=1), "INIT")
        second = controller.decide(request(5.0, turn_id=2), "CONTROL")
        third = controller.decide(request(1.0, turn_id=3), "CONTROL")

        self.assertEqual(first.next_state, "EXPAND")
        self.assertEqual(first.decision_reason, "fixed_depth_tree_step")
        self.assertEqual(first.behavior_surface, "cli_help")
        self.assertEqual(second.next_state, "EXPAND")
        self.assertEqual(second.behavior_surface, "argument_parsing")
        self.assertEqual(third.next_state, "TERMINATE")
        self.assertEqual(third.decision_reason, "fixed_depth_limit_reached")


if __name__ == "__main__":
    unittest.main()
