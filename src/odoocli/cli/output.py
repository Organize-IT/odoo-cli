"""Render data for stdout. json is the source of truth; table and csv are for humans."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from rich.console import Console
from rich.table import Table

FORMATS = ("json", "jsonl", "table", "csv")
_MAX_CELL = 60


def detect_format(explicit: str | None, isatty: bool) -> str:
    if explicit:
        return explicit
    return "table" if isatty else "json"


def _is_m2o(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], int)
        and isinstance(value[1], str)
    )


def _cell(value: Any) -> str:
    if value is False or value is None:
        return ""
    if _is_m2o(value):
        return f"{value[1]} (#{value[0]})"
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, list | dict) else str(value)
    return text if len(text) <= _MAX_CELL else text[: _MAX_CELL - 3] + "..."


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for key in row:
            if key not in cols:
                cols.append(key)
    if "id" in cols:
        cols.remove("id")
        cols.insert(0, "id")
    return cols


def _as_rows(data: Any, table_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if table_rows is not None:
        return table_rows
    if isinstance(data, list) and all(isinstance(r, dict) for r in data):
        return data
    if isinstance(data, dict):
        return [data]
    return None


def _table(rows: list[dict[str, Any]]) -> str:
    cols = _columns(rows)
    table = Table(show_lines=False, header_style="bold")
    for col in cols:
        table.add_column(col)
    for row in rows:
        table.add_row(*(_cell(row.get(c)) for c in cols))
    buf = io.StringIO()
    console = Console(file=buf, width=200, force_terminal=False, color_system=None)
    console.print(table)
    return buf.getvalue().rstrip("\n")


def _csv(rows: list[dict[str, Any]]) -> str:
    cols = _columns(rows)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                c: (json.dumps(v, ensure_ascii=False) if isinstance(v, list | dict) else v)
                for c, v in row.items()
                if c in cols
            }
        )
    return buf.getvalue().rstrip("\n")


def render(data: Any, fmt: str, *, table_rows: list[dict[str, Any]] | None = None) -> str:
    """Return the text to print for ``data`` in ``fmt``. Empty string means print nothing."""
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    if fmt == "jsonl":
        items = data if isinstance(data, list) else [data]
        return "\n".join(json.dumps(i, ensure_ascii=False) for i in items)
    rows = _as_rows(data, table_rows)
    if rows is None:
        # Scalars and unknown shapes: fall back to compact JSON.
        return json.dumps(data, ensure_ascii=False)
    if not rows:
        return ""
    return _table(rows) if fmt == "table" else _csv(rows)
