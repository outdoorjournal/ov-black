"""Shared CLI plumbing — context object, client construction, async runner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import typer

from ovb.cli import render
from ovb.config import Profile
from ovb.errors import ApiError, OvbError
from ovb.sdk import Ovb


@dataclass(slots=True)
class CliState:
    """Resolved global options, stashed on ``typer.Context.obj``."""

    profile: Profile
    role: str | None
    email: str | None
    json_mode: bool


def state_of(ctx: typer.Context) -> CliState:
    obj = ctx.obj
    if not isinstance(obj, CliState):  # pragma: no cover - wiring guard
        raise typer.Exit(2)
    return obj


def run_op[T](
    ctx: typer.Context,
    coro_fn: Callable[[Ovb], Awaitable[T]],
    *,
    authed: bool = True,
    role: str | None = None,
    email: str | None = None,
) -> T:
    """Mint an identity, run one async op against the API, render any error.

    ``role``/``email`` override the global identity for this call (e.g. chat
    ``--as traveler``).
    """
    state = state_of(ctx)

    async def _main() -> T:
        client = Ovb.for_identity(
            state.profile,
            email=email or state.email,
            role=role or state.role,
            authed=authed,
        )
        async with client as ovb:
            return await coro_fn(ovb)

    try:
        return asyncio.run(_main())
    except ApiError as exc:
        _render_error(state, code=exc.detail, status=exc.status, body=exc.body)
        raise typer.Exit(1) from exc
    except OvbError as exc:
        _render_error(state, code=str(exc), status=None, body=None)
        raise typer.Exit(1) from exc


def _render_error(state: CliState, *, code: str, status: int | None, body: object) -> None:
    if state.json_mode:
        render.print_json({"ok": False, "status": status, "error": code, "detail": body})
    else:
        prefix = f"error {status}: " if status else "error: "
        render.err_console.print(f"[bold red]{prefix}[/bold red]{code}")
