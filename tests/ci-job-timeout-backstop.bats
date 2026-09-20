#!/usr/bin/env bats
# Job-timeout backstop regression guard for .github/workflows/ci.yml (issue #143).
#
# The Fleet Monitor flagged ci.yml at a 20% (1/5) failure rate. Issues #124 and
# #126 hardened ci.yml against network operations that *error*: #124 wrapped the
# in-script fetches (gitleaks curl, coverage apt-get/pip3) in a single-retry
# helper, and #126 gave every job's `actions/checkout` a continue-on-error initial
# attempt + a gated single retry. Those idioms only fire on `outcome == 'failure'`
# — i.e. on an operation that returns an error. They do not bound an operation that
# *hangs* (a checkout that stalls on a TLS/DNS blip, an apt/pip fetch that wedges):
# with no job timeout, a hung ci.yml job runs to GitHub's 6-hour default before it
# fails. sonarcloud.yml already carries the org's remediation for exactly this — a
# job-level `timeout-minutes` backstop that bounds the whole job so a hang anywhere
# fails fast (issue #122). ci.yml's three jobs carry no such backstop.
#
# These tests pin a job-level `timeout-minutes` on all three ci.yml jobs
# (build-and-test, secret-scan, coverage), sized well above each job's worst-case
# retry path yet far below the 6-hour default.
#
# Run: bats tests/ci-job-timeout-backstop.bats

CI_YML="${BATS_TEST_DIRNAME}/../.github/workflows/ci.yml"

# Every ci.yml job that should carry a timeout backstop.
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

# Print the job-level timeout-minutes value for a job block on stdin. A job-level
# key sits at 4-space indent (`    timeout-minutes: N`); a step-level timeout is at
# 8-space indent, so the anchored 4-space match never picks one up by mistake.
job_timeout_value() {
  grep -E '^    timeout-minutes:[[:space:]]*[0-9]+[[:space:]]*$' \
    | grep -oE '[0-9]+' | head -1
}

@test "ci.yml exists" {
  [ -f "$CI_YML" ]
}

@test "each job declares a job-level timeout-minutes backstop" {
  for job in "${JOBS[@]}"; do
    block="$(job_block "$job")"
    echo "$block" | grep -qE '^    timeout-minutes:[[:space:]]*[0-9]+[[:space:]]*$' \
      || { echo "job '$job': no job-level 'timeout-minutes' backstop"; false; }
  done
}

@test "each job's timeout-minutes is a positive integer bounded well below the 6h default" {
  # A real bound: >= 1 minute (a positive cap), and <= 60 minutes so it fails fast
  # rather than approaching GitHub's 360-minute (6-hour) default. The repo's other
  # job timeouts (sonarcloud 28, copilot 30, ideation/driver 5) all sit in this range.
  for job in "${JOBS[@]}"; do
    val="$(job_block "$job" | job_timeout_value)"
    [ -n "$val" ] || { echo "job '$job': timeout-minutes value not found"; false; }
    [ "$val" -ge 1 ] || { echo "job '$job': timeout-minutes ($val) is not positive"; false; }
    [ "$val" -le 60 ] || { echo "job '$job': timeout-minutes ($val) is not bounded well below the 6h default"; false; }
  done
}

@test "ci.yml still parses as valid YAML after adding the timeout backstop" {
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
