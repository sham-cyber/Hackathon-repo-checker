# Reject control characters in exemption IDs

## Context

This is a feature-development task for the FraudGuard/Bifrost Plugin repository.
Target commit: `0ca3e119524ae5ad4b5333dc510275546b167b97`. Generated scenario: Embedded NUL in an otherwise valid identifier.

## Requirements

Update ValidateConfig to reject exemption IDs containing Unicode control characters after trimming. Keep ordinary IDs and the existing entry-count and byte-length limits valid. Return a stable error without including the ID value.

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
