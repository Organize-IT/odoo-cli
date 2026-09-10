"""Model schema read from Odoo, cached on disk, used to catch typos locally.

Odoo answers a misspelled field name with a server-side exception, which costs a
round trip and produces a message an agent has to parse. This module fetches
``fields_get`` once per model, keeps it in ``~/.cache/odoo-cli`` and validates
field names — including dotted paths such as ``partner_id.country_id.code`` —
before anything is sent.

Nothing here is authoritative: when the schema cannot be read (no access to the
model, an old server, a network hiccup) validation is skipped rather than
guessed. A false "field does not exist" would be worse than no check at all.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odoocli.client import AsyncOdooClient
from odoocli.errors import OdooError, OdooUsageError

logger = logging.getLogger("odoocli.schema")

CACHE_VERSION = 1
DEFAULT_TTL = 24 * 3600
ENV_CACHE_DIR = "ODOO_CACHE_DIR"
ENV_TTL = "ODOO_SCHEMA_TTL"
ENV_NO_VALIDATE = "ODOO_NO_VALIDATE"

# What we need to validate a path: the type and relation drive traversal,
# store/searchable/sortable drive the "not stored" warning.
SCHEMA_ATTRIBUTES = [
    "string",
    "type",
    "store",
    "relation",
    "required",
    "searchable",
    "sortable",
]

# Relational types whose ``relation`` can be followed by a dotted path.
_RELATIONAL = frozenset({"many2one", "one2many", "many2many"})

# A field path we are willing to reason about. Anything else (an operator-only
# leaf, a computed expression) is left to the server.
_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

_SUGGEST_CUTOFF = 0.55
_SUGGEST_MAX = 3

Fields = dict[str, dict[str, Any]]


# ----- cache location -----


def cache_dir(env: Mapping[str, str]) -> Path:
    if env.get(ENV_CACHE_DIR):
        return Path(env[ENV_CACHE_DIR]).expanduser()
    base = env.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "odoo-cli"


def _slug(url: str, database: str) -> str:
    raw = f"{url.rstrip('/')}|{database}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-")[:120] or "default"


def cache_file(env: Mapping[str, str], url: str, database: str) -> Path:
    return cache_dir(env) / f"schema-{_slug(url, database)}.json"


def ttl_seconds(env: Mapping[str, str]) -> int:
    raw = env.get(ENV_TTL, "").strip()
    if not raw:
        return DEFAULT_TTL
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL


# ----- suggestions -----


def suggest(name: str, candidates: list[str]) -> list[str]:
    """Closest field names: fuzzy matches first, then prefix/substring hits."""
    close = difflib.get_close_matches(name, candidates, n=_SUGGEST_MAX, cutoff=_SUGGEST_CUTOFF)
    if len(close) < _SUGGEST_MAX:
        lowered = name.lower()
        extra = [c for c in candidates if lowered and lowered in c.lower() and c not in close]
        close.extend(sorted(extra, key=len)[: _SUGGEST_MAX - len(close)])
    return close[:_SUGGEST_MAX]


@dataclass(slots=True)
class FieldProblem:
    """One unknown field, with the path it was reached through."""

    model: str
    path: str
    unknown: str
    suggestions: list[str]

    def sentence(self) -> str:
        where = f" (in {self.path!r})" if self.path != self.unknown else ""
        text = f"{self.model} has no field {self.unknown!r}{where}"
        if self.suggestions:
            head, *rest = self.suggestions
            text += f". Did you mean {head!r}?"
            if rest:
                text += " (also: " + ", ".join(rest) + ")"
        return text


def usage_error(problems: list[FieldProblem]) -> OdooUsageError:
    """Turn field problems into the exit-2 error the CLI prints. Nothing was sent."""
    message = "; ".join(p.sentence() for p in problems)
    return OdooUsageError(
        message,
        code="unknown_field",
        data={
            "unknown_fields": [
                {
                    "model": p.model,
                    "path": p.path,
                    "field": p.unknown,
                    "suggestions": p.suggestions,
                }
                for p in problems
            ]
        },
    )


# ----- store -----


class SchemaStore:
    """``fields_get`` results for one connection, memoised in RAM and on disk.

    ``fields()`` returns ``None`` whenever the schema cannot be obtained; every
    caller treats that as "skip validation".
    """

    def __init__(
        self,
        url: str,
        database: str,
        *,
        env: Mapping[str, str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.url = url
        self.database = database
        self.env: Mapping[str, str] = env if env is not None else os.environ
        self.enabled = enabled
        self.path = cache_file(self.env, url, database)
        self.ttl = ttl_seconds(self.env)
        self._memory: dict[str, Fields] = {}
        self._disk: dict[str, Any] | None = None
        self._dirty = False

    # -- disk --

    def _load_disk(self) -> dict[str, Any]:
        if self._disk is not None:
            return self._disk
        data: dict[str, Any] = {"version": CACHE_VERSION, "models": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("version") == CACHE_VERSION:
                models = raw.get("models")
                if isinstance(models, dict):
                    data["models"] = models
        except (OSError, ValueError):
            pass  # unreadable or stale format: start over, never fail a command
        self._disk = data
        return data

    def flush(self) -> None:
        """Persist newly fetched models. Cache failures are never fatal."""
        if not self._dirty or self._disk is None or self.ttl == 0:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._disk, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError as e:
            logger.debug("cannot write schema cache %s: %s", self.path, e)

    def _from_disk(self, model: str) -> Fields | None:
        if self.ttl == 0:
            return None
        entry = self._load_disk()["models"].get(model)
        if not isinstance(entry, dict):
            return None
        fetched_at = entry.get("fetched_at")
        fields = entry.get("fields")
        if not isinstance(fetched_at, int | float) or not isinstance(fields, dict):
            return None
        if time.time() - float(fetched_at) > self.ttl:
            return None
        return dict(fields)

    def _to_disk(self, model: str, fields: Fields) -> None:
        if self.ttl == 0:
            return
        self._load_disk()["models"][model] = {"fetched_at": int(time.time()), "fields": fields}
        self._dirty = True

    # -- fetch --

    async def fields(self, client: AsyncOdooClient, model: str) -> Fields | None:
        if not self.enabled:
            return None
        if model in self._memory:
            return self._memory[model]
        cached = self._from_disk(model)
        if cached is not None:
            self._memory[model] = cached
            return cached
        try:
            fetched = await client.fields_get(model, SCHEMA_ATTRIBUTES)
        except OdooError as e:
            # No access to the model, unknown model, server too old: stay quiet
            # and let the real call produce the real error.
            logger.debug("no schema for %s: %s", model, e)
            return None
        self._memory[model] = fetched
        self._to_disk(model, fetched)
        return fetched


# ----- validation -----


def _is_checkable(path: str) -> bool:
    return bool(_PATH_RE.match(path))


async def resolve_path(
    store: SchemaStore, client: AsyncOdooClient, model: str, path: str
) -> tuple[dict[str, Any] | None, FieldProblem | None]:
    """Walk a dotted path. Returns the final field description, or the problem.

    ``(None, None)`` means "no opinion": the schema was unavailable somewhere
    along the way.
    """
    current = model
    parts = path.split(".")
    for index, part in enumerate(parts):
        fields = await store.fields(client, current)
        if fields is None:
            return None, None
        if part not in fields:
            return None, FieldProblem(current, path, part, suggest(part, sorted(fields)))
        description = fields[part]
        last = index == len(parts) - 1
        if last:
            return description, None
        relation = description.get("relation")
        if description.get("type") not in _RELATIONAL or not isinstance(relation, str):
            # Traversing a non-relational field: Odoo will reject it, but the
            # message it produces is clearer than anything we could invent.
            return None, None
        current = relation
    return None, None


@dataclass(slots=True)
class SchemaReport:
    """Outcome of validating one command's field usage."""

    problems: list[FieldProblem]
    not_stored: list[tuple[str, str]]  # (path, context) pairs

    def raise_if_unknown(self) -> None:
        if self.problems:
            raise usage_error(self.problems)


