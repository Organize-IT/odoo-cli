"""Odoo domain helpers: normalisation, de-humanisation, safe field removal, -w DSL."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from odoocli.errors import OdooUsageError

_BINARY_OPS = ("&", "|")
_UNARY_OP = "!"
# Trailing "(#42)" of a humanised many2one ("Name (#42)"), as produced by
# LLM-facing layers. Recovered back to the int id when fed into a domain.
_HUMANIZED_M2O_RE = re.compile(r"\(#(\d+)\)\s*$")
_DROP = object()


# ----- normalisation (ported from UpBoard's OdooConnector) -----


def normalize_domain(domain: Any) -> list[Any]:
    """Accept a list, a JSON string or a Python literal string; keep ``& | !``."""
    if isinstance(domain, list):
        out: list[Any] = []
        for item in domain:
            if isinstance(item, str) and item in ("|", "&", "!"):
                out.append(item)
            elif isinstance(item, str):
                out.extend(normalize_domain(item))
            else:
                out.append(item)
        return out
    if isinstance(domain, str):
        text = domain.strip()
        if not text or text == "[]":
            return []
        parsed: Any = None
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(text)
            except (ValueError, SyntaxError):
                continue
            if isinstance(parsed, list):
                return parsed
        raise OdooUsageError(f"Domain is neither JSON nor a Python list: {text[:80]!r}")
    return []


def dehumanize_operand(value: Any) -> Any:
    """Turn a humanised many2one display value back into its integer id.

    LLM-facing layers often render relational fields as ``"Name (#42)"``.
    When such a string is fed back as a domain operand, recover the trailing
    ``(#42)`` as ``42``. Recurses into lists and tuples; anything else (plain
    ints, ``False``, free text) is returned unchanged.
    """
    if isinstance(value, str):
        m = _HUMANIZED_M2O_RE.search(value)
        return int(m.group(1)) if m else value
    if isinstance(value, list | tuple):
        return [dehumanize_operand(v) for v in value]
    return value


# Backwards-compatible alias (0.2.x imported the private name). Remove in 1.0.
_dehumanize = dehumanize_operand


def sanitize_domain(domain: list[Any]) -> list[Any]:
    """Turn ``"Name (#42)"`` operands on ``id``/``*_id``/``*_ids`` fields back into ints."""
    out: list[Any] = []
    for item in domain:
        if isinstance(item, list | tuple) and len(item) == 3:
            field, op, value = item
            if isinstance(field, str) and (field == "id" or field.endswith(("_id", "_ids"))):
                value = dehumanize_operand(value)
            out.append([field, op, value])
        else:
            out.append(item)
    return out


# ----- safe field removal (used by lenient mode) -----


def _is_leaf(term: Any) -> bool:
    return isinstance(term, list | tuple) and len(term) == 3 and isinstance(term[0], str)


def _parse(tokens: list[Any], pos: int) -> tuple[Any, int]:
    tok = tokens[pos]
    if tok in _BINARY_OPS:
        left, pos = _parse(tokens, pos + 1)
        right, pos = _parse(tokens, pos)
        return ("op2", tok, left, right), pos
    if tok == _UNARY_OP:
        child, pos = _parse(tokens, pos + 1)
        return ("not", child), pos
    return ("leaf", tok), pos + 1


def _serialize(node: Any, bad_field: str) -> Any:
    kind = node[0]
    if kind == "leaf":
        term = node[1]
        if _is_leaf(term) and term[0] == bad_field:
            return _DROP
        return [term]
    if kind == "not":
        child = _serialize(node[1], bad_field)
        return _DROP if child is _DROP else [_UNARY_OP, *child]
    _, operator, left_node, right_node = node
    left = _serialize(left_node, bad_field)
    right = _serialize(right_node, bad_field)
    if left is _DROP and right is _DROP:
        return _DROP
    if left is _DROP:
        return right
    if right is _DROP:
        return left
    return [operator, *left, *right]


def strip_field_from_domain(domain: Any, bad_field: str) -> Any:
    """Remove every leaf on ``bad_field``; ``|``/``&`` fold onto the surviving operand."""
    if not isinstance(domain, list) or not domain:
        return domain
    try:
        cleaned: list[Any] = []
        pos = 0
        while pos < len(domain):
            node, pos = _parse(domain, pos)
            serialized = _serialize(node, bad_field)
            if serialized is not _DROP:
                cleaned.extend(serialized)
        return cleaned
    except (IndexError, TypeError):
        # Malformed domain: leave it alone rather than risk a wrong filter.
        return domain


# ----- -w DSL -----

_WORD_OPS = (
    "not in",
    "in",
    "not ilike",
    "ilike",
    "not like",
    "like",
    "=like",
    "=ilike",
    "child_of",
    "parent_of",
    "not any",
    "any",
)
_WORD_RE = re.compile(
    r"^\s*([A-Za-z_][\w.]*)\s+(" + "|".join(re.escape(o) for o in _WORD_OPS) + r")\s+(.*?)\s*$"
)
_SYMBOL_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(>=|<=|!=|!~|=|>|<|~)\s*(.*?)\s*$")
_SYMBOL_MAP = {"~": "ilike", "!~": "not ilike"}
_LIST_OPS = {"in", "not in"}


def parse_value(raw: str) -> Any:
    """Scalar parsing for -w and -v: quotes, booleans, null, JSON, numbers, else text."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    lowered = text.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no", "null", "none"):
        return False
    if text[:1] in "[{":
        try:
            return json.loads(text)
        except ValueError as e:
            raise OdooUsageError(f"Invalid JSON value: {text[:80]!r}") from e
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_where(expr: str) -> list[Any]:
    """``field op value`` to one Odoo leaf. ``~`` is ilike, ``!~`` is not ilike."""
    m = _WORD_RE.match(expr) or _SYMBOL_RE.match(expr)
    if not m:
        raise OdooUsageError(
            f"Cannot parse condition {expr!r}. Expected 'field=value', 'field>=10', "
            "'field~text', 'field in a,b' or 'field not in a,b'."
        )
    field, op, raw = m.group(1), m.group(2), m.group(3)
    op = _SYMBOL_MAP.get(op, op)
    value: Any
    if op in _LIST_OPS:
        value = (
            parse_value(raw) if raw.startswith("[") else [parse_value(v) for v in raw.split(",")]
        )
        if not isinstance(value, list):
            raise OdooUsageError(f"'{op}' needs a list, got {raw!r}")
    else:
        value = parse_value(raw)
    return [field, op, value]


def build_domain(domain: str | None, where: list[str]) -> list[Any]:
    """AND a JSON domain (optional) with every ``-w`` condition."""
    base = sanitize_domain(normalize_domain(domain)) if domain else []
    return base + [parse_where(w) for w in where]
