"""Profile resolution + identity helpers (offline)."""

import time

import pytest

from _helpers import make_jwt
from ovb.auth import decode_jwt_exp, mint_jwt, normalize_role
from ovb.config import available_profiles, default_profile_name, loaded_config_path, resolve_profile
from ovb.errors import AuthError, ConfigError


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Force an empty config file and a clean env so resolution is deterministic.
    monkeypatch.setenv("OVB_CONFIG", str(tmp_path / "none.toml"))
    for var in (
        "OVB_PROFILE",
        "OVB_API_URL",
        "OVB_JWT",
        "OVB_SUPABASE_URL",
        "OVB_SERVICE_ROLE_KEY",
        "OVB_EMAIL",
        "OVB_ROLE",
        "OVB_ANON_KEY",
        "OVB_PASSWORD",
        "OVB_AUTH_METHOD",
        "STAGING_API_URL",
        "OV_BLACK_STAGING_JWT",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_local_profile_defaults() -> None:
    p = resolve_profile("local")
    assert p.name == "local"
    assert p.api_url == "http://127.0.0.1:8000"
    assert p.supabase_url == "http://127.0.0.1:54321"


def test_staging_reads_env_names_the_verify_scripts_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGING_API_URL", "https://api.example/")
    monkeypatch.setenv("OV_BLACK_STAGING_JWT", "tok123")
    p = resolve_profile("staging")
    assert p.api_url == "https://api.example"  # trailing slash trimmed
    assert p.jwt == "tok123"


def test_api_url_override_wins() -> None:
    p = resolve_profile("local", api_url="http://10.0.0.5:9000/")
    assert p.api_url == "http://10.0.0.5:9000"


def test_unknown_profile_raises() -> None:
    with pytest.raises(ConfigError):
        resolve_profile("nope")


def test_redacted_hides_secrets() -> None:
    secrets = {
        "service_role_key": "SVCROLE_SENTINEL",
        "jwt": "JWT_SENTINEL",
        "password": "PW_SENTINEL",
        "anon_key": "ANON_SENTINEL",
    }
    p = resolve_profile("local").model_copy(update=secrets)
    red = p.redacted()
    assert red["service_role_key"] == "<set>"
    assert red["jwt"] == "<set>"
    assert red["password"] == "<set>"
    assert red["anon_key"] == "<set>"
    assert all(value not in str(red) for value in secrets.values())


def test_cli_file_reads_password_auth_fields(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    body = (
        "[profile pwd]\n"
        "api_url = https://api.example\n"
        "supabase_url = https://proj.supabase.co\n"
        "auth_method = password\n"
        "anon_key = anon-xyz\n"
        "email = svc@x.com\n"
        "password = sekret\n"
        "role = advisor\n"
    )
    _write_cli(monkeypatch, tmp_path, body)
    p = resolve_profile("pwd")
    assert p.auth_method == "password"
    assert p.anon_key == "anon-xyz"
    assert p.password == "sekret"
    assert p.default_email == "svc@x.com"


def test_env_overrides_password_auth_fields(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_cli(monkeypatch, tmp_path, _CLI_FILE)
    monkeypatch.setenv("OVB_PASSWORD", "envpw")
    monkeypatch.setenv("OVB_ANON_KEY", "envanon")
    monkeypatch.setenv("OVB_AUTH_METHOD", "password")
    p = resolve_profile("prod")
    assert p.password == "envpw"
    assert p.anon_key == "envanon"
    assert p.auth_method == "password"


def test_normalize_role_aliases() -> None:
    assert normalize_role("traveler") == "client"
    assert normalize_role("staff") == "advisor"
    assert normalize_role("Advisor") == "advisor"
    with pytest.raises(AuthError):
        normalize_role("wizard")


def test_decode_jwt_exp_roundtrips() -> None:
    exp = int(time.time()) + 1000
    assert decode_jwt_exp(make_jwt(exp=exp)) == exp
    assert decode_jwt_exp("garbage") is None


_CLI_FILE = """\
[ovb]
default_profile = staging

[profile local]
email = me@local.test
role = staff

[profile prod]
api_url = https://prod.example/
supabase_url = https://proj.supabase.co
service_role_key = svc-secret
jwt = pre.minted.tok
role = traveler
verify_tls = false
"""


def _write_cli(monkeypatch: pytest.MonkeyPatch, tmp_path, body: str):  # type: ignore[no-untyped-def]
    path = tmp_path / "config.cli"
    path.write_text(body)
    monkeypatch.setenv("OVB_CONFIG", str(path))
    return path


def test_cli_file_defines_new_profile_with_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    _write_cli(monkeypatch, tmp_path, _CLI_FILE)
    p = resolve_profile("prod")
    assert p.api_url == "https://prod.example"  # trailing slash trimmed
    assert p.supabase_url == "https://proj.supabase.co"
    assert p.service_role_key == "svc-secret"
    assert p.jwt == "pre.minted.tok"
    assert p.default_role == "traveler"  # role alias
    assert p.verify_tls is False  # bool coercion


def test_cli_file_overrides_builtin_local(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_cli(monkeypatch, tmp_path, _CLI_FILE)
    p = resolve_profile("local")
    assert p.api_url == "http://127.0.0.1:8000"  # built-in kept
    assert p.default_email == "me@local.test"  # email alias from file
    assert p.default_role == "staff"


def test_cli_file_default_profile_and_listing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _write_cli(monkeypatch, tmp_path, _CLI_FILE)
    assert default_profile_name() == "staging"
    assert {"local", "staging", "prod"}.issubset(set(available_profiles()))
    assert loaded_config_path() == path


def test_ovb_config_is_authoritative_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    # OVB_CONFIG pointing at a nonexistent file disables discovery (no fallback).
    monkeypatch.setenv("OVB_CONFIG", str(tmp_path / "absent.cli"))
    assert loaded_config_path() is None
    assert resolve_profile("local").api_url == "http://127.0.0.1:8000"


def test_env_overrides_cli_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_cli(monkeypatch, tmp_path, _CLI_FILE)
    monkeypatch.setenv("OVB_API_URL", "http://override:9000")
    assert resolve_profile("prod").api_url == "http://override:9000"


def test_mint_uses_presupplied_jwt_without_minting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGING_API_URL", "https://api.example")
    monkeypatch.setenv("OV_BLACK_STAGING_JWT", "preset.tok.sig")
    p = resolve_profile("staging")
    # No identity override → uses the pre-supplied token, never shells out.
    assert mint_jwt(p) == "preset.tok.sig"
