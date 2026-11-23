import re
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from .models import Target


class TargetError(ValueError):
    pass


def _run_git(args: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": os.environ.get("HOME", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if completed.returncode:
        message = completed.stderr.strip() or "git command failed"
        raise TargetError(message[:1000])
    return completed.stdout.strip()


def validate_source(source: str) -> str:
    candidate = Path(source).expanduser()
    if candidate.exists():
        if not candidate.is_dir():
            raise TargetError("target path must be a Git repository directory")
        return str(candidate.resolve())

    if source.startswith("git@"):
        if re.search(r"[\s?#]", source):
            raise TargetError("SSH repository URLs must not contain query or fragment data")
        return source

    parsed = urlsplit(source)
    if parsed.scheme not in {"https", "http", "ssh"} or not parsed.netloc:
        raise TargetError("target must be a local Git checkout or an HTTP(S)/SSH repository URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise TargetError("repository URLs must not embed credentials, query strings, or fragments")
    return source


def resolve_target(source: str) -> Target:
    safe_source = validate_source(source)
    candidate = Path(safe_source).expanduser()
    if candidate.exists():
        root = Path(_run_git(["rev-parse", "--show-toplevel"], cwd=candidate))
        commit = _run_git(["rev-parse", "HEAD"], cwd=root)
        try:
            origin = _run_git(["remote", "get-url", "origin"], cwd=root)
            origin = validate_source(origin)
        except TargetError:
            origin = str(root)
        return Target(source=origin, commit=commit)

    output = _run_git(["ls-remote", "--symref", safe_source, "HEAD"])
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "HEAD" and re.fullmatch(r"[0-9a-fA-F]{40,64}", fields[0]):
            return Target(source=safe_source, commit=fields[0].lower())
    raise TargetError("could not resolve a commit for the target repository's HEAD")
