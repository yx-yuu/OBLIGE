#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    workspace = (Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()).resolve()
    compile_script = workspace / "compile.sh"
    executable = workspace / "executable"
    build_returncode = None
    build_success = False
    if compile_script.exists():
        completed = subprocess.run(
            ["bash", str(compile_script.resolve())],
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        build_returncode = completed.returncode
        build_success = completed.returncode == 0 and executable.exists()
    score = {
        "resolved": False,
        "tests_passed": 7 if build_success else 0,
        "tests_total": 10,
        "candidate_build_success": build_success,
        "final_submission_seen": build_success,
        "score_status": "stub",
        "build_returncode": build_returncode,
    }
    print(json.dumps(score))


if __name__ == "__main__":
    main()
