#!/usr/bin/env bats
# Compliance regression guard for .github/workflows/pr-review-mention.yml.
#
# WHY THIS EXISTS (issue #40 — Fleet Monitor flakiness alert):
#   The monitored window showed an 11.1% "failure" rate (2 / 18 runs). Those two
#   runs are NOT a workflow defect: both are `pull_request_review_comment` events
#   whose triggering actor is the GitHub **Copilot** coding agent. GitHub gates
#   workflow runs triggered by Copilot *pending manual approval*, so the run is
#   created and immediately parked with conclusion `action_required` — no job ever
#   executes (`jobs: []`). fleet_monitor.sh counts `action_required` alongside
#   `failure`/`timed_out`, so this external security gate inflates the rate past
#   the 10% threshold. Every run that actually executed a job succeeded or
#   correctly skipped. There is no caller-side YAML change that disables the
#   `action_required` gate, and this file is a THIN CALLER STUB that must stay
#   byte-identical to the org canonical (fleet stub-drift guard).
#
#   So the durable, in-bounds protection is this guard: it pins the invariants
#   the stub header declares immutable. If a future edit repoints the reusable
#   ref, drops a trigger, or removes the permissions block, the reusable breaks
#   with *real* `failure` conclusions — this catches that class before it ships.

PRM_YML="${BATS_TEST_DIRNAME}/../.github/workflows/pr-review-mention.yml"

# Extract the single `uses:` line that calls the org reusable.
uses_line() {
  awk '/^  pr-review-mention:$/{p=1;next} p&&/^  [^[:space:]]/{p=0} p' "$PRM_YML" | grep -E '^[[:space:]]*uses:[[:space:]]' | head -1
}

@test "pr-review-mention.yml exists" {
  [ -f "$PRM_YML" ]
}

@test "the workflow name identity is preserved" {
  grep -qE '^name: PR Review — Mention Trigger$' "$PRM_YML"
}

# ── Trigger events (header: "do not change the trigger events") ───────────────
# The dispatch fires on all three; dropping any silently disables a review path.

@test "issue_comment created trigger is present" {
  grep -qE '^  issue_comment:$' "$PRM_YML"
  awk '/^  issue_comment:$/{p=1;next} p&&/types:/{print;exit}' "$PRM_YML" | grep -qF '[created]'
}

@test "pull_request_review_comment created trigger is present" {
  grep -qE '^  pull_request_review_comment:$' "$PRM_YML"
  awk '/^  pull_request_review_comment:$/{p=1;next} p&&/types:/{print;exit}' "$PRM_YML" | grep -qF '[created]'
}

@test "pull_request review_requested trigger is present" {
  grep -qE '^  pull_request:$' "$PRM_YML"
  awk '/^  pull_request:$/{p=1;next} p&&/types:/{print;exit}' "$PRM_YML" | grep -qF '[review_requested]'
}

# ── Permissions (header: "do not change the job-level permissions block") ─────
# A reusable can be granted no more than the calling job has, so removing or
# narrowing these breaks the reusable's gh API calls at runtime.

@test "top-level permissions is the empty (least-privilege) default" {
  grep -qE '^permissions: \{\}$' "$PRM_YML"
}

@test "the pr-review-mention job grants pull-requests: write" {
  awk '/^  pr-review-mention:$/{p=1;next} p&&/^  [^[:space:]]/{p=0} p' "$PRM_YML" | grep -qE '^[[:space:]]+pull-requests:[[:space:]]+write'
}

# ── Reusable ref (header: "do not repoint to @main, a SHA, or a frozen @vX") ──

@test "uses: targets the org pr-review-mention reusable workflow" {
  uses_line | grep -qF 'petry-projects/.github/.github/workflows/pr-review-mention-reusable.yml@'
}

@test "the reusable ref is a moving channel tag, not @main / a SHA / a frozen @vX" {
  ref="$(uses_line | sed -E 's/.*pr-review-mention-reusable\.yml@([^[:space:]#]+).*/\1/')"
  [ -n "$ref" ]
  # Must be a pr-review-mention channel tag whose final segment is a `…stable`
  # moving channel (accepts `stable` and major-scoped `vN-stable`).
  echo "$ref" | grep -qE '^pr-review-mention/([a-z0-9]+-)?stable$'
  # Explicitly reject the forbidden forms.
  [ "$ref" != "main" ]
  echo "$ref" | grep -qvE '^[0-9a-f]{40}$'          # not a bare commit SHA
  echo "$ref" | grep -qvE '^pr-review-mention/v[0-9]+$'  # not a frozen @vN semver tag
}

@test "secrets are inherited by the reusable" {
  awk '/^  pr-review-mention:$/{p=1;next} p&&/^  [^[:space:]]/{p=0} p' "$PRM_YML" | grep -qE '^[[:space:]]+secrets:[[:space:]]+inherit'
}
