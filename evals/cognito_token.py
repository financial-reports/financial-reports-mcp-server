#!/usr/bin/env python3
"""Mint an MCP bearer token non-interactively from a test account (token path A).

The hosted MCP uses Cognito OAuth, which Claude Code does via an interactive
browser flow. CI can't do that — so for a test account we mint an access token
directly via Cognito USER_PASSWORD_AUTH and export it as FR_MCP_TOKEN.

    export FR_MCP_TOKEN="$(python cognito_token.py)"
    python run_eval.py --models claude,deepseek

Env required:
    COGNITO_CLIENT_ID    the app client id the MCP accepts (MCP_COGNITO_CLIENT_IDS).
                         Ask the FR team which client id to use — a token minted
                         for the wrong client is rejected by the MCP's audience check.
    COGNITO_REGION       default eu-central-1
    FR_TEST_USERNAME     test account username/email
    FR_TEST_PASSWORD     test account password

Requires the app client to have ALLOW_USER_PASSWORD_AUTH enabled.
"""
from __future__ import annotations

import os
import sys


def mint_token() -> str:
    import boto3

    client_id = os.environ.get("COGNITO_CLIENT_ID")
    username = os.environ.get("FR_TEST_USERNAME")
    password = os.environ.get("FR_TEST_PASSWORD")
    region = os.environ.get("COGNITO_REGION", "eu-central-1")
    missing = [n for n, v in (
        ("COGNITO_CLIENT_ID", client_id),
        ("FR_TEST_USERNAME", username),
        ("FR_TEST_PASSWORD", password),
    ) if not v]
    if missing:
        sys.exit("ERROR: missing env: " + ", ".join(missing))

    cognito = boto3.client("cognito-idp", region_name=region)
    resp = cognito.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    auth = resp.get("AuthenticationResult")
    if not auth:
        # e.g. NEW_PASSWORD_REQUIRED / MFA challenge — surface, don't paper over
        sys.exit(f"ERROR: no token; got challenge {resp.get('ChallengeName')!r}")
    # The MCP validates the access token (client_id + audience binding).
    return auth["AccessToken"]


if __name__ == "__main__":
    print(mint_token())
