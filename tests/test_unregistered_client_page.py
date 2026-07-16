"""The "Client Not Registered" page users actually land on.

FastMCP's stock page is written for local MCP clients: it tells the user to
"clear authentication tokens in your MCP client (or restart it)" and asserts the
client "should automatically re-register". Neither holds for a hosted connector
(ChatGPT, Claude.ai) — the registration lives on the vendor's servers, there is
no token-clearing control, and production logs show those clients replaying a
dead client_id hundreds to thousands of times without ever re-registering,
because a browser-delegated flow never tells the client the sign-in failed.

`_fr_unregistered_client_html` replaces that page with the one action that works:
remove the connector and add it again. It is installed over FastMCP's module-level
`create_unregistered_client_html`, which its AuthorizationHandler calls by global
lookup when `get_client()` misses.

These cover: the patch is installed, the page states the working fix, it drops
the misleading stock advice, the signature still matches the caller, and the
attacker-controlled client_id is HTML-escaped.
"""

from __future__ import annotations

import inspect

import pytest


@pytest.fixture()
def render(mcp_module):
    """Render the page the way FastMCP's AuthorizationHandler calls it."""

    def _render(client_id: str = "synthetic-client-id-0000") -> str:
        return mcp_module._fr_unregistered_client_html(
            client_id=client_id,
            registration_endpoint="https://mcp.test.invalid/register",
            discovery_endpoint=(
                "https://mcp.test.invalid/.well-known/oauth-authorization-server"
            ),
            server_name="FinancialReports",
            server_icon_url=None,
        )

    return _render


def test_patch_is_installed_over_fastmcp_renderer(mcp_module):
    # FastMCP's handler resolves this by module-global lookup at call time, so
    # patching the module attribute is what actually swaps the page.
    from fastmcp.server.auth.handlers import authorize as fastmcp_authorize

    assert (
        fastmcp_authorize.create_unregistered_client_html
        is mcp_module._fr_unregistered_client_html
    )


def test_signature_matches_the_fastmcp_call_site(mcp_module):
    # The handler calls with these exact keywords. If a FastMCP bump changes them,
    # fail here rather than with a TypeError inside a live OAuth redirect.
    params = inspect.signature(mcp_module._fr_unregistered_client_html).parameters
    for expected in (
        "client_id",
        "registration_endpoint",
        "discovery_endpoint",
        "server_name",
        "server_icon_url",
        "title",
    ):
        assert expected in params, f"missing parameter {expected!r}"


def test_page_tells_the_user_to_remove_and_re_add_the_connector(render):
    html = render()
    lowered = html.lower()
    # The one action that actually resolves this.
    assert "remove" in lowered
    assert "add it again" in lowered or "re-add" in lowered
    assert "connector" in lowered


def test_page_names_the_hosted_clients_by_their_real_ui_path(render):
    html = render()
    # A stuck user needs the literal path, not a concept.
    assert "ChatGPT" in html
    assert "Settings" in html
    assert "Connectors" in html


def test_page_drops_the_misleading_stock_advice(render):
    html = render()
    lowered = html.lower()
    # Prod logs disprove this outright: stuck connectors never re-register.
    assert "should automatically re-register" not in lowered
    # No such control exists in a hosted connector's UI.
    assert "clear authentication tokens in your mcp client" not in lowered


def test_page_says_retrying_will_not_help(render):
    html = render()
    lowered = html.lower()
    # Users retried a dead id hundreds of times. Say so explicitly.
    assert "retry" in lowered or "retrying" in lowered or "reload" in lowered


def test_client_id_is_html_escaped(render):
    # client_id is reflected straight from the query string — this is a
    # reflected-XSS surface. Mirror FastMCP's html.escape() exactly.
    html = render(client_id='<script>alert("xss")</script>')
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_client_id_is_shown_so_users_can_report_it(render):
    html = render(client_id="abc-123-def")
    assert "abc-123-def" in html


def test_page_is_a_complete_html_document(render):
    html = render()
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in html.lower()
