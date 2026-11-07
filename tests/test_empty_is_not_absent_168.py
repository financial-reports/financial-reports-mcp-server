"""An empty result the API DISCLOSED as restricted must not reach the user as
"these filings do not exist" (#168).

`filings_list` is a structured-output tool: it returns `_scrub_response(
response.json())` — the whole body — and `history_window` is a declared property
of `PaginatedFilingSummaryList` in both the snapshot and the live schema. So on a
200 with an empty `results` and a `history_window` notice, the disclosure DOES
reach the model; that was traced end to end in #168. The model still answered
"no such filings", because nothing told it what the pairing means.

Why this is a DESCRIPTION fix and not a response-copy fix: a structured tool has
no prose channel. `_history_window_copy` already renders the right sentence, but
it is wired only to the 404 path (`_upstream_copy`), and a 200 never reaches it.
A structured response cannot carry an extra sentence without violating its own
output schema, so the only place this rule can live is the tool description.

Two guards, the second being the one that survives rewording:

* POSITIVE, over the RENDERED description the model receives: `filings_list`
  must state that an empty `results` alongside a disclosure object is a
  restriction rather than an absence.
* SEMANTIC: the same text that names `history_window` must also say the filings
  are not retrievable on this plan — so a later edit cannot keep the field name
  while dropping what it implies.

SCOPE, stated honestly:

* Both rules are per-TEXT, not per-sentence. A description saying both things in
  unrelated places would pass. They are a floor against silent deletion, not
  proof the guidance reads well.
* Neither asserts anything about what a model DOES with the guidance. #168's
  actual finding was that a field reaching the model is not the model acting on
  it, and no unit test can close that gap — only an eval can.
"""

from __future__ import annotations

import inspect
import re

RESTRICTION_WORDS = re.compile(
    r"not retrievable|outside this plan|outside the plan|plan restriction"
    r"|restricted|not available on this plan",
    re.IGNORECASE,
)
ABSENCE_RULE = re.compile(r"empty is not absent", re.IGNORECASE)


def _description(mcp_module, name: str) -> str:
    return mcp_module.mcp._tool_manager._tools[name].description or ""


def test_filings_list_says_an_empty_disclosed_result_is_a_restriction(mcp_module):
    """The rule must be in the description the model actually receives."""
    desc = _description(mcp_module, "filings_list")
    assert ABSENCE_RULE.search(desc), (
        "filings_list's rendered description no longer states that an empty "
        "`results` carrying a disclosure object is a plan restriction rather "
        "than an absence (#168). The guidance lives in "
        "scripts/tool_overrides.yaml under filings_list.when_to_use."
    )


def test_the_rule_names_history_window_and_what_it_means(mcp_module):
    """Naming the field is not enough; the text must say what it implies."""
    desc = _description(mcp_module, "filings_list")
    assert "history_window" in desc, (
        "filings_list's description no longer names `history_window`, the "
        "disclosure object the 200-with-empty-results case carries (#168)."
    )
    assert RESTRICTION_WORDS.search(desc), (
        "filings_list's description names `history_window` but no longer says "
        "the filings are unretrievable on this plan rather than nonexistent "
        "(#168). A field name without its meaning is what the model ignored."
    )


def test_the_404_path_keeps_its_own_copy(mcp_module):
    """The pre-existing 404 wording must not be collateral of this change.

    `_history_window_copy` is the 404 path's sentence and is NOT what #168 is
    about. Asserting it survives keeps this change's blast radius honest.
    """
    src = inspect.getsource(mcp_module)
    assert "def _history_window_copy(" in src
    assert '_classify_upstream_404(body_text) == "history_window"' in src
