import hashlib
import gzip
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from . import __version__
from .models import TASK_TEST_PATH, Target
from .scanner import scan_repository
from .targets import resolve_target
from .templates import build_spec
from .variation import variation_profile


class FactoryError(RuntimeError):
    pass


HARBOR_WORKSPACE = "/workspace"
HARBOR_REWARD_FILE = "/logs/verifier/reward.txt"
HARBOR_TEST_PAYLOAD = "tests/payload"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_executable(path: Path, content: str) -> None:
    _write(path, content)
    path.chmod(0o755)


def render_reward_wrapper(command: list[str], files: list[dict], working_directory: str) -> str:
    """Render Harbor's verifier entrypoint for one task-native test command."""
    lines = [
        "#!/bin/sh",
        "# Harbor grades /logs/verifier/reward.txt; the exit code is diagnostic only.",
        "set +e",
        f'REWARD_FILE="${{VERIFIER_REWARD_FILE:-{HARBOR_REWARD_FILE}}}"',
        f'PROJECT_ROOT="${{TASK_PROJECT_ROOT:-{HARBOR_WORKSPACE}}}"',
        'TESTS_DIR="${TASK_TESTS_DIR:-/tests/payload}"',
        'mkdir -p "$(dirname "$REWARD_FILE")" || exit 1',
        "printf '0\\n' > \"$REWARD_FILE\" || exit 1",
    ]
    for item in files:
        package_path = item["package_path"]
        prefix = HARBOR_TEST_PAYLOAD + "/"
        if not package_path.startswith(prefix):
            raise FactoryError("Harbor test payload paths must be under tests/payload/")
        payload_path = package_path[len(prefix) :]
        destination = item["target_path"]
        parent = posixpath.dirname(destination)
        if parent:
            lines.append(f'mkdir -p "$PROJECT_ROOT"/{shlex.quote(parent)} || exit 1')
        lines.append(
            f'cp "$TESTS_DIR"/{shlex.quote(payload_path)} '
            f'"$PROJECT_ROOT"/{shlex.quote(destination)} || exit 1'
        )
    lines.extend(
        [
            f'cd "$PROJECT_ROOT"/{shlex.quote(working_directory)} || exit 1',
            shlex.join(command),
            "native_status=$?",
            'if [ "$native_status" -eq 0 ]; then',
            '  printf \'1\\n\' > "$REWARD_FILE" || { printf \'0\\n\' > "$REWARD_FILE" 2>/dev/null; exit 1; }',
            "else",
            '  printf \'0\\n\' > "$REWARD_FILE" || exit 1',
            "fi",
            'exit "$native_status"',
            "",
        ]
    )
    return "\n".join(lines)


def _verify_harbor_export(package: Path, task: dict) -> None:
    required_files = (
        "task.toml",
        "instruction.md",
        "environment/Dockerfile",
        "solution/solve.sh",
        "tests/test.sh",
    )
    missing = [relative for relative in required_files if not (package / relative).is_file()]
    if missing:
        raise FactoryError(
            "generated Harbor package is missing required files: " + ", ".join(missing)
        )

    for relative in ("solution/solve.sh", "tests/test.sh"):
        script = package / relative
        data = script.read_bytes()
        if not script.stat().st_mode & 0o111:
            raise FactoryError(f"generated Harbor script is not executable: {relative}")
        if b"\r" in data or not data.endswith(b"\n"):
            raise FactoryError(f"generated Harbor script must use LF line endings: {relative}")

    lines = (package / "tests/test.sh").read_text(encoding="utf-8").splitlines()
    required_order = (
        'mkdir -p "$(dirname "$REWARD_FILE")" || exit 1',
        "printf '0\\n' > \"$REWARD_FILE\" || exit 1",
        shlex.join(task.get("tests", {}).get("command", [])),
        "native_status=$?",
        'if [ "$native_status" -eq 0 ]; then',
        '  printf \'1\\n\' > "$REWARD_FILE" || { printf \'0\\n\' > "$REWARD_FILE" 2>/dev/null; exit 1; }',
        "else",
        '  printf \'0\\n\' > "$REWARD_FILE" || exit 1',
    )
    positions = []
    for line in required_order:
        try:
            positions.append(lines.index(line))
        except ValueError as exc:
            raise FactoryError(
                "generated tests/test.sh does not preserve the Harbor reward-file contract"
            ) from exc
    if positions != sorted(positions):
        raise FactoryError(
            "generated tests/test.sh must reset reward to 0 before tests and write 1 only on success"
        )


