#!/usr/bin/env python3
"""Reserve a name across the channels it is SAFE to automate.

Safety model — real domain registration (which spends money) only happens when
ALL of these are true:
  1. --execute is passed            (default is a dry run)
  2. --confirm matches the name     (typo guard)
  3. env BRAND_ALLOW_SPEND == "yes" (a secret; without it, spend is blocked)
  4. each domain's price <= --max-price
On top of that, the GitHub Actions workflow runs in a protected Environment, so
a human must approve the run before any of this executes.

What it does:
  * Domains  -> Cloudflare registration (guarded as above)
  * GitHub   -> creates a private placeholder repo to claim the name
  * Packages -> PRINTS ready-to-run reserve commands (never auto-publishes)
  * Social   -> PRINTS a signup checklist with deep links (never automated)

Usage (dry run):
    python scripts/register_name.py "Acme Co" --tlds com,io,ai
Usage (real, from the approved workflow):
    python scripts/register_name.py "Acme Co" --tlds com,io,ai \
        --execute --confirm "Acme Co" --max-price 40

Env:
    CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID   domains
    BRAND_ALLOW_SPEND=yes                         master switch for real spend
    REGISTRANT_* (see build_contact)              registrant WHOIS contact
    BRAND_GH_TOKEN                                GitHub repo creation (repo scope)
    BRAND_GH_ORG                                  optional: create repo in an org
"""
from __future__ import annotations

import argparse
import os
import sys

import common as c

CF_API = "https://api.cloudflare.com/client/v4"


def build_contact() -> dict | None:
    """Registrant contact from env. Cloudflare needs this for a real
    registration. Field names may need tweaking against the current API —
    dry-run prints the payload so you can validate before executing."""
    required = ["FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE", "ADDRESS", "CITY", "STATE", "ZIP", "COUNTRY"]
    vals = {k: os.environ.get(f"REGISTRANT_{k}", "") for k in required}
    if not all(vals.values()):
        return None
    return {
        "first_name": vals["FIRST_NAME"],
        "last_name": vals["LAST_NAME"],
        "organization": os.environ.get("REGISTRANT_ORG", ""),
        "email": vals["EMAIL"],
        "phone": vals["PHONE"],
        "address": vals["ADDRESS"],
        "city": vals["CITY"],
        "state": vals["STATE"],
        "zip": vals["ZIP"],
        "country": vals["COUNTRY"],
    }


