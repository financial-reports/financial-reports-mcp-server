"""Content-free filings: do not hand a human a viewer page with nothing to read (web#1298).

The instructions told the model to share `viewer_url` unconditionally. For a
filing that is not yet processed (`processing_status` != COMPLETED) and whose
original is not a PDF/HTML file, the web viewer can inline neither a digital
view nor the original (it inlines only .html/.htm/.xhtml/.pdf), so the person
lands on an empty reader. Measured 2026-09-28: 579 of 51,188 distinct filings
the MCP served in 30 days (1.13%) were in that state. The row already carries
both fields, so the model can route the human to `document` instead.
"""
from __future__ import annotations


def test_link_guide_routes_content_free_filings_to_document(mcp_module) -> None:
    guide = mcp_module._resource_markdown.fn()
    assert "processing_status` is not `COMPLETED`" in guide
    assert "hand them `document`" in guide


def test_filings_list_description_carries_the_rule(mcp_module) -> None:
    """The guide is read on demand; the list tool is where viewer_url arrives."""
    desc = mcp_module.mcp._tool_manager._tools["filings_list"].description
    assert "viewer_url" in desc and "document" in desc and "COMPLETED" in desc
