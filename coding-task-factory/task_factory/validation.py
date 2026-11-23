import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .factory import _report
from .coverage import (
    analyze_go_patch_coverage,
    changed_lines_from_patch,
    coverage_delta,
    parse_custom_coverage_report,
    summarize_go_coverage,
)
from .models import TASK_TEST_PATH


class ValidationError(RuntimeError):
    pass


class UnsupportedValidationError(ValidationError):
    pass


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|password|secret|authorization)\b\s*[:=]\s*)[^\s,;]+"
)
_URL_CREDENTIALS = re.compile(r"(https?://)[^/\s:@]+:[^@\s/]+@")
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_COMMON_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)
_TEST_NAME = re.compile(r"^Test[A-Za-z0-9_]+$")
_ENVIRONMENT_FAILURE = re.compile(
    r"(?i)(no module named|module not found|cannot find module|ERR_MODULE_NOT_FOUND|"
    r"command not found|not recognized as a command|no such file or directory|"
    r"could not find (?:the )?(?:package|module|crate|dependency)|"
    r"no matching package named|failed to download|module lookup disabled|"
    r"GOPROXY=off|go\.mod requires go|toolchain not available|"
    r"dependency(?:ies)? .*not found|"
    r"could not resolve|failed to resolve|compilation failed|build failed|undefined:)"
)
_OUTPUT_LIMIT = 16_000


def _clean_text(value: str) -> str:
    text = _URL_CREDENTIALS.sub(r"\1<redacted>@", value)
    text = _BEARER_TOKEN.sub("Bearer <redacted>", text)
    text = _COMMON_TOKEN.sub("<redacted-token>", text)
    text = _PRIVATE_KEY.sub("<redacted-private-key>", text)
    text = _SECRET_ASSIGNMENT.sub(r"\1<redacted>", text)
    if len(text) > _OUTPUT_LIMIT:
        text = text[:_OUTPUT_LIMIT] + "\n[output truncated]"
    return text


def _safe_environment() -> dict[str, str]:
    host_home = Path(os.environ.get("HOME", "/tmp"))
    go_path = os.environ.get("GOPATH", str(host_home / "go")).split(os.pathsep)[0]
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", str(host_home / ".cache")))
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GOENV": "off",
        "GOWORK": "off",
        "GOTOOLCHAIN": "auto",
        "GOPROXY": "off",
        "GOSUMDB": "sum.golang.org",
        "GOFLAGS": "-mod=readonly",
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "CARGO_NET_OFFLINE": "true",
        "npm_config_offline": "true",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_userconfig": os.devnull,
        "npm_config_globalconfig": os.devnull,
        "YARN_ENABLE_NETWORK": "0",
        "PYTHONNOUSERSITE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    cache_candidates = {
        "GOCACHE": os.environ.get("GOCACHE", str(cache_root / "go-build")),
        "GOMODCACHE": os.environ.get("GOMODCACHE", str(Path(go_path) / "pkg" / "mod")),
        "CARGO_HOME": os.environ.get("CARGO_HOME", str(host_home / ".cargo")),
        "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(host_home / ".rustup")),
        "npm_config_cache": os.environ.get("npm_config_cache", str(host_home / ".npm")),
        "YARN_CACHE_FOLDER": os.environ.get(
            "YARN_CACHE_FOLDER",
            str(cache_root / "yarn"),
        ),
    }
    for key, value in cache_candidates.items():
        if os.environ.get(key) or Path(value).exists():
            env[key] = value
    return env


def _command_record(argv: list[str], cwd: Path, env_keys: dict[str, str]) -> dict:
    return {
        "argv": argv,
        "rendered": shlex.join(argv),
        "cwd": str(cwd),
        "environment": env_keys,
        "exit_code": None,
        "duration_seconds": None,
    }


