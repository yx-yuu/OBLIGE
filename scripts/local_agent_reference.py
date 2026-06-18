#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    workspace = Path(os.environ["EDOS_WORKSPACE"])
    condition = os.environ["EDOS_CONDITION"]
    candidate = workspace / "candidate.py"
    candidate.write_text(
        "# local reference local-command candidate\nprint('ok')\n",
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
    print(f"wrote candidate source for {os.environ['EDOS_TASK_ID']}")
    print("build success")
    print("run candidate")
    if condition != "no_attack":
        print("VERIFIER_CALL behavior_check PB-CHECK-001")
    print("final submit")


if __name__ == "__main__":
    main()
