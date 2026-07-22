#!/usr/bin/env bats
# Drift regression guard for .github/workflows/feature-ideation.yml (issue #64).
#
# feature-ideation.yml is a THIN CALLER STUB: the 5-phase ideation pipeline, the
# model selection, the github_token override, and every mutation helper live
# centrally in the reusable feature-ideation-reusable.yml, pinned to the moving
# `feature-ideation/*` channel tag. Its header forbids behavioral edits to the
# trigger shape, the `uses:` line, the job-level `permissions:` block, and the
# `secrets:` block — those are required for the reusable to work and are enforced
# fleet-wide by the org-wide drift-enforcement mechanism (see petry-projects/.github
# AGENTS.md).
#
# Fleet Monitor flagged this workflow as DEGRADED (issue #64), but the single
# failure in the window was a TRANSIENT external condition — Claude Code weekly
# usage-quota exhaustion ("You've hit your weekly limit") — not a code defect the
# stub can prevent. The one failure mode this consumer repo DOES control is LOCAL
# DRIFT of the caller: a trimmed trigger, a widened/narrowed permission, a `@main`
# (self-hosting-circular) ref, a dropped NOSONAR marker (which re-fails the Quality
# Gate), a lost `cancel-in-progress: false` (which would let concurrent ideation
# runs clobber each other's Discussion writes), or a project_context reverted to
# the uncustomised placeholder (which the reusable rejects at run time). These
# tests pin those stability invariants so such drift fails CI before it ships.
# Mirrors tests/dev-lead-workflow.bats (#39) and tests/sonarcloud-workflow.bats (#27).

FI_YML="${BATS_TEST_DIRNAME}/../.github/workflows/feature-ideation.yml"

# Emit the `uses:` line of the `ideate` job only (not any other job).
_ideate_uses() {
  awk '/^  ideate:$/ {p=1; next} p && /^    uses:/ {print; exit} p && /^  [^ ]/ {p=0}' "$FI_YML"
}

# Reusable ref pinned on the `uses:` line, i.e. the text after
# `feature-ideation-reusable.yml@` up to the first whitespace (a comment or EOL).
_uses_ref() {
  _ideate_uses | sed -E 's/.*feature-ideation-reusable\.yml@([^[:space:]]+).*/\1/'
}

# The multi-line permissions block belongs to the `ideate` job — the only
# `permissions:` with child scopes (redispatch/prep/top-level all use `{}`).
# Emit its child `key: value` lines.
_ideate_permissions() {
  awk '/^    permissions:$/ {p=1; next} p && /^      [a-z-]+:/ {print} p && !/^      [a-z-]+:/ {p=0}' "$FI_YML"
}

# Emit the child key: value lines of the `secrets:` block under the `ideate` job.
_ideate_secrets() {
  awk '/^    secrets:$/ {p=1; next} p && /^      [A-Z_]+:/ {print} p && !/^      [A-Z_]+:/ {p=0}' "$FI_YML"
}

# Body lines of the `project_context: |` literal block (indented 8+ spaces).
_project_context_body() {
  awk '/^      project_context: \|/ {p=1; next} p { if ($0 ~ /^        /) print; else exit }' "$FI_YML"
}

@test "feature-ideation.yml exists" {
  [ -f "$FI_YML" ]
}

@test "the required workflow name is preserved" {
  grep -qE '^name: Feature Research & Ideation \(BMAD Analyst\)$' "$FI_YML"
}

@test "top-level least-privilege permissions: {} is preserved" {
  # A caller that widens the top-level permissions block is drift; the stub grants
  # scopes per-job only. Pin the empty top-level grant.
  grep -qE '^permissions: \{\}$' "$FI_YML"
}

@test "all required event triggers are present" {
  # Dropping any trigger silently stops ideation from reacting to that event:
  # schedule (weekly run), workflow_dispatch (manual + the redispatch bridge),
  # discussion (auto-enhance freshly-created ideas).
  local trigger
  for trigger in schedule workflow_dispatch discussion; do
    grep -qE "^  ${trigger}:$" "$FI_YML"
  done
}

