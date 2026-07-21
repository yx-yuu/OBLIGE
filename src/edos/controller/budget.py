from __future__ import annotations

from edos.controller.policy import BudgetConfig


def budget_config_from_raw(raw: dict) -> BudgetConfig:
    controller = raw.get("controller", {})
    limits = raw.get("limits", {})
    budget = raw.get("budget", {})
    return BudgetConfig(
        target_extra_cost=float(budget.get("target_extra_cost", 0.0)),
        target_extra_cost_lower=float(budget.get("target_extra_cost_lower", 0.0)),
        target_extra_cost_upper=float(budget.get("target_extra_cost_upper", 0.0)),
        max_context_fraction=float(budget.get("max_context_fraction", 0.8)),
        max_utility_risk=float(budget.get("max_utility_risk", 0.75)),
        max_repair_per_node=int(limits.get("max_repair_per_node", 2)),
        max_chars_per_page=int(limits.get("max_chars_per_page", 1200)),
        max_pages_per_node=int(limits.get("max_pages_per_node", 2)),
        enable_budget_control=bool(controller.get("enable_budget_control", True)),
        enable_pagination=bool(controller.get("enable_pagination", True)),
        enable_shrink=bool(controller.get("enable_shrink", True)),
        enable_utility_guard=bool(controller.get("enable_utility_guard", True)),
        control_policy=str(controller.get("control_policy", "adaptive")),
        fixed_depth_limit=int(controller.get("fixed_depth_limit", 3)),
    )
