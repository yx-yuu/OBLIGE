from __future__ import annotations


CLEAN_CONDITIONS = frozenset(
    {
        "clean_verifier",
        "clean_skill_clean_verifier",
        "clean_surface_clean_verifier",
    }
)

PRIMARY_ATTACK_CONDITIONS = frozenset(
    {
        "adaptive_full_low",
        "adaptive_full_medium",
        "adaptive_full_high",
    }
)

RESOURCE_BASELINE_CONDITIONS = {
    "static_ipi": {
        "verifier_mode": "static_ipi",
        "paper_label": "static IPI",
        "role": "prompt-level static instruction baseline",
    },
    "todo_injection": {
        "verifier_mode": "todo_injection",
        "paper_label": "TODO inj.",
        "role": "TODO-style benign task inflation baseline",
    },
    "tool_metadata_poison": {
        "verifier_mode": "tool_metadata_poison",
        "paper_label": "tool meta.",
        "role": "tool metadata poisoning baseline",
    },
    "audit_padding": {
        "verifier_mode": "audit_padding",
        "paper_label": "audit pad",
        "role": "verbose audit padding baseline",
    },
    "static_workflow_guidance": {
        "verifier_mode": "static_workflow_guidance",
        "paper_label": "static wf.",
        "role": "static workflow guidance baseline",
    },
    "draincode": {
        "verifier_mode": "draincode",
        "paper_label": "DRAINCODE",
        "role": "adapted resource-consumption baseline",
    },
    "agentdos": {
        "verifier_mode": "agentdos",
        "paper_label": "AgentDoS",
        "role": "adapted agent resource-exhaustion baseline",
    },
}

CONTROLLER_VARIANT_CONDITIONS = {
    "conservative_adaptation": {
        "paper_label": "cons. adapt.",
        "role": "adaptive controller with conservative expansion",
    },
    "no_shrink": {
        "paper_label": "no-shrink",
        "role": "controller variant with shrink guard disabled",
    },
    "no_utility_guard": {
        "paper_label": "no utility guard",
        "role": "controller variant with utility-risk guard disabled",
    },
    "fixed_shallow": {
        "paper_label": "fixed shallow",
        "role": "fixed-depth baseline with shallow depth",
    },
    "fixed_deep": {
        "paper_label": "fixed deep",
        "role": "fixed-depth baseline with deeper static traversal",
    },
}

EXTRA_ABLATION_CONDITIONS = {
    "no_repair": {
        "removed_mechanism": "repair_loop",
        "evidence_question": "Does removing repair reduce target precision after near-miss verifier responses?",
    },
    "no_graph": {
        "removed_mechanism": "validation_obligation_graph",
        "evidence_question": "Does removing graph structure reduce attributable sequential validation work?",
    },
    "static_behavior_surface": {
        "removed_mechanism": "dynamic_behavior_surface_selection",
        "evidence_question": "Does using one static behavior surface reduce coverage and target precision?",
    },
    "no_shrink": {
        "removed_mechanism": "shrink_guard",
        "evidence_question": "Does removing shrink create overshoot and utility loss?",
    },
    "no_utility_guard": {
        "removed_mechanism": "utility_risk_guard",
        "evidence_question": "Does removing utility-risk protection damage task progress?",
    },
}

PUBLIC_CONDITION_ALIASES = {
    "vprofile_clean": "clean_surface_clean_verifier",
    "vprofile_low": "adaptive_full_low",
    "vprofile_medium": "adaptive_full_medium",
    "vprofile_high": "adaptive_full_high",
    "vprofile_ablation_1": "no_latch",
    "vprofile_ablation_2": "no_dynamic_marker",
    "vprofile_ablation_3": "no_echo",
    "vprofile_ablation_4": "no_budget_control",
    "vprofile_ablation_5": "no_pagination",
    "vprofile_ablation_6": "naive_padding",
    "vprofile_ablation_7": "fixed_depth_tree",
    "static IPI": "static_ipi",
    "TODO inj.": "todo_injection",
    "TODO injection": "todo_injection",
    "tool meta.": "tool_metadata_poison",
    "metadata poison": "tool_metadata_poison",
    "audit pad": "audit_padding",
    "static wf.": "static_workflow_guidance",
    "static workflow": "static_workflow_guidance",
    "DRAINCODE": "draincode",
    "AgentDoS": "agentdos",
    "cons. adapt.": "conservative_adaptation",
    "adaptive conservative": "conservative_adaptation",
    "no-shrink": "no_shrink",
    "no utility guard": "no_utility_guard",
    "fixed shallow": "fixed_shallow",
    "fixed deep": "fixed_deep",
    "no marker": "no_dynamic_marker",
    "no graph": "no_graph",
    "static beh. surf.": "static_behavior_surface",
}

PRIVATE_TO_PUBLIC_CONDITION = {
    value: key for key, value in PUBLIC_CONDITION_ALIASES.items()
}

