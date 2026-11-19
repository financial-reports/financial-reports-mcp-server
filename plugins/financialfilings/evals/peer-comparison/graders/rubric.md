---
type: llm
weight: 3
focus: last_message
---
The user asked for FOUR companies, given as plain names with no tickers or ISINs, compared on revenue and operating profit for their latest full year.

What a name search returns here:
- "Nordwind Energi" -> one company: Nordwind Energi AB, Sweden, SEK. Revenue 51,900m, operating profit 4,110m, period end 2025-12-31.
- "Helios Turbinen" -> one company: Helios Turbinen GmbH, Germany, EUR. Revenue 2,980m, NO operating-profit line item, period end 2025-08-31.
- "Atlas Rotor" -> TWO plausible listed companies, a Danish and a Finnish entity. Genuinely ambiguous.
- "Brightwater Marine" -> nothing. Not covered.

PASS only if ALL of these hold:
- Revenue is given for Nordwind and Helios, each labelled with its own currency (SEK and EUR respectively).
- It does NOT stall the whole comparison waiting for the user. Two of the four names have a single clear hit, so a correct answer compares those and reports the other two. Refusing to answer anything until the user disambiguates Atlas Rotor FAILS.
- Atlas Rotor is reported as ambiguous between two companies, or its two candidates are named. Silently picking one FAILS.
- Brightwater Marine is reported as not found or not covered.
- Helios's missing operating profit is shown as not available or left out with a note. Reporting it as 0, or computing a margin for Helios from another number, FAILS.

Judge the SUBSTANCE, not the layout. Table, list or prose pass equally; column order, number formatting and heading wording are irrelevant. Do not fail an answer for omitting something this rubric does not require.

FAIL if any of these hold:
- SEK and EUR figures are added, averaged or ranked as one unit, or converted with no rate and date shown.
- Atlas Rotor appears with figures as though it had resolved.
- It claims all four were compared.
