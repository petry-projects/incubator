#!/usr/bin/env bats
# Stub-surface drift guard for .github/workflows/dependency-audit.yml (issue #152).
#
# This file is a THIN CALLER STUB: its `on:` trigger surface is owned centrally by
# standards/workflows/dependency-audit.yml and is not repo-adjustable. The canonical
# trigger set is pull_request + push on main *plus* `merge_group` — the last is
# required so the stub's `dependency-audit / Detect ecosystems` status check reports
# on a merge queue's `gh-readonly-queue/*` ref. Dropping `merge_group` is the exact
# drift issue #152 fixes. These tests pin the trigger surface (and the preserved
# reusable `uses:` ref + job name) so the stub cannot silently drift again.

DEP_YML="${BATS_TEST_DIRNAME}/../.github/workflows/dependency-audit.yml"

@test "dependency-audit.yml exists" {
  [ -f "$DEP_YML" ]
}

@test "the stub triggers on pull_request against main" {
  pr_block="$(awk '/^  pull_request:/{p=1;next} /^  [a-z_]+:/{p=0} p' "$DEP_YML")"
  [ -n "$pr_block" ]
  echo "$pr_block" | grep -qE 'branches: \[main\]'
}

@test "the stub triggers on push to main" {
  push_block="$(awk '/^  push:/{p=1;next} /^  [a-z_]+:/{p=0} p' "$DEP_YML")"
  [ -n "$push_block" ]
  echo "$push_block" | grep -qE 'branches: \[main\]'
}

@test "the stub declares the required merge_group trigger" {
  # merge_group is part of the canonical trigger set (issue #152): without it the
  # required status check never reports on a merge queue's gh-readonly-queue/* ref.
  grep -qE '^  merge_group:' "$DEP_YML"
}

@test "the required job name 'dependency-audit' is preserved" {
  grep -qE '^  dependency-audit:' "$DEP_YML"
}

@test "the reusable is called via the first-party channel pin" {
  grep -qE '^    uses: petry-projects/\.github/\.github/workflows/dependency-audit-reusable\.yml@dependency-audit/v2-stable' "$DEP_YML"
}
