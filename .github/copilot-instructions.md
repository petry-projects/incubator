# Copilot Instructions — repo-template

## About

`repo-template` is the org baseline scaffold for new `petry-projects` repositories:
click **Use this template** to create a repo pre-wired with the standard workflow
stubs and baseline files. Its "code" is GitHub Actions workflows and Markdown docs —
there is no application runtime and no local automation scripts. The workflow stubs and
baseline files are a distribution artifact of the org standards in
[`petry-projects/.github`](https://github.com/petry-projects/.github) (`standards/`)
and are regenerated from there.

## Tech Stack

- **Runtime:** None — this is a template/scaffold repo, not a deployable application.
- **CI / config:** GitHub Actions workflow stubs (YAML) under `.github/workflows/`; Dependabot; SonarCloud.
- **Docs:** Markdown (`AGENTS.md`, `CLAUDE.md`, `BOOTSTRAP.md`, `README.md`, `SECURITY.md`).
- **Tooling:** `bats` (compliance regression tests in `tests/`), `gh` CLI (workflow automation via CI).

## Project Structure

```
.github/
  workflows/          # Thin-caller workflow stubs (ci, sonarcloud, dependabot-*, dev-lead, …)
  copilot-instructions.md   # This file
  CODEOWNERS
  dependabot.yml      # Per-stack — picked once during bootstrap (see BOOTSTRAP.md)
tests/
  ci-secret-scan.bats # Compliance regression guard for the secret-scan CI job
AGENTS.md             # Points to org-wide standards in petry-projects/.github
BOOTSTRAP.md          # One-time, per-stack setup steps for repos made from this template
sonar-project.properties  # SonarCloud project key / sources (customize per repo)
```

Baseline workflow stubs (`ci.yml`, `copilot-setup-steps.yml`) ship as **customize-per-stack**
stubs: they pass out of the box and are tailored to each repo's language after creation.

## Local Dev Commands

There is no install/build/dev-run step — the repo has no application dependencies.

Validation happens primarily via GitHub Actions in CI. To run the compliance regression tests
locally:

- Compliance tests: `bats tests/ci-secret-scan.bats`  ← requires `bats` installed locally
- Workflow YAML validation: push to a branch and let CI run, or use `act` locally.

## Required Environment Variables

No application secrets are needed for local work. In CI:

- `SONAR_TOKEN`: SonarCloud analysis token — provided org-wide; the `sonarcloud` workflow is a
  green no-op until it is present. Never commit a real token.
- `GITHUB_TOKEN`: provided automatically by GitHub Actions; used by `gh` in the automation
  workflows. Do not hard-code personal access tokens.
- `CLAUDE_CODE_OAUTH_TOKEN`: required by `dev-lead.yml` to run the dev-lead agent. Set as an
  org or repo secret.
- `APP_ID` / `APP_PRIVATE_KEY`: GitHub App credentials required by `dependabot-automerge.yml`
  (contents:write and pull-requests:write). Set as org secrets.
- `GH_PAT_WORKFLOWS`: required by `pr-review-mention.yml` to dispatch PR review automation.
  Set as an org secret.

## Testing Framework

- Compliance tests: `bats` for CI regression guards in `tests/` (run via `bats tests/*.bats`).
  These verify that workflow stubs carry required jobs/steps (e.g. the secret-scan job in `ci.yml`).
- CI validation: GitHub Actions workflows are the primary verification mechanism — push to a
  branch and let the CI suite run. SonarCloud guards code quality (gated by `SONAR_TOKEN`).
- No coverage threshold applies — there is no application code to cover.

## Repo-Specific Overrides

- **Edit the standards, not these copies.** Workflow stubs and baseline files are regenerated
  from `petry-projects/.github` (`standards/`). Changes to the org-wide pattern belong in a PR
  against that repo and are then propagated to the fleet — do not fork the pattern here.
- `ci.yml` ships as a passing placeholder; a real repo replaces the stub step with its stack's
  lint / format / typecheck / test / coverage steps (see `BOOTSTRAP.md`).

## Org Standards

See [petry-projects/.github — AGENTS.md](https://github.com/petry-projects/.github/blob/main/AGENTS.md)
for org-wide development standards.

_No language-specific instruction files are deployed to `.github/instructions/` in this repo, so
the per-language links block is intentionally omitted per the Copilot Instructions Standard._
