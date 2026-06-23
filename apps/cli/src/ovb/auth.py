"""Identity & JWT minting.

The system distinguishes a *traveler* (Supabase role ``client``) from *staff*
(role ``advisor``) purely by which JWT is presented — there is no separate
"act as" header. So driving a turn "as traveler" vs "as staff" is just minting
the matching JWT and pointing the SDK at it (``apps/api`` resolves actor_kind
from ``public.profiles.role``).

Three credential sources, picked per profile (``auth_method``):

- **password** (recommended off-box) — log a dedicated service user in via the
  Supabase *password grant* (``POST /auth/v1/token?grant_type=password``) using
  the publishable anon key. Needs no service-role key; the raw password lives in
  the profile/secret and never reaches our backend (Supabase verifies the hash).
- **admin** — reuse the proven ``scripts/mint-jwt.sh`` (service-role key + admin
  generate_link; also syncs the ``public.profiles`` row). Can mint any role.
- pre-supplied ``jwt`` (e.g. ``OV_BLACK_STAGING_JWT``) — used verbatim.

``auto`` uses the password grant when a ``password`` is configured, else admin.
"""

from __future__ import annotations

import base64
import binascii
import json
import subprocess
import time

import httpx

from ovb.config import Profile, repo_root
from ovb.errors import AuthError

#: traveler ⇒ client, staff ⇒ advisor; canonical roles pass through.
ROLE_ALIASES: dict[str, str] = {
    "traveler": "client",
    "client": "client",
    "staff": "advisor",
    "advisor": "advisor",
}


def normalize_role(role: str) -> str:
    """Map a user-facing role/alias to a canonical Supabase role."""
    canonical = ROLE_ALIASES.get(role.strip().lower())
    if canonical is None:
        raise AuthError(f"unknown role {role!r}; use one of: traveler/client, staff/advisor")
    return canonical


def decode_jwt_exp(token: str) -> int | None:
    """Read the ``exp`` claim without verifying (we did not sign it)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError, json.JSONDecodeError):
        return None
    exp = claims.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def _is_fresh(token: str, *, skew: int = 60) -> bool:
    exp = decode_jwt_exp(token)
    return exp is None or exp - skew > time.time()


class TokenStore:
    """In-memory cache of minted JWTs keyed by (target, email, role).

    Kept process-local on purpose — a token is a credential; we don't persist
    it to disk. Re-mints automatically once a cached token is within 60s of exp.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], str] = {}

    def get(self, profile: Profile, *, email: str, role: str) -> str | None:
        key = (profile.supabase_url, email, role)
        token = self._cache.get(key)
        if token and _is_fresh(token):
            return token
        return None

    def put(self, profile: Profile, *, email: str, role: str, token: str) -> None:
        self._cache[(profile.supabase_url, email, role)] = token

    def clear(self) -> None:
        self._cache.clear()


_STORE = TokenStore()


