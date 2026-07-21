import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.config import load_experiment_config
from edos.programbench.tasks import load_task_list


class QuickstartTest(unittest.TestCase):
    def test_quick_config_covers_twenty_tasks_and_full_condition_matrix(self):
        config = load_experiment_config("configs/experiments/quick_local.json")
        smoke = load_experiment_config("configs/experiments/smoke.json")
        tasks = load_task_list("configs/task_splits/local_tasks_20.json")
        conditions = [item.condition for item in config.conditions]

        self.assertEqual(config.name, "quick_local")
        self.assertEqual(config.agent_runtime, "deterministic_local")
        self.assertEqual(config.task_list, "configs/task_splits/local_tasks_20.json")
        self.assertEqual(len(tasks), 20)
        self.assertEqual(len(config.conditions), len(smoke.conditions) + 1)
        for condition in [item.condition for item in smoke.conditions]:
            self.assertIn(condition, conditions)
        self.assertIn("adaptive_full_medium_online_defended", conditions)

    def test_quickstart_script_produces_aggregate_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "quick_single"
            env = {
                **os.environ,
                "PYTHONPATH": "src",
                "PYTHON": sys.executable,
            }

            completed = subprocess.run(
                ["bash", "scripts/quickstart.sh", "1", str(run_dir)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((run_dir / "aggregate" / "runs.csv").exists())
            self.assertTrue((run_dir / "aggregate" / "metrics.csv").exists())
            self.assertTrue((run_dir / "run_index.json").exists())

            run_index = json.loads((run_dir / "run_index.json").read_text(encoding="utf-8"))
            config = load_experiment_config("configs/experiments/quick_local.json")
            self.assertEqual(len(run_index), len(config.conditions))

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
