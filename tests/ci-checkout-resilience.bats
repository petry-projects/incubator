#!/usr/bin/env bats
# Checkout-resilience regression guard for .github/workflows/ci.yml (issue #126).
#
# Issue #124 hardened ci.yml's in-script network fetches (the gitleaks tarball
# curl, and the coverage apt-get/pip3 installs) with a single-retry helper. The
# remaining unguarded, network-bound operation in every ci.yml job is
# `actions/checkout`: a momentary DNS/TLS/GitHub blip on the fetch reds the whole
# run, with no retry. sonarcloud.yml already carries the org's remediation for
# exactly this (issue #83): a continue-on-error initial checkout, a short backoff,
# then a single retry gated on the initial checkout failing.
#
# These tests pin that same idiom on all three ci.yml jobs (build-and-test,
# secret-scan, coverage), so a transient checkout blip no longer fails the run.
#
# Run: bats tests/ci-checkout-resilience.bats

CI_YML="${BATS_TEST_DIRNAME}/../.github/workflows/ci.yml"

# Every ci.yml job that checks the repo out.
JOBS=(build-and-test secret-scan coverage)

# Print the lines of a single top-level job block from ci.yml, isolating it so a
# match in an unrelated job cannot cause a spurious hit. Jobs are 2-space indented
# under `jobs:`; a block runs from its `  <job>:` key until the next 2-space job
# key (or EOF), spanning the blank lines and comments in between.
job_block() {
  awk -v job="$1" '
    /^[A-Za-z0-9_-]+:/ { inblk = 0 }
    /^  [A-Za-z0-9_-]+:/ { inblk = ($0 ~ ("^  " job ":")) }
    inblk
  ' "$CI_YML"
}

# From a job block on stdin, print the initial-checkout step sub-block. A step
# begins at a 6-space `- ` and runs until the next 6-space `- ` or EOF. The `$`
# anchor on the name keeps this from also matching the "(retry)" step.
initial_block() {
  awk '/- name: Checkout repository$/{p=1} p && /^      - / && !/- name: Checkout repository$/{p=0} p'
}

# From a job block on stdin, print the checkout-retry step sub-block.
retry_block() {
  awk 'index($0,"- name: Checkout repository (retry)"){p=1} p && /^      - / && !index($0,"- name: Checkout repository (retry)"){p=0} p'
}

# From a job block on stdin, print the checkout-backoff step sub-block.
backoff_block() {
  awk '/- name: Checkout backoff before retry/{p=1} p && /^      - / && !/- name: Checkout backoff before retry/{p=0} p'
}

@test "ci.yml exists" {
  [ -f "$CI_YML" ]
}

@test "each job's initial checkout carries the checkout id and is continue-on-error" {
  for job in "${JOBS[@]}"; do
    block="$(job_block "$job" | initial_block)"
    [ -n "$block" ] || { echo "job '$job': no initial 'Checkout repository' step"; false; }
    echo "$block" | grep -qE '^[[:space:]]+id:[[:space:]]*checkout$' || { echo "job '$job': checkout missing 'id: checkout'"; false; }
    echo "$block" | grep -qE '^[[:space:]]+continue-on-error:[[:space:]]*true$' || { echo "job '$job': checkout not continue-on-error"; false; }
  done
}

@test "each job has exactly one checkout retry, gated on the initial checkout failing" {
  for job in "${JOBS[@]}"; do
    block="$(job_block "$job")"
    count="$(echo "$block" | awk '/- name: Checkout repository \(retry\)/{c++} END{print c+0}')"
    [ "$count" -eq 1 ] || { echo "job '$job': expected exactly 1 checkout retry, found $count"; false; }
    rblock="$(echo "$block" | retry_block)"
    echo "$rblock" | grep -qF "steps.checkout.outcome == 'failure'" || { echo "job '$job': retry not gated on checkout failure"; false; }
    # The retry must NOT be continue-on-error: if even the retry cannot fetch, the
    # job must fail fast rather than run against an empty/partial checkout.
    ! echo "$rblock" | grep -qF 'continue-on-error: true' || { echo "job '$job': retry must not be continue-on-error"; false; }
  done
}

@test "each job's backoff precedes the retry, gated on the same failure condition" {
  for job in "${JOBS[@]}"; do
    block="$(job_block "$job")"
    bblock="$(echo "$block" | backoff_block)"
    [ -n "$bblock" ] || { echo "job '$job': no checkout backoff step"; false; }
    echo "$bblock" | grep -qF "steps.checkout.outcome == 'failure'" || { echo "job '$job': backoff not gated on checkout failure"; false; }
    # A real wait precedes the retry (pin the intent, not a magic number).
    echo "$bblock" | grep -qE 'run: sleep [0-9]+' || { echo "job '$job': backoff has no 'sleep'"; false; }
    # The backoff must not be continue-on-error, so a failed backoff cannot silently
    # bypass the retry gate.
    ! echo "$bblock" | grep -qF 'continue-on-error: true' || { echo "job '$job': backoff must not be continue-on-error"; false; }
    # Ordering: the backoff step appears before the retry step within the job.
    bline="$(echo "$block" | awk '/- name: Checkout backoff before retry/{print NR; exit}')"
    rline="$(echo "$block" | awk 'index($0, "- name: Checkout repository (retry)"){print NR; exit}')"
    [ -n "$bline" ] && [ -n "$rline" ] && [ "$bline" -lt "$rline" ] || { echo "job '$job': backoff not before retry (backoff=$bline retry=$rline)"; false; }
  done
}

@test "each job's initial and retry checkouts pin the same SHA-pinned actions/checkout ref" {
  for job in "${JOBS[@]}"; do
    block="$(job_block "$job")"
    iref="$(echo "$block" | initial_block | grep -oE 'actions/checkout@[0-9a-f]{40}')"
    rref="$(echo "$block" | retry_block | grep -oE 'actions/checkout@[0-9a-f]{40}')"
    [ -n "$iref" ] || { echo "job '$job': initial checkout is not SHA-pinned"; false; }
    [ -n "$rref" ] || { echo "job '$job': retry checkout is not SHA-pinned"; false; }
    [ "$iref" = "$rref" ] || { echo "job '$job': retry ref ($rref) differs from initial ($iref)"; false; }
  done
}

@test "each job's checkouts disable credential persistence (persist-credentials: false)" {
  for job in "${JOBS[@]}"; do
    block="$(job_block "$job")"
    echo "$block" | initial_block | grep -qF 'persist-credentials: false' || { echo "job '$job': initial checkout missing persist-credentials: false"; false; }
    echo "$block" | retry_block | grep -qF 'persist-credentials: false' || { echo "job '$job': retry checkout missing persist-credentials: false"; false; }
  done
}

@test "the secret-scan checkouts both preserve full history (fetch-depth: 0)" {
  block="$(job_block secret-scan)"
  echo "$block" | initial_block | grep -qE 'fetch-depth: 0' || { echo "secret-scan initial checkout lost fetch-depth: 0"; false; }
  echo "$block" | retry_block | grep -qE 'fetch-depth: 0' || { echo "secret-scan retry checkout lost fetch-depth: 0"; false; }
}

@test "ci.yml still parses as valid YAML after hardening" {
  if ! command -v python3 >/dev/null 2>&1; then
    skip "python3 not available"
  fi
  if ! python3 -c "import yaml" >/dev/null 2>&1; then
    skip "PyYAML not available"
  fi
  run python3 -c "
import sys, yaml
try:
    yaml.safe_load(open(sys.argv[1], encoding='utf-8'))
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" "$CI_YML"
  [ "$status" -eq 0 ]
}
