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

# ── Backoff duration guard (issues #27, #80) ──────────────────────────────────
# Failure rate was 43.8% with a hang signature already bounded by #21's timeout,
# so the live driver was the single retry re-hitting the same transient: a 30s
# backoff does not outlast a minute-scale SonarCloud/API blip, so the retry lands
# inside the outage and both attempts fail together. Issue #27 raised it 30s->60s,
# cutting the rate to 16.7% (1/6). The residual failure (issue #80) is a transient
# that outlasted a single minute, so the 60s retry still re-hit it; #80 doubled the
# wait to 120s for two minutes of headroom. The org standard mandates a *single*
# retry, so the backoff duration is the only lever left to widen. This pins a
# backoff long enough to clear a multi-minute-scale transient before that retry.

@test "the backoff is long enough to outlast a multi-minute transient (>= 120s)" {
  backoff_block="$(awk '/- name: Backoff before retry/{p=1} p && /^      - / && !/- name: Backoff before retry/{p=0} p' "$SONAR_YML")"
  seconds="$(echo "$backoff_block" | grep -E '^\s*run: sleep [0-9]+' | sed -nE 's/.*sleep ([0-9]+).*/\1/p' | head -n 1)"
  [ -n "$seconds" ]
  [ "$seconds" -ge 120 ]
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

# ── Checkout resilience guard (issue #83) ─────────────────────────────────────
# Residual failure rate was 20% (1/5) with p50=45s and p95=47s — the failing run
# was *fast*. It never entered the 120s scan backoff (that would push a failed run
# past 165s), and the initial scan is continue-on-error so it can't fail the job.
# The one remaining unguarded, network-bound step is the full-history checkout
# (fetch-depth: 0), whose ~45s fetch matches the failing-run duration. These tests
# pin a single gated retry on the checkout, mirroring the scan-retry idiom, so a
# transient checkout blip no longer reds the whole run.

@test "the initial checkout carries an id and is continue-on-error" {
  checkout_block="$(awk '/- name: Checkout repository$/{p=1} p && /^      - / && !/- name: Checkout repository$/{p=0} p' "$SONAR_YML")"
  [ -n "$checkout_block" ]
  echo "$checkout_block" | grep -qE '^        id: checkout$'
  echo "$checkout_block" | grep -qE '^        continue-on-error: true$'
}

@test "a single checkout retry step is gated on the initial checkout failing" {
  retry_count="$(awk '/- name: Checkout repository \(retry\)/{c++} END{print c+0}' "$SONAR_YML")"
  [ "$retry_count" -eq 1 ]
  retry_block="$(awk 'index($0,"- name: Checkout repository (retry)"){p=1} p && /^      - / && !index($0,"- name: Checkout repository (retry)"){p=0} p' "$SONAR_YML")"
  [ -n "$retry_block" ]
  echo "$retry_block" | grep -qF "name: Checkout repository (retry)"
  echo "$retry_block" | grep -qF "steps.checkout.outcome == 'failure'"
}

@test "the checkout retry also fetches full git history (fetch-depth: 0)" {
  initial_block="$(awk '/- name: Checkout repository$/{p=1} p && /^      - / && !/- name: Checkout repository$/{p=0} p' "$SONAR_YML")"
  retry_block="$(awk 'index($0,"- name: Checkout repository (retry)"){p=1} p && /^      - / && !index($0,"- name: Checkout repository (retry)"){p=0} p' "$SONAR_YML")"
  [ -n "$initial_block" ]
  [ -n "$retry_block" ]
  echo "$initial_block" | grep -qE 'fetch-depth: 0'
  echo "$retry_block" | grep -qE 'fetch-depth: 0'
}

@test "a backoff precedes the checkout retry, gated on the same failure condition" {
  backoff_block="$(awk '/- name: Checkout backoff before retry/{p=1} p && /^      - / && !/- name: Checkout backoff before retry/{p=0} p' "$SONAR_YML")"
  [ -n "$backoff_block" ]
  echo "$backoff_block" | grep -qF "steps.checkout.outcome == 'failure'"
  # Pin the intent (a real wait precedes the retry), not a magic number.
  echo "$backoff_block" | grep -qE 'run: sleep [0-9]+'
  # The backoff must not be continue-on-error so a failed backoff cannot silently
  # bypass the retry gate.
  ! echo "$backoff_block" | grep -qF 'continue-on-error: true'
}

@test "the checkout backoff step appears before the checkout retry step" {
  backoff_line="$(awk '/- name: Checkout backoff before retry/{print NR; exit}' "$SONAR_YML")"
  retry_line="$(awk '/- name: Checkout repository \(retry\)/{print NR; exit}' "$SONAR_YML")"
  [ -n "$backoff_line" ]
  [ -n "$retry_line" ]
  [ "$backoff_line" -lt "$retry_line" ]
}

@test "both checkout steps pin the same SHA-pinned actions/checkout ref" {
  # Never a tag/branch: every actions/checkout use must be pinned to a 40-char SHA,
  # and the retry must use the same pinned ref as the initial checkout.
  initial_ref="$(awk '/- name: Checkout repository$/{p=1} p && /^      - / && !/- name: Checkout repository$/{p=0} p' "$SONAR_YML" | grep -oE 'actions/checkout@[0-9a-f]{40}')"
  retry_ref="$(awk '/- name: Checkout repository \(retry\)/{p=1} p && /^      - / && !/- name: Checkout repository \(retry\)/{p=0} p' "$SONAR_YML" | grep -oE 'actions/checkout@[0-9a-f]{40}')"
  [ -n "$initial_ref" ]
  [ -n "$retry_ref" ]
  [ "$initial_ref" = "$retry_ref" ]
}

@test "both checkout steps disable credential persistence (persist-credentials: false)" {
  initial_block="$(awk '/- name: Checkout repository$/{p=1} p && /^      - / && !/- name: Checkout repository$/{p=0} p' "$SONAR_YML")"
  retry_block="$(awk 'index($0,"- name: Checkout repository (retry)"){p=1} p && /^      - / && !index($0,"- name: Checkout repository (retry)"){p=0} p' "$SONAR_YML")"
  [ -n "$initial_block" ]
  [ -n "$retry_block" ]
  echo "$initial_block" | grep -qF 'persist-credentials: false'
  echo "$retry_block" | grep -qF 'persist-credentials: false'
}

@test "the checkout retry runs before the SonarCloud scan" {
  checkout_line="$(awk '/- name: Checkout repository$/{print NR; exit}' "$SONAR_YML")"
  backoff_line="$(awk '/- name: Checkout backoff before retry/{print NR; exit}' "$SONAR_YML")"
  checkout_retry_line="$(awk '/- name: Checkout repository \(retry\)/{print NR; exit}' "$SONAR_YML")"
  scan_line="$(awk '/- name: SonarCloud Scan$/{print NR; exit}' "$SONAR_YML")"
  [ -n "$checkout_line" ]
  [ -n "$backoff_line" ]
  [ -n "$checkout_retry_line" ]
  [ -n "$scan_line" ]
  [ "$checkout_line" -lt "$backoff_line" ]
  [ "$checkout_line" -lt "$checkout_retry_line" ]
  [ "$checkout_retry_line" -lt "$scan_line" ]
}

@test "the job timeout is large enough to cover both bounded scans plus backoff" {
  # The job backstop must exceed initial-scan + backoff + retry step timeouts so a real
  # (non-hung) retry is never killed by the job-level cap before it can recover.
  job_timeout="$(grep -E '^    timeout-minutes: [0-9]+$' "$SONAR_YML" | head -1 | grep -oE '[0-9]+')"
  initial_timeout="$(awk '/- name: SonarCloud Scan$/{p=1} p && /^      - / && !/- name: SonarCloud Scan$/{p=0} p' "$SONAR_YML" | grep -oE 'timeout-minutes: [0-9]+' | grep -oE '[0-9]+')"
  retry_timeout="$(awk 'index($0,"- name: SonarCloud Scan (retry)"){p=1} p && /^      - / && !index($0,"- name: SonarCloud Scan (retry)"){p=0} p' "$SONAR_YML" | grep -oE 'timeout-minutes: [0-9]+' | grep -oE '[0-9]+')"
  backoff_seconds="$(awk '/- name: Backoff before retry/{p=1} p && /^      - / && !/- name: Backoff before retry/{p=0} p' "$SONAR_YML" | grep -E '^\s*run: sleep [0-9]+' | sed -nE 's/.*sleep ([0-9]+).*/\1/p' | head -n 1)"
  [ -n "$job_timeout" ]
  [ -n "$initial_timeout" ]
  [ -n "$retry_timeout" ]
  [ -n "$backoff_seconds" ]
  # Compare in seconds so the backoff (seconds) and scan timeouts (minutes) use the same unit
  [ "$((job_timeout * 60))" -gt "$((initial_timeout * 60 + backoff_seconds + retry_timeout * 60))" ]
}