def _run(
    argv: list[str],
    cwd: Path,
    commands: list[dict],
    *,
    timeout: int = 180,
    env: dict[str, str] | None = None,
) -> dict:
    effective_env = env if env is not None else _safe_environment()
    recorded_env = {
        key: effective_env[key]
        for key in (
            "GOPROXY",
            "GOSUMDB",
            "GOTOOLCHAIN",
            "GOFLAGS",
            "PIP_NO_INDEX",
            "PIP_DISABLE_PIP_VERSION_CHECK",
            "CARGO_NET_OFFLINE",
            "npm_config_offline",
            "npm_config_audit",
            "npm_config_fund",
            "npm_config_userconfig",
            "npm_config_globalconfig",
            "YARN_ENABLE_NETWORK",
            "PYTHONNOUSERSITE",
            "GOCACHE",
            "GOMODCACHE",
            "CARGO_HOME",
            "RUSTUP_HOME",
            "npm_config_cache",
            "YARN_CACHE_FOLDER",
        )
        if key in effective_env
    }
    record = _command_record(argv, cwd, recorded_env)
    commands.append(record)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=effective_env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        record["exit_code"] = completed.returncode
        record["output"] = _clean_text(completed.stdout or "")
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or ""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        record["output"] = _clean_text(raw)
        record["timed_out"] = True
    except OSError as exc:
        record["exit_code"] = 127
        record["output"] = _clean_text(str(exc))
    finally:
        record["duration_seconds"] = round(time.monotonic() - started, 3)
    return record


def _command_available(command: list[str], cwd: Path) -> bool:
    executable = command[0]
    if executable.startswith("./") or os.path.isabs(executable):
        candidate = Path(executable)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return shutil.which(executable, path=_safe_environment().get("PATH")) is not None


def _looks_like_environment_failure(output: str, exit_code: int | None) -> bool:
    return exit_code == 127 or bool(_ENVIRONMENT_FAILURE.search(output))


def _coverage_environment_reason(output: str) -> str:
    cleaned = _clean_text(output)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    relevant = next(
        (line for line in lines if _ENVIRONMENT_FAILURE.search(line)),
        lines[0] if lines else "native test command could not start",
    )
    return "native test environment unavailable: " + relevant[:300]


