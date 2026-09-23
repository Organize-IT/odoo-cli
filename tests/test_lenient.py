from typing import Any

import pytest

from odoocli import AsyncOdooClient
from odoocli.errors import OdooError, OdooFieldMissingError
from odoocli.lenient import lenient_search_read
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo, RpcFailure


def scripted(fail_on_field: str, message: str) -> Any:
    def handler(args: list[Any], kwargs: dict[str, Any]) -> Any:
        if fail_on_field in str(args) or fail_on_field in str(kwargs):
            raise RpcFailure("builtins.ValueError", message)
        return [{"id": 1}]

    return handler


async def test_invalid_field_removed_from_fields_and_domain(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on(
        "res.partner",
        "search_read",
        scripted("mobile", "Invalid field 'mobile' on model 'res.partner'"),
    )
    warnings: list[dict[str, Any]] = []
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        rows = await lenient_search_read(
            c,
            "res.partner",
            ["|", ["mobile", "!=", False], ["phone", "!=", False]],
            ["name", "mobile"],
            10,
            0,
            None,
            strip_domain=True,
            on_warning=warnings.append,
        )
    assert rows == [{"id": 1}]
    assert warnings == [
        {"warning": "invalid_field_removed", "field": "mobile", "from": ["fields", "domain"]}
    ]
    last_args, last_kwargs = fake_odoo.calls[-1][2], fake_odoo.calls[-1][3]
    assert last_args == [[]], "the disjunction is unconstrained once mobile is gone"
    assert last_kwargs["fields"] == ["name"]


async def test_non_stored_field_removed_from_order_only(fake_odoo: FakeOdoo) -> None:
    def handler(args: list[Any], kwargs: dict[str, Any]) -> Any:
        if "qty_available" in kwargs.get("order", ""):
            raise RpcFailure(
                "builtins.ValueError",
                "Cannot convert qty_available to SQL because it is not stored",
            )
        return [{"id": 1}]

    fake_odoo.on("product.product", "search_read", handler)
    warnings: list[dict[str, Any]] = []
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        await lenient_search_read(
            c,
            "product.product",
            [],
            ["name", "qty_available"],
            None,
            0,
            "qty_available desc, name",
            on_warning=warnings.append,
        )
    assert warnings == [
        {"warning": "non_stored_field_removed", "field": "qty_available", "from": ["order"]}
    ]
    assert fake_odoo.calls[-1][3]["order"] == "name"
    assert fake_odoo.calls[-1][3]["fields"] == ["name", "qty_available"]


async def test_unrelated_error_is_raised(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", scripted("", "Access Denied"))
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        with pytest.raises(OdooError, match="Access Denied"):
            await lenient_search_read(c, "res.partner", [], ["name"], None, 0, None)


def search_reads(fake_odoo: FakeOdoo) -> int:
    return sum(1 for call in fake_odoo.calls if call[1] == "search_read")


@pytest.mark.parametrize(
    "message",
    [
        "Invalid field 'account_type' in leaf ('account_type', '=', 'asset_cash')",
        "Invalid field account.account.account_type in condition ('account_type', '=', 'x')",
    ],
)
async def test_domain_field_missing_raises_by_default(fake_odoo: FakeOdoo, message: str) -> None:
    fake_odoo.on("account.account", "search_read", scripted("account_type", message))
    warnings: list[dict[str, Any]] = []
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        with pytest.raises(OdooFieldMissingError) as exc:
            await lenient_search_read(
                c,
                "account.account",
                [["account_type", "=", "asset_cash"]],
                ["id"],
                None,
                0,
                None,
                on_warning=warnings.append,
            )
    assert exc.value.field == "account_type"
    assert exc.value.model == "account.account"
    assert exc.value.where == "domain"
    assert exc.value.code == "field_missing"
    assert search_reads(fake_odoo) == 1, "no wider query was replayed"
    assert warnings == []


async def test_domain_field_stripped_when_opted_in(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on(
        "account.account", "search_read", scripted("account_type", "Invalid field 'account_type'")
    )
    warnings: list[dict[str, Any]] = []
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        rows = await lenient_search_read(
            c,
            "account.account",
            [["account_type", "=", "asset_cash"]],
            ["id"],
            None,
            0,
            None,
            strip_domain=True,
            on_warning=warnings.append,
        )
    assert rows == [{"id": 1}]
    assert warnings[0]["from"] == ["domain"]
    assert fake_odoo.calls[-1][2] == [[]]


async def test_fields_only_repair_still_automatic(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on(
        "product.product", "search_read", scripted("is_storable", "Invalid field 'is_storable'")
    )
    warnings: list[dict[str, Any]] = []
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        rows = await lenient_search_read(
            c,
            "product.product",
            [],
            ["id", "is_storable"],
            None,
            0,
            None,
            on_warning=warnings.append,
        )
    assert rows == [{"id": 1}]
    assert warnings == [
        {"warning": "invalid_field_removed", "field": "is_storable", "from": ["fields"]}
    ]
    assert fake_odoo.calls[-1][3]["fields"] == ["id"]


async def test_non_stored_in_domain_raises_by_default(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on(
        "product.product",
        "search_read",
        scripted("qty_available", "Cannot convert qty_available to SQL because it is not stored"),
    )
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        with pytest.raises(OdooFieldMissingError) as exc:
            await lenient_search_read(
                c, "product.product", [["qty_available", ">", 0]], ["id"], None, 0, None
            )
    assert exc.value.field == "qty_available"
    assert exc.value.where == "domain"
    assert search_reads(fake_odoo) == 1


async def test_non_stored_in_domain_stripped_when_opted_in(fake_odoo: FakeOdoo) -> None:
    def handler(args: list[Any], kwargs: dict[str, Any]) -> Any:
        if "qty_available" in str(args):
            raise RpcFailure(
                "builtins.ValueError",
                "Cannot convert qty_available to SQL because it is not stored",
            )
        return [{"id": 1}]

    fake_odoo.on("product.product", "search_read", handler)
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        rows = await lenient_search_read(
            c,
            "product.product",
            [["qty_available", ">", 0]],
            ["id", "qty_available"],
            None,
            0,
            None,
            strip_domain=True,
        )
    assert rows == [{"id": 1}]
    assert fake_odoo.calls[-1][2] == [[]]


async def test_field_named_inside_another_is_not_a_domain_field(fake_odoo: FakeOdoo) -> None:
    def handler(args: list[Any], kwargs: dict[str, Any]) -> Any:
        if "type" in kwargs.get("fields", []):
            raise RpcFailure("builtins.ValueError", "Invalid field 'type' on model 'account.move'")
        return [{"id": 1}]

    fake_odoo.on("account.move", "search_read", handler)
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        rows = await lenient_search_read(
            c, "account.move", [["move_type", "=", "out_invoice"]], ["id", "type"], None, 0, None
        )
    assert rows == [{"id": 1}]
    assert fake_odoo.calls[-1][2] == [[["move_type", "=", "out_invoice"]]]