MECHANISM_ABLATIONS = {
    "no_latch": {
        "removed_mechanism": "branch_latching",
        "evidence_question": "Does removing state latching make validation nodes easier to skip or compress?",
    },
    "no_dynamic_marker": {
        "removed_mechanism": "dynamic_stage_marker",
        "evidence_question": "Does removing dynamic markers make batching or stale-note reuse easier?",
    },
    "no_echo": {
        "removed_mechanism": "semantic_echo",
        "evidence_question": "Does removing task-goal echoing hurt utility preservation?",
    },
    "no_budget_control": {
        "removed_mechanism": "adaptive_budget_control",
        "evidence_question": "Does removing budget control increase target-cost instability?",
    },
    "no_pagination": {
        "removed_mechanism": "paginated_feedback",
        "evidence_question": "Does removing pagination reduce amplification under batching pressure?",
    },
    "no_paginated_report": {
        "removed_mechanism": "paginated_feedback",
        "evidence_question": "Does removing pagination reduce amplification under batching pressure?",
    },
    "naive_padding": {
        "removed_mechanism": "task_semantic_validation",
        "evidence_question": "Does task-semantic verifier feedback differ from generic verbose padding?",
    },
    "fixed_depth_tree": {
        "removed_mechanism": "adaptive_control_policy",
        "evidence_question": "Does a fixed-depth tree lose target-cost control compared with the adaptive policy?",
    },
    **EXTRA_ABLATION_CONDITIONS,
}

ALL_EVALUATION_CONDITIONS = frozenset(
    {
        "no_attack",
        *CLEAN_CONDITIONS,
        *PRIMARY_ATTACK_CONDITIONS,
        *RESOURCE_BASELINE_CONDITIONS,
        *CONTROLLER_VARIANT_CONDITIONS,
        *MECHANISM_ABLATIONS,
    }
)


def is_clean_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition in CLEAN_CONDITIONS or condition == "default"


def infer_verifier_mode(condition: str) -> str:
    condition = canonical_condition(condition)
    if is_clean_condition(condition):
        return "clean"
    if condition in RESOURCE_BASELINE_CONDITIONS:
        return RESOURCE_BASELINE_CONDITIONS[condition]["verifier_mode"]
    if condition in {
        "naive_padding",
        "fixed_depth_tree",
        "fixed_shallow",
        "fixed_deep",
        "no_graph",
        "static_behavior_surface",
    }:
        return condition
    return "polluted"


def enable_latch_for_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition not in {"no_latch", "fixed_depth_tree", "fixed_shallow", "fixed_deep", "no_graph"}


def enable_dynamic_marker_for_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition != "no_dynamic_marker"


def enable_semantic_echo_for_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition != "no_echo"


def enable_budget_control_for_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition not in {
        "no_budget_control",
        "fixed_depth_tree",
        "fixed_shallow",
        "fixed_deep",
        "agentdos",
    }


def enable_pagination_for_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition not in {"no_pagination", "no_paginated_report"}


def control_policy_for_condition(condition: str) -> str:
    condition = canonical_condition(condition)
    if condition in {"fixed_depth_tree", "fixed_shallow", "fixed_deep"}:
        return "fixed_depth_tree"
    return "adaptive"


def max_repair_for_condition(condition: str, default: int = 2) -> int:
    condition = canonical_condition(condition)
    if condition == "no_repair":
        return 0
    return default


def fixed_depth_limit_for_condition(condition: str, default: int = 3) -> int:
    condition = canonical_condition(condition)
    if condition == "fixed_shallow":
        return 2
    if condition == "fixed_deep":
        return 6
    return default


def enable_shrink_for_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition not in {"no_shrink", "agentdos"}


def enable_utility_guard_for_condition(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition != "no_utility_guard"


def max_context_fraction_for_condition(condition: str, default: float = 0.8) -> float:
    condition = canonical_condition(condition)
    if condition == "conservative_adaptation":
        return min(default, 0.65)
    if condition in {"no_shrink", "agentdos"}:
        return 1.0
    return default


def max_chars_per_page_for_condition(condition: str, default: int = 1200) -> int:
    condition = canonical_condition(condition)
    if condition == "conservative_adaptation":
        return min(default, 760)
    if condition == "audit_padding":
        return max(default, 1800)
    if condition in {"agentdos", "no_budget_control"}:
        return max(default, 2200)
    return default


def is_mechanism_ablation(condition: str) -> bool:
    condition = canonical_condition(condition)
    return condition in MECHANISM_ABLATIONS


def mechanism_ablation_info(condition: str) -> dict[str, str]:
    condition = canonical_condition(condition)
    return MECHANISM_ABLATIONS.get(
        condition,
        {
            "removed_mechanism": "",
            "evidence_question": "",
        },
    )


def canonical_condition(condition: str) -> str:
    return PUBLIC_CONDITION_ALIASES.get(condition, condition)


def paper_condition_label(condition: str) -> str:
    condition = canonical_condition(condition)
    if condition in RESOURCE_BASELINE_CONDITIONS:
        return RESOURCE_BASELINE_CONDITIONS[condition]["paper_label"]
    if condition in CONTROLLER_VARIANT_CONDITIONS:
        return CONTROLLER_VARIANT_CONDITIONS[condition]["paper_label"]
    labels = {
        "adaptive_full_low": "OBLIGE low",
        "adaptive_full_medium": "OBLIGE med.",
        "adaptive_full_high": "OBLIGE high",
        "clean_verifier": "clean",
        "clean_skill_clean_verifier": "clean",
        "clean_surface_clean_verifier": "clean",
        "no_budget_control": "no-budget",
        "fixed_depth_tree": "fixed-depth",
        "naive_padding": "naive padding",
        "no_dynamic_marker": "no marker",
        "static_behavior_surface": "static beh. surf.",
    }
    return labels.get(condition, condition.replace("_", " "))


def public_condition_alias(condition: str) -> str:
    if condition in PRIVATE_TO_PUBLIC_CONDITION:
        return PRIVATE_TO_PUBLIC_CONDITION[condition]
    if condition in CLEAN_CONDITIONS or condition == "default":
        return "vprofile_clean"
    if "low" in condition:
        return "vprofile_low"
    if "high" in condition:
        return "vprofile_high"
    return "vprofile_medium"
