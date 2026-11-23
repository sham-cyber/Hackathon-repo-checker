"""Generate selected seed packages and compare them without running Harbor."""

from pathlib import Path

from .factory import FactoryError
from .seed_runs import generate_seeded_run, inspect_seed_reference
from .variation import compare_task_packages


def generate_seed_comparison(
    target_source: str,
    seeds: list[int],
    output_root: str | Path,
    *,
    blueprint_dir: str | Path | None = None,
    log_path: str | Path = "runs/seed_log.jsonl",
    timeout: int = 180,
) -> dict:
    if len(seeds) < 2:
        raise FactoryError("seed comparison requires at least two seeds")
    if len(set(seeds)) != len(seeds):
        raise FactoryError("seed comparison values must be unique")
    if timeout < 1:
        raise FactoryError("timeout must be a positive number of seconds")

    output = Path(output_root).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FactoryError(f"seed comparison output root must be empty or absent: {output}")
    output.mkdir(parents=True, exist_ok=True)
    initial_state = inspect_seed_reference(target_source)
    packages = []
    for seed in seeds:
        seed_name = str(seed).replace("-", "m")
        result = generate_seeded_run(
            target_source,
            output / f"seed-{seed_name}",
            seed_mode="selected",
            selected_seed=seed,
            blueprint_dir=blueprint_dir,
            log_path=log_path,
            local_validation=True,
            timeout=timeout,
            inspected_state=initial_state,
        )
        packages.append(result["package_path"])
        if result["seed_reference"]["source_key"] != initial_state["reference"]["source_key"]:
            raise FactoryError("target commit or patch changed during seed comparison")

    final_state = inspect_seed_reference(target_source)
    if final_state["reference"]["source_key"] != initial_state["reference"]["source_key"]:
        raise FactoryError("target commit or patch changed during seed comparison")

    report = compare_task_packages(packages)
    report["generated_packages"] = packages
    report["seed_mode"] = "selected"
    report["target_commit"] = initial_state["reference"]["commit_sha"]
    return report
