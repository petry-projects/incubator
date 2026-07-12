# pocs/

Throwaway spikes for ideas that have passed the `idea:approved` gate and need a
**testable artifact** to answer their riskiest assumption. A working spike often
decides go/no-go faster than more documents.

```
pocs/<slug>/     # one folder per POC; match the idea's slug
```

## Rules

- **Disposable by default.** A POC exists to answer a question, then it's archived
  or deleted. It is not a product and must not accumulate production dependencies,
  user-facing deploys, or long-lived infrastructure.
- **Default to a subfolder here.** Only spin a standalone `poc-<slug>` repo when the
  spike genuinely needs its own CI / deploy / dependency isolation — and mark that
  repo disposable so it never masquerades as a product.
- **Record the verdict.** When a POC concludes, note what it proved or disproved in
  the idea's `brief.md` (§6 assumptions table). A dead POC with a recorded reason is
  worth more than a silent deletion.
- **Graduation ≠ growth.** If the POC proves out, create a *new* product repo from
  `petry-projects/repo-template` and start the real build there. Don't grow the POC
  in place.