def _load_task(task_dir: Path) -> tuple[dict, dict]:
    try:
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        manifest = json.loads((task_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"could not read task package: {exc}") from exc
    if task.get("schema_version") != 2 or manifest.get("schema_version") != 2:
        raise ValidationError("unsupported task package schema")
    return task, manifest


def _verify_task_files(task_dir: Path, manifest: dict) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValidationError("task manifest is missing generated file checksums")
    for relative, expected in files.items():
        candidate = (task_dir / relative).resolve()
        if task_dir.resolve() not in candidate.parents:
            raise ValidationError("task manifest contains a path outside the task package")
        if not candidate.is_file():
            raise ValidationError(f"task file is missing: {relative}")
        import hashlib

        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != expected:
            raise ValidationError(f"task file checksum mismatch: {relative}")


def _safe_repo_relative(value: object, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValidationError("task paths must be non-empty POSIX-style relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        if allow_dot and value == ".":
            return value
        raise ValidationError("task path escapes the isolated repository")
    return path.as_posix()


def _test_configuration(task: dict) -> tuple[list[dict], list[str], str, str, list[str]]:
    tests = task.get("tests")
    if not isinstance(tests, dict):
        raise ValidationError("task.json is missing its tests configuration")

    files = tests.get("files")
    legacy_go_task = not files and isinstance(tests.get("path"), str)
    if legacy_go_task:
        files = [{"package_path": tests["path"], "target_path": tests["path"]}]
    if not isinstance(files, list) or not files:
        raise ValidationError("task must include at least one test file mapping")
    validated_files = []
    for item in files:
        if not isinstance(item, dict):
            raise ValidationError("each test file mapping must be an object")
        validated_files.append(
            {
                "package_path": _safe_repo_relative(item.get("package_path")),
                "target_path": _safe_repo_relative(item.get("target_path")),
            }
        )
    if len({item["target_path"] for item in validated_files}) != len(validated_files):
        raise ValidationError("test file destination paths must be unique")

    command = tests.get("command")
    if legacy_go_task and not command:
        expected = tests.get("expected_baseline_failures", [])
        if not isinstance(expected, list) or not expected or any(
            not isinstance(name, str) or not _TEST_NAME.fullmatch(name) for name in expected
        ):
            raise ValidationError("legacy Go task has invalid expected test names")
        command = [
            "go",
            "test",
            "-count=1",
            "-run",
            "^(" + "|".join(re.escape(name) for name in expected) + ")$",
            ".",
        ]
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) or not part or "\x00" in part for part in command)
    ):
        raise ValidationError("task test command must be a non-empty argument list")
    if Path(command[0]).name.lower() in {"sh", "bash", "zsh", "cmd", "powershell"}:
        raise ValidationError("task test commands must not invoke a shell")

    working_directory = _safe_repo_relative(
        tests.get("working_directory", "."),
        allow_dot=True,
    )
    failure_patterns = tests.get("baseline_failure_patterns")
    if legacy_go_task and not failure_patterns:
        failure_patterns = [
            rf"(?m)^--- FAIL: {re.escape(name)}(?:\s|$)"
            for name in tests["expected_baseline_failures"]
        ]
    if (
        not isinstance(failure_patterns, list)
        or not failure_patterns
        or any(not isinstance(pattern, str) or not pattern for pattern in failure_patterns)
    ):
        raise ValidationError("task must declare baseline failure evidence patterns")
    pass_pattern = tests.get("reference_pass_pattern")
    if legacy_go_task and not pass_pattern:
        pass_pattern = r"(?m)^ok\s+\S+\s+[0-9.]+s$"
    if not isinstance(pass_pattern, str) or not pass_pattern:
        raise ValidationError("task must declare a reference-pass evidence pattern")
    for pattern in [*failure_patterns, pass_pattern]:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValidationError(f"task has an invalid test evidence pattern: {exc}") from exc
    return validated_files, command, working_directory, pass_pattern, failure_patterns


def _coverage_configuration(task: dict, native_command: list[str]) -> tuple[dict | None, str | None]:
    configured = task.get("coverage")
    if configured is None and native_command[:2] == ["go", "test"]:
        configured = {"kind": "go"}
    if not isinstance(configured, dict):
        return None, "no native coverage command detected or configured"
    kind = configured.get("kind")
    if kind == "go":
        if native_command[:2] != ["go", "test"]:
            return None, "Go coverage requires a native go test command"
        return configured, None
    if kind == "custom":
        if (
            configured.get("format") not in {"coverage.py-json", "normalized-json"}
            or not isinstance(configured.get("test_command"), list)
            or not isinstance(configured.get("report_command"), list)
        ):
            return None, "custom coverage configuration is incomplete"
        return configured, None
    return None, "unsupported coverage configuration"


def _coverage_command(
    config: dict,
    native_command: list[str],
    checkout: Path,
    phase: str,
) -> tuple[list[str], Path, Path]:
    coverage_dir = checkout / ".task-factory-coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)
    profile = coverage_dir / f"{phase}.profile"
    report = coverage_dir / f"{phase}.json"
    if config["kind"] == "go":
        return (
            [*native_command[:2], f"-coverprofile={profile}", *native_command[2:]],
            profile,
            report,
        )

    def render(parts: list[str]) -> list[str]:
        return [
            part.replace("{coverage_file}", str(profile)).replace(
                "{report_file}", str(report)
            )
            for part in parts
        ]

    return render(config["test_command"]), profile, report


