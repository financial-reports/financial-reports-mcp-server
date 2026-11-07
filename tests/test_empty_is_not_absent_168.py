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

# The guidance must name the LIMIT and the CUTOFF...
LIMIT_WORDS = re.compile(r"cutoff", re.IGNORECASE)
ABSENCE_RULE = re.compile(r"empty is not proof of absence", re.IGNORECASE)
# ...and must NOT resurrect either over-claim. Both directions are defects:
# asserting absence is #168; asserting existence is what SPECHT caught on
# 79b83fc. `history_window` supports neither.
# NEGATION-AWARE on purpose. A bare substring search here is the same defect
# this repo keeps paying for — a text pattern matches MENTIONS as well as
# OCCURRENCES — and it caught the corrected guidance itself: the sentence
# "never that matches exist either" contains "matches exist" while asserting
# the opposite. So a phrase only counts as an over-claim when no negation
# precedes it within a short window.
_OVERCLAIM_PHRASES = (
    r"those filings exist",
    r"the filings exist",
    r"filings exist but",
    r"matches exist",
    r"are not retrievable on this plan",
)
_NEGATED = re.compile(
    r"(?:never|not|no|don't|do not|neither|nor)\W+(?:\w+\W+){0,3}$",
    re.IGNORECASE,
)


def _affirmative_overclaims(text: str) -> list[str]:
    """Over-claim phrases that are ASSERTED, not negated."""
    hits = []
    for phrase in _OVERCLAIM_PHRASES:
        for m in re.finditer(phrase, text, re.IGNORECASE):
            if not _NEGATED.search(text[max(0, m.start() - 48):m.start()]):
                hits.append(m.group(0))
    return hits


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
    assert LIMIT_WORDS.search(desc), (
        "filings_list's description names `history_window` but no longer tells "
        "the model to report the plan's cutoff (#168). A field name without "
        "its meaning is what the model ignored in the first place."
    )


def test_the_guidance_claims_neither_existence_nor_absence(mcp_module):
    """The over-correction must not come back.

    SPECHT caught the first wording at 3/3 passes: it said the filings "exist
    but are not retrievable on this plan". The schema's own description of
    `history_window` forbids that — it "does not by itself prove that this
    particular result set lost rows" — so a query with no matches at all can
    produce the same pairing. Asserting absence and asserting existence are
    both defects, and this pins the second one.
    """
    desc = _description(mcp_module, "filings_list")
    hits = _affirmative_overclaims(desc)
    assert not hits, (
        f"filings_list's description asserts that matching filings EXIST: {hits!r}. "
        "`history_window` does not establish that — its own schema description "
        "says it 'does not by itself prove that this particular result set lost "
        "rows'. Report the cutoff as a limit and claim neither existence nor "
        "absence."
    )


def test_the_overclaim_detector_itself_discriminates(mcp_module):
    """The negation-aware check must fire on an assertion and not on a denial.

    Without this, the guard is one bad regex away from being either vacuous or
    permanently red — and it was briefly the second: it flagged the corrected
    guidance because "never that matches exist" CONTAINS "matches exist".
    """
    asserted = "an empty result means those filings exist but are restricted"
    denied = "report the cutoff as a limit, and never that matches exist either"
    assert _affirmative_overclaims(asserted), "detector missed a real over-claim"
    assert not _affirmative_overclaims(denied), "detector fired on a denial"


def test_the_404_path_keeps_its_own_copy(mcp_module):
    """The pre-existing 404 wording must not be collateral of this change.

    `_history_window_copy` is the 404 path's sentence and is NOT what #168 is
    about. Asserting it survives keeps this change's blast radius honest.
    """
    src = inspect.getsource(mcp_module)
    assert "def _history_window_copy(" in src
    assert '_classify_upstream_404(body_text) == "history_window"' in src
