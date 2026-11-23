import hashlib
import json
import os
import random
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch as mock_patch
from pathlib import Path

from task_factory.factory import FactoryError, generate_task
from task_factory.coverage import (
    analyze_go_patch_coverage,
    coverage_delta,
    parse_custom_coverage_report,
)
from task_factory.cli import main as cli_main
from task_factory.harbor_runner import run_agent_benchmark, run_harbor_validation
from task_factory.portfolio import generate_portfolio, select_diverse_seeds
from task_factory.scanner import scan_repository
from task_factory.seed_runs import (
    derive_auto_seed,
    generate_seeded_run,
    inspect_seed_reference,
    record_agent_run,
    record_harbor_result,
    watch_target,
)
from task_factory.targets import TargetError, resolve_target, validate_source
from task_factory.templates import BUILDERS, build_spec
from task_factory.variation import compare_task_packages, render_comparison, variation_profile
from task_factory.validation import (
    _clean_text,
    _expected_failures_seen,
    _looks_like_environment_failure,
    _test_pattern,
    validate_task,
)


class FactoryTests(unittest.TestCase):
    def test_auto_seed_derivation_is_stable_for_commit_and_patch(self):
        commit = "a" * 40
        patch_bytes = b"diff --git a/file.go b/file.go\n+new behavior\n"
        first = derive_auto_seed(commit, patch_bytes)
        self.assertEqual(first, derive_auto_seed(commit, patch_bytes))
        self.assertNotEqual(first, derive_auto_seed(commit, b"different patch\n"))
        self.assertNotEqual(first, derive_auto_seed("b" * 40, patch_bytes))
        self.assertGreaterEqual(first, 0)
        self.assertLess(first.bit_length(), 257)

    def test_supplied_patch_is_identified_by_digest_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            patch_file = root / "incoming.patch"
            patch_bytes = b"diff --git a/private.go b/private.go\n+do not log contents\n"
            patch_file.write_bytes(patch_bytes)
            state = inspect_seed_reference(str(repo), patch_file)
            self.assertEqual(
                state["reference"]["patch_identifier"],
                "sha256:" + hashlib.sha256(patch_bytes).hexdigest(),
            )
            self.assertEqual(state["reference"]["patch_source"], "provided-patch-file")
            self.assertEqual(
                state["auto_seed"],
                derive_auto_seed(git(repo, "rev-parse", "HEAD"), patch_bytes),
            )
            self.assertNotIn("do not log contents", json.dumps(state["reference"]))

    def test_selected_seed_mode_records_reference_and_pending_harbor_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            result = generate_seeded_run(
                str(repo),
                root / "selected-task",
                seed_mode="selected",
                selected_seed=23,
                log_path=root / "runs/seed_log.jsonl",
            )
            repeated = generate_seeded_run(
                str(repo),
                root / "selected-task-repeat",
                seed_mode="selected",
                selected_seed=23,
                log_path=root / "runs/seed_log.jsonl",
            )
            self.assertEqual(
                file_digest_map(Path(result["package_path"])),
                file_digest_map(Path(repeated["package_path"])),
            )
            task = json.loads((Path(result["package_path"]) / "task.json").read_text())
            manifest = json.loads(
                (Path(result["package_path"]) / "manifest.json").read_text()
            )
            entry = json.loads((root / "runs/seed_log.jsonl").read_text().splitlines()[0])
            self.assertEqual(result["seed"], 23)
            self.assertEqual(task["seed_mode"], "selected")
            self.assertEqual(manifest["seed_mode"], "selected")
            self.assertEqual(entry["seed_mode"], "selected")
            self.assertEqual(entry["seed"], 23)
            self.assertTrue(entry["timestamp"])
            self.assertEqual(entry["commit_sha"], git(repo, "rev-parse", "HEAD"))
            self.assertEqual(entry["harbor_status"], "pending")
            self.assertIsNone(entry["coverage_delta_percentage_points"])
            self.assertEqual(entry["target_files"], task["patch_targets"])
            self.assertEqual(manifest["seed_run"]["source_key"], entry["source_key"])

    def test_auto_mode_validates_and_logs_before_after_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            validation = {
                "status": "passed",
                "coverage": {
                    "status": "measured",
                    "baseline": {"total_percent": 41.5},
                    "post_patch": {"total_percent": 57.0},
                    "delta_percentage_points": 15.5,
                },
            }
            with mock_patch(
                "task_factory.validation.validate_task", return_value=validation
            ) as validate:
                result = generate_seeded_run(
                    str(repo),
                    root / "auto-task",
                    seed_mode="auto",
                    log_path=root / "runs/seed_log.jsonl",
                )
            reference = inspect_seed_reference(str(repo))["reference"]
            entry = json.loads((root / "runs/seed_log.jsonl").read_text())
            task_dir = Path(result["package_path"])
            task = json.loads((task_dir / "task.json").read_text())
            manifest = json.loads((task_dir / "manifest.json").read_text())
            self.assertTrue(validate.called)
            self.assertEqual(result["seed"], derive_auto_seed(reference["commit_sha"]))
            self.assertEqual(task["seed_mode"], "auto")
            self.assertEqual(manifest["seed_mode"], "auto")
            self.assertEqual(manifest["seed"], result["seed"])
            self.assertEqual(
                manifest["seed_reference"]["source_key"], reference["source_key"]
            )
            self.assertEqual(entry["seed"], result["seed"])
            self.assertEqual(entry["source_key"], reference["source_key"])
            self.assertEqual(entry["baseline_coverage_percent"], 41.5)
            self.assertEqual(entry["post_patch_coverage_percent"], 57.0)
            self.assertEqual(entry["coverage_delta_percentage_points"], 15.5)
            self.assertEqual(entry["local_validation_status"], "passed")
            self.assertEqual(entry["harbor_status"], "pending")

    def test_watch_once_processes_new_patch_only_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            validation = {
                "status": "unsupported",
                "coverage": {"status": "unsupported"},
            }
            with mock_patch(
                "task_factory.validation.validate_task", return_value=validation
            ):
                first = watch_target(
                    str(repo),
                    root / "auto-tasks",
                    log_path=root / "runs/seed_log.jsonl",
                    once=True,
                )
                repeated = watch_target(
                    str(repo),
                    root / "auto-tasks",
                    log_path=root / "runs/seed_log.jsonl",
                    once=True,
                )
                (repo / "README.md").write_text("new tracked patch\n")
                changed = watch_target(
                    str(repo),
                    root / "auto-tasks",
                    log_path=root / "runs/seed_log.jsonl",
                    once=True,
                )
                commit_all(repo, "commit the tracked patch")
                committed = watch_target(
                    str(repo),
                    root / "auto-tasks",
                    log_path=root / "runs/seed_log.jsonl",
                    once=True,
                )
            records = [
                json.loads(line)
                for line in (root / "runs/seed_log.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(first["processed"]), 1)
            self.assertTrue(repeated["skipped_existing"])
            self.assertEqual(len(changed["processed"]), 1)
            self.assertEqual(len(committed["processed"]), 1)
            self.assertEqual(len(records), 3)
            self.assertNotEqual(records[0]["source_key"], records[1]["source_key"])
            self.assertNotEqual(records[0]["seed"], records[1]["seed"])
            self.assertEqual(records[1]["patch_source"], "tracked-working-tree-diff")
            self.assertEqual(records[1]["harbor_status"], "pending")
            self.assertNotEqual(records[1]["commit_sha"], records[2]["commit_sha"])
            self.assertIsNone(records[2]["patch_identifier"])

    def test_cli_requires_selected_seed_and_accepts_auto_seed_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            errors = StringIO()
            with redirect_stderr(errors):
                missing_seed = cli_main(
                    [
                        "generate",
                        "--target",
                        str(repo),
                        "--seed-mode",
                        "selected",
                        "--out",
                        str(root / "missing-seed"),
                    ]
                )
            self.assertEqual(missing_seed, 2)
            self.assertIn("requires --seed", errors.getvalue())
            selected_output = StringIO()
            with redirect_stdout(selected_output):
                selected_mode = cli_main(
                    [
                        "generate",
                        "--target",
                        str(repo),
                        "--seed",
                        "42",
                        "--out",
                        str(root / "selected-task"),
                        "--log",
                        str(root / "runs/seed_log.jsonl"),
                    ]
                )
            self.assertEqual(selected_mode, 0)
            selected_result = json.loads(selected_output.getvalue())
            self.assertEqual(selected_result["seed_mode"], "selected")
            self.assertEqual(selected_result["seed"], 42)
            validation = {"status": "unsupported", "coverage": {"status": "unsupported"}}
            output = StringIO()
            with mock_patch(
                "task_factory.validation.validate_task", return_value=validation
            ), redirect_stdout(output):
                auto_mode = cli_main(
                    [
                        "generate",
                        "--target",
                        str(repo),
                        "--auto-seed",
                        "--out",
                        str(root / "auto-task"),
                        "--log",
                        str(root / "runs/seed_log.jsonl"),
                    ]
                )
            self.assertEqual(auto_mode, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["seed_mode"], "auto")
            self.assertEqual(result["local_validation_status"], "unsupported")

    def test_explicit_harbor_validation_appends_status_event_for_seeded_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            result = generate_seeded_run(
                str(repo),
                root / "auto-task",
                seed_mode="selected",
                selected_seed=11,
                log_path=root / "runs/seed_log.jsonl",
            )
            logged = record_harbor_result(
                result["package_path"],
                {
                    "status": "valid",
                    "jobs": {
                        "nop": {"trials": [{"reward": 0, "atif_recorded": False}]},
                        "oracle": {"trials": [{"reward": 1, "atif_recorded": False}]},
                    },
                },
            )
            agent_logged = record_agent_run(
                result["package_path"],
                {
                    "agent": "test-agent",
                    "model": "test-model",
                    "trials": [
                        {
                            "reward": 1,
                            "atif_recorded": True,
                            "atif_trajectory": "jobs/trial-1/agent/trajectory.json",
                        }
                    ],
                },
            )
            records = [
                json.loads(line)
                for line in (root / "runs/seed_log.jsonl").read_text().splitlines()
            ]
            manifest = json.loads(
                (Path(result["package_path"]) / "manifest.json").read_text()
            )
            self.assertEqual(logged["log_record"]["event"], "harbor_validation")
            self.assertEqual(agent_logged["log_record"]["event"], "agent_run")
            self.assertTrue(records[-1]["trial_summary"][0]["atif_recorded"])
            self.assertEqual(records[-1]["harbor_status"], "valid")
            self.assertEqual(manifest["harbor_status"], "valid")

    def test_seed_and_target_commit_reproduce_all_generated_task_files(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_fraudguard_repo(Path(temp) / "target")
            source_status = git(repo, "status", "--porcelain")
            first = generate_task(42, str(repo), Path(temp) / "first")
            second = generate_task(42, str(repo), Path(temp) / "second")
            self.assertEqual(file_digest_map(first), file_digest_map(second))
            self.assertEqual(git(repo, "status", "--porcelain"), source_status)

    def test_seed_selects_all_supported_task_families(self):
        selected = {build_spec(seed).family for seed in range(50)}
        self.assertEqual(
            selected,
            {builder(0, random.Random(0)).family for builder in BUILDERS},
        )

    def test_generated_task_has_real_requirements_patch_tests_and_not_valid_state(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_fraudguard_repo(Path(temp) / "target")
            output = generate_task(7, str(repo), Path(temp) / "task")
            task = json.loads((output / "task.json").read_text())
            manifest = json.loads((output / "manifest.json").read_text())
            test_path = task["tests"]["files"][0]["package_path"]
            self.assertIn("Acceptance criteria", (output / "instruction.md").read_text())
            self.assertIn("diff --git", (output / "solution/reference.patch").read_text())
            self.assertIn("func TestGeneratedTask", (output / test_path).read_text())
            self.assertEqual(task["schema_version"], 2)
            self.assertTrue((output / "task.toml").is_file())
            self.assertTrue((output / "environment/Dockerfile").is_file())
            self.assertTrue((output / "environment/source.tar.gz").is_file())
            self.assertTrue((output / "solution/solve.sh").stat().st_mode & 0o111)
            self.assertTrue((output / "tests/test.sh").stat().st_mode & 0o111)
            for required in (
                "task.toml",
                "instruction.md",
                "environment/Dockerfile",
                "solution/solve.sh",
                "tests/test.sh",
            ):
                self.assertTrue((output / required).is_file(), required)
            for script in ("solution/solve.sh", "tests/test.sh"):
                script_bytes = (output / script).read_bytes()
                self.assertNotIn(b"\r", script_bytes, script)
                self.assertTrue(script_bytes.endswith(b"\n"), script)
            for required in (
                "task.toml",
                "instruction.md",
                "environment/Dockerfile",
                "solution/solve.sh",
                "tests/test.sh",
            ):
                self.assertIn(required, manifest["files"])
            wrapper = (output / "tests/test.sh").read_text()
            self.assertIn("/logs/verifier/reward.txt", wrapper)
            self.assertIn("printf '0\\n'", wrapper)
            self.assertIn("printf '1\\n'", wrapper)
            self.assertIn("go test", wrapper)
            task_toml = (output / "task.toml").read_text()
            self.assertIn('schema_version = "1.4"', task_toml)
            self.assertIn("[environment]", task_toml)
            self.assertIn('network_mode = "no-network"', task_toml)
            self.assertEqual(manifest["target"]["commit"], task["target"]["commit"])
            self.assertEqual(manifest["task_status"], "not_validated")
            self.assertEqual(manifest["validation"]["harbor"]["status"], "not_run")
            self.assertEqual(task["patch_targets"], ["plugins/fraudguard/config_validator.go"])
            self.assertEqual(manifest["patch_targets"], task["patch_targets"])
            self.assertTrue(task["variation"]["structure_signature"])
            self.assertIn(test_path, manifest["files"])
            self.assertIn("task.toml", manifest["files"])
            self.assertIn("environment/source.tar.gz", manifest["files"])
            self.assertIn(".agents/**", task["harbor"]["source_snapshot"]["excludes"])
            with tarfile.open(output / "environment/source.tar.gz", "r:gz") as archive:
                names = archive.getnames()
            self.assertNotIn(".agents/memory/private-project-context.md", names)

    def test_distinct_seeds_can_change_family_or_scenario(self):
        specs = [build_spec(seed) for seed in range(20)]
        self.assertGreater(len({spec.family for spec in specs}), 1)
        self.assertGreater(len({spec.scenario for spec in specs}), 1)

    def test_each_task_family_has_substantive_seeded_variants(self):
        variants = {builder(0, random.Random(0)).family: set() for builder in BUILDERS}
        specs = {}
        for seed in range(100):
            spec = build_spec(seed)
            variants[spec.family].add(spec.variant)
            specs[(spec.family, spec.variant)] = spec
        for family, family_variants in variants.items():
            self.assertGreaterEqual(len(family_variants), 2, family)
        self.assertIn(
            "unicode.IsControl",
            specs[("config-exempt-ids", "embedded-control-character")].patch,
        )
        self.assertIn(
            "array-contained object",
            specs[("duplicate-runtime-json-keys", "escaped-key-and-array-object")].scenario,
        )
        self.assertIn(
            "unset-versus-empty-override",
            specs[("strict-env-booleans", "unset-versus-empty-override")].variant,
        )
        first_field = build_spec(0)
        second_field = build_spec(13)
        self.assertEqual(first_field.variant, second_field.variant)
        self.assertNotEqual(
            variation_profile(first_field)["signature"],
            variation_profile(second_field)["signature"],
        )
        self.assertEqual(
            variation_profile(first_field)["structure_signature"],
            variation_profile(second_field)["structure_signature"],
        )

    def test_novelty_aware_portfolio_selects_unique_profiles_deterministically(self):
        first, first_examined = select_diverse_seeds(0, 6, 500)
        second, second_examined = select_diverse_seeds(0, 6, 500)
        self.assertEqual(first, second)
        self.assertEqual(first_examined, second_examined)
        signatures = {
            variation_profile(build_spec(seed))["signature"] for seed in first
        }
        self.assertEqual(len(signatures), 6)
        self.assertGreater(len({build_spec(seed).family for seed in first}), 1)

    def test_generated_portfolio_has_side_by_side_report_and_pending_harbor_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            result = generate_portfolio(
                str(repo),
                0,
                3,
                root / "portfolio",
                search_limit=100,
            )
            portfolio = root / "portfolio"
            manifest = json.loads((portfolio / "portfolio.json").read_text())
            self.assertEqual(result["portfolio_status"], "not_validated")
            self.assertEqual(len(manifest["tasks"]), 3)
            self.assertEqual(manifest["comparison"]["distinct_signatures"], 3)
            report = (portfolio / "variation-comparison.md").read_text()
            self.assertIn("Baseline coverage", report)
            self.assertIn("Post-patch coverage", report)
            self.assertIn("Harbor", report)
            for task_row in manifest["tasks"]:
                task_manifest = json.loads(
                    (portfolio / task_row["path"] / "manifest.json").read_text()
                )
                self.assertEqual(task_manifest["task_status"], "not_validated")

    def test_compare_cli_generates_seed_packages_and_markdown_json_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_fraudguard_repo(root / "target")
            validation = {
                "status": "unsupported",
                "coverage": {
                    "status": "unsupported",
                    "baseline": {
                        "available": False,
                        "reason": "Go 1.27.3 is unavailable",
                    },
                    "post_patch": {
                        "available": False,
                        "reason": "Go 1.27.3 is unavailable",
                    },
                    "delta_percentage_points": None,
                    "target_files": ["plugins/fraudguard/config_validator.go"],
                    "target_packages": ["plugins/fraudguard"],
                },
            }

            def fake_validate(package, timeout=180):
                manifest_path = Path(package) / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest.setdefault("validation", {})["local_preflight"] = validation
                manifest_path.write_text(json.dumps(manifest))
                return validation

            markdown_path = root / "comparison.md"
            json_path = root / "comparison.json"
            output = StringIO()
            with (
                mock_patch(
                    "task_factory.validation.validate_task",
                    side_effect=fake_validate,
                ),
                mock_patch(
                    "task_factory.cli.run_harbor_validation",
                    side_effect=AssertionError("compare must not start Harbor"),
                ),
                mock_patch(
                    "task_factory.cli.run_agent_benchmark",
                    side_effect=AssertionError("compare must not start agent runs"),
                ),
                redirect_stdout(output),
            ):
                status = cli_main(
                    [
                        "compare",
                        "--seeds",
                        "0",
                        "1",
                        "--target",
                        str(repo),
                        "--out-root",
                        str(root / "comparison-tasks"),
                        "--log",
                        str(root / "runs/seed_log.jsonl"),
                        "--out",
                        str(markdown_path),
                        "--json-out",
                        str(json_path),
                    ]
                )
            self.assertEqual(status, 0, output.getvalue())
            markdown = markdown_path.read_text()
            report = json.loads(json_path.read_text())
            self.assertIn("| Seed | Mode | Family / variant", markdown)
            self.assertIn("selected", markdown)
            self.assertIn("Go 1.27.3 is unavailable", markdown)
            self.assertIn("pending", markdown)
            self.assertIn("Applies solution/reference.patch", markdown)
            self.assertIn("go test", markdown)
            self.assertEqual(len(report["tasks"]), 2)
            self.assertEqual(
                [task["seed_mode"] for task in report["tasks"]],
                ["selected", "selected"],
            )
            self.assertEqual(
                [task["preflight_status"] for task in report["tasks"]],
                ["unsupported", "unsupported"],
            )
            self.assertTrue(
                all(task["harbor_status"] == "pending" for task in report["tasks"])
            )
            self.assertTrue(
                all(task["instruction_goal"] for task in report["tasks"])
            )
            self.assertTrue(
                all(task["solve_changes"] for task in report["tasks"])
            )
            self.assertTrue(
                all(
                    "plugins/fraudguard/config_validator.go"
                    in task["target_files"]
                    for task in report["tasks"]
                )
            )
            self.assertTrue(
                all(task["native_test_command"].startswith("go test") for task in report["tasks"])
            )

    def test_coverage_delta_is_accurate_and_deterministic(self):
        values = [coverage_delta(42.125, 57.875) for _ in range(10)]
        self.assertEqual(values, [15.75] * 10)
        self.assertIsNone(coverage_delta(None, 57.875))

    def test_configured_python_coverage_json_is_normalized_for_patch_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "src/normalize.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def normalize(value):\n"
                "    return value.strip().upper()\n"
            )
            patch = (
                "diff --git a/src/normalize.py b/src/normalize.py\n"
                "--- a/src/normalize.py\n"
                "+++ b/src/normalize.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def normalize(value):\n"
                "-    return value\n"
                "+    return value.strip().upper()\n"
            )
            report = {
                "totals": {"percent_covered": 80.0},
                "files": {
                    "src/normalize.py": {
                        "executed_lines": [1, 2],
                        "functions": {
                            "normalize": {
                                "start_line": 1,
                                "executed_lines": [1, 2],
                                "missing_lines": [],
                                "summary": {"percent_covered": 100.0},
                            }
                        },
                    }
                },
            }
            result = parse_custom_coverage_report(
                json.dumps(report),
                "coverage.py-json",
                patch,
                temp,
            )
            self.assertEqual(result["total_percent"], 80.0)
            self.assertTrue(
                result["patched_executable_lines"]["all_exercised"]
            )
            self.assertTrue(result["patched_functions"]["all_exercised"])

    def test_go_coverage_reports_changed_lines_and_functions_exercised(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src/normalize.go"
            source.parent.mkdir(parents=True)
            source.write_text(
                "package normalize\n"
                "func Normalize(value string) string {\n"
                '\treturn "normalized"\n'
                "}\n"
            )
            patch = (
                "diff --git a/src/normalize.go b/src/normalize.go\n"
                "--- a/src/normalize.go\n"
                "+++ b/src/normalize.go\n"
                "@@ -1,1 +1,4 @@\n"
                " package normalize\n"
                "+func Normalize(value string) string {\n"
                '+\treturn "normalized"\n'
                "+}\n"
            )
            profile = (
                "mode: set\n"
                "example.invalid/normalize/src/normalize.go:3.2,3.21 1 1\n"
            )
            function_output = (
                "example.invalid/normalize/src/normalize.go:2: Normalize 100.0%\n"
                "total: (statements) 81.25%\n"
            )
            result = analyze_go_patch_coverage(
                patch,
                profile,
                function_output,
                root,
            )
            self.assertEqual(result["total_percent"], 81.25)
            self.assertEqual(
                result["patched_executable_lines"],
                {"covered": 1, "total": 1, "all_exercised": True},
            )
            self.assertEqual(
                result["patched_functions"]["items"],
                [
                    {
                        "file": "src/normalize.go",
                        "name": "Normalize",
                        "coverage_percent": 100.0,
                        "exercised": True,
                    }
                ],
            )

    @unittest.skipUnless(shutil.which("go"), "Go is not installed")
    def test_local_validation_measures_go_coverage_before_and_after_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "go-target")
            (repo / "go.mod").write_text(
                "module example.invalid/coveragefixture\n\ngo 1.20\n"
            )
            (repo / "value.go").write_text(
                "package coveragefixture\n\n"
                "func Value() bool {\n"
                "\treturn false\n"
                "}\n"
            )
            commit_all(repo, "add Go coverage fixture")
            blueprint = root / "go-blueprint"
            (blueprint / "environment").mkdir(parents=True)
            (blueprint / "tests").mkdir()
            (blueprint / "blueprint.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "family": "go-coverage-fixture",
                        "title": "Exercise a patched Go function",
                        "instruction": "instruction.md.template",
                        "reference_patch": "reference.patch.template",
                        "harbor": {
                            "environment_dockerfile": "environment/Dockerfile.template",
                            "difficulty": "easy",
                            "source_excludes": [],
                        },
                        "tests": {
                            "files": [
                                {
                                    "source": "tests/value_test.go.template",
                                    "package_path": "value_test.go",
                                    "target_path": "task_factory_generated_test.go",
                                }
                            ],
                            "command": [
                                "go",
                                "test",
                                "-count=1",
                                "-run",
                                "^(TestGeneratedTaskValue)$",
                                ".",
                            ],
                            "working_directory": ".",
                            "baseline_failure_patterns": [
                                "(?m)^--- FAIL: TestGeneratedTaskValue\\b"
                            ],
                            "reference_pass_pattern": "(?m)^ok\\s+\\S+\\s+[0-9.]+s$",
                        },
                    }
                )
            )
            (blueprint / "instruction.md.template").write_text(
                "Make Value return true.\n"
            )
            (blueprint / "reference.patch.template").write_text(
                "diff --git a/value.go b/value.go\n"
                "--- a/value.go\n"
                "+++ b/value.go\n"
                "@@ -3,3 +3,3 @@\n"
                " func Value() bool {\n"
                "-\treturn false\n"
                "+\treturn true\n"
                " }\n"
            )
            (blueprint / "environment/Dockerfile.template").write_text(
                "FROM golang:1.26.11\nWORKDIR /workspace\n"
            )
            (blueprint / "tests/value_test.go.template").write_text(
                "package coveragefixture\n"
                "import \"testing\"\n"
                "func TestGeneratedTaskValue(t *testing.T) {\n"
                "\tif !Value() { t.Fatal(\"Value should be true\") }\n"
                "}\n"
            )
            package = generate_task(
                4,
                str(repo),
                root / "generated-task",
                blueprint_dir=blueprint,
            )
            result = validate_task(package, str(repo), timeout=120)
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertTrue(
                any(
                    command["argv"][0].endswith("/solution/solve.sh")
                    for command in result["commands"]
                )
            )
            coverage = result["coverage"]
            self.assertIsInstance(
                coverage["baseline"]["total_percent"],
                (int, float),
            )
            self.assertIsInstance(
                coverage["post_patch"]["total_percent"],
                (int, float),
            )
            self.assertEqual(
                coverage["delta_percentage_points"],
                round(
                    coverage["post_patch"]["total_percent"]
                    - coverage["baseline"]["total_percent"],
                    2,
                ),
            )
            self.assertTrue(
                coverage["patched_code_exercised"]["patched_executable_lines"][
                    "all_exercised"
                ]
            )
            self.assertTrue(
                coverage["patched_code_exercised"]["patched_functions"][
                    "all_exercised"
                ]
            )

    def test_configured_native_coverage_records_deterministic_delta(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n"
                "    return value\n\n"
                "def unused_helper(value):\n"
                "    return value\n"
            )
            runner = '''import ast
import io
import json
import sys
import unittest
from pathlib import Path

mode, profile, *rest = sys.argv[1:]
profile_path = Path(profile)
if mode == "run":
    executed = set()
    target = Path("normalize.py").resolve()
    def trace(frame, event, arg):
        if event == "line" and Path(frame.f_code.co_filename).resolve() == target:
            executed.add(frame.f_lineno)
        return trace
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_task_factory.py")
    stream = io.StringIO()
    sys.settrace(trace)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    sys.settrace(None)
    profile_path.write_text(json.dumps({"executed_lines": sorted(executed)}))
    print(stream.getvalue(), end="")
    raise SystemExit(0 if result.wasSuccessful() else 1)

report_path = Path(rest[0])
profile_data = json.loads(profile_path.read_text())
executed = set(profile_data["executed_lines"])
source = Path("normalize.py").read_text()
tree = ast.parse(source)
def executable_lines(nodes):
    return {
        node.lineno
        for parent in nodes
        for node in ast.walk(parent)
        if isinstance(node, ast.stmt)
        and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
statements = executable_lines([tree])
functions = {}
for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        lines = executable_lines(node.body)
        hit = sorted(lines & executed)
        functions[node.name] = {
            "start_line": node.lineno,
            "coverage_percent": 100.0 * len(hit) / len(lines) if lines else 100.0,
            "executed_lines": hit,
        }
percent = 100.0 * len(statements & executed) / len(statements) if statements else 100.0
report_path.write_text(json.dumps({
    "total_percent": percent,
    "files": {
        "normalize.py": {
            "executed_lines": sorted(executed),
            "functions": functions,
        }
    },
}))
'''
            (repo / "coverage_fixture_runner.py").write_text(runner)
            commit_all(repo, "add measurable Python task fixture")
            blueprint = copy_python_blueprint(root / "blueprint")
            config = json.loads((blueprint / "blueprint.json").read_text())
            config["coverage"] = {
                "format": "normalized-json",
                "test_command": [
                    "python3",
                    "coverage_fixture_runner.py",
                    "run",
                    "{coverage_file}",
                ],
                "report_command": [
                    "python3",
                    "coverage_fixture_runner.py",
                    "report",
                    "{coverage_file}",
                    "{report_file}",
                ],
            }
            (blueprint / "blueprint.json").write_text(json.dumps(config))
            (blueprint / "reference.patch.template").write_text(
                "diff --git a/normalize.py b/normalize.py\n"
                "--- a/normalize.py\n"
                "+++ b/normalize.py\n"
                "@@ -1,5 +1,5 @@\n"
                " def normalize_label(value):\n"
                "-    return value\n"
                "+    return \" \".join(value.split()).upper()\n"
                " \n"
                " def unused_helper(value):\n"
                "     return value\n"
            )
            package = generate_task(
                37,
                str(repo),
                root / "generated-task",
                blueprint_dir=blueprint,
            )
            result = validate_task(package, str(repo), timeout=30)
            self.assertEqual(result["status"], "passed", result.get("error"))
            coverage = result["coverage"]
            self.assertEqual(coverage["kind"], "custom")
            self.assertEqual(coverage["baseline"]["total_percent"], 50.0)
            self.assertEqual(coverage["post_patch"]["total_percent"], 50.0)
            self.assertEqual(coverage["delta_percentage_points"], 0.0)
            self.assertTrue(
                coverage["patched_code_exercised"]["patched_executable_lines"][
                    "all_exercised"
                ]
            )
            self.assertTrue(
                coverage["patched_code_exercised"]["patched_functions"][
                    "all_exercised"
                ]
            )

    def test_side_by_side_comparison_includes_coverage_and_flags_clone_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for seed, baseline, post in ((1, 40.0, 55.5), (2, 40.0, 55.5)):
                package = root / f"seed-{seed}"
                package.mkdir()
                (package / "task.json").write_text(
                    json.dumps(
                        {
                            "task_id": f"task-{seed}",
                            "seed": seed,
                            "seed_mode": "auto" if seed == 1 else "selected",
                            "family": "example-family",
                            "scenario": f"case {seed}",
                            "target": {"commit": "a" * 40},
                            "variation": {
                                "family": "example-family",
                                "variant": "normalized-input",
                                "dimensions": ["boundary-case"],
                                "target_symbols": [f"Normalize{seed}"],
                                "signature": f"semantic-profile-{seed}",
                                "structure_signature": "shared-normalized-structure",
                            },
                            "tests": {
                                "expected_baseline_failures": ["TestNormalize"],
                                "files": [
                                    {
                                        "target_path": "src/normalize_test.py",
                                        "package_path": "tests/payload/normalize_test.py",
                                    }
                                ],
                            },
                        }
                    )
                )
                (package / "manifest.json").write_text(
                    json.dumps(
                        {
                            "task_status": "not_validated",
                            "harbor_status": "pending",
                            "validation": {
                                "local_preflight": {
                                    "status": "unsupported",
                                    "coverage": {
                                        "target_files": ["src/normalize.py"],
                                        "baseline": {"total_percent": baseline},
                                        "post_patch": {"total_percent": post},
                                        "delta_percentage_points": post - baseline,
                                        "patched_code_exercised": {
                                            "patched_executable_lines": {
                                                "covered": 2,
                                                "total": 2,
                                                "all_exercised": True,
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    )
                )
                (package / "solution").mkdir()
                (package / "solution/reference.patch").write_text(
                    "+++ b/src/normalize.py\n"
                )
            report = compare_task_packages(
                [root / "seed-1", root / "seed-2"]
            )
            markdown = render_comparison(report)
            self.assertEqual(report["likely_clone_groups"], [["task-1", "task-2"]])
            self.assertIn("40.00%", markdown)
            self.assertIn("55.50%", markdown)
            self.assertIn("+15.50 pp", markdown)
            self.assertIn("lines 2/2", markdown)
            self.assertIn("| 1 | auto |", markdown)
            self.assertIn("| 2 | selected |", markdown)
            self.assertIn("unsupported", markdown)
            self.assertIn("pending", markdown)

    def test_generator_does_not_overwrite_existing_task_files(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_fraudguard_repo(Path(temp) / "target")
            output = Path(temp) / "task"
            output.mkdir()
            (output / "keep.txt").write_text("keep")
            with self.assertRaises(FactoryError):
                generate_task(1, str(repo), output)
            self.assertEqual((output / "keep.txt").read_text(), "keep")

    def test_target_resolution_pins_local_head_without_changing_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_git_repo(Path(temp) / "target")
            before = subprocess.check_output(
                ["git", "-C", str(repo), "status", "--porcelain"], text=True
            )
            target = resolve_target(str(repo))
            after = subprocess.check_output(
                ["git", "-C", str(repo), "status", "--porcelain"], text=True
            )
            self.assertEqual(target.commit, git(repo, "rev-parse", "HEAD"))
            self.assertEqual(before, after)

    def test_repository_urls_with_embedded_credentials_are_rejected(self):
        with self.assertRaises(TargetError):
            validate_source("https://user:password@example.com/org/repo.git")

    def test_expected_failure_detection_requires_named_assertion_failure(self):
        names = ["TestOne", "TestTwo"]
        output = "--- FAIL: TestOne (0.00s)\nFAIL\n"
        self.assertEqual(_expected_failures_seen(output, names), ["TestOne"])
        self.assertEqual(_test_pattern(names), "^(TestOne|TestTwo)$")

    def test_command_output_redacts_common_credential_formats(self):
        output = (
            "Authorization: Bearer abc.def.ghi "
            "token=sk-proj-123456789012345678901234 "
            "https://user:pass@example.invalid/private"
        )
        cleaned = _clean_text(output)
        self.assertNotIn("abc.def.ghi", cleaned)
        self.assertNotIn("sk-proj-", cleaned)
        self.assertNotIn("user:pass", cleaned)

    def test_scanner_detects_python_and_reports_a_native_test_command(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_git_repo(Path(temp) / "target")
            (repo / "utility.py").write_text("def value():\n    return 1\n")
            (repo / "lib.rs").write_text("pub fn value() -> i32 { 1 }\n")
            (repo / "app.ts").write_text("export const value = 1;\n")
            (repo / "contract.sol").write_text("pragma solidity ^0.8.0;\n")
            commit_all(repo, "add Python source")
            report = scan_repository(str(repo))
            self.assertIn("Python", report["detected_languages"])
            self.assertIn("Rust", report["detected_languages"])
            self.assertIn("TypeScript", report["detected_languages"])
            self.assertIn("Solidity", report["detected_languages"])
            self.assertTrue(
                any(
                    item["language"] == "Python"
                    and item["command"] == ["python3", "-m", "unittest", "discover"]
                    for item in report["test_command_candidates"]
                )
            )
            self.assertTrue(report["generation_capabilities"]["language_neutral_blueprints"])

    def test_language_neutral_blueprint_validates_a_python_task_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            blueprint = copy_python_blueprint(root / "blueprint")
            source_status = git(repo, "status", "--porcelain")

            package = generate_task(
                12,
                str(repo),
                root / "generated-task",
                blueprint_dir=blueprint,
            )
            task = json.loads((package / "task.json").read_text())
            self.assertIn("Python", task["detected_languages"])
            payload_path = task["tests"]["files"][0]["package_path"]
            self.assertTrue((package / payload_path).is_file())
            same_seed_package = generate_task(
                12,
                str(repo),
                root / "generated-task-same-seed",
                blueprint_dir=blueprint,
            )
            other_seed_package = generate_task(
                15,
                str(repo),
                root / "generated-task-other-seed",
                blueprint_dir=blueprint,
            )
            self.assertEqual(file_digest_map(package), file_digest_map(same_seed_package))
            self.assertNotEqual(
                (package / "instruction.md").read_text(),
                (other_seed_package / "instruction.md").read_text(),
            )

            result = validate_task(package, str(repo), timeout=30)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["baseline"]["status"], "failed_as_expected")
            self.assertEqual(result["reference"]["status"], "passed")
            self.assertEqual(
                result["network_policy"]["host_network_isolation"],
                "not enforced for local preflight; Harbor task uses no-network runtime",
            )
            self.assertEqual(
                result["network_policy"]["host_filesystem_isolation"],
                "task tests run in a temporary checkout",
            )
            manifest = json.loads((package / "manifest.json").read_text())
            self.assertEqual(manifest["task_status"], "not_validated")
            self.assertEqual(manifest["validation"]["local_preflight"]["status"], "passed")
            self.assertEqual(manifest["validation"]["harbor"]["status"], "not_run")
            self.assertEqual(manifest["validation"]["local_preflight"]["commands"][-1]["argv"], task["tests"]["command"])
            self.assertIn("python3 -m unittest", (package / "run-report.md").read_text())
            self.assertEqual(git(repo, "status", "--porcelain"), source_status)

    def test_language_neutral_blueprint_can_configure_native_coverage_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            blueprint = copy_python_blueprint(root / "blueprint")
            config = json.loads((blueprint / "blueprint.json").read_text())
            config["coverage"] = {
                "format": "coverage.py-json",
                "test_command": [
                    "python3",
                    "-m",
                    "coverage",
                    "run",
                    "--data-file",
                    "{coverage_file}",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_task_factory.py",
                    "-v",
                ],
                "report_command": [
                    "python3",
                    "-m",
                    "coverage",
                    "json",
                    "--data-file",
                    "{coverage_file}",
                    "-o",
                    "{report_file}",
                ],
            }
            (blueprint / "blueprint.json").write_text(json.dumps(config))
            package = generate_task(
                31,
                str(repo),
                root / "generated-task",
                blueprint_dir=blueprint,
            )
            task = json.loads((package / "task.json").read_text())
            self.assertEqual(task["coverage"]["kind"], "custom")
            self.assertEqual(task["coverage"]["format"], "coverage.py-json")
            self.assertIn("{coverage_file}", task["coverage"]["test_command"])
            self.assertIn("{report_file}", task["coverage"]["report_command"])

    def test_reward_wrapper_proves_baseline_zero_and_reference_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            blueprint = copy_python_blueprint(root / "blueprint")
            package = generate_task(
                23,
                str(repo),
                root / "generated-task",
                blueprint_dir=blueprint,
            )
            working_copy = root / "temporary-checkout"
            shutil.copytree(repo, working_copy, ignore=shutil.ignore_patterns(".git"))
            reward_file = root / "logs/verifier/reward.txt"
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(root),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "TASK_PROJECT_ROOT": str(working_copy),
                "TASK_TESTS_DIR": str(package / "tests/payload"),
                "VERIFIER_REWARD_FILE": str(reward_file),
                "TASK_SOLUTION_PATCH": str(package / "solution/reference.patch"),
            }
            reward_file.parent.mkdir(parents=True, exist_ok=True)
            reward_file.write_text("1\n")
            test_script = package / "tests/test.sh"
            wrapper_text = test_script.read_text()
            self.assertLess(
                wrapper_text.index("printf '0\\n' > \"$REWARD_FILE\""),
                wrapper_text.index("python3 -m unittest"),
            )
            baseline = subprocess.run(
                [str(test_script)],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(baseline.returncode, 0)
            self.assertEqual(reward_file.read_text().strip(), "0")
            self.assertIn("FAIL: test_normalizes_spaces_and_case", baseline.stdout)

            solution = subprocess.run(
                [str(package / "solution/solve.sh")],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(solution.returncode, 0, solution.stdout)
            reward_file.unlink()
            reward_file.parent.rmdir()
            reference = subprocess.run(
                [str(test_script)],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(reference.returncode, 0, reference.stdout)
            self.assertTrue(reward_file.is_file())
            self.assertEqual(reward_file.read_text().strip(), "1")
            self.assertEqual(git(repo, "status", "--porcelain"), "")

    def test_harbor_jobs_gate_validity_and_record_agent_atif_when_present(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            package = generate_task(
                24,
                str(repo),
                root / "generated-task",
                blueprint_dir=copy_python_blueprint(root / "blueprint"),
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            create_fake_harbor(fake_bin / "harbor")
            environment = {"PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"}
            with mock_patch.dict(os.environ, environment):
                validation = run_harbor_validation(package, root / "jobs")
                self.assertEqual(validation["status"], "valid")
                self.assertEqual(validation["jobs"]["nop"]["trials"][0]["reward"], 0)
                self.assertEqual(validation["jobs"]["oracle"]["trials"][0]["reward"], 1)

                run = run_agent_benchmark(
                    package,
                    "codex",
                    "example/model",
                    attempts=2,
                    jobs_dir=root / "jobs",
                )
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["observed_pass_rate"], 1)
                self.assertEqual(run["atif_recorded_trials"], 2)
            manifest = json.loads((package / "manifest.json").read_text())
            self.assertEqual(manifest["task_status"], "valid")
            self.assertEqual(len(manifest["agent_runs"]), 1)
            self.assertIn("trajectory.json", manifest["agent_runs"][0]["trials"][0]["atif_trajectory"])

    def test_harbor_validation_does_not_mark_task_valid_when_nop_reward_is_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            package = generate_task(
                25,
                str(repo),
                root / "generated-task",
                blueprint_dir=copy_python_blueprint(root / "blueprint"),
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            create_fake_harbor(fake_bin / "harbor")
            create_fake_harbor(fake_bin / "harbor-nop-passes")
            environment = {"PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"}
            with mock_patch.dict(os.environ, environment):
                validation = run_harbor_validation(
                    package,
                    root / "jobs",
                    harbor_bin="harbor-nop-passes",
                )
            self.assertEqual(validation["status"], "invalid")
            manifest = json.loads((package / "manifest.json").read_text())
            self.assertEqual(manifest["task_status"], "not_validated")

    def test_missing_harbor_cli_leaves_task_unvalidated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            package = generate_task(
                26,
                str(repo),
                root / "generated-task",
                blueprint_dir=copy_python_blueprint(root / "blueprint"),
            )
            result = run_harbor_validation(
                package,
                root / "jobs",
                harbor_bin="factory-harbor-missing-test-command",
            )
            self.assertEqual(result["status"], "unsupported")
            self.assertFalse(result["jobs"]["nop"]["executed"])
            manifest = json.loads((package / "manifest.json").read_text())
            self.assertEqual(manifest["task_status"], "not_validated")

    def test_missing_native_test_runner_is_unsupported_not_a_task_failure(self):
        self.assertTrue(
            _looks_like_environment_failure(
                "go: download go1.27.3 for linux/amd64: toolchain not available",
                1,
            )
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            blueprint = copy_python_blueprint(root / "blueprint")
            config = json.loads((blueprint / "blueprint.json").read_text())
            config["tests"]["command"][0] = "factory-missing-test-runner-should-not-exist"
            (blueprint / "blueprint.json").write_text(json.dumps(config))

            package = generate_task(
                13,
                str(repo),
                root / "generated-task",
                blueprint_dir=blueprint,
            )
            result = validate_task(package, str(repo), timeout=30)
            self.assertEqual(result["status"], "unsupported")
            self.assertEqual(result["baseline"]["status"], "unsupported_test_command")
            self.assertIn("not counted as a task failure", (package / "run-report.md").read_text())

    def test_missing_python_dependency_is_unsupported_not_a_task_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_git_repo(root / "python-target")
            (repo / "normalize.py").write_text(
                "def normalize_label(value):\n    return value\n"
            )
            commit_all(repo, "add Python target")
            blueprint = copy_python_blueprint(root / "blueprint")
            config = json.loads((blueprint / "blueprint.json").read_text())
            config["tests"]["command"] = [
                "python3",
                "-m",
                "factory_missing_dependency_module",
            ]
            (blueprint / "blueprint.json").write_text(json.dumps(config))

            package = generate_task(
                14,
                str(repo),
                root / "generated-task",
                blueprint_dir=blueprint,
            )
            result = validate_task(package, str(repo), timeout=30)
            self.assertEqual(result["status"], "unsupported")
            self.assertEqual(result["baseline"]["status"], "unsupported_environment")
            self.assertIn("not counted as a task failure", (package / "run-report.md").read_text())


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def make_git_repo(repo: Path) -> Path:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "factory@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Factory Test"],
        check=True,
    )
    (repo / "README.md").write_text("fixture\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    return repo


def make_fraudguard_repo(repo: Path) -> Path:
    make_git_repo(repo)
    module = repo / "plugins/fraudguard"
    module.mkdir(parents=True)
    (module / "go.mod").write_text(
        "module example.invalid/fraudguard\n\ngo 1.20\n"
    )
    private_context = repo / ".agents/memory/private-project-context.md"
    private_context.parent.mkdir(parents=True)
    private_context.write_text("This project-only context must not enter task archives.\n")
    commit_all(repo, "add FraudGuard module marker")
    return repo


def commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], check=True)


def copy_python_blueprint(blueprint: Path) -> Path:
    source = Path(__file__).resolve().parents[1] / "examples/python-blueprint"
    shutil.copytree(source, blueprint)
    return blueprint


def create_fake_harbor(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
agent = args[args.index("-a") + 1]
output = Path(args[args.index("-o") + 1])
job_name = args[args.index("--job-name") + 1]
attempts = int(args[args.index("-k") + 1]) if "-k" in args else 1
if agent == "nop":
    reward = "1" if Path(sys.argv[0]).name == "harbor-nop-passes" else "0"
elif agent == "oracle":
    reward = "1"
else:
    reward = "1"
for index in range(attempts):
    trial = output / job_name / f"trial-{index + 1}"
    verifier = trial / "verifier"
    verifier.mkdir(parents=True, exist_ok=True)
    (verifier / "reward.txt").write_text(reward + "\\n")
    (trial / "results.json").write_text(json.dumps({"reward": reward}))
    if agent not in {"nop", "oracle"}:
        agent_logs = trial / "agent"
        agent_logs.mkdir()
        (agent_logs / "trajectory.json").write_text(
            json.dumps({"schema_version": "ATIF-v1.8", "steps": []})
        )
"""
    )
    path.chmod(0o755)


def file_digest_map(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