def _order_fields(order: str | None) -> list[str]:
    if not order:
        return []
    out = []
    for part in order.split(","):
        token = part.strip().split()
        if token:
            out.append(token[0])
    return out


def domain_fields(domain: list[Any]) -> list[str]:
    """Field paths used by the leaves of a domain (operators are ignored)."""
    out: list[str] = []
    for term in domain:
        if isinstance(term, list | tuple) and len(term) == 3 and isinstance(term[0], str):
            out.append(term[0])
    return out


async def check(
    store: SchemaStore,
    client: AsyncOdooClient,
    model: str,
    *,
    fields: list[str] | None = None,
    domain: list[Any] | None = None,
    order: str | None = None,
    values: list[str] | None = None,
) -> SchemaReport:
    """Validate every field name a command is about to use.

    ``domain`` and ``order`` reach the database, so fields that are not stored
    are reported separately: Odoo rejects them and the message is cryptic.
    """
    problems: list[FieldProblem] = []
    not_stored: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    async def one(path: str, context: str, needs_storage: bool) -> None:
        if not _is_checkable(path) or (path, context) in seen:
            return
        seen.add((path, context))
        description, problem = await resolve_path(store, client, model, path)
        if problem is not None:
            if not any(p.path == problem.path and p.unknown == problem.unknown for p in problems):
                problems.append(problem)
            return
        if description is None or not needs_storage:
            return
        stored = bool(description.get("store", True))
        # Odoo exposes ``searchable``/``sortable`` on most versions; a field can
        # be unstored yet searchable through a custom ``search=``. Only warn
        # when every signal we have says no.
        usable = bool(description.get("searchable", stored) or description.get("sortable", stored))
        if not stored and not usable:
            not_stored.append((path, context))

    for path in domain_fields(domain or []):
        await one(path, "domain", True)
    for path in _order_fields(order):
        await one(path, "order", True)
    for path in fields or []:
        await one(path, "fields", False)
    for path in values or []:
        await one(path, "values", False)

    return SchemaReport(problems=problems, not_stored=not_stored)
