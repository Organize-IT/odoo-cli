"""Property tests for the domain algebra.

A wrong domain does not raise: it returns the wrong rows, quietly, and a bulk command then
operates on records nobody asked for. These tests check the algebra against a small evaluator
rather than against remembered examples.

The invariant that matters is about ``strip_field_from_domain``: removing a field it cannot
filter on may only ever *widen* the result. Every record the original domain matched must
still be matched afterwards -- losing a match would mean the repaired query silently dropped
a record the caller asked for.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from odoocli.domain import normalize_domain, parse_where, sanitize_domain, strip_field_from_domain

FIELDS = ("a", "b", "c")
VALUES = (0, 1)


# ----- a minimal Odoo domain evaluator, used only as an oracle -----


def _parse(tokens: list[Any], pos: int) -> tuple[Any, int]:
    token = tokens[pos]
    if token in ("&", "|"):
        left, pos = _parse(tokens, pos + 1)
        right, pos = _parse(tokens, pos)
        return (token, left, right), pos
    if token == "!":
        child, pos = _parse(tokens, pos + 1)
        return ("!", child), pos
    return ("leaf", token), pos + 1


def matches(domain: list[Any], record: dict[str, Any]) -> bool:
    """Evaluate a prefix-notation domain the way Odoo does: top level is an implicit AND."""
    pos = 0
    while pos < len(domain):
        node, pos = _parse(domain, pos)
        if not _evaluate(node, record):
            return False
    return True


def _evaluate(node: Any, record: dict[str, Any]) -> bool:
    kind = node[0]
    if kind == "leaf":
        field, _operator, value = node[1]
        return bool(record.get(field) == value)
    if kind == "!":
        return not _evaluate(node[1], record)
    _, left, right = node
    if kind == "&":
        return _evaluate(left, record) and _evaluate(right, record)
    return _evaluate(left, record) or _evaluate(right, record)


# ----- generators -----

leaves = st.tuples(st.sampled_from(FIELDS), st.just("="), st.sampled_from(VALUES)).map(
    lambda leaf: [list(leaf)]
)


def _expressions(depth: int = 3) -> st.SearchStrategy[list[Any]]:
    if depth == 0:
        return leaves
    smaller = _expressions(depth - 1)
    return st.one_of(
        leaves,
        st.tuples(st.sampled_from(["&", "|"]), smaller, smaller).map(
            lambda t: [t[0], *t[1], *t[2]]
        ),
        smaller.map(lambda child: ["!", *child]),
    )


domains = st.lists(_expressions(), min_size=1, max_size=2).map(
    lambda parts: [item for part in parts for item in part]
)
records = st.fixed_dictionaries({field: st.sampled_from(VALUES) for field in FIELDS})


# ----- the invariant -----


@given(domains, st.sampled_from(FIELDS), st.lists(records, min_size=1, max_size=8))
def test_stripping_a_field_can_only_widen_the_result(
    domain: list[Any], field: str, sample: list[dict[str, Any]]
) -> None:
    """Repairing a query may return more rows than asked for. It may never return fewer."""
    stripped = strip_field_from_domain(domain, field)
    for record in sample:
        if matches(domain, record):
            assert matches(stripped, record), (
                f"{record} matched {domain} but not {stripped} after removing {field!r}"
            )


@given(domains, st.sampled_from(FIELDS))
def test_no_leaf_on_the_removed_field_survives(domain: list[Any], field: str) -> None:
    stripped = strip_field_from_domain(domain, field)
    leaves_left = [t for t in stripped if isinstance(t, list) and len(t) == 3]
    assert all(leaf[0] != field for leaf in leaves_left)


@given(domains, st.sampled_from(FIELDS), st.lists(records, min_size=1, max_size=8))
def test_removing_an_absent_field_changes_nothing(
    domain: list[Any], field: str, sample: list[dict[str, Any]]
) -> None:
    absent = "not_a_field"
    stripped = strip_field_from_domain(domain, absent)
    for record in sample:
        assert matches(stripped, record) == matches(domain, record)


@given(domains, st.sampled_from(FIELDS))
def test_the_result_is_still_a_well_formed_domain(domain: list[Any], field: str) -> None:
    """A domain whose operators lost an operand would be rejected by the server."""
    stripped = strip_field_from_domain(domain, field)
    pos = 0
    while pos < len(stripped):
        _, pos = _parse(stripped, pos)  # raises IndexError if an operator lost an operand
    assert pos == len(stripped)


@given(domains, st.sampled_from(FIELDS))
def test_stripping_is_idempotent(domain: list[Any], field: str) -> None:
    once = strip_field_from_domain(domain, field)
    assert strip_field_from_domain(once, field) == once


@given(domains)
def test_stripping_every_field_leaves_nothing_to_filter_on(domain: list[Any]) -> None:
    stripped = domain
    for field in FIELDS:
        stripped = strip_field_from_domain(stripped, field)
    assert stripped == []


# ----- the rest of the algebra -----


@given(domains)
def test_normalise_is_idempotent(domain: list[Any]) -> None:
    once = normalize_domain(domain)
    assert normalize_domain(once) == once


@given(domains)
def test_sanitise_preserves_structure_when_there_is_nothing_to_recover(domain: list[Any]) -> None:
    assert sanitize_domain(domain) == [
        list(term) if isinstance(term, list) else term for term in domain
    ]


@given(
    st.sampled_from(FIELDS),
    st.sampled_from(["=", ">=", "<=", "!=", ">", "<"]),
    st.integers(min_value=-1000, max_value=1000),
)
def test_a_condition_keeps_its_field_operator_and_value(
    field: str, operator: str, value: int
) -> None:
    assert parse_where(f"{field}{operator}{value}") == [field, operator, value]


@given(st.sampled_from(FIELDS), st.text(alphabet="abcdefgh", min_size=1, max_size=8))
def test_the_tilde_operator_is_always_ilike(field: str, text: str) -> None:
    assert parse_where(f"{field}~{text}") == [field, "ilike", text]
    assert parse_where(f"{field}!~{text}") == [field, "not ilike", text]
