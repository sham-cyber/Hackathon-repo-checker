# Reject duplicate exemption identifiers

## Context

This is a feature-development task for the FraudGuard/Bifrost Plugin repository.
Target commit: `0ca3e119524ae5ad4b5333dc510275546b167b97`. Generated scenario: Duplicate ID sample: agent-2033-1.

## Requirements

Update ValidateConfig so exemption IDs remain valid when distinct, but duplicates are rejected after trimming surrounding whitespace. Keep the existing entry-count and byte-length limits. Return a stable error that does not include the ID value.

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
