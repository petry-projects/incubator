"""Shared text matching for the review scanners (resented_giants.py, deep_dive.py)."""

import re


def cat_pattern(terms):
    """Compile terms into one boundary-aware regex, so 'ads' matches 'ads' / 'so many ads'
    but not 'heads', and 'charge' doesn't match 'discharge'. A word boundary is added only
    where the term's edge is alphanumeric, so phrases and symbols (e.g. '$') still match
    literally."""
    parts = []
    for term in terms:
        left = r"\b" if term[:1].isalnum() else ""
        right = r"\b" if term[-1:].isalnum() else ""
        parts.append(left + re.escape(term) + right)
    return re.compile("|".join(parts))
