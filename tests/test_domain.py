import pytest

from odoocli.domain import (
    _dehumanize,
    build_domain,
    dehumanize_operand,
    normalize_domain,
    parse_value,
    parse_where,
    sanitize_domain,
    strip_field_from_domain,
)
from odoocli.errors import OdooUsageError


def test_normalize_accepts_json_and_python_literals() -> None:
    assert normalize_domain('[["a","=",1]]') == [["a", "=", 1]]
    assert normalize_domain("[('a', '=', True)]") == [("a", "=", True)]
    assert normalize_domain("") == []
    assert normalize_domain(None) == []


def test_normalize_keeps_prefix_operators() -> None:
    dom = ["|", ["a", "=", 1], ["b", "=", 2]]
    assert normalize_domain(dom) == dom


def test_sanitize_dehumanizes_relational_operands_only() -> None:
    dom = [
        ["partner_id", "=", "Acme (#42)"],
        ["name", "=", "Foo (#1)"],
        ["tag_ids", "in", ["A (#1)", 2]],
    ]
    assert sanitize_domain(dom) == [
        ["partner_id", "=", 42],
        ["name", "=", "Foo (#1)"],
        ["tag_ids", "in", [1, 2]],
    ]


def test_strip_field_folds_operators() -> None:
    dom = ["|", ["mobile", "!=", False], ["phone", "!=", False], ["is_company", "=", True]]
    assert strip_field_from_domain(dom, "mobile") == [
        ["phone", "!=", False],
        ["is_company", "=", True],
    ]
    assert strip_field_from_domain(["!", ["mobile", "=", False]], "mobile") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("False", False),
        ("null", False),
        ("none", False),
        ("42", 42),
        ("-3", -3),
        ("3.5", 3.5),
        ("'42'", "42"),
        ('"x y"', "x y"),
        ("2026-01-31", "2026-01-31"),
        ("Acme", "Acme"),
        ("[1,2]", [1, 2]),
    ],
)
def test_parse_value(raw: str, expected: object) -> None:
    assert parse_value(raw) == expected


@pytest.mark.parametrize(
    ("expr", "leaf"),
    [
        ("is_company=true", ["is_company", "=", True]),
        ("amount_total>=1000", ["amount_total", ">=", 1000]),
        ("name!=Acme", ["name", "!=", "Acme"]),
        ("name~acme", ["name", "ilike", "acme"]),
        ("name!~acme", ["name", "not ilike", "acme"]),
        ("state in draft,sent", ["state", "in", ["draft", "sent"]]),
        ("state not in done,cancel", ["state", "not in", ["done", "cancel"]]),
        ("partner_id.country_id.code = BE", ["partner_id.country_id.code", "=", "BE"]),
        ("email=null", ["email", "=", False]),
        ("tag_ids in [1,2]", ["tag_ids", "in", [1, 2]]),
        ("name =ilike Ac%", ["name", "=ilike", "Ac%"]),
        ("parent_id child_of 5", ["parent_id", "child_of", 5]),
    ],
)
def test_parse_where(expr: str, leaf: list[object]) -> None:
    assert parse_where(expr) == leaf


def test_parse_where_rejects_garbage() -> None:
    with pytest.raises(OdooUsageError):
        parse_where("no operator here")


def test_build_domain_ands_json_and_where() -> None:
    dom = build_domain('["|",["a","=",1],["b","=",2]]', ["c=3", "d~x"])
    assert dom == ["|", ["a", "=", 1], ["b", "=", 2], ["c", "=", 3], ["d", "ilike", "x"]]
    assert build_domain(None, []) == []


def test_build_domain_rejects_invalid_json() -> None:
    with pytest.raises(OdooUsageError):
        build_domain("{not a list}", [])


def test_dehumanize_operand_is_public() -> None:
    assert dehumanize_operand("Acme (#42)") == 42
    assert dehumanize_operand(["A (#1)", 2, "plain"]) == [1, 2, "plain"]
    assert dehumanize_operand(False) is False
    assert dehumanize_operand("ref (#7) extra") == "ref (#7) extra"
    assert _dehumanize is dehumanize_operand  # 0.2.x compatibility alias
