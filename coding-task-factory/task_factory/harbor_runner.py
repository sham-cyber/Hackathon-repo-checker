import json
import math
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .factory import _report
from .validation import _load_task, _verify_task_files


_BASE_ENVIRONMENT_KEYS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "CONTAINER_HOST",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "UV_CACHE_DIR",
)
_MODEL_CREDENTIAL_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
    "XAI_API_KEY",
    "CEREBRAS_API_KEY",
    "HF_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "AWS_PROFILE",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _harbor_environment(*, include_model_credentials: bool) -> dict[str, str]:
    keys = _BASE_ENVIRONMENT_KEYS
    if include_model_credentials:
        keys += _MODEL_CREDENTIAL_KEYS
    return {key: os.environ[key] for key in keys if key in os.environ}


def _read_trials(job_dir: Path) -> list[dict]:
    trials = []
    for reward_file in sorted(job_dir.rglob("reward.txt")):
        if reward_file.parent.name != "verifier":
            continue
        trial_dir = reward_file.parent.parent
        try:
            raw_reward = reward_file.read_text(encoding="utf-8").strip()
            reward = float(raw_reward)
            if not math.isfinite(reward):
                reward = None
        except (OSError, ValueError):
            raw_reward = None
            reward = None
        relative_trial = trial_dir.relative_to(job_dir).as_posix()
        trajectory = trial_dir / "agent" / "trajectory.json"
        result_file = next(
            (
                path
                for path in (trial_dir / "results.json", trial_dir / "result.json")
                if path.is_file()
            ),
            None,
        )
        trials.append(
            {
                "trial": relative_trial,
                "reward": reward,
                "raw_reward": raw_reward,
                "reward_file": str(reward_file),
                "results_file": str(result_file) if result_file else None,
                "atif_trajectory": str(trajectory) if trajectory.is_file() else None,
                "atif_recorded": trajectory.is_file(),
            }
        )
    return trials


def _run_job(
    task_dir: Path,
    jobs_root: Path,
    phase: str,
    agent: str,
    *,
    model: str | None = None,
    attempts: int = 1,
    harbor_bin: str = "harbor",
    timeout: int = 7200,
    include_model_credentials: bool = False,
) -> dict:
    executable = shutil.which(harbor_bin)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    job_name = f"{task_dir.name}-{phase}-{timestamp}"
    job_dir = (jobs_root / job_name).resolve()
    command = [
        executable or harbor_bin,
        "run",
        "-p",
        str(task_dir),
        "-a",
        agent,
        "-o",
        str(job_dir),
        "--job-name",
        job_name,
    ]
    if model:
        command.extend(["-m", model])
    if attempts > 1:
        command.extend(["-k", str(attempts)])
    result = {
        "job_name": job_name,
        "job_dir": str(job_dir),
        "agent": agent,
        "model": model,
        "attempts": attempts,
        "command": command,
        "started_at_utc": _utc_now(),
        "executed": False,
        "exit_code": None,
        "trials": [],
    }
    if executable is None:
        result["status"] = "unsupported"
        result["message"] = f"Harbor executable was not found: {harbor_bin}"
        return result
    job_dir.mkdir(parents=True, exist_ok=False)
    result["executed"] = True
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=task_dir.parent,
            env=_harbor_environment(include_model_credentials=include_model_credentials),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        result["exit_code"] = completed.returncode
    except subprocess.TimeoutExpired:
        result["status"] = "timed_out"
    except OSError as exc:
        result["status"] = "unsupported"
        result["message"] = f"could not start Harbor: {exc.__class__.__name__}"
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    result["finished_at_utc"] = _utc_now()
    result["trials"] = _read_trials(job_dir)
    if "status" not in result:
        result["status"] = "completed" if result["trials"] else "missing_reward"
    return result


