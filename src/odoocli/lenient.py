"""search_read that repairs fields Odoo rejects and retries (version drift).

Dropping a field from ``fields`` or ``order`` changes the shape of the answer, never which
records it holds, so it is always repaired. Dropping one from the domain widens the query:
the caller asked for cash accounts and would get every account. That is only done when the
caller opts in with ``strip_domain=True``; otherwise ``OdooFieldMissingError`` is raised and
nothing is replayed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from odoocli.client import AsyncOdooClient, Domain
from odoocli.domain import strip_field_from_domain
from odoocli.errors import OdooError, OdooFieldMissingError

# "Invalid field 'date_planned'" and "Invalid field account.account.deprecated in condition"
_INVALID_FIELD_RE = re.compile(r"Invalid field '?([\w.]+)'?", re.IGNORECASE)
# "Cannot convert qty_available to SQL because it is not stored" and
# "Field 'is_storable' cannot be used in domain"
_NON_STORED_RE = re.compile(
    r"Cannot convert ([\w.]+) to SQL|[Ff]ield '?([\w.]+)'? cannot be used in domain",
    re.IGNORECASE,
)

Warn = Callable[[dict[str, Any]], None]


def _in_domain(domain: Domain, bad_field: str) -> bool:
    """Whether a leaf of ``domain`` names ``bad_field``, directly or as a path segment.

    Exact on segments, so a missing ``type`` is not confused with ``move_type``.
    """
    return any(
        isinstance(term, list | tuple)
        and len(term) == 3
        and isinstance(term[0], str)
        and bad_field in term[0].split(".")
        for term in domain
    )


def _field_missing(model: str, bad_field: str) -> OdooFieldMissingError:
    return OdooFieldMissingError(
        f"Field {model}.{bad_field} is not available in the domain on this Odoo version",
        model=model,
        field=bad_field,
        where="domain",
    )


def _strip_order(order: str, bad_field: str) -> str | None:
    parts = [p.strip() for p in order.split(",") if p.strip() and p.strip().split()[0] != bad_field]
    return ", ".join(parts) if parts else None


async def lenient_search_read(
    client: AsyncOdooClient,
    model: str,
    domain: Domain | None,
    fields: list[str] | None,
    limit: int | None,
    offset: int,
    order: str | None,
    *,
    max_retries: int = 3,
    strip_domain: bool = False,
    on_warning: Warn | None = None,
) -> list[dict[str, Any]]:
    """Like ``client.search_read`` but removes rejected fields and retries.

    A rejected field in ``fields`` or ``order`` is removed and the query replayed. A rejected
    field in the domain raises ``OdooFieldMissingError`` before any replay, unless
    ``strip_domain`` is true: then its leaves are removed (the domain only ever widens, see
    ``strip_field_from_domain``) and the rows answer a wider question than the one asked.

    Every removal is reported through ``on_warning`` as
    ``{"warning": <kind>, "field": <name>, "from": ["fields" | "domain" | "order", ...]}``.
    """
    domain = list(domain or [])
    fields = list(fields) if fields else None
    for _ in range(max_retries + 1):
        try:
            return await client.search_read(model, domain, fields, limit, offset, order)
        except OdooError as e:
            text = e.message
            invalid = _INVALID_FIELD_RE.search(text)
            if invalid:
                bad = invalid.group(1).split(".")[-1]
                in_domain = _in_domain(domain, bad)
                if in_domain and not strip_domain:
                    raise _field_missing(model, bad) from e
                removed: list[str] = []
                if fields and bad in fields:
                    fields = [f for f in fields if f != bad] or None
                    removed.append("fields")
                if in_domain:
                    domain = strip_field_from_domain(domain, bad)
                    removed.append("domain")
                if order and bad in order:
                    order = _strip_order(order, bad)
                    removed.append("order")
                if removed:
                    if on_warning:
                        on_warning(
                            {"warning": "invalid_field_removed", "field": bad, "from": removed}
                        )
                    continue
                raise
            non_stored = _NON_STORED_RE.search(text)
            if non_stored:
                bad = (non_stored.group(1) or non_stored.group(2) or "").split(".")[-1]
                in_domain = bool(bad) and _in_domain(domain, bad)
                if in_domain and not strip_domain:
                    raise _field_missing(model, bad) from e
                removed = []
                if in_domain:
                    domain = strip_field_from_domain(domain, bad)
                    removed.append("domain")
                if bad and order and bad in order:
                    order = _strip_order(order, bad)
                    removed.append("order")
                if removed:
                    if on_warning:
                        on_warning(
                            {"warning": "non_stored_field_removed", "field": bad, "from": removed}
                        )
                    continue
            raise
    raise OdooError(
        f"Gave up repairing the query after {max_retries} retries", code="retry_exhausted"
    )
