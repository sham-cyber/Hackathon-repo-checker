"""Coverage collection and patch-execution analysis for local validation."""

import json
import re
from pathlib import Path


def coverage_delta(baseline_percent: float | None, post_percent: float | None) -> float | None:
    """Return a stable percentage-point delta, rounded to two decimal places."""
    if baseline_percent is None or post_percent is None:
        return None
    return round(float(post_percent) - float(baseline_percent), 2)


def changed_lines_from_patch(patch: str) -> dict[str, list[tuple[int, str]]]:
    changed: dict[str, list[tuple[int, str]]] = {}
    current_file = None
    new_line = None
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            changed.setdefault(current_file, [])
            new_line = None
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            new_line = int(match.group(1)) if match else None
            continue
        if current_file is None or new_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            changed[current_file].append((new_line, line[1:]))
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        elif line.startswith(" "):
            new_line += 1
    return {path: entries for path, entries in changed.items() if entries}


def _is_executable_added_line(source: str) -> bool:
    line = source.strip()
    if not line or line in {"{", "}", "},", "(", ")"}:
        return False
    if line.startswith("//") or line.startswith("/*") or line.startswith("*"):
        return False
    if line.startswith("import ") or (
        line.startswith('"') and line.endswith('"')
    ):
        return False
    if re.match(r"^(?:func\s|type\s|const\s|var\s)", line):
        return False
    return True


def _go_profile_coverage(profile: str) -> tuple[dict[str, set[int]], dict[str, int]]:
    covered_lines: dict[str, set[int]] = {}
    statements: dict[str, list[int]] = {}
    for line in profile.splitlines():
        if not line or line.startswith("mode:"):
            continue
        match = re.match(
            r"(.+?):(\d+)\.\d+,(\d+)\.\d+\s+(\d+)\s+(\d+)$",
            line,
        )
        if not match:
            continue
        filename, start, end, count, hits = match.groups()
        start_line, end_line = int(start), int(end)
        statements.setdefault(filename, []).append(int(count))
        if int(hits) > 0:
            covered_lines.setdefault(filename, set()).update(
                range(start_line, end_line + 1)
            )
    totals = {
        filename: sum(file_statements)
        for filename, file_statements in statements.items()
    }
    return covered_lines, totals


def _go_function_spans(source: str) -> list[tuple[int, str]]:
    result = []
    pattern = re.compile(
        r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    )
    for match in pattern.finditer(source):
        result.append((source.count("\n", 0, match.start()) + 1, match.group(1)))
    return result


def _go_function_coverage(output: str) -> tuple[float | None, dict[tuple[str, str], float]]:
    total_match = re.search(r"(?m)^total:\s+\(statements\)\s+([0-9.]+)%\s*$", output)
    total = float(total_match.group(1)) if total_match else None
    functions = {}
    for line in output.splitlines():
        match = re.match(r"(.+?):\d+:\s+(\S+)\s+([0-9.]+)%$", line.strip())
        if match:
            filename, name, percentage = match.groups()
            functions[(Path(filename).name, name)] = float(percentage)
    return total, functions


def summarize_go_coverage(profile: str, function_output: str) -> dict:
    total, functions = _go_function_coverage(function_output)
    covered_lines, statements = _go_profile_coverage(profile)
    return {
        "available": total is not None,
        "kind": "go",
        "total_percent": total,
        "profile_files": len(statements),
        "covered_profile_lines": sum(len(lines) for lines in covered_lines.values()),
        "profile_statements": sum(statements.values()),
        "function_count": len(functions),
        "covered_function_count": sum(value > 0 for value in functions.values()),
    }


def _match_coverage_path(target_path: str, candidates: list[str]) -> str | None:
    normalized_target = target_path.replace("\\", "/")
    exact = [path for path in candidates if path.replace("\\", "/").endswith(normalized_target)]
    if len(exact) == 1:
        return exact[0]
    basename = Path(target_path).name
    matches = [path for path in candidates if Path(path).name == basename]
    return matches[0] if len(matches) == 1 else None


