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
  [ -f "$PR_YML" ]
  run grep -nE '(^|[^[:alnum:]])(TODO|FIXME)([^[:alnum:]]|$)' "$PR_YML"
  # Exit 1 means no matches (pass); exit 2 means grep error (e.g. missing file),
  # which would also satisfy -ne 0 and mask regressions — check for 1 exactly.
  [ "$status" -eq 1 ]
}

@test "workflow_run watches this repo's CI workflow name" {
  # The value must match the actual CI workflow's `name:` so workflow_run fires.
  # Scope the search to the on: block to avoid spurious matches elsewhere in the file.
  # 'next' skips past the on: line itself so /^[^[:space:]]/ doesn't self-terminate.
  awk '/^on:/{f=1; next} f && /^[^[:space:]]/{exit} f' "$PR_YML" | grep -qE 'workflows: \["CI"\]'
}

@test "the watched name matches the CI workflow's declared name" {
  # Guard against a rename of the CI workflow silently breaking the trigger.
  ci_name="$(grep -E '^name: ' "$CI_YML" | head -1 | sed -E 's/^name: //')"
  [ "$ci_name" = "CI" ]
}

# The `concurrency:` surface is centrally owned (issue #141): it must stay
# in sync with standards/workflows/pr-auto-review.yml. The stub had drifted by
# dropping the block entirely; these tests pin the re-synced surface so future
# drift is caught in CI.
@test "declares a top-level concurrency block (centrally owned, issue #141)" {
  [ -f "$PR_YML" ]
  grep -qE '^concurrency:' "$PR_YML"
}

@test "concurrency groups check_suite/workflow_run runs per PR" {
  # Default-branch-context triggers collapse onto one group per PR so an
  # in-flight run is superseded (issue #1126).
  # Scope the checks to the concurrency: block so unrelated blocks or comments
  # can't cause spurious matches. 'next' skips the concurrency: line itself so
  # /^[^[:space:]]/ doesn't self-terminate.
  local block
  block="$(awk '/^concurrency:/{f=1; next} f && /^[^[:space:]]/{exit} f' "$PR_YML")"
  echo "$block" | grep -qF "format('pr-auto-review-ready-check-pr-{0}', github.event.check_suite.pull_requests[0].number)"
  echo "$block" | grep -qF "format('pr-auto-review-ready-check-pr-{0}', github.event.workflow_run.pull_requests[0].number)"
}

@test "concurrency falls back to a unique-per-run group for PR-head triggers" {
  local block
  block="$(awk '/^concurrency:/{f=1; next} f && /^[^[:space:]]/{exit} f' "$PR_YML")"
  echo "$block" | grep -qF "format('pr-auto-review-ready-check-unique-{0}', github.run_id)"
}

@test "cancel-in-progress is gated to check_suite/workflow_run only" {
  local block
  block="$(awk '/^concurrency:/{f=1; next} f && /^[^[:space:]]/{exit} f' "$PR_YML")"
  echo "$block" | grep -qF "cancel-in-progress: \${{ github.event_name == 'check_suite' || github.event_name == 'workflow_run' }}"
}
