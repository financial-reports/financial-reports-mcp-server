# Eval suite for the FinancialFilings plugin

Four cases, one per job-shaped skill, run with `claude plugin eval`. Each case asks
a question in the phrasing a user would actually type, and grades both the ANSWER
and the STEPS taken to reach it.

## Running it

```bash
claude plugin eval plugins/financialfilings --runs 3 --judge-model sonnet
```

`--ablation with-without` is the default when the plugin resolves, so every case
also runs a no-plugin baseline arm and reports the delta. The delta is the number
worth reading: a case that scores well in both arms is not evidence the skill did
anything.

Results land in `evals/results/<timestamp>/` (gitignored), including a
self-contained `report.html` with per-run grader verdicts and the judge's evidence.

## What each case tests

| Case | The behaviour it exists to catch |
|---|---|
| `find-a-section` | Searching inside the filing instead of downloading it, and quoting the real passage with its vintage |
| `company-brief` | Taking the structured financials path rather than reading numbers out of the document, and carrying currency and period end on every figure |
| `peer-comparison` | Batch-resolving, SAYING SO when a requested company does not resolve, and never mixing currencies into one column |
| `industry-screen` | Applying `listing_status=LISTED`, naming the ISIC class, and not presenting one page as the whole industry |

Every case carries a `tool_used: Skill` grader. It is a plugin-fired indicator
rather than part of the score: it answers "did the skill trigger on this phrasing",
which is a different question from "was the answer good" and the one that fails
first when a `description` is wrong.

## Mocks, and two traps they cost us

The MCP server needs OAuth, so these cases cannot call it. `mocks/financialfilings/`
stands in, and `_tools.json` is a saved `tools/list` so the mocked tools carry their
REAL descriptions and input schemas instead of a permissive placeholder.

**`_tools.json` is generated from the shipped module, not written by hand.** The
first version typed every parameter as a string. The model dutifully passed
`filing_id: "998101"`, the mock's `expect: filing_id: number` guard aborted the run,
and three of four cases scored 0.00 in both arms. ⇒ Three cases failing identically
is the shape of a broken instrument, not of three broken skills, and the abort
reason is in the JSON under `mocks.aborted`.

**A fixed mock returns the same body for every input, which a comparison case cannot
survive.** The suite's `companies_financials_retrieve` mock answers in SEK whatever
company id it is given. In `peer-comparison` that handed a German, EUR-reporting
company the Swedish company's figures to the digit. The model under test noticed,
re-ran the call with an explicit fiscal year to check, concluded it was a source
data error and refused to tabulate numbers it did not believe: exactly what the
skill's currency discipline tells it to do, and the rubric marked it wrong. The
case now has its own `type: agent` mock that varies by id. ⇒ **When a rubric fails
while `tool_used: Skill` passes, suspect the fixture and the judge before the
skill.**

## Cost

A 4-case run at `--runs 3` with a Sonnet judge is a couple of dollars and about ten
minutes. It is not wired into CI: that would spend on every plugin PR and needs a
model credential in the CI environment, which is a spend decision rather than an
engineering one. Run it by hand before submitting a new plugin version, which is
the cadence that matters, because the directory review is the slow step anyway.
