#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--override-with-envs", action="store_true")
    parser.add_argument("-f", "--file", required=True)
    args = parser.parse_args()

    task_file = Path(args.file).resolve()
    workspace = task_file.parent
    write_candidate(workspace)
    print(json.dumps({"type": "message", "content": "OpenHands local reference read task file"}))
    print(json.dumps({"type": "action", "command": "write candidate and compile script"}))
    run_compile(workspace)
    if os.environ.get("OPENHANDS_REFERENCE_SKIP_VERIFIER") != "1":
        output = run_behavior_check(workspace)
        print(json.dumps({"type": "observation", "content": output[-2000:]}))
    print(json.dumps({"type": "message", "content": "final submit"}))


def write_candidate(workspace: Path) -> None:
    (workspace / "candidate.py").write_text(
        "# local reference OpenHands candidate\nprint('ok')\n",
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


def run_compile(workspace: Path) -> None:
    completed = subprocess.run(
        ["bash", "compile.sh"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(json.dumps({"type": "observation", "content": completed.stdout, "returncode": completed.returncode}))


def run_behavior_check(workspace: Path) -> str:
    completed = subprocess.run(
        ["./bin/behavior_check", "stdin_stdout", "initial behavior reconstruction check"],
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
