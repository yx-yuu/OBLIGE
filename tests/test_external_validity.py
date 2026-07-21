import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.analysis.external_validity import build_external_validity_bundle


class ExternalValidityEvidenceTest(unittest.TestCase):
    def test_bundle_keeps_agent_runtime_surface_effects_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opencode = root / "opencode"
            mini = root / "mini"
            openhands = root / "openhands"
            self._write_agent_aggregate(
                opencode,
                agent_runtime="opencode",
                model="bigmodel/glm-5.1",
                exposure="opencode_skill",
                surface="skill",
                usage_source="opencode_reported_step_tokens",
                extra_tokens="120.0",
                official=True,
            )
            self._write_agent_aggregate(
                mini,
                agent_runtime="mini_sweagent_programbench",
                model="bigmodel/glm-5.1",
                exposure="workflow_enforced",
                surface="runtime_hook",
                usage_source="mini_sweagent_reported_tokens",
                extra_tokens="45.0",
                official=False,
            )
            self._write_agent_aggregate(
                openhands,
                agent_runtime="openhands",
                model="openai/glm-5.1",
                exposure="openhands_mcp",
                surface="mcp_or_tool_manifest",
                usage_source="openhands_reported_tokens",
                extra_tokens="15.0",
                official=False,
            )

            output = root / "external"
            paths = build_external_validity_bundle(
                [opencode, mini, openhands],
                output_dir=output,
            )

            surface_rows = self._read_csv(paths["surface"])
            condition_rows = self._read_csv(paths["condition"])
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            boundaries = paths["boundaries"].read_text(encoding="utf-8")

        self.assertEqual(summary["agent_runtime_count"], 3)
        self.assertEqual(
            set(summary["agent_runtimes"]),
            {"mini_sweagent_programbench", "opencode", "openhands"},
        )
        self.assertEqual(summary["official_tests_json_runs"], 2)
        self.assertIn("matched agent, model, task, and adoption surface", boundaries)

        by_runtime = {row["agent_runtime"]: row for row in surface_rows}
        self.assertIn("primary mechanism runtime", by_runtime["opencode"]["external_validity_scope"])
        self.assertIn("ProgramBench-aligned mechanism", by_runtime["mini_sweagent_programbench"]["external_validity_scope"])
        self.assertIn("external-validity", by_runtime["openhands"]["external_validity_scope"])
        self.assertEqual(by_runtime["opencode"]["official_tests_json_runs"], "2")
        self.assertEqual(by_runtime["openhands"]["official_tests_json_runs"], "0")

        adaptive_rows = {
            row["agent_runtime"]: row
            for row in condition_rows
            if row["condition"] == "adaptive_full_medium"
        }
        self.assertEqual(set(adaptive_rows), {"mini_sweagent_programbench", "opencode", "openhands"})
        self.assertEqual(adaptive_rows["opencode"]["avg_extra_tokens_est"], "120.0")
        self.assertEqual(adaptive_rows["mini_sweagent_programbench"]["avg_extra_tokens_est"], "45.0")
        self.assertEqual(adaptive_rows["openhands"]["avg_extra_tokens_est"], "15.0")
        self.assertIn(
            "primary_official_programbench",
            adaptive_rows["opencode"]["condition_claim_scope"],
        )
        self.assertIn(
            "programbench_aligned_mechanism",
            adaptive_rows["mini_sweagent_programbench"]["condition_claim_scope"],
        )
        self.assertIn(
            "external_validity_pilot",
            adaptive_rows["openhands"]["condition_claim_scope"],
        )

    def test_cli_writes_external_validity_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opencode = root / "opencode"
            openhands = root / "openhands"
            self._write_agent_aggregate(
                opencode,
                agent_runtime="opencode",
                model="model",
                exposure="opencode_skill",
                surface="skill",
                usage_source="opencode_reported_step_tokens",
                extra_tokens="10.0",
                official=True,
            )
            self._write_agent_aggregate(
                openhands,
                agent_runtime="openhands",
                model="model",
                exposure="openhands_mcp",
                surface="mcp_or_tool_manifest",
                usage_source="openhands_json_estimate",
                extra_tokens="5.0",
                official=False,
            )

            output = root / "bundle"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "edos.cli.build_external_validity_evidence",
                    "--run-dir",
                    str(opencode),
                    "--run-dir",
                    str(openhands),
                    "--output-dir",
                    str(output),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("agent_surface_evidence.csv", completed.stdout)
            self.assertTrue((output / "external_validity_summary.json").exists())

    def _write_agent_aggregate(
        self,
        root: Path,
        *,
        agent_runtime: str,
        model: str,
        exposure: str,
        surface: str,
        usage_source: str,
        extra_tokens: str,
        official: bool,
    ) -> None:
        aggregate = root / "aggregate"
        scoring_mode = "official_tests_json" if official else ""
        score_status = "programbench_eval" if official else "local_reference"
        self._write_csv(
            aggregate / "runs.csv",
            [
                self._run_row(
                    run_id=f"{agent_runtime}_clean",
                    agent_runtime=agent_runtime,
                    model=model,
                    exposure=exposure,
                    surface=surface,
                    condition="clean_skill_clean_verifier",
                    target_level="none",
                    verifier_calls="1",
                    input_tokens="100",
                    output_tokens="10",
                    usage_source=usage_source,
                    score_status=score_status,
                    scoring_mode=scoring_mode,
                ),
                self._run_row(
                    run_id=f"{agent_runtime}_adaptive",
                    agent_runtime=agent_runtime,
                    model=model,
                    exposure=exposure,
                    surface=surface,
                    condition="adaptive_full_medium",
                    target_level="medium",
                    verifier_calls="3",
                    input_tokens="150",
                    output_tokens="20",
                    usage_source=usage_source,
                    score_status=score_status,
                    scoring_mode=scoring_mode,
                ),
            ],
        )
        self._write_csv(
            aggregate / "metrics.csv",
            [
                {
                    "run_id": f"{agent_runtime}_clean",
                    "agent_runtime": agent_runtime,
                    "model": model,
                    "verifier_exposure_condition": exposure,
                    "entry_surface": surface,
                    "task_id": "task",
                    "condition": "clean_skill_clean_verifier",
                    "target_level": "none",
                    "extra_tokens_est": "0.0",
                },
                {
                    "run_id": f"{agent_runtime}_adaptive",
                    "agent_runtime": agent_runtime,
                    "model": model,
                    "verifier_exposure_condition": exposure,
                    "entry_surface": surface,
                    "task_id": "task",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "extra_tokens_est": extra_tokens,
                },
            ],
        )
        self._write_csv(
            aggregate / "target_cost_error.csv",
            [
                {
                    "run_id": f"{agent_runtime}_adaptive",
                    "agent_runtime": agent_runtime,
                    "model": model,
                    "verifier_exposure_condition": exposure,
                    "entry_surface": surface,
                    "task_id": "task",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "baseline_available": "True",
                    "controller_target_interval_hit": "True",
                    "target_interval_hit": "False",
                }
            ],
        )

    def _run_row(
        self,
        *,
        run_id: str,
        agent_runtime: str,
        model: str,
        exposure: str,
        surface: str,
        condition: str,
        target_level: str,
        verifier_calls: str,
        input_tokens: str,
        output_tokens: str,
        usage_source: str,
        score_status: str,
        scoring_mode: str,
    ) -> dict[str, str]:
        return {
            "run_id": run_id,
            "experiment_name": f"{agent_runtime}_external_smoke",
            "task_id": "task",
            "task_difficulty": "easy",
            "task_category": "text",
            "agent_runtime": agent_runtime,
            "model": model,
            "condition": condition,
            "target_level": target_level,
            "verifier_exposure_condition": exposure,
            "entry_surface": surface,
            "run_record_complete": "True",
            "agent_facing_condition_leak": "False",
            "usage_source": usage_source,
            "input_tokens_est": input_tokens,
            "output_tokens_est": output_tokens,
            "api_calls": "1",
            "wall_clock_seconds": "1.0",
            "verifier_calls": verifier_calls,
            "verifier_blocked_attempts": "0",
            "tests_passed_fraction": "0.7",
            "candidate_build_success": "True",
            "final_submission_seen": "True",
            "score_status": score_status,
            "programbench_scoring_mode": scoring_mode,
            "failure_label": "",
        }

    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields: list[str] = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
