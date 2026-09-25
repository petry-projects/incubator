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

setup() {
  # Extract the top-level `on:` block once and reuse it for every trigger
  # assertion below. Scoping the pull_request / push / merge_group checks to
  # this block (rather than grepping the whole file) makes them fail if the
  # top-level `on:` key is renamed or a trigger moves out of it — a stray
  # match elsewhere in the file (e.g. a comment) can no longer pass a check.
  ON_BLOCK="$(awk '/^on:/{p=1;next} /^[a-zA-Z]+:/{p=0} p' "$DEP_YML")"
}

@test "dependency-audit.yml exists" {
  [ -f "$DEP_YML" ]
}

@test "the stub triggers on pull_request against main" {
  pr_block="$(printf '%s\n' "$ON_BLOCK" | awk '/^  pull_request:/{p=1;next} /^  [a-z_]+:/{p=0} p')"
  [ -n "$pr_block" ]
  printf '%s\n' "$pr_block" | grep -qE 'branches: \[main\]'
}

@test "the stub triggers on push to main" {
  push_block="$(printf '%s\n' "$ON_BLOCK" | awk '/^  push:/{p=1;next} /^  [a-z_]+:/{p=0} p')"
  [ -n "$push_block" ]
  printf '%s\n' "$push_block" | grep -qE 'branches: \[main\]'
}

@test "the stub declares the required merge_group trigger" {
  # merge_group is part of the canonical trigger set (issue #152): without it the
  # required status check never reports on a merge queue's gh-readonly-queue/* ref.
  # The `on:` block is isolated in setup() so a stray `merge_group:` elsewhere
  # (e.g. a comment) can't produce a false positive.
  printf '%s\n' "$ON_BLOCK" | grep -qE '^  merge_group:'
}

@test "the stub declares exactly the canonical trigger set" {
  # Guard against silent drift in the other direction: an unintended trigger
  # (e.g. workflow_dispatch) must fail this test, not slip through. Pin the
  # complete set of top-level trigger keys under `on:` — not just their presence.
  triggers="$(printf '%s\n' "$ON_BLOCK" | grep -oE '^  [a-z_]+:' | tr -d ' :' | sort | tr '\n' ' ')"
  [ "$triggers" = "merge_group pull_request push " ]
}

@test "the required job name 'dependency-audit' is preserved" {
  # Isolate the `jobs:` block before matching so an unrelated top-level key
  # can't cause a spurious match.
  jobs_block="$(awk '/^jobs:/{p=1;next} /^[a-zA-Z]+:/{p=0} p' "$DEP_YML")"
  echo "$jobs_block" | grep -qE '^  dependency-audit:'
}

@test "the reusable is called via the first-party channel pin" {
  # Isolate the dependency-audit job block before checking the `uses:` line so
  # the assertion is scoped to the correct job.
  job_block="$(awk '/^  dependency-audit:/{p=1;next} /^  [a-z_]+:/{p=0} p' "$DEP_YML")"
  echo "$job_block" | grep -qE '^    uses: petry-projects/\.github/\.github/workflows/dependency-audit-reusable\.yml@dependency-audit/v2-stable'
}
