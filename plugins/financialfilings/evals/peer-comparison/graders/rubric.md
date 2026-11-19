---
type: llm
weight: 3
focus: last_message
---
The user asked for FOUR companies compared on revenue and operating profit for their latest full year. The batch resolve returned one row per company with a status, and the four statuses are the point of this case:

- Nordwind Energi AB: `matched`. Sweden, SEK, period end 2025-12-31. Revenue 51,900m, operating profit 4,110m.
- Helios Turbinen GmbH: `matched`. Germany, EUR, period end 2025-08-31. Revenue 2,980m, and NO operating-profit line item.
- Atlas Rotor: `ambiguous`. Two listed candidates were returned, a Danish and a Finnish entity, with no company resolved.
- Brightwater Marine: `not_covered`.

PASS only if ALL of these hold:
- Revenue is given for the two matched companies, each labelled with its own currency (SEK for Nordwind, EUR for Helios).
- Atlas Rotor is reported as AMBIGUOUS rather than silently dropped or silently resolved to one of the two candidates. Naming the candidates or asking which is meant both pass; picking one without saying so FAILS.
- Brightwater Marine is reported as not covered.
- Helios's missing operating profit is shown as not available or left out with a note. Reporting it as 0, or computing a margin for Helios from another number, FAILS.

Judge the SUBSTANCE, not the layout. Table, list or prose all pass equally; column order, number formatting (51,900m / 51.9bn / SEK 51.9 billion) and heading wording are irrelevant. Do not fail an answer for omitting something this rubric does not require.

FAIL if any of these hold:
- SEK and EUR figures are added, averaged or ranked against each other as one unit, or converted with no rate and date shown.
- Atlas Rotor is presented as a resolved company with figures.
- It claims all four were compared.
