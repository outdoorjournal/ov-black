"""`ovb configure` / `ovb auth` / `ovb health` / `ovb me` / `ovb demo` — plumbing."""

from pathlib import Path

import typer

from ovb.auth import decode_jwt_exp, mint_jwt, normalize_role
from ovb.cli import render
from ovb.cli._run import run_op, state_of
from ovb.config import (
    CONFIG_BASENAME,
    available_profiles,
    loaded_config_path,
    resolve_profile,
)

_CONFIG_TEMPLATE = """\
# ovb config — AWS-style profiles. Select with `--profile NAME` or OVB_PROFILE.
# Keys: api_url, supabase_url, anon_key, password, auth_method,
#       service_role_key, jwt, email, role, verify_tls.
# Precedence: built-ins < this file < environment < command flags.

[ovb]
default_profile = local

[profile local]
api_url = http://127.0.0.1:8000
supabase_url = http://127.0.0.1:54321
# email = you@example.com
# role = advisor
# service_role_key falls back to apps/api/.env when omitted (local mint-jwt.sh).

# Password-grant auth (recommended off-box): logs a dedicated service user in
# with the publishable anon key — no service-role key, password stays here only.
[profile staging]
# api_url = https://your-staging-api
# supabase_url = https://<project>.supabase.co
# auth_method = password
# anon_key = <supabase anon / publishable key>     ; not secret
# email = svc-advisor@your-domain                  ; the service user
# password = <that user's password>                ; secret — lives here only
# role = advisor

# A second service user for traveler-role turns (password auth is one user/role).
# [profile staging-traveler]
# api_url = https://your-staging-api
# supabase_url = https://<project>.supabase.co
# auth_method = password
# anon_key = <supabase anon / publishable key>
# email = svc-traveler@your-domain
# password = <that user's password>
# role = traveler
"""

configure_app = typer.Typer(help="Profiles & target configuration.")
auth_app = typer.Typer(help="Mint JWTs and drive the public auth entrypoints.")
me_app = typer.Typer(help="Traveler self-service (acts as a client identity).")


# ── configure ────────────────────────────────────────────────────────────────
@configure_app.command("list")
def configure_list(ctx: typer.Context) -> None:
    """List known profiles."""
    state = state_of(ctx)
    names = available_profiles()
    render.emit(state.json_mode, names, lambda: render.kv_panel("profiles", {"available": names}))


@configure_app.command("show")
def configure_show(ctx: typer.Context) -> None:
    """Show the resolved active profile (secrets redacted)."""
    state = state_of(ctx)
    payload = state.profile.redacted()
    loaded = loaded_config_path()
    payload["config_file"] = str(loaded) if loaded else None
    render.emit(state.json_mode, payload, lambda: render.kv_panel(state.profile.name, payload))


@configure_app.command("path")
def configure_path(ctx: typer.Context) -> None:
    """Print the .cli config file currently in effect (or none)."""
    state = state_of(ctx)
    loaded = loaded_config_path()
    payload = {"config_file": str(loaded) if loaded else None}
    render.emit(
        state.json_mode, payload, lambda: str(payload["config_file"] or "(no .cli file found)")
    )


