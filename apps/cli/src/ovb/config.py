"""Profiles & config resolution — AWS-CLI-style targeting of local vs staging.

A *profile* is a named target (base URL + Supabase coordinates + default
identity). Resolution layers, lowest priority first:

1. built-in defaults (``local`` / ``staging``),
2. the optional ``.cli`` config file — AWS-style INI with ``[profile NAME]``
   sections (``$OVB_CONFIG`` → ``<repo>/.cli`` → ``~/.ovblack/.cli`` → ``~/.cli``),
3. environment variables (incl. the established ``STAGING_API_URL`` /
   ``OV_BLACK_STAGING_JWT`` / ``SUPABASE_*`` names the verify scripts use).

This mirrors the verify-sNN.sh "local by default, staging when env is present"
posture, so the harness and those scripts target the same way.
"""

from __future__ import annotations

import configparser
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ovb.errors import ConfigError


class Profile(BaseModel):
    """A resolved target. ``service_role_key`` is never rendered (repr-stripped)."""

    model_config = ConfigDict(frozen=True)

    name: str
    api_url: str
    supabase_url: str = "http://127.0.0.1:54321"
    # When None, mint-jwt.sh falls back to apps/api/.env's supabase_service_role_key.
    # Only the `admin` auth method needs this (it's a god key — avoid distributing it).
    service_role_key: str | None = None
    # Supabase anon/publishable key — required by the `password` grant. Publishable,
    # not secret. For local it's printed by `supabase status`.
    anon_key: str | None = None
    # A dedicated service user's password (secret). When set (and auth_method allows),
    # the SDK logs in via the password grant instead of the admin key — so neither the
    # raw password nor the service-role key is exposed in the client.
    password: str | None = None
    # auto → password grant when `password` is set, else admin (mint-jwt.sh).
    auth_method: str = "auto"  # auto | password | admin
    # A pre-supplied bearer (e.g. OV_BLACK_STAGING_JWT). When set and no per-call
    # identity override is given, the SDK uses it verbatim instead of minting.
    jwt: str | None = None
    default_email: str | None = None
    default_role: str = "advisor"
    verify_tls: bool = True

    def redacted(self) -> dict[str, str | bool | None]:
        """Config-safe dict for ``--json`` / display (secrets shown as a flag)."""
        return {
            "name": self.name,
            "api_url": self.api_url,
            "supabase_url": self.supabase_url,
            "service_role_key": "<set>" if self.service_role_key else None,
            "anon_key": "<set>" if self.anon_key else None,
            "password": "<set>" if self.password else None,
            "auth_method": self.auth_method,
            "jwt": "<set>" if self.jwt else None,
            "default_email": self.default_email,
            "default_role": self.default_role,
            "verify_tls": self.verify_tls,
        }


_BUILTIN: dict[str, dict[str, object]] = {
    "local": {
        "api_url": "http://127.0.0.1:8000",
        "supabase_url": "http://127.0.0.1:54321",
        "default_role": "advisor",
    },
    "staging": {
        # api_url/jwt come from STAGING_API_URL / OV_BLACK_STAGING_JWT at resolve time.
        "api_url": "",
        "default_role": "advisor",
    },
}

DEFAULT_PROFILE = "local"


