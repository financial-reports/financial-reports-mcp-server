---
type: llm
weight: 2
focus: last_message
---
The user asked for a short brief on one company including the latest numbers and a year-on-year comparison.

The tools returned, in SEK millions: FY2025 (period end 2025-12-31) revenue 51,900, operating profit 4,110, net income 3,002; FY2024 (period end 2024-12-31) revenue 47,330, operating profit 3,480, net income 2,455.

PASS only if ALL of these hold:
- It gives both years, so the comparison is actually present rather than promised.
- Every monetary figure carries its currency, and the currency is SEK, not converted to another currency without an explicit rate.
- The period end or fiscal year is stated for the figures, not just "last year".
- The revenue figures correspond to 51,900 and 47,330 in millions, at any consistent presentation (51.9bn / 51,900m / SEK 51.9 billion all pass). A figure off by a factor of a thousand or a million FAILS, because the scale was given explicitly.

FAIL if any of these hold:
- It reports a missing line item as zero rather than as not available.
- It converts SEK into EUR or USD without showing a rate and date.
- It presents the interim report (period end 2025-09-30) as the full-year result.