@test "the discussion trigger fires on created" {
  # The redispatch bridge only works if `discussion: created` events arrive.
  # Scope the check to the `discussion:` block to avoid false positives from
  # unrelated `types:` lines elsewhere in the file.
  awk '/^  discussion:$/ {p=1; next} p && /^    types:/ {print; exit} p && /^  [^ ]/ {p=0}' "$FI_YML" \
    | grep -qE '\[created\]'
}

@test "the concurrency lane pins cancel-in-progress: false" {
  # Ideation mutates Discussion threads; overlapping runs must serialise, never
  # cancel each other. Pin the group and the no-cancel policy.
  grep -qE '^  group: feature-ideation$' "$FI_YML"
  grep -qE '^  cancel-in-progress: false$' "$FI_YML"
}

@test "the reusable ref is pinned to the feature-ideation channel tag, never @main" {
  # @main would reintroduce a self-host circular dependency (a broken ideation
  # change gating its own fix) that the channel pin exists to prevent.
  local ref; ref="$(_uses_ref)"
  [ -n "$ref" ]
  [[ "$ref" == feature-ideation/* ]]
  [ "$ref" != "main" ]
}

@test "the reusable uses: line carries its S7637 NOSONAR marker" {
  # Without the marker SonarCloud's githubactions:S7637 fails the Quality Gate on
  # the first-party channel ref, turning every ideation run red.
  _ideate_uses | grep -qE 'uses:.*feature-ideation-reusable\.yml@[^[:space:]]+[[:space:]]+# NOSONAR\(githubactions:S7637\)'
}

@test "the ideate job grants exactly the required least-privilege scopes" {
  # The reusable's gather-signals + analyze jobs need these scopes; narrowing any
  # breaks the corresponding step (e.g. dropping discussions:write stops the
  # create/update of Discussion threads — the workflow's entire purpose).
  # The count check catches privilege escalation via added scopes.
  local permissions_block
  permissions_block="$(_ideate_permissions)"
  echo "$permissions_block" | grep -qE '^      contents: read$'
  echo "$permissions_block" | grep -qE '^      issues: read$'
  echo "$permissions_block" | grep -qE '^      pull-requests: read$'
  echo "$permissions_block" | grep -qE '^      discussions: write$'
  echo "$permissions_block" | grep -qE '^      id-token: write$'
  echo "$permissions_block" | grep -qE '^      actions: read$'
  [ "$(echo "$permissions_block" | grep -c .)" -eq 6 ]
}

@test "the CLAUDE_CODE_OAUTH_TOKEN secret is wired to the reusable" {
  # The reusable authenticates claude-code-action with this secret; dropping it
  # fails the Run Claude Code step immediately.
  _ideate_secrets | grep -qE '^      CLAUDE_CODE_OAUTH_TOKEN: \$\{\{ secrets\.CLAUDE_CODE_OAUTH_TOKEN \}\}'
}

@test "project_context is customised for this repo, not the placeholder" {
  # The reusable rejects an uncustomised project_context at run time. Pin that the
  # literal block references this repo and never reverts to the template prompt.
  local body; body="$(_project_context_body)"
  [ -n "$body" ]
  echo "$body" | grep -qiE 'incubat'
  ! echo "$body" | grep -qiE 'Replace this paragraph'
}

@test "the redispatch and prep bridge jobs are present" {
  # redispatch bridges `discussion: created` to workflow_dispatch (claude-code-action
  # cannot run on discussion contexts); prep resolves inputs off the `inputs` context
  # so the reusable `with:` compiles on the discussion event (#571). Losing either
  # reintroduces a zero-job startup failure.
  grep -qE '^  redispatch:$' "$FI_YML"
  grep -qE '^  prep:$' "$FI_YML"
}
