from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from odoocli import AsyncOdooClient
from odoocli.errors import OdooAuthError, OdooConnectionError, OdooValidationError
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo, RpcFailure


def make_client(**kw: Any) -> AsyncOdooClient:
    return AsyncOdooClient(
        BASE_URL, DB, LOGIN, KEY, retry_base_delay=0.0, retry_max_delay=0.0, **kw
    )


async def test_version_does_not_authenticate(fake_odoo: FakeOdoo) -> None:
    async with make_client() as c:
        v = await c.version()
    assert v["server_version"] == "17.0"
    assert c.uid is None


async def test_authenticate_caches_uid(fake_odoo: FakeOdoo) -> None:
    async with make_client() as c:
        assert await c.authenticate() == 7
        fake_odoo.uid = 99
        assert await c.authenticate() == 7


async def test_bad_credentials_raise_auth_error(fake_odoo: FakeOdoo) -> None:
    async with AsyncOdooClient(BASE_URL, DB, LOGIN, "wrong") as c:
        with pytest.raises(OdooAuthError):
            await c.authenticate()


async def test_search_read_sends_kwargs_and_returns_raw(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [{"id": 1, "name": "Acme", "user_id": [3, "Bob"]}])
    async with make_client() as c:
        rows = await c.search_read(
            "res.partner",
            [["is_company", "=", True]],
            fields=["name", "user_id"],
            limit=5,
            order="name",
        )
    assert rows == [{"id": 1, "name": "Acme", "user_id": [3, "Bob"]}]
    model, meth, args, kwargs = fake_odoo.calls[0]
    assert (model, meth) == ("res.partner", "search_read")
    assert args == [[["is_company", "=", True]]]
    assert kwargs == {"fields": ["name", "user_id"], "limit": 5, "order": "name"}


async def test_crud_methods_map_to_execute_kw(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "create", 42)
    fake_odoo.on("res.partner", "write", True)
    fake_odoo.on("res.partner", "unlink", True)
    fake_odoo.on("res.partner", "read", [{"id": 42, "name": "X"}])
    fake_odoo.on("res.partner", "search_count", 3)
    fake_odoo.on("res.partner", "fields_get", {"name": {"type": "char"}})
    async with make_client() as c:
        assert await c.create("res.partner", {"name": "X"}) == 42
        assert await c.write("res.partner", [42], {"name": "Y"}) is True
        assert await c.read("res.partner", [42], ["name"]) == [{"id": 42, "name": "X"}]
        assert await c.search_count("res.partner", []) == 3
        assert await c.fields_get("res.partner", ["type"]) == {"name": {"type": "char"}}
        assert await c.unlink("res.partner", [42]) is True
    assert [(m, k) for m, k, *_ in fake_odoo.calls] == [
        ("res.partner", "create"),
        ("res.partner", "write"),
        ("res.partner", "read"),
        ("res.partner", "search_count"),
        ("res.partner", "fields_get"),
        ("res.partner", "unlink"),
    ]
    assert fake_odoo.calls[4][3] == {"attributes": ["type"]}


async def test_rpc_error_is_classified(fake_odoo: FakeOdoo) -> None:
    def fail(_a: list[Any], _k: dict[str, Any]) -> Any:
        raise RpcFailure("odoo.exceptions.UserError", "Cannot delete")

    fake_odoo.on("res.partner", "unlink", fail)
    async with make_client() as c:
        with pytest.raises(OdooValidationError, match="Cannot delete"):
            await c.unlink("res.partner", [1])


async def test_429_is_retried_then_succeeds(fake_odoo: FakeOdoo) -> None:
    fake_odoo.status_queue = [429, 429]
    async with make_client(max_retries_429=3) as c:
        assert (await c.version())["server_version"] == "17.0"


async def test_429_exhausted_raises_connection_error(fake_odoo: FakeOdoo) -> None:
    fake_odoo.status_queue = [429, 429, 429]
    async with make_client(max_retries_429=2) as c:
        with pytest.raises(OdooConnectionError) as ei:
            await c.version()
    assert ei.value.code == "rate_limited"


async def test_http_error_status_is_connection_error(fake_odoo: FakeOdoo) -> None:
    fake_odoo.status_queue = [502]
    async with make_client() as c:
        with pytest.raises(OdooConnectionError) as ei:
            await c.version()
    assert ei.value.code == "http_error"


async def test_network_failure_is_connection_error() -> None:
    with respx.mock() as router:
        router.post(f"{BASE_URL}/jsonrpc").mock(side_effect=httpx.ConnectError("refused"))
        async with make_client() as c:
            with pytest.raises(OdooConnectionError, match="refused"):
                await c.version()


async def test_non_json_body_is_connection_error() -> None:
    with respx.mock() as router:
        router.post(f"{BASE_URL}/jsonrpc").mock(
            return_value=httpx.Response(200, text="<html>login</html>")
        )
        async with make_client() as c:
            with pytest.raises(OdooConnectionError) as ei:
                await c.version()
    assert ei.value.code == "not_jsonrpc"
