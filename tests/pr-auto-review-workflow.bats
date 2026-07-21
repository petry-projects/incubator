#!/usr/bin/env bats
# Regression guard for .github/workflows/pr-auto-review.yml.
#
# The file shipped from repo-template with a placeholder TODO instructing the
# adopter to replace "CI" in `workflow_run.workflows` with the repo's own CI
# workflow name(s) — flagged by SonarCloud githubactions:S1135 (issue #53). This
# repo's CI workflow is named exactly `CI` (.github/workflows/ci.yml), so the
# placeholder value was already correct; the TODO is resolved, not deferred.
# These tests pin that resolution: no unresolved task marker remains, and the
# watched workflow list still matches the real CI workflow name.

PR_YML="${BATS_TEST_DIRNAME}/../.github/workflows/pr-auto-review.yml"
CI_YML="${BATS_TEST_DIRNAME}/../.github/workflows/ci.yml"

@test "pr-auto-review.yml exists" {
  [ -f "$PR_YML" ]
}

@test "no unresolved TODO/FIXME task marker remains (githubactions:S1135)" {
  # A resolved comment may still mention CI by name; only bare TODO/FIXME task
  # markers reintroduce the finding.
  run grep -nE '(^|[^[:alnum:]])(TODO|FIXME)([^[:alnum:]]|$)' "$PR_YML"
  [ "$status" -ne 0 ]
}

@test "workflow_run watches this repo's CI workflow name" {
  # The value must match the actual CI workflow's `name:` so workflow_run fires.
  grep -qE '^    workflows: \["CI"\]$' "$PR_YML"
}

@test "the watched name matches the CI workflow's declared name" {
  # Guard against a rename of the CI workflow silently breaking the trigger.
  ci_name="$(grep -E '^name: ' "$CI_YML" | head -1 | sed -E 's/^name: //')"
  [ "$ci_name" = "CI" ]
}
