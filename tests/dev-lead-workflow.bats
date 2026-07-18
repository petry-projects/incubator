#!/usr/bin/env bats
# Drift regression guard for .github/workflows/dev-lead.yml (issue #39).
#
# dev-lead.yml is a THIN CALLER STUB: its runtime behavior — per-issue / per-PR
# concurrency lanes, retries, timeouts — lives centrally in the reusable
# dev-lead-reusable.yml, pinned to the moving `dev-lead/*` channel tag. Behavioral
# edits to this caller are forbidden by its header and enforced fleet-wide by the
# org-wide drift-enforcement mechanism (see petry-projects/.github AGENTS.md). The one failure mode this consumer
# repo controls is LOCAL DRIFT of the caller: a trimmed trigger, a narrowed
# permission, a `@main` (self-hosting-circular) ref, a channel/agent_ref mismatch,
# a dropped NOSONAR marker (which re-fails the Quality Gate), or an added
# caller-level `concurrency:` block that would override the reusable's lanes and
# cause the spurious cancellations Fleet Monitor flagged. These tests pin those
# stability invariants so such drift fails CI before it ships. Mirrors the
# precedent set by issue #27 (tests/sonarcloud-workflow.bats).

DEV_LEAD_YML="${BATS_TEST_DIRNAME}/../.github/workflows/dev-lead.yml"

# Reusable ref pinned on the `uses:` line, i.e. the text after
# `dev-lead-reusable.yml@` up to the first whitespace (a comment or EOL).
_uses_ref() {
  grep -E 'uses:.*dev-lead-reusable\.yml@' "$DEV_LEAD_YML" \
    | sed -E 's/.*dev-lead-reusable\.yml@([^[:space:]]+).*/\1/' | head -1
}

@test "dev-lead.yml exists" {
  [ -f "$DEV_LEAD_YML" ]
}

@test "the required workflow name is preserved" {
  grep -qE '^name: Dev-Lead Agent$' "$DEV_LEAD_YML"
}

@test "top-level least-privilege permissions: {} is preserved" {
  # A caller that widens the top-level permissions block is drift; the stub grants
  # scopes per-job only. Pin the empty top-level grant.
  grep -qE '^permissions: \{\}$' "$DEV_LEAD_YML"
}

@test "all required event triggers are present" {
  # Dropping any trigger silently stops dev-lead from reacting to that event.
  local trigger
  for trigger in pull_request pull_request_review pull_request_review_comment \
                 issue_comment issues check_run repository_dispatch; do
    grep -qE "^  ${trigger}:$" "$DEV_LEAD_YML"
  done
}

@test "the reusable ref is pinned to the dev-lead channel tag, never @main" {
  # @main would reintroduce the self-host circular dependency (a broken dev-lead
  # change gating its own fix) that the channel pin exists to prevent.
  local ref; ref="$(_uses_ref)"
  [ -n "$ref" ]
  [[ "$ref" == dev-lead/* ]]
  [ "$ref" != "main" ]
}

@test "the reusable uses: line carries its S7637 NOSONAR marker" {
  # Without the marker SonarCloud's githubactions:S7637 fails the Quality Gate on
  # the first-party channel ref, turning every dev-lead run red.
  grep -qE 'uses:.*dev-lead-reusable\.yml@[^[:space:]]+[[:space:]]+# NOSONAR\(githubactions:S7637\)' "$DEV_LEAD_YML"
}

@test "agent_ref matches the channel pinned on the uses: ref" {
  # agent_ref threads the SAME channel into dev-lead's own scripts/prompts
  # checkout; a mismatch runs the caller against one ring and the agent code
  # against another.
  local uses_ref agent_ref
  uses_ref="$(_uses_ref)"
  agent_ref="$(awk '/^[[:space:]]+with:/ {p=1; next} p && /^[[:space:]]+agent_ref:/ {sub(/.*agent_ref:[[:space:]]*/, ""); print; exit} p && !/^[[:space:]]+[a-z_]+:/ {p=0}' "$DEV_LEAD_YML")"
  [ -n "$uses_ref" ]
  [ -n "$agent_ref" ]
  [ "$uses_ref" = "$agent_ref" ]
}

@test "secrets: inherit carries its S7635 NOSONAR marker" {
  grep -qE '^    secrets: inherit[[:space:]]+# NOSONAR\(githubactions:S7635\)' "$DEV_LEAD_YML"
}

@test "the caller declares no concurrency block" {
  # Concurrency is centralised in the reusable with per-issue / per-PR lanes. A
  # caller-level `concurrency:` group would collapse those lanes onto one ref-keyed
  # group, so PR follow-up traffic would cancel in-flight issue pickups — the
  # spurious-cancellation signature Fleet Monitor flagged. Keep it out of the caller.
  ! grep -qE '^[[:space:]]*concurrency:' "$DEV_LEAD_YML"
}

@test "the job grants the required least-privilege scopes" {
  # The dev-lead job needs exactly these scopes; narrowing any of them breaks the
  # corresponding action (e.g. dropping issues:write stops issue comments).
  local permissions_block
  permissions_block="$(awk '/^[[:space:]]+permissions:/ {p=1; next} p && /^[[:space:]]+[a-z-]+:/ {print} p && !/^[[:space:]]+[a-z-]+:/ {p=0}' "$DEV_LEAD_YML")"
  echo "$permissions_block" | grep -qE 'contents: write'
  echo "$permissions_block" | grep -qE 'pull-requests: write'
  echo "$permissions_block" | grep -qE 'issues: write'
  echo "$permissions_block" | grep -qE 'actions: read'
  echo "$permissions_block" | grep -qE 'checks: read'
  echo "$permissions_block" | grep -qE 'statuses: read'
}
