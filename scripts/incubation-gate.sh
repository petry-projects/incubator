#!/usr/bin/env bash
set -uo pipefail
# incubation-gate.sh — structural completeness gate for an incubation idea package.
#
# Reads ideas/package-spec.json and checks that each ideas/<slug>/ directory
# contains every required artifact, each marked `status: final` in its
# frontmatter, carrying its required section headers, with no leftover template
# placeholders. Emits a GitHub-flavored-markdown checklist to stdout and exits
# non-zero if any package is incomplete — that non-zero is what keeps the
# incubation PR red until the package is complete.
#
# Usage:
#   scripts/incubation-gate.sh ideas/content-twin [ideas/<slug> ...]
#   scripts/incubation-gate.sh --all      # every ideas/<slug> except _TEMPLATE
#
# Env:
#   SPEC   override path to package-spec.json (default: <repo>/ideas/package-spec.json)
#
# Helpers are sourced by tests/incubation-gate.bats.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SPEC="${SPEC:-$REPO_ROOT/ideas/package-spec.json}"

# fm_status <file> — echo the frontmatter `status:` value (empty if none/no file).
fm_status() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  awk '
    NR==1 && $0=="---" { infm=1; next }
    infm && $0=="---" { exit }
    infm && /^status:/ { sub(/^status:[[:space:]]*/,""); gsub(/["'\''` ]/,""); sub(/#.*/,""); print; exit }
  ' "$f"
  return 0
}

# has_section <file> <needle> — true if a markdown header line contains <needle>
# (case-insensitive, fixed-string so section names may contain regex metachars).
has_section() {
  local file="$1" needle="$2"
  grep -E '^#{1,6}[[:space:]]' "$file" 2>/dev/null | grep -qiF "$needle"
}

# has_placeholder <file> — true if unfilled template placeholders remain.
has_placeholder() {
  local file="$1"
  grep -qE 'TODO — needs discovery|TODO: needs discovery|<Idea Title>|<slug>|<YYYY-MM-DD>|<who>|<link>' "$file" 2>/dev/null
}

# check_artifact <idea-dir> <artifact-index> — echo "PASS|reason" / "FAIL|reason";
# return 0 when complete, 1 otherwise.
check_artifact() {
  local dir="$1" idx="$2"
  local file path st final
  file="$(jq -r ".required_artifacts[$idx].file" "$SPEC")"
  path="$dir/$file"
  final="$(jq -r '.final_status' "$SPEC")"

  [[ -f "$path" ]] || { echo "FAIL|missing"; return 1; }

  st="$(fm_status "$path")"
  [[ "$st" = "$final" ]] || { echo "FAIL|status='${st:-none}' (need '$final')"; return 1; }

  local n i sec missing=()
  n="$(jq -r ".required_artifacts[$idx].required_sections | length" "$SPEC")"
  for ((i = 0; i < n; i++)); do
    sec="$(jq -r ".required_artifacts[$idx].required_sections[$i]" "$SPEC")"
    has_section "$path" "$sec" || missing+=("$sec")
  done
  [[ "${#missing[@]}" -eq 0 ]] || { echo "FAIL|missing section(s): ${missing[*]}"; return 1; }

  ! has_placeholder "$path" || { echo "FAIL|unfilled template placeholders remain"; return 1; }

  echo "PASS|ok"
  return 0
}

# check_package <idea-dir> — print the per-artifact checklist for one package;
# return 0 when every required artifact passes, 1 otherwise.
check_package() {
  local dir="$1"
  [[ -d "$dir" ]] || dir="$REPO_ROOT/$dir"
  local slug n i file res pass=0
  slug="$(basename "$dir")"
  n="$(jq -r '.required_artifacts | length' "$SPEC")"
  echo "### \`ideas/$slug\`"
  for ((i = 0; i < n; i++)); do
    file="$(jq -r ".required_artifacts[$i].file" "$SPEC")"
    if res="$(check_artifact "$dir" "$i")"; then
      echo "- [x] \`$file\` — ${res#*|}"
      pass=$((pass + 1))
    else
      echo "- [ ] \`$file\` — ${res#*|}"
    fi
  done
  echo ""
  if [[ "$pass" -eq "$n" ]]; then
    echo "**Package: $pass/$n — COMPLETE ✅**"
    return 0
  fi
  echo "**Package: $pass/$n — INCOMPLETE ❌** — this PR stays open until every box is checked."
  return 1
}

main() {
  local -a dirs=()
  if [[ "${1:-}" = "--all" ]]; then
    while IFS= read -r d; do dirs+=("$d"); done < <(
      find "$REPO_ROOT/ideas" -mindepth 1 -maxdepth 1 -type d ! -name '_TEMPLATE' | sort
    )
  else
    dirs=("$@")
  fi

  if [[ "${#dirs[@]}" -eq 0 ]]; then
    echo "_No idea packages in scope — nothing to gate._"
    return 0
  fi

  echo "## Incubation package gate"
  echo ""
  local overall=0 dir
  for dir in "${dirs[@]}"; do
    check_package "$dir" || overall=1
    echo ""
  done
  if [[ "$overall" -eq 0 ]]; then
    echo "All packages complete — approval of this PR is the authorization to begin work."
  fi
  return "$overall"
}

# Source-guard: tests source this file to exercise the helpers.
if [[ "${BASH_SOURCE[0]:-$0}" = "$0" ]]; then
  main "$@"
fi
