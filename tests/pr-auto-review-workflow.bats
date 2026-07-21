#!/usr/bin/env bats
# Compliance regression guard for .github/workflows/pr-auto-review.yml.
#
# WHY THIS EXISTS (issue #53 — SonarCloud githubactions:S1135):
#   The shipped caller stub carried a template placeholder comment:
#     # TODO: replace "CI" with your repository's CI workflow name(s).
#   SonarCloud flags every TODO/FIXME as rule S1135 ("complete the task"). The
#   task is in fact already done: this repo's CI workflow is named `CI`
#   (.github/workflows/ci.yml → `name: CI`), so `workflow_run.workflows: ["CI"]`
#   is the correct, final value. Resolving the finding means removing the stale
#   TODO — NOT changing the trigger — and this guard pins that outcome so a future
#   template re-sync cannot silently reintroduce the marker.
#
#   The stub header declares several invariants immutable (the moving-channel
#   reusable ref and the job-level permissions block). This guard also pins those,
#   mirroring tests/pr-review-mention-workflow.bats.

PAR_YML="${BATS_TEST_DIRNAME}/../.github/workflows/pr-auto-review.yml"

# Extract the full pr-auto-review job block.
job_block() {
  awk '/^  pr-auto-review:$/{p=1;next} p&&/^  [^[:space:]]/{p=0} p' "$PAR_YML"
}

# Extract the single `uses:` line that calls the org reusable.
uses_line() {
  job_block | grep -E '^[[:space:]]*uses:[[:space:]]' | head -1
}

@test "pr-auto-review.yml exists" {
  [ -f "$PAR_YML" ]
}

@test "the workflow name identity is preserved" {
  grep -qE '^name: PR Auto-Review — Ready Check$' "$PAR_YML"
}

# ── SonarCloud S1135: no unresolved TODO/FIXME markers ────────────────────────
# This is the finding under repair. The NOSONAR annotation on the `uses:` line is
# a different, confirmed-false-positive suppression (S7637) and must not be
# mistaken for a TODO — assert specifically on TODO/FIXME comment markers.

@test "no unresolved TODO or FIXME comment remains (S1135)" {
  ! grep -nE '(^|[[:space:]#])(TODO|FIXME)\b' "$PAR_YML"
}

# ── Trigger identity: workflow_run must name this repo's CI workflow ──────────
# The header permits changing workflow_run.workflows to match the repo's CI
# workflow name(s). This repo's CI workflow is named `CI` (ci.yml).

@test "workflow_run watches this repo's CI workflow by name" {
  grep -qE '^  workflow_run:$' "$PAR_YML"
  awk '/^  workflow_run:$/{p=1;next} p&&/^[[:space:]]{0,2}[^[:space:]]/{p=0} p&&/workflows:/{print;exit}' "$PAR_YML" | grep -qF '["CI"]'
}

# ── Immutable stub invariants (header: "you MUST NOT change") ─────────────────

@test "top-level permissions is the empty (least-privilege) default" {
  grep -qE '^permissions: \{\}$' "$PAR_YML"
}

@test "the pr-auto-review job preserves its read-only permissions block" {
  job_block | grep -qE '^[[:space:]]+pull-requests:[[:space:]]+read'
  job_block | grep -qE '^[[:space:]]+checks:[[:space:]]+read'
  job_block | grep -qE '^[[:space:]]+actions:[[:space:]]+read'
}

@test "uses: targets the org pr-auto-review reusable workflow" {
  uses_line | grep -qF 'petry-projects/.github/.github/workflows/pr-auto-review-reusable.yml@'
}

@test "the reusable ref is a moving channel tag, not @main / a SHA / a frozen @vX" {
  ref="$(uses_line | sed -E 's/.*pr-auto-review-reusable\.yml@([^[:space:]#]+).*/\1/')"
  [ -n "$ref" ]
  # Must be a pr-auto-review channel tag whose final segment is a `…stable`
  # moving channel (accepts `stable` and major-scoped `vN-stable`).
  echo "$ref" | grep -qE '^pr-auto-review/([a-z0-9]+-)?stable$'
  [ "$ref" != "main" ]
  echo "$ref" | grep -qvE '^[0-9a-f]{40}$'              # not a bare commit SHA
  echo "$ref" | grep -qvE '^pr-auto-review/v[0-9]+$'    # not a frozen @vN semver tag
}