def cf_register(sess, account_id, token, domain, contact, years, dry_run) -> str:
    payload = {"name": domain, "years": years, "auto_renew": True, "privacy": True, "contact": contact}
    endpoint = f"{CF_API}/accounts/{account_id}/registrar/registrations"
    if dry_run:
        safe = dict(payload, contact={"…": "REGISTRANT_* from env (hidden)"})
        return f"DRY RUN — would POST {endpoint} :: {safe}"
    r = sess.post(
        endpoint,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if r.status_code in (200, 201):
        body = r.json()
        if not body.get("success", True):
            errors = body.get("errors", [])
            raise RuntimeError(f"Cloudflare registration reported failure for {domain}: {errors}")
        return f"REGISTERED {domain}"
    raise RuntimeError(f"Cloudflare registration failed for {domain}: HTTP {r.status_code}")


def gh_create_repo(sess, token, org, slug, dry_run) -> str:
    if dry_run:
        where = f"orgs/{org}" if org else "user"
        return f"DRY RUN — would create private repo '{slug}' under {where}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Skip if it already exists
    who = org or _gh_login(sess, headers)
    exists = sess.get(f"https://api.github.com/repos/{who}/{slug}", headers=headers, timeout=20)
    if exists.status_code == 200:
        return f"SKIP — repo {who}/{slug} already exists"
    url = f"https://api.github.com/orgs/{org}/repos" if org else "https://api.github.com/user/repos"
    body = {"name": slug, "private": True, "description": f"Reserved name: {slug}", "auto_init": True}
    r = sess.post(url, headers=headers, json=body, timeout=30)
    if r.status_code == 201:
        return f"CREATED {r.json().get('full_name')}"
    raise RuntimeError(f"GitHub repo create failed: HTTP {r.status_code}")


def _gh_login(sess, headers) -> str:
    r = sess.get("https://api.github.com/user", headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()["login"]


def log(summary: list[str], line: str) -> None:
    print(line)
    summary.append(line)


def _try_register_domain(sess, cf_account, cf_token, d, avail, contact, dry_run, allow_spend, max_price, years, summary):
    res = avail.get(d)
    if not res or res.status != c.AVAILABLE:
        log(summary, f"- ⏭️ `{d}` — {res.detail if res else 'availability unknown'} (skip)")
        return
    price = res.price
    if price is None:
        log(summary, f"- 🛑 `{d}` — price unknown; skipping (cannot enforce price cap)")
        return
    if price > max_price:
        log(summary, f"- 🛑 `{d}` — ${price:.0f} exceeds --max-price ${max_price:.0f} (skip)")
        return
    if not dry_run:
        # Gate 3 + contact presence
        if not allow_spend:
            log(summary, f"- 🔒 `{d}` — BRAND_ALLOW_SPEND != 'yes'; refusing to spend (skip)")
            return
        if not contact:
            log(summary, f"- 🔒 `{d}` — REGISTRANT_* contact not set; cannot register (skip)")
            return
    try:
        msg = cf_register(sess, cf_account, cf_token, d, contact, years, dry_run)
        price_s = f" (${price:.0f})" if price is not None else ""
        log(summary, f"- {'🟡' if dry_run else '✅'} `{d}`{price_s} — {msg}")
    except Exception as e:  # noqa: BLE001
        log(summary, f"- ❌ `{d}` — {e}")


def _register_domains(sess, slug, tlds, cf_token, cf_account, dry_run, allow_spend, max_price, years, summary):
    summary.append("### Domains")
    if not (cf_token and cf_account):
        log(summary, "- ⚠️ CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID not set — skipping domains")
        return
    domains = [f"{slug}.{t}" for t in tlds]
    try:
        avail = c.cloudflare_domain_check(sess, cf_account, cf_token, domains)
    except Exception as e:  # noqa: BLE001
        log(summary, f"- ⚠️ domain-check failed ({e}); skipping domain registration")
        avail = {}
    contact = build_contact()
    for d in domains:
        _try_register_domain(sess, cf_account, cf_token, d, avail, contact, dry_run, allow_spend, max_price, years, summary)


def _register_github(sess, gh_token, gh_org, slug, dry_run, summary):
    summary.append("\n### GitHub")
    if not gh_token:
        log(summary, "- ⚠️ BRAND_GH_TOKEN not set — skipping GitHub repo")
        return
    try:
        log(summary, f"- {'🟡' if dry_run else '✅'} {gh_create_repo(sess, gh_token, gh_org, slug, dry_run)}")
    except Exception as e:  # noqa: BLE001
        log(summary, f"- ❌ GitHub — {e}")


def main() -> int:
    p = argparse.ArgumentParser(description="Reserve a name where it is safe to automate.")
    p.add_argument("name")
    p.add_argument("--tlds", default="com,io,ai")
    p.add_argument("--execute", action="store_true", help="Actually act. Omit for a dry run.")
    p.add_argument("--confirm", default="", help="Must equal the name when --execute is set.")
    p.add_argument("--max-price", type=float, default=40.0, help="Abort a domain over this price (USD).")
    p.add_argument("--years", type=int, default=1)
    p.add_argument("--skip-domains", action="store_true")
    p.add_argument("--skip-github", action="store_true")
    args = p.parse_args()

    name, slug = args.name, c.slugify(args.name)
    if not slug:
        print(f"[error] '{name}' produces an empty slug — name must contain at least one alphanumeric character", file=sys.stderr)
        return 2
    tlds = [t.strip().lstrip(".") for t in args.tlds.split(",") if t.strip()]
    dry_run = not args.execute
    sess = c.make_session()
    summary: list[str] = [f"## Register — `{name}` (slug `{slug}`)  {'· DRY RUN' if dry_run else '· EXECUTE'}", ""]

    # Gate 2: confirm matches
    if args.execute and c.slugify(args.confirm) != slug:
        print(f"[abort] --confirm '{args.confirm}' does not match name '{name}'", file=sys.stderr)
        return 2

    cf_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    cf_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    gh_token = os.environ.get("BRAND_GH_TOKEN")
    gh_org = os.environ.get("BRAND_GH_ORG", "").strip() or None
    allow_spend = os.environ.get("BRAND_ALLOW_SPEND", "").lower() == "yes"

    if not args.skip_domains:
        _register_domains(sess, slug, tlds, cf_token, cf_account, dry_run, allow_spend, args.max_price, args.years, summary)

    if not args.skip_github:
        _register_github(sess, gh_token, gh_org, slug, dry_run, summary)

    # --- Packages (print, never auto-publish) -----------------------------
    summary.append("\n### Packages — reserve by hand (not auto-published)")
    log(summary, f"- npm:  `npm init -y && npm publish --access public`  (name: `{slug}`)")
    log(summary, f"- PyPI: build a stub sdist then `twine upload dist/*`  (name: `{slug}`)")

    # --- Social (never automated) -----------------------------------------
    summary.append("\n### Social — claim by hand")
    for platform, signup in c.SOCIAL_SIGNUP.items():
        log(summary, f"- {platform}: `@{slug}` → {signup}")

    c.write_summary("\n".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
