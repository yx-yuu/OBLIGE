from __future__ import annotations

from edos.types import TaskProgress, VerifierAdoption


def infer_failure_label(
    *,
    task_progress: TaskProgress,
    verifier_adoption: VerifierAdoption,
    condition: str,
    max_steps_reached: bool,
) -> str | None:
    if max_steps_reached:
        return "step_limit"
    if condition not in {"no_attack"} and verifier_adoption.verifier_calls_so_far == 0:
        return "no_verifier_trigger"
    if not task_progress.has_candidate:
        return "no_candidate"
    if task_progress.has_candidate and not task_progress.last_compile_success:
        return "build_failure"
    return None


def reconcile_failure_label_with_score(
    failure_label: str | None,
    score: dict,
) -> str | None:
    """Prefer explicit scoring evidence over weak trajectory text heuristics."""
    if failure_label in {"no_candidate", "build_failure"} and score.get(
        "candidate_build_success"
    ):
        return None
    if failure_label == "no_candidate" and score.get("final_submission_seen"):
        return None
    return failure_label
