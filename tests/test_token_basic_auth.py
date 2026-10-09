"""client_secret_basic on /token without client_id in the body (Glama, 2026-10-09).

The SDK tests run the REAL `mcp` ClientAuthenticator behind the middleware, so they
pin the property that matters: a Basic-only token request authenticates, and the
secret is still checked. See src/token_basic_auth.py for the rationale.
"""
from __future__ import annotations

import base64

import httpx
import pytest
from mcp.server.auth.middleware.client_auth import (
    AuthenticationError,
    ClientAuthenticator,
)
from mcp.shared.auth import OAuthClientInformationFull
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.token_basic_auth import TokenBasicAuthClientIdMiddleware, basic_client_id

CLIENT_ID = "35b350ba-4883-4ed8-943b-9c8b867d4b05"
SECRET = "s3cret"
FORM = "application/x-www-form-urlencoded"
BODY = "grant_type=authorization_code&code=abc&redirect_uri=https%3A%2F%2Fglama.ai%2Fcb&code_verifier=v"


def _basic(client_id: str = CLIENT_ID, secret: str = SECRET) -> str:
    return "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()


class _Provider:
    async def get_client(self, client_id: str):
        if client_id != CLIENT_ID:
            return None
        return OAuthClientInformationFull(
            client_id=CLIENT_ID,
            client_secret=SECRET,
            token_endpoint_auth_method="client_secret_basic",
            redirect_uris=["https://glama.ai/cb"],
        )


def _app(with_middleware: bool = True):
    authenticator = ClientAuthenticator(_Provider())

    async def token(request: Request):
        try:
            client = await authenticator.authenticate_request(request)
        except AuthenticationError as e:
            return JSONResponse({"error": e.message}, status_code=401)
        form = await request.form()
        return JSONResponse({"client_id": client.client_id, "code": form.get("code")})

    inner = Starlette(routes=[Route("/token", token, methods=["POST"])])
    return TokenBasicAuthClientIdMiddleware(inner) if with_middleware else inner


async def _post(app, body: str = BODY, **headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.post("/token", content=body, headers={"content-type": FORM, **headers})


@pytest.mark.asyncio
async def test_sdk_alone_rejects_basic_only_request():
    # Pins the SDK bug this shim exists for. If this starts passing, the SDK
    # was fixed and src/token_basic_auth.py can be deleted.
    resp = await _post(_app(with_middleware=False), authorization=_basic())
    assert resp.status_code == 401
    assert resp.json()["error"] == "Missing client_id"


@pytest.mark.asyncio
async def test_basic_only_request_authenticates_with_middleware():
    resp = await _post(_app(), authorization=_basic())
    assert resp.status_code == 200
    assert resp.json() == {"client_id": CLIENT_ID, "code": "abc"}


@pytest.mark.asyncio
async def test_wrong_secret_still_rejected():
    resp = await _post(_app(), authorization=_basic(secret="nope"))
    assert resp.status_code == 401
    assert resp.json()["error"] == "Invalid client_secret"


@pytest.mark.asyncio
async def test_body_client_id_is_left_alone():
    # A mismatching body id must reach the SDK unchanged (it rejects the mismatch).
    resp = await _post(_app(), body=BODY + "&client_id=other", authorization=_basic())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_auth_request_unchanged():
    seen = {}

    async def inner(scope, receive, send):
        msg = await receive()
        seen["body"] = msg["body"]
        await JSONResponse({})(scope, receive, send)

    body = BODY + f"&client_id={CLIENT_ID}&client_secret={SECRET}"
    await _post(TokenBasicAuthClientIdMiddleware(inner), body=body)
    assert seen["body"] == body.encode()


@pytest.mark.parametrize("header,expected", [
    (_basic(), CLIENT_ID),
    (_basic("a%3Ab"), "a:b"),          # RFC 6749 §2.3.1 form-encodes the id
    ("Bearer xyz", None),
    ("Basic !!!", None),
    ("Basic " + base64.b64encode(b"nocolon").decode(), None),
    (None, None),
])
def test_basic_client_id(header, expected):
    assert basic_client_id(header.encode() if header else None) == expected