def _save(task_dir: Path, task: dict, manifest: dict) -> None:
    harbor_status = (manifest.get("validation") or {}).get("harbor", {}).get(
        "status", "not_run"
    )
    manifest["harbor_status"] = (
        harbor_status if harbor_status in {"valid", "invalid"} else "pending"
    )
    (task_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validation = manifest.get("validation") or {}
    report_status = "valid" if harbor_status == "valid" else harbor_status.replace("_", " ")
    (task_dir / "run-report.md").write_text(
        _report(
            task | {"agent_runs": manifest.get("agent_runs", [])},
            report_status,
            {**validation, "seed_run": manifest.get("seed_run", {})},
        ),
        encoding="utf-8",
    )


def _phase_has_reward(job: dict, expected: float) -> bool:
    trials = job.get("trials", [])
    return (
        job.get("status") == "completed"
        and bool(trials)
        and all(trial.get("reward") == expected for trial in trials)
    )


def run_harbor_validation(
    task_dir: str | Path,
    jobs_dir: str | Path | None = None,
    *,
    harbor_bin: str = "harbor",
    timeout: int = 7200,
) -> dict:
    package = Path(task_dir).expanduser().resolve()
    task, manifest = _load_task(package)
    _verify_task_files(package, manifest)
    jobs_root = Path(jobs_dir).expanduser().resolve() if jobs_dir else package.parent / "harbor-jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)

    harbor = {
        "status": "not_validated",
        "required_rewards": {"nop": 0, "oracle": 1},
        "command_templates": [
            ["harbor", "run", "-p", str(package), "-a", "nop"],
            ["harbor", "run", "-p", str(package), "-a", "oracle"],
        ],
        "started_at_utc": _utc_now(),
        "jobs": {},
    }
    validation_state = manifest.get("validation") or {}
    previous = validation_state.get("harbor")
    history = validation_state.setdefault("harbor_history", [])
    if previous and previous.get("status") not in {None, "not_run"}:
        history.append(previous)
    validation_state["harbor"] = harbor
    manifest["validation"] = validation_state
    manifest["task_status"] = "not_validated"
    _save(package, task, manifest)
    for phase, agent in (("nop", "nop"), ("oracle", "oracle")):
        job = _run_job(
            package,
            jobs_root,
            phase,
            agent,
            harbor_bin=harbor_bin,
            timeout=timeout,
        )
        harbor["jobs"][phase] = job
        manifest["validation"]["harbor"] = harbor
        _save(package, task, manifest)
    harbor["finished_at_utc"] = _utc_now()
    jobs = harbor["jobs"]
    if any(job.get("status") == "unsupported" for job in jobs.values()):
        harbor["status"] = "unsupported"
        harbor["message"] = "Harbor could not run; no task validity claim is made."
    elif not jobs["nop"].get("trials") or not jobs["oracle"].get("trials"):
        harbor["status"] = "not_validated"
        harbor["message"] = (
            "A required Harbor job did not produce readable verifier reward files. "
            "Check Docker setup and native runtime/dependency availability."
        )
    elif any(job.get("status") != "completed" for job in jobs.values()):
        harbor["status"] = "not_validated"
        harbor["message"] = (
            "At least one Harbor job did not complete. Inspect its job output and "
            "check Docker and native runtime/dependency availability."
        )
    elif not _phase_has_reward(jobs["nop"], 0):
        harbor["status"] = "invalid"
        harbor["message"] = (
            "The nop trial did not consistently reward 0, so the baseline is not "
            "proven incomplete."
        )
    elif _phase_has_reward(jobs["oracle"], 1):
        harbor["status"] = "valid"
        harbor["message"] = "Harbor nop trials all rewarded 0 and oracle trials all rewarded 1."
    else:
        harbor["status"] = "not_validated"
        harbor["message"] = (
            "The oracle reward was not 1. This may indicate a reference or environment "
            "problem; inspect Harbor trial logs before treating it as a task defect."
        )
    manifest["validation"]["harbor"] = harbor
    manifest["task_status"] = "valid" if harbor["status"] == "valid" else "not_validated"
    _save(package, task, manifest)
    from .seed_runs import record_harbor_result

    record_harbor_result(package, harbor)
    return harbor


def run_agent_benchmark(
    task_dir: str | Path,
    agent: str,
    model: str,
    attempts: int = 1,
    jobs_dir: str | Path | None = None,
    *,
    harbor_bin: str = "harbor",
    timeout: int = 14400,
) -> dict:
    package = Path(task_dir).expanduser().resolve()
    task, manifest = _load_task(package)
    _verify_task_files(package, manifest)
    if manifest.get("task_status") != "valid":
        raise ValueError("run Harbor agent trials only after nop/oracle validation is valid")
    for label, value in (("agent", agent), ("model", model)):
        if not isinstance(value, str) or not value.strip() or "\n" in value or "\x00" in value:
            raise ValueError(f"{label} must be a non-empty single-line value")
    if not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    jobs_root = Path(jobs_dir).expanduser().resolve() if jobs_dir else package.parent / "harbor-jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    job = _run_job(
        package,
        jobs_root,
        "agent",
        agent,
        model=model,
        attempts=attempts,
        harbor_bin=harbor_bin,
        timeout=timeout,
        include_model_credentials=True,
    )
    rewards = [trial["reward"] for trial in job.get("trials", []) if trial.get("reward") is not None]
    job["observed_pass_rate"] = (
        sum(reward == 1 for reward in rewards) / len(rewards) if rewards else None
    )
    job["atif_recorded_trials"] = sum(
        bool(trial.get("atif_recorded")) for trial in job.get("trials", [])
    )
    job["status"] = "completed" if job.get("trials") else job.get("status", "missing_reward")
    manifest.setdefault("agent_runs", []).append(job)
    _save(package, task, manifest)
    from .seed_runs import record_agent_run

    record_agent_run(package, job)
    return job
