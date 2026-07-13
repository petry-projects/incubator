#!/usr/bin/env bats
# Flakiness regression guard for .github/workflows/sonarcloud.yml.
#
# The SonarCloud analysis endpoint flakes transiently, so the workflow retries
# the scan once. A zero-delay retry re-hits the same transient outage, which is
# what left the workflow DEGRADED (issue #10). These tests pin the structure
# that keeps the retry effective: an initial continue-on-error scan, a backoff
# wait, then a single retry gated on the initial scan failing — with the backoff
# ordered *before* the retry.

SONAR_YML="${BATS_TEST_DIRNAME}/../.github/workflows/sonarcloud.yml"

@test "sonarcloud.yml exists" {
  [ -f "$SONAR_YML" ]
}

@test "the required 'SonarCloud' job name is preserved" {
  grep -qE '^    name: SonarCloud$' "$SONAR_YML"
}

@test "checkout uses full git history (fetch-depth: 0)" {
  grep -qE 'fetch-depth: 0' "$SONAR_YML"
}

@test "initial scan is continue-on-error and carries the sonar id" {
  grep -qE '^        id: sonar$' "$SONAR_YML"
  grep -qE '^        continue-on-error: true$' "$SONAR_YML"
}

@test "a single retry step is gated on the initial scan failing" {
  retry_block="$(awk 'index($0,"- name: SonarCloud Scan (retry)"){p=1} p && /^      - / && !index($0,"- name: SonarCloud Scan (retry)"){p=0} p' "$SONAR_YML")"
  run grep -cF "name: SonarCloud Scan (retry)" "$SONAR_YML"
  [ "$output" -eq 1 ]
  echo "$retry_block" | grep -qF "steps.sonar.outcome == 'failure'"
}

@test "a backoff step waits before the retry" {
  backoff_block="$(awk '/- name: Backoff before retry/{p=1} p && /^      - / && !/- name: Backoff before retry/{p=0} p' "$SONAR_YML")"
  [ -n "$backoff_block" ]
  echo "$backoff_block" | grep -qF "steps.sonar.outcome == 'failure'"
  echo "$backoff_block" | grep -qF "run: sleep 30"
}

@test "the backoff is gated on the same failure condition as the retry" {
  # Both the backoff and the retry must only run when the first scan failed,
  # so the wait is never paid on the happy path.
  backoff_block="$(awk '/- name: Backoff before retry/{p=1} p && /^      - / && !/- name: Backoff before retry/{p=0} p' "$SONAR_YML")"
  retry_block="$(awk 'index($0,"- name: SonarCloud Scan (retry)"){p=1} p && /^      - / && !index($0,"- name: SonarCloud Scan (retry)"){p=0} p' "$SONAR_YML")"
  echo "$backoff_block" | grep -qF "steps.sonar.outcome == 'failure'"
  echo "$retry_block" | grep -qF "steps.sonar.outcome == 'failure'"
}

@test "the backoff step appears before the retry step" {
  backoff_line="$(grep -nF 'name: Backoff before retry' "$SONAR_YML" | head -1 | cut -d: -f1)"
  retry_line="$(grep -nF 'name: SonarCloud Scan (retry)' "$SONAR_YML" | head -1 | cut -d: -f1)"
  [ -n "$backoff_line" ]
  [ -n "$retry_line" ]
  [ "$backoff_line" -lt "$retry_line" ]
}
