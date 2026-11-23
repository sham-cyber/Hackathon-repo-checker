# Run report: Reject ambiguous runtime configuration JSON

- Task ID: `duplicate-runtime-json-keys-5`
- Seed: `5`
- Target repository: `https://github.com/sham-cyber/Plugin.git`
- Target commit: `0ca3e119524ae5ad4b5333dc510275546b167b97`
- Task family: `duplicate-runtime-json-keys`
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
- Validation time (UTC): `2026-11-21T16:38:24.220667+00:00`

## Executed commands

- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git init -q /tmp/coding-task-validation-58k_1fkk/checkout`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/sample-task`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-58k_1fkk/checkout remote add origin /tmp/plugin-inspect.W5Lhso/target`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/sample-task`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-58k_1fkk/checkout fetch --no-tags --depth 1 origin 0ca3e119524ae5ad4b5333dc510275546b167b97`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/sample-task`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-58k_1fkk/checkout checkout --detach FETCH_HEAD`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/sample-task`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-58k_1fkk/checkout rev-parse HEAD`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/sample-task`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null go test -count=1 -run '^(TestGeneratedTaskRejectsDuplicateRuntimeJSONKeys)$' .`
  - Working directory: `/tmp/coding-task-validation-58k_1fkk/checkout/plugins/fraudguard`
  - Exit code: `1`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-58k_1fkk/checkout apply --check /home/runner/workspace/coding-task-factory/examples/sample-task/reference.patch`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/sample-task`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null git -C /tmp/coding-task-validation-58k_1fkk/checkout apply /home/runner/workspace/coding-task-factory/examples/sample-task/reference.patch`
  - Working directory: `/home/runner/workspace/coding-task-factory/examples/sample-task`
  - Exit code: `0`
- `CARGO_NET_OFFLINE=true GOFLAGS=-mod=readonly GOMODCACHE=/home/runner/go/pkg/mod GOPROXY=off GOSUMDB=sum.golang.org GOTOOLCHAIN=auto PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INDEX=1 PYTHONNOUSERSITE=1 YARN_ENABLE_NETWORK=0 npm_config_audit=false npm_config_fund=false npm_config_globalconfig=/dev/null npm_config_offline=true npm_config_userconfig=/dev/null go test -count=1 -run '^(TestGeneratedTaskRejectsDuplicateRuntimeJSONKeys)$' .`
  - Working directory: `/tmp/coding-task-validation-58k_1fkk/checkout/plugins/fraudguard`
  - Exit code: `0`

## Baseline output

```text
--- FAIL: TestGeneratedTaskRejectsDuplicateRuntimeJSONKeys (0.00s)
    task_factory_generated_test.go:19: duplicate config field was not rejected explicitly: <nil>
FAIL
FAIL	github.com/maximhq/bifrost/plugins/fraudguard	0.062s
FAIL

```

## Reference output

```text
ok  	github.com/maximhq/bifrost/plugins/fraudguard	0.062s

```
