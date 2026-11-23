"""Deterministic task-variation profiles and human-readable portfolio comparisons."""

import hashlib
import json
import re
import shlex
from pathlib import Path

from .models import TaskSpec


def variation_profile(spec: TaskSpec) -> dict:
    payload = {
        "family": spec.family,
        "variant": spec.variant,
        "dimensions": list(spec.variation_dimensions),
        "target_symbols": list(spec.target_symbols),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    structure = "\n".join(
        (spec.title, spec.scenario, spec.requirements, spec.patch, spec.test_source)
    )
    for symbol in sorted(spec.target_symbols, key=len, reverse=True):
        structure = structure.replace(symbol, "<target-symbol>")
    structure = re.sub(r"agent-\d+-\d+", "<sample-id>", structure)
    structure = re.sub(r"\b\d[\d_]*\b", "<number>", structure)
    return {
        **payload,
        "signature": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20],
        "structure_signature": hashlib.sha256(
            structure.encode("utf-8")
        ).hexdigest()[:20],
    }


def _compact_summary(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rsplit(" ", 1)[0] + "..."


def _instruction_goal(package: Path) -> str:
    path = package / "instruction.md"
    if not path.is_file():
        return "instruction.md missing"
    source = path.read_text(encoding="utf-8")
    section = re.search(
        r"(?ms)^##\s+Requirements\s*\n(.*?)(?=^##\s|\Z)",
        source,
    )
    if section:
        return _compact_summary(section.group(1))
    fallback = next(
        (
            line.strip()
            for line in source.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
        "",
    )
    return _compact_summary(fallback) or "goal not found"


def _solve_changes(package: Path) -> str:
    path = package / "solution/solve.sh"
    if not path.is_file():
        return "solution/solve.sh missing"
    source = path.read_text(encoding="utf-8")
    if "git apply" in source:
        return "Applies solution/reference.patch to the pinned checkout."
    commands = [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return _compact_summary(" ".join(commands)) or "no executable change detected"


def compare_task_packages(package_paths: list[str | Path]) -> dict:
    """Compare generated packages; missing profiles are reported as unscored."""
    if len(package_paths) < 2:
        raise ValueError("compare requires at least two task packages")

    tasks = []
    for raw_path in package_paths:
        package = Path(raw_path).expanduser().resolve()
        task = json.loads((package / "task.json").read_text(encoding="utf-8"))
        manifest_path = package / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {}
        )
        local_coverage = (
            manifest.get("validation", {})
            .get("local_preflight", {})
            .get("coverage", {})
        )
        coverage_reason = (
            local_coverage.get("baseline", {}).get("reason")
            or local_coverage.get("post_patch", {}).get("reason")
        )
        patch_path = package / "solution/reference.patch"
        patch = patch_path.read_text(encoding="utf-8") if patch_path.is_file() else ""
        target_files = sorted(
            set(re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE))
        )
        tests = task.get("tests", {})
        local_validation = manifest.get("validation", {}).get("local_preflight", {})
        preflight_status = local_validation.get("status", "not_run")
        coverage = local_validation.get("coverage") or local_coverage
        harbor_status = manifest.get("harbor_status")
        if not harbor_status:
            harbor_status = manifest.get("validation", {}).get("harbor", {}).get(
                "status", "pending"
            )
        if harbor_status in {"not_run", "not_validated", "unsupported", None}:
            harbor_status = "pending"
        target_packages = task.get("patch_packages") or sorted(
            {
                str(Path(path).parent)
                for path in task.get("patch_targets", target_files)
                if str(Path(path).parent) != "."
            }
        )
        tasks.append(
            {
                "path": str(package),
                "task_id": task.get("task_id", package.name),
                "seed": task.get("seed"),
                "seed_mode": task.get(
                    "seed_mode", manifest.get("seed_mode", "selected")
                ),
                "family": task.get("family", "unknown"),
                "scenario": task.get("scenario", ""),
                "target": task.get("target", {}),
                "variation": task.get("variation"),
                "target_files": task.get("patch_targets")
                or target_files
                or sorted(
                    {
                        item.get("target_path", "")
                        for item in tests.get("files", [])
                        if isinstance(item, dict)
                    }
                ),
                "target_packages": target_packages,
                "instruction_goal": _instruction_goal(package),
                "solve_changes": _solve_changes(package),
                "native_test_command": shlex.join(tests.get("command", [])),
                "test_assertions": tests.get("expected_baseline_failures", []),
                "preflight_status": preflight_status,
                "harbor_status": harbor_status,
                "coverage": coverage,
                "coverage_reason": coverage_reason,
            }
        )

    signatures = {}
    unscored = []
    for task in tasks:
        variation = task.get("variation")
        if not isinstance(variation, dict) or not variation.get(
            "structure_signature", variation.get("signature")
        ):
            unscored.append(task["task_id"])
            continue
        key = (
            task.get("target", {}).get("commit", ""),
            variation.get("structure_signature", variation.get("signature")),
        )
        signatures.setdefault(key, []).append(task["task_id"])
    clones = [ids for ids in signatures.values() if len(ids) > 1]

    return {
        "tasks": tasks,
        "likely_clone_groups": clones,
        "unscored_tasks": unscored,
        "distinct_signatures": len(signatures),
        "scored_tasks": len(tasks) - len(unscored),
    }


def render_comparison(report: dict) -> str:
    tasks = report["tasks"]
    lines = [
        "# Seeded task variation comparison",
        "",
        "This report compares task behavior profiles, target areas, and generated "
        "test assertions. The clone check normalizes target-symbol names and "
        "sample values, so changing only an identifier or literal does not count "
        "as meaningful variation.",
        "",
        "| Seed | Mode | Family / variant | Variation dimensions | Target files / modules | Instruction goal | `solve.sh` changes | Native test command | Test assertions | Preflight | Baseline coverage | Post-patch coverage | Delta | Patched code exercised | Coverage status | Scenario | Harbor |",
        "|---:|---|---|---|---|---|---|---|---|---|---:|---:|---:|---|---|---|---|",
    ]
    for task in tasks:
        variation = task.get("variation") or {}
        profile = (
            f"{variation.get('family', task['family'])} / "
            f"{variation.get('variant', 'unscored')}"
        )
        dimensions = ", ".join(variation.get("dimensions", [])) or "not annotated"
        symbols = ", ".join(variation.get("target_symbols", []))
        targets = ", ".join(task["target_files"])
        packages = ", ".join(task.get("target_packages", []))
        target_summary = "; ".join(part for part in (targets, packages, symbols) if part)
        assertions = ", ".join(task["test_assertions"]) or "not listed"
        coverage = task.get("coverage", {})
        baseline_percent = coverage.get("baseline", {}).get("total_percent")
        post_percent = coverage.get("post_patch", {}).get("total_percent")
        delta = coverage.get("delta_percentage_points")
        patch_execution = coverage.get("patched_code_exercised") or {}
        line_coverage = patch_execution.get("patched_executable_lines", {})
        function_coverage = patch_execution.get("patched_functions", {})
        exercised_parts = []
        if line_coverage:
            exercised_parts.append(
                f"lines {line_coverage.get('covered', 0)}/{line_coverage.get('total', 0)}"
            )
        if function_coverage.get("items"):
            exercised_parts.append(
                f"functions {sum(item.get('exercised') is True for item in function_coverage['items'])}"
                f"/{len(function_coverage['items'])}"
            )
        exercised = ", ".join(exercised_parts) or "not measured"
        coverage_status = coverage.get("status", "not measured")
        if task.get("coverage_reason"):
            coverage_status += ": " + task["coverage_reason"]
        fields = [
            str(task.get("seed", "—")),
            str(task.get("seed_mode", "selected")),
            profile,
            dimensions,
            target_summary or "not identified",
            task.get("instruction_goal", "goal not found"),
            task.get("solve_changes", "solve script not found"),
            task.get("native_test_command", "not recorded"),
            assertions,
            task.get("preflight_status", "not_run"),
            f"{baseline_percent:.2f}%" if isinstance(baseline_percent, (int, float)) else "n/a",
            f"{post_percent:.2f}%" if isinstance(post_percent, (int, float)) else "n/a",
            f"{delta:+.2f} pp" if isinstance(delta, (int, float)) else "n/a",
            exercised,
            coverage_status,
            task["scenario"] or "—",
            str(task["harbor_status"]),
        ]
        escaped = [value.replace("|", "\\|").replace("\n", " ") for value in fields]
        lines.append("| " + " | ".join(escaped) + " |")

    lines.extend(["", "## Portfolio summary", ""])
    lines.append(
        f"- Tasks with variation metadata: {report['scored_tasks']} of {len(tasks)}"
    )
    lines.append(f"- Distinct normalized task structures: {report['distinct_signatures']}")
    lines.append(f"- Likely clone groups: {len(report['likely_clone_groups'])}")
    measured = sum(
        isinstance(task.get("coverage", {}).get("baseline", {}).get("total_percent"), (int, float))
        and isinstance(task.get("coverage", {}).get("post_patch", {}).get("total_percent"), (int, float))
        for task in tasks
    )
    lines.append(f"- Tasks with baseline and post-patch coverage: {measured} of {len(tasks)}")
    unavailable_reasons = sorted(
        {
            task["coverage_reason"]
            for task in tasks
            if task.get("coverage_reason")
        }
    )
    for reason in unavailable_reasons:
        lines.append(f"- Coverage unavailable: {reason}")
    for group in report["likely_clone_groups"]:
        lines.append(f"  - {', '.join(group)}")
    if report["unscored_tasks"]:
        lines.append(
            "- Missing variation metadata: " + ", ".join(report["unscored_tasks"])
        )
    if not report["likely_clone_groups"] and not report["unscored_tasks"]:
        lines.append("- No repeated normalized task structures detected.")
    lines.extend(
        [
            "",
            "A distinct profile is evidence of variation in the authored recipe, "
            "not proof that a coding task is valid. Harbor validity still requires "
            "real `nop` reward 0 and `oracle` reward 1 trials.",
            "",
        ]
    )
    return "\n".join(lines)
