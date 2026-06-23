"""Async HTTP transport — one configured ``httpx.AsyncClient`` per identity.

A transport is bound to a single bearer (the JWT for one traveler/staff
identity), matching how the web client attaches one Supabase token. The
per-session HS256 *agent* token is deliberately not held here — it lives only
inside the runtime server-side, exactly as in production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any

import httpx

QueryValue = str | int | float | bool | Sequence[str] | None


class Transport:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        verify_tls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            verify=verify_tls,
            timeout=timeout,
            follow_redirects=True,
        )

    @property
    def base_url(self) -> str:
        return str(self._client.base_url)

    @property
    def token(self) -> str | None:
        return self._token

    def _headers(self, authed: bool, extra: Mapping[str, str] | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if authed and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if extra:
            headers.update(extra)
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Mapping[str, QueryValue] | None = None,
        headers: Mapping[str, str] | None = None,
        authed: bool = True,
    ) -> httpx.Response:
        clean_params = {k: v for k, v in params.items() if v is not None} if params else None
        return await self._client.request(
            method,
            path,
            json=json_body,
            params=clean_params,
            headers=self._headers(authed, headers),
        )

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        authed: bool = True,
    ) -> AsyncIterator[httpx.Response]:
        """Open a streaming response (used for the SSE turn endpoint)."""
        sse_headers = {"Accept": "text/event-stream", **(headers or {})}
        async with self._client.stream(
            method,
            path,
            json=json_body,
            headers=self._headers(authed, sse_headers),
        ) as response:
            yield response

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Transport:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
