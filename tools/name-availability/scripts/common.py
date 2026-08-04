"""Shared helpers for name-availability tooling.

Read-only availability primitives + output formatting, shared by
check_name.py and register_name.py. No secrets are hardcoded — tokens are
read from the environment by the callers and passed in.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict

import requests

DEFAULT_TLDS = ["com", "io", "ai", "co", "app", "dev", "org", "net"]

# Handle-based channels. {h} is the slugified name.
SOCIAL = {
    "x": "https://x.com/{h}",
    "instagram": "https://www.instagram.com/{h}/",
    "tiktok": "https://www.tiktok.com/@{h}",
    "youtube": "https://www.youtube.com/@{h}",
    "linkedin": "https://www.linkedin.com/company/{h}",
}

# Where a human goes to actually claim each social handle (register_name prints these).
SOCIAL_SIGNUP = {
    "x": "https://x.com/i/flow/signup",
    "instagram": "https://www.instagram.com/accounts/emailsignup/",
    "tiktok": "https://www.tiktok.com/signup",
    "youtube": "https://www.youtube.com/create_channel",
    "linkedin": "https://www.linkedin.com/company/setup/new/",
}

AVAILABLE, TAKEN, UNKNOWN, ERROR = "AVAILABLE", "TAKEN", "UNKNOWN", "ERROR"
ICON = {AVAILABLE: "🟢", TAKEN: "🔴", UNKNOWN: "🟡", ERROR: "⚠️"}

USER_AGENT = "name-availability/1.0"


@dataclass
class Result:
    channel: str            # domain | github | npm | pypi | social
    target: str             # acme.com | acme | instagram:acme
    status: str             # AVAILABLE | TAKEN | UNKNOWN | ERROR
    detail: str = ""
    url: str = ""
    price: float | None = None
    confidence: str = "high"  # high | low (social checks are low)
    currency: str = "USD"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def slugify(name: str) -> str:
    """'Acme Co' -> 'acmeco'. Domain/handle/package safe."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# --------------------------------------------------------------------------- #
# Availability checks (all read-only)
# --------------------------------------------------------------------------- #
def rdap_domain(sess: requests.Session, domain: str) -> Result:
    """Domain availability via RDAP (rdap.org bootstraps to the authoritative registry).

    rdap.org returns 302 to the authoritative RDAP server for TLDs it knows.
    A bootstrap 404 means no RDAP authority exists for that TLD (UNKNOWN).
    Only the authoritative server's 404 means the domain is unregistered (AVAILABLE).
    """
    url = f"https://rdap.org/domain/{domain}"
    try:
        r = sess.get(url, timeout=20, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308):
            redirect_url = r.headers.get("Location")
            if not redirect_url:
                return Result("domain", domain, UNKNOWN, "RDAP redirect without Location", f"https://{domain}")
            r2 = sess.get(redirect_url, timeout=20, allow_redirects=True)
            if r2.status_code == 404:
                return Result("domain", domain, AVAILABLE, "RDAP: no record", f"https://{domain}")
            if r2.status_code == 200:
                return Result("domain", domain, TAKEN, "RDAP: registered", f"https://{domain}")
            return Result("domain", domain, UNKNOWN, f"RDAP HTTP {r2.status_code} — verify manually", f"https://{domain}")
        if r.status_code == 404:
            return Result("domain", domain, UNKNOWN, "RDAP: no authority for TLD", f"https://{domain}")
        if r.status_code == 200:
            return Result("domain", domain, TAKEN, "RDAP: registered", f"https://{domain}")
        return Result("domain", domain, UNKNOWN, f"RDAP HTTP {r.status_code} — verify manually", f"https://{domain}")
    except requests.RequestException as e:
        return Result("domain", domain, UNKNOWN, f"RDAP error: {e}", f"https://{domain}")


def cloudflare_domain_check(sess, account_id, token, domains) -> dict:
    """POST /registrar/domain-check — authoritative availability + price.

    Returns {domain: Result}. On any API error, raises so the caller can fall
    back to RDAP. Response shape: result.domains[].{name, registrable, reason, pricing}.
    Only reason=="domain_unavailable" maps to TAKEN; other non-registrable values
    (e.g. extension_not_supported_via_api) map to UNKNOWN so callers fall back to RDAP.
    """
    base = f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
    r = sess.post(
        f"{base}/registrar/domain-check",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"domains": list(domains)},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if not body.get("success", True):
        errors = body.get("errors", [])
        raise RuntimeError(f"Cloudflare API error: {errors}")
    out: dict[str, Result] = {}
    for item in body.get("result", {}).get("domains", []):
        name = item.get("name")
        if name is None:
            continue
        registrable = item.get("registrable")
        reason = item.get("reason", "")
        pricing = item.get("pricing") or {}
        price_raw = pricing.get("registration_cost")
        currency = pricing.get("currency", "USD")
        try:
            price = float(price_raw) if price_raw is not None else None
        except (TypeError, ValueError):
            price = None
        if registrable is True:
            out[name] = Result("domain", name, AVAILABLE, "Cloudflare: available", f"https://{name}", price=price, currency=currency)
        elif registrable is False and reason == "domain_unavailable":
            out[name] = Result("domain", name, TAKEN, "Cloudflare: registered", f"https://{name}", price=price, currency=currency)
        else:
            out[name] = Result("domain", name, UNKNOWN, f"Cloudflare: {reason or 'indeterminate'}", f"https://{name}", price=price, currency=currency)
    return out


