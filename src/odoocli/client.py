"""Async Odoo JSON-RPC client. No env, no printing; logs through ``logging`` only."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from types import TracebackType
from typing import Any

import httpx

from odoocli._version import __version__
from odoocli.errors import OdooAuthError, OdooConnectionError, classify_rpc_error
from odoocli.security import is_read_safe_method

Domain = list[Any]

logger = logging.getLogger("odoocli.rpc")


class AsyncOdooClient:
    """Talk to one Odoo database over ``/jsonrpc``.

    ``api_key`` is what goes in the password slot of ``common.authenticate``:
    an API key (Odoo 14+) or the user's password.

    ``context`` is merged into every ``execute_kw`` call (``lang``,
    ``allowed_company_ids``, ``active_test``, ...); a per-call ``context``
    keyword argument overrides keys of the client-wide one.

    Retry policy: HTTP 429 is always retried (Odoo rejected the request before
    running it). Network errors, timeouts and HTTP 5xx are retried only for
    calls that cannot change data (``common.*`` and read-safe ORM methods),
    because a ``create`` that timed out may well have been committed.
    """

    def __init__(
        self,
        url: str,
        database: str,
        login: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 8.0,
        verify_ssl: bool = True,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.login = login
        self._api_key = api_key
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.verify_ssl = verify_ssl
        self.context: dict[str, Any] = dict(context or {})
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

    def __repr__(self) -> str:
        return (
            f"AsyncOdooClient(url={self.url!r}, database={self.database!r}, "
            f"login={self.login!r}, uid={self._uid!r})"
        )

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
                timeout=self._timeout,
                headers={"User-Agent": f"odoocli/{__version__}"},
                verify=self.verify_ssl,
            )
        return self._http

    # ----- transport -----

    def _retry_delay(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), self.retry_max_delay))
            except ValueError:
                pass  # HTTP-date format: fall back to backoff
        base = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
        jitter: float = 0.5 + random.random() / 2
        return float(base * jitter)

    async def _rpc(
        self, service: str, method: str, args: list[Any], *, retryable: bool = True
    ) -> Any:
        request_id = random.randint(1, 1_000_000)
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": request_id,
        }
        url = f"{self.url}/jsonrpc"
        client = self._client()
        label = f"{service}.{method}" if service == "common" else f"{args[3]}.{args[4]}"
        started = time.perf_counter()
        logger.debug("-> %s id=%d", label, request_id)

        response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                response = await client.post(url, json=payload)
            except httpx.HTTPError as e:
                if not retryable or last:
                    raise OdooConnectionError(
                        f"Cannot reach {url}: {e}", code="connection_error"
                    ) from e
                delay = self._retry_delay(attempt)
                logger.warning(
                    "%s failed (%s), retry %d/%d in %.1fs",
                    label,
                    type(e).__name__,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            status = response.status_code
            if status == 429 and not last:
                delay = self._retry_delay(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "%s rate limited (429), retry %d/%d in %.1fs",
                    label,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            if status >= 500 and retryable and not last:
                delay = self._retry_delay(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "%s got HTTP %d, retry %d/%d in %.1fs",
                    label,
                    status,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            break

        assert response is not None
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code == 429:
            raise OdooConnectionError(
                f"Odoo rate limited the request (HTTP 429) after {self.max_retries + 1} attempts",
                code="rate_limited",
            )
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
            err = classify_rpc_error(data["error"])
            logger.debug("!! %s id=%d %.1fms %s: %s", label, request_id, elapsed_ms, err.code, err)
            raise err
        logger.debug("<- %s id=%d %.1fms", label, request_id, elapsed_ms)
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
        """``execute_kw`` with the client context merged into ``kwargs["context"]``."""
        uid = await self.authenticate()
        call_context = kwargs.pop("context", None) or {}
        merged = {**self.context, **call_context}
        if merged:
            kwargs["context"] = merged
        return await self._rpc(
            "object",
            "execute_kw",
            [self.database, uid, self._api_key, model, method, list(args), kwargs],
            retryable=is_read_safe_method(method),
        )

    @staticmethod
    def _page_kwargs(
        fields: list[str] | None, limit: int | None, offset: int, order: str | None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order:
            kwargs["order"] = order
        return kwargs

    async def search(
        self,
        model: str,
        domain: Domain | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[int]:
        """Record ids matching ``domain``."""
        kwargs = self._page_kwargs(None, limit, offset, order)
        result = await self.execute(model, "search", domain or [], **kwargs)
        return [int(i) for i in result] if isinstance(result, list) else []

    async def search_read(
        self,
        model: str,
        domain: Domain | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs = self._page_kwargs(fields, limit, offset, order)
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
