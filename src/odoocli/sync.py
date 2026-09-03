"""Blocking wrapper around AsyncOdooClient for plain scripts."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Coroutine
from types import TracebackType
from typing import Any, TypeVar

from odoocli.client import AsyncOdooClient, Domain

T = TypeVar("T")


class OdooClient:
    """Same API as :class:`AsyncOdooClient`, without ``await``.

    Runs a private event loop on a daemon thread so the underlying httpx
    client keeps one connection pool for the life of the object.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._async = AsyncOdooClient(*args, **kwargs)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="odoocli-loop", daemon=True
        )
        self._thread.start()
        self._closed = False

    def _run(self, coro: Coroutine[Any, Any, T]) -> T:
        if self._closed:
            coro.close()
            raise RuntimeError("OdooClient is closed")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    # ----- lifecycle -----

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        asyncio.run_coroutine_threadsafe(self._async.close(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()

    def __enter__(self) -> OdooClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):  # never raise from a destructor
            self.close()

    # ----- mirror -----

    @property
    def uid(self) -> int | None:
        return self._async.uid

    def version(self) -> dict[str, Any]:
        return self._run(self._async.version())

    def authenticate(self) -> int:
        return self._run(self._async.authenticate())

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._run(self._async.execute(model, method, *args, **kwargs))

    def search_read(
        self,
        model: str,
        domain: Domain | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._run(self._async.search_read(model, domain, fields, limit, offset, order))

    def search_count(self, model: str, domain: Domain | None = None) -> int:
        return self._run(self._async.search_count(model, domain))

    def read(
        self, model: str, ids: list[int], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return self._run(self._async.read(model, ids, fields))

    def create(self, model: str, values: dict[str, Any] | list[dict[str, Any]]) -> Any:
        return self._run(self._async.create(model, values))

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        return self._run(self._async.write(model, ids, values))

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self._run(self._async.unlink(model, ids))

    def fields_get(
        self, model: str, attributes: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        return self._run(self._async.fields_get(model, attributes))
