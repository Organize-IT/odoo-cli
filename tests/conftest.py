from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import respx

BASE_URL = "https://odoo.test"
DB = "testdb"
LOGIN = "bot@test"
KEY = "secret-key"

Handler = Callable[[list[Any], dict[str, Any]], Any]


class RpcFailure(Exception):
    """Raise from a handler to make the fake server answer a JSON-RPC error."""

    def __init__(self, name: str, message: str) -> None:
        self.name = name
        self.message = message
        super().__init__(message)


class FakeOdoo:
    """Scripted Odoo JSON-RPC server behind respx.

    Register ``on(model, method, handler_or_value)``. Every ``execute_kw``
    call is appended to ``calls`` as ``(model, method, args, kwargs)``.
    ``status_queue`` holds HTTP statuses returned (with an empty body) before
    the real answer, to simulate 429 or 5xx.
    """

    def __init__(self, router: respx.MockRouter) -> None:
        self.router = router
        self.uid = 7
        self.password_ok = KEY
        self.calls: list[tuple[str, str, list[Any], dict[str, Any]]] = []
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.status_queue: list[int] = []
        self.version_info: dict[str, Any] = {
            "server_version": "17.0",
            "server_version_info": [17, 0, 0, "final", 0, ""],
            "protocol_version": 1,
        }
        router.post(f"{BASE_URL}/jsonrpc").mock(side_effect=self._dispatch)

    def on(self, model: str, method: str, handler: Handler | Any) -> None:
        if callable(handler):
            self.handlers[(model, method)] = handler
        else:
            self.handlers[(model, method)] = lambda _a, _k: handler

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        if self.status_queue:
            status = self.status_queue.pop(0)
            headers = {"Retry-After": "0"} if status == 429 else {}
            return httpx.Response(status, headers=headers)
        body = json.loads(request.content)
        params = body["params"]
        service, method, args = params["service"], params["method"], params["args"]
        try:
            if service == "common" and method == "version":
                result: Any = self.version_info
            elif service == "common" and method == "authenticate":
                db, login, password, _ = args
                ok = (db, login, password) == (DB, LOGIN, self.password_ok)
                result = self.uid if ok else False
            elif service == "object" and method == "execute_kw":
                _db, _uid, _pwd, model, meth, m_args, m_kwargs = args
                self.calls.append((model, meth, m_args, m_kwargs))
                handler = self.handlers.get((model, meth))
                if handler is None:
                    raise RpcFailure("builtins.KeyError", f"unscripted {model}.{meth}")
                result = handler(m_args, m_kwargs)
            else:
                raise RpcFailure("builtins.ValueError", f"unknown {service}.{method}")
        except RpcFailure as f:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {
                        "code": 200,
                        "message": "Odoo Server Error",
                        "data": {
                            "name": f.name,
                            "message": f.message,
                            "debug": "Traceback",
                            "arguments": [f.message],
                        },
                    },
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


@pytest.fixture
def fake_odoo() -> Iterator[FakeOdoo]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeOdoo(router)
