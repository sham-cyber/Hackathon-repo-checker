import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from .targets import TargetError, resolve_target


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "target",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".next",
    ".tox",
    ".mypy_cache",
}
LANGUAGE_BY_SUFFIX = {
    ".go": "Go",
    ".py": "Python",
    ".pyi": "Python",
    ".pyx": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".sc": "Scala",
    ".c": "C",
    ".h": "C/C++",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hh": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".fs": "F#",
    ".fsx": "F#",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".lua": "Lua",
    ".pl": "Perl",
    ".pm": "Perl",
    ".r": "R",
    ".R": "R",
    ".jl": "Julia",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hrl": "Erlang",
    ".hs": "Haskell",
    ".lhs": "Haskell",
    ".clj": "Clojure",
    ".cljs": "ClojureScript",
    ".cljc": "Clojure",
    ".dart": "Dart",
    ".groovy": "Groovy",
    ".gradle": "Groovy",
    ".ml": "OCaml",
    ".mli": "OCaml",
    ".hx": "Haxe",
    ".elm": "Elm",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".astro": "Astro",
    ".sql": "SQL",
    ".sol": "Solidity",
    ".zig": "Zig",
    ".nim": "Nim",
    ".v": "Verilog",
    ".sv": "SystemVerilog",
    ".vhd": "VHDL",
    ".vhdl": "VHDL",
    ".f": "Fortran",
    ".for": "Fortran",
    ".f90": "Fortran",
    ".f95": "Fortran",
    ".f03": "Fortran",
    ".asm": "Assembly",
    ".s": "Assembly",
    ".rkt": "Racket",
    ".lisp": "Common Lisp",
    ".cl": "Common Lisp",
    ".cr": "Crystal",
    ".d": "D",
}
MAX_SCANNED_FILES = 100_000


class ScanError(ValueError):
    pass


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
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
        raise ScanError(completed.stderr.strip() or "could not inspect Git checkout")
    return completed.stdout.strip()


def _repo_files(root: Path) -> tuple[list[Path], bool]:
    files: list[Path] = []
    truncated = False
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        for name in sorted(names):
            files.append(Path(current) / name)
            if len(files) >= MAX_SCANNED_FILES:
                truncated = True
                return files, truncated
    return files, truncated


def _command_candidate(
    language: str,
    directory: Path,
    command: list[str],
    reason: str,
    root: Path,
) -> dict:
    executable = command[0]
    if executable.startswith("./") or os.path.isabs(executable):
        candidate = Path(executable)
        if not candidate.is_absolute():
            candidate = root / directory / candidate
        available = candidate.is_file() and os.access(candidate, os.X_OK)
    else:
        available = shutil.which(executable) is not None
    return {
        "language": language,
        "working_directory": directory.as_posix() or ".",
        "command": command,
        "command_available": available,
        "reason": reason,
    }


