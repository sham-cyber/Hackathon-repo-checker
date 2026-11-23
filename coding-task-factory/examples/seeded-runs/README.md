# Historical seeded local checks

These records were produced before the project switched to Harbor task packages.
They show deterministic task-family variation and local baseline-fail /
reference-pass checks at target commit
`0ca3e119524ae5ad4b5333dc510275546b167b97`.

| Seed | Task family | Local baseline | Local reference | Run record |
|---:|---|---|---|---|
| 0 | `strict-env-booleans` | Expected test failed | Passed | [`seed-0`](seed-0/run-report.md) |
| 1 | `config-exempt-ids` | Expected test failed | Passed | [`seed-1`](seed-1/run-report.md) |
| 5 | `duplicate-runtime-json-keys` | Expected test failed | Passed | [`../sample-task/run-report.md`](../sample-task/run-report.md) |

These are not Harbor `nop`/`oracle` trials and are not Harbor-valid benchmark
packages. Current export examples are in `../harbor-runs/`; each remains
`not_validated` until Harbor produces the required reward evidence.
