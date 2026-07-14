#!/usr/bin/env bats
# SonarCloud githubactions:S7635 regression guard — issue #23.
#
# "Only pass required secrets to this workflow." First-party reusable-workflow
# caller stubs must NOT use `secrets: inherit` (which hands the reusable every
# org secret). Instead each stub passes only the secrets its reusable declares —
# the least-privilege pattern already adopted in add-to-project.yml and
# dependabot-rebase.yml. Auto-rebase needs no secrets at all (GITHUB_TOKEN only),
# so it carries no `secrets:` block.
#
# These tests pin that end-state so a future edit can't silently reintroduce
# `secrets: inherit` on a caller stub.

WF_DIR="${BATS_TEST_DIRNAME}/../.github/workflows"

# Every caller stub that previously used `secrets: inherit`.
STUBS=(
  auto-rebase.yml
  dependabot-automerge.yml
  dev-lead.yml
  pr-review-mention.yml
)

@test "no caller stub uses 'secrets: inherit'" {
  for f in "${STUBS[@]}"; do
    run grep -nE '^\s*secrets:\s*inherit\s*$' "$WF_DIR/$f"
    [ "$status" -ne 0 ] || {
      echo "FAIL: $f still uses 'secrets: inherit' (S7635)"
      echo "$output"
      return 1
    }
  done
}

@test "auto-rebase.yml passes no secrets (GITHUB_TOKEN only)" {
  # The reusable needs no repo secrets, so there must be no job-level
  # `secrets:` mapping at all.
  run grep -nE '^\s*secrets:' "$WF_DIR/auto-rebase.yml"
  [ "$status" -ne 0 ]
}

@test "dependabot-automerge.yml passes only APP_ID and APP_PRIVATE_KEY" {
  grep -qE '^\s*secrets:\s*$' "$WF_DIR/dependabot-automerge.yml"
  grep -qE '^\s*APP_ID:\s*\$\{\{\s*secrets\.APP_ID\s*\}\}\s*$' "$WF_DIR/dependabot-automerge.yml"
  grep -qE '^\s*APP_PRIVATE_KEY:\s*\$\{\{\s*secrets\.APP_PRIVATE_KEY\s*\}\}\s*$' "$WF_DIR/dependabot-automerge.yml"
}

@test "dev-lead.yml passes the CLAUDE token plus its optional secrets explicitly" {
  grep -qE '^\s*secrets:\s*$' "$WF_DIR/dev-lead.yml"
  grep -qE '^\s*CLAUDE_CODE_OAUTH_TOKEN:\s*\$\{\{\s*secrets\.CLAUDE_CODE_OAUTH_TOKEN\s*\}\}\s*$' "$WF_DIR/dev-lead.yml"
  grep -qE '^\s*GH_PAT_WORKFLOWS:\s*\$\{\{\s*secrets\.GH_PAT_WORKFLOWS\s*\}\}\s*$' "$WF_DIR/dev-lead.yml"
  grep -qE '^\s*GOOGLE_API_KEY:\s*\$\{\{\s*secrets\.GOOGLE_API_KEY\s*\}\}\s*$' "$WF_DIR/dev-lead.yml"
  grep -qE '^\s*GH_PAT:\s*\$\{\{\s*secrets\.GH_PAT\s*\}\}\s*$' "$WF_DIR/dev-lead.yml"
}

@test "pr-review-mention.yml passes only GH_PAT_WORKFLOWS" {
  grep -qE '^\s*secrets:\s*$' "$WF_DIR/pr-review-mention.yml"
  grep -qE '^\s*GH_PAT_WORKFLOWS:\s*\$\{\{\s*secrets\.GH_PAT_WORKFLOWS\s*\}\}\s*$' "$WF_DIR/pr-review-mention.yml"
}
