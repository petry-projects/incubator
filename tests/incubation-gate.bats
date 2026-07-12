#!/usr/bin/env bats
# Unit tests for scripts/incubation-gate.sh — the structural completeness gate.
# Run: bats tests/incubation-gate.bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  SPEC="$REPO_ROOT/ideas/package-spec.json"
  export SPEC
  # shellcheck source=../scripts/incubation-gate.sh
  source "$REPO_ROOT/scripts/incubation-gate.sh"
  WORK="$(mktemp -d)"
}
teardown() { rm -rf "${WORK:-}"; }

# Write a complete, gate-passing package into $WORK/<slug> from the templates,
# flipping each required artifact's status to `final` and filling placeholders.
_make_complete_pkg() {
  local dir="$WORK/demo"; mkdir -p "$dir"
  local file
  for file in $(jq -r '.required_artifacts[].file' "$SPEC"); do
    cp "$REPO_ROOT/ideas/_TEMPLATE/$file" "$dir/$file"
    # mark final + strip the literal placeholders the gate rejects
    sed -i 's/^status: draft.*/status: final/' "$dir/$file"
    sed -i 's/<Idea Title>/Demo/g; s/<slug>/demo/g; s/<YYYY-MM-DD>/2026-07-12/g; s/<who>/tester/g; s#<link>#https://example.com#g' "$dir/$file"
  done
  echo "$dir"
}

@test "fm_status: reads final from frontmatter" {
  printf -- '---\nstatus: final\n---\n# x\n' > "$WORK/a.md"
  [ "$(fm_status "$WORK/a.md")" = "final" ]
}

@test "fm_status: reads draft, ignores trailing comment" {
  printf -- '---\nstatus: draft   # draft | final\n---\n' > "$WORK/a.md"
  [ "$(fm_status "$WORK/a.md")" = "draft" ]
}

@test "fm_status: empty when no frontmatter" {
  printf -- '# no frontmatter\n' > "$WORK/a.md"
  [ -z "$(fm_status "$WORK/a.md")" ]
}

@test "has_section: matches header substring case-insensitively" {
  printf -- '## 1. Problem\ntext\n' > "$WORK/a.md"
  has_section "$WORK/a.md" "Problem"
}

@test "has_section: false when header absent" {
  printf -- '## Something else\n' > "$WORK/a.md"
  ! has_section "$WORK/a.md" "Problem"
}

@test "has_placeholder: detects the needs-discovery marker and angle placeholders" {
  printf -- 'TODO — needs discovery\n' > "$WORK/a.md"; has_placeholder "$WORK/a.md"
  printf -- 'slug is <slug>\n'        > "$WORK/b.md"; has_placeholder "$WORK/b.md"
  printf -- 'all filled in here\n'    > "$WORK/c.md"; ! has_placeholder "$WORK/c.md"
}

@test "check_package: a fully-filled package passes (exit 0, COMPLETE)" {
  local dir; dir="$(_make_complete_pkg)"
  run check_package "$dir"
  [ "$status" -eq 0 ]
  [[ "$output" == *"COMPLETE ✅"* ]]
}

@test "check_package: missing artifact fails and is named" {
  local dir; dir="$(_make_complete_pkg)"
  rm "$dir/prd.md"
  run check_package "$dir"
  [ "$status" -eq 1 ]
  [[ "$output" == *"prd.md"* && "$output" == *"missing"* ]]
  [[ "$output" == *"INCOMPLETE ❌"* ]]
}

@test "check_package: a draft-status artifact fails the gate" {
  local dir; dir="$(_make_complete_pkg)"
  sed -i 's/^status: final/status: draft/' "$dir/brief.md"
  run check_package "$dir"
  [ "$status" -eq 1 ]
  [[ "$output" == *"brief.md"* && "$output" == *"draft"* ]]
}

@test "check_package: a leftover placeholder fails even when marked final" {
  local dir; dir="$(_make_complete_pkg)"
  printf -- '\nleftover <Idea Title>\n' >> "$dir/brief.md"
  run check_package "$dir"
  [ "$status" -eq 1 ]
  [[ "$output" == *"placeholder"* ]]
}

@test "main: exits non-zero and prints header when a package is incomplete" {
  local dir; dir="$(_make_complete_pkg)"
  rm "$dir/prd.md"
  run main "$dir"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Incubation package gate"* ]]
}

@test "main: no args in scope exits 0 with a nothing-to-gate note" {
  run main
  [ "$status" -eq 0 ]
  [[ "$output" == *"nothing to gate"* ]]
}

@test "package-spec.json: is valid JSON and lists the four required artifacts" {
  run jq -e '.required_artifacts | map(.file) == ["brainstorm.md","market-research.md","brief.md","prd.md"]' "$SPEC"
  [ "$status" -eq 0 ]
}
