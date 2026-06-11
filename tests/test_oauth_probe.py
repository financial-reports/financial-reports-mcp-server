"""Unit coverage for the prod OAuth probe's #32-contract classifier.

The live probe (`tests/e2e/test_prod_oauth_probe.py`) is env-gated and never runs
in CI. This pins the deterministic classifier it relies on — especially that a raw
upstream-403 leak is ALWAYS flagged `forbidden` and that `forbidden` beats a
reconnect hint — so the regression guard itself can't silently rot. No network.
"""
from __future__ import annotations

from tests.e2e.oauth_probe import FORBIDDEN_MARKERS, RECONNECT_MARKER, classify


def test_raw_upstream_403_is_forbidden() -> None:
    # The exact #32 signature the probe must always catch.
    text = "Error calling tool 'companies_list': upstream companies_list returned 403"
    assert classify(text, True) == "forbidden"


def test_no_kid_detail_is_forbidden() -> None:
    text = '{"detail":"Authentication error: Invalid token header. No kid provided."}'
    assert classify(text, True) == "forbidden"


def test_reconnect_message_is_accepted() -> None:
    # The post-#32 fail-closed message is an EXPECTED outcome, not a regression.
    msg = (
        "Your session could not be linked to upstream credentials. Please "
        "disconnect and reconnect the FinancialReports connector, then retry."
    )
    assert classify(msg, True) == "reconnect"


def test_real_data_is_data() -> None:
    assert classify('{"results":[{"id":14,"name":"Alcoa"}]}', False) == "data"


def test_forbidden_beats_reconnect() -> None:
    # A 403 leak must never be masked as an acceptable reconnect outcome.
    assert classify("returned 403 — please disconnect and reconnect", True) == "forbidden"


def test_markers_are_what_the_probe_asserts_on() -> None:
    assert "returned 403" in FORBIDDEN_MARKERS
    assert RECONNECT_MARKER == "disconnect and reconnect"
