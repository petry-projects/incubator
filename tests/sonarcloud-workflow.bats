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
  [ -n "$retry_block" ]
  echo "$retry_block" | grep -qF "name: SonarCloud Scan (retry)"
  echo "$retry_block" | grep -qF "steps.sonar.outcome == 'failure'"
}

@test "a backoff step waits before the retry" {
  backoff_block="$(awk '/- name: Backoff before retry/{p=1} p && /^      - / && !/- name: Backoff before retry/{p=0} p' "$SONAR_YML")"
  [ -n "$backoff_block" ]
  echo "$backoff_block" | grep -qF "steps.sonar.outcome == 'failure'"
  # Pin the intent (a real wait precedes the retry), not a magic number: parse the
  # sleep duration so tuning the backoff never needs a brittle exact-match edit.
  echo "$backoff_block" | grep -qE 'run: sleep [0-9]+'
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

# ── Backoff duration guard (issue #27) ────────────────────────────────────────
# Failure rate was 43.8% with a hang signature already bounded by #21's timeout,
# so the live driver was the single retry re-hitting the same transient: a 30s
# backoff does not outlast a minute-scale SonarCloud/API blip, so the retry lands
# inside the outage and both attempts fail together. This pins a backoff long
# enough to clear a typical transient before the (single, standard-mandated) retry.

@test "the backoff is long enough to outlast a minute-scale transient (>= 60s)" {
  backoff_block="$(awk '/- name: Backoff before retry/{p=1} p && /^      - / && !/- name: Backoff before retry/{p=0} p' "$SONAR_YML")"
  seconds="$(echo "$backoff_block" | sed -nE 's/.*sleep ([0-9]+).*/\1/p' | head -n 1)"
  [ -n "$seconds" ]
  [ "$seconds" -ge 60 ]
}

# ── Hang guard (issue #21) ────────────────────────────────────────────────────
# p50 was 66s but p95 was ~2.8h: the signature of a hung scan, not a slow one.
# With no timeout-minutes, a hung SonarCloud scan runs to GitHub's 6-hour job
# default and counts as a failed run — and because the hang never lets the step
# finish, continue-on-error never fires, so the backoff/retry never runs. These
# tests pin the timeout bounds that turn a hang into a fast, retryable failure.

@test "the sonarcloud job declares a timeout-minutes backstop" {
  # Job-level key (4-space indent) that bounds the whole job.
  timeout="$(grep -E '^    timeout-minutes: [0-9]+$' "$SONAR_YML" | head -1 | grep -oE '[0-9]+')"
  [ -n "$timeout" ]
  [ "$timeout" -gt 0 ]
}

@test "the initial scan step bounds its runtime with timeout-minutes" {
  scan_block="$(awk '/- name: SonarCloud Scan$/{p=1} p && /^      - / && !/- name: SonarCloud Scan$/{p=0} p' "$SONAR_YML")"
  [ -n "$scan_block" ]
  echo "$scan_block" | grep -qE '^        timeout-minutes: [0-9]+$'
}

@test "the retry scan step bounds its runtime with timeout-minutes" {
  retry_block="$(awk 'index($0,"- name: SonarCloud Scan (retry)"){p=1} p && /^      - / && !index($0,"- name: SonarCloud Scan (retry)"){p=0} p' "$SONAR_YML")"
  [ -n "$retry_block" ]
  echo "$retry_block" | grep -qE '^        timeout-minutes: [0-9]+$'
}

@test "the job timeout is large enough to cover both bounded scans plus backoff" {
  # The job backstop must exceed initial-scan + retry step timeouts so a real
  # (non-hung) retry is never killed by the job-level cap before it can recover.
  job_timeout="$(grep -E '^    timeout-minutes: [0-9]+$' "$SONAR_YML" | head -1 | grep -oE '[0-9]+')"
  initial_timeout="$(awk '/- name: SonarCloud Scan$/{p=1} p && /^      - / && !/- name: SonarCloud Scan$/{p=0} p' "$SONAR_YML" | grep -oE 'timeout-minutes: [0-9]+' | grep -oE '[0-9]+')"
  retry_timeout="$(awk 'index($0,"- name: SonarCloud Scan (retry)"){p=1} p && /^      - / && !index($0,"- name: SonarCloud Scan (retry)"){p=0} p' "$SONAR_YML" | grep -oE 'timeout-minutes: [0-9]+' | grep -oE '[0-9]+')"
  [ -n "$job_timeout" ]
  [ -n "$initial_timeout" ]
  [ -n "$retry_timeout" ]
  [ "$job_timeout" -gt "$((initial_timeout + retry_timeout))" ]
}

# ── Queue-pileup guard (issue #31) ────────────────────────────────────────────
# p50 was a healthy 78s but p95 was 50669s (~14h) — far beyond the job's 25-min
# (#21) execution timeout, which a single run's steps cannot exceed. That tail is
# therefore dominated by *queue/pending* time: with no concurrency control and
# "Cancelled Runs: 0", superseded/hung runs are never cancelled — they pile up,
# hold runner capacity, and newer runs queue for hours before failing, driving
# the degraded failure rate. These tests pin a concurrency group that cancels the
# older in-flight run when a newer commit on the same ref arrives (as ci.yml does).

@test "the workflow declares a concurrency group" {
  # Top-level concurrency block with a non-empty group expression.
  grep -qE '^concurrency:$' "$SONAR_YML"
  grep -qE '^  group: .+$' "$SONAR_YML"
}

@test "cancel-in-progress is enabled so superseded runs are cancelled" {
  concurrency_block="$(awk '/^concurrency:$/{p=1; next} p && /^[^[:space:]]/{p=0} p' "$SONAR_YML")"
  [ -n "$concurrency_block" ]
  echo "$concurrency_block" | grep -qE '^  cancel-in-progress: true$'
}

@test "the concurrency group is keyed on github.ref so it cancels across commits" {
  # Keying on github.ref (not ref+sha) means a newer commit on the same branch
  # supersedes and cancels the older, still-queued/running scan — the lever that
  # drains the queue pileup behind the ~14h p95 tail.
  group_line="$(grep -E '^  group: ' "$SONAR_YML" | head -1)"
  [ -n "$group_line" ]
  echo "$group_line" | grep -qF 'github.ref'
  # Must not also pin the sha, which would scope the group per-commit and defeat
  # cancellation of superseded runs.
  ! echo "$group_line" | grep -qF 'github.sha'
}