@configure_app.command("init")
def configure_init(
    ctx: typer.Context,
    path: str | None = typer.Option(
        None, "--path", help=f"Where to write the {CONFIG_BASENAME} file."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    """Scaffold a starter AWS-style .cli config file."""
    state = state_of(ctx)
    target = Path(path).expanduser() if path else Path.home() / ".ovblack" / CONFIG_BASENAME
    if target.exists() and not force:
        raise typer.BadParameter(f"{target} already exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_CONFIG_TEMPLATE)
    payload = {"ok": True, "written": str(target)}
    render.emit(state.json_mode, payload, lambda: f"wrote {target}")


# ── auth ─────────────────────────────────────────────────────────────────────
@auth_app.command("mint")
def auth_mint(
    ctx: typer.Context,
    email: str | None = typer.Option(None, "--email"),
    role: str | None = typer.Option(None, "--role", help="traveler/client | staff/advisor."),
    method: str | None = typer.Option(
        None, "--method", help="password | admin | auto — override the profile's auth_method."
    ),
) -> None:
    """Mint a JWT. Plain mode prints ONLY the token (composes into env vars)."""
    state = state_of(ctx)
    profile = state.profile
    if method is not None:
        profile = profile.model_copy(update={"auth_method": method})
    token = mint_jwt(profile, email=email or state.email, role=role or state.role)
    if state.json_mode:
        render.print_json({"token": token, "exp": decode_jwt_exp(token)})
    else:
        # stdout = token only, like scripts/mint-jwt.sh, so `$(ovb auth mint)` works.
        print(token)


@auth_app.command("login")
def auth_login(
    ctx: typer.Context,
    email: str = typer.Option(..., "--email"),
) -> None:
    """Request a sign-in magic link for an existing account (public route)."""
    state = state_of(ctx)
    run_op(ctx, lambda ovb: ovb.login(email=email), authed=False)
    render.emit(state.json_mode, {"ok": True}, lambda: "magic link sent")


# ── whoami / health ──────────────────────────────────────────────────────────
def register_top_level(app: typer.Typer) -> None:
    """Attach the flat top-level commands (whoami / health / opener / demo)."""

    @app.command("whoami")
    def whoami(ctx: typer.Context) -> None:
        """Mint the active identity's JWT and decode who it represents."""
        import base64
        import json

        state = state_of(ctx)
        role = state.role or state.profile.default_role
        token = mint_jwt(state.profile, email=state.email, role=role)
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        info = {
            "profile": state.profile.name,
            "api_url": state.profile.api_url,
            "sub": claims.get("sub"),
            "email": claims.get("email"),
            "role": normalize_role(role),
            "exp": claims.get("exp"),
        }
        render.emit(state.json_mode, info, lambda: render.kv_panel("whoami", info))

    @app.command("health")
    def health(ctx: typer.Context) -> None:
        """Hit the public liveness probe."""
        state = state_of(ctx)
        res = run_op(ctx, lambda ovb: ovb.health(), authed=False)
        render.emit(state.json_mode, res, lambda: render.kv_panel("health", res))

    @app.command("opener")
    def opener(ctx: typer.Context) -> None:
        """Pick a random onboarding opener."""
        state = state_of(ctx)
        res = run_op(ctx, lambda ovb: ovb.random_opener())
        render.emit(state.json_mode, res, lambda: render.kv_panel("opener", res))

    @app.command("demo-japan")
    def demo_japan(
        ctx: typer.Context,
        client_id: str = typer.Option(..., "--client-id"),
        trip_start_at: str | None = typer.Option(None, "--trip-start-at"),
        title: str | None = typer.Option(None, "--title"),
    ) -> None:
        """Instantiate the Japan template itinerary for a client."""
        state = state_of(ctx)
        res = run_op(
            ctx,
            lambda ovb: ovb.demo_japan(
                client_id=client_id, trip_start_at=trip_start_at, title=title
            ),
        )
        render.emit(state.json_mode, res, lambda: render.kv_panel("japan demo", res))


# ── me (traveler) ────────────────────────────────────────────────────────────
@me_app.command("client")
def me_client(ctx: typer.Context) -> None:
    """Resolve the calling user's client_id (acts as a client)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.my_client(), role=state.role or "client")
    render.emit(state.json_mode, res, lambda: render.kv_panel("me/client", res))


@me_app.command("itineraries")
def me_itineraries(ctx: typer.Context) -> None:
    """List the calling client's itineraries."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.my_itineraries(), role=state.role or "client")
    render.emit(state.json_mode, res, lambda: render.itineraries_table(res))


# convenience for resolve in tests / external callers
__all__ = [
    "auth_app",
    "configure_app",
    "me_app",
    "register_top_level",
    "resolve_profile",
]
