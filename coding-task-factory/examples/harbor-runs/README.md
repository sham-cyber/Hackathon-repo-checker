# Harbor export examples

These are the first-pass Harbor exports. For the expanded novelty-aware
portfolio, per-task variation profiles, clone screening, and side-by-side
coverage columns, see `../variation-portfolio/`.

These packages pin FraudGuard/Bifrost Plugin commit
`0ca3e119524ae5ad4b5333dc510275546b167b97`.

| Seed | Generated family | Harbor state |
|---:|---|---|
| 0 | `strict-env-booleans` | Not validated; `nop` / `oracle` not run |
| 1 | `config-exempt-ids` | Not validated; `nop` / `oracle` not run |
| 5 | `duplicate-runtime-json-keys` | Not validated; `nop` / `oracle` not run |

Each directory is a complete Harbor export with the pinned source archive,
task-specific test payload, reward wrapper, and oracle solution. The Harbor CLI
is not installed in this workspace, so these packages are
intentionally **not** marked valid. Run `task-factory validate --task
<directory>` after installing Harbor to collect real reward evidence.
