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

The factory runs the generated test against the unmodified target first, then
applies `reference.patch` in a separate temporary checkout and reruns it. The
task is valid only if the baseline test fails for its assertion and the
reference test run passes. Do not edit the target repository.
