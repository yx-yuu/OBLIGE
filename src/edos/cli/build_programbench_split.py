from __future__ import annotations

import argparse

from edos.programbench.tasks import load_programbench_catalog, write_task_list


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--programbench-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--difficulty", action="append", default=None)
    parser.add_argument("--category", action="append", default=None)
    parser.add_argument("--exclude-repository-prefix", action="append", default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--per-difficulty-limit", type=int, default=None)
    parser.add_argument("--per-category-limit", type=int, default=None)
    args = parser.parse_args()

    difficulty = set(args.difficulty) if args.difficulty else None
    category = set(args.category) if args.category else None
    exclude_repository_prefixes = (
        set(args.exclude_repository_prefix) if args.exclude_repository_prefix else None
    )
    tasks = load_programbench_catalog(
        args.programbench_root,
        limit=args.limit,
        difficulty=difficulty,
        category=category,
        exclude_repository_prefixes=exclude_repository_prefixes,
        seed=args.seed,
        per_difficulty_limit=args.per_difficulty_limit,
        per_category_limit=args.per_category_limit,
    )
    write_task_list(
        args.output,
        tasks,
        metadata={
            "source": "build_programbench_split",
            "programbench_root": args.programbench_root,
            "limit": args.limit,
            "difficulty": sorted(difficulty) if difficulty else [],
            "category": sorted(category) if category else [],
            "exclude_repository_prefix": (
                sorted(exclude_repository_prefixes)
                if exclude_repository_prefixes
                else []
            ),
            "seed": args.seed,
            "per_difficulty_limit": args.per_difficulty_limit,
            "per_category_limit": args.per_category_limit,
            "selection_mode": (
                "stratified"
                if (
                    args.seed is not None
                    or args.per_difficulty_limit is not None
                    or args.per_category_limit is not None
                )
                else "ordered"
            ),
        },
    )
    print(f"Wrote {len(tasks)} ProgramBench tasks to {args.output}")


if __name__ == "__main__":
    main()
