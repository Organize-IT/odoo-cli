from typing import Any

import pytest

from odoocli import AsyncOdooClient
from odoocli.errors import OdooError
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
            on_warning=warnings.append,
        )
    assert rows == [{"id": 1}]
    assert warnings == [
        {"warning": "invalid_field_removed", "field": "mobile", "from": ["fields", "domain"]}
    ]
    last_args, last_kwargs = fake_odoo.calls[-1][2], fake_odoo.calls[-1][3]
    assert last_args == [[["phone", "!=", False]]]
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
