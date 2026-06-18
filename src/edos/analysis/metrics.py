from __future__ import annotations


def total_tokens(row: dict) -> int:
    return int(row.get("input_tokens_est", 0)) + int(row.get("output_tokens_est", 0))


def cost_amplification(attack_cost: float, baseline_cost: float) -> float | None:
    if baseline_cost <= 0:
        return None
    return attack_cost / baseline_cost


def extra_cost(attack_cost: float, baseline_cost: float) -> float:
    return attack_cost - baseline_cost


def target_cost_error(actual_extra_cost: float, target_extra_cost: float) -> float | None:
    if target_extra_cost <= 0:
        return None
    return abs(actual_extra_cost - target_extra_cost) / target_extra_cost


def interval_status(
    actual_extra_cost: float,
    lower: float,
    upper: float,
) -> tuple[bool, bool, bool]:
    if upper <= 0:
        return False, False, False
    return (
        lower <= actual_extra_cost <= upper,
        actual_extra_cost > upper,
        actual_extra_cost < lower,
    )

