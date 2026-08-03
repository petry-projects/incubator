#!/usr/bin/env bats
# Regression guard for the failure mode behind issue #90.
#
# A workflow file with a YAML *syntax* error (e.g. an unquoted `run:` scalar that
# embeds a `": "` such as `--only-binary :all: -r …`) is rejected by GitHub at
# parse time. When that happens no job runs and the *entire* CI run fails —
# nothing inside the run can catch it, so the bad ref fails 100% of the time.
#
# This suite parses every `.github/workflows/*.yml` and asserts it is a YAML
# mapping that defines a top-level `jobs:` block, so an unparseable or
# structurally-broken workflow is caught in CI before it can land on main.
#
# Run: bats tests/workflows-yaml-valid.bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  WF_DIR="$REPO_ROOT/.github/workflows"
  export REPO_ROOT WF_DIR

  # Environment guard only (never used to mask a real failure): the validator
  # needs python3 + PyYAML, mirroring the existing python3/yaml dependency in
  # .dev-lead/scripts/dev-lead-lint.sh. Skip cleanly if the interpreter is absent.
  if ! command -v python3 >/dev/null 2>&1; then
    skip "python3 not available"
  fi
  if ! python3 -c "import yaml" >/dev/null 2>&1; then
    skip "PyYAML not available (pip3 install pyyaml)"
  fi
}

# _validate_workflow FILE
# Exit 0 if FILE is a YAML mapping containing a non-empty `jobs` mapping.
# Prints a human-readable reason and exits non-zero otherwise.
_validate_workflow() {
  python3 - "$1" <<'PY'
import sys
import yaml

path = sys.argv[1]
try:
    with open(path) as fh:
        doc = yaml.safe_load(fh)
except yaml.YAMLError as exc:
    print(f"YAML parse error: {exc}")
    sys.exit(2)

if not isinstance(doc, dict):
    print("top-level document is not a YAML mapping")
    sys.exit(3)
if "jobs" not in doc:
    print("missing top-level 'jobs:' key")
    sys.exit(4)
if not isinstance(doc["jobs"], dict) or not doc["jobs"]:
    print("'jobs:' is not a non-empty mapping")
    sys.exit(5)
sys.exit(0)
PY
}

@test "at least one workflow file exists to validate" {
  shopt -s nullglob
  local files=("$WF_DIR"/*.yml "$WF_DIR"/*.yaml)
  shopt -u nullglob
  [ "${#files[@]}" -gt 0 ]
}

@test "every workflow file is a valid YAML mapping with a jobs block" {
  shopt -s nullglob
  local files=("$WF_DIR"/*.yml "$WF_DIR"/*.yaml)
  shopt -u nullglob

  local bad=0 f reason
  for f in "${files[@]}"; do
    if ! reason="$(_validate_workflow "$f")"; then
      echo "INVALID: ${f#"$REPO_ROOT"/} — $reason"
      bad=1
    fi
  done
  [ "$bad" -eq 0 ]
}

@test "ci.yml specifically parses and defines a jobs block" {
  run _validate_workflow "$WF_DIR/ci.yml"
  [ "$status" -eq 0 ]
}

@test "validator flags an unquoted run: scalar with an embedded ': ' (the issue #90 break)" {
  # This is the exact class of edit that degraded ci.yml: a plain scalar
  # containing `": "` makes YAML read `all:` as a mapping key.
  local broken="$BATS_TEST_TMPDIR/broken.yml"
  cat > "$broken" <<'YML'
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: pip install --require-hashes --only-binary :all: -r requirements-lock.txt
YML
  run _validate_workflow "$broken"
  [ "$status" -ne 0 ]
  [[ "$output" == *"YAML parse error"* ]]
}

@test "validator accepts the same run: step once it is quoted" {
  local fixed="$BATS_TEST_TMPDIR/fixed.yml"
  cat > "$fixed" <<'YML'
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: "pip install --require-hashes --only-binary :all: -r requirements-lock.txt"
YML
  run _validate_workflow "$fixed"
  [ "$status" -eq 0 ]
}
