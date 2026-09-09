#!/usr/bin/env bats
# Regression guard for issue #124.
#
# ci.yml carried a 14.3% (1/7) transient failure rate — the signature of an
# unguarded network fetch failing the whole job on a single blip. The fatal,
# retry-less network operations were:
#   • secret-scan: the gitleaks release tarball `curl` download
#   • coverage:    `apt-get update`, the `bats` install, and the `pip3` install
#
# The repo's canonical remediation (established by sonarcloud.yml, #122, per the
# org standard) is a SINGLE retry after a short backoff. This suite asserts each
# of those network fetches is wrapped in the retry helper (never issued bare), so
# a momentary DNS/TLS/mirror blip no longer reds the whole run.
#
# Run: bats tests/ci-network-resilience.bats

CI_YML="${BATS_TEST_DIRNAME}/../.github/workflows/ci.yml"

# Print the lines of a single top-level job block from ci.yml, isolating it so a
# match in an unrelated job cannot cause a spurious hit. Jobs are 2-space indented
# under `jobs:`; a block runs from its `  <job>:` key until the next 2-space job
# key (or EOF), spanning the blank lines and comments in between (a plain awk
# `/<job>:/,/^…$/` range would truncate at the first blank line inside the job).
job_block() {
  awk -v job="$1" '
    /^  [A-Za-z0-9_-]+:/ { inblk = ($0 ~ ("^  " job ":")) }
    inblk
  ' "$CI_YML"
}

# Print the body of the first retry() helper definition (the shell function that
# wraps a transient fetch), so assertions target the helper itself rather than any
# stray `sleep`/command elsewhere in the file.
retry_helper() {
  awk '/^ *retry\(\) \{/ { f = 1 } f { print } f && /^ *\}/ { exit }' "$CI_YML"
}

@test "ci.yml defines a retry helper for transient network fetches" {
  grep -qE '^ *retry\(\) \{' "$CI_YML"
}

@test "the retry helper performs a single backoff before retrying once" {
  # Target the helper body, not just any indented `sleep`. Assert the helper backs
  # off (sleep) between attempts, contains no loop construct (while/until/for) that
  # would mean unbounded retries, and invokes the command exactly twice — the first
  # attempt plus a single retry.
  retry_helper | grep -qE '^ *sleep '
  ! retry_helper | grep -qE '\b(while|until|for)\b'
  [ "$(retry_helper | grep -cE '"\$@"')" -eq 2 ]
}

@test "the gitleaks tarball download is wrapped in the retry helper" {
  job_block secret-scan | grep -qE 'retry curl .*-o /tmp/gitleaks\.tar\.gz'
}

@test "no bare (un-retried) curl download of the gitleaks tarball remains" {
  # The original fatal line was a bare `curl … -o /tmp/gitleaks.tar.gz`. Within the
  # secret-scan block, any curl fetching the tarball at the start of a command —
  # bare or `sudo curl` — must instead be prefixed by the retry helper (a wrapped
  # line begins with `retry curl …`, so it is not matched here).
  ! job_block secret-scan | grep -qE '^[[:space:]]*(sudo[[:space:]]+)?curl[[:space:]].*-o[[:space:]]*/tmp/gitleaks\.tar\.gz'
}

@test "the coverage apt-get update is retried" {
  job_block coverage | grep -qE 'retry sudo apt-get update'
}

@test "the coverage bats install is retried" {
  job_block coverage | grep -qE 'retry sudo apt-get install -y -qq bats'
}

@test "the coverage pip3 install is retried" {
  job_block coverage | grep -qE 'retry pip3 install'
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