def analyze_go_patch_coverage(
    patch: str,
    profile: str,
    function_output: str,
    checkout: str | Path,
) -> dict:
    added = changed_lines_from_patch(patch)
    covered_by_file, statement_totals = _go_profile_coverage(profile)
    total_percent, function_percentages = _go_function_coverage(function_output)
    all_profile_files = sorted(set(covered_by_file) | set(statement_totals))
    details = {}
    executable_total = executable_covered = 0
    modified_functions = []

    for target_path, additions in sorted(added.items()):
        source_path = Path(checkout) / target_path
        function_spans = (
            _go_function_spans(source_path.read_text(encoding="utf-8"))
            if source_path.is_file()
            else []
        )
        profile_path = _match_coverage_path(target_path, all_profile_files)
        covered_lines = covered_by_file.get(profile_path, set()) if profile_path else set()
        executable = [
            (line_number, text)
            for line_number, text in additions
            if _is_executable_added_line(text)
        ]
        line_covered = sum(line_number in covered_lines for line_number, _ in executable)
        executable_total += len(executable)
        executable_covered += line_covered

        touched_functions = set()
        for line_number, _ in executable:
            candidates = [item for item in function_spans if item[0] <= line_number]
            if candidates:
                touched_functions.add(candidates[-1][1])
        function_results = []
        for name in sorted(touched_functions):
            percentage = (
                function_percentages.get((Path(profile_path).name, name))
                if profile_path
                else None
            )
            function_results.append(
                {
                    "name": name,
                    "coverage_percent": percentage,
                    "exercised": percentage is not None and percentage > 0,
                }
            )
            modified_functions.append(
                {
                    "file": target_path,
                    "name": name,
                    "coverage_percent": percentage,
                    "exercised": percentage is not None and percentage > 0,
                }
            )
        details[target_path] = {
            "package": str(Path(target_path).parent),
            "executable_added_lines": len(executable),
            "covered_added_lines": line_covered,
            "added_line_coverage_percent": (
                round(line_covered * 100.0 / len(executable), 2)
                if executable
                else None
            ),
            "modified_functions": function_results,
        }

    line_exercised = (
        executable_total > 0 and executable_covered == executable_total
    )
    functions_known = bool(modified_functions) and all(
        item["coverage_percent"] is not None for item in modified_functions
    )
    functions_exercised = (
        all(item["exercised"] for item in modified_functions)
        if functions_known
        else None
    )
    return {
        "available": total_percent is not None,
        "kind": "go",
        "total_percent": total_percent,
        "files": details,
        "patched_executable_lines": {
            "covered": executable_covered,
            "total": executable_total,
            "all_exercised": line_exercised if executable_total else None,
        },
        "patched_functions": {
            "items": modified_functions,
            "all_exercised": functions_exercised,
        },
    }


def parse_custom_coverage_report(
    output: str,
    report_format: str,
    patch: str,
    checkout: str | Path,
) -> dict:
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "kind": report_format,
            "reason": f"coverage report did not contain JSON: {exc}",
        }
    if report_format == "coverage.py-json":
        total = data.get("totals", {}).get("percent_covered")
        files = {}
        for path, item in data.get("files", {}).items():
            functions = {}
            for name, details in item.get("functions", {}).items():
                executed = details.get("executed_lines", [])
                missing = details.get("missing_lines", [])
                summary = details.get("summary", {})
                functions[name] = {
                    "coverage_percent": (
                        summary.get("percent_covered")
                        if summary.get("percent_covered") is not None
                        else (
                            round(100 * len(executed) / (len(executed) + len(missing)), 2)
                            if executed or missing
                            else 100.0
                        )
                    ),
                    "executed_lines": executed,
                    "start_line": details.get(
                        "start_line",
                        min(executed + missing) if executed or missing else None,
                    ),
                }
            files[path] = {
                "executed_lines": item.get("executed_lines", []),
                "functions": functions,
            }
    elif report_format == "normalized-json":
        total = data.get("total_percent")
        files = data.get("files", {})
    else:
        return {
            "available": False,
            "kind": report_format,
            "reason": "unsupported custom coverage report format",
        }
    return _analyze_generic_lines(patch, checkout, total, files, report_format)


def _analyze_generic_lines(
    patch: str,
    checkout: str | Path,
    total: object,
    coverage_files: dict,
    kind: str,
) -> dict:
    try:
        total_percent = float(total)
    except (TypeError, ValueError):
        total_percent = None
    file_names = list(coverage_files)
    changes = changed_lines_from_patch(patch)
    details = {}
    patched_functions = []
    executable_total = executable_covered = 0
    for target_path, additions in sorted(changes.items()):
        coverage_path = _match_coverage_path(target_path, file_names)
        item = coverage_files.get(coverage_path, {}) if coverage_path else {}
        executed = set(item.get("executed_lines", []))
        executable = [
            number for number, source in additions if _is_executable_added_line(source)
        ]
        covered = sum(number in executed for number in executable)
        executable_total += len(executable)
        executable_covered += covered
        functions = item.get("functions", {})
        starts = sorted(
            (int(info["start_line"]), name)
            for name, info in functions.items()
            if info.get("start_line") is not None
        )
        for index, (start_line, name) in enumerate(starts):
            info = functions[name]
            next_start = starts[index + 1][0] if index + 1 < len(starts) else None
            end_line = info.get("end_line", next_start - 1 if next_start else None)
            belongs = any(
                line >= start_line and (end_line is None or line <= int(end_line))
                for line in executable
            )
            if belongs:
                percentage = info.get("coverage_percent")
                if percentage is None:
                    function_executed = bool(info.get("executed_lines"))
                else:
                    function_executed = float(percentage) > 0
                patched_functions.append(
                    {
                        "file": target_path,
                        "name": name,
                        "coverage_percent": percentage,
                        "exercised": function_executed,
                    }
                )
        details[target_path] = {
            "package": str(Path(target_path).parent),
            "executable_added_lines": len(executable),
            "covered_added_lines": covered,
            "added_line_coverage_percent": (
                round(covered * 100.0 / len(executable), 2) if executable else None
            ),
            "modified_functions": [
                item for item in patched_functions if item["file"] == target_path
            ],
        }
    functions_exercised = (
        all(item["exercised"] for item in patched_functions)
        if patched_functions
        else None
    )
    return {
        "available": total_percent is not None,
        "kind": kind,
        "total_percent": total_percent,
        "files": details,
        "patched_executable_lines": {
            "covered": executable_covered,
            "total": executable_total,
            "all_exercised": (
                executable_total > 0 and executable_covered == executable_total
                if executable_total
                else None
            ),
        },
        "patched_functions": {
            "items": patched_functions,
            "all_exercised": functions_exercised,
        },
    }

