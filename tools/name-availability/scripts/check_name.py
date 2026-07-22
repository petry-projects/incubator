#!/usr/bin/env python3
"""Check a name's availability across domains, GitHub, package registries and
(best-effort) social handles.

Read-only. Safe to run anytime. Prefers Cloudflare's authoritative domain-check
(which also returns price) when CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID are
set; otherwise falls back to RDAP.

Usage:
    python scripts/check_name.py "Acme Co"
    python scripts/check_name.py "Acme Co" --tlds com,io,ai --no-social
    python scripts/check_name.py "Acme Co" --json out.json --fail-on domain:com,github

Env:
    CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID   optional, for authoritative domains
    BRAND_GH_TOKEN (or GITHUB_TOKEN)              optional, raises GitHub rate limit
"""
from __future__ import annotations

import argparse
import os
import sys

import common as c


def _resolve_domains(sess, slug, tlds, cf_token, cf_account) -> list[c.Result]:
    domains = [f"{slug}.{t}" for t in tlds]
    if cf_token and cf_account:
        try:
            cf_map = c.cloudflare_domain_check(sess, cf_account, cf_token, domains)
            out = [cf_map[d] for d in domains if d in cf_map]
            missing = [d for d in domains if d not in cf_map]
            out.extend(c.rdap_domain(sess, d) for d in missing)
            return out
        except Exception as e:  # noqa: BLE001 - fall back to RDAP on any CF failure
            print(f"[warn] Cloudflare domain-check failed ({e}); using RDAP", file=sys.stderr)
    return [c.rdap_domain(sess, d) for d in domains]


def main() -> int:
    p = argparse.ArgumentParser(description="Check a name everywhere (read-only).")
    p.add_argument("name", help="Name to check, e.g. 'Acme Co'")
    p.add_argument("--tlds", default=",".join(c.DEFAULT_TLDS), help="Comma-separated TLDs")
    p.add_argument("--social", action=argparse.BooleanOptionalAction, default=True, help="Check social handles")
    p.add_argument("--json", dest="json_path", default="", help="Write full results to this JSON path")
    p.add_argument(
        "--fail-on",
        default="",
        help="Comma list of critical channels; exit 1 if any is not available. "
        "e.g. 'domain:com,github,npm'",
    )
    args = p.parse_args()

    name = args.name
    slug = c.slugify(name)
    if not slug:
        print(f"[error] '{name}' produces an empty slug — name must contain at least one alphanumeric character", file=sys.stderr)
        return 1
    tlds = [t.strip().lstrip(".") for t in args.tlds.split(",") if t.strip()]
    sess = c.make_session()
    gh_token = os.environ.get("BRAND_GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    cf_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    cf_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")

    results: list[c.Result] = []

    # Domains --------------------------------------------------------------
    results.extend(_resolve_domains(sess, slug, tlds, cf_token, cf_account))

    # GitHub, packages -----------------------------------------------------
    results.append(c.github_handle(sess, slug, gh_token))
    results.append(c.npm_package(sess, slug))
    results.append(c.pypi_package(sess, slug))

    # Social ---------------------------------------------------------------
    if args.social:
        for platform in c.SOCIAL:
            results.append(c.social_handle(sess, platform, slug))

    # Output ---------------------------------------------------------------
    md = c.to_markdown(name, slug, results)
    print(md)
    c.write_summary(md)
    if args.json_path:
        c.dump_json(args.json_path, name, slug, results)

    critical = [k.strip() for k in args.fail_on.split(",") if k.strip()]
    if critical:
        ok, detail = c.verdict(results, critical)
        banner = f"\n{'✅ CLEAR' if ok else '❌ CONFLICT'} — {detail}"
        print(banner)
        c.write_summary(banner)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
