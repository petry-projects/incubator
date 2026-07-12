# The incubation package

An idea graduates from "logged" to "approved to build" by accumulating a **complete
package** of artifacts on a single, long-lived **incubation PR**. The PR stays open
(and red) while the package is assembled through the human⇄agent loop in the idea's
Discussion; when the package is complete and a code owner approves, **that approval is
the authorization to begin work on the idea as defined**.

## Required artifacts

Each lives at `ideas/<slug>/<file>` (start from [`_TEMPLATE/`](./_TEMPLATE/)). The
machine-readable contract is [`package-spec.json`](./package-spec.json); the CI gate
(`.github/workflows/incubation-gate.yml`) enforces it.

| Artifact | File | Producer | Today |
|----------|------|----------|-------|
| Brainstorm | `brainstorm.md` | Mary (Analyst) | **Human-facilitated** in the Discussion — BMAD's brainstorm skill is interactive, not headless |
| Market & competitive research | `market-research.md` | Mary (Analyst) | **Human-facilitated** — likewise interactive today |
| Decision brief / PRD-lite | `brief.md` | Mary (Analyst) | Headless-capable |
| PRD | `prd.md` | John (PM), `bmad-prd` | Headless + has a validation checklist |

`ost.md` (opportunity-solution-tree) is a **supporting** artifact — encouraged, not gate-required.

> Fast-follow: headless producers + machine validators for brainstorm and
> market-research are being built in `petry-projects/bmad-bgreat-suite` so the whole
> package can eventually be agent-generated and validated, not just structurally checked.

## What "done" means (what the gate checks)

For every required artifact, the gate requires **all** of:
1. **Present** — the file exists at `ideas/<slug>/<file>`.
2. **Final** — frontmatter `status: final` (templates ship `status: draft`).
3. **Structured** — its required section headers are present (see `package-spec.json`).
4. **Filled** — no leftover template placeholders (`<Idea Title>`, `<slug>`,
   `TODO — needs discovery`, …).

The gate posts a single checklist comment on the PR showing exactly which boxes are
still open, and updates it on every push. When every box is checked the gate goes
green.

> This is the **structural** tier. The PRD additionally has a BMAD validation
> checklist that will be wired as a second, content-quality tier; other artifacts get
> validators as they're built in bgreat-suite.

## The flow

1. **Capture** — idea Discussion (Ideas category).
2. **Assemble** — open an incubation PR (`incubate/<slug>` or `onboard/<slug>`) and
   grow `ideas/<slug>/` through the Discussion loop: Mary facilitates brainstorm +
   market research, drafts the brief; John generates the PRD from the brief. Mark each
   artifact `status: final` as it lands.
3. **Gate** — the PR stays red until the package is complete; the checklist comment
   shows what's missing.
4. **Approve = go** — a green gate **plus** a code-owner approval (the `pr-quality`
   ruleset) authorizes work to begin. Merge records the decision; the idea then
   graduates to its own product repo.

## Running the gate locally

```bash
scripts/incubation-gate.sh ideas/<slug>     # check one package
scripts/incubation-gate.sh --all            # check every package
```
