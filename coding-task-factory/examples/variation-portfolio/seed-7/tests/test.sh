#!/bin/sh
# Harbor grades /logs/verifier/reward.txt; the exit code is diagnostic only.
set +e
REWARD_FILE="${VERIFIER_REWARD_FILE:-/logs/verifier/reward.txt}"
PROJECT_ROOT="${TASK_PROJECT_ROOT:-/workspace}"
TESTS_DIR="${TASK_TESTS_DIR:-/tests/payload}"
mkdir -p "$(dirname "$REWARD_FILE")" || exit 1
printf '0\n' > "$REWARD_FILE" || exit 1
mkdir -p "$PROJECT_ROOT"/plugins/fraudguard || exit 1
cp "$TESTS_DIR"/plugins/fraudguard/task_factory_generated_test.go "$PROJECT_ROOT"/plugins/fraudguard/task_factory_generated_test.go || exit 1
cd "$PROJECT_ROOT"/plugins/fraudguard || exit 1
go test -count=1 -run '^(TestGeneratedTaskDistinguishesUnsetAndInvalidBooleanOverrides)$' .
native_status=$?
if [ "$native_status" -eq 0 ]; then
  printf '1\n' > "$REWARD_FILE" || { printf '0\n' > "$REWARD_FILE" 2>/dev/null; exit 1; }
else
  printf '0\n' > "$REWARD_FILE" || exit 1
fi
exit "$native_status"
