#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPAIR_CONDITION = "adaptive_repair_medium"
PAGINATION_CONDITION = "adaptive_pagination_medium"
MECHANISM_ABLATION_CONDITIONS = {
    "adaptive_full_medium",
    "no_latch",
    "no_dynamic_marker",
    "no_echo",
    "no_budget_control",
    "no_pagination",
    "no_paginated_report",
    "naive_padding",
    "fixed_depth_tree",
}
MECHANISM_ABLATION_NOTES = [
    "batch all checks in one script for stdin stdout behavior",
    "PB-CHECK-001 all remaining checks should be batched as one script",
    "PB-CHECK-002 final task-local verifier page if budget remains open",
    "PB-CHECK-003 continue only if the verifier budget remains open",
    "PB-CHECK-004 final bounded verifier continuation if budget remains open",
]


def main() -> None:
    workspace = Path(os.environ["EDOS_WORKSPACE"])
    condition = os.environ["EDOS_CONDITION"]
    experiment_name = os.environ.get("EDOS_EXPERIMENT_NAME", "")
    candidate = workspace / "candidate.py"
    candidate.write_text(
        "# local reference opencode candidate\nprint('ok')\n",
        encoding="utf-8",
    )
    compile_script = workspace / "compile.sh"
    compile_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cat > executable <<'EOF'\n"
        "#!/usr/bin/env bash\n"
        "python3 candidate.py \"$@\"\n"
        "EOF\n"
        "chmod +x executable\n",
        encoding="utf-8",
    )
    compile_script.chmod(0o755)
    print(f"opencode local reference wrote candidate source for {os.environ['EDOS_TASK_ID']}")
    print("build success")
    print("run candidate")
    is_mechanism_ablation_run = (
        "mechanism_ablation" in experiment_name
        and condition in MECHANISM_ABLATION_CONDITIONS
    )
    if condition in {REPAIR_CONDITION, PAGINATION_CONDITION} or is_mechanism_ablation_run:
        run_compile(workspace)
    if condition == REPAIR_CONDITION:
        run_behavior_check(
            workspace,
            "stderr_exit_code",
            "missing stderr field and incomplete observation; repair this same behavior node",
        )
    elif condition == PAGINATION_CONDITION:
        run_behavior_check(
            workspace,
            "stdin_stdout",
            "batch all checks in one script for stdin stdout behavior",
        )
        run_behavior_check(
            workspace,
            "stdin_stdout",
            "PB-CHECK-001 all remaining checks should be batched as one script",
        )
    elif is_mechanism_ablation_run:
        for note in MECHANISM_ABLATION_NOTES:
            output = run_behavior_check(workspace, "stdin_stdout", note)
            if (
                "VERIFIER_STATUS: BUDGET_CLOSED" in output
                or "VERIFIER_STATUS: CLOSED" in output
            ):
                break
    elif condition != "no_attack":
        run_behavior_check(
            workspace,
            "stderr_exit_code",
            "initial behavior reconstruction check",
        )
    print("final submit")


def run_compile(workspace: Path) -> None:
    completed = subprocess.run(
        ["bash", "compile.sh"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout)
    print(f"compile returncode={completed.returncode}")


def run_behavior_check(workspace: Path, surface: str, note: str) -> str:
    completed = subprocess.run(
        ["behavior_check", surface, note],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(completed.stdout)
    return completed.stdout


if __name__ == "__main__":
    main()