def github_handle(sess: requests.Session, handle: str, token: str | None) -> Result:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/users/{handle}"
    web = f"https://github.com/{handle}"
    try:
        r = sess.get(url, headers=headers, timeout=20)
        if r.status_code == 404:
            return Result("github", handle, AVAILABLE, "no such user/org", web)
        if r.status_code == 200:
            return Result("github", handle, TAKEN, r.json().get("type", "account"), web)
        if r.status_code == 403:
            return Result("github", handle, UNKNOWN, "rate limited — set BRAND_GH_TOKEN", web)
        return Result("github", handle, UNKNOWN, f"HTTP {r.status_code}", web)
    except requests.RequestException as e:
        return Result("github", handle, ERROR, str(e), web)


def _registry_404_means_free(sess, name, url, channel, web) -> Result:
    try:
        r = sess.get(url, timeout=20)
        if r.status_code == 404:
            return Result(channel, name, AVAILABLE, "unregistered", web)
        if r.status_code == 200:
            return Result(channel, name, TAKEN, "registered", web)
        return Result(channel, name, UNKNOWN, f"HTTP {r.status_code}", web)
    except requests.RequestException as e:
        return Result(channel, name, ERROR, str(e), web)


def npm_package(sess, name) -> Result:
    return _registry_404_means_free(
        sess, name, f"https://registry.npmjs.org/{name}", "npm", f"https://www.npmjs.com/package/{name}"
    )


def pypi_package(sess, name) -> Result:
    return _registry_404_means_free(
        sess, name, f"https://pypi.org/pypi/{name}/json", "pypi", f"https://pypi.org/project/{name}/"
    )


def social_handle(sess, platform, handle) -> Result:
    """Best-effort ONLY. Login walls make this unreliable, so every social
    result is marked low-confidence — treat it as a hint plus a link, not proof.
    """
    url = SOCIAL[platform].format(h=handle)
    target = f"{platform}:{handle}"
    try:
        r = sess.get(url, timeout=20, allow_redirects=False)
        if r.status_code == 404:
            return Result("social", target, AVAILABLE, "profile 404 (low confidence)", url, confidence="low")
        if r.status_code == 200:
            return Result("social", target, TAKEN, "profile loads (low confidence)", url, confidence="low")
        return Result("social", target, UNKNOWN, f"HTTP {r.status_code} — verify by hand", url, confidence="low")
    except requests.RequestException as e:
        return Result("social", target, UNKNOWN, f"{e} — verify by hand", url, confidence="low")


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def to_markdown(name: str, slug: str, results: list[Result]) -> str:
    lines = [f"## Name check — `{name}`  (slug `{slug}`)", ""]
    order = ["domain", "github", "npm", "pypi", "social"]
    titles = {"domain": "Domains", "github": "GitHub", "npm": "npm", "pypi": "PyPI", "social": "Social (low confidence)"}
    for ch in order:
        rows = [r for r in results if r.channel == ch]
        if not rows:
            continue
        lines.append(f"### {titles[ch]}")
        lines.append("| | Target | Status | Detail | Price |")
        lines.append("|---|---|---|---|---|")
        for r in rows:
            if r.price is not None:
                price = f"${r.price:.2f}" if r.currency == "USD" else f"{r.price:.2f} {r.currency}"
            else:
                price = ""
            tgt = f"[{r.target}]({r.url})" if r.url else r.target
            lines.append(f"| {ICON.get(r.status, '')} | {tgt} | {r.status} | {r.detail} | {price} |")
        lines.append("")
    return "\n".join(lines)


def verdict(results: list[Result], critical: list[str]) -> tuple[bool, str]:
    """critical = e.g. ['domain:com', 'github']. Name is 'clear' when every
    critical channel is AVAILABLE."""
    problems = []
    for key in critical:
        if ":" in key:
            ch, suffix = key.split(":", 1)
            matches = [r for r in results if r.channel == ch and r.target.endswith("." + suffix)]
        else:
            matches = [r for r in results if r.channel == key]
        if not matches or any(m.status != AVAILABLE for m in matches):
            problems.append(key)
    return (not problems), (", ".join(problems) if problems else "all critical channels available")


def write_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


def dump_json(path: str, name: str, slug: str, results: list[Result]) -> None:
    base = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(path)
    if not resolved.startswith(base + os.sep):
        raise ValueError(f"Output path escapes the working directory: {path!r}")
    with open(resolved, "w", encoding="utf-8") as f:
        json.dump({"name": name, "slug": slug, "results": [asdict(r) for r in results]}, f, indent=2)
