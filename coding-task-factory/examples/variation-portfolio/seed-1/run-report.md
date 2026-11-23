# Run report: Reject control characters in exemption IDs

- Task ID: `config-exempt-ids-1`
- Seed: `1`
- Target repository: `https://github.com/sham-cyber/Plugin.git`
- Target commit: `0ca3e119524ae5ad4b5333dc510275546b167b97`
- Task family: `config-exempt-ids`
- Task variant: `embedded-control-character`
- Harbor validation status: **not_validated**

## Variation profile

- Dimensions: control-character-policy, identifier-error-path, error-privacy
- Target symbols: ValidateConfig, ExemptVirtualKeyIDs
- Semantic signature: 12068c6fdd137788405a

## Task package files

- `instruction.md`
- `task.toml`
- `environment/Dockerfile`
- `environment/source.tar.gz`
- `solution/solve.sh`
- `solution/reference.patch`
- `tests/test.sh`
- `tests/payload/plugins/fraudguard/task_factory_generated_test.go`
- `task.json`
- `manifest.json`
- `run-report.md`

## Native verifier and solution commands

- Native test: `go test -count=1 -run '^(TestGeneratedTaskRejectsControlCharactersInExemptIDs)$' .`
- Test working directory: `plugins/fraudguard`
- Harbor reward file: `/logs/verifier/reward.txt`
- Oracle solution: `sh /solution/solve.sh`

## Local coverage comparison

- Modified target files/packages: plugins/fraudguard, plugins/fraudguard/config_validator.go
- Baseline coverage: unavailable
- Post-patch coverage: unavailable
- Coverage delta: unavailable
- Coverage measurement status: unavailable (native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available)
- Coverage is supplementary local evidence; Harbor still grades only `/logs/verifier/reward.txt`.

Harbor's `nop` and `oracle` trials have **not run**. This task is unvalidated and must not be treated as valid.

Run `task-factory validate --task <task-directory>` to collect baseline-fail (`nop`) and reference-pass (`oracle`) evidence in isolated Harbor trials.

Planned Harbor commands (not yet executed):

- `harbor run -p '<task-directory>' -a nop`
- `harbor run -p '<task-directory>' -a oracle`


## Local preflight

- Result: `unsupported`
- Baseline: `unsupported_environment` (exit `1`)
- Reference: `not_run` (exit `not run`)
- Local preflight is diagnostic only; it does not substitute for Harbor `nop` and `oracle` trials.

Executed local preflight commands:

- `go test -coverprofile=/tmp/coding-task-validation-emukb4gp/checkout/.task-factory-coverage/baseline.profile -count=1 -run '^(TestGeneratedTaskRejectsControlCharactersInExemptIDs)$' .`
  - Working directory: `/tmp/coding-task-validation-emukb4gp/checkout/plugins/fraudguard`
  - Exit code: `1`
- Local runtime/dependency evidence was unavailable; this is not counted as a task failure.

**Not validated yet:** Harbor has not proved both required reward outcomes.
