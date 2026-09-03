"""Async Odoo JSON-RPC client. No logging, no env, no printing."""

from __future__ import annotations

import asyncio
import json
import random
from types import TracebackType
from typing import Any

import httpx

from odoocli._version import __version__
from odoocli.errors import OdooAuthError, OdooConnectionError, classify_rpc_error

Domain = list[Any]


class AsyncOdooClient:
    """Talk to one Odoo database over ``/jsonrpc``.

    ``api_key`` is what goes in the password slot of ``common.authenticate``:
    an API key (Odoo 14+) or the user's password.
    """

    def __init__(
        self,
        url: str,
        database: str,
        login: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_retries_429: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 8.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.login = login
        self._api_key = api_key
        self.max_retries_429 = max_retries_429
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        # Connect tight so a dead host or firewall surfaces fast; keep the
        # read budget close to the total.
        self._timeout = httpx.Timeout(
            connect=min(5.0, timeout),
            read=max(1.0, timeout - 5.0),
            write=max(1.0, timeout - 5.0),
            pool=5.0,
        )
        self._uid: int | None = None
        self._http: httpx.AsyncClient | None = None

    # ----- lifecycle -----

    @property
    def uid(self) -> int | None:
        return self._uid

    async def __aenter__(self) -> AsyncOdooClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": f"odoocli/{__version__}"}
            )
        return self._http

    # ----- transport -----

    def _retry_delay(self, attempt: int, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), self.retry_max_delay))
            except ValueError:
                pass  # HTTP-date format: fall back to backoff
        base = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
        jitter: float = 0.5 + random.random() / 2
        return float(base * jitter)

    async def _rpc(self, service: str, method: str, args: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": random.randint(1, 1_000_000),
        }
        url = f"{self.url}/jsonrpc"
        client = self._client()
        try:
            for attempt in range(self.max_retries_429 + 1):
                response = await client.post(url, json=payload)
                if response.status_code != 429:
                    break
                if attempt == self.max_retries_429:
                    raise OdooConnectionError(
                        f"Odoo rate limited the request (HTTP 429) after {attempt + 1} attempts",
                        code="rate_limited",
                    )
                await asyncio.sleep(self._retry_delay(attempt, response))
        except httpx.HTTPError as e:
            raise OdooConnectionError(f"Cannot reach {url}: {e}", code="connection_error") from e

        if response.status_code >= 400:
            raise OdooConnectionError(f"HTTP {response.status_code} from {url}", code="http_error")
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise OdooConnectionError(
                f"{url} did not answer JSON-RPC (is this an Odoo server URL?)",
                code="not_jsonrpc",
            ) from e
        if not isinstance(data, dict):
            raise OdooConnectionError(f"{url} did not answer JSON-RPC", code="not_jsonrpc")
        if "error" in data:
            raise classify_rpc_error(data["error"])
        return data.get("result")

    # ----- public API -----

    async def version(self) -> dict[str, Any]:
        """Server version info. Works without credentials."""
        result = await self._rpc("common", "version", [])
        return result if isinstance(result, dict) else {}

    async def authenticate(self) -> int:
        if self._uid is not None:
            return self._uid
        uid = await self._rpc(
            "common", "authenticate", [self.database, self.login, self._api_key, {}]
        )
        if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
            raise OdooAuthError(
                f"Authentication failed for {self.login!r} on database {self.database!r}"
            )
        self._uid = uid
        return uid

    async def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        uid = await self.authenticate()
        return await self._rpc(
            "object",
            "execute_kw",
            [self.database, uid, self._api_key, model, method, list(args), kwargs],
        )

    async def search_read(
        self,
        model: str,
        domain: Domain | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order:
            kwargs["order"] = order
        result = await self.execute(model, "search_read", domain or [], **kwargs)
        return list(result) if isinstance(result, list) else []

    async def search_count(self, model: str, domain: Domain | None = None) -> int:
        result = await self.execute(model, "search_count", domain or [])
        return int(result)

    async def read(
        self, model: str, ids: list[int], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"fields": fields} if fields else {}
        result = await self.execute(model, "read", ids, **kwargs)
        return list(result) if isinstance(result, list) else []

    async def create(self, model: str, values: dict[str, Any] | list[dict[str, Any]]) -> Any:
        """Create one record (dict) or several (list of dicts). Returns id or ids."""
        return await self.execute(model, "create", values)

    async def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        return bool(await self.execute(model, "write", ids, values))

    async def unlink(self, model: str, ids: list[int]) -> bool:
        return bool(await self.execute(model, "unlink", ids))

    async def fields_get(
        self, model: str, attributes: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        kwargs: dict[str, Any] = {"attributes": attributes} if attributes else {}
        result = await self.execute(model, "fields_get", **kwargs)
        return dict(result) if isinstance(result, dict) else {}