def _manifest_test_commands(root: Path, files: list[Path]) -> list[dict]:
    commands: list[dict] = []
    manifests = {path.relative_to(root).as_posix(): path for path in files}
    for relative, path in sorted(manifests.items()):
        directory = Path(relative).parent
        cwd = "." if str(directory) == "." else directory.as_posix()
        if path.name == "go.mod":
            commands.append(
                _command_candidate(
                    "Go",
                    directory,
                    ["go", "test", "./..."],
                    "Go module manifest",
                    root,
                )
            )
        elif path.name in {"pyproject.toml", "setup.cfg", "setup.py"}:
            commands.append(
                _command_candidate(
                    "Python",
                    directory,
                    ["python3", "-m", "unittest", "discover"],
                    "Python project manifest",
                    root,
                )
            )
        elif path.name == "package.json":
            try:
                package = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                package = {}
            scripts = package.get("scripts") if isinstance(package, dict) else None
            if isinstance(scripts, dict) and scripts.get("test"):
                parent = path.parent
                if (parent / "pnpm-lock.yaml").is_file():
                    command = ["pnpm", "test"]
                elif (parent / "yarn.lock").is_file():
                    command = ["yarn", "test"]
                elif (parent / "bun.lockb").is_file() or (parent / "bun.lock").is_file():
                    command = ["bun", "test"]
                else:
                    command = ["npm", "test"]
                commands.append(
                    _command_candidate(
                        "JavaScript/TypeScript",
                        directory,
                        command,
                        "package.json defines a test script",
                        root,
                    )
                )
        elif path.name == "Cargo.toml":
            commands.append(
                _command_candidate(
                    "Rust",
                    directory,
                    ["cargo", "test"],
                    "Cargo manifest",
                    root,
                )
            )
        elif path.name == "pom.xml":
            parent = path.parent
            command = ["./mvnw", "test"] if (parent / "mvnw").is_file() else ["mvn", "test"]
            commands.append(
                _command_candidate("Java", directory, command, "Maven manifest", root)
            )
        elif path.name in {"build.gradle", "build.gradle.kts"}:
            parent = path.parent
            command = (
                ["./gradlew", "test"]
                if (parent / "gradlew").is_file()
                else ["gradle", "test"]
            )
            commands.append(
                _command_candidate("Java/Kotlin", directory, command, "Gradle manifest", root)
            )
        elif path.name == "Package.swift":
            commands.append(
                _command_candidate("Swift", directory, ["swift", "test"], "Swift package manifest", root)
            )
        elif path.name == "mix.exs":
            commands.append(
                _command_candidate("Elixir", directory, ["mix", "test"], "Elixir project manifest", root)
            )
        elif path.name == "rebar.config":
            commands.append(
                _command_candidate("Erlang", directory, ["rebar3", "eunit"], "Erlang project manifest", root)
            )
        elif path.name == "pubspec.yaml":
            commands.append(
                _command_candidate("Dart", directory, ["dart", "test"], "Dart package manifest", root)
            )
        elif path.name == "build.sbt":
            commands.append(
                _command_candidate("Scala", directory, ["sbt", "test"], "SBT build manifest", root)
            )
        elif path.suffix.lower() in {".csproj", ".sln"}:
            commands.append(
                _command_candidate("C#", directory, ["dotnet", "test"], ".NET project or solution", root)
            )
        elif path.name == "Gemfile":
            rake = path.parent / "Rakefile"
            command = (
                ["bundle", "exec", "rake", "test"]
                if rake.is_file()
                else ["bundle", "exec", "rspec"]
            )
            commands.append(
                _command_candidate("Ruby", directory, command, "Ruby project manifest", root)
            )
        elif path.name == "composer.json":
            try:
                composer = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                composer = {}
            scripts = composer.get("scripts") if isinstance(composer, dict) else None
            if isinstance(scripts, dict) and "test" in scripts:
                command = ["composer", "test"]
            else:
                command = ["./vendor/bin/phpunit"]
            commands.append(
                _command_candidate("PHP", directory, command, "Composer project manifest", root)
            )
        elif path.name == "stack.yaml":
            commands.append(
                _command_candidate("Haskell", directory, ["stack", "test"], "Stack manifest", root)
            )
        elif path.suffix == ".cabal":
            commands.append(
                _command_candidate("Haskell", directory, ["cabal", "test"], "Cabal manifest", root)
            )
        elif path.name == "Makefile":
            try:
                has_test_target = "test:" in path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                has_test_target = False
            if has_test_target:
                commands.append(
                    _command_candidate("Make", directory, ["make", "test"], "Makefile test target", root)
                )

    if not commands and any(path.suffix.lower() in {".py", ".pyi"} for path in files):
        commands.append(
            _command_candidate(
                "Python",
                Path("."),
                ["python3", "-m", "unittest", "discover"],
                "Python source files; no test manifest found",
                root,
            )
        )
    return commands


def scan_repository(source: str) -> dict:
    candidate = Path(source).expanduser()
    if not candidate.exists() or not candidate.is_dir():
        raise ScanError("repository scanning requires an available local checkout")
    safe_source = str(candidate.resolve())
    try:
        root = Path(_git(candidate, "rev-parse", "--show-toplevel"))
        target = resolve_target(safe_source)
    except TargetError as exc:
        raise ScanError(str(exc)) from exc

    files, truncated = _repo_files(root)
    counts: Counter[str] = Counter()
    for path in files:
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language:
            counts[language] += 1

    languages = sorted(counts, key=str.casefold)
    commands = _manifest_test_commands(root, files)
    has_fraudguard_go = (root / "plugins/fraudguard/go.mod").is_file()
    return {
        "schema_version": 1,
        "repository": target.source,
        "local_checkout": str(root),
        "commit": target.commit,
        "detected_languages": languages,
        "source_file_counts": dict(sorted(counts.items())),
        "scanned_file_count": len(files),
        "scan_truncated": truncated,
        "test_command_candidates": commands,
        "generation_capabilities": {
            "bundled_seeded_templates": (
                ["fraudguard-go"] if has_fraudguard_go else []
            ),
            "language_neutral_blueprints": True,
            "blueprint_requirement": (
                "Provide task test files, a reference patch, a native test command, "
                "and baseline-failure/pass evidence patterns."
            ),
        },
    }


def format_scan_report(result: dict) -> str:
    lines = [
        f"Repository: {result['repository']}",
        f"Commit: {result['commit']}",
        f"Source files scanned: {result['scanned_file_count']}"
        + (" (scan limit reached)" if result["scan_truncated"] else ""),
        "",
        "Detected languages:",
    ]
    if result["detected_languages"]:
        for language in result["detected_languages"]:
            lines.append(
                f"- {language}: {result['source_file_counts'][language]} source files"
            )
    else:
        lines.append("- No recognized programming-language files")

    lines.extend(["", "Test command candidates:"])
    if result["test_command_candidates"]:
        for candidate in result["test_command_candidates"]:
            command = " ".join(candidate["command"])
            availability = "available" if candidate["command_available"] else "not installed"
            lines.append(
                f"- {candidate['language']} ({candidate['working_directory']}): "
                f"`{command}` — {availability}"
            )
    else:
        lines.append("- No common test manifest or command detected")

    bundled = result["generation_capabilities"]["bundled_seeded_templates"]
    lines.extend(
        [
            "",
            "Task generation:",
            f"- Bundled seeded templates: {', '.join(bundled) if bundled else 'none for this repository'}",
            "- Language-neutral blueprints: available for any language when the task package supplies its native test contract",
        ]
    )
    return "\n".join(lines) + "\n"
