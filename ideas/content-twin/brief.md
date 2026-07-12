# Decision Brief — ContentTwin

<!--
The decision brief / PRD-lite. This is the artifact a human decides `idea:approved`
on. It exists to INFORM the go/no-go with discovery evidence — it does not replace
discovery, and it is not the full PRD (that gets written in the product repo after
graduation). Owner: Mary (Analyst). Keep it tight — a page or two.
-->

- **Slug:** `content-twin`
- **Source Discussion:** https://github.com/petry-projects/incubator/discussions/6
- **Source repo (canonical home):** https://github.com/petry-projects/ContentTwin — ContentTwin's canonical home remains its own repo. This incubator entry is for **ideation tracking only**, not a move.
- **Author / owner:** don-petry
- **Status:** `draft`
- **Last updated:** 2026-07-12

> **Provenance note (read first).** Almost everything below the "current state" line is
> **synthesized from a single grounded source: the repo's one-line GitHub description.**
> The ContentTwin repo contains no README, no spec, no PRD, and no product code — only
> org-standard scaffolding. Claims that are not directly supported by repo content are
> explicitly flagged **[ASSUMPTION]**. No market figures are invented; where a number
> would normally go, this brief says "unknown — needs discovery" instead.

## 0. Grounded current state (what actually exists)

Everything in this section is directly observable in `petry-projects/ContentTwin` as of 2026-07-12:

- Repo created **2026-03-26**; primary language **Shell**; ~1.3 MB on disk.
- **No product code.** The only source is org-standard scaffolding: `scripts/apply-repo-settings.sh`, `scripts/setup-rulesets.sh`, CI/lint workflows, reusable-workflow caller stubs, LICENSE, SECURITY, and AGENTS/CLAUDE pointer files.
- **No README** describing the product; **0 Discussions**; **no PRD/brief**.
- The product concept exists **only in the repo's GitHub description**: _"AI-powered Social Media Agent for small organizations — enterprise-quality social presence at non-profit pricing."_
- `.github/copilot-instructions.md` **contradicts** the description — it calls ContentTwin "a repository security and analysis settings automation tool." This is templated boilerplate that leaked from the org repo-template; it is **not** evidence of the actual product direction. Treat it as noise.
- A scheduled **"ContentTwin Audit — content pipeline issues"** agent files a daily issue referencing an empty `queue/` content-pipeline directory. **No `queue/` directory exists in the repo.** The audited pipeline is aspirational/described, not built — the audit is running against a hypothetical.
- `feature-ideation.yml` still carries the placeholder `project_context` (`TODO: Replace this…`) — the ideation automation was never pointed at the product.

**Bottom line:** ContentTwin is a name and a one-line value proposition with a repo that has never held product code. Maturity ≈ pre-POC ideation.

## 1. Problem

Small organizations and non-profits need a consistent, credible social-media presence to reach donors, volunteers, members, and beneficiaries — but they rarely have a dedicated social/marketing hire, and agency retainers are out of budget. The work (planning a calendar, drafting on-brand posts, sizing/formatting per platform, publishing on cadence, keeping it up week after week) is real and recurring, and it is usually the first thing to lapse when a 2–5 person org is stretched. **[ASSUMPTION — not evidenced in repo]** this pain is acute enough that small orgs would adopt and pay for an AI agent that does most of it; the repo asserts the value prop but provides no discovery evidence (interviews, waitlist, usage) behind it.

## 2. Target user & JTBD

- **Who:** Small organizations and non-profits (roughly the "no dedicated social-media person, can't afford an agency" band). The exact segment — e.g. faith orgs, local charities, small clinics, community groups — is **unknown; needs discovery.**
- **Job to be done:** When _I'm running a small org with no marketing staff_, I want to _keep a steady, on-brand social presence without hiring or learning agency-grade tooling_, so I can _reach and grow my audience (donors/volunteers/members) without it eating my week_.

## 3. Market & competitive context

How this is solved today (see `market-research.md` — currently a **TODO/needs-discovery** scaffold, not researched):

- **Manual / DIY** — someone at the org posts ad hoc; free but inconsistent, the default that lapses.
- **SMB social schedulers** (Buffer, Hootsuite, Later, and similar) — mature, but priced/positioned for SMBs and marketers, and they schedule; they don't *do the thinking/drafting*. **[ASSUMPTION]** they are the incumbent alternative most small orgs would compare against.
- **General AI writing tools** (ChatGPT et al.) — can draft a post but leave planning, brand consistency, formatting, and publishing to the user.
- **Agencies / freelancers** — full-service but priced out of the target band.

**The wedge (hypothesis):** an *agent* that closes the loop — plan → draft on-brand → format per platform → publish on cadence — at non-profit pricing, so the org gets "agency-quality output" without agency cost or a scheduler's manual drafting burden. **This wedge is a hypothesis, not a validated finding.** Market size, willingness-to-pay, and the real competitive set are **unknown — needs discovery.** No market figures are asserted here.

