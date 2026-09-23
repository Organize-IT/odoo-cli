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
from odoocli.domain import PathMatcher, strip_leaves_from_domain
from odoocli.errors import OdooError, OdooFieldMissingError

# "Invalid field 'mobile' on model 'res.partner'" (read), "Invalid field 'date_planned'",
# "Invalid field account.account.deprecated in condition" / "in leaf" (domain, 15 to 20).
_INVALID_FIELD_RE = re.compile(
    r"Invalid field '?([\w.]+)'?(?: on model '?([\w.]+)'?)?", re.IGNORECASE
)
# "Cannot convert product.product.qty_available to SQL because it is not stored" and
# "Field 'is_storable' cannot be used in domain"
_NON_STORED_RE = re.compile(
    r"Cannot convert ([\w.]+) to SQL|[Ff]ield '?([\w.]+)'? cannot be used in domain",
    re.IGNORECASE,
)

Warn = Callable[[dict[str, Any]], None]


def _rejected(name: str, on_model: str | None, queried: str) -> tuple[str, str]:
    """``(model, field)`` that Odoo rejected, from the name its error message printed.

    ``account.account.deprecated`` is qualified: the model is everything before the last dot.
    A bare name is taken to be on the queried model.
    """
    if on_model:
        return on_model, name.rsplit(".", 1)[-1]
    if "." in name:
        model, field = name.rsplit(".", 1)
        return model, field
    return queried, name


def _path_matcher(queried: str, rejected_model: str, bad_field: str) -> PathMatcher:
    """Which domain paths the rejection is about.

    A rejection on the queried model is about the *first* segment of a path only:
    ``name`` missing on ``sale.order.line`` says nothing about ``product_id.name``, and
    matching it there would refuse, or strip, a filter that is perfectly valid.

    A rejection naming another model (the qualified ``product.product.detailed_type`` form
    Odoo prints for the model the failing segment was resolved on) can only come from a
    deeper segment, so any segment after the first is matched. Segments are compared
    exactly, so a missing ``type`` is never confused with ``move_type``.

    Without the schema this cannot tell a self-referencing path (``parent_id.x`` on
    ``res.partner``) from a root one; such a leaf is not matched and the original error is
    raised, which is the safe way to be wrong.
    """
    if rejected_model == queried:
        return lambda path: path.split(".")[0] == bad_field
    return lambda path: bad_field in path.split(".")[1:]


def _in_domain(domain: Domain, matches: PathMatcher) -> bool:
    """Whether a top-level leaf of ``domain`` has a path ``matches`` accepts."""
    return any(
        isinstance(term, list | tuple)
        and len(term) == 3
        and isinstance(term[0], str)
        and matches(term[0])
        for term in domain
    )


def _field_missing(model: str, bad_field: str, cause: OdooError) -> OdooFieldMissingError:
    return OdooFieldMissingError(
        f"Field {model}.{bad_field} is not available in the domain on this Odoo version",
        model=model,
        field=bad_field,
        where="domain",
        data=cause.data,
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
    ``strip_domain`` is true: then the leaves holding it are removed, dotted paths included
    (the domain only ever widens, see ``strip_leaves_from_domain``) and the rows answer a
    wider question than the one asked. ``_path_matcher`` decides which leaves hold it.

    ``fields`` and ``order`` are only repaired for a rejection on the queried model itself.

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
            non_stored = None if invalid else _NON_STORED_RE.search(text)
            if invalid:
                kind, name, on_model = "invalid_field_removed", invalid.group(1), invalid.group(2)
            elif non_stored:
                kind, on_model = "non_stored_field_removed", None
                name = non_stored.group(1) or non_stored.group(2) or ""
            else:
                raise
            owner, bad = _rejected(name, on_model, model)
            matches = _path_matcher(model, owner, bad)
            in_domain = bool(bad) and _in_domain(domain, matches)
            if in_domain and not strip_domain:
                raise _field_missing(owner, bad, e) from e
            on_root = owner == model
            removed: list[str] = []
            # A non-stored field reads fine, so it never has to leave ``fields``.
            if invalid and on_root and fields and bad in fields:
                fields = [f for f in fields if f != bad] or None
                removed.append("fields")
            if in_domain:
                domain = strip_leaves_from_domain(domain, matches)
                removed.append("domain")
            if on_root and bad and order and bad in order:
                order = _strip_order(order, bad)
                removed.append("order")
            if not removed:
                raise
            if on_warning:
                on_warning({"warning": kind, "field": bad, "from": removed})
    raise OdooError(
        f"Gave up repairing the query after {max_retries} retries", code="retry_exhausted"
    )
