---
name: industry-screen
description: Use when the user wants a list of companies rather than facts about a named one: "which companies", "screen for", "shortlist", "list the listed companies in", "who else is in this industry", "find companies in <sector> in <country>", or peers of a company they name. Screens by ISIC sub-industry and country with the listing filter that keeps dead registrations out, then optionally filters the shortlist on financials.
---

# Industry screen

Produces a list of companies, which is a different job from answering about one.
Two things decide whether the output is usable: getting the right ISIC class, and
excluding companies that no longer trade.

## When to use this rather than another skill

- "Which companies are in X" or "who are the peers of Y": **here**.
- The user already named the companies: **peer-comparison**.
- One company: **company-brief**.

## The sequence

1. **Get the 4-digit ISIC class.** There is no `isic_class` parameter. The
   reliable route is to resolve a company you know is in the industry and read
   its `sub_industry_code`. `get_fr_industry_classification_isic` gives the
   taxonomy when you need to pick a class by name.
2. **Screen.**
   `companies_list?sub_industry=<4-digit code>&countries=<ISO2>&listing_status=LISTED`
3. **Filter on financials** only for the shortlist, with
   `companies_financials_retrieve` per company. Screen first, then measure, not
   the other way round.
4. **Hand a comparison off** to the peer-comparison skill once the list is short.

## `listing_status=LISTED` is required, not optional

Without it the result is dominated by long-dead registrations. Measured on US
ISIC 2619: **392 companies unfiltered, 81 with the filter.** The unfiltered list
sorts alphabetically into companies delisted in the 1990s, so the first page
looks plausible and is mostly useless.

If the user genuinely wants former constituents, pass the status deliberately and
say that is what you did.

## ISIC is not GICS and not NAICS

If the user asks in GICS or NAICS terms, say the mapping is approximate before
giving results. A screen that silently answers a different taxonomy's question
produces a list the user cannot reconcile with their own.

Neighbouring ISIC classes often split an industry a user thinks of as one. When
the obvious class returns too few companies, check the adjacent classes and say
which ones you included.

## Reporting the screen

Always state, above the list:

- The ISIC class used, by code **and** name. ⚠ **Neither the screen response nor
  the ISIC guide gives you the name.** `companies_list` rows carry
  `sub_industry_code` and no name, and `get_fr_industry_classification_isic`
  states plainly that the hierarchy endpoints are not exposed as tools, so there
  is no code-lookup call: it has the 22 SECTION names and the screening recipe,
  not the 463 class names.
  ⇒ **The name comes from `companies_retrieve` on a company in the class**, whose
  `sub_industry` carries both code and name. You have already resolved a peer to
  get the code, so retrieve that peer. **If you cannot, give the code alone and
  say the name is unavailable**, and never supply one from memory, because a
  plausible-sounding wrong class name makes a reproducible screen look like a
  different one, which is worse than no name.
- The country filter, or that there was none.
- That the listing filter was applied.
- The count, and whether it is the whole result or the first page.

A screen without its criteria is not reproducible, and the user cannot tell a
small industry from a narrow filter.

## Do not characterise rows you have not seen

When the count says 81 and you hold one page, describe the page and state the
count. **Do not guess what the other rows are**, such as "many are probably unrelated",
"most are small caps", "the rest are likely holding companies". A guess about
unseen rows reads as a finding about the industry and is not one. If the user
needs to know, page further or narrow the filter and look.

## Pagination

Do not page past the first two pages hunting for a company you expect. Refine the
class or the country instead. If the user needs the full list of a large class,
say how many there are and ask before pulling it all, because each page costs a
call.

## Pitfalls

- **Do not screen without `listing_status`.** See the 392-versus-81 measurement.
- **Do not infer the class from the company name.** Resolve a known member and
  read its code.
- **Do not present a page as the industry.** Say the count.
- **Skip rows whose `processing_status` is present and not `COMPLETED`** when you
  go on to read filing content. A null value means unknown, so do not gate on it.
- **A small result is not necessarily a small industry.** It may be a narrow
  class or a country filter. Check an adjacent class before telling the user the
  industry is thin.
