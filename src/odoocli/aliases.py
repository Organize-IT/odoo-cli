"""Model aliases and named conditions.

Knowing that "unpaid customer invoices" means ``account.move`` filtered on
``move_type = out_invoice`` and ``payment_state = not_paid`` is Odoo knowledge,
not information the caller has. An alias carries the model name plus the
clauses that define the business object; a preset names a recurring filter on
it.

Both are pure sugar: they expand to an ordinary domain before anything is sent,
they never change the shape of the result, and the technical model name always
keeps working. Aliases apply to read commands only — writing through a name
that hides a filter would be a good way to create the wrong record.

The tables below ship with the tool. A profile file may add its own under
``[aliases]`` and ``[presets]``; a user entry with a built-in name replaces it,
because the tenant knows its own vocabulary better than this file does.
"""

from __future__ import annotations

import difflib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# Dynamic operands, substituted when a preset is expanded.
TODAY = "@today"
MONTH_START = "@month-start"
YEAR_START = "@year-start"


@dataclass(frozen=True, slots=True)
class Alias:
    """A friendly name for a model, optionally narrowed to a business object."""

    model: str
    domain: tuple[tuple[str, str, Any], ...] = ()
    help: str = ""

    def clauses(self) -> list[list[Any]]:
        return [list(leaf) for leaf in self.domain]


@dataclass(frozen=True, slots=True)
class Preset:
    """A named condition usable wherever ``-w`` is accepted."""

    domain: tuple[tuple[str, str, Any], ...]
    help: str = ""
    models: tuple[str, ...] = field(default=())

    def clauses(self, today: date) -> list[list[Any]]:
        return [[leaf[0], leaf[1], _operand(leaf[2], today)] for leaf in self.domain]


def _operand(value: Any, today: date) -> Any:
    if value == TODAY:
        return today.isoformat()
    if value == MONTH_START:
        return today.replace(day=1).isoformat()
    if value == YEAR_START:
        return today.replace(month=1, day=1).isoformat()
    return value


# ----- aliases -----

ALIASES: Mapping[str, Alias] = {
    "partners": Alias("res.partner", help="Every contact, company or person"),
    "contacts": Alias("res.partner", help="Every contact, company or person"),
    "customers": Alias(
        "res.partner", (("customer_rank", ">", 0),), "Partners that have bought something"
    ),
    "suppliers": Alias("res.partner", (("supplier_rank", ">", 0),), "Partners we buy from"),
    "vendors": Alias("res.partner", (("supplier_rank", ">", 0),), "Partners we buy from"),
    "companies": Alias("res.company", help="Companies of the database (multi-company)"),
    "users": Alias("res.users", help="Odoo users"),
    "invoices": Alias("account.move", (("move_type", "=", "out_invoice"),), "Customer invoices"),
    "bills": Alias("account.move", (("move_type", "=", "in_invoice"),), "Vendor bills"),
    "credit-notes": Alias(
        "account.move", (("move_type", "=", "out_refund"),), "Customer credit notes"
    ),
    "journal-entries": Alias("account.move", help="Every account.move, any type"),
    "payments": Alias("account.payment", help="Customer and vendor payments"),
    "journals": Alias("account.journal", help="Accounting journals"),
    "accounts": Alias("account.account", help="Chart of accounts"),
    "taxes": Alias("account.tax", help="Taxes"),
    "orders": Alias("sale.order", help="Sales orders and quotations"),
    "sales": Alias("sale.order", help="Sales orders and quotations"),
    "quotes": Alias(
        "sale.order", (("state", "in", ["draft", "sent"]),), "Sales orders not confirmed yet"
    ),
    "purchases": Alias("purchase.order", help="Purchase orders"),
    "leads": Alias("crm.lead", help="CRM leads and opportunities"),
    "opportunities": Alias(
        "crm.lead", (("type", "=", "opportunity"),), "CRM records qualified as opportunities"
    ),
    "products": Alias("product.template", help="Product templates"),
    "variants": Alias("product.product", help="Product variants"),
    "pickings": Alias("stock.picking", help="Stock transfers"),
    "transfers": Alias("stock.picking", help="Stock transfers"),
    "employees": Alias("hr.employee", help="Employees"),
    "projects": Alias("project.project", help="Projects"),
    "tasks": Alias("project.task", help="Project tasks"),
    "attachments": Alias("ir.attachment", help="Stored files"),
    "countries": Alias("res.country", help="Countries"),
    "currencies": Alias("res.currency", help="Currencies"),
}