def _render_solve_script() -> str:
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        f'PROJECT_ROOT="${{TASK_PROJECT_ROOT:-{HARBOR_WORKSPACE}}}"\n'
        'PATCH_FILE="${TASK_SOLUTION_PATCH:-/solution/reference.patch}"\n'
        'cd "$PROJECT_ROOT"\n'
        'git apply "$PATCH_FILE"\n'
    )


def _render_go_dockerfile() -> str:
    return """FROM golang:1.27.3
WORKDIR /workspace
COPY source.tar.gz /tmp/task-source.tar.gz
RUN tar -xzf /tmp/task-source.tar.gz -C /workspace && rm /tmp/task-source.tar.gz
RUN command -v git
RUN cd /workspace/plugins/fraudguard && go mod download
ENV GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local GOFLAGS=-mod=readonly
"""


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_task_toml(task: dict, harbor_config: dict | None = None) -> str:
    harbor_config = harbor_config or {}
    name = f"innodata-frontier-ai/{task['task_id']}"
    description = str(task["title"]).replace("\n", " ").strip()
    keywords = {
        "coding-task-factory",
        "innodata-frontier-ai",
        task["family"],
    }
    for item in harbor_config.get("keywords", []):
        if isinstance(item, str) and item.strip():
            keywords.add(item.strip().lower())
    difficulty = harbor_config.get("difficulty", "medium")
    if difficulty not in {"easy", "medium", "hard"}:
        raise FactoryError("Harbor task difficulty must be easy, medium, or hard")
    tags = harbor_config.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise FactoryError("Harbor task tags must be a list of strings")
    lines = [
        'schema_version = "1.4"',
        "",
        "[task]",
        f"name = {_toml_string(name)}",
        f"description = {_toml_string(description)}",
        "keywords = ["
        + ", ".join(_toml_string(item) for item in sorted(keywords))
        + "]",
        "",
        "[metadata]",
        f'difficulty = "{difficulty}"',
        'category = "programming"',
        "tags = ["
        + ", ".join(_toml_string(tag) for tag in sorted(set(tags)))
        + "]",
        "",
        "[agent]",
        f"timeout_sec = {int(harbor_config.get('agent_timeout_sec', 1800))}",
        "",
        "[verifier]",
        'environment_mode = "shared"',
        f"timeout_sec = {int(harbor_config.get('verifier_timeout_sec', 600))}",
        "",
        "[environment]",
        'network_mode = "no-network"',
        "",
    ]
    return "\n".join(lines)


def _validate_source_excludes(values: object) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise FactoryError("source_excludes must be a list of relative Git pathspecs")
    excludes = []
    for value in values:
        if (
            not value
            or value.startswith("/")
            or "\\" in value
            or any(part == ".." for part in value.split("/"))
        ):
            raise FactoryError(f"unsafe source exclusion pattern: {value}")
        excludes.append(value)
    return excludes


