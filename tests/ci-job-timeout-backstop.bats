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

# List every top-level job id defined under `jobs:` in ci.yml. Jobs are 2-space
# indented under the `jobs:` key; other top-level maps (on, concurrency) also have
# 2-space children, so we only collect 2-space keys once inside the `jobs:` block.
list_jobs() {
  awk '
    /^[A-Za-z0-9_-]+:/ { injobs = ($0 ~ /^jobs:/) }
    injobs && /^  [A-Za-z0-9_-]+:/ {
      name = $0
      sub(/:.*/, "", name)
      sub(/^[[:space:]]+/, "", name)
      print name
    }
  ' "$CI_YML"
}

# Every ci.yml job that should carry a timeout backstop, discovered from the
# workflow itself. Deriving the set dynamically (rather than hardcoding it) means a
# newly added job that forgets a timeout backstop is caught by the guards below
# instead of silently passing the all-jobs contract.
mapfile -t JOBS < <(list_jobs)

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

@test "job discovery finds ci.yml's jobs (guards the loops against a vacuous pass)" {
  # If list_jobs returned nothing, every "for job in JOBS" loop below would pass
  # vacuously — so assert the set is non-empty and still contains the three
  # org-required jobs the backstop was introduced for.
  [ "${#JOBS[@]}" -ge 1 ] || { echo "no jobs discovered from ci.yml — parser broken?"; false; }
  for required in build-and-test secret-scan coverage; do
    found=0
    for job in "${JOBS[@]}"; do [ "$job" = "$required" ] && found=1; done
    [ "$found" -eq 1 ] || { echo "required job '$required' not discovered from ci.yml"; false; }
  done
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
    with open(sys.argv[1], encoding='utf-8') as f:
        yaml.safe_load(f)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" "$CI_YML"
  [ "$status" -eq 0 ]
}
