# Seeded task variation comparison

This report compares task behavior profiles, target areas, and generated test assertions. The clone check normalizes target-symbol names and sample values, so changing only an identifier or literal does not count as meaningful variation.

| Seed | Family / variant | Variation dimensions | Modified targets / symbols | Test assertions | Baseline coverage | Post-patch coverage | Delta | Patched code exercised | Coverage status | Scenario | Harbor |
|---:|---|---|---|---|---:|---:|---:|---|---|---|---|
| 0 | strict-env-booleans / reject-parsebool-aliases | accepted-value-contract, alias-rejection, field-specific-assertion | plugins/fraudguard/config_validator.go; FRAUDGUARD_ENABLE_EXPIRED_KEY_SIGNAL, EnableExpiredKeySignal, configFromLookup | TestGeneratedTaskAcceptsOnlyDocumentedBooleanWords | n/a | n/a | n/a | not measured | unsupported: native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available | Selected override: FRAUDGUARD_ENABLE_EXPIRED_KEY_SIGNAL | not_validated |
| 1 | config-exempt-ids / embedded-control-character | control-character-policy, identifier-error-path, error-privacy | plugins/fraudguard/config_validator.go; ValidateConfig, ExemptVirtualKeyIDs | TestGeneratedTaskRejectsControlCharactersInExemptIDs | n/a | n/a | n/a | not measured | unsupported: native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available | Embedded NUL in an otherwise valid identifier | not_validated |
| 2 | config-exempt-ids / trim-equivalent-duplicate | trim-normalization, collision-detection, error-privacy | plugins/fraudguard/config_validator.go; ValidateConfig, ExemptVirtualKeyIDs | TestGeneratedTaskRejectsTrimmedDuplicateExemptIDs | n/a | n/a | n/a | not measured | unsupported: native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available | Duplicate ID sample: agent-2500-2 | not_validated |
| 5 | duplicate-runtime-json-keys / escaped-key-and-array-object | escaped-key-equivalence, array-nested-object, recursive-json-scan | plugins/fraudguard/config_loader.go; decodeRuntimeConfig, rejectDuplicateJSONKeys | TestGeneratedTaskRejectsEscapedEquivalentJSONKeys, TestGeneratedTaskRejectsArrayNestedJSONDuplicates | n/a | n/a | n/a | not measured | unsupported: native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available | Escaped key equivalence and array-contained object; threshold sample 63 | not_validated |
| 7 | strict-env-booleans / unset-versus-empty-override | presence-boundary, empty-input, default-preservation, error-privacy | plugins/fraudguard/config_validator.go; FRAUDGUARD_ENABLE_PROMPT_LENGTH_SIGNAL, EnablePromptLengthSignal, configFromLookup | TestGeneratedTaskDistinguishesUnsetAndInvalidBooleanOverrides | n/a | n/a | n/a | not measured | unsupported: native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available | Presence boundary for FRAUDGUARD_ENABLE_PROMPT_LENGTH_SIGNAL | not_validated |
| 19 | duplicate-runtime-json-keys / top-level-and-nested-object | top-level-collision, nested-object-collision, recursive-json-scan | plugins/fraudguard/config_loader.go; decodeRuntimeConfig, rejectDuplicateJSONKeys | TestGeneratedTaskRejectsDuplicateRuntimeJSONKeys | n/a | n/a | n/a | not measured | unsupported: native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available | Conflicting threshold sample: 31 | not_validated |

## Portfolio summary

- Tasks with variation metadata: 6 of 6
- Distinct normalized task structures: 6
- Likely clone groups: 0
- Tasks with baseline and post-patch coverage: 0 of 6
- Coverage unavailable: native test environment unavailable: go: download go1.27.3 for linux/amd64: toolchain not available
- No repeated normalized task structures detected.

A distinct profile is evidence of variation in the authored recipe, not proof that a coding task is valid. Harbor validity still requires real `nop` reward 0 and `oracle` reward 1 trials.
