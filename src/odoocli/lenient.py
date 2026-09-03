"""Opt-in search_read that strips fields Odoo rejects and retries (version drift)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from odoocli.client import AsyncOdooClient, Domain
from odoocli.domain import strip_field_from_domain
from odoocli.errors import OdooError

# "Invalid field 'date_planned'" and "Invalid field account.account.deprecated in condition"
_INVALID_FIELD_RE = re.compile(r"Invalid field '?([\w.]+)'?", re.IGNORECASE)
# "Cannot convert qty_available to SQL because it is not stored" and
# "Field 'is_storable' cannot be used in domain"
_NON_STORED_RE = re.compile(
    r"Cannot convert ([\w.]+) to SQL|[Ff]ield '?([\w.]+)'? cannot be used in domain",
    re.IGNORECASE,
)

Warn = Callable[[dict[str, Any]], None]


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
    on_warning: Warn | None = None,
) -> list[dict[str, Any]]:
    """Like ``client.search_read`` but removes rejected fields and retries.

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
                removed: list[str] = []
                if fields and bad in fields:
                    fields = [f for f in fields if f != bad] or None
                    removed.append("fields")
                if bad in str(domain):
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
                removed = []
                if bad and bad in str(domain):
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
