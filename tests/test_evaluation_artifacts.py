import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edos.analysis.evaluation_artifacts import (
    PAPER_TABLE_SCHEMAS,
    TABLE_SPECS,
    build_evaluation_artifacts,
)


class EvaluationArtifactsTest(unittest.TestCase):
    def test_smoke_mode_generates_all_evaluation_tables_and_figures(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "eval"
            paths = build_evaluation_artifacts(output_dir=out, mode="smoke")
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))

            self.assertEqual(manifest["artifact_mode"], "reviewer_smoke_fixture")
            self.assertEqual(set(manifest["tables"]), {label for label, _, _ in TABLE_SPECS})
            for _label, stem, _caption in TABLE_SPECS:
                csv_path = out / "tables" / f"{stem}.csv"
                tex_path = out / "tables" / f"{stem}.tex"
                self.assertTrue(csv_path.exists(), stem)
                self.assertTrue(tex_path.exists(), stem)
                self.assertGreater(len(self._read_csv(csv_path)), 0, stem)
            self.assertTrue((out / "figures" / "fig_control.pdf").exists())
            self.assertTrue((out / "figures" / "fig_token_growth.pdf").exists())
            self.assertIn("full Evaluation artifact schema", manifest["artifact_scope"])

    def test_smoke_mode_covers_paper_table_columns_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "eval"
            build_evaluation_artifacts(output_dir=out, mode="smoke")

            for label, schema in PAPER_TABLE_SCHEMAS.items():
                with self.subTest(label=label):
                    csv_path = out / "tables" / f"{schema['stem']}.csv"
                    rows = self._read_csv(csv_path)
                    columns = set(rows[0].keys())
                    observed = {self._row_key(row, str(schema["row_field"])) for row in rows}

                    self.assertTrue(set(schema["internal_columns"]).issubset(columns))
                    self.assertTrue(set(schema["paper_rows"]).issubset(observed))

    def test_aggregate_mode_reads_existing_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            out = Path(tmp) / "eval"
            self._write_minimal_aggregate(root)

            paths = build_evaluation_artifacts(
                output_dir=out,
                mode="aggregate",
                run_dir=root,
            )
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            main_rows = self._read_csv(out / "tables" / "table_main_results.csv")
            control_rows = self._read_csv(out / "tables" / "table_control.csv")

            self.assertEqual(manifest["artifact_mode"], "aggregate_observed")
            self.assertTrue(any(row["condition"] == "OBLIGE med." for row in main_rows))
            self.assertTrue(any(row["condition"] == "OBLIGE med." for row in control_rows))
            self.assertTrue(any(row["condition"] == "static IPI" for row in control_rows))
            self.assertTrue((out / "figures" / "fig_control.pdf").exists())

    def test_cli_smoke_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "eval"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "edos.cli.build_evaluation_artifacts",
                    "--mode",
                    "smoke",
                    "--output-dir",
                    str(out),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("manifest:", completed.stdout)
            self.assertTrue((out / "evaluation_artifacts_manifest.json").exists())

    def _write_minimal_aggregate(self, root: Path) -> None:
        aggregate = root / "aggregate"
        self._write_csv(
            aggregate / "runs.csv",
            [
                self._run("clean", "clean_skill_clean_verifier", "none", "1", "0", "opencode", "model"),
                self._run("attack", "adaptive_full_medium", "medium", "3", "1", "opencode", "model"),
            ],
        )
        self._write_csv(
            aggregate / "metrics.csv",
            [
                self._metric("clean", "clean_skill_clean_verifier", "none", total=1000, baseline=1000, caf=1.0, tests=0.8, calls=2, vf=0),
                self._metric("attack", "adaptive_full_medium", "medium", total=5000, baseline=1000, caf=5.0, tests=0.79, calls=6, vf=3),
                self._metric("static", "static_ipi", "medium", total=1800, baseline=1000, caf=1.8, tests=0.8, calls=3, vf=1),
            ],
        )
        self._write_csv(
            aggregate / "target_cost_error.csv",
            [
                {
                    "run_id": "attack",
                    "condition": "adaptive_full_medium",
                    "target_level": "medium",
                    "target_extra_cost": "4000",
                    "target_extra_cost_lower": "3000",
                    "target_extra_cost_upper": "5000",
                    "target_cost_error": "0",
                    "target_interval_hit": "True",
                    "overshoot": "False",
                    "undershoot": "False",
                }
            ],
        )
        self._write_csv(
            aggregate / "adoption_summary.csv",
            [
                {
                    "verifier_exposure_condition": "workflow",
                    "entry_surface": "workflow",
                    "runs": "2",
                    "adopted_runs": "1",
                    "verifier_adoption_rate": "0.5",
                    "runs_with_no_verifier_call": "1",
                    "avg_first_verifier_call_turn": "2",
                    "avg_verifier_calls_per_run": "1.5",
                }
            ],
        )

    def _run(
        self,
        run_id: str,
        condition: str,
        target: str,
        verifier_calls: str,
        repeat: str,
        agent: str,
        model: str,
    ) -> dict[str, str]:
        return {
            "run_id": run_id,
            "repeat_index": repeat,
            "task_id": "task",
            "task_difficulty": "easy",
            "task_category": "text-processing",
            "agent_runtime": agent,
            "model": model,
            "condition": condition,
            "target_level": target,
            "verifier_exposure_condition": "workflow",
            "entry_surface": "workflow",
            "verifier_calls": verifier_calls,
            "candidate_build_success": "True",
            "final_submission_seen": "True",
            "failure_label": "",
        }

    def _metric(
        self,
        run_id: str,
        condition: str,
        target: str,
        *,
        total: int,
        baseline: int,
        caf: float,
        tests: float,
        calls: int,
        vf: int,
    ) -> dict[str, str]:
        return {
            "run_id": run_id,
            "repeat_index": "0",
            "task_id": "task",
            "condition": condition,
            "target_level": target,
            "total_tokens_est": str(total),
            "baseline_tokens_est": str(baseline),
            "extra_tokens_est": str(total - baseline),
            "cost_amplification_factor": str(caf),
            "api_calls": str(calls),
            "verifier_calls": str(vf),
            "tests_passed_fraction": str(tests),
            "candidate_build_success": "True",
            "final_submission_seen": "True",
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

    def _row_key(self, row: dict[str, str], row_field: str) -> str:
        if row_field == "agent_surface":
            return f"{row.get('agent', '')} / {row.get('adoption_surface', '')}"
        return row.get(row_field, "")


if __name__ == "__main__":
    unittest.main()
