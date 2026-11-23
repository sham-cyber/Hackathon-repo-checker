"""Deterministic commit/patch seed selection and append-only run records."""

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .factory import FactoryError, _report, generate_task
from .targets import TargetError, _run_git, resolve_target


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_auto_seed(commit_sha: str, patch_bytes: bytes | None = None) -> int:
    """Derive a stable 256-bit integer seed from a commit and optional patch."""
    patch_id = hashlib.sha256(patch_bytes).hexdigest() if patch_bytes else None
    identity = json.dumps(
        {
            "namespace": "coding-task-factory-auto-seed-v1",
            "commit_sha": commit_sha.lower(),
            "patch_sha256": patch_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(identity).digest(), "big")


def _working_tree_patch(target_source: str) -> bytes:
    root = Path(_run_git(["rev-parse", "--show-toplevel"], cwd=Path(target_source)))
    completed = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": os.environ.get("HOME", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if completed.returncode:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise TargetError((message or "could not inspect target working-tree diff")[:1000])
    return completed.stdout


def inspect_seed_reference(
    target_source: str,
    patch_file: str | Path | None = None,
) -> dict:
    target = resolve_target(target_source)
    patch_bytes = None
    patch_source = None
    if patch_file is not None:
        path = Path(patch_file).expanduser().resolve()
        try:
            patch_bytes = path.read_bytes()
        except OSError as exc:
            raise FactoryError(f"could not read patch file: {exc}") from exc
        patch_source = "provided-patch-file"
    elif Path(target_source).expanduser().exists():
        patch_bytes = _working_tree_patch(target_source)
        if patch_bytes:
            patch_source = "tracked-working-tree-diff"

    patch_digest = hashlib.sha256(patch_bytes).hexdigest() if patch_bytes else None
    seed_identity = {
        "commit_sha": target.commit.lower(),
        "patch_sha256": patch_digest,
    }
    source_key = hashlib.sha256(
        json.dumps(seed_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    reference = {
        "commit_sha": target.commit.lower(),
        "patch_identifier": f"sha256:{patch_digest}" if patch_digest else None,
        "patch_source": patch_source,
        "source_key": source_key,
    }
    return {
        "target": target,
        "reference": reference,
        "auto_seed": derive_auto_seed(target.commit, patch_bytes),
    }


def _read_seed_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FactoryError(f"seed log has invalid JSON on line {line_number}") from exc
        if not isinstance(record, dict):
            raise FactoryError(f"seed log line {line_number} must be a JSON object")
        records.append(record)
    return records


def processed_source_keys(log_path: str | Path) -> set[str]:
    return {
        record["source_key"]
        for record in _read_seed_log(Path(log_path).expanduser().resolve())
        if record.get("event") == "task_generated"
        and record.get("seed_mode") == "auto"
        and isinstance(record.get("source_key"), str)
    }


def append_seed_log(log_path: str | Path, record: dict) -> Path:
    path = Path(log_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)
    return path


def _coverage_value(coverage: dict, field: str):
    baseline = coverage.get("baseline", {}).get("total_percent")
    post_patch = coverage.get("post_patch", {}).get("total_percent")
    if field == "baseline":
        return baseline
    if field == "post_patch":
        return post_patch
    return coverage.get("delta_percentage_points")


def _write_seed_run_manifest(package: Path, record: dict, log_path: Path) -> None:
    manifest_path = package / "manifest.json"
    task_path = package / "task.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    task = json.loads(task_path.read_text(encoding="utf-8"))
    seed_run = {
        key: value
        for key, value in record.items()
        if key not in {"timestamp", "package_path"}
    }
    seed_run["log_path"] = str(log_path)
    manifest["seed_run"] = seed_run
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_validation = {
        **(manifest.get("validation") or {}),
        "seed_run": seed_run,
    }
    (package / "run-report.md").write_text(
        _report(task, manifest.get("task_status", "not validated"), report_validation),
        encoding="utf-8",
        newline="\n",
    )


def generate_seeded_run(
    target_source: str,
    output_dir: str | Path,
    *,
    seed_mode: str,
    selected_seed: int | None = None,
    blueprint_dir: str | Path | None = None,
    patch_file: str | Path | None = None,
    log_path: str | Path = "runs/seed_log.jsonl",
    local_validation: bool | None = None,
    timeout: int = 180,
    inspected_state: dict | None = None,
) -> dict:
    if seed_mode not in {"auto", "selected"}:
        raise FactoryError("seed_mode must be 'auto' or 'selected'")
    if seed_mode == "selected" and selected_seed is None:
        raise FactoryError("selected seed mode requires an explicit integer seed")
    if seed_mode == "auto" and selected_seed is not None:
        raise FactoryError("auto seed mode must not include a selected seed")

    state = inspected_state or inspect_seed_reference(target_source, patch_file)
    seed = state["auto_seed"] if seed_mode == "auto" else selected_seed
    run_local_validation = seed_mode == "auto" if local_validation is None else local_validation
    package = generate_task(
        seed,
        target_source,
        output_dir,
        blueprint_dir,
        seed_mode=seed_mode,
        seed_reference=state["reference"],
        target_commit=state["target"].commit,
    )

    validation_result = None
    if run_local_validation:
        from .validation import validate_task

        validation_result = validate_task(package, timeout=timeout)

    task = json.loads((package / "task.json").read_text(encoding="utf-8"))
    coverage = (validation_result or {}).get("coverage", {})
    log_record = {
        "schema_version": 1,
        "event": "task_generated",
        "timestamp": _utc_now(),
        "seed_mode": seed_mode,
        "seed": seed,
        "commit_sha": state["reference"]["commit_sha"],
        "patch_identifier": state["reference"]["patch_identifier"],
        "patch_source": state["reference"]["patch_source"],
        "source_key": state["reference"]["source_key"],
        "task_id": task["task_id"],
        "task_family": task["family"],
        "task_variant": task.get("variation", {}).get("variant"),
        "target_files": task.get("patch_targets", []),
        "baseline_coverage_percent": _coverage_value(coverage, "baseline"),
        "post_patch_coverage_percent": _coverage_value(coverage, "post_patch"),
        "coverage_delta_percentage_points": _coverage_value(coverage, "delta"),
        "coverage_status": coverage.get("status", "not_run"),
        "local_validation_status": (
            validation_result.get("status") if validation_result else "not_run"
        ),
        "harbor_status": "pending",
        "package_path": str(package),
    }
    stored_log = append_seed_log(log_path, log_record)
    _write_seed_run_manifest(package, log_record, stored_log)
    return {
        "package_path": str(package),
        "seed": seed,
        "seed_mode": seed_mode,
        "seed_reference": state["reference"],
        "local_validation": validation_result,
        "log_record": log_record,
        "log_path": str(stored_log),
    }


def watch_target(
    target_source: str,
    output_root: str | Path,
    *,
    log_path: str | Path = "runs/seed_log.jsonl",
    interval_seconds: float = 5,
    timeout: int = 180,
    once: bool = False,
    on_record: Callable[[dict], None] | None = None,
) -> dict:
    if not Path(target_source).expanduser().exists():
        raise FactoryError("watch requires a local target Git checkout")
    if interval_seconds <= 0:
        raise FactoryError("watch interval must be positive")
    output = Path(output_root).expanduser().resolve()
    log = Path(log_path).expanduser().resolve()
    seen = processed_source_keys(log)
    processed = []
    while True:
        state = inspect_seed_reference(target_source)
        source_key = state["reference"]["source_key"]
        if source_key not in seen:
            seed = state["auto_seed"]
            patch_short = (
                state["reference"]["patch_identifier"].split(":", 1)[1][:10]
                if state["reference"]["patch_identifier"]
                else "clean"
            )
            package = output / (
                f"{state['reference']['commit_sha'][:12]}-{patch_short}-{seed:064x}"
            )
            result = generate_seeded_run(
                target_source,
                package,
                seed_mode="auto",
                log_path=log,
                timeout=timeout,
                inspected_state=state,
            )
            processed.append(result["log_record"])
            if on_record is not None:
                on_record(result["log_record"])
            seen.add(source_key)
        if once:
            return {
                "processed": processed,
                "skipped_existing": not processed,
                "log_path": str(log),
            }
        time.sleep(interval_seconds)


def record_harbor_result(task_dir: str | Path, harbor_result: dict) -> dict | None:
    package = Path(task_dir).expanduser().resolve()
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    seed_run = manifest.get("seed_run")
    if not isinstance(seed_run, dict) or not seed_run.get("log_path"):
        return None
    result_status = harbor_result.get("status")
    if result_status in {"valid", "invalid"}:
        harbor_status = result_status
    else:
        harbor_status = "pending"
    record = {
        "schema_version": 1,
        "event": "harbor_validation",
        "timestamp": _utc_now(),
        "seed_mode": seed_run.get("seed_mode"),
        "seed": seed_run.get("seed"),
        "commit_sha": seed_run.get("commit_sha"),
        "patch_identifier": seed_run.get("patch_identifier"),
        "source_key": seed_run.get("source_key"),
        "task_id": seed_run.get("task_id"),
        "harbor_status": harbor_status,
        "trial_summary": {
            phase: [
                {"reward": trial.get("reward"), "atif_recorded": trial.get("atif_recorded")}
                for trial in job.get("trials", [])
            ]
            for phase, job in harbor_result.get("jobs", {}).items()
        },
    }
    log_path = append_seed_log(seed_run["log_path"], record)
    seed_run["harbor_status"] = harbor_status
    seed_run["last_harbor_event"] = {
        "timestamp": record["timestamp"],
        "status": harbor_status,
    }
    manifest["harbor_status"] = harbor_status
    manifest["seed_run"] = seed_run
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    task = json.loads((package / "task.json").read_text(encoding="utf-8"))
    validation = {
        **(manifest.get("validation") or {}),
        "seed_run": seed_run,
    }
    (package / "run-report.md").write_text(
        _report(task, harbor_status, validation), encoding="utf-8", newline="\n"
    )
    return {"log_record": record, "log_path": str(log_path)}


def record_agent_run(task_dir: str | Path, agent_result: dict) -> dict | None:
    package = Path(task_dir).expanduser().resolve()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    seed_run = manifest.get("seed_run")
    if not isinstance(seed_run, dict) or not seed_run.get("log_path"):
        return None
    record = {
        "schema_version": 1,
        "event": "agent_run",
        "timestamp": _utc_now(),
        "seed_mode": seed_run.get("seed_mode"),
        "seed": seed_run.get("seed"),
        "commit_sha": seed_run.get("commit_sha"),
        "patch_identifier": seed_run.get("patch_identifier"),
        "source_key": seed_run.get("source_key"),
        "task_id": seed_run.get("task_id"),
        "harbor_status": seed_run.get("harbor_status", "pending"),
        "agent": agent_result.get("agent"),
        "model": agent_result.get("model"),
        "trial_summary": [
            {
                "reward": trial.get("reward"),
                "atif_recorded": trial.get("atif_recorded", False),
                "atif_trajectory": trial.get("atif_trajectory"),
            }
            for trial in agent_result.get("trials", [])
        ],
    }
    log_path = append_seed_log(seed_run["log_path"], record)
    return {"log_record": record, "log_path": str(log_path)}
