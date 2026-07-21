from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from edos.instrumentation.logger import utc_now
from edos.jsonutil import to_jsonable


RESERVED_DIRS = {"_archives", "aggregate", "programbench_runs", "__pycache__"}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(to_jsonable(value), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def iter_run_dirs(source: Path) -> list[Path]:
    out = []
    for child in sorted(source.iterdir() if source.exists() else []):
        if not child.is_dir() or child.name in RESERVED_DIRS:
            continue
        if (child / "metadata.json").exists() or (child / "run_manifest.json").exists():
            out.append(child)
    return out


def run_identity(run_dir: Path) -> str:
    metadata = load_json(run_dir / "metadata.json", {})
    manifest = load_json(run_dir / "run_manifest.json", {})
    return str(metadata.get("run_id") or manifest.get("run_id") or run_dir.name)


def copy_tree_no_overwrite(source: Path, target: Path) -> list[str]:
    copied: list[str] = []
    if not source.exists():
        return copied
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if destination.exists():
            raise FileExistsError(f"Merge target already has artifact: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(str(destination))
    return copied


def rewrite_merged_run_manifest(
    *,
    target_run_dir: Path,
    source_root: Path,
    source_run_dir: Path,
) -> None:
    path = target_run_dir / "run_manifest.json"
    if not path.exists():
        return
    manifest = load_json(path, {})
    if not isinstance(manifest, dict):
        return
    manifest.setdefault("source_run_dir", str(source_run_dir))
    manifest["run_dir"] = str(target_run_dir)
    manifest["merged_from"] = str(source_root)
    manifest["merged_at"] = utc_now()
    write_json(path, manifest)


def rewrite_run_index_item(item: dict, *, source_root: Path, output_dir: Path) -> dict:
    row = dict(item)
    run_id = str(row.get("run_id") or "")
    if run_id:
        row.setdefault("source_run_dir", row.get("run_dir", ""))
        row["run_dir"] = str(output_dir / run_id)
    row["merged_from"] = str(source_root)
    return row


def rewrite_planned_item(item: dict, *, source_root: Path, output_dir: Path) -> dict:
    row = dict(item)
    run_id = str(row.get("run_id") or "")
    if run_id:
        row.setdefault("source_run_dir", row.get("run_dir", ""))
        row["run_dir"] = str(output_dir / run_id)
    row["merged_from"] = str(source_root)
    return row


def merge_experiment_shards(
    *,
    sources: list[str | Path],
    output_dir: str | Path,
    allow_existing: bool = False,
) -> dict:
    output = Path(output_dir)
    if output.exists() and not allow_existing:
        raise FileExistsError(
            f"Output directory already exists: {output}. Use --allow-existing to merge into it."
        )
    output.mkdir(parents=True, exist_ok=True)

    seen_run_ids: dict[str, Path] = {}
    run_index: list[dict] = []
    planned_runs: list[dict] = []
    source_summaries: list[dict] = []
    copied_runs = 0
    copied_artifacts = 0

    for raw_source in sources:
        source = Path(raw_source)
        if not source.exists() or not source.is_dir():
            raise FileNotFoundError(f"Shard source directory not found: {source}")
        source_summary = {
            "source": str(source),
            "experiment": load_json(source / "experiment.resolved.json", {}),
            "run_count": 0,
            "programbench_artifacts": 0,
        }

        for source_run_dir in iter_run_dirs(source):
            run_id = run_identity(source_run_dir)
            if run_id in seen_run_ids:
                raise ValueError(
                    f"Duplicate run_id {run_id!r} in {source_run_dir} and {seen_run_ids[run_id]}"
                )
            seen_run_ids[run_id] = source_run_dir
            target_run_dir = output / run_id
            if target_run_dir.exists():
                raise FileExistsError(f"Merge target already has run dir: {target_run_dir}")
            shutil.copytree(source_run_dir, target_run_dir, symlinks=True)
            rewrite_merged_run_manifest(
                target_run_dir=target_run_dir,
                source_root=source,
                source_run_dir=source_run_dir,
            )
            copied_runs += 1
            source_summary["run_count"] += 1

        for item in load_json(source / "run_index.json", []):
            if isinstance(item, dict):
                run_index.append(
                    rewrite_run_index_item(
                        item,
                        source_root=source,
                        output_dir=output,
                    )
                )
        for item in load_json(source / "planned_runs.json", []):
            if isinstance(item, dict):
                planned_runs.append(
                    rewrite_planned_item(
                        item,
                        source_root=source,
                        output_dir=output,
                    )
                )

        artifact_paths = copy_tree_no_overwrite(
            source / "programbench_runs",
            output / "programbench_runs",
        )
        copied_artifacts += len(artifact_paths)
        source_summary["programbench_artifacts"] = len(artifact_paths)
        source_summaries.append(source_summary)

    duplicate_index_ids = duplicate_values(
        str(item.get("run_id") or "") for item in run_index if isinstance(item, dict)
    )
    if duplicate_index_ids:
        raise ValueError(
            "Duplicate run_id values in merged run_index: "
            + ", ".join(sorted(duplicate_index_ids))
        )

    summary = {
        "schema_version": "1.0",
        "merged_at": utc_now(),
        "output_dir": str(output),
        "sources": source_summaries,
        "run_count": copied_runs,
        "run_index_count": len(run_index),
        "planned_run_count": len(planned_runs),
        "programbench_artifact_count": copied_artifacts,
    }
    write_json(output / "merge_summary.json", summary)
    write_json(output / "run_index.json", run_index)
    write_json(output / "planned_runs.json", planned_runs)
    return summary


def duplicate_values(values: Any) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-existing", action="store_true")
    args = parser.parse_args()
    summary = merge_experiment_shards(
        sources=args.source,
        output_dir=args.output_dir,
        allow_existing=args.allow_existing,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