def _archive_target_source(
    target_source: str,
    commit: str,
    destination: Path,
    source_excludes: list[str],
) -> dict:
    source_path = Path(target_source).expanduser()
    if not source_path.exists() or not source_path.is_dir():
        raise FactoryError(
            "Harbor task export requires a local target checkout so it can embed a pinned source snapshot"
        )
    root_result = subprocess.run(
        ["git", "-C", str(source_path), "rev-parse", "--show-toplevel"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if root_result.returncode != 0:
        raise FactoryError("Harbor task export requires a local Git checkout")
    root = Path(root_result.stdout.strip()).resolve()
    tree_result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", f"{commit}^{{tree}}"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if tree_result.returncode != 0:
        raise FactoryError("could not resolve the pinned target tree for Harbor export")
    submodules = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", commit],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if submodules.returncode != 0:
        raise FactoryError("could not inspect the pinned target tree")
    if any(record.startswith(b"160000 commit ") for record in submodules.stdout.split(b"\0")):
        raise FactoryError(
            "target commit contains Git submodules; package their pinned contents before Harbor export"
        )

    argv = ["git", "-C", str(root), "archive", "--format=tar", commit]
    if source_excludes:
        argv.extend(["--", ".", *[f":(exclude){pattern}" for pattern in source_excludes]])
    else:
        argv.extend(["--", "."])
    destination.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with destination.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                shutil.copyfileobj(process.stdout, compressed)
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        return_code = process.wait()
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    if return_code != 0:
        destination.unlink(missing_ok=True)
        raise FactoryError(f"could not archive pinned target source: {stderr.strip()[:1000]}")
    return {
        "archive": "environment/source.tar.gz",
        "sha256": _sha256(destination),
        "tree": tree_result.stdout.strip(),
        "commit": commit,
        "excludes": source_excludes,
    }


def _report(task: dict, status: str, validation: dict | None = None) -> str:
    test_files = task.get("tests", {}).get("files", [])
    lines = [
        f"# Run report: {task['title']}",
        "",
        f"- Task ID: `{task['task_id']}`",
        f"- Seed: `{task['seed']}`",
        f"- Seed mode: `{task.get('seed_mode', 'selected')}`",
        f"- Target repository: `{task['target']['repository']}`",
        f"- Target commit: `{task['target']['commit']}`",
        f"- Patch reference: `{(task.get('seed_reference') or {}).get('patch_identifier') or 'none'}`",
        f"- Task family: `{task['family']}`",
        f"- Task variant: `{task.get('variation', {}).get('variant', 'not annotated')}`",
        f"- Harbor validation status: **{status}**",
        "",
        "## Variation profile",
        "",
        "- Dimensions: "
        + ", ".join(task.get("variation", {}).get("dimensions", []))
        if task.get("variation")
        else "- Dimensions: not annotated",
        "- Target symbols: "
        + ", ".join(task.get("variation", {}).get("target_symbols", []))
        if task.get("variation")
        else "- Target symbols: not annotated",
        "- Semantic signature: "
        + str(task.get("variation", {}).get("signature", "not scored"))
        if task.get("variation")
        else "- Semantic signature: not scored",
        "",
        "## Task package files",
        "",
        "- `instruction.md`",
        "- `task.toml`",
        "- `environment/Dockerfile`",
        "- `environment/source.tar.gz`",
        "- `solution/solve.sh`",
        "- `solution/reference.patch`",
        "- `tests/test.sh`",
        *[f"- `{item['package_path']}`" for item in test_files],
        "- `task.json`",
        "- `manifest.json`",
        "- `run-report.md`",
        "",
        "## Native verifier and solution commands",
        "",
        f"- Native test: `{shlex.join(task.get('tests', {}).get('command', []))}`",
        f"- Test working directory: `{task.get('tests', {}).get('working_directory', '.')}`",
        f"- Harbor reward file: `{task.get('harbor', {}).get('reward_file', HARBOR_REWARD_FILE)}`",
        "- Oracle solution: `sh /solution/solve.sh`",
        "",
    ]
    validation = validation or {}
    seed_run = validation.get("seed_run", {})
    if seed_run:
        lines.extend(
            [
                "",
                "## Seed processing record",
                "",
                "- Run timestamp: recorded in the JSONL seed log",
                f"- Local validation: `{seed_run.get('local_validation_status', 'not run')}`",
                f"- Persistent log: `{seed_run.get('log_path', 'not recorded')}`",
                f"- Harbor status: `{seed_run.get('harbor_status', 'pending')}`",
            ]
        )
    local_validation = validation.get("local_preflight", validation)
    coverage = local_validation.get("coverage", {})
    baseline_coverage = coverage.get("baseline", {})
    post_coverage = coverage.get("post_patch", {})
    baseline_percent = baseline_coverage.get("total_percent")
    post_percent = post_coverage.get("total_percent")
    delta = coverage.get("delta_percentage_points")
    harbor = validation.get("harbor")
    lines.extend(
        [
            "## Local coverage comparison",
            "",
            "- Modified target files/packages: "
            + (
                ", ".join(
                    sorted(
                        set(task.get("patch_targets", []))
                        | set(task.get("patch_packages", []))
                        | set(coverage.get("target_files", []))
                        | set(coverage.get("target_packages", []))
                    )
                )
                or "not recorded"
            ),
            "- Baseline coverage: "
            + (f"{baseline_percent:.2f}%" if isinstance(baseline_percent, (int, float)) else "unavailable"),
            "- Post-patch coverage: "
            + (f"{post_percent:.2f}%" if isinstance(post_percent, (int, float)) else "unavailable"),
            "- Coverage delta: "
            + (
                f"{delta:+.2f} percentage points"
                if isinstance(delta, (int, float))
                else "unavailable"
            ),
        ]
    )
    patch_execution = coverage.get("patched_code_exercised") or {}
    patched_lines = patch_execution.get("patched_executable_lines", {})
    patched_functions = patch_execution.get("patched_functions", {})
    if patched_lines.get("total"):
        lines.append(
            "- Patched executable lines exercised: "
            f"{patched_lines.get('covered', 0)}/{patched_lines.get('total', 0)} "
            f"(all: {patched_lines.get('all_exercised')})"
        )
    if patched_functions.get("items"):
        function_items = patched_functions.get("items", [])
        exercised_count = sum(item.get("exercised") is True for item in function_items)
        lines.append(
            "- Patched functions exercised: "
            f"{exercised_count}/{len(function_items)} "
            f"(all: {patched_functions.get('all_exercised')})"
        )
    if not coverage:
        configured = bool(task.get("coverage")) or task.get("tests", {}).get(
            "command", []
        )[:2] == ["go", "test"]
        lines.append(
            "- Coverage is configured but has not been measured yet."
            if configured
            else "- Coverage is not configured for this task."
        )
    elif not baseline_coverage.get("available") or not post_coverage.get("available"):
        reasons = [
            phase.get("reason")
            for phase in (baseline_coverage, post_coverage)
            if phase.get("reason")
        ]
        lines.append(
            "- Coverage measurement status: unavailable"
            + (f" ({'; '.join(reasons)})" if reasons else "")
        )
    lines.extend(
        [
            "- Coverage is supplementary local evidence; Harbor still grades only "
            "`/logs/verifier/reward.txt`.",
            "",
        ]
    )
    if not harbor or harbor.get("status") in {None, "not_run"}:
        lines.extend(
            [
                "Harbor's `nop` and `oracle` trials have **not run**. This task is "
                "unvalidated and must not be treated as valid.",
                "",
                "Run `task-factory validate --task <task-directory>` to collect "
                "baseline-fail (`nop`) and reference-pass (`oracle`) evidence in "
                "isolated Harbor trials.",
                "",
            ]
        )
        command_templates = harbor.get("command_templates", []) if harbor else []
        if command_templates:
            lines.extend(["Planned Harbor commands (not yet executed):", ""])
            lines.extend(f"- `{shlex.join(command)}`" for command in command_templates)
            lines.append("")
    else:
        lines.extend(
            [
                f"Harbor validation result: **{harbor.get('status', 'unknown')}**",
                "",
                "## Harbor jobs and reward evidence",
                "",
            ]
        )
        for phase in ("nop", "oracle"):
            job = harbor.get("jobs", {}).get(phase, {})
            lines.append(f"- `{phase}` command: `{shlex.join(job.get('command', []))}`")
            lines.append(f"  - Executed: `{job.get('executed', False)}`")
            lines.append(f"  - Job directory: `{job.get('job_dir', 'not recorded')}`")
            lines.append(f"  - Harbor CLI exit code: `{job.get('exit_code', 'not recorded')}`")
            for trial in job.get("trials", []):
                lines.append(
                    f"  - Reward `{trial.get('reward', 'unavailable')}` "
                    f"from `{trial.get('reward_file', 'unknown')}`"
                )
        if harbor.get("message"):
            lines.extend(["", f"Validation note: {harbor['message']}"])
    if validation.get("local_preflight"):
        local = validation["local_preflight"]
        lines.extend(
            [
                "",
                "## Local preflight",
                "",
                f"- Result: `{local.get('status', 'unknown')}`",
                f"- Baseline: `{local.get('baseline', {}).get('status', 'not run')}` "
                f"(exit `{local.get('baseline', {}).get('exit_code', 'not run')}`)",
                f"- Reference: `{local.get('reference', {}).get('status', 'not run')}` "
                f"(exit `{local.get('reference', {}).get('exit_code', 'not run')}`)",
                "- Local preflight is diagnostic only; it does not substitute for "
                "Harbor `nop` and `oracle` trials.",
            ]
        )
        if local.get("commands"):
            lines.extend(["", "Executed local preflight commands:", ""])
            for item in local["commands"]:
                lines.append(f"- `{item.get('rendered', '')}`")
                lines.append(f"  - Working directory: `{item.get('cwd', 'unknown')}`")
                lines.append(f"  - Exit code: `{item.get('exit_code', 'not run')}`")
        if local.get("status") == "unsupported":
            lines.append("- Local runtime/dependency evidence was unavailable; this is not counted as a task failure.")
    if task.get("agent_runs"):
        lines.extend(["", "## Opt-in agent runs", ""])
        for run in task["agent_runs"]:
            lines.append(
                f"- `{run.get('agent', 'unknown')}` / `{run.get('model', 'unknown')}`: "
                f"{len(run.get('trials', []))} trial(s), "
                f"observed pass rate `{run.get('observed_pass_rate', 'unavailable')}`"
            )
            lines.append(f"  - Job directory: `{run.get('job_dir', 'not recorded')}`")
            lines.append(
                f"  - ATIF trajectories: {run.get('atif_recorded_trials', 0)} "
                f"of {len(run.get('trials', []))} trial(s)"
            )
    if status == "unsupported":
        lines.extend(["", "**Unsupported / unvalidated:** required Harbor evidence was not available."])
    elif status in {"not_validated", "not validated"}:
        lines.extend(["", "**Not validated yet:** Harbor has not proved both required reward outcomes."])
    elif status != "valid":
        lines.extend(["", "**Not valid:** Harbor did not prove both required reward outcomes."])
    lines.append("")
    return "\n".join(lines)


def _target_for_generation(source: str) -> Target:
    target = resolve_target(source)
    if not re.fullmatch(r"[0-9a-f]{40,64}", target.commit):
        raise FactoryError("target HEAD did not resolve to a full Git commit")
    return target


def _safe_relative_path(value: object, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FactoryError("task paths must be non-empty POSIX-style relative paths")
    if allow_dot and value == ".":
        return value
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise FactoryError(f"task path is not a safe relative path: {value}")
    if ":" in path.parts[0]:
        raise FactoryError(f"task path is not portable: {value}")
    return path.as_posix()


def _blueprint_source(root: Path, relative: object) -> Path:
    safe = _safe_relative_path(relative)
    path = (root / safe).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise FactoryError(f"blueprint file is missing or outside its directory: {safe}")
    return path


def _seed_tokens(seed: int, target: Target, task_id: str) -> dict[str, str]:
    return {
        "{{SEED}}": str(seed),
        "{{SEED_MOD_10}}": str(seed % 10),
        "{{SEED_MOD_100}}": str(seed % 100),
        "{{TARGET_COMMIT}}": target.commit,
        "{{TARGET_REPOSITORY}}": target.source,
        "{{TASK_ID}}": task_id,
    }


def _render_seed(value: str, tokens: dict[str, str]) -> str:
    rendered = value
    for token, replacement in tokens.items():
        rendered = rendered.replace(token, replacement)
    if re.search(r"\{\{[A-Z0-9_]+\}\}", rendered):
        raise FactoryError("blueprint contains an unsupported template token")
    return rendered


def _coverage_command(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(
            not isinstance(part, str)
            or not part
            or "\x00" in part
            or "\n" in part
            or "\r" in part
            for part in value
        )
    ):
        raise FactoryError(f"coverage {label} must be a non-empty argument list")
    if Path(value[0]).name.lower() in {"sh", "bash", "zsh", "cmd", "powershell"}:
        raise FactoryError(f"coverage {label} must not invoke a shell")
    for part in value:
        without_seed_tokens = re.sub(r"\{\{[A-Z0-9_]+\}\}", "", part)
        if re.search(r"\{(?!coverage_file\}|report_file\})", without_seed_tokens):
            raise FactoryError(f"coverage {label} contains an unsupported path token")
    return value


def _emit_harbor_task(
    output: Path,
    task: dict,
    instruction: str,
    patch: str,
    copied_tests: list[dict],
    target_source: str,
    dockerfile: str,
    harbor_config: dict,
) -> Path:
    source_excludes = _validate_source_excludes(harbor_config.get("source_excludes", []))
    patch_targets = sorted(set(re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)))
    if not patch_targets:
        raise FactoryError("reference patch does not identify any modified target files")
    task["patch_targets"] = patch_targets
    task["patch_packages"] = sorted(
        {
            str(Path(path).parent)
            for path in patch_targets
            if str(Path(path).parent) != "."
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".task-factory-", dir=output.parent))
    try:
        _write(stage / "instruction.md", instruction)
        _write(stage / "task.toml", _render_task_toml(task, harbor_config))
        _write(stage / "environment/Dockerfile", dockerfile)
        source_metadata = _archive_target_source(
            target_source,
            task["target"]["commit"],
            stage / "environment/source.tar.gz",
            source_excludes,
        )
        task["reference"] = {"path": "solution/reference.patch", "type": "git-patch"}
        task["harbor"] = {
            "task_name": f"innodata-frontier-ai/{task['task_id']}",
            "network_mode": "no-network",
            "reward_file": HARBOR_REWARD_FILE,
            "source_snapshot": source_metadata,
        }
        _write(stage / "solution/reference.patch", patch)
        _write_executable(stage / "solution/solve.sh", _render_solve_script())
        for item in copied_tests:
            _write(stage / item["package_path"], item["content"])
        _write_executable(
            stage / "tests/test.sh",
            render_reward_wrapper(
                task["tests"]["command"],
                task["tests"]["files"],
                task["tests"]["working_directory"],
            ),
        )
        _verify_harbor_export(stage, task)
        _write(stage / "task.json", json.dumps(task, indent=2, sort_keys=True) + "\n")

        file_hashes = {
            path.relative_to(stage).as_posix(): _sha256(path)
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        manifest = {
            "schema_version": 2,
            "task_id": task["task_id"],
            "seed": task["seed"],
            "seed_mode": task.get("seed_mode", "selected"),
            "seed_reference": task.get("seed_reference"),
            "family": task["family"],
            "variation": task.get("variation"),
            "patch_targets": task.get("patch_targets", []),
            "patch_packages": task.get("patch_packages", []),
            "target": {
                "repository": task["target"]["repository"],
                "commit": task["target"]["commit"],
                "tree": source_metadata["tree"],
            },
            "detected_languages": task.get("detected_languages", []),
            "generator_version": __version__,
            "task_status": "not_validated",
            "harbor_status": "pending",
            "files": file_hashes,
            "validation": {
                "harbor": {
                    "status": "not_run",
                    "required_rewards": {"nop": 0, "oracle": 1},
                    "command_templates": [
                        ["harbor", "run", "-p", "<task-directory>", "-a", "nop"],
                        ["harbor", "run", "-p", "<task-directory>", "-a", "oracle"],
                    ],
                    "jobs": {},
                }
            },
            "agent_runs": [],
        }
        _write(stage / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        _write(stage / "run-report.md", _report(task, "not validated", manifest["validation"]))
        if output.exists():
            output.rmdir()
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def _generate_blueprint_task(
    seed: int,
    target_source: str,
    output: Path,
    blueprint_dir: str | Path,
    target: Target,
    seed_mode: str,
    seed_reference: dict,
) -> Path:
    blueprint_root = Path(blueprint_dir).expanduser().resolve()
    try:
        blueprint = json.loads((blueprint_root / "blueprint.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FactoryError(f"could not read blueprint.json: {exc}") from exc
    if not isinstance(blueprint, dict) or blueprint.get("schema_version") != 1:
        raise FactoryError("blueprint.json must use schema_version 1")

    family = blueprint.get("family")
    if not isinstance(family, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", family):
        raise FactoryError("blueprint family must be a short lowercase identifier")
    tests = blueprint.get("tests")
    if not isinstance(tests, dict):
        raise FactoryError("blueprint must define a tests object")
    harbor_config = blueprint.get("harbor")
    if not isinstance(harbor_config, dict):
        raise FactoryError("blueprint must define Harbor Docker environment settings")
    dockerfile_source = _blueprint_source(
        blueprint_root, harbor_config.get("environment_dockerfile")
    )
    test_files = tests.get("files")
    command = tests.get("command")
    failure_patterns = tests.get("baseline_failure_patterns")
    pass_pattern = tests.get("reference_pass_pattern")
    if not isinstance(test_files, list) or not test_files:
        raise FactoryError("blueprint must provide at least one test file")
    if (
        not isinstance(command, list)
        or not command
        or any(
            not isinstance(part, str)
            or not part
            or "\x00" in part
            or "\n" in part
            or "\r" in part
            for part in command
        )
    ):
        raise FactoryError("blueprint test command must be a non-empty argument list")
    if Path(command[0]).name.lower() in {"sh", "bash", "zsh", "cmd", "powershell"}:
        raise FactoryError("blueprint test commands must not invoke a shell")
    if (
        not isinstance(failure_patterns, list)
        or not failure_patterns
        or any(not isinstance(pattern, str) or not pattern for pattern in failure_patterns)
        or not isinstance(pass_pattern, str)
        or not pass_pattern
    ):
        raise FactoryError("blueprint must define failure and reference-pass evidence patterns")
    for pattern in [*failure_patterns, pass_pattern]:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise FactoryError(f"invalid blueprint evidence pattern: {exc}") from exc

    instruction_source = _blueprint_source(blueprint_root, blueprint.get("instruction"))
    patch_source = _blueprint_source(blueprint_root, blueprint.get("reference_patch"))
    seed_label = str(seed).replace("-", "m")
    task_id = f"{family}-{seed_label}"
    tokens = _seed_tokens(seed, target, task_id)
    instruction = _render_seed(instruction_source.read_text(encoding="utf-8"), tokens)
    patch = _render_seed(patch_source.read_text(encoding="utf-8"), tokens)
    title = _render_seed(str(blueprint.get("title", family)), tokens)
    rendered_command = [_render_seed(part, tokens) for part in command]
    working_directory = _safe_relative_path(tests.get("working_directory", "."), allow_dot=True)
    coverage_configuration = blueprint.get("coverage")
    if coverage_configuration is not None:
        if not isinstance(coverage_configuration, dict):
            raise FactoryError("blueprint coverage configuration must be an object")
        coverage_format = coverage_configuration.get("format")
        if coverage_format not in {"coverage.py-json", "normalized-json"}:
            raise FactoryError(
                "coverage format must be coverage.py-json or normalized-json"
            )
        coverage_test_command = _coverage_command(
            coverage_configuration.get("test_command"),
            "test_command",
        )
        coverage_report_command = _coverage_command(
            coverage_configuration.get("report_command"),
            "report_command",
        )
        if not any("{coverage_file}" in part for part in coverage_test_command):
            raise FactoryError("coverage test_command must use {coverage_file}")
        if not any("{report_file}" in part for part in coverage_report_command):
            raise FactoryError("coverage report_command must use {report_file}")
        if not any("{coverage_file}" in part for part in coverage_report_command):
            raise FactoryError("coverage report_command must use {coverage_file}")
        coverage_configuration = {
            "kind": "custom",
            "format": coverage_format,
            "test_command": [
                _render_seed(part, tokens) for part in coverage_test_command
            ],
            "report_command": [
                _render_seed(part, tokens) for part in coverage_report_command
            ],
        }

    copied_tests = []
    for file in test_files:
        if not isinstance(file, dict):
            raise FactoryError("each blueprint test file must be an object")
        source_path = _blueprint_source(blueprint_root, file.get("source"))
        payload_relative = _safe_relative_path(file.get("package_path"))
        if payload_relative.startswith(HARBOR_TEST_PAYLOAD + "/"):
            payload_relative = payload_relative[len(HARBOR_TEST_PAYLOAD) + 1 :]
        package_path = f"{HARBOR_TEST_PAYLOAD}/{payload_relative}"
        target_path = _safe_relative_path(file.get("target_path"))
        copied_tests.append(
            {
                "package_path": package_path,
                "target_path": target_path,
                "content": _render_seed(source_path.read_text(encoding="utf-8"), tokens),
            }
        )
    package_paths = [item["package_path"] for item in copied_tests]
    target_paths = [item["target_path"] for item in copied_tests]
    if len(set(package_paths)) != len(package_paths) or len(set(target_paths)) != len(target_paths):
        raise FactoryError("blueprint test file paths must be unique")

    detected_languages = []
    local_target = Path(target_source).expanduser()
    if local_target.exists():
        detected_languages = scan_repository(str(local_target))["detected_languages"]
    task = {
        "schema_version": 2,
        "task_id": task_id,
        "family": family,
        "title": title,
        "seed": seed,
        "seed_mode": seed_mode,
        "seed_reference": seed_reference,
        "generation_mode": "language-neutral-blueprint",
        "detected_languages": detected_languages,
        "target": {"repository": target.source, "commit": target.commit},
        "tests": {
            "files": [
                {"package_path": item["package_path"], "target_path": item["target_path"]}
                for item in copied_tests
            ],
            "command": rendered_command,
            "working_directory": working_directory,
            "baseline_failure_patterns": failure_patterns,
            "reference_pass_pattern": pass_pattern,
        },
    }
    if coverage_configuration is not None:
        task["coverage"] = coverage_configuration
    dockerfile = _render_seed(dockerfile_source.read_text(encoding="utf-8"), tokens)
    return _emit_harbor_task(
        output,
        task,
        instruction,
        patch,
        copied_tests,
        target_source,
        dockerfile,
        harbor_config,
    )


def generate_task(
    seed: int,
    target_source: str,
    output_dir: str | Path,
    blueprint_dir: str | Path | None = None,
    *,
    seed_mode: str = "selected",
    seed_reference: dict | None = None,
    target_commit: str | None = None,
) -> Path:
    if seed_mode not in {"auto", "selected"}:
        raise FactoryError("seed_mode must be 'auto' or 'selected'")
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FactoryError(f"output directory must be empty or absent: {output}")

    target = _target_for_generation(target_source)
    if target_commit is not None and target.commit != target_commit:
        raise FactoryError(
            "target commit changed before task generation; inspect the target again"
        )
    resolved_seed_reference = seed_reference or {
        "commit_sha": target.commit,
        "patch_identifier": None,
        "patch_source": None,
        "source_key": target.commit,
    }
    if blueprint_dir is not None:
        return _generate_blueprint_task(
            seed,
            target_source,
            output,
            blueprint_dir,
            target,
            seed_mode,
            resolved_seed_reference,
        )

    target_path = Path(target_source).expanduser()
    if not target_path.exists():
        raise FactoryError("built-in task recipes require a local target checkout; use --blueprint for other repositories")
    scan = scan_repository(str(target_path))
    if "fraudguard-go" not in scan["generation_capabilities"]["bundled_seeded_templates"]:
        raise FactoryError(
            "no bundled seeded recipe matches this repository; use --blueprint with its native tests"
        )
    spec = build_spec(seed)
    seed_label = str(seed).replace("-", "m")
    task_id = f"{spec.family}-{seed_label}"
    package_test_path = f"{HARBOR_TEST_PAYLOAD}/{TASK_TEST_PATH}"
    harbor_config = {
        "difficulty": "medium",
        "keywords": ["fraudguard", "bifrost", "go"],
        "source_excludes": ["release-assets/**", ".conversation/**", ".agents/**"],
    }
    task = {
        "schema_version": 2,
        "task_id": task_id,
        "seed": seed,
        "seed_mode": seed_mode,
        "seed_reference": resolved_seed_reference,
        "family": spec.family,
        "title": spec.title,
        "scenario": spec.scenario,
        "variation": variation_profile(spec),
        "generation_mode": "bundled-seeded-recipe",
        "detected_languages": scan["detected_languages"],
        "target": {"repository": target.source, "commit": target.commit},
        "tests": {
            "files": [
                {"package_path": package_test_path, "target_path": TASK_TEST_PATH}
            ],
            "working_directory": "plugins/fraudguard",
            "command": [
                "go",
                "test",
                "-count=1",
                "-run",
                "^(" + "|".join(re.escape(name) for name in spec.expected_failures) + ")$",
                ".",
            ],
            "expected_baseline_failures": list(spec.expected_failures),
            "baseline_failure_patterns": [
                rf"(?m)^--- FAIL: {re.escape(name)}(?:\s|$)"
                for name in spec.expected_failures
            ],
            "reference_pass_pattern": r"(?m)^ok\s+\S+\s+[0-9.]+s$",
        },
        "coverage": {"kind": "go"},
    }
    copied_tests = [
        {
            "package_path": package_test_path,
            "target_path": TASK_TEST_PATH,
            "content": spec.test_source,
        }
    ]
    return _emit_harbor_task(
        output,
        task,
        _instruction(task, spec),
        spec.patch,
        copied_tests,
        target_source,
        _render_go_dockerfile(),
        harbor_config,
    )


def _instruction(task: dict, spec) -> str:
    return f"""# {spec.title}

## Context

This is a feature-development task for the FraudGuard/Bifrost Plugin repository.
Target commit: `{task['target']['commit']}`. Generated scenario: {spec.scenario}.

## Requirements

{spec.requirements}

## Acceptance criteria

1. Implement the behavior in the existing FraudGuard Go module without changing
   unrelated behavior.
2. Keep errors stable and avoid including configuration values or identifiers
   in error text.
3. The generated test in `plugins/fraudguard/task_factory_generated_test.go`
   passes, and the existing package tests continue to compile.
4. Preserve the module's existing public APIs unless the requirement above
   makes a private helper necessary.

## Validation

Harbor's `nop` trial must leave the verifier reward at 0, and its `oracle` trial
must apply `solution/solve.sh` and produce reward 1. Run both with the factory's
`validate` command. A generated task is not valid until these Harbor trials have
actually run and produced the required rewards. Do not edit the target repository.
"""
