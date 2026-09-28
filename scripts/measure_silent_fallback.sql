-- Silent-fallback metric (#109): how often an agent takes a structured
-- `companies_financials_retrieve` answer and then reads a filing body for the
-- SAME company anyway.
--
-- Why: #109 showed capable agents route around a wrong financials figure by
-- reading the annual report, and report the right answer without mentioning
-- the defect. Final-answer evals and error telemetry cannot see that. This
-- query makes the repair visible in the data we already log.
--
-- Run read-only against prod (users_mcptoolevent lives in the web DB):
--   cloud-sql-proxy + the alex_ro login, see the umbrella CLAUDE.md.
--
-- Columns per mcp_client_name (ROLLUP row = all clients):
--   financials_ok          successful, non-empty financials calls
--   same_company_fallback  followed within 30 min by the same user reading a
--                          filing of the same company        <- the tell
--   other_company_read     followed by a read of a DIFFERENT company <- baseline
--
-- Read same_company_fallback against other_company_read, never alone: agents
-- also read filings for context, and this query cannot tell a repair from a
-- legitimate follow-up read. A rise in the gap is the signal. The e2e probe
-- client (fr-e2e-probe) never falls back and should stay at 0 as a control.
--
-- Measured 2026-09-28, 30-day window: 2,606 / 471 (18.1%) / 278 (10.7%).
with f as (
  select id, user_id, timestamp ts, (arguments->>'id')::bigint company_id, mcp_client_name
  from users_mcptoolevent
  where name='companies_financials_retrieve' and status='ok' and has_data
    and timestamp > now() - interval '30 days' and user_id is not null
    and arguments ? 'id' and (arguments->>'id') ~ '^[0-9]+$'
), m as (
  select e.user_id, e.timestamp ts, fl.company_id
  from users_mcptoolevent e join filings_filing fl on fl.id = (e.arguments->>'filing_id')::bigint
  where e.name='filings_markdown_retrieve' and e.timestamp > now() - interval '30 days'
    and e.arguments ? 'filing_id' and (e.arguments->>'filing_id') ~ '^[0-9]+$'
)
select f.mcp_client_name,
  count(*) financials_ok,
  count(*) filter (where exists (select 1 from m where m.user_id=f.user_id and m.company_id=f.company_id
                                  and m.ts > f.ts and m.ts <= f.ts + interval '30 minutes')) same_company_fallback,
  count(*) filter (where exists (select 1 from m where m.user_id=f.user_id and m.company_id<>f.company_id
                                  and m.ts > f.ts and m.ts <= f.ts + interval '30 minutes')) other_company_read
from f group by rollup(f.mcp_client_name) order by 2 desc;
