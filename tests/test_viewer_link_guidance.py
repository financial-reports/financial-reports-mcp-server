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
    assert "PENDING, QUEUED, PROCESSING, FAILED or SKIPPED" in guide
    # list rows carry document_url, not document (FilingSummary schema)
    assert "raw file link instead of `viewer_url`" in guide
    # summary rows carry document_url; view=full rows and retrieve carry document
    assert "`document_url` on default" in guide and "`document` on `view='full'` rows" in guide
    assert "no file link is available yet" in guide  # null raw link: say so
    assert "HTM or XHTML" in guide  # the viewer inlines these too
    assert "A null status" in guide  # view='full' nulls the status


def test_filings_list_description_carries_the_rule(mcp_module) -> None:
    """The guide is read on demand; the list tool is where viewer_url arrives."""
    desc = mcp_module.mcp._tool_manager._tools["filings_list"].description
    assert "viewer_url" in desc and "document_url" in desc
    assert "view=full rows" in desc and "no file link is available yet" in desc
    assert "PENDING/QUEUED/PROCESSING/FAILED/SKIPPED" in desc
    assert "null" in desc


def test_list_guidance_names_a_field_the_list_row_actually_has(mcp_module) -> None:
    """#137 review: `document` exists only on filings_retrieve."""
    import json
    from pathlib import Path

    snap = json.loads(Path("scripts/openapi.snapshot.json").read_text())
    props = snap["components"]["schemas"]["FilingSummary"]["properties"]
    assert "document_url" in props and "document" not in props
    # ...and view=full rows carry `document` (list example, #137 review round 2)
    op = snap["paths"]["/filings/"]["get"]["responses"]["200"]["content"]
    full = op["application/json"]["examples"]["FullView(`?view=full`)"]["value"][0]
    assert "document" in full and "document_url" not in full
