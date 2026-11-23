#!/bin/sh
set -eu
PROJECT_ROOT="${TASK_PROJECT_ROOT:-/workspace}"
PATCH_FILE="${TASK_SOLUTION_PATCH:-/solution/reference.patch}"
cd "$PROJECT_ROOT"
git apply "$PATCH_FILE"
