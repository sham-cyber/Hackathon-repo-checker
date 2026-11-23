# Reject escaped and array-nested duplicate JSON keys

## Context

This is a feature-development task for the FraudGuard/Bifrost Plugin repository.
Target commit: `0ca3e119524ae5ad4b5333dc510275546b167b97`. Generated scenario: Escaped key equivalence and array-contained object; threshold sample 63.

## Requirements

Reject duplicate JSON object keys before runtime config decoding, including escaped spellings that decode to the same key and duplicate keys inside objects nested in arrays. Keep the error stable and avoid including config values.

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