def _collect_coverage(
    config: dict | None,
    error: str | None,
    profile: Path,
    report_file: Path,
    patch_text: str,
    checkout: Path,
    working_directory: Path,
    commands: list[dict],
    timeout: int,
    env: dict[str, str],
) -> dict:
    if config is None:
        return {"available": False, "reason": error or "coverage unavailable"}
    if not profile.is_file():
        return {
            "available": False,
            "kind": config["kind"],
            "reason": "coverage profile was not produced by the test command",
        }
    if config["kind"] == "go":
        profile_text = profile.read_text(encoding="utf-8", errors="replace")
        report_command = ["go", "tool", "cover", f"-func={profile}"]
        summary_record = _run(
            report_command,
            working_directory,
            commands,
            timeout=timeout,
            env=env,
        )
        if summary_record.get("exit_code") != 0:
            return {
                "available": False,
                "kind": "go",
                "reason": "go tool cover could not summarize the profile",
            }
        summary = summarize_go_coverage(profile_text, summary_record.get("output", ""))
        if summary["available"]:
            summary["patch_execution"] = analyze_go_patch_coverage(
                patch_text,
                profile_text,
                summary_record.get("output", ""),
                checkout,
            )
        return summary

    report_command = [
        part.replace("{coverage_file}", str(profile)).replace(
            "{report_file}", str(report_file)
        )
        for part in config["report_command"]
    ]
    report_record = _run(
        report_command,
        working_directory,
        commands,
        timeout=timeout,
        env=env,
    )
    if report_record.get("exit_code") != 0:
        return {
            "available": False,
            "kind": config["format"],
            "reason": "configured coverage report command failed",
        }
    output = (
        report_file.read_text(encoding="utf-8", errors="replace")
        if report_file.is_file()
        else report_record.get("output", "")
    )
    return parse_custom_coverage_report(
        output,
        config["format"],
        patch_text,
        checkout,
    )


def _pattern_matches(output: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, output)]


def _test_pattern(expected_failures: list[str]) -> str:
    if not expected_failures or any(not _TEST_NAME.fullmatch(name) for name in expected_failures):
        raise ValidationError("task has invalid expected test names")
    return "^(" + "|".join(re.escape(name) for name in expected_failures) + ")$"


def _expected_failures_seen(output: str, expected: list[str]) -> list[str]:
    failed_names = set(re.findall(r"^--- FAIL: (Test[A-Za-z0-9_]+)", output, re.MULTILINE))
    return [name for name in expected if name in failed_names]


