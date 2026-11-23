# Accept only documented boolean environment values

## Context

This is a feature-development task for the FraudGuard/Bifrost Plugin repository.
Target commit: `0ca3e119524ae5ad4b5333dc510275546b167b97`. Generated scenario: Selected override: FRAUDGUARD_ENABLE_EXPIRED_KEY_SIGNAL.

## Requirements

Make `FRAUDGUARD_ENABLE_EXPIRED_KEY_SIGNAL` accept only `true` or `false`, ignoring letter case and surrounding whitespace. Reject shorthand aliases such as `1`, `0`, `t`, and `yes`, while keeping the existing stable error message and not echoing the supplied value.

## Acceptance criteria

1. Implement the behavior in the existing FraudGuard Go module without changing
   unrelated behavior.
2. Keep errors stable and avoid including configuration values or identifiers
   in error text.
3. The generated test in `plugins/fraudguard/task_factory_generated_test.go`
   passes, and the existing package tests continue to compile.
4. Preserve the module's existing public APIs unless the requirement above
   makes a private helper necessary.

## Validation

Harbor's `nop` trial must leave the verifier reward at 0, and its `oracle` trial
must apply `solution/solve.sh` and produce reward 1. Run both with the factory's
`validate` command. A generated task is not valid until these Harbor trials have
actually run and produced the required rewards. Do not edit the target repository.
