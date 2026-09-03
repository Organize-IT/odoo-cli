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
    async with make_client(max_retries=3) as c:
        assert (await c.version())["server_version"] == "17.0"


async def test_429_exhausted_raises_connection_error(fake_odoo: FakeOdoo) -> None:
    fake_odoo.status_queue = [429, 429, 429]
    async with make_client(max_retries=2) as c:
        with pytest.raises(OdooConnectionError) as ei:
            await c.version()
    assert ei.value.code == "rate_limited"


async def test_http_error_status_is_connection_error(fake_odoo: FakeOdoo) -> None:
    fake_odoo.status_queue = [502, 502, 502]
    async with make_client(max_retries=2) as c:
        with pytest.raises(OdooConnectionError) as ei:
            await c.version()
    assert ei.value.code == "http_error"
    fake_odoo.status_queue = [404]
    async with make_client(max_retries=2) as c:
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


async def test_context_is_merged_into_every_call(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [])
    async with make_client(context={"lang": "fr_BE", "active_test": False}) as c:
        await c.search_read("res.partner", [], ["name"])
        await c.execute("res.partner", "search_read", [], context={"lang": "nl_BE"})
    assert fake_odoo.calls[0][3]["context"] == {"lang": "fr_BE", "active_test": False}
    assert fake_odoo.calls[1][3]["context"] == {"lang": "nl_BE", "active_test": False}


async def test_no_context_key_when_empty(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_count", 0)
    async with make_client() as c:
        await c.search_count("res.partner")
    assert "context" not in fake_odoo.calls[0][3]


async def test_search_returns_ids(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search", [3, 1])
    async with make_client() as c:
        assert await c.search("res.partner", [["x", "=", 1]], limit=2, order="id") == [3, 1]
    assert fake_odoo.calls[0][3] == {"limit": 2, "order": "id"}


async def test_5xx_retried_for_reads(fake_odoo: FakeOdoo) -> None:
    fake_odoo.status_queue = [502, 503]
    fake_odoo.on("res.partner", "search_count", 1)
    async with make_client(max_retries=2) as c:
        assert await c.search_count("res.partner") == 1


async def test_5xx_not_retried_for_writes(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "create", 1)
    async with make_client(max_retries=3) as c:
        await c.authenticate()
        fake_odoo.status_queue = [502]
        with pytest.raises(OdooConnectionError) as ei:
            await c.create("res.partner", {"name": "x"})
    assert ei.value.code == "http_error"
    assert fake_odoo.status_queue == []


async def test_network_error_retried_for_reads_only() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {"server_version": "17.0"}}
        )

    with respx.mock() as router:
        router.post(f"{BASE_URL}/jsonrpc").mock(side_effect=flaky)
        async with make_client(max_retries=2) as c:
            assert (await c.version())["server_version"] == "17.0"
    assert calls["n"] == 2

    calls["n"] = 0
    with respx.mock() as router:
        router.post(f"{BASE_URL}/jsonrpc").mock(side_effect=flaky)
        async with make_client(max_retries=2) as c:
            c._uid = 7  # skip auth so the first request is the write itself
            with pytest.raises(OdooConnectionError):
                await c.create("res.partner", {"name": "x"})
    assert calls["n"] == 1


def test_verify_ssl_is_passed_to_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.is_closed = False

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    AsyncOdooClient(BASE_URL, DB, LOGIN, KEY, verify_ssl=False)._client()
    assert captured["verify"] is False


async def test_debug_logging_and_repr(
    fake_odoo: FakeOdoo, caplog: pytest.LogCaptureFixture
) -> None:
    fake_odoo.on("res.partner", "search_count", 1)
    with caplog.at_level("DEBUG", logger="odoocli.rpc"):
        async with make_client() as c:
            await c.search_count("res.partner")
            text = repr(c)
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("-> res.partner.search_count") for m in messages)
    assert any(m.startswith("<- res.partner.search_count") and "ms" in m for m in messages)
    assert KEY not in text and "uid=7" in text
