"""Value normalization shared by the judge and the adapters."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def collapse_whitespace(value: object) -> str | None:
    """Return ``value`` as a string with runs of whitespace collapsed to one space.

    ``None`` stays ``None`` so that "not set" and "empty" remain distinguishable.
    """
    if value is None:
        return None
    return _WHITESPACE.sub(" ", str(value)).strip()