# ----- presets -----

_ANY: tuple[str, ...] = ()
_STATEFUL = ("account.move", "sale.order", "purchase.order")

PRESETS: Mapping[str, Preset] = {
    "archived": Preset((("active", "=", False),), "Only archived records", _ANY),
    "active": Preset((("active", "=", True),), "Only active records", _ANY),
    "draft": Preset((("state", "=", "draft"),), "Not confirmed yet", _STATEFUL),
    "posted": Preset((("state", "=", "posted"),), "Booked in the ledger", ("account.move",)),
    "cancelled": Preset((("state", "=", "cancel"),), "Cancelled by a user", _STATEFUL),
    "unpaid": Preset(
        (("payment_state", "=", "not_paid"),), "Nothing received yet", ("account.move",)
    ),
    "paid": Preset(
        (("payment_state", "in", ["paid", "in_payment"]),), "Settled", ("account.move",)
    ),
    "overdue": Preset(
        (("payment_state", "=", "not_paid"), ("invoice_date_due", "<", TODAY)),
        "Unpaid and past its due date",
        ("account.move",),
    ),
    "this-month": Preset(
        (("invoice_date", ">=", MONTH_START),), "Invoiced this month", ("account.move",)
    ),
    "this-year": Preset(
        (("invoice_date", ">=", YEAR_START),), "Invoiced this year", ("account.move",)
    ),
    "confirmed": Preset((("state", "=", "sale"),), "Confirmed sales order", ("sale.order",)),
    "won": Preset((("stage_id.is_won", "=", True),), "Won opportunities", ("crm.lead",)),
    "lost": Preset((("active", "=", False), ("probability", "=", 0)), "Lost leads", ("crm.lead",)),
    "ready": Preset((("state", "=", "assigned"),), "Transfer ready to process", ("stock.picking",)),
    "done": Preset((("state", "=", "done"),), "Completed transfer", ("stock.picking",)),
}


# ----- registry -----


@dataclass(frozen=True, slots=True)
class Registry:
    """The alias and preset tables in force for one invocation."""

    aliases: Mapping[str, Alias]
    presets: Mapping[str, Preset]

    def resolve(self, name: str) -> Alias | None:
        return self.aliases.get(name.strip().lower())

    def resolve_model(self, name: str) -> str:
        alias = self.resolve(name)
        return alias.model if alias else name

    def suggest(self, name: str) -> list[str]:
        return difflib.get_close_matches(
            name.strip().lower(), sorted(self.aliases), n=3, cutoff=0.6
        )

    def preset(self, model: str, name: str) -> Preset | None:
        found = self.presets.get(name.strip().lower())
        if found is None or (found.models and model not in found.models):
            return None
        return found

    def presets_for(self, model: str | None) -> dict[str, Preset]:
        if model is None:
            return dict(self.presets)
        return {n: p for n, p in self.presets.items() if not p.models or model in p.models}

    def expand(self, model: str, token: str, today: date | None = None) -> list[list[Any]] | None:
        found = self.preset(model, token)
        return None if found is None else found.clauses(today or date.today())

    def rows(self) -> list[dict[str, Any]]:
        """Table-friendly listing, marking which entries came from the config file."""
        return [
            {
                "alias": name,
                "model": alias.model,
                "filter": ", ".join(f"{f} {o} {v}" for f, o, v in alias.domain),
                "presets": ", ".join(sorted(self.presets_for(alias.model))),
                "source": "config" if name not in ALIASES or ALIASES[name] != alias else "builtin",
                "help": alias.help,
            }
            for name, alias in sorted(self.aliases.items())
        ]


