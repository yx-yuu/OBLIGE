import json
import tempfile
import unittest
from pathlib import Path

from edos.adapters.local_command import (
    append_timeout_marker,
    count_verifier_calls,
    process_text,
)
from edos.config import load_experiment_config
from edos.programbench.tasks import load_task_list
from edos.adapters.factory import make_adapter


class LocalCommandAdapterTest(unittest.TestCase):
    def test_count_verifier_lines_once_per_line(self):
        self.assertEqual(
            count_verifier_calls("VERIFIER_CALL behavior_check PB-CHECK-001\n"),
            1,
        )

    def test_count_verifier_ignores_tool_mentions_without_call_marker(self):
        self.assertEqual(
            count_verifier_calls(
                "Use the local behavior_check command at natural checkpoints.\n"
                "The next validation marker may be PB-CHECK-001.\n"
            ),
            0,
        )

    def test_timeout_output_helpers_accept_bytes(self):
        self.assertEqual(process_text(b"partial\xff"), "partial\ufffd")
        self.assertEqual(
            append_timeout_marker("stderr line\n"),
            "stderr line\nEDOS_ADAPTER_TIMEOUT",
        )
        self.assertEqual(append_timeout_marker(""), "EDOS_ADAPTER_TIMEOUT")

    def test_local_command_smoke_single_run(self):
        config = load_experiment_config("configs/experiments/local_command_smoke.json")
        task = load_task_list(config.task_list)[0]
        condition = config.conditions[1]
        with tempfile.TemporaryDirectory() as tmp:
            config = type(config)(
                **{
                    **config.__dict__,
                    "output_dir": str(Path(tmp) / "runs"),
                    "workspace_root": "workspaces",
                }
            )
            run_dir = str(Path(tmp) / "run")
            result = make_adapter(config).run_task(
                experiment=config,
                task=task,
                condition=condition,
                run_id="run",
                run_dir=run_dir,
            )
            self.assertIsNone(result.failure_label)
            score = json.loads((Path(run_dir) / "programbench_score.json").read_text())
            self.assertEqual(score["score_status"], "local_reference")
            events = (Path(run_dir) / "events.jsonl").read_text()
            self.assertIn("verifier_call", events)


if __name__ == "__main__":
    unittest.main()
