# Run report: Reject duplicate exemption identifiers

- Task ID: `config-exempt-ids-1`
- Seed: `1`
- Target repository: `https://github.com/sham-cyber/Plugin.git`
- Target commit: `0ca3e119524ae5ad4b5333dc510275546b167b97`
- Task family: `config-exempt-ids`
- Status: **local preflight passed; Harbor not validated**

> Historical direct-local-run record only. Harbor `nop` and `oracle` trials
> have not run; this package is not a current Harbor export and is not valid
> for a Harbor benchmark.

## Task package files

- `instruction.md`
- `reference.patch`
- `plugins/fraudguard/task_factory_generated_test.go`
- `task.json`
- `manifest.json`
- `run-report.md`

- Baseline tests failed as expected: **failed_as_expected**
- Reference tests passed: **passed**
- Isolation: `fresh temporary Git checkout; not an OS-level filesystem or network sandbox`
- Factory model/API calls: **none**
- Common package-manager offline flags: **enabled**
- Host network isolation: **not enforced**
- Host filesystem isolation: **not enforced**
- Validation time (UTC): `2026-11-21T16:43:46.484073+00:00`

## Executed commands

- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git init -q /tmp/coding-task-validation-vz5xpyd9/checkout`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-vz5xpyd9/checkout remote add origin /tmp/plugin-inspect.W5Lhso/target`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-vz5xpyd9/checkout fetch --no-tags --depth 1 origin 0ca3e119524ae5ad4b5333dc510275546b167b97`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-vz5xpyd9/checkout checkout --detach FETCH_HEAD`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-vz5xpyd9/checkout rev-parse HEAD`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null go test -count=1 -run '^(TestGeneratedTaskRejectsTrimmedDuplicateExemptIDs)$' .`
  - Working directory: `/tmp/coding-task-validation-vz5xpyd9/checkout/plugins/fraudguard`
  - Exit code: `1`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-vz5xpyd9/checkout apply --check /home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1/reference.patch`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-vz5xpyd9/checkout apply /home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1/reference.patch`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/seeded-runs/seed-1`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null go test -count=1 -run '^(TestGeneratedTaskRejectsTrimmedDuplicateExemptIDs)$' .`
  - Working directory: `/tmp/coding-task-validation-vz5xpyd9/checkout/plugins/fraudguard`
  - Exit code: `0`

## Baseline output

```text
--- FAIL: TestGeneratedTaskRejectsTrimmedDuplicateExemptIDs (0.00s)
    task_factory_generated_test.go:13: duplicate exemption IDs were accepted
FAIL
FAIL	github.com/maximhq/bifrost/plugins/fraudguard	0.124s
FAIL

```

## Reference output

```text
ok  	github.com/maximhq/bifrost/plugins/fraudguard	0.057s

```