BUILTIN = Registry(ALIASES, PRESETS)


def _leaves(raw: Any, where: str) -> tuple[tuple[str, str, Any], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{where}: 'domain' must be a list of [field, operator, value]")
    out: list[tuple[str, str, Any]] = []
    for leaf in raw:
        if not isinstance(leaf, list | tuple) or len(leaf) != 3 or not isinstance(leaf[0], str):
            raise ValueError(
                f"{where}: every clause must be [field, operator, value], got {leaf!r}"
            )
        out.append((str(leaf[0]), str(leaf[1]), leaf[2]))
    return tuple(out)


def from_config(path: Path) -> Registry:
    """Merge ``[aliases]`` and ``[presets]`` from a profile file over the built-in tables.

    A malformed entry raises rather than being skipped: a filter the caller believes is
    applied and is not is exactly the failure this whole mechanism exists to avoid.
    """
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return BUILTIN
    user_aliases = dict(ALIASES)
    for name, table in (raw.get("aliases") or {}).items():
        if not isinstance(table, dict):
            continue
        model = table.get("model")
        if not isinstance(model, str) or "." not in model:
            raise ValueError(f"alias '{name}': 'model' must be a technical Odoo model name")
        user_aliases[name.strip().lower()] = Alias(
            model=model,
            domain=_leaves(table.get("domain"), f"alias '{name}'"),
            help=str(table.get("help", "")),
        )
    user_presets = dict(PRESETS)
    for name, table in (raw.get("presets") or {}).items():
        if not isinstance(table, dict):
            continue
        models = table.get("models") or []
        user_presets[name.strip().lower()] = Preset(
            domain=_leaves(table.get("domain"), f"preset '{name}'"),
            help=str(table.get("help", "")),
            models=tuple(str(m) for m in models) if isinstance(models, list) else (),
        )
    return Registry(user_aliases, user_presets)


# ----- lookup (the built-in tables) -----


def resolve(name: str) -> Alias | None:
    """The alias registered under ``name``, or ``None`` for a technical model name."""
    return ALIASES.get(name.strip().lower())


def resolve_model(name: str) -> str:
    """``name`` mapped through the alias table; unknown names are returned as-is."""
    alias = resolve(name)
    return alias.model if alias else name


def suggest_alias(name: str) -> list[str]:
    return difflib.get_close_matches(name.strip().lower(), sorted(ALIASES), n=3, cutoff=0.6)


def preset(model: str, name: str) -> Preset | None:
    """The preset called ``name`` if it applies to ``model``."""
    found = PRESETS.get(name.strip().lower())
    if found is None:
        return None
    if found.models and model not in found.models:
        return None
    return found


def presets_for(model: str | None) -> dict[str, Preset]:
    if model is None:
        return dict(PRESETS)
    return {n: p for n, p in PRESETS.items() if not p.models or model in p.models}


def expand(model: str, token: str, today: date | None = None) -> list[list[Any]] | None:
    """Expand ``token`` if it names a preset for ``model``, else ``None``."""
    found = preset(model, token)
    if found is None:
        return None
    return found.clauses(today or date.today())


def alias_rows() -> list[dict[str, Any]]:
    """Table-friendly listing of every alias, for ``odoo alias``."""
    rows = []
    for name, alias in sorted(ALIASES.items()):
        rows.append(
            {
                "alias": name,
                "model": alias.model,
                "filter": ", ".join(f"{f} {o} {v}" for f, o, v in alias.domain),
                "presets": ", ".join(sorted(presets_for(alias.model))),
                "help": alias.help,
            }
        )
    return rows