def mint_via_password(
    *,
    supabase_url: str,
    anon_key: str,
    email: str,
    password: str,
    verify_tls: bool = True,
    timeout: float = 15.0,
) -> str:
    """Exchange (email, password) for a Supabase access token (no admin key).

    The token is a normal Supabase JWT — the API validates it identically to a
    magic-link token. The password is sent only to Supabase over TLS and is
    never logged here.
    """
    url = f"{supabase_url.rstrip('/')}/auth/v1/token"
    try:
        resp = httpx.post(
            url,
            params={"grant_type": "password"},
            headers={"apikey": anon_key, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=timeout,
            verify=verify_tls,
        )
    except httpx.HTTPError as exc:
        raise AuthError(f"password grant request failed: {exc}") from exc

    if resp.status_code != 200:
        raise AuthError(f"password grant rejected ({resp.status_code}): {_grant_error(resp)}")

    try:
        data = resp.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise AuthError("password grant returned non-JSON") from exc
    token = data.get("access_token") if isinstance(data, dict) else None
    if not isinstance(token, str) or token.count(".") != 2:
        raise AuthError("password grant returned no access_token")
    return token


def _grant_error(resp: httpx.Response) -> str:
    """Pull a stable reason from a GoTrue error body (never echoes credentials)."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200] or "unknown"
    if isinstance(body, dict):
        for key in ("error_description", "msg", "message", "error", "code"):
            val = body.get(key)
            if isinstance(val, str) and val:
                return val
    return "invalid_grant"


def mint_jwt(
    profile: Profile,
    *,
    email: str | None = None,
    role: str | None = None,
    force: bool = False,
    store: TokenStore | None = None,
) -> str:
    """Return a bearer JWT for the given identity on ``profile``.

    Routes by ``profile.auth_method`` (password grant / admin mint-jwt.sh /
    pre-supplied jwt) and caches the result. See the module docstring.
    """
    role_in = role or profile.default_role
    canonical_role = normalize_role(role_in)
    target_email = email or profile.default_email

    # Pre-supplied token path (staging): only when the caller didn't ask for a
    # specific identity that differs from the profile default.
    if profile.jwt and email is None and role is None:
        return profile.jwt

    if not target_email:
        raise AuthError(
            "no email to mint a JWT for (pass --email, set OVB_EMAIL, or configure git user.email)"
        )

    store = store or _STORE
    if not force:
        cached = store.get(profile, email=target_email, role=canonical_role)
        if cached:
            return cached

    method = (profile.auth_method or "auto").strip().lower()
    use_password = method == "password" or (method == "auto" and bool(profile.password))
    if use_password:
        token = _mint_via_password_profile(
            profile, email=email, role=role, target_email=target_email
        )
    else:
        token = _mint_via_admin(profile, target_email=target_email, canonical_role=canonical_role)

    store.put(profile, email=target_email, role=canonical_role, token=token)
    return token


def _mint_via_password_profile(
    profile: Profile, *, email: str | None, role: str | None, target_email: str
) -> str:
    """Password-grant a token for the profile's bound service identity.

    The grant logs in *one* user; it can't switch email or role on the fly
    (those come from the account itself), so a mismatched override is a hard
    error pointing you at a profile that carries that user's credentials.
    """
    if email is not None and email != profile.default_email:
        raise AuthError(
            f"password auth on profile {profile.name!r} is bound to "
            f"{profile.default_email!r}; use a profile with that user's password "
            "(or auth_method=admin)"
        )
    if role is not None and normalize_role(role) != normalize_role(profile.default_role):
        raise AuthError(
            f"password auth on profile {profile.name!r} yields the "
            f"{normalize_role(profile.default_role)!r} role; cannot mint a "
            f"{normalize_role(role)!r} token — use a profile whose service user has that role"
        )
    if not profile.password:
        raise AuthError(
            f"profile {profile.name!r} uses password auth but no password is set "
            "(set `password` in .cli or OVB_PASSWORD)"
        )
    if not profile.anon_key:
        raise AuthError(
            "password auth needs an anon key (set `anon_key` in .cli or SUPABASE_ANON_KEY)"
        )
    return mint_via_password(
        supabase_url=profile.supabase_url,
        anon_key=profile.anon_key,
        email=target_email,
        password=profile.password,
        verify_tls=profile.verify_tls,
    )


def _mint_via_admin(profile: Profile, *, target_email: str, canonical_role: str) -> str:
    """Mint via scripts/mint-jwt.sh (needs the service-role key; sets profiles.role)."""
    root = repo_root()
    if root is None:
        raise AuthError("cannot locate repo root to run scripts/mint-jwt.sh")
    script = root / "scripts" / "mint-jwt.sh"
    if not script.exists():
        raise AuthError(f"mint-jwt.sh not found at {script}")

    env = {
        "PATH": _env_path(),
        "HOME": _env_home(),
        "SUPABASE_URL": profile.supabase_url,
    }
    if profile.service_role_key:
        env["SUPABASE_SERVICE_ROLE_KEY"] = profile.service_role_key

    try:
        proc = subprocess.run(
            [str(script), "--email", target_email, "--role", canonical_role],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthError(f"mint-jwt.sh failed to run: {exc}") from exc

    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-3:]
        raise AuthError("mint-jwt.sh exited non-zero:\n  " + "\n  ".join(tail))

    token = proc.stdout.strip()
    if not token or token.count(".") != 2:
        raise AuthError("mint-jwt.sh produced no JWT on stdout")
    return token


def _env_path() -> str:
    import os

    return os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin")


def _env_home() -> str:
    import os

    return os.environ.get("HOME", "")