## 4. Opportunity → solution

See `ost.md` (scaffolded from the concept; solution branches are hypotheses to be tested):

- **Desired outcome (metric):** a target org sustains a consistent posting cadence with minimal human effort — e.g. _% of weeks that hit planned post volume with < X minutes of human time_. Exact metric **TBD in discovery.**
- **Opportunity addressed:** "I can't keep up a credible social presence without staff or budget."
- **Proposed solution(s) [all hypotheses]:** an AI agent that (a) builds a content calendar from a light brand/brief input, (b) drafts on-brand posts, (c) adapts them per platform, (d) publishes on a schedule with a human approval gate.

## 5. Value & feasibility (rough)

- **Impact:** **Unscored — insufficient evidence.** The value prop is plausible but there is zero demand signal in-repo. Potential upside is real *if* the JTBD and willingness-to-pay hold.
- **Effort:** **High / multi-month.** Nothing is built. A real product implies platform API integrations (posting to multiple social networks, each with its own auth/review/policy surface), an LLM content pipeline, brand/state storage, scheduling, and a human-approval UX — from a standing start.
- **Prioritization score — ICE (deliberately low-confidence):**
  - **Impact = 3/5** — plausible, unvalidated pain in a real segment.
  - **Confidence = 1/5** — grounded in a one-line description only; no interviews, no usage, no market data.
  - **Ease = 2/5** — greenfield build with multiple third-party publishing integrations and their policy/compliance overhead.
  - **ICE = 3 × 1 × 2 = 6 / 125 (≈ 0.05 normalized).** _Reasoning shown so the low confidence is legible: this score is dominated by the confidence gap, not by a belief the idea is bad. The cheap move is to buy confidence with discovery (§6), which is exactly what a POC/spike is for — not to greenlight a multi-month build on a one-liner._

## 6. Riskiest assumptions & cheapest test

Most-dangerous first:

| # | Assumption | If wrong… | Cheapest test | Result |
|---|-----------|-----------|---------------|--------|
| 1 | Small orgs/non-profits actually feel this pain enough to adopt & pay | Whole premise fails | 5–10 problem interviews with target-band orgs; a fake-door landing page measuring signups against the exact value prop | — |
| 2 | An *agent* (auto plan→draft→publish) is wanted over a cheaper scheduler or a plain AI drafting tool | Wrong product shape; we rebuild a crowded category | Show 3–5 orgs a clickable/Wizard-of-Oz "agent" flow; measure preference & willingness-to-pay vs. Buffer/ChatGPT | — |
| 3 | "Enterprise-quality" AI-drafted, auto-published content is safe/on-brand enough that orgs trust it | Trust/brand-safety kills retention; every post needs heavy human editing | Wizard-of-Oz: hand-run the pipeline for 1–2 real orgs for 2 weeks; measure edit rate & approval friction | — |
| 4 | Multi-platform publishing is technically/politically feasible at non-profit price (API access, review, rate limits, policy) | Unit economics or platform policy sink "non-profit pricing" | 1-day spike: enumerate posting-API requirements/costs/app-review for the 2 target platforms | — |

## 7. Recommendation (go / no-go)

**Recommendation: do NOT treat this as an approved product yet — advance it as an ideation item and buy confidence before any build.** The concept is coherent and the segment is real, but the entire brief rests on a single one-line description with no discovery behind it, and the ICE confidence term reflects that. This is a textbook incubator case: the cheapest next artifact is *evidence*, not code.

**What a POC would need to prove to graduate:**
1. **Demand** — target-band orgs confirm the pain and show intent (interview signal + fake-door signups against the real value prop).
2. **Product shape** — orgs prefer an *agent* that closes the loop over a scheduler or a plain drafting tool, and will pay at a non-profit-friendly price point.
3. **Trust/quality** — a Wizard-of-Oz run shows AI-drafted, human-approved posts land with an acceptably low edit rate.
4. **Feasibility of "non-profit pricing"** — multi-platform publishing is achievable within a viable cost envelope (a spike confirms API access, review, and rate/policy constraints for the first two platforms).

If those hold, ContentTwin graduates to a full PRD in its own repo. Until then, keep it here as a tracked idea.

**Hard gate:** the go/no-go is a human's, applied via `idea:approved`. This brief informs that decision; it does not make it.

## 8. Open questions

- **Which** small-org segment first? (Non-profit is stated; the specific vertical/wedge is unknown.)
- **Which platforms** are must-have vs. nice-to-have for v1 publishing?
- What does **"non-profit pricing"** actually mean as a number, and does it survive multi-platform API/LLM unit costs?
- How much **human-in-the-loop** approval is acceptable before the "agent" promise erodes?
- Is the mislabeled `copilot-instructions.md` / the phantom `queue/` audit a sign of an **earlier, abandoned direction** for this repo, or just template drift? (Affects how much prior intent to read into the scaffolding.)
- Why has the repo sat at scaffolding-only since **2026-03-26** — deprioritized, blocked, or simply not started?
