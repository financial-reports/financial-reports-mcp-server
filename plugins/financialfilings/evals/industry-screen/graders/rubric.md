---
type: llm
weight: 2
focus: last_message
---
The user asked which listed companies are in the same industry as a named company, restricted to Europe. The screen matches 9 companies in total (all listed, all European) and returns them 3 per page by default, so the first call shows 3 of 9.

PASS only if ALL of these hold:
- It names the industry it screened on by ISIC class CODE (2819), so the screen is
  reproducible. Giving the code alone passes. If it also gives a class name, the
  name must be the right one: 2819 is "manufacture of other general-purpose
  machinery" (its group 281 is general-purpose; "special-purpose" is 2829). A
  plausible but WRONG class name FAILS, because it makes a
  reproducible screen look like a different one.
- It lists the peer companies the screen returned. ⚠ EXCLUDING the reference company itself passes: the user asked for companies in the same industry AS Nordwind, so leaving Nordwind out of its own peer list is a reasonable reading. Listing it passes too. Do not fail on that choice either way.
- It does not present a partial page as the whole result. Either it lists all 9 (by paging or a larger `page_size`), or it states the total of 9, says this is the first page, or otherwise makes clear the rows shown are not the complete set.

Paging to see every row is GOOD, not required. Ending with an offer to narrow or extend the screen is fine.

FAIL if any of these hold:
- It presents fewer than 9 companies as the full list of companies in the industry.
- It describes the industry in GICS or NAICS terms without saying the mapping is approximate.
- It invents companies that were not returned.
