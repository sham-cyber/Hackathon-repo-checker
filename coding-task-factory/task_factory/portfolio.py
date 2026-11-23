"""Deterministic novelty-aware generation for the bundled task catalog."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from .factory import FactoryError, generate_task
from .targets import resolve_target
from .templates import build_spec
from .variation import compare_task_packages, render_comparison, variation_profile


def select_diverse_seeds(
    seed_start: int,
    count: int,
    search_limit: int = 10_000,
) -> tuple[list[int], int]:
    """Pick the earliest seeds with unique recipe-authored variation signatures."""
    if count < 2:
        raise FactoryError("portfolio count must be at least 2")
    if search_limit < 1:
        raise FactoryError("portfolio search limit must be positive")

    selected: list[int] = []
    seen: set[str] = set()
    examined = 0
    for seed in range(seed_start, seed_start + search_limit):
        examined += 1
        signature = variation_profile(build_spec(seed))["structure_signature"]
        if signature in seen:
            continue
        seen.add(signature)
        selected.append(seed)
        if len(selected) == count:
            return selected, examined
    raise FactoryError(
        f"found only {len(selected)} distinct task profiles in "
        f"{examined} seeds; lower --count or expand the task catalog"
    )


def generate_portfolio(
    target_source: str,
    seed_start: int,
    count: int,
    output_dir: str | Path,
    search_limit: int = 10_000,
) -> dict:
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FactoryError(f"portfolio output directory must be empty or absent: {output}")
    seeds, examined = select_diverse_seeds(seed_start, count, search_limit)
    pinned_target = resolve_target(target_source)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".task-portfolio-", dir=output.parent))
    try:
        packages = []
        package_rows = []
        for seed in seeds:
            package = generate_task(
                seed,
                target_source,
                stage / f"seed-{str(seed).replace('-', 'm')}",
            )
            packages.append(package)
            task = json.loads((package / "task.json").read_text(encoding="utf-8"))
            if task["target"]["commit"] != pinned_target.commit:
                raise FactoryError(
                    "target HEAD changed while generating the portfolio; no output was published"
                )
            package_rows.append(
                {
                    "seed": seed,
                    "path": package.name,
                    "task_id": task["task_id"],
                    "family": task["family"],
                    "variation": task["variation"],
                    "task_status": "not_validated",
                }
            )

        comparison = compare_task_packages(packages)
        (stage / "variation-comparison.md").write_text(
            render_comparison(comparison), encoding="utf-8", newline="\n"
        )
        if resolve_target(target_source).commit != pinned_target.commit:
            raise FactoryError(
                "target HEAD changed while generating the portfolio; no output was published"
            )
        portfolio_manifest = {
            "schema_version": 1,
            "target": {
                "repository": pinned_target.source,
                "commit": pinned_target.commit,
            },
            "selection": {
                "seed_start": seed_start,
                "count": count,
                "search_limit": search_limit,
                "candidates_examined": examined,
                "policy": "earliest unique normalized task structures",
            },
            "tasks": package_rows,
            "comparison": {
                "distinct_signatures": comparison["distinct_signatures"],
                "likely_clone_groups": comparison["likely_clone_groups"],
                "unscored_tasks": comparison["unscored_tasks"],
            },
            "portfolio_status": "not_validated",
        }
        (stage / "portfolio.json").write_text(
            json.dumps(portfolio_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if output.exists():
            output.rmdir()
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        "path": str(output),
        "seeds": seeds,
        "distinct_signatures": comparison["distinct_signatures"],
        "likely_clone_groups": comparison["likely_clone_groups"],
        "portfolio_status": "not_validated",
    }
