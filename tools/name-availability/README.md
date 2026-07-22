# name-availability

Repeatable name availability + reservation, runnable locally or as GitHub
Actions. Point it at any candidate name and it reports where that name is free.

Two tools:

| Workflow | Script | Side effects |
|---|---|---|
| **Name check** | `scripts/check_name.py` | none — read-only |
| **Name register** | `scripts/register_name.py` | reserves domains / GitHub; guarded |

## What each channel does

**check** → domains (Cloudflare `domain-check`, authoritative + price; RDAP
fallback), GitHub org/user, npm, PyPI, and best-effort social handles (login
walls make social low-confidence — treat as a hint plus a link).

**register** → reserves only what is safe to automate:
- **Domains** — Cloudflare registration, behind three gates (below).
- **GitHub** — creates a private placeholder repo to claim the name.
- **Packages** — prints ready-to-run `npm publish` / `twine upload` commands
  (does **not** auto-publish).
- **Social** — prints a signup checklist with deep links. Account creation is
  **not** automated — platform anti-bot + ToS make it a good way to get banned,
  and it's out of scope by design.

## Safety gates on real domain spend

Money moves only when **all** hold:
1. The workflow runs in the **`brand-register` Environment** — protect it with
   required reviewers so a human approves each run.
2. `execute` is checked (default is a **dry run** that prints the exact request).
3. Secret **`BRAND_ALLOW_SPEND=yes`** is set (master kill-switch).
4. Each domain's price is **≤ `max_price`**.

Plus `--confirm` must match the name (typo guard) and `REGISTRANT_*` contact
must be present.

## Setup

**Secrets** (repo → Settings → Secrets and variables → Actions):

| Secret | For |
|---|---|
| `CLOUDFLARE_API_TOKEN` | domains (token with Registrar read/write) |
| `CLOUDFLARE_ACCOUNT_ID` | domains |
| `BRAND_GH_TOKEN` | PAT with `repo` scope, to create the placeholder repo |
| `BRAND_ALLOW_SPEND` | set to `yes` only when you want real registration |
| `REGISTRANT_FIRST_NAME` … `REGISTRANT_COUNTRY` | WHOIS contact (see below) |

Variables (optional): `BRAND_GH_ORG` to create the repo in an org.

Registrant contact keys: `REGISTRANT_FIRST_NAME`, `_LAST_NAME`, `_ORG`
(optional), `_EMAIL`, `_PHONE`, `_ADDRESS`, `_CITY`, `_STATE`, `_ZIP`,
`_COUNTRY`.

**Protect the environment**: Settings → Environments → `brand-register` →
add a required reviewer.

## Usage

**GitHub**: Actions tab → *Name check* / *Name register* → Run workflow.
Register defaults to a dry run — review the job summary, then re-run with
`execute` checked (it pauses for approval).

**Local** (read-only check needs no secrets beyond the optional ones):

```bash
cd tools/name-availability
pip install -r requirements.txt
python scripts/check_name.py "Acme Co" --tlds com,io,ai
# dry-run reservation:
python scripts/register_name.py "Acme Co" --tlds com,io,ai
```

## Caveats

- The Cloudflare registrar **registration** API is recent. If a call 4xxs,
  confirm the endpoint/payload in the current Cloudflare API docs and adjust
  `cloudflare_domain_check` / `cf_register`. Dry-run prints the exact request so
  you can validate first. Premium domains aren't supported by the API.
- Social checks are **low-confidence** by nature — always eyeball the handle.
- This is not trademark clearance.
