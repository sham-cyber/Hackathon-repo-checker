# Coding Task Factory

Authors: [Muhammad Saad Cheema](https://github.com/saadcheema-6242) and [Sham Ratan Mohite](https://github.com/sham-cyber)

License: Apache-2.0

A small, language-neutral pipeline for producing feature-development coding
tasks for the Innodata Frontier AI Hackathon 2026, Track 1. The selected
FraudGuard/Bifrost Plugin repository is the first target; it is never edited by
the factory. The bundled seeded task families are Go examples, while a
language-specific blueprint can package a task for any repository language.

The factory and its documentation are licensed under Apache-2.0. Embedded
Plugin source snapshots retain their own Apache-2.0 license in the archive.

## What each generated task contains

Generated directories use Harbor's task layout:

```text
task/
├── task.toml
├── instruction.md
├── environment/
│   ├── Dockerfile
│   └── source.tar.gz
├── solution/
│   ├── solve.sh
│   └── reference.patch
├── tests/
│   ├── test.sh
│   └── payload/...
├── task.json
├── manifest.json
└── run-report.md
```

Every package is checked before publication for Harbor's five required files:
`task.toml`, `instruction.md`, `environment/Dockerfile`, executable
`solution/solve.sh`, and executable `tests/test.sh`. Both scripts are LF-only.
The verifier wrapper is checked for `/logs/verifier` creation, an initial
`reward.txt` value of `0`, and a `1` write only on native-test success.

The source archive is built from the pinned Git commit, so Harbor runs do not
need to clone the target. The manifest records the seed, repository, commit,
tree, source exclusions, generated file hashes, exact Harbor commands, job
directories, trial rewards, and ATIF trajectory paths when available.

`tests/test.sh` creates `/logs/verifier`, resets `reward.txt` to `0`, copies
the task's native tests into the target checkout, and runs the declared native
test command. It writes `1` only when that command succeeds; every failure path
leaves or restores `0`. Harbor grades the reward file, not the shell exit code.
The reference implementation is applied by `solution/solve.sh`.

Generation is deterministic for the same seed, blueprint, and target commit.
It makes no model or API calls and does not write to the target repository.
Generated tasks remain `not_validated` until Harbor `nop` and `oracle` trials
produce the required rewards.

## Selected and automatic seed modes

Selected mode requires an explicit integer and preserves exact reproducibility:

```sh
python3 -m task_factory generate \
  --target /path/to/Plugin \
  --seed-mode selected --seed 42 \
  --out ./runs/manual-42 \
  --log ./runs/seed_log.jsonl
```

When `--seed` is given without `--seed-mode`, selected mode is used. `--seed-mode
selected` without `--seed` is an error.

Auto mode derives a 256-bit integer seed from the pinned commit and, when
present, the SHA-256 of an optional patch file or tracked working-tree diff. It
generates the package, runs isolated local preflight and coverage when available,
then appends a JSON record to `runs/seed_log.jsonl`:

```sh
python3 -m task_factory generate \
  --target /path/to/Plugin --auto-seed \
  --out ./runs/auto-current \
  --log ./runs/seed_log.jsonl
```

`--seed-mode auto` is equivalent to `--auto-seed`. `watch` polls a local
checkout and processes each new commit or tracked diff once; it runs local
preflight but never starts Harbor or model-agent jobs:

```sh
# Process only the current state once:
python3 -m task_factory watch --target /path/to/Plugin --once

# Keep watching until interrupted:
python3 -m task_factory watch \
  --target /path/to/Plugin \
  --out-root ./runs/auto-tasks \
  --log ./runs/seed_log.jsonl \
  --interval 5
```

The JSONL record stores timestamp, seed mode/value, commit, patch digest,
generated task family/targets, baseline and post-patch coverage, delta, local
validation status, and `harbor_status: pending`. A later explicit `validate`
command appends the real Harbor result; an explicit `agent-run` appends its
trial/ATIF evidence. Unsupported local runtimes leave coverage unavailable and
do not imply task failure.

The factory archives the commit named in the task. A working-tree or supplied
patch is used as an auto-seed identity and its digest is logged; its contents
are not copied into the source snapshot. Commit changes that should be part of
the task snapshot before processing. The watcher detects tracked staged and
unstaged changes; use `--patch-file` with `generate --auto-seed` for an external
patch. Patch contents are never written to the run log.

## Setup

Requirements:

- Python 3.10 or newer
- Git
- Docker for Harbor's local task environment
- Harbor for task validation and optional agent trials

Install Harbor outside this project when you are ready to run the task:

```sh
uv tool install harbor
docker info
```

The factory itself uses only Python's standard library. No API credentials are
needed for generation, local preflight, Harbor `nop`, or Harbor `oracle`.
Real model-agent trials are opt-in and use Harbor's configured provider
credentials; the factory does not write credential values to task files,
manifests, or reports.

## Inspect a repository

`scan` identifies source languages, project manifests, and likely native test
commands. It does not pretend to generate a valid task automatically for every
language. A blueprint must provide a real implementation patch, native tests,
their command, and a Dockerfile that supplies the runtime and dependencies.

```sh
python3 -m task_factory scan --target /path/to/repository
python3 -m task_factory scan --target /path/to/repository --format json
```

## Generate a task

The bundled task catalog targets the FraudGuard Go module:

```sh
python3 -m task_factory generate \
  --target /path/to/Plugin \
  --seed 42 \
  --out ./runs/task-42
```

For another codebase or language, provide a blueprint directory. See
`examples/python-blueprint/` for the full contract:

```sh
python3 -m task_factory generate \
  --target /path/to/any-repository \
  --seed 42 \
  --blueprint /path/to/task-blueprint \
  --out ./runs/task-42
```

The blueprint supplies the task instruction, reference patch, test files,
native command, working directory, failure/success evidence patterns, and a
Harbor Dockerfile template with the runtime, dependencies, and Git (the
reference script applies a patch). That keeps language support open-ended
without pretending the factory can invent correct tests for an unknown
codebase.
Template tokens such as `{{SEED}}`, `{{TARGET_COMMIT}}`, and `{{TASK_ID}}` are
expanded deterministically.

## Generate a diverse portfolio

The bundled recipes declare semantic variation profiles: task family, variant,
edge-case dimensions, and target symbols. `portfolio` searches forward from a
seed and selects the earliest seeds with unique profiles, so a batch does not
count changed sample IDs or numbers as meaningful novelty.

```sh
python3 -m task_factory portfolio \
  --target /path/to/Plugin \
  --seed-start 0 \
  --count 6 \
  --out ./runs/portfolio
```

The portfolio includes each Harbor task package, `portfolio.json`, and a
side-by-side `variation-comparison.md`. The selection is deterministic for the
same catalog, seed start, and target. If the requested count exceeds the
catalog's distinct profiles within `--search-limit`, generation stops instead
of filling the batch with clones.

To compare an existing set of task packages:

```sh
python3 -m task_factory compare \
  --tasks ./runs/task-a ./runs/task-b ./runs/task-c \
  --out ./runs/variation-comparison.md
```

To generate and compare selected seeds in one command:

```sh
python3 -m task_factory compare \
  --seeds 0 1 42 \
  --target /path/to/Plugin \
  --out-root ./runs/seed-comparison \
  --out ./runs/seed-comparison.md \
  --json-out ./runs/seed-comparison.json
```

This generates each task and runs only local preflight/coverage. It never starts
Harbor or a model agent. The output root must be new or empty. Use `--tasks` to
compare already-generated packages, including auto-seeded ones.

The comparison normalizes sample values and target-symbol names, then flags
matching task structures for the same target commit as likely clones. It also
displays each seed and mode, family, target files/modules, the instruction goal,
the oracle script's patch behavior, native test command, preflight and coverage
states, coverage deltas, and Harbor status. Unsupported toolchains remain
`unsupported`; Harbor remains `pending` until real trials are recorded.

For the bundled FraudGuard recipes, `release-assets/`, `.conversation/`, and
`.agents/` are omitted from the source archive. These contain release
archives, conversation attachments, and project-agent context rather than code
needed by the task. The exclusions and source tree hash are recorded in the
task metadata. Other blueprints include all tracked target files by default and
can declare explicit relative `source_excludes`.

The ready-to-import three-family package set is in `harbor-export/`. Its task
archives omit `.agents/` context, and all three remain unvalidated until real
Harbor `nop` and `oracle` trials record the required rewards.

Generation requires a local Git checkout and archives the recorded commit, not
the checkout's uncommitted changes. Output directories must be new or empty;
non-empty task packages are never overwritten.

## Validate with Harbor

Run Harbor's no-op baseline and Oracle reference solution:

```sh
python3 -m task_factory validate \
  --task ./runs/task-42 \
  --jobs-dir ./runs/harbor-jobs
```

This invokes `harbor run -a nop` and `harbor run -a oracle` in separate jobs
and fresh trials. A task is marked `valid` only when every `nop` trial rewards
`0` and every Oracle trial rewards `1`. The wrapper records the exact commands,
job directories, trial rewards, and result paths in `manifest.json` and
`run-report.md`.

If Harbor is unavailable, Docker cannot start, a reward file is missing, or the
Oracle reward is not `1`, the task stays unvalidated. An Oracle reward of `0`
is reported as inconclusive until trial logs establish whether the reference
implementation or the language environment is at fault. Missing runtimes or
dependencies are not silently presented as a valid task or automatically
blamed on the task author.

An optional local diagnostic runs the embedded native test command against a
temporary extraction of the source snapshot:

```sh
python3 -m task_factory preflight --task ./runs/task-42
```

Preflight can identify missing local test runners or dependencies, but it is
not a substitute for Harbor trials and never marks a task valid. It uses offline
package-manager flags and does not pass caller credentials to test commands.
It is not an OS-level sandbox; only validate repositories and tests you trust.

For Go tasks, preflight adds `-coverprofile` to the same native test command and
uses `go tool cover -func` before and after applying the reference patch. The
manifest and run report include total coverage, percentage-point delta, changed
files/packages, and whether added executable lines and their enclosing
functions were exercised. Coverage is supplementary local evidence: it does not
change `tests/test.sh`, Harbor's 0/1 reward file, or task-validity rules.

Other languages can configure native instrumentation in `blueprint.json`:

```json
{
  "coverage": {
    "format": "coverage.py-json",
    "test_command": [
      "python3", "-m", "coverage", "run",
      "--data-file", "{coverage_file}",
      "-m", "unittest", "discover"
    ],
    "report_command": [
      "python3", "-m", "coverage", "json",
      "--data-file", "{coverage_file}",
      "-o", "{report_file}"
    ]
  }
}
```

The configured test command must run the same native suite as `tests.command`.
For other tooling, use `format: "normalized-json"` and have `report_command`
write JSON containing `total_percent` and per-file `executed_lines`; optional
function entries can include `start_line` and `coverage_percent`. If no native
coverage adapter is detected or configured, the report says coverage is
unavailable rather than inferring a value.

The generated task sets Harbor's runtime `network_mode` to `no-network`.
Docker may need to pull the base image and download dependencies while building
the image. To run completely offline, cache or prebuild that image and all
dependencies first; subsequent task trials do not need outbound network access.

## Optional coding-agent benchmark

Agent/model runs never happen during generation or validation. To explicitly
run trials after the task is Harbor-valid:

```sh
python3 -m task_factory agent-run \
  --task ./runs/task-42 \
  --agent codex \
  --model openai/model-name \
  --attempts 5 \
  --jobs-dir ./runs/harbor-jobs
```

The command requires both `--agent` and `--model`, records trial/job metadata
and rewards, and records `agent/trajectory.json` when that agent emits ATIF.
ATIF availability depends on the selected Harbor agent. No API key belongs in
the command line or task files; configure credentials through Harbor's
supported secret flow.

## Examples and demo

`examples/variation-portfolio/` contains six packages selected from seeds
`0, 1, 2, 5, 7, 19`. They cover six normalized task structures across the three
families, with a side-by-side comparison report. Local coverage is `n/a` in
these examples because this workspace lacks the target's Go 1.27.3 toolchain;
the preflight reports that as unsupported rather than as a task failure. Harbor
`nop` and `oracle` have not run, so the packages remain **not validated**.

`examples/harbor-runs/` contains the earlier three-family export examples and
demonstrates the standard Harbor directory layout.

The Python blueprint unit test executes the actual generated `tests/test.sh`
on a temporary checkout: the baseline produces reward `0`, the reference
solution is applied, and the same native test command then produces reward
`1`. See [`examples/reward-wrapper-demo.md`](examples/reward-wrapper-demo.md)
for the concise result. This proves the wrapper and blueprint path locally; it
is not represented as a Harbor trial.

Earlier `examples/sample-task/` and `examples/seeded-runs/` directories are
historical direct-local-run records from before Harbor export was added. Their
results are not Harbor `nop`/`oracle` evidence; use `examples/harbor-runs/` for
current task packages.

## Factory tests

```sh
python3 -m unittest discover -s tests -v
```

The tests cover deterministic generation, language-neutral Python packaging,
the emitted Harbor layout, reward-file reset/pass/fail behavior, Harbor validity
gating, and optional ATIF recording. They do not require Harbor or Docker.

## Current task families

- `config-exempt-ids`: reject duplicate exemption IDs after trimming whitespace
- `strict-env-booleans`: accept only case-insensitive `true` / `false` values
- `duplicate-runtime-json-keys`: reject ambiguous duplicate JSON object keys
  before applying runtime configuration

The built-in catalog is deliberately small. New language or repository support
is added as a concrete blueprint with a working task-native test command and a
Docker environment—not as a language-name claim.

Harbor format references: [task layout](https://docs.harborframework.com/tasks/overview),
[task configuration](https://docs.harborframework.com/tasks/configuration),
[verifier rewards](https://docs.harborframework.com/tasks/verifier),
[Oracle solutions](https://docs.harborframework.com/tasks/solution),
[jobs](https://docs.harborframework.com/jobs/run-a-job), and
[ATIF trajectories](https://docs.harborframework.com/agents/atif).
