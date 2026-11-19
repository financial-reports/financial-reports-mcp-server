---
type: llm
weight: 2
focus: last_message
---
The user asked which listed companies are in the same industry as a named company, restricted to Europe. The screen returned a page of 3 companies out of a reported total count of 81.

PASS only if ALL of these hold:
- It names the industry it screened on by ISIC class CODE (2819), so the screen is
  reproducible. Giving the code alone passes. If it also gives a class name, the
  name must be the right one: 2819 is "manufacture of other special-purpose
  machinery". A plausible but WRONG class name FAILS, because it makes a
  reproducible screen look like a different one.
- It lists the peer companies the screen returned. ⚠ EXCLUDING the reference company itself passes: the user asked for companies in the same industry AS Nordwind, so leaving Nordwind out of its own peer list is a reasonable reading. Listing it passes too. Do not fail on that choice either way.
- It makes clear that the 3 shown are not the whole result: it states the total of 81, or says this is the first page, or otherwise does not present 3 as the complete set.

Noticing that the result count did not change when the country filter was applied, and saying so, is GOOD. The fixture returns a fixed count, and an answer that catches it and discloses the uncertainty is behaving better than one that does not. Never fail an answer for that.

FAIL if any of these hold:
- It presents the 3 companies as the full list of companies in the industry when the tool reported 81.
- It describes the industry in GICS or NAICS terms without saying the mapping is approximate.
- It invents companies that were not returned.
