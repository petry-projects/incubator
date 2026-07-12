---
artifact: prd
status: draft   # draft | final — the incubation gate requires `final`
---

# PRD — <Idea Title>

<!--
The Product Requirements Document. Owner: John (PM), via the BMAD `bmad-prd` skill
(headless-capable + has a validation checklist — the one artifact with a first-class
machine-checkable gate). Seeded from brief.md; do not restate the brief — decide.
This is the last artifact in the package; a complete PRD is what turns approval into
"begin work as defined."
-->

- **Slug:** `<slug>`
- **Source Discussion:** <link>
- **Seeded from:** `brief.md`
- **Last updated:** <YYYY-MM-DD>

## Vision
The one-paragraph product vision — the change in the world if this ships.

## Target User & JTBD
Primary user(s) and the job(s) to be done this product serves. Reference personas
from the brief; do not re-derive.

## Functional Requirements
The capabilities the product must have, as testable requirements (FR-1, FR-2, …).
Group by user journey where it helps.

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | | must |

## Non-Functional Requirements
Performance, security, privacy, accessibility, cost — whatever constrains the build.

## Success Metrics
How we'll know it worked — the outcome metric(s) and the target(s). Tie back to the
brief's opportunity.

## Scope & Non-Goals
Explicitly in and — just as important — explicitly out for the first build.

## Open Questions
Unresolved decisions the build must not silently guess. (BMAD `bmad-prd` §8.)

## Assumptions
The assumptions this PRD rests on, most-load-bearing first. (BMAD `bmad-prd` §9.)
