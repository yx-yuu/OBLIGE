import json
import tempfile
import unittest
from pathlib import Path

from edos.cli.merge_experiment_shards import merge_experiment_shards


class MergeExperimentShardsTest(unittest.TestCase):
    def test_merge_experiment_shards_copies_runs_and_programbench_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shard_a = root / "shard_a"
            shard_b = root / "shard_b"
            self._write_shard(shard_a, run_dir_name="local_a", run_id="run_a")
            self._write_shard(shard_b, run_dir_name="local_b", run_id="run_b")

            summary = merge_experiment_shards(
                sources=[shard_a, shard_b],
                output_dir=root / "merged",
            )

            merged = root / "merged"
            self.assertEqual(summary["run_count"], 2)
            self.assertEqual(summary["run_index_count"], 2)
            self.assertTrue((merged / "run_a" / "metadata.json").exists())
            self.assertTrue((merged / "run_b" / "metadata.json").exists())
            manifest = json.loads(
                (merged / "run_a" / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["run_dir"], str(merged / "run_a"))
            self.assertEqual(manifest["merged_from"], str(shard_a))
            self.assertEqual(manifest["source_run_dir"], str(shard_a / "local_a"))
            run_index = json.loads(
                (merged / "run_index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                {item["run_dir"] for item in run_index},
                {str(merged / "run_a"), str(merged / "run_b")},
            )
            self.assertTrue(
                (
                    merged
                    / "programbench_runs"
                    / "clean"
                    / "task_run_a"
                    / "submission.tar.gz"
                ).exists()
            )
            self.assertTrue((merged / "merge_summary.json").exists())

    def test_merge_experiment_shards_rejects_duplicate_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shard_a = root / "shard_a"
            shard_b = root / "shard_b"
            self._write_shard(shard_a, run_dir_name="local_a", run_id="same_run")
            self._write_shard(shard_b, run_dir_name="local_b", run_id="same_run")

            with self.assertRaises(ValueError):
                merge_experiment_shards(
                    sources=[shard_a, shard_b],
                    output_dir=root / "merged",
                )

    def _write_shard(self, root: Path, *, run_dir_name: str, run_id: str) -> None:
        run_dir = root / run_dir_name
        run_dir.mkdir(parents=True)
        self._write_json(
            root / "experiment.resolved.json",
            {"experiment_name": f"exp_{run_id}", "task_count": 1},
        )
        self._write_json(
            run_dir / "metadata.json",
            {
                "run_id": run_id,
                "task_id": f"task_{run_id}",
                "condition": "clean",
                "ended_at": "2026-05-25T00:00:00Z",
            },
        )
        self._write_json(
            run_dir / "run_manifest.json",
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "status": "complete",
            },
        )
        self._write_json(
            root / "run_index.json",
            [
                {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "status": "complete",
                    "score_status": "local_reference",
                }
            ],
        )
        self._write_json(
            root / "planned_runs.json",
            [
                {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "status": "planned",
                }
            ],
        )
        artifact = (
            root
            / "programbench_runs"
            / "clean"
            / f"task_{run_id}"
            / "submission.tar.gz"
        )
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"sample submission")

    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
