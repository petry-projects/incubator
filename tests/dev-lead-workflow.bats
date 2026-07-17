#!/usr/bin/env bats
# Compliance guard for .github/workflows/dev-lead.yml (issue #37,
# check: dev-lead-stub-agent-ref).
#
# The dev-lead caller stub must pass `with: agent_ref: dev-lead/<channel>` so the
# reusable checks out its own scripts/prompts from the same channel it runs from.
# The channel must be one of the standard-mandated forms — `stable`, `next`, or
# `ring<N>` — and the `agent_ref` must match the channel tag pinned on the `uses:`
# ref. These tests pin that contract so drift (e.g. a non-standard `v1-stable`
# tag) is caught before it ships.

DEV_LEAD_YML="${BATS_TEST_DIRNAME}/../.github/workflows/dev-lead.yml"

# Extract the tag pinned on the reusable `uses:` ref (the part after the last '@',
# stripping any trailing inline comment).
uses_tag() {
  grep -E '^    uses: petry-projects/\.github-private/' "$DEV_LEAD_YML" \
    | head -1 \
    | sed -E 's/.*@([^ ]+).*/\1/'
}

# Extract the value passed to `with: agent_ref:`.
agent_ref_value() {
  grep -E '^      agent_ref: ' "$DEV_LEAD_YML" \
    | head -1 \
    | sed -E 's/^      agent_ref: *//'
}

@test "dev-lead.yml exists" {
  [ -f "$DEV_LEAD_YML" ]
}

@test "the reusable uses: ref is pinned to a dev-lead channel tag" {
  tag="$(uses_tag)"
  [ -n "$tag" ]
  echo "$tag" | grep -qE '^dev-lead/(stable|next|ring[0-9]+)$'
}

@test "with: agent_ref is present and uses a standard channel form" {
  ref="$(agent_ref_value)"
  [ -n "$ref" ]
  # channel must be stable, next, or ring<N> — a non-standard tag (v1-stable) fails
  echo "$ref" | grep -qE '^dev-lead/(stable|next|ring[0-9]+)$'
}

@test "agent_ref matches the channel tag pinned on the uses: ref" {
  [ "$(agent_ref_value)" = "$(uses_tag)" ]
}

@test "the reusable ref carries the S7637 first-party marker" {
  grep -qE '^    uses: petry-projects/\.github-private/.*# NOSONAR\(githubactions:S7637\)' "$DEV_LEAD_YML"
}

@test "the required event triggers are preserved" {
  for ev in pull_request pull_request_review issue_comment issues check_run repository_dispatch; do
    grep -qE "^  ${ev}:" "$DEV_LEAD_YML"
  done
}

@test "top-level permissions are empty (least privilege at the caller)" {
  grep -qE '^permissions: \{\}$' "$DEV_LEAD_YML"
}
