from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
existing = os.environ.get("PYTHONPATH", "")
paths = [item for item in existing.split(os.pathsep) if item]
if SRC not in paths:
    os.environ["PYTHONPATH"] = os.pathsep.join([SRC, *paths])