def _save_result(task_dir: Path, task: dict, manifest: dict, validation: dict, status: str) -> None:
    validation_state = manifest.get("validation") or {}
    validation_state["local_preflight"] = validation
    if validation_state.get("harbor", {}).get("status") != "valid":
        manifest["task_status"] = "not_validated"
    manifest["validation"] = validation_state
    (task_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (task_dir / "run-report.md").write_text(
        _report(
            task,
            manifest["task_status"],
            {**validation_state, "seed_run": manifest.get("seed_run", {})},
        ),
        encoding="utf-8",
    )


def _extract_source_snapshot(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise ValidationError(f"could not open embedded source snapshot: {exc}") from exc
    with archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                raise ValidationError("source snapshot contains an unsafe path")
            output = (root / Path(*relative.parts)).resolve()
            if root not in output.parents and output != root:
                raise ValidationError("source snapshot path escapes its temporary checkout")
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            if member.isfile():
                source = archive.extractfile(member)
                if source is None:
                    raise ValidationError("source snapshot contains an unreadable file")
                with source, output.open("wb") as target:
                    shutil.copyfileobj(source, target)
                output.chmod(stat.S_IMODE(member.mode) & 0o777)
                continue
            if member.issym():
                link_target = (output.parent / member.linkname).resolve()
                if root not in link_target.parents and link_target != root:
                    raise ValidationError("source snapshot contains an unsafe symbolic link")
                output.symlink_to(member.linkname)
                continue
            if member.islnk():
                link_relative = PurePosixPath(member.linkname)
                if link_relative.is_absolute() or any(
                    part in {"", ".", ".."} for part in link_relative.parts
                ):
                    raise ValidationError("source snapshot contains an unsafe hard link")
                source = (root / Path(*link_relative.parts)).resolve()
                if root not in source.parents or not source.is_file():
                    raise ValidationError("source snapshot hard link target is missing")
                os.link(source, output)
                continue
            raise ValidationError("source snapshot contains an unsupported file type")


def validate_task(
    task_dir: str | Path,
    target_source: str | None = None,
    *,
    timeout: int = 180,
) -> dict:
    package = Path(task_dir).expanduser().resolve()
    task, manifest = _load_task(package)
    validation = {
        "status": "not_run",
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "isolation": "embedded pinned source snapshot extracted to a fresh temporary checkout",
        "network_policy": {
            "factory_model_or_api_calls": "none",
            "common_package_manager_offline_flags": "enabled",
            "host_network_isolation": "not enforced for local preflight; Harbor task uses no-network runtime",
            "host_filesystem_isolation": "task tests run in a temporary checkout",
            "caller_credentials_passed_to_commands": False,
        },
        "baseline": {"status": "not_run"},
        "reference": {"status": "not_run"},
        "commands": [],
    }
    status = "not_validated"
    try:
        _verify_task_files(package, manifest)
        reference_path = task.get("reference", {}).get("path")
        if reference_path != "solution/reference.patch":
            raise ValidationError("task reference patch path is unsupported")
        test_files, test_command, test_working_directory, pass_pattern, failure_patterns = (
            _test_configuration(task)
        )
        coverage_config, coverage_error = _coverage_configuration(task, test_command)
        patch_text = (package / reference_path).read_text(encoding="utf-8")
        changed_files = changed_lines_from_patch(patch_text)
        validation["coverage"] = {
            "status": "pending",
            "kind": (
                coverage_config.get("kind")
                if coverage_config
                else ("go" if test_command[:2] == ["go", "test"] else "unavailable")
            ),
            "target_files": sorted(changed_files),
            "target_packages": sorted(
                {
                    str(Path(path).parent)
                    for path in changed_files
                    if str(Path(path).parent) != "."
                }
            ),
            "baseline": {"available": False, "reason": coverage_error},
            "post_patch": {"available": False, "reason": coverage_error},
            "delta_percentage_points": None,
            "patched_code_exercised": None,
        }

        commit = task["target"]["commit"]
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise ValidationError("task target commit is not a full Git object ID")
        validation["target_commit"] = commit
        snapshot = task.get("harbor", {}).get("source_snapshot", {})
        if snapshot.get("commit") != commit:
            raise ValidationError("embedded source snapshot does not match the recorded target commit")
        archive_relative = _safe_repo_relative(snapshot.get("archive"))
        archive_path = (package / archive_relative).resolve()
        if package.resolve() not in archive_path.parents or not archive_path.is_file():
            raise ValidationError("embedded source snapshot archive is missing")
        validation["source_snapshot"] = {
            "commit": commit,
            "tree": snapshot.get("tree"),
            "sha256": snapshot.get("sha256"),
        }

        with tempfile.TemporaryDirectory(prefix="coding-task-validation-") as tmp:
            checkout = Path(tmp) / "checkout"
            _extract_source_snapshot(archive_path, checkout)
            git_env = _safe_environment()
            commands = validation["commands"]
            for item in test_files:
                package_test = (package / item["package_path"]).resolve()
                if package.resolve() not in package_test.parents or not package_test.is_file():
                    raise ValidationError(
                        f"generated test file is missing or outside the task package: {item['package_path']}"
                    )
                target_test = (checkout / item["target_path"]).resolve()
                if checkout.resolve() not in target_test.parents:
                    raise ValidationError("generated test destination escapes the isolated checkout")
                if target_test.exists():
                    raise ValidationError(
                        f"generated test destination already exists in target: {item['target_path']}"
                    )
                target_test.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(package_test, target_test)
            working_directory = (checkout / test_working_directory).resolve()
            if checkout.resolve() not in working_directory.parents and working_directory != checkout.resolve():
                raise ValidationError("test working directory escapes the isolated checkout")
            if not working_directory.is_dir():
                raise ValidationError("task test working directory does not exist in the target")
            if not _command_available(test_command, working_directory):
                validation["baseline"]["status"] = "unsupported_test_command"
                raise UnsupportedValidationError(
                    f"test command executable is unavailable: {test_command[0]}"
                )
            test_home = checkout / ".task-factory-home"
            test_home.mkdir()
            test_env = _safe_environment()
            test_env["HOME"] = str(test_home)

            if coverage_config:
                baseline_command, baseline_profile, baseline_report = _coverage_command(
                    coverage_config, test_command, checkout, "baseline"
                )
            else:
                baseline_command = test_command
                baseline_profile = checkout / ".task-factory-coverage/baseline.profile"
                baseline_report = checkout / ".task-factory-coverage/baseline.json"
            baseline = _run(
                baseline_command,
                working_directory,
                commands,
                timeout=timeout,
                env=test_env,
            )
            try:
                baseline_coverage = _collect_coverage(
                    coverage_config,
                    coverage_error,
                    baseline_profile,
                    baseline_report,
                    patch_text,
                    checkout,
                    working_directory,
                    commands,
                    timeout,
                    test_env,
                )
            except (OSError, ValueError, TypeError) as exc:
                baseline_coverage = {
                    "available": False,
                    "reason": _clean_text(f"coverage collection failed: {exc}"),
                }
            if (
                not baseline_coverage.get("available")
                and _looks_like_environment_failure(
                    baseline.get("output", ""),
                    baseline.get("exit_code"),
                )
            ):
                baseline_coverage["reason"] = _coverage_environment_reason(
                    baseline.get("output", "")
                )
            validation["coverage"]["baseline"] = baseline_coverage
            observed_failures = _pattern_matches(baseline.get("output", ""), failure_patterns)
            validation["baseline"] = {
                "status": "failed_as_expected",
                "exit_code": baseline.get("exit_code"),
                "expected_failure_patterns": failure_patterns,
                "observed_failure_patterns": observed_failures,
                "output": baseline.get("output", ""),
            }
            baseline_ok = (
                baseline.get("exit_code") not in (None, 0)
                and len(observed_failures) == len(failure_patterns)
            )
            if not baseline_ok:
                if _looks_like_environment_failure(
                    baseline.get("output", ""),
                    baseline.get("exit_code"),
                ):
                    validation["baseline"]["status"] = "unsupported_environment"
                    raise UnsupportedValidationError(
                        "test command could not run because the language runtime or dependencies are unavailable"
                    )
                validation["baseline"]["status"] = "did_not_fail_as_expected"
                raise ValidationError(
                    "baseline did not fail with every declared test-evidence pattern"
                )

            patch_check = _run(
                ["git", "-C", str(checkout), "apply", "--check", str(package / reference_path)],
                package,
                commands,
                timeout=timeout,
                env=git_env,
            )
            if patch_check.get("exit_code") != 0:
                raise ValidationError("reference patch does not apply cleanly to the pinned baseline")
            solution_script = (package / "solution/solve.sh").resolve()
            if package.resolve() not in solution_script.parents or not solution_script.is_file():
                raise ValidationError("reference solution script is missing or outside the task package")
            solve_env = git_env.copy()
            solve_env["TASK_PROJECT_ROOT"] = str(checkout)
            solve_env["TASK_SOLUTION_PATCH"] = str(package / reference_path)
            apply_patch = _run(
                [str(solution_script)],
                package,
                commands,
                timeout=timeout,
                env=solve_env,
            )
            if apply_patch.get("exit_code") != 0:
                raise ValidationError("solution/solve.sh could not apply the reference patch in the isolated checkout")

            if coverage_config:
                reference_command, reference_profile, reference_report = _coverage_command(
                    coverage_config, test_command, checkout, "post-patch"
                )
            else:
                reference_command = test_command
                reference_profile = checkout / ".task-factory-coverage/post-patch.profile"
                reference_report = checkout / ".task-factory-coverage/post-patch.json"
            reference = _run(
                reference_command,
                working_directory,
                commands,
                timeout=timeout,
                env=test_env,
            )
            try:
                post_coverage = _collect_coverage(
                    coverage_config,
                    coverage_error,
                    reference_profile,
                    reference_report,
                    patch_text,
                    checkout,
                    working_directory,
                    commands,
                    timeout,
                    test_env,
                )
            except (OSError, ValueError, TypeError) as exc:
                post_coverage = {
                    "available": False,
                    "reason": _clean_text(f"coverage collection failed: {exc}"),
                }
            if (
                not post_coverage.get("available")
                and _looks_like_environment_failure(
                    reference.get("output", ""),
                    reference.get("exit_code"),
                )
            ):
                post_coverage["reason"] = _coverage_environment_reason(
                    reference.get("output", "")
                )
            validation["coverage"]["post_patch"] = post_coverage
            validation["coverage"]["delta_percentage_points"] = coverage_delta(
                baseline_coverage.get("total_percent"),
                post_coverage.get("total_percent"),
            )
            execution = post_coverage.get("patch_execution")
            if execution is None and post_coverage.get("patched_executable_lines"):
                execution = {
                    "patched_executable_lines": post_coverage["patched_executable_lines"],
                    "patched_functions": post_coverage.get("patched_functions"),
                }
            validation["coverage"]["patched_code_exercised"] = execution
            validation["coverage"]["status"] = (
                "measured"
                if baseline_coverage.get("available")
                and post_coverage.get("available")
                else "unavailable"
            )
            pass_output = reference.get("output", "")
            if coverage_config and coverage_config.get("kind") == "go":
                pass_output = re.sub(
                    r"(?m)(^ok\s+\S+\s+[0-9.]+s)\s+coverage: [0-9.]+% of statements$",
                    r"\1",
                    pass_output,
                )
            pass_evidence = bool(re.search(pass_pattern, pass_output))
            validation["reference"] = {
                "status": (
                    "passed"
                    if reference.get("exit_code") == 0 and pass_evidence
                    else "failed"
                ),
                "exit_code": reference.get("exit_code"),
                "pass_pattern": pass_pattern,
                "pass_evidence_seen": pass_evidence,
                "output": reference.get("output", ""),
            }
            if reference.get("exit_code") != 0 or not pass_evidence:
                if _looks_like_environment_failure(
                    reference.get("output", ""),
                    reference.get("exit_code"),
                ):
                    validation["reference"]["status"] = "unsupported_environment"
                    raise UnsupportedValidationError(
                        "reference test run could not complete because the language runtime or dependencies are unavailable"
                    )
                if reference.get("exit_code") == 0 and not pass_evidence:
                    validation["reference"]["status"] = "unsupported_evidence_contract"
                    raise UnsupportedValidationError(
                        "reference command passed but emitted no declared success evidence"
                    )
                raise ValidationError(
                    "reference run did not pass and match its declared success evidence"
                )

        validation["status"] = "passed"
        validation["reference"]["patch_applied_by"] = "solution/solve.sh"
        status = "passed"
    except UnsupportedValidationError as exc:
        validation["status"] = "unsupported"
        validation["error"] = _clean_text(str(exc))
        if validation.get("coverage", {}).get("status") == "pending":
            validation["coverage"]["status"] = "unsupported"
        status = "unsupported"
    except (ValidationError, OSError, KeyError, TypeError) as exc:
        validation["status"] = "invalid"
        validation["error"] = _clean_text(str(exc))
        if validation.get("coverage", {}).get("status") == "pending":
            validation["coverage"]["status"] = "unavailable"
        if validation["baseline"]["status"] == "not_run":
            validation["baseline"]["status"] = "not_run"
        if validation["reference"]["status"] == "not_run":
            validation["reference"]["status"] = "not_run"
    _save_result(package, task, manifest, validation, status)
    return validation
