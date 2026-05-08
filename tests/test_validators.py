"""Tool input validators."""
from __future__ import annotations

import pytest


def test_isin_round_trip(mcp_module):
    """A valid ISIN survives validation unchanged."""
    assert mcp_module._validate_path_param("code", "US0378331005") == "US0378331005"


@pytest.mark.parametrize(
    "value",
    [
        "../etc/passwd",
        "../../admin",
        "AAPL",
        "abcdef0123456",
        "us0378331005",
        "",
    ],
)
def test_isin_rejects_bad_input(mcp_module, value: str) -> None:
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._validate_path_param("code", value)


def test_uuid_accepts_canonical(mcp_module) -> None:
    out = mcp_module._validate_path_param(
        "delivery_uuid", "11111111-2222-3333-4444-555555555555"
    )
    assert out == "11111111-2222-3333-4444-555555555555"


@pytest.mark.parametrize(
    "value",
    [
        "abc",
        "11111111-2222-3333-4444-55555555555",
        "../../11111111-2222-3333-4444-555555555555",
        "11111111-2222-3333-4444-555555555555/../admin",
    ],
)
def test_uuid_rejects_bad_input(mcp_module, value: str) -> None:
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._validate_path_param("delivery_uuid", value)


def test_int_path_param_passes_through(mcp_module) -> None:
    assert mcp_module._validate_path_param("id", 42) == "42"


def test_boolean_path_param_rejected(mcp_module) -> None:
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._validate_path_param("id", True)


@pytest.mark.parametrize(
    "value",
    [
        "with space",
        "with/slash",
        "with?query",
        "with#frag",
        "",
    ],
)
def test_generic_path_rejects_dangerous_chars(mcp_module, value: str) -> None:
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._validate_path_param("name", value)


@pytest.mark.parametrize(
    "value",
    [
        "https://hooks.example.com/path",
        "https://hooks.example.com:8443/path?x=1&y=2",
    ],
)
def test_webhook_url_accepts_public_https(mcp_module, value: str) -> None:
    assert mcp_module._validate_webhook_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com/",
        "ftp://example.com/",
        "https://169.254.169.254/",
        "https://10.0.0.1/",
        "https://192.168.1.1/",
        "https://127.0.0.1/",
        "",
        None,
    ],
)
def test_webhook_url_blocks_unsafe(mcp_module, value):
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._validate_webhook_url(value)


def test_webhook_url_localhost_hostname_form_passes(mcp_module) -> None:
    """Hostname `localhost` (not an IP literal) is accepted at the MCP boundary;
    the backend is authoritative for hostname-based SSRF policy."""
    assert (
        mcp_module._validate_webhook_url("https://localhost/")
        == "https://localhost/"
    )


def test_redact_redis_url(mcp_module) -> None:
    assert (
        mcp_module._redact_redis_url("rediss://:abc123@host.example:6380/3")
        == "host.example:6380"
    )
    assert (
        mcp_module._redact_redis_url("rediss://host.example:6380/3")
        == "host.example:6380"
    )
    assert mcp_module._redact_redis_url("not-a-url") == "redis-store"


def test_safe_error_no_internal_leak(mcp_module) -> None:
    exc = RuntimeError("Internal API at https://api.test.invalid/secret/path failed")
    out = mcp_module._safe_error("companies_list", exc)
    assert "api.test.invalid" not in out
    assert "secret" not in out
    assert "companies_list" in out


def test_safe_error_passes_validation_message(mcp_module) -> None:
    exc = mcp_module.ToolInputError("'code' must be a 12-character ISIN")
    out = mcp_module._safe_error("isins_retrieve", exc)
    assert "must be a 12-character ISIN" in out
    assert "Invalid argument" in out