@lru_cache(maxsize=1)
def repo_root() -> Path | None:
    """Locate the monorepo root (holds ``pnpm-workspace.yaml`` + ``scripts/``).

    Honors ``$OVB_REPO_ROOT``; otherwise walks up from this file, then cwd.
    """
    override = os.environ.get("OVB_REPO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    for base in (Path(__file__).resolve(), Path.cwd().resolve()):
        for parent in (base, *base.parents):
            if (parent / "pnpm-workspace.yaml").exists() and (parent / "scripts").is_dir():
                return parent
    return None


def _git_email() -> str | None:
    root = repo_root()
    try:
        out = subprocess.run(
            ["git", "config", "--get", "user.email"],
            cwd=str(root) if root else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    email = out.stdout.strip()
    return email or None


#: Basename of the AWS-style config file (INI with ``[profile NAME]`` sections).
CONFIG_BASENAME = ".cli"

#: Friendly aliases accepted inside a profile section.
_KEY_ALIASES = {"email": "default_email", "role": "default_role"}
_BOOL_KEYS = {"verify_tls"}


def _candidate_config_paths() -> list[Path]:
    """Where to look for the ``.cli`` file, in precedence order.

    ``$OVB_CONFIG`` is authoritative (like ``AWS_CONFIG_FILE``): when set, only
    that path is considered — no fallback — so it cleanly disables discovery.
    """
    override = os.environ.get("OVB_CONFIG")
    if override:
        return [Path(override).expanduser()]
    paths: list[Path] = []
    root = repo_root()
    if root is not None:
        paths.append(root / CONFIG_BASENAME)
        paths.append(root / "apps" / "cli" / CONFIG_BASENAME)
    paths.append(Path.home() / ".ovblack" / CONFIG_BASENAME)
    paths.append(Path.home() / CONFIG_BASENAME)
    return paths


def loaded_config_path() -> Path | None:
    """First existing candidate config file, or None."""
    for path in _candidate_config_paths():
        if path.exists():
            return path
    return None


def _normalize_section(items: dict[str, str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for raw_key, value in items.items():
        key = _KEY_ALIASES.get(raw_key, raw_key)
        if key in _BOOL_KEYS:
            out[key] = value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            out[key] = value
    return out


def load_config_file() -> dict[str, object]:
    """Parse the ``.cli`` file into ``{profiles: {...}, default_profile?: str}``.

    AWS-style sections: ``[profile NAME]`` (and a bare ``[NAME]``) define a
    profile; ``[ovb]``/``[settings]`` may carry ``default_profile``. Secrets
    (``service_role_key``/``jwt``) and identity (``email``/``role``) live here so
    they need not be re-exported into the environment each call.
    """
    path = loaded_config_path()
    if path is None:
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open() as fh:
            parser.read_file(fh)
    except (OSError, configparser.Error) as exc:
        raise ConfigError(f"failed to read {path}: {exc}") from exc

    profiles: dict[str, dict[str, object]] = {}
    default_profile: str | None = None
    for section in parser.sections():
        low = section.strip().lower()
        body = dict(parser.items(section))
        if low in {"ovb", "settings"}:
            if body.get("default_profile"):
                default_profile = body["default_profile"]
            continue
        name = section.split(None, 1)[1].strip() if low.startswith("profile ") else section.strip()
        normalized = _normalize_section(body)
        dp = normalized.pop("default_profile", None)
        if isinstance(dp, str):
            default_profile = dp
        profiles[name] = normalized

    result: dict[str, object] = {"profiles": profiles}
    if default_profile:
        result["default_profile"] = default_profile
    return result


def available_profiles() -> list[str]:
    file_cfg = load_config_file()
    file_profiles = file_cfg.get("profiles", {})
    names = set(_BUILTIN)
    if isinstance(file_profiles, dict):
        names.update(file_profiles.keys())
    return sorted(names)


def default_profile_name() -> str:
    name = os.environ.get("OVB_PROFILE")
    if name:
        return name
    file_cfg = load_config_file()
    file_default = file_cfg.get("default_profile")
    if isinstance(file_default, str):
        return file_default
    return DEFAULT_PROFILE


def resolve_profile(
    name: str | None = None,
    *,
    api_url: str | None = None,
    email: str | None = None,
    role: str | None = None,
) -> Profile:
    """Merge built-ins → config file → env → explicit overrides into a Profile."""
    name = name or default_profile_name()

    merged: dict[str, object] = dict(_BUILTIN.get(name, {}))
    file_cfg = load_config_file()
    file_profiles = file_cfg.get("profiles", {})
    if isinstance(file_profiles, dict) and isinstance(file_profiles.get(name), dict):
        merged.update(file_profiles[name])
    elif name not in _BUILTIN:
        raise ConfigError(f"unknown profile {name!r}; known: {', '.join(available_profiles())}")

    env = os.environ

    def pick(*keys: str) -> str | None:
        for key in keys:
            val = env.get(key)
            if val:
                return val
        return None

    # Environment overlay (established names first so verify scripts compose).
    if name == "staging":
        merged.setdefault("api_url", "")
        env_api = pick("OVB_API_URL", "STAGING_API_URL")
        env_jwt = pick("OVB_JWT", "OV_BLACK_STAGING_JWT")
    else:
        env_api = pick("OVB_API_URL")
        env_jwt = pick("OVB_JWT")
    if env_api:
        merged["api_url"] = env_api.rstrip("/")
    if env_jwt:
        merged["jwt"] = env_jwt

    env_sb = pick("OVB_SUPABASE_URL", "SUPABASE_URL")
    if env_sb:
        merged["supabase_url"] = env_sb
    env_key = pick("OVB_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY")
    if env_key:
        merged["service_role_key"] = env_key
    env_anon = pick("OVB_ANON_KEY", "SUPABASE_ANON_KEY")
    if env_anon:
        merged["anon_key"] = env_anon
    env_pw = pick("OVB_PASSWORD")
    if env_pw:
        merged["password"] = env_pw
    env_method = pick("OVB_AUTH_METHOD")
    if env_method:
        merged["auth_method"] = env_method
    env_email = pick("OVB_EMAIL")
    if env_email:
        merged["default_email"] = env_email
    env_role = pick("OVB_ROLE")
    if env_role:
        merged["default_role"] = env_role

    # Explicit call overrides win over everything.
    if api_url:
        merged["api_url"] = api_url.rstrip("/")
    if email:
        merged["default_email"] = email
    if role:
        merged["default_role"] = role

    if not merged.get("default_email"):
        merged["default_email"] = _git_email()

    # Normalize the base URL once, whatever its source (file/env/flag).
    api_url_val = merged.get("api_url")
    if isinstance(api_url_val, str):
        merged["api_url"] = api_url_val.rstrip("/")

    # api_url may be empty here (e.g. staging before STAGING_API_URL is set);
    # that's only an error when a command actually makes an API call — minting
    # a JWT or showing the profile does not need it. The guard lives in
    # Ovb.for_identity so `configure`/`whoami`/`auth mint` stay usable.
    merged["name"] = name
    return Profile.model_validate(merged)
