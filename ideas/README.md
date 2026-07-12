# ideas/

One folder per idea that has passed `idea-triage` and earned a **decision brief**.
Start a new one by copying [`_TEMPLATE/`](./_TEMPLATE/) to `ideas/<slug>/`.

```
ideas/<slug>/
  brief.md            # decision brief / PRD-lite — the go/no-go artifact (Mary)
  market-research.md  # competitive / market context (Mary)
  ost.md              # Mermaid opportunity-solution-tree
```

- **`<slug>`** — short, kebab-case, stable; match the source Discussion where you can.
- The **brief is the artifact a human decides `idea:approved` on** — it informs the
  go/no-go, it does not replace it (discovery precedes the PRD).
- Ideas that don't make the cut stay here as-is (or archived) so the reasoning
  remains searchable. Don't delete.
- On **graduation**, the `brief.md` seeds the full PRD in the new product repo;
  archive the folder here.
