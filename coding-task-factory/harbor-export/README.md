# Harbor export

This folder contains three ready-to-import Harbor task packages, one from each
built-in task family. Each `seed-*` directory is a complete package; open the
directory itself in Harbor.

| Package | Task family | Goal | Local preflight | Harbor status |
| --- | --- | --- | --- | --- |
| `seed-0` | `strict-env-booleans` | Accept only documented true/false environment values | Unsupported: required Go toolchain unavailable | Pending |
| `seed-1` | `config-exempt-ids` | Reject duplicate exemption IDs after whitespace trimming | Unsupported: required Go toolchain unavailable | Pending |
| `seed-5` | `duplicate-runtime-json-keys` | Reject ambiguous duplicate JSON keys in runtime configuration | Unsupported: required Go toolchain unavailable | Pending |

All three packages use the pinned Plugin commit
`0ca3e119524ae5ad4b5333dc510275546b167b97`. The embedded source snapshots omit
`.agents/` project-agent context; the original target license remains in each
snapshot.

The required Harbor files are present in every package:

- `task.toml`
- `instruction.md`
- `environment/Dockerfile`
- executable `solution/solve.sh`
- executable `tests/test.sh`

The test wrapper resets `/logs/verifier/reward.txt` to `0` before running the
native test command, and writes `1` only when that command succeeds. Harbor
must prove both outcomes before a task is considered valid: `nop` must reward
`0`, and `oracle` must reward `1`. These packages have **not** had Harbor
trials run, so keep their status pending until those results are recorded.

From the `coding-task-factory` directory, run a task's real Harbor validation
and save the job logs with:

```sh
python3 -m task_factory validate \
  --task ./harbor-export/seed-0 \
  --jobs-dir ./runs/harbor-jobs
```

Repeat with `seed-1` and `seed-5`. This performs only Harbor's `nop` and
`oracle` checks; real model-agent trials remain a separate, explicit command.
