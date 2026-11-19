---
type: llm
weight: 2
focus: last_message
---
The user asked which listed companies are in the same industry as a named company, restricted to Europe. The screen returned a page of 3 companies out of a reported total count of 81.

PASS only if ALL of these hold:
- It names the industry it screened on, by ISIC class code (2819) or by the class name (manufacture of other special-purpose machinery), so the screen is reproducible.
- It lists the companies it got back.
- It makes clear that the 3 shown are not the whole result: it states the total of 81, or says this is the first page, or otherwise does not present 3 as the complete set.

FAIL if any of these hold:
- It presents the 3 companies as the full list of companies in the industry when the tool reported 81.
- It describes the industry in GICS or NAICS terms without saying the mapping is approximate.
- It invents companies that were not returned.
