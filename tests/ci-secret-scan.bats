#!/usr/bin/env bats
# Compliance regression guard for push-protection.md#required-ci-job:
# ci.yml must carry the canonical gitleaks secret-scan job and the repo must
# ship a .gitleaks.toml config, or the `Secret scan (gitleaks)` required check
# cannot run.

CI_YML="${BATS_TEST_DIRNAME}/../.github/workflows/ci.yml"
GITLEAKS_TOML="${BATS_TEST_DIRNAME}/../.gitleaks.toml"

@test "ci.yml defines a secret-scan job" {
  grep -qE '^  secret-scan:' "$CI_YML"
}

@test "secret-scan job has the required display name" {
  grep -qF 'name: Secret scan (gitleaks)' "$CI_YML"
}

@test "secret-scan checks out full git history" {
  grep -qE 'fetch-depth: 0' "$CI_YML"
}

@test "secret-scan installs the pinned, checksum-verified gitleaks version" {
  grep -qF 'GITLEAKS_VERSION: "8.30.1"' "$CI_YML"
  grep -qF 'GITLEAKS_CHECKSUM: "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"' "$CI_YML"
}

@test "secret-scan runs gitleaks detect with the required flags" {
  grep -qF 'gitleaks detect --source . --config .gitleaks.toml --redact --verbose --exit-code 1' "$CI_YML"
}

@test ".gitleaks.toml config exists at the repo root" {
  [ -f "$GITLEAKS_TOML" ]
}

@test ".gitleaks.toml declares an allowlist section" {
  grep -qE '^\[allowlist\]' "$GITLEAKS_TOML"
}
