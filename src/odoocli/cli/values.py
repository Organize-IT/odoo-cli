"""Parsing of -v key=value pairs, id lists and JSON arguments."""

from __future__ import annotations

import json
from typing import Any

from odoocli.domain import parse_value
from odoocli.errors import OdooUsageError


def parse_ids(tokens: list[str]) -> list[int]:
    ids: list[int] = []
    for tok in tokens:
        for part in tok.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError as e:
                raise OdooUsageError(f"Record id must be an integer, got {part!r}") from e
    if not ids:
        raise OdooUsageError("At least one record id is required")
    return ids


def parse_kv(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key.strip():
            raise OdooUsageError(f"Expected key=value, got {pair!r}")
        out[key.strip()] = parse_value(raw)
    return out


def parse_json_arg(text: str | None, kind: str) -> Any:
    if text is None or not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError as e:
        raise OdooUsageError(f"--{kind} must be valid JSON: {e}") from e


def split_fields(text: str | None) -> list[str] | None:
    if text is None:
        return None
    fields = [f.strip() for f in text.split(",") if f.strip()]
    return fields or None
