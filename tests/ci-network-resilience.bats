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

@test "ci.yml defines a retry helper for transient network fetches" {
  grep -qE '^ *retry\(\) \{' "$CI_YML"
}

@test "the retry helper performs a single backoff before retrying once" {
  # A backoff (sleep) must sit between the two attempts so the retry lands after
  # the transient clears rather than immediately re-hitting it.
  grep -qE '^ *sleep ' "$CI_YML"
}

@test "the gitleaks tarball download is wrapped in the retry helper" {
  grep -qE 'retry curl .*-o /tmp/gitleaks\.tar\.gz' "$CI_YML"
}

@test "no bare (un-retried) curl download of the gitleaks tarball remains" {
  # The original fatal line was a bare `curl … -o /tmp/gitleaks.tar.gz`. Any curl
  # fetching the tarball must be prefixed by the retry helper.
  ! grep -qE '^[[:space:]]*curl .*-o /tmp/gitleaks\.tar\.gz' "$CI_YML"
}

@test "the coverage apt-get update is retried" {
  grep -qE 'retry sudo apt-get update' "$CI_YML"
}

@test "the coverage bats install is retried" {
  grep -qE 'retry sudo apt-get install -y -qq bats' "$CI_YML"
}

@test "the coverage pip3 install is retried" {
  grep -qE 'retry pip3 install' "$CI_YML"
}

@test "ci.yml still parses as valid YAML after hardening" {
  if ! command -v python3 >/dev/null 2>&1; then
    skip "python3 not available"
  fi
  if ! python3 -c "import yaml" >/dev/null 2>&1; then
    skip "PyYAML not available"
  fi
  run python3 -c "import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding='utf-8'))" "$CI_YML"
  [ "$status" -eq 0 ]
}
