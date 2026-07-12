# incubator

Front-of-funnel home for **pre-product** work in `petry-projects`: raw idea
Discussions that aren't yet a product, the **decision brief / PRD-lite** an idea
is judged on, and **disposable POCs**. When a POC proves out, the idea
**graduates to its own product repo** — it does not grow up here.

This repo is the missing pre-product stage of the org ideation pipeline
(`petry-projects/.github-private` → `feature-ideation` → `idea-triage` →
`idea:approved` → `initiative-planner`). Approved *products* already own their
PRDs in their own repos (`_bmad-output/planning-artifacts/`); this repo is where
an idea lives **before** it earns a repo of its own.

## Lifecycle

| Stage | Gate | Where it lives |
|-------|------|----------------|
| Raw idea capture | — | **Discussions** here (Ideas category) — for ideas not tied to an existing product repo |
| Enhancement + **decision brief / PRD-lite** (Mary, Analyst) | before `idea:approved` | `ideas/<slug>/` in this repo |
| **POC / spike** (throwaway) | after `idea:approved` | `pocs/<slug>/` in this repo |
| POC needing real CI / deploy / dependency isolation | — | a **disposable** standalone `poc-<slug>` repo |
| **Graduation** to a real product | after the POC proves out | a **new product repo** (full BMAD PRD by John, PM) |

The hard rule: **graduation is a boundary, not organic growth.** A proven POC
seeds a *new* product repo where the full PRD is written. Keeping the incubator
small is what keeps `dev-lead` / `pr-review` pointed at real products.

## Layout

```
ideas/
  <slug>/
    brief.md            # decision brief / PRD-lite — the go/no-go artifact
    market-research.md  # competitive / market context (Mary, Analyst)
    ost.md              # Mermaid opportunity-solution-tree
  _TEMPLATE/            # copy this folder to start a new idea
pocs/
  <slug>/               # throwaway spikes; archive or delete freely
```

## How an idea moves through here

1. **Capture** — open a Discussion in the **Ideas** category (or one is filed for
   you). Ideas that clearly belong to an existing product go in *that* product's
   repo instead; cross-cutting or net-new ideas come here.
2. **Brief** — once an idea reaches "Ripe" in `idea-triage`, copy `ideas/_TEMPLATE/`
   to `ideas/<slug>/` and let **Mary** fill `brief.md` (problem, market context,
   JTBD, RICE/ICE, key assumptions + cheapest test, recommendation). The brief —
   not a bare idea — is what a human decides `idea:approved` on.
   Discovery precedes the PRD: the brief exists to *inform* the go/no-go, never to
   substitute for it.
3. **Go/no-go** — a human applies `idea:approved` (or declines). Declined ideas
   stay as a closed Discussion / archived folder — cheap to keep, easy to revisit.
4. **POC** — spin a spike under `pocs/<slug>/` (default) or, only if it needs its
   own CI/deploy/deps, a disposable `poc-<slug>` repo. Prefer the *cheapest*
   testable artifact — a working spike often decides faster than more documents.
5. **Graduate** — if the POC proves out, create a new product repo from
   `petry-projects/repo-template`; the `brief.md` seeds John's full PRD there.
   Archive the incubator folder.

## Conventions

- **`<slug>`** — short kebab-case, stable, matches the Discussion where practical.
- **Ideas that die cost nothing** — do not delete history; close/archive so the
  reasoning stays searchable for the next person (or agent).
- **Nothing here is a product.** No production dependencies, no user-facing
  deploys, no long-lived infrastructure. If it needs those, it's time to graduate.

---

Baseline scaffolding (workflows, CODEOWNERS, LICENSE, SECURITY) comes from
`petry-projects/repo-template`; see [BOOTSTRAP.md](./BOOTSTRAP.md) for the
one-time per-repo setup and [AGENTS.md](./AGENTS.md) for the org-standards pointer.
