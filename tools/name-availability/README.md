# name-availability

Repeatable name availability + reservation. Point it at any candidate name and
it reports where that name is free — domains, GitHub, package registries, and
(best-effort) social handles.

The GitHub workflows here are **reusable** (`workflow_call` only). Because this
repository is public, they are deliberately **not** directly runnable: a direct
run would publish the name and domains on the public Actions tab. Instead a
**private caller repo** invokes them, so every run's logs, job summary, and
artifacts stay private. You can also run the scripts locally.

Two tools:

| Reusable workflow | Script | Side effects |
|---|---|---|
| `.github/workflows/name-check.yml` | `scripts/check_name.py` | none — read-only |
| `.github/workflows/name-register.yml` | `scripts/register_name.py` | reserves domains / GitHub; guarded |

## What each channel does

**check** → domains (Cloudflare `domain-check`, authoritative + price; RDAP
fallback), GitHub org/user, npm, PyPI, and best-effort social handles (login
walls make social low-confidence — treat as a hint plus a link).

**register** → reserves only what is safe to automate:
- **Domains** — Cloudflare registration, behind the gates below.
- **GitHub** — creates a private placeholder repo to claim the name.
- **Packages** — prints ready-to-run `npm publish` / `twine upload` commands
  (does **not** auto-publish).
- **Social** — prints a signup checklist with deep links. Account creation is
  **not** automated.

## Private usage (reusable workflow pattern)

In a **private** repo you control, add caller workflows and put the secrets and
the approval Environment there. Runs then live only in that private repo.

```yaml
# .github/workflows/check.yml in your PRIVATE repo
name: Check name
on:
  workflow_dispatch:
    inputs:
      name: { description: "Name to check", required: true }
jobs:
  check:
    uses: petry-projects/incubator/.github/workflows/name-check.yml@main
    with:
      name: ${{ inputs.name }}
      source_ref: main  # pin to a tag or SHA for reproducible runs, e.g. v1.2.3
    secrets: inherit
```

```yaml
# .github/workflows/register.yml in your PRIVATE repo
name: Register name
on:
  workflow_dispatch:
    inputs:
      name: { description: "Name to reserve", required: true }
      execute: { description: "EXECUTE? unchecked = dry run", type: boolean, default: false }
jobs:
  approve:
    runs-on: ubuntu-latest
    environment: brand-register     # protect with required reviewers HERE
    steps: [{ run: "echo Approved ${{ inputs.name }}" }]
  register:
    needs: approve
    uses: petry-projects/incubator/.github/workflows/name-register.yml@main
    with:
      name: ${{ inputs.name }}
      execute: ${{ inputs.execute }}
      source_ref: main  # pin to a tag or SHA for reproducible runs, e.g. v1.2.3
    secrets: inherit
```

## Safety gates on real domain spend

Money moves only when **all** hold:
1. The caller's **`brand-register` Environment** approves the run (required reviewer).
2. `execute` is true (default is a **dry run** that prints the exact request).
3. Secret **`BRAND_ALLOW_SPEND=yes`** is set (master kill-switch).
4. Each domain's price is **≤ `max_price`**.

Plus a `--confirm` typo guard and a required `REGISTRANT_*` contact.

## Secrets (set them in the PRIVATE caller repo)

| Secret | For |
|---|---|
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` | domains |
| `BRAND_GH_TOKEN` | PAT with `repo` scope, to create the placeholder repo |
| `BRAND_GH_ORG` | optional: create the repo in an org |
| `BRAND_ALLOW_SPEND` | set to `yes` only when you want real registration |
| `REGISTRANT_FIRST_NAME` … `REGISTRANT_COUNTRY` | WHOIS contact |

## Local usage

```bash
cd tools/name-availability
pip install -r requirements.txt
python scripts/check_name.py "Acme Co" --tlds com,io,ai
python scripts/register_name.py "Acme Co" --tlds com,io,ai      # dry run
```

## Caveats

- The Cloudflare registrar **registration** API is recent. If a call 4xxs,
  confirm the endpoint/payload in the current Cloudflare API docs and adjust
  `cloudflare_domain_check` / `cf_register`. Dry-run prints the exact request.
- Social checks are **low-confidence** — always eyeball the handle.
- This is not trademark clearance.
